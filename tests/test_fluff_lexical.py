"""Lexical fluff rules, one true positive and one true negative per family.

The negatives carry the weight. A rule that fires on everything is worse than
no rule, because it trains the author to ignore the output.
"""

from __future__ import annotations

import pytest

from research_better.findings import Finding, Severity, Suggestion
from research_better.fluff import analyse
from research_better.fluff.lexical import analyse_lexical
from research_better.ingest.markdown import ingest
from research_better.lexicon import LexiconError, load_lexicon, parse_lexicon


def findings_for(text: str) -> list[Finding]:
    return analyse(ingest("draft.md", text))


def rules_for(text: str) -> set[str]:
    return {finding.rule for finding in findings_for(text)}


def matched(text: str, rule: str) -> list[str]:
    return [f.matched_text for f in findings_for(text) if f.rule == rule]


# filler_opener ------------------------------------------------------------


def test_filler_opener_fires() -> None:
    assert matched("It is important to note that recall improved.", "filler_openers") == [
        "It is important to note that"
    ]


def test_filler_opener_leaves_a_direct_claim_alone() -> None:
    assert "filler_openers" not in rules_for("Recall improved by four points.")


def test_filler_opener_deletion_takes_its_trailing_separator() -> None:
    text = "Needless to say, recall improved.\n"
    finding = next(f for f in findings_for(text) if f.rule == "filler_openers")
    start, end = finding.char_range
    assert text[start:end] == "Needless to say, "
    assert finding.suggestion is Suggestion.DELETE_CLAUSE
    assert finding.auto_actionable


# empty_intensifier --------------------------------------------------------


def test_empty_intensifier_fires_on_an_unmeasured_adjective() -> None:
    assert matched("The result is very significant for the field.", "empty_intensifiers") == [
        "very"
    ]


def test_empty_intensifier_spares_a_sentence_that_reports_a_number() -> None:
    # An intensifier next to a measurement is the author's voice, not padding.
    assert "empty_intensifiers" not in rules_for("The very small gain of 0.4 points held.")


def test_empty_intensifier_needs_a_following_word() -> None:
    assert "empty_intensifiers" not in rules_for("The improvement was modest.")


# hedge_stack --------------------------------------------------------------


def test_a_single_hedge_is_left_alone() -> None:
    # One hedge is normal academic writing and often the correct thing to say.
    assert not {"hedge_adverbs", "hedge_verbs"} & rules_for(
        "This may explain the gap between the two systems."
    )


def test_a_stacked_hedge_is_flagged_but_the_first_survives() -> None:
    findings = [
        f for f in findings_for("This may potentially explain the gap.") if "hedge" in f.rule
    ]
    assert [f.matched_text for f in findings] == ["potentially"]


def test_a_hedging_verb_in_a_stack_goes_to_the_human() -> None:
    findings = {
        f.matched_text: f
        for f in findings_for("The evidence may suggest a link.")
        if "hedge" in f.rule
    }
    # Deleting a verb would leave the sentence ungrammatical, so the tool asks
    # rather than acting.
    assert findings["suggest"].suggestion is Suggestion.REVIEW
    assert not findings["suggest"].auto_actionable


def test_hedges_in_separate_clauses_do_not_stack() -> None:
    assert not {"hedge_adverbs", "hedge_verbs"} & rules_for(
        "This may hold for short queries, although the effect is possibly smaller elsewhere."
    )


# model_vocabulary ---------------------------------------------------------


def test_model_vocabulary_fires_once_at_low_severity() -> None:
    findings = [
        f for f in findings_for("We delve into the results.") if f.rule == "model_vocabulary"
    ]
    assert [f.matched_text for f in findings] == ["delve"]
    assert findings[0].severity is Severity.LOW
    # Removing the word needs a rewrite, so it is never auto-applied.
    assert findings[0].suggestion is Suggestion.REVIEW
    assert not findings[0].auto_actionable


def test_repeated_model_vocabulary_is_raised_to_medium() -> None:
    text = "The realm is wide.\n\nThe realm is deep.\n\nThe realm is old.\n"
    findings = [f for f in findings_for(text) if f.rule == "model_vocabulary"]
    assert len(findings) == 3
    assert all(f.severity is Severity.MEDIUM for f in findings)


def test_ordinary_vocabulary_is_untouched() -> None:
    assert "model_vocabulary" not in rules_for("We index the corpus and rank the results.")


# nominalization -----------------------------------------------------------


def test_nominalization_offers_a_dictionary_replacement() -> None:
    finding = next(
        f
        for f in findings_for("We performed an analysis of the logs.")
        if f.rule == "nominalizations"
    )
    assert finding.suggestion is Suggestion.REPLACE_WITH
    assert finding.replacement == "analysed"
    # A replacement is only ever a fixed lexicon entry, never generated text.
    assert not finding.auto_actionable


def test_the_direct_verb_is_left_alone() -> None:
    assert "nominalizations" not in rules_for("We analysed the logs.")


# citation_free_superlative ------------------------------------------------


def test_superlative_without_evidence_fires() -> None:
    assert matched(
        "Our method significantly outperforms the baseline.", "unsupported_superlative_adverbs"
    ) == ["significantly"]


def test_superlative_with_a_number_is_spared() -> None:
    assert "unsupported_superlative_adverbs" not in rules_for(
        "Our method significantly outperforms the baseline, p < 0.01 by a paired t-test."
    )


def test_superlative_with_a_citation_is_spared() -> None:
    assert "unsupported_superlative_adverbs" not in rules_for(
        "Our method substantially outperforms the baseline of Smith [@smith2021]."
    )


