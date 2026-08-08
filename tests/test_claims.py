"""Whether a cited work actually says what it is cited for.

The fixture cites one real paper with retrievable full text twice: once for
something it establishes, and once for something it explicitly defers. Catching
the second is the whole point of the pass, because overclaiming a real source is
far more common than inventing one and no reference manager can see it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_better.findings import Severity, Suggestion
from research_better.grounding import Support, check_claims, claim_findings
from research_better.grounding.claims import (
    MAXIMUM_QUOTE_WORDS,
    ClaimReport,
    check_claim,
    content_words,
    coverage,
    passages,
    strength_markers,
    strip_citations,
)
from research_better.grounding.fulltext import ABSTRACT, FULL_TEXT, NONE, SourceText, html_to_text
from research_better.model import Sentence, Span
from research_better.net import HttpCache, PoliteClient

FIXTURE_HTTP = Path(__file__).parent / "fixtures" / "http"

SUPPORTED_CLAIM = "Hierarchical indexing keeps the resident footprint independent"
OVERCLAIM = "Hierarchical indexing recovers the exhaustive result score at billion"


@pytest.fixture
def client():
    with PoliteClient(HttpCache(FIXTURE_HTTP, ignore_ttl=True), offline=True) as offline_client:
        yield offline_client


@pytest.fixture(scope="module")
def report(bad_paper):
    cache = HttpCache(FIXTURE_HTTP, ignore_ttl=True)
    with PoliteClient(cache, offline=True) as client:
        return check_claims(bad_paper, client)


def sentence_of(text: str) -> Sentence:
    return Sentence(
        id="s-1", paragraph_id="p-1", section_id=None, text=text, span=Span(0, len(text))
    )


# Text preparation ---------------------------------------------------------


def test_citation_markers_are_not_part_of_the_claim() -> None:
    # Leaving "[8]" in makes the number 8 look like a quantity the source has
    # to establish, and every cited sentence comes back as an overclaim.
    assert strip_citations("Recall rose [8].") == "Recall rose ."
    assert "8" not in strength_markers("Recall rose [8].")
    assert "8" not in content_words("Recall rose [8].")


def test_a_real_number_in_the_claim_is_still_a_marker() -> None:
    assert "0.71" in strength_markers("Recall rose to 0.71 [8].")


def test_magnitudes_count_as_claims_about_scale() -> None:
    assert "billion" in strength_markers("This works at billion document scale.")


def test_html_becomes_quotable_prose() -> None:
    text = html_to_text("<p>First para.</p><script>ignored()</script><h2>Head</h2><p>Second.</p>")
    assert "ignored" not in text
    assert "First para." in text
    assert "Second." in text


def test_passages_are_sentences_not_paragraphs() -> None:
    block = (
        "The resident footprint is fixed and small. "
        "Queries over the whole corpus return quickly. "
        "Recall at the largest scale remains open. "
        "We leave that question to later work."
    )
    found = passages(block)
    labels = [where for where, _ in found]
    # An abstract paragraph contains every word of several different claims, so
    # scoring against the paragraph makes every on-topic claim look supported.
    assert any("sentence 1" in label for label in labels)
    assert any("sentences 1-2" in label for label in labels)
    assert max(len(text) for _, text in found) < len(block)


# Verdicts on the fixture --------------------------------------------------


def test_a_true_claim_is_supported_with_a_real_quote(report: ClaimReport) -> None:
    check = next(c for c in report.checks if c.claim.startswith(SUPPORTED_CLAIM))
    assert check.support is Support.SUPPORTED
    assert check.source_kind == FULL_TEXT
    assert check.quote and "independent of corpus size" in check.quote
    assert check.locator and "block" in check.locator


def test_the_planted_overclaim_is_partial(report: ClaimReport) -> None:
    check = next(c for c in report.checks if c.claim.startswith(OVERCLAIM))
    assert check.support is Support.PARTIAL
    # The source's own sentence ends "though not yet at billion scale". Word
    # overlap cannot see a negation, so the deferral cue is what catches it.
    assert check.quote and "not yet" in check.quote
    assert "not yet" in check.note


def test_a_partial_verdict_quotes_rather_than_paraphrases(report: ClaimReport) -> None:
    check = next(c for c in report.checks if c.claim.startswith(OVERCLAIM))
    # A paraphrase would be the tool's opinion wearing the source's clothes.
    # The author has to be able to check.
    assert check.quote
    assert check.locator


def test_a_source_with_no_full_text_is_uncheckable_not_unsupported(report: ClaimReport) -> None:
    abstract_only = [c for c in report.checks if c.source_kind == ABSTRACT]
    assert abstract_only
    for check in abstract_only:
        assert check.support is not Support.UNSUPPORTED


def test_coverage_is_reported_as_a_count_and_a_share(report: ClaimReport) -> None:
    note = report.coverage_note()
    assert "of" in note and "retrievable full text" in note
    assert "retrieval coverage" in note, "the percentage must be labelled as coverage"
    assert "Nothing here is a judgment of the paper" in note


def test_the_pass_makes_no_requests(bad_paper) -> None:
    cache = HttpCache(FIXTURE_HTTP, ignore_ttl=True)
    with PoliteClient(cache, offline=True) as client:
        check_claims(bad_paper, client)
        assert client.requests_made == 0


# Verdict rules in isolation -----------------------------------------------


def test_an_absent_source_is_uncheckable() -> None:
    check = check_claim(sentence_of("A claim."), "1", SourceText(NONE, ""))
    assert check.support is Support.UNCHECKABLE


def test_an_abstract_that_does_not_mention_it_is_uncheckable() -> None:
    source = SourceText(ABSTRACT, "We study protein folding using contact maps and energy terms.")
    check = check_claim(
        sentence_of("Sparse retrieval beats dense retrieval on recall."), "1", source
    )
    # An abstract not mentioning something is no evidence the paper does not
    # say it, so this is not checked rather than found wanting.
    assert check.support is Support.UNCHECKABLE


def test_full_text_that_does_not_mention_it_is_unsupported() -> None:
    body = "We study protein folding. " * 8
    check = check_claim(
        sentence_of("Sparse retrieval beats dense retrieval on recall."),
        "1",
        SourceText(FULL_TEXT, body),
    )
    assert check.support is Support.UNSUPPORTED
    assert "lexical" in check.note, "the note has to own the limits of the matching"


def test_an_unmet_number_downgrades_to_partial() -> None:
    source = SourceText(
        FULL_TEXT, "Expansion improves recall on the held-out split by some margin."
    )
    check = check_claim(sentence_of("Expansion improves recall by 40 points."), "1", source)
    assert check.support is Support.PARTIAL
    assert "40" in check.unmet


def test_a_deferral_cue_blocks_support() -> None:
    source = SourceText(
        FULL_TEXT,
        "Expansion improves recall on the held-out split, though scaling remains open.",
    )
    check = check_claim(
        sentence_of("Expansion improves recall on the held-out split."), "1", source
    )
    assert check.support is Support.PARTIAL
    assert "remains open" in check.note


def test_a_quote_is_capped_in_length() -> None:
    body = " ".join(f"word{index}" for index in range(400)) + " recall improves markedly here."
    check = check_claim(
        sentence_of("Recall improves markedly here."), "1", SourceText(FULL_TEXT, body)
    )
    assert check.quote
    assert len(check.quote.split()) <= MAXIMUM_QUOTE_WORDS + 4, "the ellipsis adds a token or two"


def test_coverage_scoring_is_directional() -> None:
    assert coverage("recall improves", "recall improves on the split") == 1.0
    assert coverage("recall improves", "protein folding") == 0.0


# Findings -----------------------------------------------------------------


def test_a_supported_claim_produces_no_finding(report: ClaimReport) -> None:
    flagged = {finding.matched_text for finding in claim_findings(report)}
    assert not any(text.startswith(SUPPORTED_CLAIM) for text in flagged)


def test_the_overclaim_produces_a_finding_carrying_the_quote(report: ClaimReport) -> None:
    finding = next(f for f in claim_findings(report) if f.matched_text.startswith(OVERCLAIM))
    assert finding.severity is Severity.MEDIUM
    assert finding.suggestion is Suggestion.REVIEW
    assert "The source says:" in (finding.note or "")


def test_an_uncheckable_claim_is_advisory(report: ClaimReport) -> None:
    uncheckable = [f for f in claim_findings(report) if f.rule == "claim_uncheckable"]
    assert uncheckable
    for finding in uncheckable:
        # It describes the retrieval, not the writing.
        assert finding.advisory
        assert finding.severity is Severity.LOW


def test_no_claim_finding_is_auto_applied(report: ClaimReport) -> None:
    for finding in claim_findings(report):
        assert not finding.auto_actionable


def test_an_empty_report_says_nothing_was_checked() -> None:
    assert "nothing was checked" in ClaimReport().coverage_note()
