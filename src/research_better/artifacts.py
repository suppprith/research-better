"""The on-disk contract every pass reads and writes through.

Artifacts live in `.research-better/` next to the draft, so they travel with
the paper and a `git clean` never takes work with it that the author wanted.

Every artifact carries the hash of the draft it was produced from and the
version of the tool that produced it. That is the whole point of the envelope.
A grounding check that verified twelve citations is worthless once the author
has rewritten the paragraph those citations sat in, and the failure mode
without a hash is silent: the report still lists twelve verified citations and
nobody knows they refer to text that no longer exists.

So a pass reading a stale artifact warns and names the file. The edit pass
refuses outright, because applying a patch computed against text that has since
changed is how a tool corrupts a paper.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_better import __version__
from research_better.errors import ResearchBetterError

ARTIFACT_DIRECTORY = ".research-better"
CACHE_DIRECTORY = "cache"


class StaleArtifactError(ResearchBetterError):
    """An artifact was produced from a different draft than the one on disk."""

    def __init__(self, name: str, path: Path, source_file: str) -> None:
        self.name = name
        self.path = path
        super().__init__(
            f"{path.name} was produced from an older version of {source_file}. "
            f"Applying it could patch text that no longer exists. "
            f"Rerun the passes that produced it first."
        )


@dataclass(frozen=True, slots=True)
class Artifact:
    name: str
    tool_version: str
    source_hash: str
    source_file: str
    created_at: str
    payload: Any
    offline: bool = False
    """Whether the run that produced this was forbidden from reaching the
    network. A grounding result produced offline checked a citation against
    whatever was cached, which is not the same claim as checking it against the
    live literature, and the report has to be able to tell them apart."""

    def is_stale(self, source_hash: str) -> bool:
        return self.source_hash != source_hash

    def from_a_different_tool_version(self) -> bool:
        return self.tool_version != __version__

    def to_json(self) -> dict[str, Any]:
        return {
            "artifact": self.name,
            "tool_version": self.tool_version,
            "source_hash": self.source_hash,
            "source_file": self.source_file,
            "created_at": self.created_at,
            "offline": self.offline,
            "payload": self.payload,
        }


class ArtifactStore:
    """`.research-better/` beside a draft."""

    def __init__(self, draft: Path) -> None:
        self.draft = Path(draft)
        self.root = self.draft.parent / ARTIFACT_DIRECTORY

    @property
    def cache(self) -> Path:
        return self.root / CACHE_DIRECTORY

    def path_for(self, name: str, suffix: str = ".json") -> Path:
        return self.root / f"{name}{suffix}"

    def existing(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(path for path in self.root.glob("*.json") if path.is_file())

    # Writing ---------------------------------------------------------------

    def write(self, name: str, payload: Any, source_hash: str, offline: bool = False) -> Path:
        artifact = Artifact(
            name=name,
            tool_version=__version__,
            source_hash=source_hash,
            source_file=self.draft.name,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            payload=payload,
            offline=offline,
        )
        target = self.path_for(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(artifact.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return target

    def write_text(self, name: str, body: str, source_hash: str, suffix: str = ".md") -> Path:
        """Write a human-readable artifact carrying the same provenance header.

        Markdown cannot hold the JSON envelope, so the same four fields go in a
        comment. A reader who opens report.md still learns which draft it
        describes.

        The comment syntax follows the suffix. A patch has to survive `git
        apply`, which skips `#` preamble lines and would choke on markup, so
        provenance is never bought at the cost of the file being usable.
        """
        target = self.path_for(name, suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        provenance = (
            f"research-better {__version__} | source: {self.draft.name} | "
            f"hash: {source_hash[:16]} | generated: "
            f"{datetime.now(UTC).isoformat(timespec='seconds')}"
        )
        header = f"<!-- {provenance} -->\n\n" if suffix == ".md" else f"# {provenance}\n"
        target.write_text(header + body, encoding="utf-8", newline="\n")
        return target

    # Reading ---------------------------------------------------------------

    def read(self, name: str) -> Artifact | None:
        target = self.path_for(name)
        if not target.is_file():
            return None
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ResearchBetterError(f"{target} is not readable as JSON: {error}") from None
        return Artifact(
            name=raw.get("artifact", name),
            tool_version=raw.get("tool_version", "unknown"),
            source_hash=raw.get("source_hash", ""),
            source_file=raw.get("source_file", self.draft.name),
            created_at=raw.get("created_at", ""),
            payload=raw.get("payload"),
            offline=bool(raw.get("offline", False)),
        )

    def require_fresh(self, name: str, source_hash: str) -> Artifact:
        """Read an artifact, refusing a stale one.

        Used by the edit pass, which turns findings into changes on disk. A
        warning is the right response to reading stale analysis. It is the
        wrong response to writing from it.
        """
        artifact = self.read(name)
        if artifact is None:
            raise ResearchBetterError(
                f"{self.path_for(name).name} does not exist. Run the {name} pass first."
            )
        if artifact.is_stale(source_hash):
            raise StaleArtifactError(name, self.path_for(name), self.draft.name)
        return artifact

    def stale_warnings(self, source_hash: str) -> list[str]:
        """One line per artifact that no longer matches the draft."""
        warnings: list[str] = []
        for path in self.existing():
            artifact = self.read(path.stem)
            if artifact is None:
                continue
            if artifact.source_file != self.draft.name:
                # The store is flat and sits beside the draft, so two papers in
                # one directory share it. Saying this artifact is a stale copy
                # of the current draft would be a false statement about a file
                # that is simply somebody else's.
                warnings.append(
                    f"{path.name} was produced from {artifact.source_file}, not "
                    f"{self.draft.name}. Running a pass here will overwrite it."
                )
            elif artifact.is_stale(source_hash):
                warnings.append(
                    f"{path.name} was produced from an older version of "
                    f"{self.draft.name} and is out of date"
                )
            elif artifact.from_a_different_tool_version():
                warnings.append(
                    f"{path.name} was produced by research-better "
                    f"{artifact.tool_version}, this is {__version__}"
                )
        return warnings
