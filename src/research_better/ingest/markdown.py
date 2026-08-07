"""Markdown ingest.

The first adapter, and the reference the others are checked against. Markdown
is the simplest format this tool reads, which makes it the right place to fix
the shape of an adapter: walk the source once, hand every run of characters to
the builder as exactly one kind of thing, and never lose a character.

The scanner is line based and deliberately not a full CommonMark parser. It
needs to answer one question per block: is this prose that a human wrote as an
argument, or is it something else. Getting that wrong in the permissive
direction is what makes a tool flag a code comment as fluff, so anything it
does not positively recognise as prose becomes a float and is left alone.
"""

from __future__ import annotations

import re
from pathlib import Path

from research_better.builder import DocumentBuilder
from research_better.ingest.citations import find_citations, protected_ranges
from research_better.model import Document, FloatKind

FORMAT = "markdown"

ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
SETEXT_UNDERLINE = re.compile(r"^ {0,3}(=+|-+)\s*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
MATH_FENCE = re.compile(r"^ {0,3}\$\$\s*$")
BLOCKQUOTE = re.compile(r"^ {0,3}>")
THEMATIC_BREAK = re.compile(r"^ {0,3}((\* *){3,}|(- *){3,}|(_ *){3,})$")
TABLE_DELIMITER = re.compile(r"^ {0,3}\|?[ :|-]*-[ :|-]*\|?\s*$")
LIST_MARKER = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+")
HTML_COMMENT_OPEN = re.compile(r"^ {0,3}<!--")
FRONT_MATTER_FENCE = re.compile(r"^(---|\.\.\.)\s*$")
FRONT_MATTER_KEY = re.compile(r"^([A-Za-z_][\w -]*)\s*:\s*(.*?)\s*$")

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

ENTRY_KEY = re.compile(r"^\s*(?:\[([^\]]{1,40})\]|\(([^)]{1,40})\))\s*")

METADATA_KEYS = frozenset({"title", "author", "authors", "date", "subtitle", "keywords"})


class _Line:
    __slots__ = ("start", "text")

    def __init__(self, start: int, text: str) -> None:
        self.start = start
        self.text = text

    @property
    def end(self) -> int:
        return self.start + len(self.text)

    @property
    def blank(self) -> bool:
        return not self.text.strip()


def _split_list_items(block: list[_Line]) -> list[list[_Line]]:
    """Break a block at each list marker.

    Without this, a three-bullet list is one paragraph and the second and third
    bullets end up inside a sentence, markers and all.
    """
    if not any(LIST_MARKER.match(line.text) for line in block):
        return [block]

    items: list[list[_Line]] = []
    for line in block:
        if LIST_MARKER.match(line.text) or not items:
            items.append([line])
        else:
            items[-1].append(line)
    return items


def _split_lines(source: str) -> list[_Line]:
    """Split into lines keeping absolute offsets and dropping only the break.

    A carriage return is excluded from the line text but still counted in the
    offsets, so a CRLF file produces the same spans as an LF one.
    """
    lines: list[_Line] = []
    offset = 0
    for raw in source.split("\n"):
        text = raw[:-1] if raw.endswith("\r") else raw
        lines.append(_Line(offset, text))
        offset += len(raw) + 1
    return lines


class _MarkdownWalker:
    def __init__(self, path: Path, source: str) -> None:
        self.source = source
        self.builder = DocumentBuilder(path, FORMAT, source)
        self.lines = _split_lines(source)
        self.index = 0
        self.paragraph: list[_Line] = []
        # Set while inside a reference list. Its contents are entries to be
        # verified, not prose to be judged, so nothing there is segmented.
        self.reference_level: int | None = None

    # Walking ---------------------------------------------------------------

    def run(self) -> Document:
        self._read_front_matter()
        while self.index < len(self.lines):
            line = self.lines[self.index]

            if line.blank:
                self._flush_paragraph()
                self.index += 1
                continue

            for handler in (
                self._take_fence,
                self._take_math_block,
                self._take_html_comment,
                self._take_atx_heading,
                self._take_setext_heading,
                self._take_blockquote,
                self._take_table,
                self._take_thematic_break,
            ):
                if handler(line):
                    break
            else:
                self.paragraph.append(line)
                self.index += 1

        self._flush_paragraph()
        return self.builder.build()

    # Blocks ----------------------------------------------------------------

    def _read_front_matter(self) -> None:
        if not self.lines or self.lines[0].text.strip() != "---":
            return
        for position in range(1, len(self.lines)):
            if FRONT_MATTER_FENCE.match(self.lines[position].text):
                block = self.lines[1:position]
                for line in block:
                    key_match = FRONT_MATTER_KEY.match(line.text)
                    if key_match and key_match.group(1).lower() in METADATA_KEYS:
                        self.builder.set_metadata(
                            key_match.group(1).lower(), key_match.group(2).strip("\"'")
                        )
                self.builder.add_float(
                    FloatKind.FRONT_MATTER,
                    self.builder.span(self.lines[0].start, self.lines[position].end),
                )
                self.index = position + 1
                return
        # An unterminated fence is not front matter. Treat it as ordinary text
        # rather than swallowing the whole paper.

    def _take_fence(self, line: _Line) -> bool:
        match = FENCE.match(line.text)
        if not match:
            return False
        self._flush_paragraph()
        marker = match.group(1)[0]
        length = len(match.group(1))
        end_line = self.lines[-1]
        for position in range(self.index + 1, len(self.lines)):
            closing = FENCE.match(self.lines[position].text)
            if closing and closing.group(1)[0] == marker and len(closing.group(1)) >= length:
                end_line = self.lines[position]
                self.index = position + 1
                break
        else:
            self.index = len(self.lines)
        self.builder.add_float(
            FloatKind.CODE,
            self.builder.span(line.start, end_line.end),
            label=match.group(2).strip() or None,
        )
        return True

    def _take_math_block(self, line: _Line) -> bool:
        if not MATH_FENCE.match(line.text):
            return False
        self._flush_paragraph()
        end_line = self.lines[-1]
        for position in range(self.index + 1, len(self.lines)):
            if MATH_FENCE.match(self.lines[position].text):
                end_line = self.lines[position]
                self.index = position + 1
                break
        else:
            self.index = len(self.lines)
        self.builder.add_float(FloatKind.EQUATION, self.builder.span(line.start, end_line.end))
        return True

    def _take_html_comment(self, line: _Line) -> bool:
        if not HTML_COMMENT_OPEN.match(line.text):
            return False
        self._flush_paragraph()
        end_line = line
        for position in range(self.index, len(self.lines)):
            if "-->" in self.lines[position].text:
                end_line = self.lines[position]
                self.index = position + 1
                break
        else:
            self.index = len(self.lines)
        self.builder.add_float(FloatKind.OTHER, self.builder.span(line.start, end_line.end))
        return True

    def _take_atx_heading(self, line: _Line) -> bool:
        match = ATX_HEADING.match(line.text)
        if not match:
            return False
        self._flush_paragraph()
        self._open_heading(
            title=match.group(2).strip(), level=len(match.group(1)), start=line.start, end=line.end
        )
        self.index += 1
        return True

    def _take_setext_heading(self, line: _Line) -> bool:
        """A run of `=` or `-` under a text line makes that line a heading."""
        if not self.paragraph:
            return False
        match = SETEXT_UNDERLINE.match(line.text)
        if not match:
            return False

        title_line = self.paragraph[-1]
        self.paragraph = self.paragraph[:-1]
        self._flush_paragraph()
        self._open_heading(
            title=title_line.text.strip(),
            level=1 if match.group(1).startswith("=") else 2,
            start=title_line.start,
            end=line.end,
        )
        self.index += 1
        return True

    def _take_blockquote(self, line: _Line) -> bool:
        if not BLOCKQUOTE.match(line.text):
            return False
        self._flush_paragraph()
        end_line = line
        position = self.index
        while position < len(self.lines) and not self.lines[position].blank:
            end_line = self.lines[position]
            position += 1
        self.index = position
        # A quotation is someone else's words. Cutting it for fluff or
        # rewriting it for voice would be putting words in their mouth.
        self.builder.add_float(FloatKind.QUOTE, self.builder.span(line.start, end_line.end))
        return True

    def _take_table(self, line: _Line) -> bool:
        following = self.index + 1
        if "|" not in line.text or following >= len(self.lines):
            return False
        if not TABLE_DELIMITER.match(self.lines[following].text):
            return False
        self._flush_paragraph()
        end_line = line
        position = self.index
        while position < len(self.lines) and not self.lines[position].blank:
            end_line = self.lines[position]
            position += 1
        self.index = position
        self.builder.add_float(FloatKind.TABLE, self.builder.span(line.start, end_line.end))
        return True

    def _take_thematic_break(self, line: _Line) -> bool:
        if not THEMATIC_BREAK.match(line.text):
            return False
        self._flush_paragraph()
        self.index += 1
        return True

    # Headings and paragraphs -----------------------------------------------

    def _open_heading(self, title: str, level: int, start: int, end: int) -> None:
        self.builder.add_section(
            title=title, level=level, heading_span=self.builder.span(start, end)
        )
        if title.strip().lower() in REFERENCE_HEADINGS:
            self.reference_level = level
        elif self.reference_level is not None and level <= self.reference_level:
            self.reference_level = None

    def _flush_paragraph(self) -> None:
        block, self.paragraph = self.paragraph, []
        if not block:
            return

        for item in _split_list_items(block):
            if self.reference_level is not None:
                self._add_reference_entry(item)
            else:
                self._add_prose_paragraph(item)

    def _add_prose_paragraph(self, block: list[_Line]) -> None:
        marker = LIST_MARKER.match(block[0].text)
        start = block[0].start + marker.end() if marker else block[0].start
        end = block[-1].end
        text = self.source[start:end]

        relative_protected = protected_ranges(text)
        self.builder.add_paragraph(
            self.builder.span(start, end),
            protected=[(start + low, start + high) for low, high in relative_protected],
        )

        for citation in find_citations(text):
            self.builder.add_citation(
                key=citation.key,
                raw=citation.raw,
                span=self.builder.span(start + citation.start, start + citation.end),
            )

    def _add_reference_entry(self, block: list[_Line]) -> None:
        """One entry in the reference list.

        A wrapped entry spans several lines, and a list-marker entry carries a
        bullet. Both collapse to one entry, keyed by its bracketed label when
        it has one so a numeric citation in the text can be matched to it.
        """
        start = block[0].start
        end = block[-1].end
        marker = LIST_MARKER.match(block[0].text)
        if marker:
            start += marker.end()
        raw = self.source[start:end]

        label = ENTRY_KEY.match(raw)
        key = (label.group(1) or label.group(2)) if label else None
        if key is None:
            found = find_citations(raw)
            key = found[0].key if found else raw.split(",")[0].strip()[:60]

        span = self.builder.span(start, end)
        self.builder.add_float(FloatKind.BIBLIOGRAPHY, span, label=key)
        self.builder.add_citation(key=key, raw=raw, span=span, in_bibliography=True)


def ingest(path: Path | str, source: str) -> Document:
    """Build a `Document` from Markdown source."""
    return _MarkdownWalker(Path(path), source).run()
