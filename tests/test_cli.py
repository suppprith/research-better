"""The command surface, and the exit codes that make it usable in CI.

The distinction between exit 1 and exit 2 carries the weight. A build that
fails because the paper has problems and a build that fails because the tool
broke are different events, and collapsing them teaches people to ignore both.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_better import __version__
from research_better.artifacts import ArtifactStore
from research_better.cli import EXIT_CLEAN, EXIT_ERROR, EXIT_FINDINGS, main
from research_better.passes import PASSES, RUN_ORDER

CLEAN_PAPER = """\
# Results

Recall rose from 0.62 to 0.71 with expansion enabled, a gain of nine points.
The cost was one third that of the dense baseline over 5,000 queries.
We saw no gain on the long-tail split.
"""


@pytest.fixture
def draft(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "bad-paper.md"
    target = tmp_path / "bad-paper.md"
    target.write_bytes(source.read_bytes())
    return target


@pytest.fixture
def clean_draft(tmp_path: Path) -> Path:
    target = tmp_path / "clean.md"
    target.write_text(CLEAN_PAPER, encoding="utf-8")
    return target


# Exit codes ---------------------------------------------------------------


def test_findings_exit_one(draft: Path) -> None:
    assert main(["fluff", str(draft), "--quiet"]) == EXIT_FINDINGS


def test_no_findings_exit_zero(clean_draft: Path) -> None:
    assert main(["fluff", str(clean_draft), "--quiet"]) == EXIT_CLEAN


def test_a_tool_error_exits_two(tmp_path: Path) -> None:
    assert main(["fluff", str(tmp_path / "absent.md"), "--quiet"]) == EXIT_ERROR


def test_an_unreadable_format_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "paper.rtf"
    target.write_text("body", encoding="utf-8")
    assert main(["ingest", str(target), "--quiet"]) == EXIT_ERROR


def test_ingest_alone_never_reports_findings(draft: Path) -> None:
    # Ingest parses. It has no opinion, so it cannot fail a CI check.
    assert main(["ingest", str(draft), "--quiet"]) == EXIT_CLEAN


# Artifacts ----------------------------------------------------------------


def test_each_implemented_pass_writes_its_artifact(draft: Path) -> None:
    store = ArtifactStore(draft)
    for name, entry in PASSES.items():
        if not entry.implemented:
            continue
        main([name, str(draft), "--quiet"])
        assert store.path_for(entry.artifact).is_file(), f"{name} wrote no artifact"


def test_run_executes_every_implemented_pass(draft: Path) -> None:
    assert main(["run", str(draft), "--quiet"]) == EXIT_FINDINGS
    store = ArtifactStore(draft)
    for name in RUN_ORDER:
        entry = PASSES[name]
        assert store.path_for(entry.artifact).is_file() is entry.implemented


def test_ingest_runs_before_the_passes_that_read_it() -> None:
    assert RUN_ORDER[0] == "ingest"
    # Voice constrains any pass that could propose words, so it has to exist
    # before one does.
    assert RUN_ORDER.index("voice") < RUN_ORDER.index("edit")


def test_an_artifact_records_the_hash_of_the_draft_it_came_from(draft: Path) -> None:
    main(["ingest", str(draft), "--quiet"])
    artifact = ArtifactStore(draft).read("paper")
    assert artifact is not None
    assert artifact.source_hash
    assert artifact.payload["source_hash"] == artifact.source_hash


# Passes that are not built yet --------------------------------------------


def test_an_unbuilt_pass_refuses_rather_than_writing_an_empty_artifact(
    draft: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["ask", str(draft), "--quiet"]) == EXIT_ERROR
    message = capsys.readouterr().err
    assert "not built yet" in message
    assert "P4" in message
    # An empty reviewer-questions artifact looks exactly like a reviewer pass
    # that found nothing to ask, which is the false assurance this tool must
    # not give.
    assert not ArtifactStore(draft).path_for("reviewer-questions").exists()


@pytest.mark.parametrize("name", sorted(n for n, p in PASSES.items() if not p.implemented))
def test_every_unbuilt_pass_names_the_phase_it_lands_in(
    name: str, draft: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([name, str(draft), "--quiet"]) == EXIT_ERROR
    assert PASSES[name].phase in capsys.readouterr().err


def test_run_says_which_passes_did_not_run(draft: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["run", str(draft)])
    output = capsys.readouterr().out
    # Silence about an unrun pass reads as a clean result. Same commitment as
    # never printing a total score.
    assert "not checked" in output
    for name in ("novelty", "ask", "edit", "report"):
        assert name in output


# Staleness ----------------------------------------------------------------


def test_a_stale_artifact_warns_and_names_the_file(
    draft: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["ingest", str(draft), "--quiet"])
    capsys.readouterr()

    draft.write_text(draft.read_text(encoding="utf-8") + "\nA new sentence.\n", encoding="utf-8")
    main(["ingest", str(draft), "--quiet"])

    warning = capsys.readouterr().err
    assert "paper.json" in warning
    assert "out of date" in warning


def test_warnings_survive_quiet(draft: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["ingest", str(draft), "--quiet"])
    capsys.readouterr()
    draft.write_text(draft.read_text(encoding="utf-8") + "\nAnother.\n", encoding="utf-8")

    main(["ingest", str(draft), "--quiet"])
    captured = capsys.readouterr()
    # Suppressing the news that an artifact is out of date is how somebody
    # trusts a stale report.
    assert captured.out == ""
    assert "out of date" in captured.err


# Flags --------------------------------------------------------------------


def test_json_output_is_machine_readable(
    clean_draft: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["fluff", str(clean_draft), "--json", "--quiet"]) == EXIT_CLEAN
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == EXIT_CLEAN
    assert payload["passes"][0]["pass"] == "fluff"


def test_quiet_prints_nothing_on_success(
    clean_draft: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["fluff", str(clean_draft), "--quiet"])
    assert capsys.readouterr().out == ""


def test_verbose_names_the_file_it_wrote(
    clean_draft: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["fluff", str(clean_draft), "--verbose"])
    assert "fluff.json" in capsys.readouterr().out


def test_no_color_strips_escapes(clean_draft: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["fluff", str(clean_draft), "--no-color"])
    assert "\033[" not in capsys.readouterr().out


def test_format_override_reads_a_draft_with_the_wrong_extension(tmp_path: Path) -> None:
    target = tmp_path / "paper.txt"
    target.write_text(CLEAN_PAPER, encoding="utf-8")
    assert main(["ingest", str(target), "--format", "markdown", "--quiet"]) == EXIT_CLEAN


def test_an_unknown_format_override_exits_two(clean_draft: Path) -> None:
    assert main(["ingest", str(clean_draft), "--format", "wordperfect", "--quiet"]) == EXIT_ERROR


def test_offline_is_recorded_in_the_artifact(clean_draft: Path) -> None:
    main(["fluff", str(clean_draft), "--offline", "--quiet"])
    artifact = ArtifactStore(clean_draft).read("fluff")
    assert artifact is not None
    # A grounding result produced offline checked a citation against whatever
    # was cached, which is a different claim from checking the live literature.
    assert artifact.offline is True


def test_a_normal_run_is_not_marked_offline(clean_draft: Path) -> None:
    main(["fluff", str(clean_draft), "--quiet"])
    artifact = ArtifactStore(clean_draft).read("fluff")
    assert artifact is not None
    assert artifact.offline is False


def test_offline_is_accepted(clean_draft: Path) -> None:
    # Nothing reaches the network yet, so this flag changes no behaviour today.
    # It is parsed now so the contract exists before the pass that honours it.
    assert main(["fluff", str(clean_draft), "--offline", "--quiet"]) == EXIT_CLEAN


# Surface ------------------------------------------------------------------


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == EXIT_CLEAN
    assert __version__ in capsys.readouterr().out


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_CLEAN
    assert "usage: research-better" in capsys.readouterr().out


def test_every_registered_pass_has_a_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    main([])
    help_text = capsys.readouterr().out
    for name in PASSES:
        assert name in help_text
    assert "run" in help_text


def test_edit_accepts_apply_and_report_accepts_check(draft: Path) -> None:
    # Both refuse for now, but the surface has to be stable before the passes
    # land behind it.
    assert main(["edit", str(draft), "--apply", "--quiet"]) == EXIT_ERROR
    assert main(["report", str(draft), "--check", "--quiet"]) == EXIT_ERROR
