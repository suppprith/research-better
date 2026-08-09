"""The check on the written analysis.

SUP-523 shipped the synthesis step and a reference file telling the model what
it may and may not contain. A reference file is a preference, and this
project's own sentence about those is in `edit/gate.py`: a prompt is a
preference and a check is a guarantee. So the tests here are mostly about the
grader catching each thing the reference forbids, and one about it passing an
analysis that follows the reference, because a grader that refuses everything
is as useless as one that refuses nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_better import synthesis
from research_better.report import Report

CLEAN = """\
# What this run found

## The claim, and whether the body supports it

The paper claims a formal proof of convergence. Nothing in the body picks up
the words proof or converges.

## What would get this rejected

3 of 8 bibliography entries resolved. 5 did not, which is not evidence any of
them is invented. The entry `smith2021` is retracted.

## What was not checked

Only 1 of 6 cited works had retrievable full text, so claim support covers that
one and could not see the rest.
"""


def report_with(**overrides: object) -> Report:
    """A report shaped like a partial run, which is the normal case."""
    defaults: dict[str, object] = {
        "draft": "paper.md",
        "claim": "We prove convergence.",
        "citations": {"VERIFIED": 3, "NOT_FOUND": 5},
        "citations_with_full_text": (1, 6),
        "gaps": (),
    }
    defaults.update(overrides)
    return Report(**defaults)  # type: ignore[arg-type]


def rules(result: synthesis.AnalysisCheck) -> set[str]:
    return {item.rule for item in result.violations}


def check(text: str, **overrides: object) -> synthesis.AnalysisCheck:
    return synthesis.check(text, report_with(**overrides), {"smith2021", "1", "2", "3"})


# The analysis that follows the reference ----------------------------------


def test_an_analysis_that_follows_the_reference_passes() -> None:
    result = check(CLEAN)
    assert result.clean, [item.to_json() for item in result.violations]


def test_a_clean_result_still_says_what_it_did_not_look_at() -> None:
    """A checker reporting no violations without saying what it never examined
    is making the false-assurance move this project refuses everywhere else."""
    result = check(CLEAN)
    assert result.not_checked
    assert any("rewrites the author's prose" in item for item in result.not_checked)
    assert any("reviewer question" in item for item in result.not_checked)
    assert "not a verdict on the analysis" in synthesis.to_markdown(result)


# No percentage ------------------------------------------------------------


@pytest.mark.parametrize("phrase", ["came out at 12%", "roughly 8 per cent", "12.5% overlap"])
def test_a_percentage_is_refused(phrase: str) -> None:
    assert "percentage" in rules(check(CLEAN + f"\n\nSimilarity {phrase}.\n"))


def test_a_decimal_that_is_not_a_percentage_is_allowed() -> None:
    """Recall rising from 0.62 to 0.71 is the author's own measurement."""
    result = synthesis.check(
        CLEAN + "\n\nThe paper reports recall rising from 0.62 to 0.71.\n",
        report_with(),
        {"smith2021", "1", "2", "3"},
        payloads={"paper": {}},
        draft_text="Recall rose from 0.62 to 0.71.",
    )
    assert "percentage" not in rules(result)


# Citations ----------------------------------------------------------------


def test_a_citation_the_grounding_pass_never_saw_is_refused() -> None:
    result = check(CLEAN + "\n\nSee also [42] on this point.\n")
    assert "citation_not_in_grounding" in rules(result)


def test_a_key_the_grounding_pass_never_saw_is_refused() -> None:
    result = check(CLEAN + "\n\nThe work in `nakamura2029` covers this.\n")
    assert "citation_not_in_grounding" in rules(result)


def test_a_citation_the_pass_failed_to_resolve_is_still_allowed() -> None:
    """A failed lookup is still a record. Naming a citation the pass could not
    resolve is honest reporting; naming one it never saw is invention."""
    assert "citation_not_in_grounding" not in rules(
        check(CLEAN + "\n\nEntry [2] did not resolve.\n")
    )


# Verdicts -----------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "Your paper is in good shape.",
        "This is a solid paper overall.",
        "The draft is well written.",
        "It is ready for submission.",
        "There are no major issues.",
    ],
)
def test_a_verdict_on_the_paper_is_refused(phrase: str) -> None:
    """The thing the checker exists for. Everything else on the list is a thing
    a careless summarizer drops, and this is the thing it adds."""
    assert "verdict_on_the_paper" in rules(check(CLEAN + f"\n\n{phrase}\n"))


def test_reporting_a_finding_is_not_a_verdict() -> None:
    text = CLEAN + "\n\nThe contribution claim is not established by the body.\n"
    assert "verdict_on_the_paper" not in rules(check(text))


