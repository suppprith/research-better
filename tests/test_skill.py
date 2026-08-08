"""SKILL.md, the entrypoint an agent loads.

Two properties are worth testing mechanically. The description is the trigger
surface, so it has to name the phrasings a user actually types. And the body
orchestrates rather than teaching, so it has to stay short and defer to the
reference pack.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_better.passes import PASSES

SKILL = Path(__file__).parent.parent / "SKILL.md"
REFERENCES = Path(__file__).parent.parent / "src" / "research_better" / "references"

BODY_WORD_LIMIT = 900
"""About a page. Longer than this and the body has started carrying knowledge
that belongs in a reference file, which costs the context the paper needs."""


@pytest.fixture(scope="module")
def skill() -> str:
    return SKILL.read_bytes().decode("utf-8")


def frontmatter(text: str) -> str:
    return text.split("---")[1]


def body(text: str) -> str:
    return text.split("---", 2)[2]


# Triggering ---------------------------------------------------------------


def test_the_description_names_realistic_phrasings(skill: str) -> None:
    description = frontmatter(skill).lower()
    # The router matches on this text, so it has to contain the words a user
    # would actually type rather than the words the tool uses internally.
    for phrasing in ("tighten", "citations", "related work", "reviewer", "de-slop"):
        assert phrasing in description, f"the description never mentions {phrasing!r}"


def test_the_description_names_what_it_operates_on(skill: str) -> None:
    description = frontmatter(skill).lower()
    for noun in ("paper", "thesis", "manuscript", "draft"):
        assert noun in description


# Size ---------------------------------------------------------------------


def test_the_body_stays_about_a_page(skill: str) -> None:
    words = len(body(skill).split())
    assert words <= BODY_WORD_LIMIT, f"the body is {words} words and should orchestrate, not teach"


def test_the_body_defers_to_the_reference_pack(skill: str) -> None:
    text = body(skill)
    for reference in (
        "novelty-audit.md",
        "grounding-protocol.md",
        "reviewer-questions.md",
        "voice-preservation.md",
    ):
        assert reference in text, f"{reference} is never loaded by any step"
    assert "Read a reference only when its step runs" in text


# Orchestration ------------------------------------------------------------


def test_the_operating_rule_comes_first(skill: str) -> None:
    text = body(skill)
    assert text.index("Cut before you write") < text.index("## Order")
    assert "delete or ask, never rewrite" in text


def test_every_implemented_pass_has_a_step(skill: str) -> None:
    text = body(skill)
    for name, entry in PASSES.items():
        if entry.implemented:
            assert f"rb {name} " in text, f"the {name} pass has no step"


def test_the_claim_confirmation_is_a_stop(skill: str) -> None:
    text = body(skill)
    assert "Stop here until they answer" in text
    assert "every cut after it is wrong" in text


def test_the_agent_is_told_to_run_the_scripts(skill: str) -> None:
    text = " ".join(body(skill).split())
    # A model judging fluff by eye produces a different answer every run, and
    # the whole point of the deterministic passes is that they do not.
    assert "Do not reimplement their logic by eye" in text
    assert "including when it returns nothing" in text


# Refusals -----------------------------------------------------------------


def test_the_refusals_are_in_the_body_not_a_reference(skill: str) -> None:
    text = body(skill)
    # A refusal in a reference file is a refusal that gets skipped whenever
    # that file is not loaded.
    for refusal in (
        "Never invent a source",
        "Never claim a check that did not run",
        "Never help evade a detector",
        "Never edit results, data, or numbers",
        "Never present a count as a score",
        "Never answer the reviewer questions",
    ):
        assert refusal in text


def test_false_positives_are_handled_generously(skill: str) -> None:
    text = " ".join(body(skill).split())
    assert "likely a false positive, leave it" in text
    assert "Non-native English phrasing" in text


def test_coverage_is_required_in_what_the_user_is_told(skill: str) -> None:
    text = " ".join(body(skill).split())
    assert "Silence about what was not checked reads as a clean result" in text


# House rules --------------------------------------------------------------


def test_the_skill_holds_to_the_repo_writing_rules(skill: str) -> None:
    assert chr(0x2014) not in skill


def test_every_referenced_file_exists(skill: str) -> None:
    for path in REFERENCES.iterdir():
        if path.suffix == ".md" and path.name in skill:
            assert path.is_file()


# The final analysis -------------------------------------------------------
#
# The skill orchestrated ten passes, waited several minutes, and stopped. There
# was no step where it read what came back and told the author what was wrong
# with their paper. SUP-522 is the tool half, printing findings instead of
# counts. This is the other half and the one that matters more: even with every
# finding printed, relaying eleven passes of output is not an analysis.

FINAL_ANALYSIS = REFERENCES / "final-analysis.md"


@pytest.fixture(scope="module")
def final_analysis() -> str:
    return FINAL_ANALYSIS.read_bytes().decode("utf-8")


def test_the_synthesis_is_a_step_rather_than_a_hope(skill: str) -> None:
    text = body(skill)
    assert "final-analysis.md" in text, "the reference is never loaded by any step"
    assert "Write the analysis" in text


def test_the_synthesis_step_comes_after_every_pass(skill: str) -> None:
    text = body(skill)
    assert text.index("Write the analysis") > text.index("rb report")


def test_the_run_is_not_finished_without_it(skill: str) -> None:
    text = " ".join(body(skill).split())
    assert "the run is not finished without it" in text


def test_the_synthesis_is_bound_to_the_artifacts(skill: str, final_analysis: str) -> None:
    """The constraint that shapes the whole thing. The moment the model adds its
    own view of whether the paper is good, it is producing the unverified
    judgement this project exists to replace, under the tool's name."""
    assert "trace back to a record" in " ".join(body(skill).split())
    assert "It is not a second analysis" in final_analysis
    assert "evidence gate applied to prose" in final_analysis


def test_the_synthesis_structure_is_settled_not_left_to_the_model(
    final_analysis: str,
) -> None:
    """Settled in the reference rather than improvised each run, so two runs of
    the same paper do not produce differently shaped answers."""
    for section in (
        "The claim, and whether the body supports it",
        "What would get this rejected",
        "What to fix, and in what order",
        "What was not checked",
        "What was looked at and deliberately left alone",
    ):
        assert section in final_analysis


def test_the_synthesis_carries_its_own_refusals(final_analysis: str) -> None:
    for refusal in (
        "A rewritten sentence",
        "A citation that is not in `grounding.json`",
        "A score, a percentage, or a grade",
        "An answer to a reviewer question",
        "A verdict on the paper as a whole",
    ):
        assert refusal in final_analysis


def test_the_coverage_caveats_are_told_to_survive(final_analysis: str) -> None:
    """The first thing a summarizer drops. A run where one of six sources had
    full text must not produce prose reading as though six were checked."""
    assert "Coverage travels with every statement" in final_analysis
    assert "one of six" in final_analysis
    assert "first thing a summarizer drops" in final_analysis


def test_a_clean_paper_does_not_become_a_good_one(final_analysis: str) -> None:
    """Reporting that the bibliography resolved is a complete answer. It is
    also not a verdict, and the reference has to say so or the model supplies
    one."""
    assert 'not "your paper is good"' in final_analysis
