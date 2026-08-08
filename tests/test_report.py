"""The one page, and the check mode that turns it into a gate.

Two things carry the most weight. The page has to fit on a page, because one
that needs scrolling is not read. And it has to name what was not checked,
because silence about a check that did not happen reads as a check that found
nothing, which is the same false assurance as printing a plagiarism score.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_better.artifacts import ArtifactStore
from research_better.cli import EXIT_CLEAN, EXIT_ERROR, EXIT_FINDINGS, main
from research_better.ingest import load
from research_better.report import CheckError, CheckThresholds, Report, build, to_html, to_markdown

ONE_PAGE = 60
"""Lines. A terminal shows about this many, and the point of the page is that
an author sees all of it at once."""

CLEAN_PAPER = """\
# Results

Recall rose from 0.62 to 0.71 with expansion enabled, a gain of nine points.
The cost was one third that of the dense baseline over 5,000 queries.
We saw no gain on the long-tail split, and we report that here.
"""


@pytest.fixture
def draft(tmp_path: Path) -> Path:
    target = tmp_path / "bad-paper.md"
    target.write_bytes((Path(__file__).parent / "fixtures" / "bad-paper.md").read_bytes())
    return target


@pytest.fixture
def analysed(draft: Path) -> Path:
    for command in (
        ["novelty", str(draft), "--confirm-claim"],
        ["ground", str(draft)],
        ["fluff", str(draft)],
        ["voice", str(draft)],
        ["originality", str(draft)],
        ["ask", str(draft)],
        ["edit", str(draft)],
    ):
        main([*command, "--quiet"])
    return draft


@pytest.fixture
def built(analysed: Path) -> Report:
    return build(load(analysed), ArtifactStore(analysed))


# Length ---------------------------------------------------------------------


def test_a_ledger_of_cuts_makes_the_paper_shorter(built: Report, analysed: Path) -> None:
    """The two numbers on the length line have to be the same measure.

    They were not. The budget counts the whole source string, front matter and
    reference list included, and the report subtracted that from a count of
    prose, so the fixture came out nine words longer in the same breath as the
    edit pass reporting a hundred and sixty one words cut.
    """
    ledger = ArtifactStore(analysed).read("edits")
    assert ledger is not None
    assert ledger.payload["words_delta"] < 0

    assert built.words_after is not None
    assert built.words_after < built.words_before
    assert built.words_after - built.words_before == ledger.payload["words_delta"]


def test_no_ledger_means_no_second_number(draft: Path) -> None:
    main(["ingest", str(draft), "--quiet"])
    report = build(load(draft), ArtifactStore(draft))
    assert report.words_before > 0
    assert report.words_after is None


def test_the_page_carries_no_percentage(built: Report) -> None:
    # Counts throughout. The same fact as a share invites being read as a grade
    # for the paper, and a coverage line labelled as coverage did not stop that.
    assert "%" not in to_markdown(built, CheckThresholds())


# The page ------------------------------------------------------------------


def test_the_report_fits_one_page(built: Report) -> None:
    page = to_markdown(built, CheckThresholds())
    assert len(page.splitlines()) <= ONE_PAGE


def test_the_claim_is_stated_first(built: Report) -> None:
    # A wrong reading of the contribution has to be catchable before the author
    # spends any time on the rest of the page.
    body = to_markdown(built).splitlines()
    heading = next(index for index, line in enumerate(body) if line.startswith("# "))
    claim = next(index for index, line in enumerate(body) if "The paper claims" in line)
    assert claim == heading + 2


def test_every_planted_problem_is_represented(built: Report) -> None:
    # The fixture plants one of each. The page carries the shape of the paper's
    # problems, not every individual finding, so this checks that no planted
    # class of problem is missing rather than that each hit is listed.
    assert built.citations["RETRACTED"] >= 1
    assert built.citations["NOT_FOUND"] >= 1
    assert built.citations["TITLE_MISMATCH"] >= 1
    assert built.cuts["orphan paragraphs"] >= 1
    assert built.cuts["mechanical fluff"] >= 1
    assert built.questions["blocking"] >= 1
    assert built.blocking


def test_the_blocking_questions_are_listed_in_full(built: Report) -> None:
    page = to_markdown(built)
    for question in built.blocking:
        assert question in page


def test_counts_are_never_shown_as_a_share(built: Report) -> None:
    page = to_markdown(built, CheckThresholds())
    # A percentage here would be read as a score for the paper whatever it was
    # labelled. The one share the tool does print is retrieval coverage, and it
    # arrives already labelled from the grounding pass.
    for line in page.splitlines():
        if "%" in line and "retrieval coverage" not in line and "target" not in line:
            raise AssertionError(f"a share leaked into the page: {line}")


# What was not checked ------------------------------------------------------


def test_a_pass_that_did_not_run_is_named_with_its_command(draft: Path) -> None:
    report = build(load(draft), ArtifactStore(draft))
    joined = " ".join(report.gaps)
    assert "grounding pass has not run" in joined
    assert "research-better ground bad-paper.md" in joined


def test_a_stale_artifact_is_not_read_and_is_named(analysed: Path) -> None:
    analysed.write_text(analysed.read_text(encoding="utf-8") + "\nOne more.\n", encoding="utf-8")
    report = build(load(analysed), ArtifactStore(analysed))
    assert any("describes an older version" in gap for gap in report.gaps)
    # Not read, rather than read with a warning. A count from the previous draft
    # sitting in a summary is the failure this whole design is against.
    assert not report.citations


def test_an_unconfirmed_claim_is_named_as_a_gap(draft: Path) -> None:
    main(["novelty", str(draft), "--quiet"])
    report = build(load(draft), ArtifactStore(draft))
    assert any("has not been confirmed" in gap for gap in report.gaps)


def test_offline_evidence_is_named_as_a_gap(draft: Path) -> None:
    main(["ground", str(draft), "--offline", "--quiet"])
    report = build(load(draft), ArtifactStore(draft))
    assert any("ran offline" in gap for gap in report.gaps)


def test_a_disabled_rule_is_named(built: Report) -> None:
    # Two structural rules ship off until somebody calibrates them. An author
    # reading a clean page has to know they were never applied.
    assert any("switched off until it has been calibrated" in gap for gap in built.gaps)


def test_the_overlap_check_says_what_it_is_not(built: Report) -> None:
    assert any("not a plagiarism check" in gap for gap in built.gaps)


def test_a_report_with_no_gaps_says_nothing_was_skipped() -> None:
    assert "Nothing was skipped." in to_markdown(Report(draft="paper.md"))


# Formats -------------------------------------------------------------------


def test_the_html_is_one_self_contained_file(built: Report) -> None:
    page = to_html(built, CheckThresholds())
    assert page.startswith("<!doctype html>")
    # No external stylesheet or script, so it opens the same way in a mail
    # client as in a browser.
    assert "<link" not in page
    assert "<script" not in page


def test_the_html_escapes_what_the_paper_says(tmp_path: Path) -> None:
    page = to_html(Report(draft="paper.md", claim="We show that a < b & b < c"))
    assert "&lt; b &amp; b" in page


def test_the_json_payload_carries_the_whole_report(analysed: Path) -> None:
    main(["report", str(analysed), "--quiet"])
    artifact = ArtifactStore(analysed).read("report")
    assert artifact is not None
    payload = artifact.payload["report"]
    assert payload["claim"]
    assert payload["not_checked"]
    assert payload["citations"]


def test_the_command_writes_markdown_and_html(analysed: Path) -> None:
    main(["report", str(analysed), "--quiet"])
    store = ArtifactStore(analysed)
    assert store.path_for("report", ".md").is_file()
    assert store.path_for("report", ".html").is_file()


def test_the_page_is_printed_rather_than_only_filed(
    analysed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["report", str(analysed)])
    assert "## Not checked" in capsys.readouterr().out


def test_html_prints_the_page_as_html(analysed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["report", str(analysed), "--html"])
    assert "<!doctype html>" in capsys.readouterr().out


# Check mode ----------------------------------------------------------------


def test_check_exits_non_zero_on_the_fixture(analysed: Path) -> None:
    assert main(["report", str(analysed), "--check", "--quiet"]) == EXIT_FINDINGS


def test_check_exits_zero_on_a_clean_document(tmp_path: Path) -> None:
    target = tmp_path / "clean.md"
    target.write_text(CLEAN_PAPER, encoding="utf-8")
    assert main(["report", str(target), "--check", "--quiet"]) == EXIT_CLEAN


def test_reading_a_report_without_check_never_fails(analysed: Path) -> None:
    # Reading a report should not fail a build. Asking it to gate one should.
    assert main(["report", str(analysed), "--quiet"]) == EXIT_CLEAN


def test_thresholds_come_from_a_local_config(analysed: Path) -> None:
    (analysed.parent / ".research-better.toml").write_text(
        "max_unverified_citations = 99\nmax_blocking_questions = 99\n", encoding="utf-8"
    )
    assert main(["report", str(analysed), "--check", "--quiet"]) == EXIT_CLEAN


def test_thresholds_come_from_pyproject(analysed: Path) -> None:
    (analysed.parent / "pyproject.toml").write_text(
        "[tool.research-better.check]\nmax_unverified_citations = 99\n"
        "max_blocking_questions = 99\n",
        encoding="utf-8",
    )
    assert main(["report", str(analysed), "--check", "--quiet"]) == EXIT_CLEAN


def test_an_unknown_setting_is_refused_rather_than_ignored(tmp_path: Path) -> None:
    (tmp_path / ".research-better.toml").write_text("max_bad_vibes = 3\n", encoding="utf-8")
    # Silently ignoring it would let somebody believe a limit is in force.
    with pytest.raises(CheckError, match="max_bad_vibes"):
        CheckThresholds.load(tmp_path / "paper.md")


def test_unreadable_config_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "clean.md"
    target.write_text(CLEAN_PAPER, encoding="utf-8")
    (tmp_path / ".research-better.toml").write_text("this is not toml =\n", encoding="utf-8")
    assert main(["report", str(target), "--check", "--quiet"]) == EXIT_ERROR


def test_the_breach_names_the_count_and_the_limit(built: Report) -> None:
    breaches = built.breaches(CheckThresholds())
    assert any("limit 0" in line for line in breaches)


def test_the_page_says_where_its_thresholds_came_from(built: Report) -> None:
    assert "Thresholds from defaults." in to_markdown(built, CheckThresholds())


def test_the_json_output_still_parses(analysed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["report", str(analysed), "--json", "--quiet"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["passes"][0]["pass"] == "report"
