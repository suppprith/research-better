"""Citation verification against the fixture bibliography.

The bibliography is built to exercise every verdict: two invented entries, one
real, one real DOI carrying a wrong title, one retracted, one book, one thesis.
The last two matter most. A tool that reports an unindexed thesis as missing
without saying why is making a fabrication insinuation it cannot support, and
authors would be right to stop reading it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_better.findings import Severity, Suggestion
from research_better.grounding import (
    AUTHOR_OVERLAP,
    TITLE_SAME,
    GroundingReport,
    Verdict,
    analyse,
    bibliography,
    parse_entry,
    title_similarity,
    to_findings,
    verify_entry,
)
from research_better.grounding.entries import BibliographyEntry
from research_better.model import Citation, ResolvedWork, Span
from research_better.net import HttpCache, PoliteClient
from research_better.sources import ArxivAdapter, CrossrefAdapter, OpenAlexAdapter

FIXTURE_HTTP = Path(__file__).parent / "fixtures" / "http"


@pytest.fixture
def client():
    with PoliteClient(HttpCache(FIXTURE_HTTP, ignore_ttl=True), offline=True) as offline_client:
        yield offline_client


@pytest.fixture
def adapters():
    return [OpenAlexAdapter(), CrossrefAdapter(), ArxivAdapter()]


@pytest.fixture(scope="module")
def entries(bad_paper):
    return {entry.key: entry for entry in bibliography(bad_paper.citations)}


def check_for(bad_paper, client, adapters, key: str):
    entry = next(e for e in bibliography(bad_paper.citations) if e.key == key)
    return verify_entry(client, entry, adapters)


# Entry parsing ------------------------------------------------------------


def test_an_author_list_is_split_from_the_title(entries) -> None:
    entry = entries["2"]
    # A naive split on ". " turns this entry into one titled "Robertson, S".
    assert entry.authors == ("Robertson, S", "Zaragoza, H")
    assert entry.title == "The Probabilistic Relevance Framework: BM25 and Beyond"


def test_multiple_initials_do_not_merge_two_authors(entries) -> None:
    # "Manning, C. D., Raghavan, P." has commas doing two different jobs.
    assert entries["6"].authors == ("Manning, C. D", "Raghavan, P", "Schutze, H")


def test_a_doi_containing_parentheses_survives(entries) -> None:
    # Elsevier DOIs contain brackets, and a pattern that stops at the first one
    # truncates them into something that resolves nowhere.
    assert entries["5"].doi == "10.1016/s0140-6736(97)11096-0"


def test_a_book_and_a_thesis_are_recognised_as_such(entries) -> None:
    assert entries["6"].kind == "book"
    assert entries["7"].kind == "thesis"
    assert entries["6"].likely_unindexed
    assert entries["7"].likely_unindexed


def test_a_journal_article_is_not_marked_unindexed(entries) -> None:
    assert not entries["2"].likely_unindexed


def test_a_bibtex_backed_entry_is_exact() -> None:
    citation = Citation(
        id="cit-1",
        key="smith2021",
        raw="@article{smith2021} A Survey",
        span=Span(0, 10),
        in_bibliography=True,
        resolved=ResolvedWork(
            doi="10.1/x", title="A Survey of Retrieval", year=2021, authors=("Smith, Jane",)
        ),
    )
    entry = parse_entry(citation)
    # LaTeX papers arrive already structured, and guessing at prose is only the
    # fallback for formats that have no structure to read.
    assert entry.exact
    assert entry.title == "A Survey of Retrieval"
    assert entry.doi == "10.1/x"


def test_an_unreadable_entry_is_reported_as_such(client, adapters) -> None:
    entry = BibliographyEntry(key="9", raw="???")
    check = verify_entry(client, entry, adapters)
    assert check.verdict is Verdict.UNPARSEABLE
    # A malformed entry is a fact about the entry, not about whether the work
    # exists, so nothing was queried.
    assert check.sources_queried == ()
    assert "not that the work is missing" in check.note


# Verdicts -----------------------------------------------------------------


def test_a_real_entry_verifies(bad_paper, client, adapters) -> None:
    check = check_for(bad_paper, client, adapters, "2")
    assert check.verdict is Verdict.VERIFIED
    assert check.title_score == 1.0
    assert check.matched_doi == "10.1561/1500000019"


def test_a_wrong_title_on_a_real_doi_is_caught(bad_paper, client, adapters) -> None:
    check = check_for(bad_paper, client, adapters, "3")
    assert check.verdict is Verdict.TITLE_MISMATCH
    assert check.severity == "high"
    assert check.title_score < TITLE_SAME
    assert check.author_score >= AUTHOR_OVERLAP, "the authors are real, only the title is wrong"
    assert "Dense Passage Retrieval" in (check.matched_title or "")


def test_an_invented_entry_is_not_found(bad_paper, client, adapters) -> None:
    check = check_for(bad_paper, client, adapters, "1")
    assert check.verdict is Verdict.NOT_FOUND
    assert check.severity == "medium", "never high, because absence is not proof"


def test_not_found_is_never_reported_as_fabrication(bad_paper, client, adapters) -> None:
    for key in ("1", "4", "7"):
        note = check_for(bad_paper, client, adapters, key).note.lower()
        for forbidden in ("fabricat", "made up", "invented", "fake"):
            assert forbidden not in note, f"[{key}] insinuates fabrication: {note}"
        assert "not proof" in note or "not evidence" in note


def test_a_retracted_entry_names_its_notice(bad_paper, client, adapters) -> None:
    check = check_for(bad_paper, client, adapters, "5")
    assert check.verdict is Verdict.RETRACTED
    assert check.severity == "high"
    # Naming the notice lets the author read it rather than take the tool's word.
    assert check.retraction_doi
    assert check.retraction_doi in check.note


def test_retraction_outranks_every_other_problem(bad_paper, client, adapters) -> None:
    # The entry is also a year off, and that is not what the author needs told.
    check = check_for(bad_paper, client, adapters, "5")
    assert check.verdict is Verdict.RETRACTED


def test_a_real_book_does_not_produce_a_false_signal(bad_paper, client, adapters) -> None:
    check = check_for(bad_paper, client, adapters, "6")
    assert check.verdict is Verdict.VERIFIED


def test_an_unindexed_thesis_is_explained_rather_than_accused(bad_paper, client, adapters) -> None:
    check = check_for(bad_paper, client, adapters, "7")
    assert check.verdict is Verdict.NOT_FOUND
    assert check.likely_unindexed
    assert "thesis" in check.note
    assert "not evidence" in check.note


def test_a_near_title_match_is_not_enough_to_claim_a_mismatch(bad_paper, client, adapters) -> None:
    # "Ranking Under Budget Constraints" scores 0.82 against "Machine learning
    # under budget constraints", and they are unrelated papers. Calling that a
    # title mismatch would assert the tool knows what the author meant.
    check = check_for(bad_paper, client, adapters, "7")
    assert check.verdict is not Verdict.TITLE_MISMATCH


# Evidence -----------------------------------------------------------------


def test_every_verdict_reports_the_sources_and_the_score(bad_paper, client, adapters) -> None:
    report = analyse(bad_paper, client, adapters=adapters)
    for check in report.checks:
        if check.verdict is Verdict.UNPARSEABLE:
            continue
        assert check.sources_queried, f"[{check.key}] does not say where it looked"
        assert 0.0 <= check.title_score <= 1.0


def test_the_similarity_algorithm_is_forgiving_about_transcription() -> None:
    assert title_similarity("BM25 and Beyond", "bm25 and beyond!") == 1.0
    assert title_similarity("A Survey of Retrieval", "The Survey of Retrieval") > 0.9
    assert title_similarity("Dense Passage Retrieval", "Protein Folding at Scale") < 0.6


def test_coverage_is_a_count_not_a_share(bad_paper, client, adapters) -> None:
    note = analyse(bad_paper, client, adapters=adapters).coverage_note()
    # A share would read as a score for the bibliography, and this tool does
    # not issue scores.
    assert "%" not in note
    assert "of 8 entries resolved" in note
    assert "queried" in note


def test_an_unreachable_source_weakens_the_conclusion() -> None:
    report = GroundingReport(sources_unavailable={"openalex": "SourceUnavailableError"})
    assert "absence of a record means less than usual" in report.coverage_note()


# Findings -----------------------------------------------------------------


def test_findings_are_anchored_at_the_entry(bad_paper, client, adapters) -> None:
    report = analyse(bad_paper, client, adapters=adapters)
    findings = to_findings(bad_paper, report)
    assert findings
    for finding in findings:
        start, end = finding.char_range
        assert bad_paper.source_text[start:end].strip()


def test_no_grounding_finding_is_ever_auto_applied(bad_paper, client, adapters) -> None:
    report = analyse(bad_paper, client, adapters=adapters)
    for finding in to_findings(bad_paper, report):
        # Fixing a citation means working out what the author meant to cite,
        # and deleting a bad reference leaves its claim standing with nothing
        # behind it.
        assert finding.suggestion is Suggestion.REVIEW
        assert not finding.auto_actionable


def test_a_verified_entry_produces_no_finding(bad_paper, client, adapters) -> None:
    report = analyse(bad_paper, client, adapters=adapters)
    flagged = {finding.matched_text for finding in to_findings(bad_paper, report)}
    assert not any("BM25 and Beyond" in text for text in flagged)


def test_an_unindexed_miss_is_advisory(bad_paper, client, adapters) -> None:
    report = analyse(bad_paper, client, adapters=adapters)
    thesis = next(
        f for f in to_findings(bad_paper, report) if "Ranking Under Budget" in f.matched_text
    )
    assert thesis.advisory
    assert thesis.severity is Severity.MEDIUM


def test_the_whole_pass_makes_no_requests(bad_paper, client, adapters) -> None:
    analyse(bad_paper, client, adapters=adapters)
    assert client.requests_made == 0
