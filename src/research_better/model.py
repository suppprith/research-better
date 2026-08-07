"""The single internal representation every pass reads and writes against.

Ingest adapters produce a `Document`. Analysis passes read one and emit findings
that name span ids. The edit pass turns findings back into byte ranges in the
original file. Nothing downstream of ingest ever sees a `.tex` or `.md` detail,
which is what keeps a new format from touching the analysis code.

Two properties carry the design:

* **Content-addressed ids.** See `research_better.spans` for why.
* **Round-trippable spans.** A `Document` holds the exact source text it was
  built from, so any span recovers the original characters and, through
  `Document.byte_range`, the original bytes. Review-only patching depends on
  that: the tool proposes a byte range and a replacement, and never has to
  re-serialize a document it only partly understands.

Every element is frozen. A pass that wants to record a result builds a new
object with `dataclasses.replace` rather than mutating shared state, so two
passes running over one document cannot interfere.
"""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class FloatKind(StrEnum):
    """Block content that is never prose and is therefore never edited.

    A code comment is not a sentence, a table cell is not a claim, and an
    equation is not fluff. These are counted and located so passes can reason
    about them, never segmented or rewritten.
    """

    FIGURE = "figure"
    TABLE = "table"
    EQUATION = "equation"
    CODE = "code"
    QUOTE = "quote"
    VERBATIM = "verbatim"
    ALGORITHM = "algorithm"
    FRONT_MATTER = "front_matter"
    BIBLIOGRAPHY = "bibliography"
    OTHER = "other"


@dataclass(frozen=True, slots=True, order=True)
class Span:
    """A half-open character range in the document's source text.

    Offsets are character offsets into the decoded text, not byte offsets, so
    they behave the same on any platform. Use `Document.byte_range` when a byte
    range is what is needed.

    `source_file` is set when a document was assembled from more than one file,
    which is the normal case for a LaTeX paper using `\\input`. A patch has to
    go back to the file the text came from, not to the root file.
    """

    char_start: int
    char_end: int
    line: int = 0
    source_file: str | None = None

    def __post_init__(self) -> None:
        if self.char_end < self.char_start:
            raise ValueError(f"span ends before it starts: {self.char_start}..{self.char_end}")

    @property
    def length(self) -> int:
        return self.char_end - self.char_start

    def contains(self, offset: int) -> bool:
        return self.char_start <= offset < self.char_end

    def overlaps(self, other: Span) -> bool:
        return self.char_start < other.char_end and other.char_start < self.char_end


@dataclass(frozen=True, slots=True)
class Section:
    """A heading and everything under it until the next heading of equal rank."""

    id: str
    title: str
    level: int
    heading_span: Span
    span: Span
    parent_id: str | None = None
    path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Paragraph:
    id: str
    section_id: str | None
    span: Span


@dataclass(frozen=True, slots=True)
class Sentence:
    """The unit every analysis pass addresses."""

    id: str
    paragraph_id: str
    section_id: str | None
    text: str
    span: Span

    @property
    def char_start(self) -> int:
        return self.span.char_start

    @property
    def char_end(self) -> int:
        return self.span.char_end

    @property
    def line(self) -> int:
        return self.span.line


@dataclass(frozen=True, slots=True)
class ResolvedWork:
    """What a citation key turned out to point at.

    Filled by citation verification. Every field is optional because partial
    resolution is the normal outcome: a DOI with no retrievable full text is
    still worth more than nothing, and the report has to be able to say which
    parts were confirmed and which were not.
    """

    doi: str | None = None
    title: str | None = None
    year: int | None = None
    authors: tuple[str, ...] = ()
    venue: str | None = None
    source: str | None = None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class Citation:
    """One key at one place in the text.

    `\\cite{a,b,c}` produces three citations pointing at the same span. Each key
    is verified separately, because two of them can be right and one wrong.
    """

    id: str
    key: str
    raw: str
    span: Span
    sentence_id: str | None = None
    resolved: ResolvedWork | None = None
    in_bibliography: bool = False
    """True for an entry in the reference list, false for a use in the text.

    Both are needed and they are checked for different things. A use is checked
    against the claim it supports. An entry is checked for existing at all, and
    for being cited somewhere. An entry with no matching use is a dangling
    reference, and a use with no matching entry will not compile.
    """


