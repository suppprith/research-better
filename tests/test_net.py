"""The HTTP layer: caching, politeness, backoff, and offline mode.

Nothing here reaches the network. Every test drives a stub transport or a warm
cache, which is also how the whole suite runs in CI.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from research_better import __version__
from research_better.net import (
    CONTACT_ENVIRONMENT_VARIABLE,
    CacheEntry,
    HttpCache,
    OfflineCacheMissError,
    PoliteClient,
    SourceUnavailableError,
    TokenBucket,
    cache_key,
    load_limits,
    normalize_request,
    resolve_contact,
    user_agent,
)
from research_better.net.limits import LimitsError, parse_limits


def stub_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def json_handler(payload: dict, status: int = 200):
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload, request=request)

    return handle


@pytest.fixture
def cache(tmp_path: Path) -> HttpCache:
    return HttpCache(tmp_path / "cache")


# Request normalization ----------------------------------------------------


def test_parameter_order_does_not_change_the_key() -> None:
    first = cache_key("GET", "https://api.example.org/works", {"a": "1", "b": "2"})
    second = cache_key("GET", "https://api.example.org/works", {"b": "2", "a": "1"})
    # Caching these separately would double the load on somebody else's server
    # for no benefit at all.
    assert first == second


def test_host_case_does_not_change_the_key() -> None:
    assert cache_key("GET", "https://API.Example.org/w") == cache_key(
        "GET", "https://api.example.org/w"
    )


def test_query_string_and_params_merge() -> None:
    assert normalize_request("GET", "https://x.org/w?a=1", {"b": "2"}) == normalize_request(
        "GET", "https://x.org/w", {"a": "1", "b": "2"}
    )


def test_a_different_path_is_a_different_key() -> None:
    assert cache_key("GET", "https://x.org/a") != cache_key("GET", "https://x.org/b")


# Cache --------------------------------------------------------------------


def test_a_cached_entry_round_trips(cache: HttpCache) -> None:
    entry = CacheEntry(
        key="k",
        request="GET https://x.org/w?",
        status=200,
        headers={"content-type": "application/json"},
        body=b'{"ok": true}',
        stored_at=time.time(),
        source="crossref",
    )
    cache.write(entry)
    read_back = cache.read("crossref", "k", ttl_seconds=60)
    assert read_back is not None
    assert read_back.text == '{"ok": true}'
    assert read_back.status == 200


def test_a_text_body_stays_readable_on_disk(cache: HttpCache) -> None:
    cache.write(CacheEntry("k", "r", 200, {}, b'{"title": "BM25"}', time.time(), "crossref"))
    raw = json.loads(cache.path_for("crossref", "k").read_text(encoding="utf-8"))
    # When a verdict looks wrong the first question is what the API returned,
    # and the answer should be a file somebody can open.
    assert raw["body_encoding"] == "utf-8"
    assert "BM25" in raw["body"]


def test_a_binary_body_survives_as_base64(cache: HttpCache) -> None:
    pdf = b"%PDF-1.4\n\xff\xfe binary"
    cache.write(CacheEntry("k", "r", 200, {}, pdf, time.time(), "arxiv"))
    assert cache.read("arxiv", "k", 60).body == pdf  # type: ignore[union-attr]


def test_an_expired_entry_is_not_returned(cache: HttpCache) -> None:
    cache.write(CacheEntry("k", "r", 200, {}, b"old", time.time() - 100, "crossref"))
    assert cache.read("crossref", "k", ttl_seconds=10) is None
    assert cache.read("crossref", "k", ttl_seconds=1000) is not None


def test_recorded_fixtures_never_expire(tmp_path: Path) -> None:
    frozen = HttpCache(tmp_path / "fixtures", ignore_ttl=True)
    frozen.write(CacheEntry("k", "r", 200, {}, b"old", 0.0, "crossref"))
    # A fixture that expires turns a green suite red for reasons that have
    # nothing to do with the code.
    assert frozen.read("crossref", "k", ttl_seconds=1) is not None


def test_a_corrupt_entry_is_treated_as_absent(cache: HttpCache) -> None:
    cache.path_for("crossref", "k").parent.mkdir(parents=True, exist_ok=True)
    cache.path_for("crossref", "k").write_text("{not json", encoding="utf-8")
    assert cache.read("crossref", "k", 60) is None


# Politeness ---------------------------------------------------------------


def test_every_request_identifies_the_tool(cache: HttpCache) -> None:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, json={}, request=request)

    with PoliteClient(cache, transport=stub_transport(handle)) as client:
        client.get("crossref", "https://api.crossref.org/works/10.1/x")

    assert __version__ in seen[0]
    assert "research-better" in seen[0]


def test_a_contact_moves_the_caller_into_the_polite_pool() -> None:
    assert user_agent("me@example.org").endswith("mailto:me@example.org")
    assert "mailto" not in user_agent(None)


def test_the_contact_can_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONTACT_ENVIRONMENT_VARIABLE, "me@example.org")
    assert resolve_contact() == "me@example.org"
    assert resolve_contact("explicit@example.org") == "explicit@example.org"


def test_the_polite_parameter_is_added_where_the_source_wants_one(
    cache: HttpCache,
) -> None:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={}, request=request)

    with PoliteClient(cache, contact="me@example.org", transport=stub_transport(handle)) as client:
        client.get("openalex", "https://api.openalex.org/works")

    assert "mailto=me%40example.org" in seen[0]


def test_defaults_sit_below_what_each_source_documents() -> None:
    limits = load_limits()
    # Being a bad client gets the tool blocked and its users with it, so the
    # configured rate is deliberately under the published ceiling.
    assert limits.for_source("openalex").requests_per_second <= 10
    assert limits.for_source("arxiv").requests_per_second <= 0.34
    assert limits.for_source("semantic_scholar").requests_per_second <= 0.34
    for source in limits.sources.values():
        assert source.documented, f"{source.name} does not record what it documents"


# Rate limiting ------------------------------------------------------------


def test_a_bucket_allows_its_burst_then_waits() -> None:
    slept: list[float] = []
    bucket = TokenBucket(rate=10.0, capacity=2)

    assert bucket.acquire(sleep=slept.append) == 0.0
    assert bucket.acquire(sleep=slept.append) == 0.0
    waited = bucket.acquire(sleep=slept.append)

    assert waited > 0.0
    assert slept, "the third request should have waited for a token"


def test_buckets_are_per_source(cache: HttpCache) -> None:
    with PoliteClient(cache, transport=stub_transport(json_handler({}))) as client:
        assert client.buckets.for_source("crossref") is not client.buckets.for_source("arxiv")
        assert client.buckets.for_source("crossref") is client.buckets.for_source("crossref")


def test_an_unconfigured_source_is_refused(cache: HttpCache) -> None:
    with (
        PoliteClient(cache, transport=stub_transport(json_handler({}))) as client,
        pytest.raises(LimitsError, match="no limits configured"),
    ):
        client.get("made_up_source", "https://x.org/w")


# Retries ------------------------------------------------------------------


def test_a_retryable_status_is_retried_then_reported(
    cache: HttpCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    attempts = {"count": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(503, request=request)

    with (
        PoliteClient(cache, transport=stub_transport(handle)) as client,
        pytest.raises(SourceUnavailableError, match="crossref is unavailable"),
    ):
        client.get("crossref", "https://api.crossref.org/works")

    assert attempts["count"] == 4


def test_a_recovering_source_succeeds_on_a_later_attempt(
    cache: HttpCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    attempts = {"count": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(429, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    with PoliteClient(cache, transport=stub_transport(handle)) as client:
        assert client.get("crossref", "https://api.crossref.org/works").json() == {"ok": True}


def test_retry_after_is_respected(cache: HttpCache) -> None:
    with PoliteClient(cache, transport=stub_transport(json_handler({}))) as client:
        response = httpx.Response(429, headers={"retry-after": "7"})
        assert client._backoff(1, response) == 7.0


def test_backoff_is_jittered(cache: HttpCache) -> None:
    with PoliteClient(cache, transport=stub_transport(json_handler({}))) as client:
        waits = {client._backoff(3, None) for _ in range(20)}
    # Without jitter every retry from every user lands in the same instant
    # after an outage, which is how a recovering service gets knocked over.
    assert len(waits) > 1


def test_a_404_is_not_retried(cache: HttpCache) -> None:
    attempts = {"count": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(404, request=request)

    with PoliteClient(cache, transport=stub_transport(handle)) as client:
        assert client.get("crossref", "https://api.crossref.org/works").status == 404
    assert attempts["count"] == 1


# Cache behaviour through the client ---------------------------------------


def test_a_warm_cache_makes_no_request(cache: HttpCache) -> None:
    handler = json_handler({"title": "BM25"})
    url = "https://api.crossref.org/works/10.1561/1500000019"

    with PoliteClient(cache, transport=stub_transport(handler)) as client:
        client.get("crossref", url)
        assert client.requests_made == 1

    with PoliteClient(cache, transport=stub_transport(handler)) as second:
        response = second.get("crossref", url)
        assert response.from_cache
        assert second.requests_made == 0


def test_refresh_bypasses_a_warm_cache(cache: HttpCache) -> None:
    handler = json_handler({"v": 1})
    url = "https://api.crossref.org/works/x"

    with PoliteClient(cache, transport=stub_transport(handler)) as client:
        client.get("crossref", url)

    with PoliteClient(cache, transport=stub_transport(handler), refresh=True) as second:
        assert not second.get("crossref", url).from_cache
        assert second.requests_made == 1


def test_offline_serves_from_cache(cache: HttpCache) -> None:
    url = "https://api.crossref.org/works/x"
    with PoliteClient(cache, transport=stub_transport(json_handler({"v": 1}))) as client:
        client.get("crossref", url)

    with PoliteClient(cache, offline=True) as offline:
        assert offline.get("crossref", url).from_cache
        assert offline.requests_made == 0


def test_offline_on_a_cold_cache_fails_loudly(cache: HttpCache) -> None:
    with (
        PoliteClient(cache, offline=True) as client,
        pytest.raises(OfflineCacheMissError) as error_info,
    ):
        client.get("crossref", "https://api.crossref.org/works/absent")

    message = str(error_info.value)
    # Returning nothing would show up downstream as a citation that could not
    # be verified, which reads as a finding about the paper.
    assert "Nothing was guessed" in message
    assert "--offline" in message
    assert "--refresh" in message


# Concurrency --------------------------------------------------------------


def test_gather_runs_calls_in_parallel_and_keeps_failures(cache: HttpCache) -> None:
    def good() -> str:
        return "ok"

    def bad() -> str:
        raise SourceUnavailableError("arxiv", "timeout")

    with PoliteClient(cache, transport=stub_transport(json_handler({}))) as client:
        results = client.gather([("openalex", good), ("arxiv", bad)])

    by_source = {name: (value, error) for name, value, error in results}
    # A dead source degrades the answer. It never fails the run.
    assert by_source["openalex"] == ("ok", None)
    assert by_source["arxiv"][0] is None
    assert isinstance(by_source["arxiv"][1], SourceUnavailableError)


def test_in_flight_requests_are_capped(cache: HttpCache) -> None:
    with PoliteClient(cache, transport=stub_transport(json_handler({}))) as client:
        assert client.limits.maximum_in_flight <= 8


# Limits file --------------------------------------------------------------


def test_a_limits_file_with_no_sources_is_an_error() -> None:
    with pytest.raises(LimitsError, match="lists no sources"):
        parse_limits({"cache": {"record_ttl_days": 1}})


def test_cache_lifetimes_reflect_what_changes() -> None:
    limits = load_limits()
    # A resolved DOI says the same thing next year. A search does not.
    assert limits.record_ttl_seconds > limits.search_ttl_seconds
    assert limits.fulltext_ttl_seconds > limits.search_ttl_seconds
