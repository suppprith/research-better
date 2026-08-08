"""Semantic Scholar: the best abstracts, and the hardest rate limit.

Without an API key this source returns 429 more often than it returns data.
That is not a bug to work around, it is the deal: the endpoint is free and
shared. The adapter treats a 429 as an empty result rather than an error, so a
throttled Semantic Scholar quietly contributes nothing instead of taking the
run down with it.

Set SEMANTIC_SCHOLAR_API_KEY to get a usable rate. The tool works without it.
"""

from __future__ import annotations

import os
from typing import Any

from research_better.net import PoliteClient
from research_better.sources.base import SourceAdapter, Work, normalize_arxiv, normalize_doi

BASE = "https://api.semanticscholar.org/graph/v1"
API_KEY_ENVIRONMENT_VARIABLE = "SEMANTIC_SCHOLAR_API_KEY"

FIELDS = (
    "title,year,authors,abstract,externalIds,citationCount,venue,openAccessPdf,publicationTypes"
)


def _work_from(record: dict[str, Any]) -> Work:
    external = record.get("externalIds") or {}
    open_access = record.get("openAccessPdf") or {}
    types = record.get("publicationTypes") or []
    return Work(
        title=record.get("title") or "",
        authors=tuple(
            entry.get("name", "") for entry in record.get("authors") or [] if entry.get("name")
        ),
        year=record.get("year"),
        venue=record.get("venue") or None,
        doi=normalize_doi(external.get("DOI")),
        arxiv_id=normalize_arxiv(external.get("ArXiv")),
        abstract=record.get("abstract"),
        citation_count=int(record.get("citationCount") or 0),
        open_access_url=open_access.get("url"),
        work_type=str(types[0]).lower() if types else None,
        sources=("semantic_scholar",),
        identifiers={str(k): str(v) for k, v in external.items() if v is not None},
    )


class SemanticScholarAdapter(SourceAdapter):
    name = "semantic_scholar"
    label = "Semantic Scholar"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get(API_KEY_ENVIRONMENT_VARIABLE) or None

    def search(self, client: PoliteClient, query: str, limit: int = 10) -> list[Work]:
        response = client.get(
            self.name,
            f"{BASE}/paper/search",
            params={"query": query, "limit": str(min(limit, 20)), "fields": FIELDS},
        )
        if not response.ok:
            return []
        return [_work_from(record) for record in (response.json().get("data") or [])][:limit]

    def by_doi(self, client: PoliteClient, doi: str) -> Work | None:
        bare = normalize_doi(doi)
        if not bare:
            return None
        response = client.get(
            self.name,
            f"{BASE}/paper/DOI:{bare}",
            params={"fields": FIELDS},
            ttl_seconds=client.limits.record_ttl_seconds,
        )
        return _work_from(response.json()) if response.ok else None
