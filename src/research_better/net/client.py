"""The only thing in this package that touches the network.

Every outbound request goes through here so that politeness is not something
each adapter has to remember. It identifies itself, it waits its turn, it backs
off when told to, it caches what it gets, and in offline mode it does not go out
at all.

Threads rather than asyncio. Four sources queried at once does not need an
event loop, and the sync path keeps the CLI, the library, and the tests from
each needing their own way to run a coroutine.
"""

from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from research_better import __version__
from research_better.errors import ResearchBetterError
from research_better.net.cache import CacheEntry, HttpCache, cache_key, normalize_request
from research_better.net.limits import BucketRegistry, Limits, load_limits

PROJECT_URL = "https://github.com/suppprith/research-better"
CONTACT_ENVIRONMENT_VARIABLE = "RESEARCH_BETTER_CONTACT"

MAXIMUM_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class OfflineCacheMissError(ResearchBetterError):
    """Offline mode needed something the cache does not have.

    Deliberately loud. Returning nothing instead would show up downstream as a
    citation that could not be verified, which reads as a finding about the
    paper rather than a fact about the run.
    """

    def __init__(self, source: str, request: str) -> None:
        self.source = source
        self.request = request
        super().__init__(
            f"offline, and {source} has no cached response for {request}. "
            f"Run once without --offline to populate the cache, or use --refresh "
            f"to replace what is there. Nothing was guessed."
        )


class SourceUnavailableError(ResearchBetterError):
    """A source failed after its retries. Never fatal to a whole run."""

    def __init__(self, source: str, reason: str) -> None:
        self.source = source
        self.reason = reason
        super().__init__(f"{source} is unavailable: {reason}")


@dataclass(frozen=True, slots=True)
class Response:
    source: str
    status: int
    url: str
    text: str
    body: bytes
    from_cache: bool

    def json(self) -> Any:
        import json

        return json.loads(self.text)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def user_agent(contact: str | None = None) -> str:
    """What every request announces itself as.

    The polite pools at Crossref and OpenAlex ask for exactly this: a name, a
    version, and a way to reach whoever is running it. Supplying a contact is
    not a formality, it moves the caller into a faster pool and it means a
    source operator can email rather than block.
    """
    base = f"research-better/{__version__} (+{PROJECT_URL})"
    return f"{base} mailto:{contact}" if contact else base


def resolve_contact(explicit: str | None = None) -> str | None:
    import os

    return explicit or os.environ.get(CONTACT_ENVIRONMENT_VARIABLE) or None


class PoliteClient:
    """A rate-limited, caching, self-identifying HTTP client."""

    def __init__(
        self,
        cache: HttpCache,
        limits: Limits | None = None,
        contact: str | None = None,
        offline: bool = False,
        refresh: bool = False,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.cache = cache
        self.limits = limits or load_limits()
        self.contact = resolve_contact(contact)
        self.offline = offline
        self.refresh = refresh
        self.timeout = timeout
        self.buckets = BucketRegistry(self.limits)
        self._in_flight = threading.Semaphore(self.limits.maximum_in_flight)
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": user_agent(self.contact)},
        )
        self.requests_made = 0
        """Counts real outbound requests. Tests assert this is zero on a warm
        cache, which is the only way to be sure the cache is actually used."""

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # Requests --------------------------------------------------------------

    def get(
        self,
        source: str,
        url: str,
        params: dict[str, str] | None = None,
        ttl_seconds: float | None = None,
    ) -> Response:
        limit = self.limits.for_source(source)
        params = dict(params or {})

        # The cache key is computed before the contact address is attached. A
        # mailto changes which pool serves the request, never what comes back,
        # so keying on it would give every user of a shared fixture set a
        # different key for the same question.
        key = cache_key("GET", url, params)
        request_description = normalize_request("GET", url, params)
        ttl = self.limits.search_ttl_seconds if ttl_seconds is None else ttl_seconds

        if limit.polite_parameter and self.contact:
            params.setdefault(limit.polite_parameter, self.contact)

        if not self.refresh:
            cached = self.cache.read(source, key, ttl)
            if cached is not None:
                return Response(
                    source=source,
                    status=cached.status,
                    url=url,
                    text=cached.text,
                    body=cached.body,
                    from_cache=True,
                )

        if self.offline:
            raise OfflineCacheMissError(source, request_description)

        response = self._fetch(source, url, params)
        self.cache.write(
            CacheEntry(
                key=key,
                request=request_description,
                status=response.status_code,
                headers={"content-type": response.headers.get("content-type", "")},
                body=response.content,
                stored_at=time.time(),
                source=source,
            )
        )
        return Response(
            source=source,
            status=response.status_code,
            url=str(response.url),
            text=response.text,
            body=response.content,
            from_cache=False,
        )

    def _fetch(self, source: str, url: str, params: dict[str, str]) -> httpx.Response:
        last_reason = "unknown"
        for attempt in range(1, MAXIMUM_ATTEMPTS + 1):
            self.buckets.for_source(source).acquire()
            response: httpx.Response | None = None
            with self._in_flight:
                self.requests_made += 1
                try:
                    response = self._client.get(url, params=params)
                except httpx.HTTPError as error:
                    last_reason = f"{type(error).__name__}: {error}"

            if response is not None:
                if response.status_code not in RETRYABLE_STATUS:
                    return response
                last_reason = f"HTTP {response.status_code}"

            if attempt == MAXIMUM_ATTEMPTS:
                break
            time.sleep(self._backoff(attempt, response))

        raise SourceUnavailableError(source, f"{last_reason} after {MAXIMUM_ATTEMPTS} attempts")

    def _backoff(self, attempt: int, response: httpx.Response | None) -> float:
        """Exponential with jitter, and `Retry-After` wins when the server sent one.

        Jitter matters more than it looks. Without it, every retry from every
        user of this tool lands in the same instant after an outage, which is
        how a recovering service gets knocked over again.
        """
        if response is not None:
            header = response.headers.get("retry-after")
            if header:
                try:
                    return min(float(header), BACKOFF_CAP_SECONDS)
                except ValueError:
                    pass
        window = min(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)), BACKOFF_CAP_SECONDS)
        return window * (0.5 + random.random() / 2)

    # Concurrency -----------------------------------------------------------

    def gather(self, calls: list[tuple[str, Any]]) -> list[tuple[str, Any, Exception | None]]:
        """Run per-source calls in parallel, keeping failures rather than raising.

        A slow or dead source degrades the answer. It never fails the run,
        because a citation check that returns three sources' worth of evidence
        is worth more than one that returns an exception.
        """
        results: list[tuple[str, Any, Exception | None]] = []
        with ThreadPoolExecutor(max_workers=max(1, len(calls))) as pool:
            futures = {pool.submit(call): name for name, call in calls}
            for future, name in futures.items():
                try:
                    results.append((name, future.result(), None))
                except Exception as error:
                    results.append((name, None, error))
        return sorted(results, key=lambda row: row[0])


def default_cache(draft: Path) -> HttpCache:
    """The cache that sits beside a draft, inside its artifact directory."""
    from research_better.artifacts import ArtifactStore

    return HttpCache(ArtifactStore(draft).cache)
