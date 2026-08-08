"""PDF ingest, for review only.

The common case is reading somebody else's paper, or the submitted version of
your own, where a PDF is the only artifact there is. Citation verification is
the pass that works best on it and is most of the reason to support the format.

Three limits, and all three are stated rather than worked around.

**No writeback.** A PDF is a rendering, not a source. `--apply` refuses.

**Span ids do not survive a recompile.** They hash the sentence and its section
path, and a PDF that has been rebuilt reflows lines, breaks words in different
places, and can change what this module reads as a paragraph. Artifacts do not
carry over between PDF versions, and nothing here pretends otherwise.

**Extraction quality varies, so it is measured.** A scanned page carries no
text at all, a heavily typeset one carries text in an order nothing can
recover. Rather than analysing whatever came out, this refuses when the page
gives too little to work with, and records what it was unsure about for the
report to state.

Reading order is the hard part. A two-column paper extracted naively produces
interleaved nonsense, because the text operators run down the page rather than
down the column. So every fragment is taken with its coordinates, the gutter is
found by looking for a vertical band of the page nothing is written in, and the
columns are read one after the other.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from io import BytesIO
from itertools import pairwise
from pathlib import Path
from typing import Any

from research_better.builder import DocumentBuilder
from research_better.errors import IngestError
from research_better.extras import require
from research_better.ingest.citations import find_citations, protected_ranges
from research_better.model import Document, FloatKind

FORMAT = "pdf"

MARGIN_BAND = 0.08
"""Share of the page height at the top and the bottom where a running header or
a footer lives. Text there is only dropped if it also repeats or is a bare page
number, because a one-page paper's first line sits in the same band."""

GUTTER = 15.0
"""Points of empty vertical space that make a gap a column boundary rather than
an indent. A wide indent is about 20 points; a two-column gutter is rarely
under 25."""

GUTTER_BAND = (0.2, 0.8)
"""Where in the page width a gutter may be found. A gap at the edge is a
margin, not a column boundary."""

GLYPH_WIDTH = 0.5
"""Average glyph width as a share of the font size. Used only to estimate where
a line ends, which decides whether it is a short line and therefore the end of
a paragraph. Nothing depends on it being exact."""

SHORT_LINE = 0.85
"""A line reaching less than this share of the column's width ends a paragraph.
The signal a PDF has instead of a blank line."""

MINIMUM_CHARACTERS = 200
"""Below this across the whole document there is nothing to analyse. A scan
extracts to almost nothing, and analysing that would produce a clean report
about a paper the tool never read."""

NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
BARE_NUMBER = re.compile(r"^[0-9ivxlc]+$", re.IGNORECASE)
ENTRY_START = re.compile(r"^\s*(?:\[(\d{1,3})\]|(\d{1,3})\.)\s+\S")

KNOWN_HEADINGS = frozenset(
    {
        "abstract",
        "introduction",
        "background",
        "related work",
        "method",
        "methods",
        "methodology",
        "experiments",
        "evaluation",
        "results",
        "discussion",
        "limitations",
        "conclusion",
        "conclusions",
        "acknowledgements",
        "acknowledgments",
        "references",
        "bibliography",
        "appendix",
    }
)

REFERENCE_HEADINGS = frozenset({"references", "bibliography", "works cited"})


@dataclass(frozen=True, slots=True)
class Fragment:
    """One run of text the PDF drew, and where it drew it."""

    page: int
    x: float
    y: float
    size: float
    text: str
    runs: tuple[str, ...] = ()
    """The separately positioned runs this fragment was drawn in. One run for a
    line of prose; one per cell for a row of a table."""

    @property
    def width(self) -> float:
        return len(self.text) * self.size * GLYPH_WIDTH

    @property
    def right(self) -> float:
        return self.x + self.width


@dataclass(frozen=True, slots=True)
class ReadLine:
    """One line of the paper, and whether it is prose at all."""

    text: str
    tabular: bool = False
    """The fragments on this line are separated by gaps far wider than a space,
    which is what a table row looks like and what no sentence does."""

    caption: bool = False


