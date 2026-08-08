"""The record every source is normalized into, and the contract adapters meet.

Four databases with four different field names, four different notions of what
a title is, and four different ways of saying a paper was retracted. Everything
downstream sees one shape, so adding a fifth source means writing one module
and touching nothing else.
"""

from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import Any

from research_better.net import PoliteClient

DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
PUNCTUATION = re.compile(r"[^\w\s]")
WHITESPACE = re.compile(r"\s+")
RETRACTED_PREFIX = re.compile(r"^\s*(?:retracted|withdrawn)\b[:\s]*", re.IGNORECASE)


def trim_doi(raw: str) -> str:
    """Cut trailing punctuation off a DOI without cutting into the DOI.

    Elsevier DOIs contain parentheses, as in `10.1016/S0140-6736(97)11096-0`, so
    a pattern that stops at the first bracket truncates them. This takes the
    permissive match and walks back from the end while the last character is
    punctuation that cannot end a DOI, or is a closing bracket with no opener.
    """
    trimmed = raw.strip()
    while trimmed:
        last = trimmed[-1]
        unbalanced = (last == ")" and trimmed.count("(") < trimmed.count(")")) or (
            last == "]" and trimmed.count("[") < trimmed.count("]")
        )
        if last not in ".,;:" and not unbalanced:
            break
        trimmed = trimmed[:-1]
    return trimmed


def normalize_doi(value: str | None) -> str | None:
    """Strip the many ways a DOI gets written down to the bare identifier."""
    if not value:
        return None
    return trim_doi(DOI_PREFIX.sub("", value.strip())).lower() or None


def normalize_arxiv(value: str | None) -> str | None:
    if not value:
        return None
    match = ARXIV_ID.search(value)
    # The version suffix is dropped on purpose. v1 and v3 of a preprint are the
    # same work, and keeping them apart would defeat the dedup that exists to
    # collapse a preprint with its published version.
    return match.group(1) if match else None


def normalize_title(value: str | None) -> str:
    """Reduce a title to what a librarian would call the same title.

    Case, punctuation, accents, and a leading RETRACTED marker all go. What
    survives is the word sequence, which is what actually identifies a work.
    """
    if not value:
        return ""
    stripped = RETRACTED_PREFIX.sub("", value)
    folded = unicodedata.normalize("NFKD", stripped)
    folded = "".join(character for character in folded if not unicodedata.combining(character))
    folded = PUNCTUATION.sub(" ", folded.lower())
    return WHITESPACE.sub(" ", folded).strip()


def surname(author: str) -> str:
    """Best effort at a family name from either `Smith, Jane` or `Jane Smith`."""
    cleaned = author.strip()
    if not cleaned:
        return ""
    if "," in cleaned:
        return normalize_title(cleaned.split(",")[0])
    return normalize_title(cleaned.split()[-1])


@dataclass(frozen=True, slots=True)
class Work:
    """One scholarly work, however many databases it was found in."""

    title: str
    authors: tuple[str, ...] = ()
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    abstract: str | None = None
    citation_count: int = 0
    open_access_url: str | None = None
    retracted: bool = False
    retraction_doi: str | None = None
    retraction_date: str | None = None
    work_type: str | None = None
    sources: tuple[str, ...] = ()
    """Which databases this record came from. Kept because a verdict that says
    where it looked is arguable and one that does not is an oracle."""

    identifiers: dict[str, str] = field(default_factory=dict)
    relevance: float = 0.0

    @property
    def normalized_title(self) -> str:
        return normalize_title(self.title)

    @property
    def first_author_surname(self) -> str:
        return surname(self.authors[0]) if self.authors else ""

    @property
    def is_preprint_only(self) -> bool:
        return self.arxiv_id is not None and self.doi is None

    def merged_with(self, other: Work) -> Work:
        """Combine two records of the same work, keeping the better of each field.

        Deliberately non-destructive. An arXiv record has the abstract, the
        Crossref record has the venue, and OpenAlex has the citation count, so
        the union is worth more than any one of them.
        """
        return replace(
            self,
            title=self.title if len(self.title) >= len(other.title) else other.title,
            authors=self.authors or other.authors,
            year=_earliest(self.year, other.year),
            venue=self.venue or other.venue,
            doi=self.doi or other.doi,
            arxiv_id=self.arxiv_id or other.arxiv_id,
            abstract=_longer(self.abstract, other.abstract),
            citation_count=max(self.citation_count, other.citation_count),
            open_access_url=self.open_access_url or other.open_access_url,
            retracted=self.retracted or other.retracted,
            retraction_doi=self.retraction_doi or other.retraction_doi,
            retraction_date=self.retraction_date or other.retraction_date,
            work_type=self.work_type or other.work_type,
            sources=tuple(sorted(set(self.sources) | set(other.sources))),
            identifiers={**other.identifiers, **self.identifiers},
            relevance=max(self.relevance, other.relevance),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "venue": self.venue,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "abstract": self.abstract,
            "citation_count": self.citation_count,
            "open_access_url": self.open_access_url,
            "retracted": self.retracted,
            "retraction_doi": self.retraction_doi,
            "retraction_date": self.retraction_date,
            "work_type": self.work_type,
            "sources": list(self.sources),
            "identifiers": dict(self.identifiers),
            "relevance": round(self.relevance, 4),
        }


def _earliest(left: int | None, right: int | None) -> int | None:
    """The earlier year wins.

    A preprint and its published version differ by a year or two, and the
    preprint date is when the work entered the record.
    """
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _longer(left: str | None, right: str | None) -> str | None:
    if not left:
        return right
    if not right:
        return left
    return left if len(left) >= len(right) else right


class SourceAdapter(ABC):
    """One scholarly database.

    Adapters never build an HTTP client, set a header, or decide how long to
    wait. They are handed a client and they parse what comes back, which is why
    adding a source cannot make the tool impolite.
    """

    name: str
    label: str

    @abstractmethod
    def search(self, client: PoliteClient, query: str, limit: int = 10) -> list[Work]:
        """Free-text search. Returns an empty list rather than raising on no hits."""

    @abstractmethod
    def by_doi(self, client: PoliteClient, doi: str) -> Work | None:
        """Exact lookup. Returns None when the source has no such record."""

    def by_title(self, client: PoliteClient, title: str, limit: int = 5) -> list[Work]:
        """Title lookup, defaulting to search. Sources with a better endpoint
        override this."""
        return self.search(client, title, limit)
