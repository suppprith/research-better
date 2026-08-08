"""arXiv: Atom XML, and often the only place recent CS work exists at all.

Parsed with the standard library rather than a dependency. The feed is small
and its shape is stable, and an XML parser is not worth an extra install for
somebody who only wanted to check their citations.
"""

from __future__ import annotations

from xml.etree import ElementTree

from research_better.net import PoliteClient
from research_better.sources.base import SourceAdapter, Work, normalize_arxiv, normalize_doi

BASE = "https://export.arxiv.org/api/query"

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"


def _text(node: ElementTree.Element | None) -> str:
    return " ".join(node.text.split()) if node is not None and node.text else ""


def _work_from(entry: ElementTree.Element) -> Work:
    identifier = _text(entry.find(f"{ATOM}id"))
    pdf_url = None
    for link in entry.findall(f"{ATOM}link"):
        if link.get("title") == "pdf":
            pdf_url = link.get("href")

    published = _text(entry.find(f"{ATOM}published"))
    year = int(published[:4]) if published[:4].isdigit() else None

    return Work(
        title=_text(entry.find(f"{ATOM}title")),
        authors=tuple(
            _text(author.find(f"{ATOM}name")) for author in entry.findall(f"{ATOM}author")
        ),
        year=year,
        venue="arXiv",
        doi=normalize_doi(_text(entry.find(f"{ARXIV}doi")) or None),
        arxiv_id=normalize_arxiv(identifier),
        abstract=_text(entry.find(f"{ATOM}summary")) or None,
        open_access_url=pdf_url,
        work_type="preprint",
        sources=("arxiv",),
        identifiers={"arxiv": identifier} if identifier else {},
    )


def parse_feed(xml: str) -> list[Work]:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        # A malformed feed is a bad day at arXiv, not a reason to fail the run.
        return []
    return [_work_from(entry) for entry in root.findall(f"{ATOM}entry")]


class ArxivAdapter(SourceAdapter):
    name = "arxiv"
    label = "arXiv"

    def search(self, client: PoliteClient, query: str, limit: int = 10) -> list[Work]:
        response = client.get(
            self.name,
            BASE,
            params={
                "search_query": f"all:{query}",
                "max_results": str(min(limit, 20)),
                "sortBy": "relevance",
            },
        )
        return parse_feed(response.text)[:limit] if response.ok else []

    def by_doi(self, client: PoliteClient, doi: str) -> Work | None:
        """arXiv has no DOI index, so this looks the DOI up as free text.

        A preprint that was later published carries the published DOI in its
        metadata, so this finds some of them and honestly misses the rest.
        """
        bare = normalize_doi(doi)
        if not bare:
            return None
        found = self.search(client, bare, limit=1)
        return found[0] if found and found[0].doi == bare else None

    def by_title(self, client: PoliteClient, title: str, limit: int = 5) -> list[Work]:
        cleaned = title.replace('"', " ").strip()
        response = client.get(
            self.name,
            BASE,
            params={"search_query": f'ti:"{cleaned}"', "max_results": str(min(limit, 20))},
        )
        return parse_feed(response.text)[:limit] if response.ok else []
