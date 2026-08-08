"""Structural rules, and the discipline that keeps their thresholds honest.

The recurring shape of these tests is a pair: the pattern used once is not a
finding, the pattern repeated inside one section is. A single tricolon is a
sentence somebody wrote. Four of them is a cadence.
"""

from __future__ import annotations

import pytest

from research_better.findings import Finding
from research_better.fluff import analyse
from research_better.fluff.structural import analyse_structural
from research_better.ingest.markdown import ingest
from research_better.thresholds import (
    ThresholdError,
    load_thresholds,
    parse_thresholds,
    thresholds_path,
)


def structural(text: str, thresholds_file=None) -> list[Finding]:
    return analyse_structural(ingest("draft.md", text), thresholds_file=thresholds_file)


def rules(text: str) -> list[str]:
    return [finding.rule for finding in structural(text)]


# tricolon -----------------------------------------------------------------


def test_one_tricolon_in_a_section_is_not_a_finding() -> None:
    assert "tricolon" not in rules("# Method\n\nThe system is fast, small, and simple.\n")


def test_two_tricolons_in_one_section_both_fire() -> None:
    text = (
        "# Method\n\n"
        "The system is fast, small, and simple.\n\n"
        "The index is compact, portable, and cheap.\n"
    )
    assert rules(text).count("tricolon") == 2


def test_tricolons_in_different_sections_do_not_combine() -> None:
    text = (
        "# Method\n\nThe system is fast, small, and simple.\n\n"
        "# Results\n\nThe index is compact, portable, and cheap.\n"
    )
    assert "tricolon" not in rules(text)


def test_a_tricolon_finding_points_at_the_list_not_the_sentence() -> None:
    text = (
        "# Method\n\n"
        "We found that the system is fast, small, and simple in every run.\n\n"
        "The index is compact, portable, and cheap.\n"
    )
    finding = next(f for f in structural(text) if f.rule == "tricolon")
    start, end = finding.char_range
    assert text[start:end] == "fast, small, and simple"


# balanced_clause ----------------------------------------------------------


def test_one_balanced_clause_is_not_a_finding() -> None:
    assert "balanced_clause" not in rules(
        "# Method\n\nNot only is it faster, it is also cheaper to run.\n"
    )


def test_a_repeated_balanced_template_fires() -> None:
    text = (
        "# Method\n\n"
        "Not only is it faster, it is also cheaper.\n\n"
        "It is not only smaller but also easier to deploy.\n"
    )
    assert rules(text).count("balanced_clause") == 2


# section_closing_restatement ----------------------------------------------


def test_a_closing_sentence_that_adds_nothing_fires() -> None:
    text = (
        "# Conclusion\n\n"
        "We presented a unified framework for adaptive retrieval.\n"
        "The method indexes the corpus with BM25.\n"
        "A unified framework for adaptive retrieval was presented.\n"
    )
    assert "section_closing_restatement" in rules(text)


def test_a_closing_sentence_that_adds_content_is_left_alone() -> None:
    text = (
        "# Conclusion\n\n"
        "We presented a framework for adaptive retrieval.\n"
        "The method indexes the corpus with BM25.\n"
        "Recall improved by nine points on the held-out split.\n"
    )
    assert "section_closing_restatement" not in rules(text)


def test_a_one_sentence_section_cannot_restate_itself() -> None:
    assert "section_closing_restatement" not in rules("# Conclusion\n\nWe presented a method.\n")


def test_a_very_short_closing_sentence_is_not_judged() -> None:
    # "It follows." repeats nothing and asserts nothing. Flagging it would be
    # noise, so the rule needs enough content words to have an opinion.
    text = "# Conclusion\n\nWe presented a framework for adaptive retrieval.\nIt follows.\n"
    assert "section_closing_restatement" not in rules(text)


# empty_forward_reference --------------------------------------------------


def test_a_forward_reference_with_no_target_fires() -> None:
    assert "empty_forward_reference" in rules(
        "# Method\n\nAs will be discussed later, the design has useful properties.\n"
    )


def test_a_forward_reference_that_names_its_target_is_left_alone() -> None:
    assert "empty_forward_reference" not in rules(
        "# Method\n\nAs will be discussed later in Section 5, the design has useful properties.\n"
    )


def test_a_sentence_with_no_forward_reference_is_left_alone() -> None:
    assert "empty_forward_reference" not in rules(
        "# Method\n\nThe design has useful properties that we measure below.\n"
    )


# Advisory standing --------------------------------------------------------


def test_every_structural_finding_is_advisory(bad_paper) -> None:
    for finding in analyse_structural(bad_paper):
        assert finding.advisory, f"{finding.rule} is not marked advisory"