@dataclass(frozen=True, slots=True)
class Reading:
    """What came out of the file, and how much of it to trust."""

    lines: tuple[ReadLine, ...] = ()
    columns: tuple[int, ...] = ()
    """Columns found on each page, in page order. Reported so a reader can see
    the layout was understood rather than guessed."""

    notes: tuple[str, ...] = ()
    """What the reader was unsure about, in words the report can print."""

    characters: int = 0


# Reading the file ----------------------------------------------------------


def _fragments(reader: Any) -> tuple[list[Fragment], list[tuple[float, float]]]:
    """Every run of text with the position the page drew it at.

    pypdf reports the position of the first run on a visual line and then
    reports the rest of that line with no position at all, separated by one
    space however wide the real gap was. Those continuations are folded back
    into the run they belong to, so a line is one fragment with one anchor,
    which is what column detection needs. How many runs the line was drawn in
    is kept, because it is what survives of the gaps.
    """
    collected: list[list[Any]] = []
    boxes: list[tuple[float, float]] = []

    for number, page in enumerate(reader.pages):
        box = page.mediabox
        boxes.append((float(box.width), float(box.height)))

        def visit(
            text: str,
            _cm: Any,
            tm: Any,
            _font: Any,
            size: Any,
            page_number: int = number,
        ) -> None:
            if not text.strip():
                return
            x, y = float(tm[4]), float(tm[5])
            anchored = collected and collected[-1][0] == page_number
            if x == 0 and y == 0 and anchored:
                collected[-1][4] += text.rstrip()
                collected[-1][5].append(text.strip())
                return
            collected.append([page_number, x, y, float(size or 10), text.rstrip(), [text.strip()]])

        page.extract_text(visitor_text=visit)

    fragments = [
        Fragment(page=page, x=x, y=y, size=size, text=text, runs=tuple(runs))
        for page, x, y, size, text, runs in collected
    ]
    return fragments, boxes


def _running_text(fragments: list[Fragment], boxes: list[tuple[float, float]]) -> set[str]:
    """Header and footer lines, found by their repeating rather than by position.

    Position alone is not enough. The first line of a one-page paper sits in the
    same band as a running header, and dropping it would take the title.
    """
    seen: dict[str, set[int]] = {}
    for fragment in fragments:
        _width, height = boxes[fragment.page]
        in_margin = fragment.y > height * (1 - MARGIN_BAND) or fragment.y < height * MARGIN_BAND
        if not in_margin:
            continue
        key = re.sub(r"\d+", "#", fragment.text.strip())
        seen.setdefault(key, set()).add(fragment.page)

    repeated = {key for key, pages in seen.items() if len(pages) > 1}
    return repeated


def _drop_margins(
    fragments: list[Fragment], boxes: list[tuple[float, float]], notes: list[str]
) -> list[Fragment]:
    repeated = _running_text(fragments, boxes)
    kept: list[Fragment] = []
    dropped = 0

    for fragment in fragments:
        _width, height = boxes[fragment.page]
        in_margin = fragment.y > height * (1 - MARGIN_BAND) or fragment.y < height * MARGIN_BAND
        key = re.sub(r"\d+", "#", fragment.text.strip())
        if in_margin and (key in repeated or BARE_NUMBER.match(fragment.text.strip())):
            dropped += 1
            continue
        kept.append(fragment)

    if dropped:
        notes.append(f"{dropped} running header, footer, or page number line(s) were dropped.")
    return kept


def _drop_line_numbers(fragments: list[Fragment], notes: list[str]) -> list[Fragment]:
    """Numbers down the left margin of a submitted manuscript.

    They are not prose and they are not part of any sentence, and left in place
    they turn the first word of every line into a claim about a number.
    """
    if not fragments:
        return fragments
    body_left = statistics.median([fragment.x for fragment in fragments])
    kept = [
        fragment
        for fragment in fragments
        if not (BARE_NUMBER.match(fragment.text.strip()) and fragment.x < body_left - 10)
    ]
    if len(kept) < len(fragments):
        notes.append(f"{len(fragments) - len(kept)} margin line number(s) were dropped.")
    return kept


