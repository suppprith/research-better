"""Retrieving the text of a cited work.

The route under test is the open-access PDF one. Every other route was covered
where it is used, but this one fetches from a host nobody chose and reads bytes
somebody else's server produced, so what it does when the answer is not a paper
matters as much as what it does when it is.

The PDF served here is the two-column fixture from pdf_fixture.py, padded out
past the length that counts as full text, so a pass over the result is reading
the same extraction the ingest tests pin down.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pdf_fixture import build, build_scanned
from research_better.grounding.fulltext import ABSTRACT, FULL_TEXT, MINIMUM_FULL_TEXT, retrieve
from research_better.net import HttpCache, PoliteClient
from research_better.sources.base import Work

PDF_URL = "https://repository.example.edu/paper.pdf"

ABSTRACT_TEXT = "We compare sparse and dense retrieval at a fixed budget."


def work(url: str = PDF_URL, abstract: str = ABSTRACT_TEXT) -> Work:
    return Work(
        title="Sparse Retrieval at Equal Cost",
        authors=("Robertson, S.",),
        year=2026,
        sources=("openalex",),
        abstract=abstract,
        open_access_url=url,
    )


def serving(body: bytes, status: int = 200) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, request=request)

    return httpx.MockTransport(handle)


@pytest.fixture
def client(tmp_path: Path):
    def make(transport: httpx.MockTransport) -> PoliteClient:
        return PoliteClient(HttpCache(tmp_path / "cache"), transport=transport)

    return make


@pytest.fixture(scope="module")
def paper(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    """A real paper, long enough to count as full text."""
    target = build(tmp_path_factory.mktemp("oa") / "paper.pdf", body_pages=8)
    return target.read_bytes()


# The route works ------------------------------------------------------------


def test_an_open_access_pdf_is_read_as_full_text(client, paper: bytes) -> None:
    source = retrieve(client(serving(paper)), work())
    assert source.kind == FULL_TEXT
    assert source.is_full_text
    assert "holds the retrieval budget fixed" in source.text


def test_the_reading_order_comes_from_the_ingest_adapter(client, paper: bytes) -> None:
    # The same extraction the ingest tests pin down, not a second one that
    # could drift from it. Naive extraction interleaves the two columns.
    text = retrieve(client(serving(paper)), work()).text
    assert text.index("Dense encoders are reported") < text.index("The corpus is indexed")


def test_a_table_row_is_not_offered_as_a_passage(client, paper: bytes) -> None:
    # A matcher handed a table row quotes it back as though the author had
    # written it as a sentence.
    assert "BM25+QE 0.71 1.0" not in retrieve(client(serving(paper)), work()).text


def test_the_note_says_where_the_text_came_from(client, paper: bytes) -> None:
    assert "open-access PDF" in retrieve(client(serving(paper)), work()).note


def test_the_pdf_is_cached_rather_than_fetched_twice(client, paper: bytes, tmp_path: Path) -> None:
    warm = client(serving(paper))
    retrieve(warm, work())
    before = warm.requests_made
    retrieve(warm, work())
    assert warm.requests_made == before, "a full text is large and stable, so it is kept"


# The route fails honestly ---------------------------------------------------


def test_a_landing_page_is_not_read_as_a_paper(client) -> None:
    # A repository that has moved the file answers with HTML and a 200.
    source = retrieve(client(serving(b"<html><body>Download this paper</body></html>")), work())
    assert source.kind == ABSTRACT
    assert "not a PDF" in source.note
    assert "Download this paper" not in source.text


def test_a_missing_file_falls_back_to_the_abstract(client) -> None:
    source = retrieve(client(serving(b"", status=404)), work())
    assert source.kind == ABSTRACT
    assert "404" in source.note


def test_a_scan_is_not_full_text(client, tmp_path: Path) -> None:
    scanned = build_scanned(tmp_path / "scan.pdf").read_bytes()
    source = retrieve(client(serving(scanned)), work())
    # Labelling this full text is what turns "nothing was read" into "the
    # source does not say it".
    assert source.kind == ABSTRACT
    assert "too little text" in source.note


def test_a_corrupt_file_is_not_fatal(client) -> None:
    source = retrieve(client(serving(b"%PDF-1.4 and then nothing that parses")), work())
    assert source.kind == ABSTRACT
    assert "could not be parsed" in source.note


def test_an_offline_miss_falls_back_rather_than_raising(tmp_path: Path, paper: bytes) -> None:
    offline = PoliteClient(HttpCache(tmp_path / "cache"), offline=True, transport=serving(paper))
    source = retrieve(offline, work())
    # Loud everywhere else, because silence would read as a finding about the
    # paper. It cannot here: the fallback is labelled an abstract, and a claim
    # checked against an abstract comes back unchecked rather than unsupported.
    assert source.kind == ABSTRACT
    assert "offline" in source.note
    assert offline.requests_made == 0


def test_a_work_with_no_full_text_and_no_abstract_reports_none(client, paper: bytes) -> None:
    source = retrieve(client(serving(b"", status=404)), work(abstract=""))
    assert not source.available


def test_the_threshold_is_the_same_one_the_arxiv_route_uses() -> None:
    # Two thresholds would mean the same paper counted as full text from one
    # host and not from another.
    assert MINIMUM_FULL_TEXT == 2000
