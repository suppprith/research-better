"""The seam between an ingest adapter and the document model.

An adapter knows one format. It walks the source, and for each thing it
recognises it calls one method here: this run of text is a heading, this run is
a paragraph, this run is a code block, this run is a citation. It never has to
know how ids are derived, how sentences are split, or how a citation is
attached to the sentence it sits in.

That split is what keeps a new format cheap. Adding Word support should mean
writing a walker, not reimplementing segmentation and id allocation and getting
them subtly different.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from pathlib import Path

from research_better.model import (
    Citation,
    Document,
    Float,
    FloatKind,
    LineMap,
    Paragraph,
    Section,
    Sentence,
    Span,
)
from research_better.segmentation import split_sentences
from research_better.spans import IdAllocator, normalize, section_path_key


class DocumentBuilder:
    """Accumulates document elements, then freezes them into a `Document`.

    Call order matters only in that headings must be opened before the content
    that belongs under them. Everything else is resolved in `build`.
    """

    def __init__(self, path: Path | str, format: str, source_text: str) -> None:
        self.path = Path(path)
        self.format = format
        self.source_text = source_text
        self._lines = LineMap.build(source_text)
        self._ids = IdAllocator()
        self._sections: list[Section] = []
        self._open: list[Section] = []
        self._paragraphs: list[Paragraph] = []
        self._sentences: list[Sentence] = []
        self._citations: list[Citation] = []
        self._floats: list[Float] = []
        self._metadata: dict[str, str] = {}

    # Span construction -----------------------------------------------------

    def span(self, char_start: int, char_end: int, source_file: str | None = None) -> Span:
        """Build a span with its line number filled in from the source text."""
        return Span(
            char_start=char_start,
            char_end=char_end,
            line=self._lines.line_of(char_start),
            source_file=source_file,
        )

    # Elements --------------------------------------------------------------

    def add_section(self, title: str, level: int, heading_span: Span) -> Section:
        """Open a heading. Closes any open headings of equal or deeper rank."""
        while self._open and self._open[-1].level >= level:
            self._open.pop()

        parent = self._open[-1] if self._open else None
        path = (*parent.path, title) if parent else (title,)
        section_id = self._ids.allocate("sec", section_path_key(path), str(level))

        section = Section(
            id=section_id,
            title=title,
            level=level,
            heading_span=heading_span,
            # Extended in build() to cover everything under the heading. The
            # true end is not known until the next heading of equal rank shows
            # up, or the document runs out.
            span=heading_span,
            parent_id=parent.id if parent else None,
            path=path,
        )
        self._sections.append(section)
        self._open.append(section)
        return section

    @property
    def current_section_id(self) -> str | None:
        return self._open[-1].id if self._open else None

    def add_paragraph(
        self, span: Span, protected: Sequence[tuple[int, int]] = ()
    ) -> tuple[Paragraph, list[Sentence]]:
        """Record a paragraph and split it into sentences.

        Args:
            span: Absolute range of the paragraph in the source text.
            protected: Absolute ranges inside the paragraph that segmentation
                must treat as opaque, such as a LaTeX command's argument.
        """
        text = self.source_text[span.char_start : span.char_end]
        section_id = self.current_section_id
        section_key = section_path_key(self._open[-1].path) if self._open else ""

        paragraph = Paragraph(
            id=self._ids.allocate("par", normalize(text), section_key),
            section_id=section_id,
            span=span,
        )
        self._paragraphs.append(paragraph)

        relative_protected = [
            (start - span.char_start, end - span.char_start) for start, end in protected
        ]

        produced: list[Sentence] = []
        for start, end in split_sentences(text, relative_protected):
            absolute_start = span.char_start + start
            absolute_end = span.char_start + end
            sentence_text = self.source_text[absolute_start:absolute_end]
            sentence = Sentence(
                id=self._ids.allocate("s", normalize(sentence_text), section_key),
                paragraph_id=paragraph.id,
                section_id=section_id,
                text=sentence_text,
                span=self.span(absolute_start, absolute_end, span.source_file),
            )
            self._sentences.append(sentence)
            produced.append(sentence)

        return paragraph, produced

    def add_float(self, kind: FloatKind, span: Span, label: str | None = None) -> Float:
        content = self.source_text[span.char_start : span.char_end]
        section_key = section_path_key(self._open[-1].path) if self._open else ""
        item = Float(
            id=self._ids.allocate("flt", kind.value, normalize(content), section_key),
            kind=kind,
            span=span,
            label=label,
        )
        self._floats.append(item)
        return item

    def add_citation(
        self, key: str, raw: str, span: Span, in_bibliography: bool = False
    ) -> Citation:
        """Record one citation key. Multi-key commands call this once per key."""
        section_key = section_path_key(self._open[-1].path) if self._open else ""
        citation = Citation(
            id=self._ids.allocate("cit", key, section_key, str(span.char_start)),
            key=key,
            raw=raw,
            span=span,
            in_bibliography=in_bibliography,
        )
        self._citations.append(citation)
        return citation

    def set_metadata(self, key: str, value: str) -> None:
        """Record a document-level fact the format declares out of band."""
        self._metadata[key] = value

    # Freeze ----------------------------------------------------------------

    def build(self) -> Document:
        sections = self._close_section_spans()
        citations = self._attach_citations_to_sentences()
        return Document(
            path=self.path,
            format=self.format,
            source_text=self.source_text,
            source_hash=Document.hash_source(self.source_text),
            sections=tuple(sections),
            paragraphs=tuple(self._paragraphs),
            sentences=tuple(self._sentences),
            citations=tuple(citations),
            floats=tuple(self._floats),
            metadata=dict(self._metadata),
        )

    def _close_section_spans(self) -> list[Section]:
        """Extend each section's span to cover everything under its heading."""
        end_of_document = len(self.source_text)
        closed: list[Section] = []
        for position, section in enumerate(self._sections):
            end = end_of_document
            for later in self._sections[position + 1 :]:
                if later.level <= section.level:
                    end = later.heading_span.char_start
                    break
            closed.append(
                Section(
                    id=section.id,
                    title=section.title,
                    level=section.level,
                    heading_span=section.heading_span,
                    span=self.span(
                        section.heading_span.char_start, end, section.heading_span.source_file
                    ),
                    parent_id=section.parent_id,
                    path=section.path,
                )
            )
        return closed

    def _attach_citations_to_sentences(self) -> list[Citation]:
        """Point each citation at the sentence it sits in.

        A citation in a caption or a bibliography entry has no sentence, and
        that is not an error. It stays unattached and the passes that need a
        sentence skip it.
        """
        ordered = sorted(self._sentences, key=lambda s: s.span.char_start)
        starts = [s.span.char_start for s in ordered]
        attached: list[Citation] = []

        for citation in self._citations:
            sentence_id: str | None = None
            if not citation.in_bibliography:
                position = bisect_right(starts, citation.span.char_start) - 1
                if position >= 0 and ordered[position].span.char_end >= citation.span.char_end:
                    sentence_id = ordered[position].id
            attached.append(
                Citation(
                    id=citation.id,
                    key=citation.key,
                    raw=citation.raw,
                    span=citation.span,
                    sentence_id=sentence_id,
                    resolved=citation.resolved,
                    in_bibliography=citation.in_bibliography,
                )
            )
        return attached
