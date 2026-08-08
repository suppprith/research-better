"""Unattributed overlap, and the boundaries that keep it honest.

The single most important property here is what the output does not say. This
tool is not a plagiarism service, cannot see paywalled work or the web, and must
never print a number that reads as a similarity score. A test asserts that
directly, because it is the kind of thing that gets added back by accident.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_better.findings import Severity, Suggestion
from research_better.grounding import check_originality
from research_better.grounding.fulltext import ABSTRACT, FULL_TEXT, NONE, SourceText
from research_better.grounding.originality import (
    MINIMUM_MATCH_WORDS,
    OriginalityReport,
    Overlap,
    analyse_originality,
    compare_sentence,
    distinctiveness,
    is_boilerplate,
    load_boilerplate,
    shingles,
    to_findings,
    words_of,
)
from research_better.ingest.markdown import ingest
from research_better.model import Sentence, Span
from research_better.net import HttpCache, PoliteClient

FIXTURE_HTTP = Path(__file__).parent / "fixtures" / "http"

LIFTED = "two signals the total frequency of each query term within a group"
QUOTED_WITHOUT_MARKS = "topical size balanced document groups a query visits"


@pytest.fixture(scope="module")
def report(bad_paper):
    with PoliteClient(HttpCache(FIXTURE_HTTP, ignore_ttl=True), offline=True) as client:
        return check_originality(bad_paper, client)


@pytest.fixture(scope="module")
def phrases():
    return load_boilerplate()


def sentence_of(text: str) -> Sentence:
    return Sentence(
        id="s-1", paragraph_id="p-1", section_id=None, text=text, span=Span(0, len(text))
    )


# Shingling ----------------------------------------------------------------


def test_shingles_are_overlapping_windows() -> None:
    found = shingles(words_of("one two three four five six seven eight nine"), size=8)
    assert len(found) == 2


def test_distinctiveness_separates_rare_text_from_english() -> None:
    # A ten-word match on a rare phrase matters more than a fifteen-word match
    # on words everyone uses.
    assert distinctiveness(words_of("of the and in on at to for with by")) == 0.0
    assert distinctiveness(words_of("hierarchical shingled inverted index quantization")) == 1.0


# The planted cases --------------------------------------------------------


def test_a_lifted_passage_with_no_citation_is_caught(report: OriginalityReport) -> None:
    match = next(m for m in report.matches if LIFTED in m.matched_text)
    assert match.verdict is Overlap.UNATTRIBUTED_OVERLAP
    assert match.length >= MINIMUM_MATCH_WORDS
    assert match.source_title


def test_a_quote_missing_its_quote_marks_gets_its_own_verdict(
    report: OriginalityReport,
) -> None:
    match = next(m for m in report.matches if QUOTED_WITHOUT_MARKS in m.matched_text)
    # The fix is two quotation marks. Filing this with unattributed copying
    # would frighten an author over a typographic slip.
    assert match.verdict is Overlap.NEEDS_QUOTE_MARKS
    assert "quotation marks" in match.note


def test_the_two_planted_cases_carry_different_severities(report: OriginalityReport) -> None:
    findings = {f.rule: f for f in to_findings(report)}
    assert findings["originality_unattributed_overlap"].severity is Severity.HIGH
    assert findings["originality_needs_quote_marks"].severity is Severity.MEDIUM


def test_matches_are_ranked_by_distinctiveness(report: OriginalityReport) -> None:
    scores = [match.distinctiveness for match in report.matches]
    assert scores == sorted(scores, reverse=True)


def test_findings_anchor_at_the_sentence(bad_paper, report: OriginalityReport) -> None:
    for finding in to_findings(report):
        start, end = finding.char_range
        assert bad_paper.source_text[start:end].strip()


def test_nothing_here_is_auto_applied(report: OriginalityReport) -> None:
    for finding in to_findings(report):
        # Rewriting a passage to avoid an overlap is exactly the synonym
        # substitution this project rules out.
        assert finding.suggestion is Suggestion.REVIEW
        assert not finding.auto_actionable


# Boilerplate --------------------------------------------------------------


def test_standard_framing_is_whitelisted(phrases) -> None:
    assert is_boilerplate("The remainder of this paper is organized as follows", phrases)
    assert is_boilerplate("we use a learning rate of", phrases)


def test_real_prose_is_not_whitelisted(phrases) -> None:
    assert not is_boilerplate("hierarchical shingled quantization over topical clusters", phrases)


def test_a_boilerplate_overlap_is_recorded_but_not_reported(phrases) -> None:
    source = SourceText(
        FULL_TEXT,
        "We describe the setup. The remainder of this paper is organized as follows "
        "and covers the method. Results appear later.",
    )
    match = compare_sentence(
        sentence_of("The remainder of this paper is organized as follows and covers the method."),
        set(),
        source,
        "A Source",
        None,
        phrases,
    )
    assert match is not None
    # An author shown fifteen matches on standard phrasing stops reading the
    # output, and a tool nobody reads catches nothing.
    assert match.verdict is Overlap.BOILERPLATE_IGNORED

    report = analyse_originality(
        ingest(
            "d.md",
            "The remainder of this paper is organized as follows and covers the method.\n",
        ),
        {"1": (source, "A Source", None)},
    )
    assert report.matches == ()
    assert report.boilerplate_ignored == 1


def test_a_run_of_common_words_is_not_evidence(phrases) -> None:
    source = SourceText(FULL_TEXT, "of the and in on at to for with by from as is are was")
    match = compare_sentence(
        sentence_of("of the and in on at to for with by from as is are was"),
        set(),
        source,
        None,
        None,
        phrases,
    )
    assert match is None or match.verdict is Overlap.BOILERPLATE_IGNORED


def test_a_short_match_is_not_worth_reporting(phrases) -> None:
    source = SourceText(FULL_TEXT, "quantized hierarchical clusters " * 6)
    assert (
        compare_sentence(sentence_of("quantized hierarchical"), set(), source, None, None, phrases)
        is None
    )


# Self-overlap -------------------------------------------------------------


def test_overlap_with_the_authors_own_work_is_its_own_verdict(phrases) -> None:
    source = SourceText(
        FULL_TEXT,
        "We index the corpus using hierarchical shingled quantization over topical "
        "clusters selected by term frequency.",
    )
    match = compare_sentence(
        sentence_of(
            "We index the corpus using hierarchical shingled quantization over topical "
            "clusters selected by term frequency."
        ),
        set(),
        source,
        "Our Earlier Paper",
        "10.1/earlier",
        phrases,
        is_own_prior_work=True,
    )
    assert match is not None
    assert match.verdict is Overlap.SELF_OVERLAP
    # Authors extending a conference paper into a journal version routinely do
    # not realize this applies to them.
    assert "your own earlier work" in match.note
    assert "venue" in match.note


def test_self_overlap_is_reported_separately_from_copying(phrases) -> None:
    assert Overlap.SELF_OVERLAP != Overlap.UNATTRIBUTED_OVERLAP
    findings = to_findings(
        OriginalityReport(
            matches=(
                compare_sentence(
                    sentence_of(
                        "We index the corpus using hierarchical shingled quantization over "
                        "topical clusters selected by term frequency."
                    ),
                    set(),
                    SourceText(
                        FULL_TEXT,
                        "We index the corpus using hierarchical shingled quantization over "
                        "topical clusters selected by term frequency.",
                    ),
                    "Earlier",
                    None,
                    phrases,
                    is_own_prior_work=True,
                ),
            )
        )
    )
    assert findings[0].rule == "originality_self_overlap"
    assert findings[0].severity is Severity.MEDIUM


# What the output must never say -------------------------------------------


def test_the_coverage_note_never_prints_a_similarity_score(report: OriginalityReport) -> None:
    note = report.coverage_note()
    # Reporting a percentage from a partial corpus would be a false assurance,
    # and that phrasing is banned from the output.
    assert "%" not in note
    for forbidden in ("plagiarism score", "similarity score", "originality score", "0%"):
        assert forbidden not in note.lower()


def test_the_coverage_note_always_states_what_was_compared(
    report: OriginalityReport,
) -> None:
    note = report.coverage_note()
    assert "Compared against" in note
    assert "not a plagiarism service" in note
    assert "could not be retrieved" in note


def test_abstract_only_sources_are_not_counted_as_full_text() -> None:
    report = analyse_originality(
        ingest("d.md", "A short sentence here.\n"),
        {
            "1": (SourceText(FULL_TEXT, "body " * 40), "Full", None),
            "2": (SourceText(ABSTRACT, "abstract text here"), "Abstract", None),
        },
    )
    # Saying "compared against 2 sources" when one was an abstract would
    # overstate what was read by a wide margin.
    assert report.sources_compared == 2
    assert report.sources_with_full_text == 1
    assert "1 as full text and 1 as abstract only" in report.coverage_note()


def test_unretrievable_sources_are_named_in_the_report() -> None:
    report = analyse_originality(
        ingest("d.md", "A short sentence here.\n"),
        {"1": (SourceText(NONE, ""), "A Paywalled Paper", None)},
    )
    assert report.sources_unavailable == 1
    assert "A Paywalled Paper" in report.unavailable_titles


def test_an_empty_report_still_states_its_limits() -> None:
    assert "not a plagiarism service" in OriginalityReport().coverage_note()


def test_the_pass_makes_no_requests(bad_paper) -> None:
    with PoliteClient(HttpCache(FIXTURE_HTTP, ignore_ttl=True), offline=True) as client:
        check_originality(bad_paper, client)
        assert client.requests_made == 0
