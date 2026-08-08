"""Crossref: the canonical DOI registry, and the best source of retraction data.

A retraction shows up in `updated-by` on the retracted record, carrying the DOI
and date of the notice. That is what lets the tool tell an author which notice
to go read rather than just asserting a paper was pulled.
"""

from __future__ import annotations

import re
from typing import Any

from research_better.net import PoliteClient
from research_better.sources.base import SourceAdapter, Work, normalize_doi

BASE = "https://api.crossref.org/works"

RETRACTION_TYPES = frozenset({"retraction", "withdrawal", "removal"})
JATS_TAG = re.compile(r"<[^>]+>")


def _year(record: dict[str, Any]) -> int | None:
    for key in ("issued", "published", "published-print", "published-online", "created"):
        parts = (record.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def _first(values: Any) -> str | None:
    if isinstance(values, list) and values:
        return str(values[0])
    return str(values) if isinstance(values, str) and values else None


def _authors(record: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for entry in record.get("author") or []:
        family = entry.get("family")
        given = entry.get("given")
        if family and given:
            names.append(f"{family}, {given}")
        elif family:
            names.append(str(family))
        elif entry.get("name"):
            names.append(str(entry["name"]))
    return tuple(names)


def _retraction(record: dict[str, Any]) -> tuple[bool, str | None, str | None]:
    for update in record.get("updated-by") or []:
        if str(update.get("type", "")).lower() in RETRACTION_TYPES:
            parts = (update.get("updated") or {}).get("date-parts") or []
            stamp = "-".join(str(piece) for piece in parts[0]) if parts and parts[0] else None
            return True, normalize_doi(update.get("DOI")), stamp
    # Some publishers only mark it in the title, and a reader deserves to know
    # either way.
    title = _first(record.get("title")) or ""
    if title.upper().startswith(("RETRACTED", "WITHDRAWN")):
        return True, None, None
    return False, None, None


def _work_from(record: dict[str, Any]) -> Work:
    retracted, notice_doi, notice_date = _retraction(record)
    abstract = record.get("abstract")
    return Work(
        title=_first(record.get("title")) or "",
        authors=_authors(record),
        year=_year(record),
        venue=_first(record.get("container-title")),
        doi=normalize_doi(record.get("DOI")),
        abstract=JATS_TAG.sub("", abstract).strip() if abstract else None,
        citation_count=int(record.get("is-referenced-by-count") or 0),
        retracted=retracted,
        retraction_doi=notice_doi,
        retraction_date=notice_date,
        work_type=record.get("type"),
        sources=("crossref",),
        identifiers={"doi": str(record.get("DOI"))} if record.get("DOI") else {},
    )


class CrossrefAdapter(SourceAdapter):
    name = "crossref"
    label = "Crossref"

    def search(self, client: PoliteClient, query: str, limit: int = 10) -> list[Work]:
        response = client.get(
            self.name,
            BASE,
            params={"query.bibliographic": query, "rows": str(min(limit, 20))},
        )
        if not response.ok:
            return []
        items = (response.json().get("message") or {}).get("items") or []
        return [_work_from(record) for record in items[:limit]]

    def by_doi(self, client: PoliteClient, doi: str) -> Work | None:
        bare = normalize_doi(doi)
        if not bare:
            return None
        response = client.get(
            self.name, f"{BASE}/{bare}", ttl_seconds=client.limits.record_ttl_seconds
        )
        if not response.ok:
            return None
        message = (response.json() or {}).get("message")
        return _work_from(message) if message else None
