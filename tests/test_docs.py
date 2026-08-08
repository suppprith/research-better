"""The documentation, and the lint that holds it to the tool's own rules.

Two claims are worth testing rather than trusting. That the example output in
the repository is what the tool actually prints, because a README about
verifying claims carrying invented output would be refuting itself in its own
text. And that the lint bites, because a check nobody has seen fail is a check
nobody knows is running.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from test_packaging import load_script

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
INTEGRITY = ROOT / "docs" / "INTEGRITY.md"
EXAMPLES = ROOT / "examples"

EM_DASH = chr(0x2014)


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def integrity() -> str:
    return INTEGRITY.read_text(encoding="utf-8")


# The worked example ---------------------------------------------------------


def test_the_committed_example_is_what_the_tool_prints() -> None:
    """Regenerating changes nothing.

    Slow, because it runs every pass. Worth it: this is the check that keeps
    the repository's own documentation from drifting away from its behaviour,
    and a stale example is worse than none.
    """
    builder = load_script("build_example")
    for name, body in builder.render().items():
        current = (EXAMPLES / "output" / name).read_text(encoding="utf-8")
        assert current == body, f"examples/output/{name} is stale. Run scripts/build_example.py"


def test_the_example_paper_is_the_fixture() -> None:
    fixture = ROOT / "tests" / "fixtures" / "bad-paper.md"
    assert (EXAMPLES / "paper.md").read_text(encoding="utf-8") == fixture.read_text(
        encoding="utf-8"
    )


def test_the_example_shows_a_report_that_names_its_gaps() -> None:
    report = (EXAMPLES / "output" / "report.md").read_text(encoding="utf-8")
    assert "## Not checked" in report
    assert report.count("\n- ") > 3


def test_the_example_shows_the_audit_leaving_something_alone() -> None:
    # The distinction the trace pass exists to make. An example that only
    # showed flags would teach the wrong thing about it.
    trace = (EXAMPLES / "output" / "trace.md").read_text(encoding="utf-8")
    assert "Looked at, left alone" in trace
    assert "false positive" in trace


def test_the_example_shows_the_edit_pass_refusing_something() -> None:
    edits = (EXAMPLES / "output" / "edits.md").read_text(encoding="utf-8")
    assert "refused" in edits.lower() or "not proposed" in edits.lower()


# The README -----------------------------------------------------------------


def test_the_usage_output_is_copied_from_the_real_run(readme: str) -> None:
    transcript = (EXAMPLES / "output" / "run.txt").read_text(encoding="utf-8")
    summaries = re.findall(r"^(?:ingest|fluff|trace|ask|edit|ground) +\S.*$", readme, re.MULTILINE)
    assert summaries, "the README shows no command output"
    for line in summaries:
        assert line in transcript, f"the README invented this line: {line!r}"


def test_every_pass_is_described(readme: str) -> None:
    from research_better.passes import PASSES

    for name, entry in PASSES.items():
        if entry.implemented:
            assert f"`{name}`" in readme, f"the {name} pass is not in the README"


def test_the_readme_states_the_limits_beside_the_features(readme: str) -> None:
    assert "## Limitations" in readme
    for limit in ("lexical", "not plagiarism detection", "switched off", "default only"):
        assert limit in readme.lower() or limit in readme


def test_the_readme_has_no_em_dash(readme: str) -> None:
    assert EM_DASH not in readme


def test_the_readme_carries_no_percentage(readme: str) -> None:
    assert "%" not in readme


def test_the_readme_has_no_badge_wall_or_emoji_heading(readme: str) -> None:
    headings = [line for line in readme.splitlines() if line.startswith("#")]
    assert all(character.isascii() for heading in headings for character in heading)
    assert "img.shields.io" not in readme


# The integrity document -----------------------------------------------------


def test_the_integrity_doc_covers_every_refusal(integrity: str) -> None:
    for refusal in (
        "No fabricated citations",
        "No claimed check that did not run",
        "No edits to results",
        "No answers to the reviewer questions",
    ):
        assert refusal in integrity


def test_the_integrity_doc_argues_rather_than_asserts(integrity: str) -> None:
    assert "degrade" in integrity or "degrades" in integrity
    assert "laundering tool" in integrity


def test_the_integrity_doc_gives_disclosure_guidance(integrity: str) -> None:
    # Some venues require declaring tool assistance, and a user should hear
    # that from the tool rather than at submission.
    assert "Disclosing" in integrity
    assert "policy of the venue" in integrity


def test_the_disclosure_wording_is_true_of_a_default_run(integrity: str) -> None:
    # The suggested sentence stops being true if somebody uses the tool to
    # write, and the document has to say so beside it.
    assert "No text in this manuscript was generated by" in integrity
    assert "stops being true" in integrity


# The lint -------------------------------------------------------------------


@pytest.fixture
def lint():
    return load_script("lint_prose")


def test_the_repository_passes_its_own_lint(lint) -> None:
    assert lint.check(ROOT) == []


def test_the_lint_catches_an_em_dash(lint, tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text(
        f"A sentence {EM_DASH} and its other half.\n", encoding="utf-8"
    )
    problems = lint.check(tmp_path)
    assert any("em dash" in problem for problem in problems)


def test_the_lint_catches_a_filler_opener(lint, tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text(
        "It is important to note that this works.\n", encoding="utf-8"
    )
    problems = lint.check(tmp_path)
    assert any("filler opener" in problem for problem in problems)


def test_the_filler_list_is_the_tool_own(lint) -> None:
    # Read from the shipped lexicon rather than copied. A phrase the tool tells
    # authors to cut cannot sit in its README, and two lists would drift.
    from research_better.lexicon import load_lexicon

    shipped = {
        term.phrase for section in load_lexicon().family("filler_opener") for term in section.terms
    }
    assert set(lint.filler_openers()) == shipped


def test_a_quoted_phrase_is_allowed(lint, tmp_path: Path) -> None:
    # A rule that names the phrase it forbids has to be able to write it down.
    (tmp_path / "page.md").write_text('Cut "It is important to note that" from the opening.\n')
    assert lint.check(tmp_path) == []


def test_a_fenced_block_is_evidence_rather_than_prose(lint, tmp_path: Path) -> None:
    # A block quoting real output would have to be reworded to satisfy the
    # lint, which would make the documentation wrong.
    (tmp_path / "page.md").write_text(
        "Real output:\n\n```\nIt is important to note that this is what it printed.\n```\n"
    )
    assert lint.check(tmp_path) == []


def test_the_lint_covers_every_markdown_file(lint) -> None:
    checked = {path.relative_to(ROOT).as_posix() for path in lint.iter_checked_files(ROOT)}
    for expected in ("README.md", "CONTRIBUTING.md", "SKILL.md", "docs/INTEGRITY.md"):
        assert expected in checked