# Coverage -----------------------------------------------------------------


def test_dropping_the_full_text_ratio_is_refused() -> None:
    """A run where one of six cited works had retrievable full text must not
    produce prose reading as though six were checked."""
    text = "The bibliography was checked and 3 of 8 entries resolved. 5 did not.\n"
    result = check(text)
    assert "coverage_dropped" in rules(result)
    assert any("1 of 6" in item.quote for item in result.violations)


def test_dropping_the_unresolved_count_is_refused() -> None:
    text = "Everything resolved. 1 of 6 cited works had full text.\n"
    assert "coverage_dropped" in rules(check(text))


def test_a_run_with_full_coverage_needs_no_caveat() -> None:
    """The rule is about what was missed. A complete run has nothing to carry."""
    result = synthesis.check(
        "Every bibliography entry resolved.\n",
        report_with(citations={"VERIFIED": 8}, citations_with_full_text=(8, 8)),
        {"smith2021"},
    )
    assert "coverage_dropped" not in rules(result)


def test_a_pass_that_did_not_run_must_be_named() -> None:
    """Silence about a check that did not happen reads as a check that found
    nothing."""
    gaps = ("The edits pass has not run. Run: research-better edit paper.md",)
    assert "unrun_pass_not_named" in rules(check(CLEAN, gaps=gaps))
    assert "unrun_pass_not_named" not in rules(
        check(CLEAN + "\n\nThe edits pass has not run.\n", gaps=gaps)
    )


# Numbers ------------------------------------------------------------------


def test_a_number_from_nowhere_is_refused() -> None:
    """Two counts added together is the usual cause."""
    result = synthesis.check(
        CLEAN + "\n\nAcross the 47 checks that ran, most resolved.\n",
        report_with(),
        {"smith2021", "1", "2", "3"},
        payloads={"grounding": {"verified": 3, "checks": [{"key": "smith2021"}]}},
        draft_text="A paper with 8 references.",
    )
    assert "number_not_in_the_artifacts" in rules(result)


def test_a_number_the_artifacts_contain_is_allowed() -> None:
    result = synthesis.check(
        "3 entries resolved.\n",
        report_with(citations={"VERIFIED": 3}, citations_with_full_text=(0, 0)),
        set(),
        payloads={"grounding": {"verified": 3}},
    )
    assert "number_not_in_the_artifacts" not in rules(result)


def test_a_number_from_the_paper_itself_is_allowed() -> None:
    """Quoting the author's own measurement back to them is the point."""
    result = synthesis.check(
        "The paper reports coverage falling to 0.54.\n",
        report_with(citations={}, citations_with_full_text=(0, 0)),
        set(),
        payloads={"paper": {}},
        draft_text="Coverage falls from 0.81 to 0.54 across four floors.",
    )
    assert "number_not_in_the_artifacts" not in rules(result)


def test_a_markdown_list_marker_is_not_a_claim() -> None:
    result = synthesis.check(
        "Fix these:\n\n1. the bibliography\n2. the claim\n",
        report_with(citations={}, citations_with_full_text=(0, 0)),
        set(),
        payloads={"paper": {}},
    )
    assert "number_not_in_the_artifacts" not in rules(result)


def test_without_the_artifacts_the_number_check_does_not_run() -> None:
    """A checker that cannot see the artifacts must not report the analysis as
    inventing things. It says it did not check instead."""
    result = synthesis.check("There were 999 findings.\n", report_with(), set())
    assert "number_not_in_the_artifacts" not in rules(result)
    assert not any("number" in rule for rule in result.checked)


# The whole thing, against a real run --------------------------------------


def test_every_rule_the_reference_states_is_either_checked_or_declared() -> None:
    """The reference forbids six things. Four are checked and two are not, and
    a reader has to be able to tell which without reading this file."""
    result = check(CLEAN)
    covered = " ".join(result.checked + result.not_checked).lower()
    for topic in ("percentage", "citation", "verdict", "coverage", "rewrite", "reviewer question"):
        assert topic.split()[0] in covered, f"nothing says whether {topic} is checked"


def test_the_reference_and_the_checker_agree_on_what_is_forbidden() -> None:
    """If the reference grows a rule the checker cannot see, the checker has to
    say so rather than passing silently."""
    reference = (
        Path(__file__).parent.parent
        / "src"
        / "research_better"
        / "references"
        / "final-analysis.md"
    )
    text = reference.read_text(encoding="utf-8")
    assert "rb check-analysis" in text, "the reference never mentions the check on it"
