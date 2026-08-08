"""LaTeX ingest, with the ranges a patch may never touch.

LaTeX is the format the target users actually write in, and the one where a
careless edit fails silently: the paper stops compiling, or worse, compiles into
something different. So this adapter carries a second job beyond finding prose.
It marks the character ranges that are load bearing, and the edit pass refuses
any patch that overlaps one.

Protected means math mode, command names, environment delimiters, and the
arguments of commands whose arguments are not prose (`\\label`, `\\ref`,
`\\cite`, `\\url`, `\\input`, and the preamble's declarations). A `\\cite{x}`
sitting mid-sentence stays inside the sentence, because the claim and its
citation belong together, but it is opaque to segmentation and closed to edits.

Full TeX parsing is undecidable, and this does not attempt it. It handles the
subset that real IEEE and ACM papers use. Where it meets something it cannot
place, it fails loudly rather than guessing, because a wrong guess here shows
up as a broken build on the author's machine, not as an error here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from research_better.builder import DocumentBuilder
from research_better.errors import IngestError
from research_better.extras import require
from research_better.model import Document, FileSegment, FloatKind, ResolvedWork
from research_better.segmentation import merge_ranges

FORMAT = "latex"

# Only relative depth matters. A pass that cares about nesting reads
# `section.path`, not this number, because a book and an article number their
# top level differently and neither is wrong.
SECTION_LEVELS: dict[str, int] = {
    "part": 1,
    "chapter": 2,
    "section": 3,
    "subsection": 4,
    "subsubsection": 5,
    "paragraph": 6,
    "subparagraph": 7,
}

# Environments whose contents are never prose. A tabular cell is not a claim
# and a listing's comments are not the author's argument.
NON_PROSE_ENVIRONMENTS: dict[str, FloatKind] = {
    "equation": FloatKind.EQUATION,
    "align": FloatKind.EQUATION,
    "gather": FloatKind.EQUATION,
    "multline": FloatKind.EQUATION,
    "eqnarray": FloatKind.EQUATION,
    "displaymath": FloatKind.EQUATION,
    "math": FloatKind.EQUATION,
    "array": FloatKind.EQUATION,
    "figure": FloatKind.FIGURE,
    "subfigure": FloatKind.FIGURE,
    "wrapfigure": FloatKind.FIGURE,
    "tikzpicture": FloatKind.FIGURE,
    "table": FloatKind.TABLE,
    "tabular": FloatKind.TABLE,
    "tabularx": FloatKind.TABLE,
    "longtable": FloatKind.TABLE,
    "lstlisting": FloatKind.CODE,
    "minted": FloatKind.CODE,
    "verbatim": FloatKind.VERBATIM,
    "algorithm": FloatKind.ALGORITHM,
    "algorithmic": FloatKind.ALGORITHM,
    "thebibliography": FloatKind.BIBLIOGRAPHY,
    # Keywords are metadata that happens to be made of words. Read as prose
    # they become a paragraph nothing in the body supports, which is how a
    # keyword list ends up proposed for deletion.
    "IEEEkeywords": FloatKind.FRONT_MATTER,
    "keywords": FloatKind.FRONT_MATTER,
    "CCSXML": FloatKind.FRONT_MATTER,
}

CITATION_COMMANDS = frozenset(
    {
        "cite",
        "citep",
        "citet",
        "citealp",
        "citealt",
        "citeauthor",
        "citeyear",
        "autocite",
        "parencite",
        "textcite",
        "footcite",
        "nocite",
    }
)

# Commands whose braces hold identifiers, paths, or markup rather than prose.
# The whole invocation is protected and is not offered to any pass as text.
OPAQUE_ARGUMENT_COMMANDS = (
    frozenset(
        {
            "begin",
            "end",
            "label",
            "ref",
            "eqref",
            "autoref",
            "cref",
            "Cref",
            "pageref",
            "nameref",
            "url",
            "input",
            "include",
            "includegraphics",
            "bibliography",
            "bibliographystyle",
            "addbibresource",
            "usepackage",
            "documentclass",
            "newcommand",
            "renewcommand",
            "providecommand",
            "def",
            "setlength",
            "verb",
            "hspace",
            "vspace",
            "bibitem",
        }
    )
    | CITATION_COMMANDS
)

# Layout directives that carry no prose. They are cut out rather than merely
# frozen, because leaving `\item` inside a sentence would put it in front of
# every pass that reads sentence text.
MARKUP_COMMANDS = frozenset(
    {
        "item",
        "noindent",
        "indent",
        "centering",
        "raggedright",
        "hline",
        "toprule",
        "midrule",
        "bottomrule",
        "newpage",
        "clearpage",
        "newline",
        "maketitle",
        "tableofcontents",
        "listoffigures",
        "listoftables",
        "bigskip",
        "medskip",
        "smallskip",
        "par",
    }
)

# Commands whose argument is front matter rather than argument: who wrote the
# paper, where they work, and how to reach them. Every one of these holds real
# words, which is exactly why they have to be named. Read as prose they become
# paragraphs no body sentence supports, and an orphan paragraph is a deletion
# candidate.
#
# Named across templates on purpose. IEEEtran, acmart, and llncs each invent
# their own author macros, and the tool ships venue profiles for all three.
FRONT_MATTER_COMMANDS = frozenset(
    {
        "title",
        "author",
        "date",
        "thanks",
        "orcidlink",
        "IEEEauthorblockN",
        "IEEEauthorblockA",
        "IEEEpubid",
        "IEEEspecialpapernotice",
        "markboth",
        "affiliation",
        "institution",
        "streetaddress",
        "postcode",
        "city",
        "country",
        "email",
        "keywords",
        "ccsdesc",
        "shortauthors",
        "institute",
        "inst",
        "authorrunning",
        "titlerunning",
        "address",
        "additionalaffiliation",
    }
)

COMMAND = re.compile(r"\\([A-Za-z@]+)\*?")
LINE_BREAK = re.compile(r"\\\\(?:\s*\[[^\]]*\])?")
BLANK_LINE = re.compile(r"\n[ \t]*\n")
ENVIRONMENT_BEGIN = re.compile(r"\\begin\s*\{([A-Za-z@*]+)\}")
COMMENT = re.compile(r"(?<!\\)%[^\n]*")
INPUT_COMMAND = re.compile(r"\\(?:input|include)\s*\{([^}]*)\}")
BEGIN_DOCUMENT = re.compile(r"\\begin\s*\{document\}")
END_DOCUMENT = re.compile(r"\\end\s*\{document\}")
BIBLIOGRAPHY_COMMAND = re.compile(r"\\(?:bibliography|addbibresource)\s*\{([^}]*)\}")
BIBITEM = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
MAKETITLE = re.compile(r"\\maketitle\b")
ABSTRACT_BEGIN = re.compile(r"\\begin\s*\{abstract\*?\}")
SECTIONING = re.compile(r"\\(?:" + "|".join(SECTION_LEVELS) + r")\*?\s*[\[{]")

INLINE_MATH = (
    re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$", re.DOTALL),
    re.compile(r"(?<!\\)\$.*?(?<!\\)\$", re.DOTALL),
    re.compile(r"\\\(.*?\\\)", re.DOTALL),
)
DISPLAY_MATH = re.compile(r"\\\[.*?\\\]", re.DOTALL)

METADATA_COMMANDS = {"title": "title", "author": "author", "date": "date"}


@dataclass(frozen=True, slots=True)
class _Heading:
    start: int
    end: int
    title: str
    level: int


@dataclass(frozen=True, slots=True)
class _Prose:
    start: int
    end: int


def _comment_ranges(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in COMMENT.finditer(text)]


def _inside(ranges: list[tuple[int, int]], offset: int) -> bool:
    return any(low <= offset < high for low, high in ranges)


def _match_brace(text: str, open_index: int) -> int:
    """Index just past the `}` matching the `{` at `open_index`.

    Raises when the braces do not balance, because everything downstream would
    otherwise silently address the wrong range.
    """
    depth = 0
    index = open_index
    while index < len(text):
        character = text[index]
        if character == "\\":
            index += 2
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise IngestError(f"unbalanced braces starting at offset {open_index}")


def _find_environment_end(text: str, name: str, after: int) -> int:
    """End offset of the `\\end{name}` closing the environment opened at `after`."""
    opener = re.compile(r"\\begin\s*\{" + re.escape(name) + r"\}")
    closer = re.compile(r"\\end\s*\{" + re.escape(name) + r"\}")
    depth = 1
    index = after
    while index < len(text):
        next_open = opener.search(text, index)
        next_close = closer.search(text, index)
        if next_close is None:
            raise IngestError(f"environment {name!r} is never closed")
        if next_open is not None and next_open.start() < next_close.start():
            depth += 1
            index = next_open.end()
            continue
        depth -= 1
        if depth == 0:
            return next_close.end()
        index = next_close.end()
    raise IngestError(f"environment {name!r} is never closed")


class _Expander:
    """Splices `\\input` and `\\include` into one text, remembering the seams."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.parts: list[str] = []
        self.segments: list[FileSegment] = []
        self.offset = 0
        self.visited: set[Path] = set()

    def expand(self, path: Path, text: str) -> None:
        self.visited.add(path.resolve())
        comments = _comment_ranges(text)
        cursor = 0
        for match in INPUT_COMMAND.finditer(text):
            if _inside(comments, match.start()):
                continue
            child = self._resolve(match.group(1).strip())
            self._emit(path, text, cursor, match.start())
            if child.resolve() in self.visited:
                raise IngestError(f"{child.name} is included more than once, which would loop")
            self.expand(child, child.read_bytes().decode("utf-8"))
            cursor = match.end()
        self._emit(path, text, cursor, len(text))

    def _resolve(self, name: str) -> Path:
        candidate = self.root.parent / name
        for option in (candidate, candidate.with_suffix(".tex")):
            if option.is_file():
                return option
        raise IngestError(
            f"{self.root.name} inputs {name!r}, which does not exist. "
            f"Analysing a paper with a missing chunk would report the wrong word count "
            f"and miss whatever that chunk claims."
        )

    def _emit(self, path: Path, text: str, start: int, end: int) -> None:
        if end <= start:
            return
        self.parts.append(text[start:end])
        self.segments.append(
            FileSegment(
                global_start=self.offset,
                global_end=self.offset + (end - start),
                file=str(path),
                local_start=start,
            )
        )
        self.offset += end - start

    @property
    def text(self) -> str:
        return "".join(self.parts)


