"""Reviewer questions, and the constraint that the tool never answers them.

A tool that fills a gap with plausible text produces a paper that reads as
finished and is not. If the sample size is missing this asks for the sample
size. It does not write "on a dataset of moderate size", and a test checks the
output for exactly that habit.
"""

from __future__ import annotations

import pytest

from research_better import novelty, reviewer
from research_better.ingest.markdown import ingest
from research_better.reviewer import ORDER, ReviewerReport, Severity


@pytest.fixture(scope="module")
def report(bad_paper) -> ReviewerReport:
    return reviewer.analyse(bad_paper, novelty.analyse(bad_paper))


def categories(report: ReviewerReport) -> set[str]:
    return {question.category for question in report.questions}


# The two planted cases ----------------------------------------------------


def test_the_unsupported_contribution_is_blocking(report: ReviewerReport) -> None:
    question = next(q for q in report.questions if q.category == "unsupported_claim")
    # A gap between the stated contribution and the results is the most common
    # single cause of rejection.
    assert question.severity is Severity.BLOCKING
    assert "stated contribution" in question.question
    assert question.quote


def test_the_planted_significance_claim_is_questioned(report: ReviewerReport) -> None:
    questions = [q for q in report.questions if q.category == "unquantified_significance"]
    assert any("significantly" in q.question for q in questions)
    assert all(q.severity is Severity.SERIOUS for q in questions)


# The contract on every question -------------------------------------------


def test_every_question_names_a_span_and_a_resolution(report: ReviewerReport) -> None:
    assert report.questions
    for question in report.questions:
        assert question.span_id, f"{question.category} names no span"
        assert question.resolution, f"{question.category} offers no way out"
        assert question.why, f"{question.category} does not say why it is asked"


def test_questions_are_ordered_by_consequence(report: ReviewerReport) -> None:
    positions = [ORDER.index(q.severity) for q in report.questions]
    assert positions == sorted(positions)


def test_the_tool_never_answers_its_own_questions(report: ReviewerReport) -> None:
    body = report.to_markdown().lower()
    # The failure mode is filling a gap with something that sounds like an
    # answer. Every one of these is a phrase that papers over a missing number.
    for filler in (
        "a dataset of moderate size",
        "a reasonable number of",
        "standard hyperparameters were used",
        "typical hardware",
    ):
        assert filler not in body


def test_the_markdown_says_these_are_questions_not_corrections(
    report: ReviewerReport,
) -> None:
    body = report.to_markdown()
    assert "questions, not corrections" in body
    assert "answering them is the work" in body


def test_every_question_appears_in_the_markdown(report: ReviewerReport) -> None:
    body = report.to_markdown()
    for question in report.questions:
        assert question.question in body
        assert question.resolution in body


# Individual checks --------------------------------------------------------


def test_a_significance_claim_with_a_test_is_left_alone() -> None:
    draft = ingest(
        "d.md",
        "# Results\n\nOur method significantly outperforms the BM25 baseline, "
        "p < 0.01 by a paired t-test.\n",
    )
    result = reviewer.analyse(draft)
    assert "unquantified_significance" not in categories(result)


def test_a_comparison_with_a_named_baseline_is_left_alone() -> None:
    draft = ingest("d.md", "# Results\n\nOur method outperforms the BM25 baseline on recall.\n")
    assert "missing_baseline" not in categories(reviewer.analyse(draft))


def test_a_comparison_with_nothing_named_is_questioned() -> None:
    draft = ingest("d.md", "# Results\n\nOur method outperforms all prior approaches.\n")
    assert "missing_baseline" in categories(reviewer.analyse(draft))


def test_generalization_beyond_the_evidence_is_questioned() -> None:
    draft = ingest("d.md", "# Results\n\nThe method works for all domains and any dataset.\n")
    assert "generalization_overreach" in categories(reviewer.analyse(draft))


def test_a_paper_stating_its_limitations_is_not_asked_for_them(bad_paper) -> None:
    # The fixture has a limitations section, so this check must stay quiet.
    assert "threat_to_validity" not in categories(reviewer.analyse(bad_paper))


def test_a_paper_with_no_limitations_is_asked() -> None:
    draft = ingest("d.md", "# Results\n\nRecall rose by four points on the test collection.\n")
    assert "threat_to_validity" in categories(reviewer.analyse(draft))


def test_a_paper_that_releases_its_code_is_not_asked_about_it(bad_paper) -> None:
    assert "reproducibility" not in categories(reviewer.analyse(bad_paper))


def test_a_missing_method_detail_is_asked_for_by_name() -> None:
    draft = ingest("d.md", "# Method\n\nThe model was trained until it converged.\n")
    details = [
        q for q in reviewer.analyse(draft).questions if q.category == "undisclosed_method_detail"
    ]
    assert details
    assert any("hyperparameters" in q.question for q in details)


# Venue awareness ----------------------------------------------------------


def test_an_unverified_venue_does_not_assert_its_rules(bad_paper) -> None:
    result = reviewer.analyse(bad_paper, venue="ieee")
    assert not result.venue_verified
    ablation = next(q for q in result.questions if q.category == "missing_ablation")
    # The tool does not get to say a venue requires something it never checked.
    assert ablation.severity is Severity.MINOR
    assert "depends on the venue" in ablation.why


def test_the_markdown_says_when_no_venue_profile_was_used(bad_paper) -> None:
    body = reviewer.analyse(bad_paper, venue="ieee").to_markdown()
    assert "No verified profile" in body


def test_an_ablation_that_exists_is_not_asked_for() -> None:
    draft = ingest("d.md", "# Results\n\nThe ablation removes each component in turn.\n")
    assert "missing_ablation" not in categories(reviewer.analyse(draft))


# Without a novelty report -------------------------------------------------


def test_the_pass_runs_without_a_claim(bad_paper) -> None:
    # Every check except the contribution question still applies.
    result = reviewer.analyse(bad_paper)
    assert result.questions
    assert "unsupported_claim" not in categories(result)


def test_a_report_with_no_questions_says_so() -> None:
    assert "No questions raised" in ReviewerReport().to_markdown()
