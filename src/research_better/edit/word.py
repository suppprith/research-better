"""Applying a ledger to a Word file as tracked changes.

A Word user reviewing a unified diff in a terminal is not a real workflow. They
have an accept and reject pane they already know, so the edits arrive there,
attributed and dated, and the author decides in the tool they were already
using. That is more work than replacing text and it is the whole reason Word
support is worth having.

Nothing is rewritten. A deletion splits the run that held the text and wraps
the removed part in `w:del`, keeping the original formatting on every piece. A
replacement adds a `w:ins` beside it. The rest of the package is untouched, so
a style, a field, or a content control this module never looked at survives
exactly as Word wrote it.

The offset map comes from re-extracting the file rather than from anything
stored. If the extracted text no longer matches the draft the ledger was
computed against, this refuses. A ledger applied to a file somebody has edited
since would delete the wrong words while looking entirely successful.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_better.edit.ledger import Edit
from research_better.errors import ResearchBetterError
from research_better.extras import require
from research_better.ingest.word import TextSlice, W, extract
from research_better.model import Document

AUTHOR = "research-better"

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


class WordWritebackError(ResearchBetterError):
    """The Word file was not written, and why."""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new(tag: str) -> Any:
    from docx.oxml import parse_xml

    namespace = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    return parse_xml(f"<w:{tag} {namespace}/>")


def _run_with(template: Any, tag: str, text: str) -> Any:
    """A copy of a run carrying different text.

    Copied rather than built, so the font, size, and every other run property
    the author set survives the split. A tracked change that silently restyles
    a sentence is a change the author cannot see in the review pane.
    """
    from copy import deepcopy

    run = deepcopy(template)
    for child in list(run):
        if child.tag in {f"{W}t", f"{W}delText"}:
            run.remove(child)
    node = _new(tag)
    node.text = text
    node.set(XML_SPACE, "preserve")
    run.append(node)
    return run


def _tracked(kind: str, revision: int, children: list[Any]) -> Any:
    element = _new(kind)
    element.set(f"{W}id", str(revision))
    element.set(f"{W}author", AUTHOR)
    element.set(f"{W}date", _now())
    for child in children:
        element.append(child)
    return element


def _cuts_by_text_element(
    document: Document, edits: list[Edit], extraction: Any
) -> dict[tuple[int, int], list[tuple[int, int, str]]]:
    """Every edit, resolved down to ranges inside individual `w:t` elements.

    An edit can span several runs, so the replacement text is attached to the
    first piece and the rest are pure deletions. Keyed by (paragraph, text) so
    one element is rewritten once however many edits touch it.
    """
    pieces: dict[tuple[int, int], list[tuple[int, int, str]]] = defaultdict(list)
    for edit in edits:
        start, end = edit.char_range
        covering: list[TextSlice] = extraction.slices_covering(start, end)
        if not covering:
            raise WordWritebackError(
                f"Edit {edit.id} covers no text in the document. Nothing was written."
            )
        for position, item in enumerate(covering):
            low = max(start, item.char_start) - item.char_start
            high = min(end, item.char_end) - item.char_start
            replacement = edit.proposed if position == 0 else ""
            pieces[(item.paragraph, item.text)].append((low, high, replacement))
    return pieces


def _rewrite(text_element: Any, cuts: list[tuple[int, int, str]], revision: int) -> int:
    """Replace one `w:t` and its run with a tracked sequence."""
    run = text_element.getparent()
    parent = run.getparent()
    if parent is None:
        raise WordWritebackError("A run to edit is not attached to a paragraph.")

    original = text_element.text or ""
    position = list(parent).index(run)
    parent.remove(run)

    produced: list[Any] = []
    cursor = 0
    for low, high, replacement in sorted(cuts):
        if low > cursor:
            produced.append(_run_with(run, "t", original[cursor:low]))
        if replacement:
            produced.append(_tracked("ins", revision, [_run_with(run, "t", replacement)]))
            revision += 1
        produced.append(_tracked("del", revision, [_run_with(run, "delText", original[low:high])]))
        revision += 1
        cursor = high
    if cursor < len(original):
        produced.append(_run_with(run, "t", original[cursor:]))

    for offset, element in enumerate(produced):
        parent.insert(position + offset, element)
    return revision


def apply(document: Document, edits: list[Edit]) -> Path:
    """Write the ledger into the `.docx` as tracked changes.

    Refuses before touching the file if the document on disk no longer produces
    the text the ledger was computed against.
    """
    docx = require("docx", "docx", "Word writeback")
    path = Path(document.path)

    extraction = extract(path)
    if extraction.text != document.source_text:
        raise WordWritebackError(
            f"{path.name} no longer extracts to the text this ledger was computed "
            f"against. Applying it would delete the wrong words while looking "
            f"entirely successful. Rerun the passes and try again."
        )

    pieces = _cuts_by_text_element(document, edits, extraction)
    if not pieces:
        return path

    package = docx.Document(str(path))
    paragraphs = list(package.element.body.iter(f"{W}p"))
    revision = 1000

    # Later elements first, so rewriting one does not move the index of another
    # that has not been handled yet.
    for paragraph_index, text_index in sorted(pieces, reverse=True):
        texts = list(paragraphs[paragraph_index].iter(f"{W}t"))
        revision = _rewrite(texts[text_index], pieces[(paragraph_index, text_index)], revision)

    package.save(str(path))
    return path
