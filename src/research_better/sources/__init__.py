"""The retrieval layer: query every source at once, merge, dedup, rank.

The contract that matters is that a slow or dead source degrades the answer and
never fails the run. A citation check that consulted three of four databases is
worth having. One that raises because arXiv timed out is not.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from research_better.net import PoliteClient
from research_better.sources.arxiv import ArxivAdapter
from research_better.sources.base import SourceAdapter, Work, normalize_doi
from research_better.sources.crossref import CrossrefAdapter
from research_better.sources.merge import DEFAULT_WEIGHTS, RankingWeights, deduplicate, rank
from research_better.sources.openalex import OpenAlexAdapter
from research_better.sources.semantic_scholar import SemanticScholarAdapter


def default_adapters() -> list[SourceAdapter]:
    return [
        OpenAlexAdapter(),
        CrossrefAdapter(),
        SemanticScholarAdapter(),
        ArxivAdapter(),
    ]


@dataclass(frozen=True, slots=True)
class SearchResult:
    """What came back, and just as importantly what did not.

    `unavailable` is not an implementation detail. A verdict of "not found"
    means something different when three sources answered than when one did,
    and the report has to be able to say which.
    """

    works: tuple[Work, ...] = ()
    queried: tuple[str, ...] = ()
    unavailable: dict[str, str] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return not self.unavailable

    def coverage_note(self) -> str:
        if self.complete:
            return f"searched {len(self.queried)} sources: {', '.join(self.queried)}"
        missing = ", ".join(
            f"{name} ({reason})" for name, reason in sorted(self.unavailable.items())
        )
        return (
            f"searched {len(self.queried)} of {len(self.queried) + len(self.unavailable)} "
            f"sources. Could not reach: {missing}"
        )

    def to_json(self) -> dict[str, object]:
        return {
            "works": [work.to_json() for work in self.works],
            "sources_queried": list(self.queried),
            "sources_unavailable": dict(self.unavailable),
            "coverage_note": self.coverage_note(),
        }


def _gather(
    client: PoliteClient,
    adapters: list[SourceAdapter],
    call: str,
    *args: object,
) -> tuple[list[Work], list[str], dict[str, str]]:
    def bind(adapter: SourceAdapter) -> Callable[[], object]:
        # Bound in a closure factory rather than a default argument, so every
        # thread gets its own adapter rather than whichever one the loop
        # variable happened to hold when the pool got round to it.
        return lambda: getattr(adapter, call)(client, *args)

    calls = [(adapter.name, bind(adapter)) for adapter in adapters]
    works: list[Work] = []
    queried: list[str] = []
    unavailable: dict[str, str] = {}

    for name, value, error in client.gather(calls):
        if error is not None:
            unavailable[name] = type(error).__name__
            continue
        queried.append(name)
        found = value if isinstance(value, list) else ([value] if value else [])
        works.extend(found)

    return works, queried, unavailable


def search(
    client: PoliteClient,
    query: str,
    limit: int = 10,
    adapters: list[SourceAdapter] | None = None,
    weights: RankingWeights = DEFAULT_WEIGHTS,
    current_year: int | None = None,
) -> SearchResult:
    """Free-text search across every source, merged and ranked."""
    chosen = adapters if adapters is not None else default_adapters()
    works, queried, unavailable = _gather(client, chosen, "search", query, limit)
    year = current_year or datetime.now(UTC).year
    ranked = rank(deduplicate(works), query, year, weights)
    return SearchResult(tuple(ranked[:limit]), tuple(sorted(queried)), unavailable)


def find_by_doi(
    client: PoliteClient,
    doi: str,
    adapters: list[SourceAdapter] | None = None,
) -> SearchResult:
    """Exact lookup across every source, merged into one record where found."""
    bare = normalize_doi(doi)
    if not bare:
        return SearchResult()
    chosen = adapters if adapters is not None else default_adapters()
    works, queried, unavailable = _gather(client, chosen, "by_doi", bare)
    return SearchResult(tuple(deduplicate(works)), tuple(sorted(queried)), unavailable)


def find_by_title(
    client: PoliteClient,
    title: str,
    limit: int = 5,
    adapters: list[SourceAdapter] | None = None,
    current_year: int | None = None,
) -> SearchResult:
    """Title lookup, which is how a bibliography entry without a DOI is resolved."""
    chosen = adapters if adapters is not None else default_adapters()
    works, queried, unavailable = _gather(client, chosen, "by_title", title, limit)
    year = current_year or datetime.now(UTC).year
    ranked = rank(deduplicate(works), title, year)
    return SearchResult(tuple(ranked[:limit]), tuple(sorted(queried)), unavailable)


__all__ = [
    "ArxivAdapter",
    "CrossrefAdapter",
    "OpenAlexAdapter",
    "RankingWeights",
    "SearchResult",
    "SemanticScholarAdapter",
    "SourceAdapter",
    "Work",
    "deduplicate",
    "default_adapters",
    "find_by_doi",
    "find_by_title",
    "rank",
    "search",
]
