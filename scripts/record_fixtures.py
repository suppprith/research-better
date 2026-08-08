"""Record real API responses into the test fixture cache.

CI runs offline against these. Re-record when a source changes its response
shape, which is what the weekly network job in .github/workflows/network.yml
exists to notice.

    python scripts/record_fixtures.py            # only what is missing
    python scripts/record_fixtures.py --refresh  # replace everything

Set RESEARCH_BETTER_CONTACT first. It is a courtesy to the people running these
services for free, and it gets better throughput.

Recorded responses are checked into the repository on purpose. A reviewer
looking at a wrong verdict should be able to open the file and see exactly what
the API said, without a network call and without trusting a summary.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from research_better.net import HttpCache, PoliteClient, resolve_contact  # noqa: E402
from research_better.sources import (  # noqa: E402
    ArxivAdapter,
    CrossrefAdapter,
    OpenAlexAdapter,
    SemanticScholarAdapter,
)

FIXTURE_CACHE = REPO / "tests" / "fixtures" / "http"

# Chosen to cover the cases the verification tests need: a real and heavily
# cited paper, a real paper whose title is commonly mis-cited, a retracted
# paper with a Crossref retraction notice, and a query that finds nothing.
REAL_DOI = "10.1561/1500000019"
"""Robertson and Zaragoza, BM25 and Beyond. Real, and in every source."""

RETRACTED_DOI = "10.1016/S0140-6736(97)11096-0"
"""Retracted, with a Crossref retraction relationship pointing at the notice."""

DENSE_RETRIEVAL_TITLE = "Dense Passage Retrieval for Open-Domain Question Answering"
"""Real work by Karpukhin and Oguz. The fixture paper cites these authors under
a title they never wrote, which is the TITLE_MISMATCH case."""

INVENTED_TITLE = "Adaptive Query Expansion Under Drift Ferreira Osei"
"""Invented in the fixture paper. Should find nothing, which is the NOT_FOUND
case, and NOT_FOUND is never reported as proof of fabrication."""


def record(refresh: bool) -> int:
    contact = resolve_contact()
    if not contact:
        print(
            "No RESEARCH_BETTER_CONTACT set. Recording anyway, but set it: these "
            "are free services and identifying yourself is the deal.",
            file=sys.stderr,
        )

    cache = HttpCache(FIXTURE_CACHE, ignore_ttl=True)
    openalex, crossref, semantic, arxiv = (
        OpenAlexAdapter(),
        CrossrefAdapter(),
        SemanticScholarAdapter(),
        ArxivAdapter(),
    )

    with PoliteClient(cache, contact=contact, refresh=refresh) as client:
        plan = [
            ("openalex by_doi real", lambda: openalex.by_doi(client, REAL_DOI)),
            ("crossref by_doi real", lambda: crossref.by_doi(client, REAL_DOI)),
            ("semantic_scholar by_doi real", lambda: semantic.by_doi(client, REAL_DOI)),
            ("arxiv by_doi real", lambda: arxiv.by_doi(client, REAL_DOI)),
            ("crossref by_doi retracted", lambda: crossref.by_doi(client, RETRACTED_DOI)),
            ("openalex by_doi retracted", lambda: openalex.by_doi(client, RETRACTED_DOI)),
            ("openalex by_title dense", lambda: openalex.by_title(client, DENSE_RETRIEVAL_TITLE)),
            ("crossref by_title dense", lambda: crossref.by_title(client, DENSE_RETRIEVAL_TITLE)),
            ("arxiv by_title dense", lambda: arxiv.by_title(client, DENSE_RETRIEVAL_TITLE)),
            ("openalex by_title invented", lambda: openalex.by_title(client, INVENTED_TITLE)),
            ("crossref by_title invented", lambda: crossref.by_title(client, INVENTED_TITLE)),
            ("arxiv by_title invented", lambda: arxiv.by_title(client, INVENTED_TITLE)),
            ("openalex search bm25", lambda: openalex.search(client, "BM25 ranking function", 5)),
            ("crossref search bm25", lambda: crossref.search(client, "BM25 ranking function", 5)),
            ("arxiv search bm25", lambda: arxiv.search(client, "BM25 ranking function", 5)),
        ]

        for label, call in plan:
            try:
                result = call()
            except Exception as error:
                # A source refusing to answer is worth recording as a fact about
                # the run, not a reason to abandon the other fourteen.
                print(f"  {label}: unavailable, {type(error).__name__}: {error}")
                continue
            count = len(result) if isinstance(result, list) else (1 if result else 0)
            print(f"  {label}: {count} record(s)")

        print(f"\n{client.requests_made} request(s) made.")

    print(f"{len(cache.entries())} fixture(s) in {FIXTURE_CACHE}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh", action="store_true", help="re-fetch entries that are already recorded"
    )
    return record(parser.parse_args().refresh)


if __name__ == "__main__":
    raise SystemExit(main())
