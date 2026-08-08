"""Putting an accepted ledger back into the author's file.

Opt in, never the default. Everything up to here produces a patch and a summary
and touches nothing, because a tool that edits your paper as a side effect of
checking it is a tool you stop running.

Losing an author's unsaved work is the worst thing this could do, so three
things stand between a ledger and a write: a backup taken before any change, a
refusal to overwrite a file with uncommitted changes, and the protected-range
check run again here rather than trusted from plan time. The last is belt and
braces on purpose. A LaTeX file that no longer compiles costs the author an
evening of bisecting, which is far more than the writing problem the edit was
fixing.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from research_better.edit.ledger import Edit, apply_to
from research_better.edit.voicelock import assemble
from research_better.errors import ResearchBetterError
from research_better.model import Document, Span

BACKUP_MARKER = ".rb-backup-"

UNSUPPORTED = {
    ".pdf": (
        "A PDF is a rendering, not a source. Editing one would mean rebuilding a "
        "document this tool only partly understands, and the result would not be "
        "the file you compile from. Read the report and change the source."
    ),
}

TRACKED_CHANGES = {".docx"}
"""Formats written as tracked changes rather than by replacing text.

A Word user has an accept and reject pane they already know, so the edits go
there and the author decides in the tool they were already using."""


class WritebackError(ResearchBetterError):
    """The draft was not written, and why."""


@dataclass(frozen=True, slots=True)
class Written:
    files: tuple[Path, ...]
    backups: tuple[Path, ...]
    words: int

    def to_json(self) -> dict[str, object]:
        return {
            "files": [str(path) for path in self.files],
            "backups": [str(path) for path in self.backups],
            "words": self.words,
        }


# Guards --------------------------------------------------------------------


def refuse_unsupported(path: Path) -> None:
    reason = UNSUPPORTED.get(path.suffix.lower())
    if reason:
        raise WritebackError(f"Cannot write to {path.name}. {reason}")


def uncommitted(path: Path) -> bool | None:
    """Whether git says this file has unsaved changes. None outside a repo.

    A file with uncommitted work has no undo behind it but the backup this tool
    takes, and an author who has not committed for an hour will not think to
    look for one.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", path.name],
            cwd=path.parent,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def assert_still_patchable(document: Document, edits: list[Edit]) -> None:
    """The plan-time protected-range check, run again at write time.

    Deliberately duplicated. The check at plan time keeps a bad row out of the
    ledger; this one keeps a row that arrived some other way, from an edited
    artifact or a caller using the library directly, out of the file.
    """
    for edit in edits:
        document.assert_patchable(
            Span(*edit.char_range),
            f"{edit.id} ({edit.category})",
        )


# Backups -------------------------------------------------------------------


def backup_path(path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return path.with_name(f"{path.name}{BACKUP_MARKER}{stamp}")


def backups_of(path: Path) -> list[Path]:
    """Every backup of this file, oldest first."""
    return sorted(path.parent.glob(f"{path.name}{BACKUP_MARKER}*"))


def take_backup(path: Path) -> Path:
    target = backup_path(path)
    target.write_bytes(path.read_bytes())
    return target


def revert(path: Path) -> Path:
    """Restore the most recent backup, keeping it in place.

    The backup is not deleted. Somebody reverting is already having a bad time,
    and taking away the only copy of what they reverted from would be a poor
    moment to save a kilobyte.
    """
    found = backups_of(path)
    if not found:
        raise WritebackError(
            f"No backup of {path.name} to restore. Backups are written beside the "
            f"draft as {path.name}{BACKUP_MARKER}<timestamp> when --apply runs."
        )
    newest = found[-1]
    path.write_bytes(newest.read_bytes())
    return newest


# Writing -------------------------------------------------------------------


def _by_file(document: Document, edits: list[Edit]) -> dict[str, list[tuple[int, int, Edit]]]:
    """Rows grouped by the file they actually live in.

    A LaTeX paper is normally written across several files pulled together with
    an input command. Analysis sees one text; a patch has to go back to the file
    the characters came from, at that file's own offsets.
    """
    grouped: dict[str, list[tuple[int, int, Edit]]] = defaultdict(list)
    for edit in edits:
        try:
            file, start, end = document.locate(Span(*edit.char_range))
        except ValueError as error:
            raise WritebackError(
                f"Cannot place {edit.id} on disk: {error}. Nothing was written."
            ) from None
        grouped[file].append((start, end, edit))
    return grouped


def apply(
    document: Document,
    edits: list[Edit],
    force: bool = False,
    target_reduction: float = 0.0,
) -> Written:
    """Write the ledger to the source, after taking a backup of every file.

    Raises before touching anything if the format cannot be written, a row
    lands in protected source, the result would be longer than the original, or
    a file has uncommitted changes and `force` was not given.
    """
    refuse_unsupported(document.path)
    assert_still_patchable(document, edits)

    # Assembled once over the whole document, so the word budget is checked
    # against the paper rather than against whichever file a row happened to
    # land in.
    words = len(assemble(document, edits, target_reduction).split())

    if document.path.suffix.lower() in TRACKED_CHANGES:
        return _tracked_changes(document, edits, words, force)

    grouped = _by_file(document, edits)
    targets = [Path(name) for name in sorted(grouped)]

    for target in targets:
        if uncommitted(target) and not force:
            raise WritebackError(
                f"{target.name} has uncommitted changes. Applying would overwrite work "
                f"that git cannot give back. Commit or stash first, or pass --force if "
                f"you have another copy."
            )

    backups = tuple(take_backup(target) for target in targets)
    for target in targets:
        rows = grouped[str(target)]
        text = target.read_bytes().decode("utf-8")
        patched = apply_to(text, [_relocated(edit, start, end) for start, end, edit in rows])
        target.write_text(patched, encoding="utf-8", newline="")

    return Written(files=tuple(targets), backups=backups, words=words)


def _tracked_changes(document: Document, edits: list[Edit], words: int, force: bool) -> Written:
    """Word, written through the tracked-changes writer.

    Single file by construction, and it goes through the same dirty check and
    the same backup as every other format. Losing unsaved work is no less bad
    for being lost in a zip.
    """
    from research_better.edit import word

    target = Path(document.path)
    if uncommitted(target) and not force:
        raise WritebackError(
            f"{target.name} has uncommitted changes. Applying would overwrite work "
            f"that git cannot give back. Commit or stash first, or pass --force if "
            f"you have another copy."
        )

    backup = take_backup(target)
    word.apply(document, edits)
    return Written(files=(target,), backups=(backup,), words=words)


def _relocated(edit: Edit, start: int, end: int) -> Edit:
    return replace(edit, char_range=(start, end))
