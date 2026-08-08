"""Reading a bibliography entry back into structured fields.

Two paths with very different reliability, and the difference is worth being
explicit about rather than hiding behind one function name.

A LaTeX paper with a `.bib` file arrives already structured, because the ingest
adapter parsed BibTeX and filled `Citation.resolved`. Those fields are exact.

A Markdown paper arrives as a line of prose that somebody typed, in whatever
style their venue asked for. There is no format to parse, only conventions to
guess at, and the guessing is why `UNPARSEABLE` exists as a verdict rather than
being swept into `NOT_FOUND`. An entry this cannot read is a fact about the
entry, not about whether the work exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from research_better.model import Citation
from research_better.sources.base import normalize_arxiv, normalize_doi, surname

YEAR = re.compile(r"\b(1[89]\d{2}|20[0-4]\d)\b")
DOI_IN_TEXT = re.compile(
    # Permissive on purpose, then trimmed by trim_doi. Elsevier DOIs contain
    # parentheses and a pattern that stops at the first bracket truncates them.
    r"(?:doi:\s*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/\S+)",
    re.IGNORECASE,
)
ARXIV_IN_TEXT = re.compile(
    r"(?:arxiv:\s*|https?://arxiv\.org/abs/)(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE
)
LEADING_LABEL = re.compile(r"^\s*[\[\(]?[\w.-]{1,12}[\]\)]\s*")

# A period after a single capital letter is an initial, not the end of a field.
# Splitting on it is why a naive parser turns "Ferreira, L. and Osei, N. Adaptive
# Query Expansion" into an entry titled "Ferreira, L".
SENTENCE_BREAK = re.compile(r"(?<!\b[A-Z])\.\s+")
INITIAL = re.compile(r"\b[A-Z]\.(?=\s|$)")

AUTHOR_BLOCK_LIMIT = 0.6
"""Fraction of the entry that the author list is allowed to occupy. A capital
letter followed by a period in the venue ("Proc. ACM") would otherwise swallow
the title."""

# Entry kinds that scholarly databases index poorly or not at all. Reporting
# one of these as missing without saying why would read as a fabrication
# signal, and it is nothing of the sort.
UNINDEXED_MARKERS = (
    (
        "thesis",
        (
            "phd thesis",
            "master's thesis",
            "masters thesis",
            "doctoral dissertation",
            "dissertation",
        ),
    ),
    ("book", ("press", "publishers", "publishing", "isbn", "edition", "chapter in")),
    ("standard", ("rfc ", "iso ", "ieee std", "w3c ", "ansi ")),
    ("report", ("technical report", "tech. rep", "working paper", "white paper")),
)


@dataclass(frozen=True, slots=True)
class BibliographyEntry:
    """One reference, as far as it could be read."""

    key: str
    raw: str
    title: str | None = None
    authors: tuple[str, ...] = ()
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    kind: str | None = None
    exact: bool = False
    """True when the fields came from a BibTeX record rather than from guessing
    at a line of prose."""

    @property
    def readable(self) -> bool:
        return bool(self.title or self.doi or self.arxiv_id)

    @property
    def likely_unindexed(self) -> bool:
        """Whether this kind of work is routinely absent from the databases."""
        return self.kind in {"thesis", "book", "standard", "report"}

    @property
    def surnames(self) -> tuple[str, ...]:
        return tuple(filter(None, (surname(author) for author in self.authors)))


def _kind_of(text: str) -> str | None:
    lowered = text.lower()
    for kind, markers in UNINDEXED_MARKERS:
        if any(marker in lowered for marker in markers):
            return kind
    return None


def _looks_like_authors(segment: str) -> bool:
    """Whether a leading segment reads as a name list rather than a title.

    Initials and the word "and" are the two signals that survive across the
    citation styles this has to cope with.
    """
    if not segment or len(segment) > 200:
        return False
    return bool(INITIAL.search(segment)) or " and " in segment.lower()


NEXT_SURNAME = re.compile(r",\s*(?=[A-Z][a-z])")


def _split_authors(segment: str) -> tuple[str, ...]:
    """Break an author block into names.

    Commas do double duty: they separate authors and they separate a surname
    from its initials. The second comma in `Manning, C. D., Raghavan, P.` starts
    a new author and the first does not, and what tells them apart is that a new
    author's surname continues in lowercase while an initial does not.
    """
    names: list[str] = []
    for chunk in re.split(r",?\s+and\s+|;\s*", segment):
        for part in NEXT_SURNAME.split(chunk):
            cleaned = part.strip().strip(",.")
            if cleaned and len(cleaned) > 1:
                names.append(cleaned)
    return tuple(names)


def _split_author_block(text: str) -> tuple[tuple[str, ...], str]:
    """Cut the leading author list off, using the last initial as the boundary.

    Almost every citation style writes `Authors. Title. Venue, Year`, and the
    author block is the part made of surnames and initials. The last initial in
    that opening run is where it ends, which handles `Manning, C. D., Raghavan,
    P., and Schutze, H.` without needing to know the style.
    """
    limit = max(120, int(len(text) * AUTHOR_BLOCK_LIMIT))
    candidates = [match for match in INITIAL.finditer(text) if match.end() <= limit]
    if not candidates:
        return (), text

    boundary = candidates[-1].end()
    remainder = text[boundary:].lstrip(" ,")
    if not remainder:
        return (), text
    return _split_authors(text[:boundary]), remainder


def parse_entry(citation: Citation) -> BibliographyEntry:
    """Read one bibliography entry, exactly where possible and by guess otherwise."""
    if citation.resolved is not None:
        work = citation.resolved
        return BibliographyEntry(
            key=citation.key,
            raw=citation.raw,
            title=work.title,
            authors=work.authors,
            year=work.year,
            doi=normalize_doi(work.doi),
            arxiv_id=normalize_arxiv(work.url) if work.url else None,
            kind=_kind_of(citation.raw),
            exact=True,
        )

    text = LEADING_LABEL.sub("", " ".join(citation.raw.split()))
    doi_match = DOI_IN_TEXT.search(text)
    arxiv_match = ARXIV_IN_TEXT.search(text)
    year_match = YEAR.search(text)

    authors, remainder = _split_author_block(text)
    segments = [piece.strip() for piece in SENTENCE_BREAK.split(remainder) if piece.strip()]
    title: str | None = None

    if segments:
        if not authors and _looks_like_authors(segments[0]) and len(segments) > 1:
            authors = _split_authors(segments[0])
            title = segments[1]
        else:
            title = segments[0]

    if title:
        title = title.strip().rstrip(".,;")
        # A trailing URL or DOI is not part of the title.
        title = DOI_IN_TEXT.sub("", title).strip().rstrip(".,;") or None

    return BibliographyEntry(
        key=citation.key,
        raw=citation.raw,
        title=title or None,
        authors=authors,
        year=int(year_match.group(1)) if year_match else None,
        doi=normalize_doi(doi_match.group(1)) if doi_match else None,
        arxiv_id=normalize_arxiv(arxiv_match.group(1)) if arxiv_match else None,
        kind=_kind_of(text),
        exact=False,
    )


def bibliography(citations: tuple[Citation, ...]) -> list[BibliographyEntry]:
    return [parse_entry(citation) for citation in citations if citation.in_bibliography]