def find_gutter(fragments: list[Fragment], width: float) -> float | None:
    """The x of a vertical band nothing is written in, or None for one column.

    Computed from where text actually stops and starts again rather than from
    where lines begin, because an indented first line begins further right than
    its paragraph and would look like a second column.
    """
    if len(fragments) < 6:
        return None

    events = sorted((fragment.x, fragment.right) for fragment in fragments)
    low, high = width * GUTTER_BAND[0], width * GUTTER_BAND[1]

    best_gap, best_at = 0.0, None
    reach = events[0][1]
    for start, end in events[1:]:
        if start - reach > best_gap:
            middle = (reach + start) / 2
            if low <= middle <= high:
                best_gap, best_at = start - reach, middle
        reach = max(reach, end)

    return best_at if best_gap >= GUTTER else None


def _page_lines(fragments: list[Fragment], width: float) -> tuple[list[Fragment], int]:
    """One page in reading order, and how many columns it turned out to have."""
    gutter = find_gutter(fragments, width)
    if gutter is None:
        return sorted(fragments, key=lambda item: (-item.y, item.x)), 1

    left = [fragment for fragment in fragments if fragment.x < gutter]
    right = [fragment for fragment in fragments if fragment.x >= gutter]
    ordered = sorted(left, key=lambda item: (-item.y, item.x))
    ordered += sorted(right, key=lambda item: (-item.y, item.x))
    return ordered, 2


def read(path: Path) -> Reading:
    """Every line of the paper, in reading order, with what was unsure."""
    return read_bytes(path.read_bytes(), path.name)


def read_bytes(data: bytes, name: str = "the PDF") -> Reading:
    """The same, for a PDF that was downloaded rather than opened.

    A cited work's open-access copy arrives as bytes from somebody else's
    server, so the whole extraction sits inside the guard rather than only the
    parse. An unreadable page of a stranger's PDF is a source this tool could
    not see, which is a thing to report, never a thing to crash on.
    """
    pypdf = require("pypdf", "pdf", "PDF ingest")
    notes: list[str] = []
    try:
        reader = pypdf.PdfReader(BytesIO(data))
        fragments, boxes = _fragments(reader)
    except Exception as error:  # pypdf raises several unrelated types
        raise IngestError(f"{name} could not be read as a PDF: {error}") from None

    fragments = _drop_margins(fragments, boxes, notes)
    fragments = _drop_line_numbers(fragments, notes)

    lines: list[ReadLine] = []
    columns: list[int] = []
    for number, (width, _height) in enumerate(boxes):
        page = [fragment for fragment in fragments if fragment.page == number]
        if not page:
            continue
        ordered, count = _page_lines(page, width)
        columns.append(count)
        lines.extend(_join(ordered))

    characters = sum(len(line.text) for line in lines)
    if skipped := sum(1 for line in lines if line.tabular or line.caption):
        notes.append(
            f"{skipped} line(s) read as a table row or a caption were skipped rather "
            f"than analysed as prose. A table cell is not a claim."
        )
    if len(set(columns)) > 1:
        notes.append(
            "The column layout changes between pages, which is normal for a paper "
            "with a full-width abstract and worth knowing if the reading order "
            "looks wrong."
        )
    return Reading(tuple(lines), tuple(columns), tuple(notes), characters)


def _join(ordered: list[Fragment]) -> list[ReadLine]:
    """Fragments on the same baseline become one line."""
    baselines: list[list[Fragment]] = []
    for fragment in ordered:
        if baselines and abs(fragment.y - baselines[-1][0].y) <= 1.5:
            baselines[-1].append(fragment)
        else:
            baselines.append([fragment])

    shapes = [_shape(baseline) for baseline in baselines]
    lines: list[ReadLine] = []
    for index, baseline in enumerate(baselines):
        around = shapes[index - 1 : index] + shapes[index + 1 : index + 2]
        lines.append(_read_line(baseline, shapes[index], around))
    return lines