class _LatexWalker:
    def __init__(self, path: Path, source: str, segments: list[FileSegment]) -> None:
        self.path = path
        self.source = source
        self.segments = segments
        self.builder = DocumentBuilder(path, FORMAT, source)
        self.excluded: list[tuple[int, int]] = []
        self.protected: list[tuple[int, int]] = []
        self.comments: list[tuple[int, int]] = []
        self.headings: list[_Heading] = []
        self.pending_citations: list[tuple[int, int, str, str]] = []

    # Passes ----------------------------------------------------------------

    def run(self) -> Document:
        # Comments first. Every structural search below asks where the body
        # starts and where the front matter ends, and a paper whose comments
        # discuss `\begin{document}` would otherwise have its body start
        # inside a note to a co-author.
        self._mark_comments()
        body_start, body_end = self._mark_preamble_and_trailer()
        self._mark_front_matter(body_start, body_end)
        self._mark_environments(body_start, body_end)
        self._mark_math()
        self._scan_commands(body_start, body_end)
        self._emit_in_order(body_start, body_end)
        self._read_bibliography()

        for start, end in merge_ranges(self.protected):
            self.builder.add_protected(self.builder.span(start, end))
        if len(self.segments) > 1:
            self.builder.set_file_segments(self.segments)
        return self.builder.build()

    def _uncommented(
        self, pattern: re.Pattern[str], start: int = 0, end: int | None = None
    ) -> re.Match[str] | None:
        """First match of `pattern` that is not sitting inside a comment.

        A paper's comments talk about its own markup. `\\begin{document}` and
        `\\section{Introduction}` both appear in prose written to a co-author,
        and a structural search that believes them puts the body boundary in
        the wrong place.
        """
        position = start
        limit = len(self.source) if end is None else end
        while position < limit:
            match = pattern.search(self.source, position, limit)
            if match is None:
                return None
            if not _inside(self.comments, match.start()):
                return match
            position = match.start() + 1
        return None

    def _mark_preamble_and_trailer(self) -> tuple[int, int]:
        """Everything outside `document` is configuration, not argument."""
        opening = self._uncommented(BEGIN_DOCUMENT)
        closing = self._uncommented(END_DOCUMENT)
        body_start = opening.end() if opening else 0
        body_end = closing.start() if closing else len(self.source)

        if opening:
            self._exclude(0, body_start)
            self._read_preamble_metadata(self.source[:body_start])
        if closing:
            self._exclude(body_end, len(self.source))
        return body_start, body_end

    def _read_preamble_metadata(self, preamble: str) -> None:
        for match in COMMAND.finditer(preamble):
            field = METADATA_COMMANDS.get(match.group(1))
            if field is None or match.end() >= len(preamble) or preamble[match.end()] != "{":
                continue
            end = _match_brace(preamble, match.end())
            value = preamble[match.end() + 1 : end - 1].strip()
            if value:
                self.builder.set_metadata(field, value)

    def _mark_front_matter(self, body_start: int, body_end: int) -> None:
        """The run of the body that names the authors rather than making the argument.

        IEEEtran, acmart, and llncs all put `\\title` and `\\author` after
        `\\begin{document}`, so the preamble rule above never sees them. The
        affiliations then arrive at the analysis as ordinary paragraphs, get
        classified as orphans because no body sentence supports "Bengaluru,
        India", and are offered for deletion.

        The rule is structural rather than a list of macro names, because every
        template invents its own macros and a list is always one template
        behind. Everything from `\\begin{document}` to `\\maketitle` is front
        matter. Where there is no `\\maketitle`, the first section heading ends
        it.

        The abstract is the exception that has to be respected in both cases.
        It is prose, it is where `extract_claim` looks for the contribution,
        and `acmart` puts it before `\\maketitle`, so it caps the range.
        """
        end = self._front_matter_end(body_start, body_end)
        if end <= body_start:
            return
        self._read_metadata(self.source[body_start:end])
        self._exclude(body_start, end)
        self.builder.add_float(
            FloatKind.FRONT_MATTER, self.builder.span(body_start, end), label="front matter"
        )

    def _front_matter_end(self, body_start: int, body_end: int) -> int:
        limit = body_end
        stops = (
            self._uncommented(ABSTRACT_BEGIN, body_start, body_end),
            self._uncommented(SECTIONING, body_start, body_end),
        )
        found = [stop.start() for stop in stops if stop is not None]
        if found:
            limit = min(limit, min(found))

        title = self._uncommented(MAKETITLE, body_start, body_end)
        if title is not None and title.end() <= limit:
            return title.end()
        return limit if found else body_start

    def _read_metadata(self, region: str) -> None:
        """Title and author out of the body's front matter.

        Excluding the range is what stops it being analysed. Reading it first is
        what stops that being a loss: the paper still knows its own title, and
        the report can name what it skipped rather than silently dropping it.
        """
        for match in COMMAND.finditer(region):
            field = METADATA_COMMANDS.get(match.group(1))
            if field is None or match.end() >= len(region) or region[match.end()] != "{":
                continue
            end = _match_brace(region, match.end())
            value = _plain(region[match.end() + 1 : end - 1])
            if value and not self.builder.has_metadata(field):
                self.builder.set_metadata(field, value)

    def _mark_comments(self) -> None:
        """Full-line comments leave the prose. Trailing ones stay but are frozen.

        A comment on its own line is a note to a co-author and has no business
        in the analysis. A comment trailing a prose line cannot be cut without
        breaking the sentence into two spans, which would cost more than it
        buys, so it is protected from editing and hidden from segmentation
        instead.
        """
        for match in COMMENT.finditer(self.source):
            self.comments.append((match.start(), match.end()))
            line_start = self.source.rfind("\n", 0, match.start()) + 1
            if not self.source[line_start : match.start()].strip():
                self._exclude(line_start, match.end())
            else:
                self.protected.append((match.start(), match.end()))

    def _mark_environments(self, body_start: int, body_end: int) -> None:
        index = body_start
        while index < body_end:
            match = ENVIRONMENT_BEGIN.search(self.source, index, body_end)
            if match is None:
                return
            name = match.group(1).rstrip("*")
            kind = NON_PROSE_ENVIRONMENTS.get(name)
            if kind is None or self._is_excluded(match.start()):
                index = match.end()
                continue
            end = _find_environment_end(self.source, match.group(1), match.end())
            if name == "thebibliography":
                self._read_thebibliography(match.start(), end)
            self._exclude(match.start(), end)
            self.builder.add_float(
                kind, self.builder.span(match.start(), end), label=match.group(1)
            )
            index = end

    def _mark_math(self) -> None:
        """Inline math stays in the sentence. Display math is its own block."""
        for match in DISPLAY_MATH.finditer(self.source):
            if self._is_excluded(match.start()):
                continue
            self._exclude(match.start(), match.end())
            self.builder.add_float(
                FloatKind.EQUATION, self.builder.span(match.start(), match.end())
            )
        for pattern in INLINE_MATH:
            for match in pattern.finditer(self.source):
                if not self._is_excluded(match.start()):
                    self.protected.append((match.start(), match.end()))

    def _scan_commands(self, body_start: int, body_end: int) -> None:
        for line_break in LINE_BREAK.finditer(self.source, body_start, body_end):
            if not self._is_excluded(line_break.start()):
                self._exclude(line_break.start(), line_break.end())

        index = body_start
        while index < body_end:
            match = COMMAND.search(self.source, index, body_end)
            if match is None:
                return
            if self._is_excluded(match.start()):
                index = match.end()
                continue

            name = match.group(1)
            end = self._end_of_arguments(match.end())

            if name in SECTION_LEVELS:
                self._take_heading(name, match.start(), match.end(), end)
            elif name in FRONT_MATTER_COMMANDS:
                # Named on top of the structural rule above, because acmart
                # puts `\keywords` after the abstract and llncs puts
                # `\institute` wherever the author felt like it.
                self._take_front_matter(name, match.start(), match.end(), end)
            elif name in CITATION_COMMANDS:
                self._take_citation(name, match.start(), match.end(), end)
                self.protected.append((match.start(), end))
            elif name in MARKUP_COMMANDS:
                self._exclude(match.start(), end)
            elif name in OPAQUE_ARGUMENT_COMMANDS:
                self.protected.append((match.start(), end))
                if name in {"begin", "end"} or self._on_its_own_line(match.start(), end):
                    self._exclude(match.start(), end)
            else:
                # A formatting command such as \emph. The name and braces are
                # structure, the text between them is the author's prose.
                self.protected.append((match.start(), match.end()))
                self._protect_braces(match.end(), end)

            index = max(end, match.end())

    def _emit_in_order(self, body_start: int, body_end: int) -> None:
        """Feed headings and prose to the builder in document order."""
        blocked = merge_ranges(self.excluded)
        events: list[_Heading | _Prose] = list(self.headings)
        events.extend(
            _Prose(start, end) for start, end in self._prose_blocks(blocked, body_start, body_end)
        )
        events.sort(key=lambda event: event.start)

        for event in events:
            if isinstance(event, _Heading):
                self.builder.add_section(
                    event.title, event.level, self.builder.span(event.start, event.end)
                )
            else:
                self._add_paragraph(event.start, event.end)

        for start, end, key, raw in self.pending_citations:
            self.builder.add_citation(key=key, raw=raw, span=self.builder.span(start, end))

    # Helpers ---------------------------------------------------------------

    def _prose_blocks(
        self, blocked: list[tuple[int, int]], body_start: int, body_end: int
    ) -> list[tuple[int, int]]:
        """Runs of body text that survive exclusion, split on blank lines."""
        gaps: list[tuple[int, int]] = []
        cursor = body_start
        for low, high in blocked:
            if high <= body_start or low >= body_end:
                continue
            if low > cursor:
                gaps.append((cursor, min(low, body_end)))
            cursor = max(cursor, high)
        if cursor < body_end:
            gaps.append((cursor, body_end))

        blocks: list[tuple[int, int]] = []
        for low, high in gaps:
            segment = self.source[low:high]
            cursor = 0
            for separator in BLANK_LINE.finditer(segment):
                self._append_block(blocks, low + cursor, low + separator.start())
                cursor = separator.end()
            self._append_block(blocks, low + cursor, high)
        return blocks

    def _append_block(self, blocks: list[tuple[int, int]], start: int, end: int) -> None:
        trimmed = self._trim(start, end)
        if trimmed[1] > trimmed[0]:
            blocks.append(trimmed)

    def _trim(self, start: int, end: int) -> tuple[int, int]:
        """Drop surrounding whitespace, and any comment left hanging off the end.

        A comment trailing the last line of a paragraph would otherwise come
        out of segmentation as its own sentence, and a note to a co-author is
        not a claim to be checked.
        """
        while True:
            while start < end and self.source[start].isspace():
                start += 1
            while end > start and self.source[end - 1].isspace():
                end -= 1
            trailing = next((c for c in self.comments if c[1] == end and c[0] >= start), None)
            if trailing is None:
                return start, end
            end = trailing[0]

    def _add_paragraph(self, start: int, end: int) -> None:
        protected_inside = [
            (max(low, start), min(high, end))
            for low, high in merge_ranges(self.protected)
            if low < end and high > start
        ]
        self.builder.add_paragraph(self.builder.span(start, end), protected=protected_inside)

    def _take_heading(self, name: str, start: int, after_name: int, end: int) -> None:
        title = ""
        if after_name < len(self.source) and self.source[after_name] == "{":
            close = _match_brace(self.source, after_name)
            title = self.source[after_name + 1 : close - 1].strip()
        self.headings.append(_Heading(start, end, title, SECTION_LEVELS[name]))
        # The heading text is a title, not a claim, so it is not prose. The
        # command around it is structure either way.
        self._exclude(start, end)
        self.protected.append((start, after_name))

    def _take_front_matter(self, name: str, start: int, after_name: int, end: int) -> None:
        """Cut an author or keyword macro out, keeping what it declared."""
        field = METADATA_COMMANDS.get(name)
        if field is not None and after_name < len(self.source) and self.source[after_name] == "{":
            close = _match_brace(self.source, after_name)
            value = _plain(self.source[after_name + 1 : close - 1])
            if value and not self.builder.has_metadata(field):
                self.builder.set_metadata(field, value)
        self._exclude(start, end)
        self.builder.add_float(FloatKind.FRONT_MATTER, self.builder.span(start, end), label=name)

    def _take_citation(self, name: str, start: int, after_name: int, end: int) -> None:
        index = after_name
        while index < len(self.source) and self.source[index] in "[ ":
            index = _skip_optional(self.source, index)
        if index >= len(self.source) or self.source[index] != "{":
            return
        close = _match_brace(self.source, index)
        raw = self.source[start:end]
        for key in self.source[index + 1 : close - 1].split(","):
            cleaned = key.strip()
            if cleaned:
                self.pending_citations.append((start, end, cleaned, raw))

    def _read_thebibliography(self, start: int, end: int) -> None:
        entries = list(BIBITEM.finditer(self.source, start, end))
        for position, match in enumerate(entries):
            entry_end = entries[position + 1].start() if position + 1 < len(entries) else end
            span = self.builder.span(match.start(), entry_end)
            self.builder.add_citation(
                key=match.group(1).strip(),
                raw=self.source[match.start() : entry_end].strip(),
                span=span,
                in_bibliography=True,
            )

    def _read_bibliography(self) -> None:
        """Pull entry metadata out of the `.bib` file, if there is one.

        The entries live in another file that is deliberately not spliced into
        the document text, so each one is anchored at the `\\bibliography`
        command that pulls it in. What matters downstream is the metadata,
        which is the input citation verification works from.
        """
        match = self._uncommented(BIBLIOGRAPHY_COMMAND)
        if match is None:
            return
        span = self.builder.span(match.start(), match.end())
        parser = require("bibtexparser", "latex", "LaTeX bibliography parsing")

        for name in match.group(1).split(","):
            bib_path = self._resolve_bib(name.strip())
            if bib_path is None:
                continue
            database = parser.loads(bib_path.read_bytes().decode("utf-8"))
            for entry in database.entries:
                key = str(entry.get("ID", "")).strip()
                if not key:
                    continue
                self.builder.add_citation(
                    key=key,
                    raw=f"@{entry.get('ENTRYTYPE', 'misc')}{{{key}}} {entry.get('title', '')}",
                    span=span,
                    in_bibliography=True,
                    resolved=_to_resolved_work(entry),
                )

    def _resolve_bib(self, name: str) -> Path | None:
        if not name:
            return None
        candidate = self.path.parent / name
        for option in (candidate, candidate.with_suffix(".bib")):
            if option.is_file():
                return option
        raise IngestError(
            f"{self.path.name} points at bibliography {name!r}, which does not exist. "
            f"Citation verification has nothing to check against without it."
        )

    def _end_of_arguments(self, index: int) -> int:
        while index < len(self.source):
            if self.source[index] == "[":
                index = _skip_optional(self.source, index)
            elif self.source[index] == "{":
                index = _match_brace(self.source, index)
            else:
                break
        return index

    def _protect_braces(self, start: int, end: int) -> None:
        for position in range(start, min(end, len(self.source))):
            if self.source[position] in "{}":
                self.protected.append((position, position + 1))

    def _on_its_own_line(self, start: int, end: int) -> bool:
        """Whether this command is the only prose-bearing thing on its line.

        Text already cut out does not count as company. `\\section{Intro}` and
        `\\label{sec:intro}` share a line in most real papers, and the heading
        is excluded by the time the label is reached, so a label that looks
        accompanied is in fact alone. Without this the label survived as a
        paragraph whose whole text was `\\label{sec:intro}`, which then read as
        an orphan and became a deletion candidate.
        """
        line_start = self.source.rfind("\n", 0, start) + 1
        line_end = self.source.find("\n", end)
        line_end = len(self.source) if line_end < 0 else line_end
        return not self._residue(line_start, start) and not self._residue(end, line_end)

    def _residue(self, start: int, end: int) -> str:
        """What is left on a stretch of line once excluded ranges are removed."""
        kept = []
        for offset in range(start, end):
            if not self._is_excluded(offset):
                kept.append(self.source[offset])
        return "".join(kept).strip()

    def _exclude(self, start: int, end: int) -> None:
        if end > start:
            self.excluded.append((start, end))
            self.protected.append((start, end))

    def _is_excluded(self, offset: int) -> bool:
        return any(low <= offset < high for low, high in self.excluded)


