"""Word ingest.

Many researchers write in Word because the Springer and Elsevier templates are
Word, and a tool that cannot read their file is a tool they cannot use.

Word is the first format with no linear source text. A `.docx` is a zip of XML,
so `Document.source_text` here is the prose this module extracts, and every
character of it is mapped back to the `w:t` element it came from. That map is
what makes byte-range patching work against a format that has no bytes to
range over: the edit layer proposes offsets into the extracted text, and
`edit.word` turns them back into runs and wraps them as tracked changes.

The map is never stored. `extract` is deterministic, so writeback rebuilds it
from the file and refuses if the text no longer matches the draft the analysis
was computed from. A stored map would be one more thing that can go stale
silently, which is the failure this whole design is built against.

Four things get special handling and all four are about not judging text that
is not the author's argument.

* **Tracked changes already in the file.** Text a coauthor deleted is not in
  the document and is never extracted. Text a coauthor inserted is extracted
  and marked protected, because somebody is already handling it.
* **Commented ranges**, for the same reason. A comment is a conversation in
  progress and the tool does not get to edit inside one.
* **Field citations** from Zotero and Mendeley, which carry CSL JSON in the
  field instruction. The metadata there is what the reference manager knows
  about the work, which beats parsing the rendered string by a wide margin.
* **Footnotes and endnotes**, captured so they can be verified but never
  segmented as body prose. A footnote is not a sentence in the argument.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_better.builder import DocumentBuilder
from research_better.extras import require
from research_better.ingest.citations import find_citations, protected_ranges
from research_better.model import Document, FloatKind, ResolvedWork

FORMAT = "word"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

PARAGRAPH_SEPARATOR = "\n\n"

HEADING_NAME = re.compile(r"heading\s*([1-9])\b", re.IGNORECASE)

REFERENCE_HEADINGS = frozenset(
    {
        "references",
        "reference",
        "reference list",
        "bibliography",
        "works cited",
        "literature cited",
    }
)

CSL_MARKERS = ("CSL_CITATION", "ZOTERO_ITEM", "ZOTERO_BIBL", "MENDELEY_CITATION")
"""Field instructions Zotero and Mendeley write. The rendered text beside them
is a formatted string; the JSON is the record."""


@dataclass(frozen=True, slots=True)
class TextSlice:
    """One run of extracted text, and the `w:t` element it came from."""

    char_start: int
    char_end: int
    paragraph: int
    """Index of the `w:p` in document order, counting those inside tables."""

    text: int
    """Index of the `w:t` within that paragraph, in document order."""


@dataclass(frozen=True, slots=True)
class Block:
    """One thing the walker recognised, as a range of the extracted text."""

    kind: str
    start: int
    end: int
    level: int = 0
    title: str = ""
    label: str | None = None
    opaque: tuple[tuple[int, int], ...] = ()
    """Ranges inside a paragraph that are not prose: an inline equation, or the
    rendered text of a reference-manager field. Segmentation must not split
    inside one and no patch may touch one."""


@dataclass(frozen=True, slots=True)
class FieldCitation:
    key: str
    raw: str
    start: int
    end: int
    title: str | None = None
    year: int | None = None
    authors: tuple[str, ...] = ()
    doi: str | None = None
    in_bibliography: bool = False


@dataclass(frozen=True, slots=True)
class Extraction:
    text: str
    slices: tuple[TextSlice, ...] = ()
    blocks: tuple[Block, ...] = ()
    citations: tuple[FieldCitation, ...] = ()
    marked: tuple[tuple[int, int], ...] = ()
    """Ranges a human is already working on: a coauthor's tracked insertion or
    a commented range. Recorded as protected, so no edit is proposed inside
    one."""

    metadata: dict[str, str] = field(default_factory=dict)

    def slices_covering(self, start: int, end: int) -> list[TextSlice]:
        return [item for item in self.slices if item.char_start < end and start < item.char_end]


# Styles --------------------------------------------------------------------


def _style_index(styles_element: Any) -> dict[str, Any]:
    return {
        style.get(f"{W}styleId"): style
        for style in styles_element.iterchildren(f"{W}style")
        if style.get(f"{W}styleId")
    }


def heading_level(style_id: str | None, styles: dict[str, Any], depth: int = 0) -> int | None:
    """The outline level a paragraph style means, or None for body text.

    Publisher templates rename the heading styles, so the style name is checked
    second and `w:outlineLvl` first. The outline level is what Word itself uses
    to build a table of contents, which makes it the one signal a template
    cannot rename away.
    """
    style = styles.get(style_id or "")
    if style is None or depth > 3:
        return None

    for properties in style.iterchildren(f"{W}pPr"):
        for outline in properties.iterchildren(f"{W}outlineLvl"):
            value = outline.get(f"{W}val")
            if value is not None and value.isdigit() and int(value) <= 8:
                return int(value) + 1

    for name in style.iterchildren(f"{W}name"):
        match = HEADING_NAME.search(name.get(f"{W}val") or "")
        if match:
            return int(match.group(1))

    for based in style.iterchildren(f"{W}basedOn"):
        inherited = heading_level(based.get(f"{W}val"), styles, depth + 1)
        if inherited is not None:
            return inherited
    return None


# Extraction ----------------------------------------------------------------


def _citation_from_instruction(instruction: str) -> list[dict[str, Any]]:
    """The CSL items a Zotero or Mendeley field carries, if any."""
    if not any(marker in instruction for marker in CSL_MARKERS):
        return []
    brace = instruction.find("{")
    if brace < 0:
        return []
    try:
        payload, _ = json.JSONDecoder().raw_decode(instruction[brace:])
    except json.JSONDecodeError:
        # A field this module cannot read is a field it reports nothing about.
        # Guessing at a citation from a half-parsed instruction would put an
        # invented record into the bibliography.
        return []
    items = payload.get("citationItems") or []
    return [item.get("itemData") or item for item in items if isinstance(item, dict)]


def _work_from(
    item: dict[str, Any],
) -> tuple[str, str | None, int | None, tuple[str, ...], str | None]:
    authors = tuple(
        " ".join(part for part in (person.get("given"), person.get("family")) if part).strip()
        for person in item.get("author") or ()
        if isinstance(person, dict)
    )
    issued = item.get("issued") or {}
    parts = issued.get("date-parts") or [[]]
    year = None
    if parts and parts[0] and str(parts[0][0]).isdigit():
        year = int(parts[0][0])

    surname = ""
    for person in item.get("author") or ():
        if isinstance(person, dict) and person.get("family"):
            surname = str(person["family"]).lower().replace(" ", "")
            break
    key = str(item.get("id") or f"{surname}{year or ''}" or item.get("title", "")[:40])
    return key, item.get("title"), year, authors, item.get("DOI") or item.get("doi")


class _Walker:
    """One pass over the package, producing text and everything that maps to it."""

    def __init__(self, docx: Any, styles: dict[str, Any]) -> None:
        self.docx = docx
        self.styles = styles
        self.parts: list[str] = []
        self.length = 0
        self.slices: list[TextSlice] = []
        self.blocks: list[Block] = []
        self.citations: list[FieldCitation] = []
        self.marked: list[tuple[int, int]] = []
        self.paragraph_index = 0
        self.text_index = 0
        self.in_references = False
        self.opaque: list[tuple[int, int]] = []

    # Text ------------------------------------------------------------------

    def emit(self, text: str) -> tuple[int, int]:
        start = self.length
        self.parts.append(text)
        self.length += len(text)
        return start, self.length

    def emit_run(self, text: str) -> tuple[int, int]:
        start, end = self.emit(text)
        self.slices.append(TextSlice(start, end, self.paragraph_index, self.text_index))
        self.text_index += 1
        return start, end

    # Walking ---------------------------------------------------------------

    def run(self) -> Extraction:
        body = self.docx.element.body
        numbering = {element: index for index, element in enumerate(body.iter(f"{W}p"))}
        self._walk_body(body, numbering)
        self._walk_notes()

        return Extraction(
            text="".join(self.parts),
            slices=tuple(self.slices),
            blocks=tuple(sorted(self.blocks, key=lambda block: (block.start, block.end))),
            citations=tuple(self.citations),
            marked=tuple(self.marked),
            metadata={
                key: value
                for key, value in (
                    ("title", self.docx.core_properties.title),
                    ("author", self.docx.core_properties.author),
                )
                if value
            },
        )

    def _walk_body(self, body: Any, numbering: dict[Any, int]) -> None:
        for element in body.iterchildren():
            tag = element.tag
            if tag == f"{W}p":
                self._paragraph(element, numbering)
            elif tag == f"{W}tbl":
                self._table(element, numbering)
            elif tag == f"{W}sdt":
                for content in element.iterchildren(f"{W}sdtContent"):
                    self._walk_body(content, numbering)

    def _table(self, table: Any, numbering: dict[Any, int]) -> None:
        """A table is counted and located, never segmented.

        A table cell is not a claim. Its paragraphs still go through the run
        walker so their offsets exist, which is what lets a later pass quote a
        cell without this module pretending it is prose.
        """
        start = self.length
        for paragraph in table.iter(f"{W}p"):
            self.paragraph_index = numbering.get(paragraph, self.paragraph_index)
            self.text_index = 0
            self._runs(paragraph)
            self.emit(PARAGRAPH_SEPARATOR)
        self.blocks.append(Block("float", start, self.length, label="table"))

    def _paragraph(self, paragraph: Any, numbering: dict[Any, int]) -> None:
        self.paragraph_index = numbering.get(paragraph, self.paragraph_index)
        self.text_index = 0

        style_id = None
        for properties in paragraph.iterchildren(f"{W}pPr"):
            for style in properties.iterchildren(f"{W}pStyle"):
                style_id = style.get(f"{W}val")

        start = self.length
        self.opaque = []
        self._runs(paragraph)
        end = self.length
        opaque = tuple(self.opaque)
        self.emit(PARAGRAPH_SEPARATOR)

        body = "".join(self.parts)[start:end]
        if not body.strip():
            return

        level = heading_level(style_id, self.styles)
        if level is not None:
            self.blocks.append(Block("heading", start, end, level=level, title=body.strip()))
            self.in_references = body.strip().lower() in REFERENCE_HEADINGS
            return

        self.blocks.append(
            Block(
                "reference" if self.in_references else "paragraph",
                start,
                end,
                opaque=opaque,
            )
        )

    def _runs(self, paragraph: Any) -> None:
        state = _FieldState()
        self._children(paragraph, state, marked=False)

    def _children(self, element: Any, state: _FieldState, marked: bool) -> None:
        for child in element.iterchildren():
            tag = child.tag
            if tag == f"{W}del":
                # Deleted by a coauthor. It is not in the document, so it is not
                # extracted, and nothing downstream can flag text that is on its
                # way out.
                continue
            if tag == f"{W}ins":
                start = self.length
                self._children(child, state, marked=True)
                if self.length > start:
                    self.marked.append((start, self.length))
            elif tag in {f"{M}oMath", f"{M}oMathPara"}:
                start = self.length
                self.emit("".join(node.text or "" for node in child.iter(f"{M}t")))
                # An equation is never a sentence. It is recorded so a pass can
                # locate it, and marked opaque so segmentation does not read the
                # periods in it as full stops and no patch lands inside it.
                self.blocks.append(Block("float", start, self.length, label="equation"))
                self.opaque.append((start, self.length))
            elif tag == f"{W}r":
                self._run(child, state, marked)
            elif tag == f"{W}fldSimple":
                self._simple_field(child, state, marked)
            elif tag in {f"{W}hyperlink", f"{W}smartTag", f"{W}sdt", f"{W}sdtContent"}:
                self._children(child, state, marked)
            elif tag == f"{W}commentRangeStart":
                state.comments[child.get(f"{W}id")] = self.length
            elif tag == f"{W}commentRangeEnd":
                opened = state.comments.pop(child.get(f"{W}id"), None)
                if opened is not None and self.length > opened:
                    # A comment is a conversation in progress. The tool does not
                    # get to edit inside one.
                    self.marked.append((opened, self.length))

    def _run(self, run: Any, state: _FieldState, marked: bool) -> None:
        for child in run.iterchildren():
            tag = child.tag
            if tag == f"{W}fldChar":
                kind = child.get(f"{W}fldCharType")
                if kind == "begin":
                    state.open()
                elif kind == "separate":
                    state.begin_result(self.length)
                elif kind == "end":
                    self._close_field(state)
            elif tag == f"{W}instrText":
                state.instruction += child.text or ""
            elif tag == f"{W}t":
                if state.collecting_instruction:
                    continue
                self.emit_run(child.text or "")
            elif tag in {f"{W}tab", f"{W}br"}:
                # A tab or a line break separates words. Dropping it would join
                # two of them into one that neither the author nor the lexicon
                # ever wrote.
                self.emit(" ")
            elif tag in {f"{W}drawing", f"{W}pict", f"{W}object"}:
                start = self.length
                self.blocks.append(Block("float", start, start, label="figure"))
            elif tag in {f"{W}footnoteReference", f"{W}endnoteReference"}:
                state.notes.append(child.get(f"{W}id"))

    def _simple_field(self, element: Any, state: _FieldState, marked: bool) -> None:
        instruction = element.get(f"{W}instr") or ""
        start = self.length
        self._children(element, state, marked)
        self._record_field(instruction, start, self.length)

    def _close_field(self, state: _FieldState) -> None:
        instruction, start = state.close()
        if start is not None:
            self._record_field(instruction, start, self.length)

    def _record_field(self, instruction: str, start: int, end: int) -> None:
        items = _citation_from_instruction(instruction)
        if not items:
            return
        raw = "".join(self.parts)[start:end]
        bibliography = "BIBL" in instruction.upper()
        if end > start:
            # The rendered citation belongs to the reference manager. Editing
            # inside it would be overwritten the next time Word refreshes the
            # field, and the author would never know which change was lost.
            self.opaque.append((start, end))
        for item in items:
            key, title, year, authors, doi = _work_from(item)
            self.citations.append(
                FieldCitation(
                    key=key,
                    raw=raw or key,
                    start=start,
                    end=end,
                    title=title,
                    year=year,
                    authors=authors,
                    doi=doi,
                    in_bibliography=bibliography,
                )
            )

    # Notes -----------------------------------------------------------------

    def _walk_notes(self) -> None:
        """Footnotes and endnotes, captured but never segmented as prose.

        A footnote is not a sentence in the argument, so it gets a float rather
        than a paragraph. It is still extracted, because a footnote is where a
        surprising number of citations live.
        """
        for kind in ("footnotes", "endnotes"):
            element = self._notes_part(kind)
            if element is None:
                continue
            for note in element.iterchildren(f"{W}{kind[:-1]}"):
                if note.get(f"{W}type") in {"separator", "continuationSeparator"}:
                    continue
                start = self.length
                text = " ".join(
                    "".join(node.text or "" for node in paragraph.iter(f"{W}t")).strip()
                    for paragraph in note.iter(f"{W}p")
                ).strip()
                if not text:
                    continue
                self.emit(text)
                self.blocks.append(
                    Block("note", start, self.length, label=f"{kind[:-1]} {note.get(f'{W}id')}")
                )
                self.emit(PARAGRAPH_SEPARATOR)

    def _notes_part(self, kind: str) -> Any:
        """The footnotes or endnotes part, however the package exposes it.

        python-docx parses the parts it has an object model for and leaves the
        rest as bytes. Notes are in the second group, so this falls back to
        parsing the blob rather than assuming an element is there.
        """
        from docx.oxml import parse_xml

        for relation in self.docx.part.rels.values():
            if not relation.reltype.endswith(f"/{kind}"):
                continue
            target = relation.target_part
            element = getattr(target, "element", None)
            return element if element is not None else parse_xml(target.blob)
        return None


@dataclass
class _FieldState:
    """Where the walker is inside a Word field.

    A field is a run of elements bracketed by `fldChar` markers, with the
    instruction in the middle and the rendered text after a separator. Zotero
    puts its CSL JSON in the instruction, so the instruction text has to be
    collected and kept out of the prose.
    """

    instruction: str = ""
    result_start: int | None = None
    depth: int = 0
    comments: dict[str | None, int] = field(default_factory=dict)
    notes: list[str | None] = field(default_factory=list)

    @property
    def collecting_instruction(self) -> bool:
        return self.depth > 0 and self.result_start is None

    def open(self) -> None:
        self.depth += 1
        if self.depth == 1:
            self.instruction = ""
            self.result_start = None

    def begin_result(self, offset: int) -> None:
        if self.depth == 1:
            self.result_start = offset

    def close(self) -> tuple[str, int | None]:
        self.depth = max(0, self.depth - 1)
        if self.depth:
            return "", None
        instruction, start = self.instruction, self.result_start
        self.instruction, self.result_start = "", None
        return instruction, start


def extract(path: Path | str) -> Extraction:
    """Read a `.docx` into text plus everything that points back into it.

    Deterministic: writeback calls this again and refuses if the result no
    longer matches the draft the analysis was computed from.
    """
    docx = require("docx", "docx", "Word ingest")
    document = docx.Document(str(path))
    styles = _style_index(document.styles.element)
    return _Walker(document, styles).run()


# Ingest --------------------------------------------------------------------


def ingest(path: Path | str, source: str = "") -> Document:
    """Build a `Document` from a Word file.

    `source` is ignored. Word is binary, so the text is whatever `extract`
    produces, and taking it from a caller would let the map and the text
    disagree.
    """
    path = Path(path)
    extraction = extract(path)
    builder = DocumentBuilder(path, FORMAT, extraction.text)

    for key, value in extraction.metadata.items():
        builder.set_metadata(key, value)

    for block in extraction.blocks:
        span = builder.span(block.start, block.end)
        if block.kind == "heading":
            builder.add_section(title=block.title, level=block.level, heading_span=span)
        elif block.kind == "paragraph":
            text = extraction.text[block.start : block.end]
            builder.add_paragraph(
                span,
                protected=[
                    (block.start + low, block.start + high) for low, high in protected_ranges(text)
                ]
                + list(block.opaque),
            )
            for low, high in block.opaque:
                builder.add_protected(builder.span(low, high))
            for found in find_citations(text):
                builder.add_citation(
                    key=found.key,
                    raw=found.raw,
                    span=builder.span(block.start + found.start, block.start + found.end),
                )
        elif block.kind == "reference":
            raw = extraction.text[block.start : block.end]
            entries = find_citations(raw)
            key = entries[0].key if entries else raw.split(",")[0].strip()[:60]
            builder.add_float(FloatKind.BIBLIOGRAPHY, span, label=key)
            builder.add_citation(key=key, raw=raw, span=span, in_bibliography=True)
        elif block.kind == "note":
            builder.add_float(FloatKind.OTHER, span, label=block.label)
        else:
            builder.add_float(_float_kind(block.label), span, label=block.label)

    for citation in extraction.citations:
        builder.add_citation(
            key=citation.key,
            raw=citation.raw,
            span=builder.span(citation.start, citation.end),
            in_bibliography=citation.in_bibliography,
            resolved=_resolved(citation),
        )

    for start, end in extraction.marked:
        builder.add_protected(builder.span(start, end))

    return builder.build()


def _float_kind(label: str | None) -> FloatKind:
    return {
        "table": FloatKind.TABLE,
        "figure": FloatKind.FIGURE,
        "equation": FloatKind.EQUATION,
    }.get(label or "", FloatKind.OTHER)


def _resolved(citation: FieldCitation) -> ResolvedWork | None:
    if not (citation.title or citation.doi):
        return None
    return ResolvedWork(
        doi=citation.doi,
        title=citation.title,
        year=citation.year,
        authors=citation.authors,
        source="reference manager",
    )
