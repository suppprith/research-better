"""Source adapters, driven by responses recorded from the real APIs.

Nothing here reaches the network. `tests/fixtures/http/` holds what OpenAlex,
Crossref, Semantic Scholar, and arXiv actually returned, and the client runs
offline so an unrecorded request raises rather than quietly going out.

Refresh with `python scripts/record_fixtures.py --refresh` when a source
changes shape. The weekly job in network.yml is what notices that it did.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_better.net import HttpCache, OfflineCacheMissError, PoliteClient
from research_better.sources import (
    ArxivAdapter,
    CrossrefAdapter,
    OpenAlexAdapter,
    SearchResult,
    SemanticScholarAdapter,
    Work,
    deduplicate,
    default_adapters,
    find_by_doi,
    find_by_title,
    rank,
    search,
)
from research_better.sources.base import normalize_arxiv, normalize_doi, normalize_title, surname
from research_better.sources.merge import RankingWeights, text_relevance

FIXTURE_HTTP = Path(__file__).parent / "fixtures" / "http"

REAL_DOI = "10.1561/1500000019"
RETRACTED_DOI = "10.1016/S0140-6736(97)11096-0"
DENSE_TITLE = "Dense Passage Retrieval for Open-Domain Question Answering"
INVENTED_TITLE = "Adaptive Query Expansion Under Drift Ferreira Osei"


@pytest.fixture
def client():
    cache = HttpCache(FIXTURE_HTTP, ignore_ttl=True)
    with PoliteClient(cache, offline=True) as offline_client:
        yield offline_client


@pytest.fixture
def web_adapters():
    return [OpenAlexAdapter(), CrossrefAdapter(), ArxivAdapter()]


# Normalization ------------------------------------------------------------


def test_a_doi_is_recognised_however_it_was_written() -> None:
    for written in (
        "10.1561/1500000019",
        "https://doi.org/10.1561/1500000019",
        "http://dx.doi.org/10.1561/1500000019",
        "doi: 10.1561/1500000019",
        "10.1561/1500000019.",
    ):
        assert normalize_doi(written) == "10.1561/1500000019"


def test_an_arxiv_version_suffix_is_dropped() -> None:
    # v1 and v3 of a preprint are the same work. Keeping them apart would
    # defeat the dedup that exists to collapse a preprint with its published
    # version.
    assert normalize_arxiv("http://arxiv.org/abs/2004.04906v3") == "2004.04906"
    assert normalize_arxiv("arXiv:2004.04906") == "2004.04906"


def test_title_normalization_ignores_what_a_librarian_would() -> None:
    assert normalize_title("The Probabilistic Relevance Framework: BM25 and Beyond") == (
        "the probabilistic relevance framework bm25 and beyond"
    )
    assert normalize_title("RETRACTED: Ileal-lymphoid hyperplasia") == "ileal lymphoid hyperplasia"
    assert normalize_title("Naïve Bayes") == "naive bayes"


def test_surname_handles_both_name_orders() -> None:
    assert surname("Robertson, Stephen") == "robertson"
    assert surname("Stephen Robertson") == "robertson"


# Adapters against recorded responses --------------------------------------


def test_openalex_parses_a_record(client: PoliteClient) -> None:
    work = OpenAlexAdapter().by_doi(client, REAL_DOI)
    assert work is not None
    assert work.title == "The Probabilistic Relevance Framework: BM25 and Beyond"
    assert work.year == 2009
    assert work.doi == REAL_DOI
    assert work.citation_count > 1000
    assert work.sources == ("openalex",)
    assert "Robertson" in work.authors[0]


def test_openalex_rebuilds_an_abstract_from_its_inverted_index(client: PoliteClient) -> None:
    work = OpenAlexAdapter().by_doi(client, REAL_DOI)
    assert work is not None and work.abstract
    assert "Probabilistic Relevance Framework" in work.abstract


def test_crossref_parses_a_record(client: PoliteClient) -> None:
    work = CrossrefAdapter().by_doi(client, REAL_DOI)
    assert work is not None
    assert work.doi == REAL_DOI
    assert work.venue and "Foundations and Trends" in work.venue
    assert work.authors[0] == "Robertson, Stephen"
    assert work.work_type == "journal-article"


def test_semantic_scholar_parses_a_record(client: PoliteClient) -> None:
    work = SemanticScholarAdapter().by_doi(client, REAL_DOI)
    assert work is not None
    assert work.doi == REAL_DOI
    assert work.sources == ("semantic_scholar",)


def test_arxiv_parses_its_atom_feed(client: PoliteClient) -> None:
    works = ArxivAdapter().by_title(client, DENSE_TITLE)
    assert works
    assert works[0].arxiv_id
    assert works[0].venue == "arXiv"
    assert works[0].work_type == "preprint"


def test_a_malformed_arxiv_feed_yields_nothing_rather_than_raising() -> None:
    from research_better.sources.arxiv import parse_feed

    # A bad day at arXiv is not a reason to fail the run.
    assert parse_feed("<not xml") == []


# Retraction ---------------------------------------------------------------


def test_a_retraction_is_detected_with_its_notice(client: PoliteClient) -> None:
    result = find_by_doi(client, RETRACTED_DOI, adapters=[OpenAlexAdapter(), CrossrefAdapter()])
    work = result.works[0]
    assert work.retracted
    # Naming the notice lets the author go read it, rather than taking the
    # tool's word that a paper was pulled.
    assert work.retraction_doi
    assert work.retraction_date


def test_openalex_reports_retraction_as_a_flag(client: PoliteClient) -> None:
    work = OpenAlexAdapter().by_doi(client, RETRACTED_DOI)
    assert work is not None and work.retracted


# Merging and dedup --------------------------------------------------------


def test_one_doi_merges_into_a_single_record(client: PoliteClient) -> None:
    result = find_by_doi(client, REAL_DOI, adapters=default_adapters())
    assert len(result.works) == 1
    work = result.works[0]
    # Per-source attribution on the record, so a verdict can say where it looked.
    assert set(work.sources) >= {"openalex", "crossref"}


def test_merging_keeps_the_best_field_from_each_source(client: PoliteClient) -> None:
    work = find_by_doi(client, REAL_DOI, adapters=default_adapters()).works[0]
    assert work.venue, "Crossref knows the venue"
    assert work.abstract, "OpenAlex and Semantic Scholar know the abstract"
    assert work.citation_count > 0, "OpenAlex knows the citation count"


def test_a_preprint_and_its_published_version_collapse(client: PoliteClient, web_adapters) -> None:
    result = find_by_title(client, DENSE_TITLE, adapters=web_adapters)
    dense = next(
        w for w in result.works if normalize_title(w.title) == normalize_title(DENSE_TITLE)
    )
    # The same paper appears on arXiv and in the ACL Anthology with different
    # identifiers. Presenting them as two candidates would make every verdict
    # look ambiguous when it is not.
    assert dense.doi and dense.arxiv_id
    assert {"arxiv", "openalex"} <= set(dense.sources)


def test_dedup_matches_on_doi_first() -> None:
    left = Work(title="One title", doi="10.1/x", sources=("openalex",))
    right = Work(title="A completely different title", doi="10.1/x", sources=("crossref",))
    merged = deduplicate([left, right])
    assert len(merged) == 1
    assert merged[0].sources == ("crossref", "openalex")


def test_dedup_matches_on_title_and_author_when_there_is_no_doi() -> None:
    left = Work(title="Dense Passage Retrieval", authors=("Karpukhin, V",), year=2020)
    right = Work(title="dense passage retrieval", authors=("Vladimir Karpukhin",), year=2021)
    # Year is not part of the key. A preprint and its published version differ
    # by a year and are the same work.
    assert len(deduplicate([left, right])) == 1


def test_dedup_keeps_genuinely_different_works_apart() -> None:
    left = Work(title="Dense Passage Retrieval", authors=("Karpukhin, V",))
    right = Work(title="Sparse Passage Retrieval", authors=("Robertson, S",))
    assert len(deduplicate([left, right])) == 2


def test_a_record_becomes_findable_by_an_identifier_a_later_source_supplied() -> None:
    by_title_only = Work(title="A Paper", authors=("Smith, J",), sources=("arxiv",))
    with_doi = Work(title="A Paper", authors=("Smith, J",), doi="10.1/x", sources=("openalex",))
    same_doi = Work(title="Different Wording Entirely", doi="10.1/x", sources=("crossref",))
    assert len(deduplicate([by_title_only, with_doi, same_doi])) == 1


def test_the_earlier_year_survives_a_merge() -> None:
    preprint = Work(title="X", doi="10.1/x", year=2020)
    published = Work(title="X", doi="10.1/x", year=2021)
    assert deduplicate([published, preprint])[0].year == 2020


# Ranking ------------------------------------------------------------------


def test_relevance_rewards_a_title_match() -> None:
    on_title = Work(title="BM25 ranking function")
    in_abstract = Work(title="Something else", abstract="We discuss the BM25 ranking function")
    assert text_relevance("BM25 ranking function", on_title) > text_relevance(
        "BM25 ranking function", in_abstract
    )


def test_an_unrelated_record_scores_low() -> None:
    assert text_relevance("BM25 ranking function", Work(title="Protein folding")) == 0.0


def test_citation_count_breaks_a_tie_but_does_not_decide() -> None:
    famous = Work(title="Protein folding", citation_count=50_000)
    relevant = Work(title="BM25 ranking function", citation_count=3)
    ordered = rank([famous, relevant], "BM25 ranking function", current_year=2026)
    # Without damping the citation signal, every query would return the field's
    # most famous paper.
    assert ordered[0].title == "BM25 ranking function"


def test_weights_are_configurable() -> None:
    older = Work(title="Same words here", year=1990)
    newer = Work(title="Same words here", year=2025)
    recency_only = RankingWeights(relevance=0.0, citations=0.0, recency=1.0)
    assert rank([older, newer], "same words here", 2026, recency_only)[0].year == 2025


def test_search_returns_ranked_deduped_results(client: PoliteClient, web_adapters) -> None:
    result = search(client, "BM25 ranking function", limit=5, adapters=web_adapters)
    assert result.works
    assert len(result.works) <= 5
    assert all(work.sources for work in result.works)
    scores = [work.relevance for work in result.works]
    assert scores == sorted(scores, reverse=True) or len(set(scores)) == 1


# Degrading rather than failing --------------------------------------------


class BrokenAdapter(OpenAlexAdapter):
    name = "openalex"

    def by_title(self, client, title, limit=5):
        raise RuntimeError("source exploded mid-run")

    def search(self, client, query, limit=10):
        raise RuntimeError("source exploded mid-run")


def test_one_dead_source_does_not_fail_the_run(client: PoliteClient) -> None:
    result = find_by_title(
        client, DENSE_TITLE, adapters=[BrokenAdapter(), CrossrefAdapter(), ArxivAdapter()]
    )
    # A citation check that consulted two of three databases is worth having.
    # One that raises because a source died is not.
    assert result.works
    assert "openalex" in result.unavailable
    assert set(result.queried) == {"arxiv", "crossref"}
    assert not result.complete


def test_the_result_says_which_sources_answered(client: PoliteClient, web_adapters) -> None:
    result = find_by_title(client, DENSE_TITLE, adapters=web_adapters)
    note = result.coverage_note()
    # A verdict of "not found" means something different when three sources
    # answered than when one did.
    assert "3 sources" in note
    assert result.complete


def test_the_coverage_note_names_what_could_not_be_reached(client: PoliteClient) -> None:
    result = find_by_title(client, DENSE_TITLE, adapters=[BrokenAdapter(), CrossrefAdapter()])
    assert "Could not reach: openalex" in result.coverage_note()


def test_an_empty_result_serializes_cleanly() -> None:
    payload = SearchResult().to_json()
    assert payload["works"] == []
    assert payload["sources_queried"] == []


# Offline discipline -------------------------------------------------------


def test_an_unrecorded_request_raises_rather_than_going_out(client: PoliteClient) -> None:
    # This is what makes the fixture set a replay layer rather than a cache
    # that silently falls through to the network in CI.
    with pytest.raises(OfflineCacheMissError):
        OpenAlexAdapter().by_doi(client, "10.9999/not-recorded")


def test_the_whole_fixture_suite_makes_no_requests(client: PoliteClient, web_adapters) -> None:
    find_by_doi(client, REAL_DOI, adapters=web_adapters)
    find_by_title(client, DENSE_TITLE, adapters=web_adapters)
    search(client, "BM25 ranking function", adapters=web_adapters)
    assert client.requests_made == 0


def test_a_contact_address_does_not_change_the_cache_key() -> None:
    cache = HttpCache(FIXTURE_HTTP, ignore_ttl=True)
    # A mailto changes which pool serves a request, never what comes back, so
    # two users with different addresses must share one fixture set.
    with PoliteClient(cache, offline=True, contact="someone@else.org") as other:
        assert OpenAlexAdapter().by_doi(other, REAL_DOI) is not None
        assert other.requests_made == 0


# The invented citation ----------------------------------------------------


def test_an_invented_title_finds_nothing_that_matches(client: PoliteClient, web_adapters) -> None:
    result = find_by_title(client, INVENTED_TITLE, adapters=web_adapters)
    matching = [
        work
        for work in result.works
        if normalize_title(work.title) == normalize_title(INVENTED_TITLE)
    ]
    assert matching == []
    # Sources answered, so a later NOT_FOUND verdict is about the record and
    # not about the run.
    assert result.complete