def test_a_superlative_that_cannot_be_deleted_goes_to_the_human() -> None:
    finding = next(
        f
        for f in findings_for("This is a novel approach to the problem.")
        if f.rule == "unsupported_superlative_claims"
    )
    assert finding.suggestion is Suggestion.REVIEW


# throat_clearing ----------------------------------------------------------


def test_a_run_of_three_transitions_fires() -> None:
    text = (
        "Moreover, the first point holds.\n\n"
        "Furthermore, the second point holds.\n\n"
        "Additionally, the third point holds.\n"
    )
    assert matched(text, "throat_clearing_transitions") == [
        "Moreover",
        "Furthermore",
        "Additionally",
    ]


def test_two_transitions_are_not_a_run() -> None:
    text = "Moreover, the first point holds.\n\nFurthermore, the second point holds.\n"
    assert "throat_clearing_transitions" not in rules_for(text)


def test_a_transition_broken_by_a_plain_paragraph_is_not_a_run() -> None:
    text = (
        "Moreover, the first point holds.\n\n"
        "The second point holds on its own.\n\n"
        "Furthermore, the third point holds.\n"
    )
    assert "throat_clearing_transitions" not in rules_for(text)


# The fixture --------------------------------------------------------------


def test_the_good_paragraph_produces_no_findings(bad_paper, good_paragraph_ids) -> None:
    offenders = [f for f in analyse(bad_paper) if f.span_id in good_paragraph_ids]
    assert offenders == [], f"the paragraph that must survive was flagged: {offenders}"


def test_every_rule_family_fires_on_the_fixture(bad_paper) -> None:
    fired = {finding.rule for finding in analyse(bad_paper)}
    for rule in (
        "filler_openers",
        "empty_intensifiers",
        "hedge_adverbs",
        "hedge_verbs",
        "model_vocabulary",
        "nominalizations",
        "unsupported_superlative_adverbs",
        "unsupported_superlative_claims",
        "throat_clearing_transitions",
    ):
        assert rule in fired, f"{rule} never fired on a fixture built to trigger it"


def test_every_auto_actionable_deletion_leaves_clean_text(bad_paper) -> None:
    """Applying every high-severity deletion must not leave doubled spaces or
    orphaned punctuation. This is the property that makes them auto-actionable."""
    text = bad_paper.source_text
    for finding in sorted(
        (f for f in analyse(bad_paper) if f.auto_actionable),
        key=lambda f: -f.char_range[0],
    ):
        start, end = finding.char_range
        text = text[:start] + text[end:]

    original_lines = set(bad_paper.source_text.splitlines())
    for line in text.splitlines():
        if line in original_lines:
            continue  # untouched by any deletion, so its indentation is the author's
        body = line.strip()
        assert "  " not in body, f"doubled space left behind: {line!r}"
        assert " ," not in body, f"orphaned comma: {line!r}"
        assert " ." not in body, f"orphaned full stop: {line!r}"


def test_findings_are_in_document_order(bad_paper) -> None:
    starts = [f.char_range[0] for f in analyse(bad_paper)]
    assert starts == sorted(starts)


def test_char_ranges_recover_the_matched_source(bad_paper) -> None:
    for finding in analyse(bad_paper):
        start, end = finding.char_range
        assert finding.matched_text.lower() in bad_paper.source_text[start:end].lower()


# The lexicon is data ------------------------------------------------------


def test_a_new_term_needs_no_python_change(tmp_path) -> None:
    custom = tmp_path / "lexicon.md"
    custom.write_text(
        "## filler_openers\n"
        "family: filler_opener\n"
        "severity: high\n"
        "suggestion: delete_clause\n"
        "note: made up for this test\n"
        "\n"
        "- As every schoolchild knows\n",
        encoding="utf-8",
    )
    document = ingest("draft.md", "As every schoolchild knows, recall improved.\n")
    findings = analyse_lexical(document, lexicon_file=custom)
    assert [f.matched_text for f in findings] == ["As every schoolchild knows"]
    assert findings[0].note == "made up for this test"


def test_prose_headings_are_not_rule_sections() -> None:
    lexicon = parse_lexicon(
        "# Title\n\n## How this file is parsed\n\nSome prose.\n\n"
        "## real_rule\nfamily: filler_opener\nseverity: low\nsuggestion: review\n- a term\n"
    )
    assert [section.id for section in lexicon.sections] == ["real_rule"]


def test_a_rule_section_with_no_terms_is_an_error() -> None:
    with pytest.raises(LexiconError, match="lists no terms"):
        parse_lexicon("## empty_rule\nseverity: high\n")


def test_an_unknown_severity_is_an_error() -> None:
    with pytest.raises(LexiconError, match="expected one of"):
        parse_lexicon("## bad_rule\nseverity: catastrophic\n- a term\n")


def test_an_unknown_suggestion_is_an_error() -> None:
    with pytest.raises(LexiconError, match="expected one of"):
        parse_lexicon("## bad_rule\nsuggestion: rewrite_it\n- a term\n")


def test_a_lexicon_with_no_sections_is_an_error() -> None:
    with pytest.raises(LexiconError, match="no rule sections"):
        parse_lexicon("# Just prose\n\nNothing here.\n")


def test_the_shipped_lexicon_covers_every_matcher() -> None:
    from research_better.fluff.lexical import MATCHERS
    from research_better.fluff.structural import LEXICON_FAMILIES

    assert set(load_lexicon().families) == set(MATCHERS) | set(LEXICON_FAMILIES), (
        "a matcher with no lexicon section can never fire, and a lexicon "
        "section with no matcher is silently ignored"
    )


def test_a_missing_lexicon_file_says_where_it_looked(tmp_path) -> None:
    with pytest.raises(LexiconError, match="lexicon not found"):
        load_lexicon(tmp_path / "absent.md")
