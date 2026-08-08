"""Writing an accepted ledger back into the author's file.

Losing somebody's unsaved work is the worst thing this tool could do, so most
of these tests are about the paths where nothing gets written: the wrong
format, a row landing in source the format cannot survive, a file with
uncommitted changes, a result longer than the original.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from research_better import fluff, novelty, voice
from research_better.artifacts import Artifact, ArtifactStore
from research_better.cli import EXIT_CLEAN, EXIT_ERROR, EXIT_FINDINGS, main
from research_better.edit import ledger, voicelock, writeback
from research_better.edit.gate import EvidenceBundle, evidence_ids
from research_better.edit.ledger import Category, Edit, Ledger
from research_better.edit.writeback import WritebackError
from research_better.errors import ProtectedRangeError
from research_better.ingest import load
from research_better.model import Document

FIXTURES = Path(__file__).parent / "fixtures"


def bundle_for(document: Document) -> EvidenceBundle:
    """The evidence a ledger needs, without going through the artifact store."""
    payloads = {
        "fluff": [finding.to_json() for finding in fluff.analyse(document)],
        "novelty": novelty.analyse(document, confirmed=True).to_json(),
        "voice": voice.extract(document).to_json(),
    }
    return EvidenceBundle(
        source_hash=document.source_hash,
        artifacts={
            name: Artifact(name, "0.1.0", document.source_hash, document.path.name, "", payload)
            for name, payload in payloads.items()
        },
        pointers=frozenset(
            pointer for name, payload in payloads.items() for pointer in evidence_ids(name, payload)
        ),
        offline=True,
    )


def ledger_for(document: Document) -> Ledger:
    lock = voicelock.VoiceLock.of(document, voice.extract(document).to_json())
    return ledger.build(document, bundle_for(document), screen=voicelock.screen(lock))


@pytest.fixture
def draft(tmp_path: Path) -> Path:
    target = tmp_path / "bad-paper.md"
    target.write_bytes((FIXTURES / "bad-paper.md").read_bytes())
    return target


@pytest.fixture
def ready(draft: Path) -> Path:
    main(["novelty", str(draft), "--confirm-claim", "--quiet"])
    main(["ground", str(draft), "--quiet"])
    main(["fluff", str(draft), "--quiet"])
    main(["voice", str(draft), "--quiet"])
    return draft


# Backups ------------------------------------------------------------------


def test_a_backup_exists_before_any_write(draft: Path) -> None:
    original = draft.read_bytes()
    document = load(draft)

    written = writeback.apply(document, list(ledger_for(document).edits))

    assert written.backups
    assert written.backups[0].read_bytes() == original
    assert draft.read_bytes() != original


def test_the_backup_name_says_what_it_is(draft: Path) -> None:
    document = load(draft)
    written = writeback.apply(document, list(ledger_for(document).edits))
    assert written.backups[0].name.startswith("bad-paper.md.rb-backup-")


def test_revert_restores_the_most_recent_backup(draft: Path) -> None:
    original = draft.read_text(encoding="utf-8")
    document = load(draft)
    writeback.apply(document, list(ledger_for(document).edits))

    writeback.revert(draft)
    assert draft.read_text(encoding="utf-8") == original


def test_revert_keeps_the_backup_it_restored_from(draft: Path) -> None:
    document = load(draft)
    writeback.apply(document, list(ledger_for(document).edits))
    restored = writeback.revert(draft)
    # Somebody reverting is already having a bad time. Taking away the only copy
    # of what they reverted from would be a poor moment to save a kilobyte.
    assert restored.is_file()


def test_revert_with_nothing_to_restore_says_where_backups_come_from(draft: Path) -> None:
    with pytest.raises(WritebackError, match="rb-backup"):
        writeback.revert(draft)


def test_the_revert_command_reports_the_file_it_restored(
    draft: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = load(draft)
    writeback.apply(document, list(ledger_for(document).edits))

    assert main(["revert", str(draft)]) == EXIT_CLEAN
    assert "restored from" in capsys.readouterr().out


# Formats that cannot be written -------------------------------------------


def test_apply_to_a_pdf_points_at_the_report() -> None:
    # A PDF is a rendering, not a source. Rebuilding one would produce a file
    # the author does not compile from.
    with pytest.raises(WritebackError, match="Read the report"):
        writeback.refuse_unsupported(Path("paper.pdf"))


def test_a_word_file_is_written_as_tracked_changes_not_replacements() -> None:
    # Word goes through its own writer rather than through span replacement.
    # See test_word.py.
    assert writeback.refuse_unsupported(Path("paper.docx")) is None
    assert ".docx" in writeback.TRACKED_CHANGES


def test_a_markdown_draft_is_writable() -> None:
    assert writeback.refuse_unsupported(Path("paper.md")) is None


# Guards -------------------------------------------------------------------


def test_a_row_landing_in_protected_source_is_refused_at_write_time(tmp_path: Path) -> None:
    target = tmp_path / "compilable.tex"
    target.write_bytes((FIXTURES / "latex" / "compilable.tex").read_bytes())
    document = load(target)

    protected = document.protected[0]
    row = Edit(
        span_id="s-000000000001",
        category=Category.CUT,
        original=document.text_of(protected),
        proposed="",
        reason="Test.",
        evidence="fluff:test@0-1",
        confidence=0.9,
        char_range=(protected.char_start, protected.char_end),
    )
    # The plan-time check keeps a bad row out of the ledger. This one keeps a
    # row that arrived some other way out of the file.
    with pytest.raises(ProtectedRangeError):
        writeback.apply(document, [row])
    assert not writeback.backups_of(target)


def test_a_result_longer_than_the_original_is_refused_before_writing(draft: Path) -> None:
    original = draft.read_bytes()
    document = load(draft)
    grew = Edit(
        span_id="s-000000000001",
        category=Category.GROUND,
        original=document.source_text[:10],
        proposed="one two three four five six seven eight nine ten eleven twelve",
        reason="Test.",
        evidence="fluff:test@0-1",
        confidence=0.9,
        char_range=(0, 10),
    )
    with pytest.raises(voicelock.WordBudgetError):
        writeback.apply(document, [grew])
    assert draft.read_bytes() == original


def test_uncommitted_changes_stop_a_write(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    target = repo / "paper.md"
    target.write_bytes((FIXTURES / "bad-paper.md").read_bytes())

    document = load(target)
    with pytest.raises(WritebackError, match="uncommitted changes"):
        writeback.apply(document, list(ledger_for(document).edits))


def test_force_writes_anyway(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    target = repo / "paper.md"
    target.write_bytes((FIXTURES / "bad-paper.md").read_bytes())

    document = load(target)
    written = writeback.apply(document, list(ledger_for(document).edits), force=True)
    # A backup is still taken. Force means git cannot give the original back,
    # not that nothing can.
    assert written.backups[0].is_file()


def test_a_file_outside_a_repo_is_not_treated_as_dirty(draft: Path) -> None:
    assert writeback.uncommitted(draft) is None


# Multi-file ---------------------------------------------------------------


def test_a_row_is_written_to_the_file_its_text_came_from(tmp_path: Path) -> None:
    for name in ("paper.tex", "method.tex", "refs.bib"):
        shutil.copy(FIXTURES / "latex" / name, tmp_path / name)
    document = load(tmp_path / "paper.tex")
    assert document.file_segments, "the fixture has to be assembled from more than one file"

    root = document.source_text
    inside_method = next(
        segment for segment in document.file_segments if segment.file.endswith("method.tex")
    )
    needle = "The scoring function above"
    start = root.index(needle, inside_method.global_start)
    row = Edit(
        span_id="s-000000000001",
        category=Category.CUT,
        original=root[start : start + len(needle)],
        proposed="",
        reason="Test.",
        evidence="fluff:test@0-1",
        confidence=0.9,
        char_range=(start, start + len(needle)),
    )

    written = writeback.apply(document, [row], force=True)
    # A patch has to go back to the file the characters came from, not to the
    # root file that pulled them in.
    assert [path.name for path in written.files] == ["method.tex"]
    assert needle not in (tmp_path / "method.tex").read_text(encoding="utf-8")
    assert needle not in (tmp_path / "paper.tex").read_text(encoding="utf-8")


# The command --------------------------------------------------------------


def test_without_apply_the_draft_is_untouched(ready: Path) -> None:
    before = ready.read_bytes()
    assert main(["edit", str(ready), "--quiet"]) == EXIT_FINDINGS
    assert ready.read_bytes() == before
    assert not writeback.backups_of(ready)


def test_apply_writes_the_draft_and_records_it(ready: Path) -> None:
    before = ready.read_bytes()
    assert main(["edit", str(ready), "--apply", "--quiet"]) == EXIT_FINDINGS

    assert ready.read_bytes() != before
    assert writeback.backups_of(ready)
    artifact = ArtifactStore(ready).read("edits")
    assert artifact is not None
    assert artifact.payload["written"]["files"]


def test_apply_says_the_artifacts_now_describe_the_old_draft(
    ready: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["edit", str(ready), "--apply"])
    # Cheaper to say now than to let the next run's staleness warning arrive
    # after the author has moved on.
    assert "Rerun the passes" in capsys.readouterr().out


def test_applying_to_a_pdf_fails_cleanly(tmp_path: Path) -> None:
    target = tmp_path / "paper.pdf"
    target.write_bytes(b"%PDF-1.4\n")
    assert main(["edit", str(target), "--apply", "--quiet"]) == EXIT_ERROR


# The compile ---------------------------------------------------------------


def test_an_applied_latex_ledger_leaves_every_protected_range_intact(tmp_path: Path) -> None:
    """The compile below is the real check, and it only runs where LaTeX is
    installed. This one runs everywhere, so a change that starts editing math
    fails on somebody's laptop rather than waiting for CI."""
    target = tmp_path / "compilable.tex"
    target.write_bytes((FIXTURES / "latex" / "compilable.tex").read_bytes())
    document = load(target)

    rows = list(ledger_for(document).edits)
    assert rows, "an empty ledger would make this test prove nothing"
    guarded = [document.text_of(region) for region in document.protected]
    writeback.apply(document, rows)

    after = target.read_text(encoding="utf-8")
    for region in guarded:
        assert region in after


@pytest.mark.latex
def test_a_latex_draft_still_compiles_after_the_ledger_is_applied(tmp_path: Path) -> None:
    target = tmp_path / "compilable.tex"
    target.write_bytes((FIXTURES / "latex" / "compilable.tex").read_bytes())

    assert _compiles(target), "the fixture has to compile before the test means anything"

    document = load(target)
    rows = list(ledger_for(document).edits)
    assert rows, "an empty ledger would make this test prove nothing"
    writeback.apply(document, rows)

    # An actual compile, not an assumption. A LaTeX file that no longer builds
    # costs the author an evening of bisecting.
    assert _compiles(target)


def _compiles(target: Path) -> bool:
    result = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", target.name],
        cwd=target.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout[-4000:])
    return result.returncode == 0 and target.with_suffix(".pdf").is_file()


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
    ):
        subprocess.run(command, cwd=repo, check=True, capture_output=True)
    return repo