def _plain(text: str) -> str:
    """A metadata value with its markup taken off.

    `\\author{\\IEEEauthorblockN{A. Researcher}}` should record the name, not
    the macro that wraps it. Only metadata goes through this. Prose is never
    rewritten, because a span has to recover the exact source characters.
    """
    stripped = LINE_BREAK.sub(" ", text)
    stripped = COMMAND.sub(" ", stripped).replace("{", " ").replace("}", " ")
    return " ".join(stripped.split())


def _skip_optional(text: str, index: int) -> int:
    """Index just past a `[...]` optional argument starting at `index`."""
    if index >= len(text) or text[index] != "[":
        return index + 1
    depth = 0
    while index < len(text):
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def _to_resolved_work(entry: dict[str, str]) -> ResolvedWork:
    year = entry.get("year", "").strip()
    authors = tuple(
        name.strip() for name in re.split(r"\s+and\s+", entry.get("author", "")) if name.strip()
    )
    return ResolvedWork(
        doi=entry.get("doi") or None,
        title=(entry.get("title") or "").strip("{} ") or None,
        year=int(year) if year.isdigit() else None,
        authors=authors,
        venue=entry.get("journal") or entry.get("booktitle") or None,
        source="bibtex",
        url=entry.get("url") or None,
    )


def ingest(path: Path | str, source: str | None = None) -> Document:
    """Build a `Document` from a LaTeX paper, following `\\input` as it goes."""
    require("bibtexparser", "latex", "LaTeX ingest")
    path = Path(path)
    text = path.read_bytes().decode("utf-8") if source is None else source

    expander = _Expander(path)
    expander.expand(path, text)
    return _LatexWalker(path, expander.text, expander.segments).run()
