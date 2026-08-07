"""Format adapters and the dispatch that picks one.

An adapter reads bytes and produces a `Document`. Nothing past this package
knows what format a paper was written in.

Adapters whose parser lives in an optional extra are imported here, at call
time, so `import research_better` stays cheap and a missing extra produces an
error naming the install command rather than an ImportError at startup.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path

from research_better.errors import UnsupportedFormatError
from research_better.model import Document


@dataclass(frozen=True, slots=True)
class Adapter:
    """Where an adapter lives and what it costs to use."""

    module: str
    format: str
    extra: str | None = None


ADAPTERS: dict[str, Adapter] = {
    ".md": Adapter("research_better.ingest.markdown", "markdown"),
    ".markdown": Adapter("research_better.ingest.markdown", "markdown"),
    ".tex": Adapter("research_better.ingest.latex", "latex", extra="latex"),
    ".ltx": Adapter("research_better.ingest.latex", "latex", extra="latex"),
}


def supported_suffixes() -> list[str]:
    return sorted(ADAPTERS)


def read_source(path: Path) -> str:
    """Decode a file without touching its line endings.

    `Path.read_text` translates CRLF to LF, which would put every span two
    characters off on a Windows-authored file and break byte-exact round trip.
    """
    return path.read_bytes().decode("utf-8")


def load(path: Path | str, text: str | None = None) -> Document:
    """Ingest a paper, choosing the adapter by file extension.

    Args:
        path: Path to the paper. Used for dispatch and for span attribution.
        text: Source text, if it has already been read. Mostly for tests.
    """
    path = Path(path)
    adapter = ADAPTERS.get(path.suffix.lower())
    if adapter is None:
        raise UnsupportedFormatError(path.suffix or "(no extension)", supported_suffixes())

    module = importlib.import_module(adapter.module)
    source = read_source(path) if text is None else text
    document: Document = module.ingest(path, source)
    return document


def emit(document: Document) -> str:
    """Re-emit a document as source text.

    This returns the source unchanged, and that is the guarantee rather than a
    shortcut. The tool proposes patches against byte ranges and never rewrites
    a file from its own model, so a formatting detail the parser did not
    understand cannot be lost by round tripping through it.
    """
    return document.source_text