@dataclass(frozen=True, slots=True)
class Float:
    id: str
    kind: FloatKind
    span: Span
    label: str | None = None


@dataclass(frozen=True, slots=True)
class LineMap:
    """Offset to 1-based line number, without rescanning the text each time."""

    starts: tuple[int, ...]

    @classmethod
    def build(cls, text: str) -> LineMap:
        starts = [0]
        for index, character in enumerate(text):
            if character == "\n":
                starts.append(index + 1)
        return cls(tuple(starts))

    def line_of(self, offset: int) -> int:
        return bisect_right(self.starts, offset)


@dataclass(frozen=True, slots=True)
class Document:
    """A whole paper, however many files it was written across."""

    path: Path
    format: str
    source_text: str
    source_hash: str
    sections: tuple[Section, ...] = ()
    paragraphs: tuple[Paragraph, ...] = ()
    sentences: tuple[Sentence, ...] = ()
    citations: tuple[Citation, ...] = ()
    floats: tuple[Float, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)
    """Title, author, and anything else the format declares out of band. Front
    matter is metadata, not prose, so it is never segmented or analysed."""

    _index: dict[str, object] = field(default_factory=dict, repr=False, compare=False, init=False)

    def __post_init__(self) -> None:
        groups: tuple[tuple[Section | Paragraph | Sentence | Citation | Float, ...], ...] = (
            self.sections,
            self.paragraphs,
            self.sentences,
            self.citations,
            self.floats,
        )
        for group in groups:
            for element in group:
                self._index[element.id] = element

    @staticmethod
    def hash_source(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def text_of(self, span: Span) -> str:
        """The exact source characters a span covers."""
        return self.source_text[span.char_start : span.char_end]

    def byte_range(self, span: Span) -> tuple[int, int]:
        """The span as UTF-8 byte offsets into the source.

        Character offsets are what the model stores, but a patch applied by an
        external tool usually wants bytes. Converting here, from the text the
        document was actually built from, keeps that conversion in one place.
        """
        start = len(self.source_text[: span.char_start].encode("utf-8"))
        return start, start + len(self.text_of(span).encode("utf-8"))

    def element(self, element_id: str) -> object:
        try:
            return self._index[element_id]
        except KeyError:
            raise KeyError(f"no element with id {element_id!r} in this document") from None

    def sentence(self, sentence_id: str) -> Sentence:
        element = self.element(sentence_id)
        if not isinstance(element, Sentence):
            raise KeyError(f"id {sentence_id!r} is a {type(element).__name__}, not a Sentence")
        return element

    def section(self, section_id: str) -> Section:
        element = self.element(section_id)
        if not isinstance(element, Section):
            raise KeyError(f"id {section_id!r} is a {type(element).__name__}, not a Section")
        return element

    def sentences_in_section(self, section_id: str) -> tuple[Sentence, ...]:
        return tuple(s for s in self.sentences if s.section_id == section_id)

    def citations_in_sentence(self, sentence_id: str) -> tuple[Citation, ...]:
        return tuple(c for c in self.citations if c.sentence_id == sentence_id)

    def sentence_at(self, offset: int) -> Sentence | None:
        for sentence in self.sentences:
            if sentence.span.contains(offset):
                return sentence
        return None

    @property
    def word_count(self) -> int:
        """Words of prose. Floats are excluded, which is the number a venue's
        page limit actually cares about."""
        return sum(len(sentence.text.split()) for sentence in self.sentences)

    def floats_of_kind(self, kind: FloatKind) -> tuple[Float, ...]:
        return tuple(item for item in self.floats if item.kind is kind)
