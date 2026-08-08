"""OpenAlex: the widest coverage, and the only source that reports retraction
status as a plain boolean."""

from __future__ import annotations

from typing import Any

from research_better.net import PoliteClient, Response
from research_better.sources.base import (
    SourceAdapter,
    Work,
    normalize_arxiv,
    normalize_doi,
)

BASE = "https://api.openalex.org/works"


def _abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """Rebuild an abstract from OpenAlex's inverted index.

    OpenAlex stores abstracts as {word: [positions]} rather than as text, for
    licensing reasons. Reversing it is lossy about whitespace and nothing else.
    """
    if not inverted:
        return None
    positions: dict[int, str] = {}
    for word, places in inverted.items():
        for place in places:
            positions[place] = word
    if not positions:
        return None
    return " ".join(positions[index] for index in sorted(positions))


def _work_from(record: dict[str, Any]) -> Work:
    authorships = record.get("authorships") or []
    location = record.get("primary_location") or {}
    source = location.get("source") or {}
    best_oa = record.get("best_oa_location") or {}

    return Work(
        title=record.get("display_name") or record.get("title") or "",
        authors=tuple(
            (entry.get("author") or {}).get("display_name", "")
            for entry in authorships
            if (entry.get("author") or {}).get("display_name")
        ),
        year=record.get("publication_year"),
        venue=source.get("display_name"),
        doi=normalize_doi(record.get("doi")),
        arxiv_id=normalize_arxiv((record.get("ids") or {}).get("arxiv")),
        abstract=_abstract(record.get("abstract_inverted_index")),
        citation_count=int(record.get("cited_by_count") or 0),
        open_access_url=best_oa.get("pdf_url") or best_oa.get("landing_page_url"),
        retracted=bool(record.get("is_retracted")),
        work_type=record.get("type"),
        sources=("openalex",),
        identifiers={
            key: str(value) for key, value in (record.get("ids") or {}).items() if value is not None
        },
    )


class OpenAlexAdapter(SourceAdapter):
    name = "openalex"
    label = "OpenAlex"

    def search(self, client: PoliteClient, query: str, limit: int = 10) -> list[Work]:
        response = client.get(
            self.name,
            BASE,
            params={"search": query, "per-page": str(min(limit, 25))},
        )
        return self._works(response, limit)

    def by_doi(self, client: PoliteClient, doi: str) -> Work | None:
        bare = normalize_doi(doi)
        if not bare:
            return None
        response = client.get(
            self.name,
            f"{BASE}/https://doi.org/{bare}",
            ttl_seconds=client.limits.record_ttl_seconds,
        )
        if not response.ok:
            return None
        return _work_from(response.json())

    def by_title(self, client: PoliteClient, title: str, limit: int = 5) -> list[Work]:
        response = client.get(
            self.name,
            BASE,
            params={"filter": f"title.search:{title}", "per-page": str(min(limit, 25))},
        )
        return self._works(response, limit)

    def _works(self, response: Response, limit: int) -> list[Work]:
        if not response.ok:
            return []
        results = response.json().get("results") or []
        return [_work_from(record) for record in results[:limit]]