COLUMN_GAP = 3.0
"""Multiples of the font size between two fragments on one line before the line
is read as a table row. A word space is about a third of the font size, so this
is roughly nine spaces: wide enough that no typesetter put it there by
accident."""

CELLS = 3
"""Runs a line has to be drawn in before it can be a row of cells. Two is an
italic phrase inside a sentence, which every paper has."""

CELL_WORDS = 4
"""Words in a run before it stops being a cell and starts being a clause."""

CAPTION = re.compile(r"^(figure|fig\.?|table|algorithm|listing)\s*\d+", re.IGNORECASE)


def _shape(fragments: list[Fragment]) -> int:
    """How many cells this line could be, or zero if it is prose.

    The run count is what is left of the gaps after pypdf reports a line's
    continuations without position. On its own it is not enough, because prose
    is also drawn in several runs wherever the font changes, so a line only
    counts as cell-shaped when every run is too short to be a clause.
    """
    runs = [run for fragment in fragments for run in fragment.runs]
    if len(runs) < CELLS or any(len(run.split()) > CELL_WORDS for run in runs):
        return 0
    return len(runs)


def _read_line(fragments: list[Fragment], shape: int, neighbours: list[int]) -> ReadLine:
    ordered = sorted(fragments, key=lambda item: item.x)
    text = " ".join(fragment.text.strip() for fragment in ordered)

    # A gap no typesetter leaves by accident, where the positions survived, or
    # a run of lines drawn to the same shape. One cell-shaped line on its own
    # is a sentence that happened to break oddly; three in a row is a table,
    # and skipping a real sentence costs more than reading one cell as prose.
    tabular = any(
        later.x - earlier.right > earlier.size * COLUMN_GAP for earlier, later in pairwise(ordered)
    ) or (shape >= CELLS and shape in neighbours)
    return ReadLine(text=text, tabular=tabular, caption=bool(CAPTION.match(text.strip())))


# Turning lines into a paper -------------------------------------------------


@dataclass
class _Block:
    kind: str
    lines: list[str] = field(default_factory=list)
    level: int = 0


def _looks_like_a_heading(line: str) -> int | None:
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        return None

    numbered = NUMBERED_HEADING.match(stripped)
    if numbered and len(numbered.group(2).split()) <= 8:
        return numbered.group(1).count(".") + 1

    plain = stripped.lower().rstrip(".")
    if plain in KNOWN_HEADINGS:
        return 1
    if stripped.isupper() and len(stripped.split()) <= 6:
        return 1
    return None


def _dehyphenate(head: str, tail: str) -> str:
    """Rejoin a word a line break split.

    Only when the next line starts lower case. "state-of-the-art" broken after
    a hyphen the author wrote would be rejoined wrongly by a rule that ignored
    that, and the tool would invent a word nobody typed.
    """
    if head.endswith("-") and tail[:1].islower():
        return head[:-1] + tail
    return f"{head} {tail}"


def _text_of(block: _Block) -> str:
    joined = block.lines[0]
    for line in block.lines[1:]:
        joined = _dehyphenate(joined, line)
    return " ".join(joined.split())


def prose(reading: Reading) -> str:
    """The readable text, for a caller that wants text rather than a document.

    Table rows, captions, and reference entries are left out. A passage matcher
    handed a table row will quote it back as though the author had written it
    as a sentence, and a bibliography is a list of other people's titles rather
    than anything this source claims.
    """
    return "\n\n".join(
        _text_of(block) for block in _rebuild(reading) if block.kind in READABLE
    ).strip()


READABLE = frozenset({"paragraph", "heading"})