def test_no_structural_finding_can_be_auto_applied(bad_paper) -> None:
    # Uniform rhythm correlates with generated text and does not prove it.
    # Acting on a correlation for the author is how a tool rewrites the work of
    # somebody who simply writes evenly.
    for finding in analyse_structural(bad_paper):
        assert not finding.auto_actionable


def test_an_advisory_finding_stays_advisory_even_at_high_severity() -> None:
    from research_better.findings import Severity, Suggestion

    finding = Finding(
        span_id="s-1",
        rule="demo",
        severity=Severity.HIGH,
        matched_text="x",
        char_range=(0, 1),
        suggestion=Suggestion.DELETE,
        advisory=True,
    )
    assert not finding.auto_actionable


def test_the_good_paragraph_survives_the_structural_rules(bad_paper, good_paragraph_ids) -> None:
    offenders = [f for f in analyse(bad_paper) if f.span_id in good_paragraph_ids]
    assert offenders == []


def test_every_enabled_rule_fires_on_the_fixture(bad_paper) -> None:
    fired = {finding.rule for finding in analyse_structural(bad_paper)}
    assert fired == {
        "tricolon",
        "balanced_clause",
        "section_closing_restatement",
        "empty_forward_reference",
    }


# Thresholds ---------------------------------------------------------------


def test_the_uncalibrated_rules_ship_disabled() -> None:
    config = load_thresholds()
    assert not config.enabled("sentence_length_variance")
    assert not config.enabled("paragraph_shape_uniformity")


def test_disabled_rules_are_reportable_rather_than_silent() -> None:
    # An author who sees no rhythm findings should be able to learn that the
    # rhythm rules did not run, rather than reading silence as a clean bill.
    assert load_thresholds().disabled_for_want_of_a_corpus == (
        "paragraph_shape_uniformity",
        "sentence_length_variance",
    )


def test_every_enabled_rule_names_its_source() -> None:
    config = load_thresholds()
    for name, rule in config.rules.items():
        if rule.enabled:
            assert rule.source, f"{name} is enabled with no source"
            assert rule.calibrated, f"{name} is enabled but marked uncalibrated"


def test_enabling_a_rule_without_a_source_is_refused() -> None:
    with pytest.raises(ThresholdError, match="traceable to a corpus statistic"):
        parse_thresholds({"made_up": {"enabled": True}})


def test_a_calibrated_threshold_turns_the_rule_on(tmp_path) -> None:
    config = tmp_path / "thresholds.toml"
    config.write_text(
        "[sentence_length_variance]\nenabled = true\n"
        'source = "percentile 5 of 900 paragraphs from acl-oa, calibrated 2026-08-07"\n'
        "min_stdev_words = 4.0\nminimum_sentences = 4\n",
        encoding="utf-8",
    )
    uniform = (
        "# Method\n\n"
        "The system indexes the corpus with an inverted index structure.\n"
        "The queries are expanded using terms from initial retrieval results.\n"
        "The ranking function combines frequency with inverse document weights.\n"
        "The parameters were selected using grid search over development data.\n"
    )
    findings = structural(uniform, thresholds_file=config)
    assert [f.rule for f in findings] == ["sentence_length_variance"]
    assert findings[0].advisory
    assert "correlates with generated text and does not prove it" in (findings[0].note or "")


def test_a_calibrated_variance_rule_spares_varied_prose(tmp_path) -> None:
    config = tmp_path / "thresholds.toml"
    config.write_text(
        '[sentence_length_variance]\nenabled = true\nsource = "calibrated for this test"\n'
        "min_stdev_words = 4.0\nminimum_sentences = 4\n",
        encoding="utf-8",
    )
    varied = (
        "# Method\n\n"
        "Recall rose.\n"
        "The cost is one third that of the dense baseline on the same hardware, "
        "measured as wall-clock latency over many thousands of queries.\n"
        "We did not see the same gain elsewhere.\n"
        "Expansion helps short queries and does very little for long ones.\n"
    )
    assert [f.rule for f in structural(varied, thresholds_file=config)] == []


def test_a_missing_threshold_file_says_where_it_looked(tmp_path) -> None:
    with pytest.raises(ThresholdError, match="threshold file not found"):
        load_thresholds(tmp_path / "absent.toml")


def test_an_unknown_rule_is_an_error() -> None:
    with pytest.raises(ThresholdError, match="no threshold section"):
        load_thresholds().for_rule("does_not_exist")


def test_the_shipped_threshold_file_documents_every_rule() -> None:
    text = thresholds_path().read_bytes().decode("utf-8")
    for rule in load_thresholds().rules:
        assert f"[{rule}]" in text
    assert "scripts/calibrate_rhythm.py" in text, "the file must say how to calibrate"