def ingest(path: Path | str, source: str = "") -> Document:
    """Build a `Document` from a PDF.

    `source` is ignored. A PDF is binary, and the text is whatever `read`
    recovers from it.
    """
    path = Path(path)
    reading = read(path)

    if reading.characters < MINIMUM_CHARACTERS:
        raise IngestError(
            f"{path.name} yielded {reading.characters} characters of text, which is too "
            f"little to analyse. A scanned PDF carries images rather than text, and no "
            f"pass here can read one. Run it through OCR first, or work from the source. "
            f"Nothing was analysed, because a clean report about a paper the tool never "
            f"read is worse than no report."
        )

    blocks = _rebuild(reading)
    pieces: list[str] = []
    for block in blocks:
        pieces.append(_text_of(block))
    text = "\n\n".join(pieces) + "\n"

    builder = DocumentBuilder(path, FORMAT, text)
    builder.set_metadata("pages", str(len(reading.columns)))
    builder.set_metadata("columns", ", ".join(str(count) for count in reading.columns))
    if reading.notes:
        # Carried on the document so the report can say what the reader was
        # unsure about. Silence about a doubtful extraction reads as a
        # confident one.
        builder.set_metadata("extraction_notes", " ".join(reading.notes))

    offset = 0
    for block, body in zip(blocks, pieces, strict=True):
        span = builder.span(offset, offset + len(body))
        if block.kind == "heading":
            builder.add_section(title=body, level=block.level, heading_span=span)
        elif block.kind == "float":
            builder.add_float(FloatKind.TABLE, span)
        elif block.kind == "reference":
            found = find_citations(body)
            key = found[0].key if found else body.split(",")[0].strip()[:60]
            builder.add_float(FloatKind.BIBLIOGRAPHY, span, label=key)
            builder.add_citation(key=key, raw=body, span=span, in_bibliography=True)
        else:
            builder.add_paragraph(
                span,
                protected=[(offset + low, offset + high) for low, high in protected_ranges(body)],
            )
            for citation in find_citations(body):
                builder.add_citation(
                    key=citation.key,
                    raw=citation.raw,
                    span=builder.span(offset + citation.start, offset + citation.end),
                )
        offset += len(body) + 2

    return builder.build()


def _rebuild(reading: Reading) -> list[_Block]:
    """Group lines into headings, paragraphs, and reference entries.

    A PDF has no blank lines to go by. What it has instead is a line that stops
    short of the column edge, which is where a paragraph ended, and that is the
    signal used here.
    """
    widths = _column_width(reading)
    blocks: list[_Block] = []
    in_references = False
    open_paragraph = False

    for line in reading.lines:
        stripped = line.text.strip()
        if not stripped:
            continue

        if line.tabular or line.caption:
            # A table cell is not a claim and a caption is not a sentence in the
            # argument. Both are located and neither is segmented.
            blocks.append(_Block("float", [stripped]))
            open_paragraph = False
            continue

        level = _looks_like_a_heading(stripped)
        if level is not None:
            numbered = NUMBERED_HEADING.match(stripped)
            title = numbered.group(2) if numbered else stripped
            blocks.append(_Block("heading", [title], level=level))
            in_references = title.lower().rstrip(".") in REFERENCE_HEADINGS
            open_paragraph = False
            continue

        if in_references:
            if ENTRY_START.match(stripped) or not blocks or blocks[-1].kind != "reference":
                blocks.append(_Block("reference", [stripped]))
            else:
                blocks[-1].lines.append(stripped)
            continue

        if open_paragraph and blocks and blocks[-1].kind == "paragraph":
            blocks[-1].lines.append(stripped)
        else:
            blocks.append(_Block("paragraph", [stripped]))
        open_paragraph = len(stripped) >= widths * SHORT_LINE

    return blocks


def _column_width(reading: Reading) -> float:
    """A typical full line, in characters, so a short one can be recognised."""
    lengths = [len(line.text.strip()) for line in reading.lines if line.text.strip()]
    return max(lengths) if lengths else 0.0
