"""Collapsing four sources' results into one ranked list.

The same paper routinely appears four times: as an arXiv preprint, as a
Crossref DOI record, as an OpenAlex work, and as a Semantic Scholar entry, each
with a different subset of the metadata. Presenting those as four candidates
would make every verdict look ambiguous when it is not.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace

from research_better.sources.base import Work, normalize_title

WORD = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    """
    a an the and or of in on at to for with by from as is are was were be this that
    """.split()
)


@dataclass(frozen=True, slots=True)
class RankingWeights:
    """How the ranking blends its three signals.

    Defaults chosen so relevance dominates and the other two break ties.
    Citation count is deliberately damped by a logarithm: a paper with 3,000
    citations is more established than one with 300, but it is not ten times
    more likely to be the work being cited, and without damping every query
    would return the field's most famous paper.
    """

    relevance: float = 1.0
    citations: float = 0.15
    recency: float = 0.10
    recency_half_life_years: float = 12.0

    def score(self, work: Work, current_year: int) -> float:
        citation_signal = math.log1p(max(0, work.citation_count)) / math.log1p(10_000)
        if work.year:
            age = max(0, current_year - work.year)
            recency_signal = 0.5 ** (age / self.recency_half_life_years)
        else:
            recency_signal = 0.0
        return (
            self.relevance * work.relevance
            + self.citations * citation_signal
            + self.recency * recency_signal
        )


DEFAULT_WEIGHTS = RankingWeights()


def tokens(text: str) -> set[str]:
    return {word for word in WORD.findall(text.lower()) if word not in STOPWORDS}


def text_relevance(query: str, work: Work) -> float:
    """Share of the query's content words the record actually contains.

    Lexical, not semantic. There is no embedding model here, and pretending
    otherwise would be worse than saying so: this scores word overlap against
    the title and abstract, and a paraphrased query scores lower than it
    deserves. Title matches count double, because a query that matches a title
    is usually looking for that paper.
    """
    wanted = tokens(query)
    if not wanted:
        return 0.0
    title_words = tokens(work.title)
    abstract_words = tokens(work.abstract or "")
    hits = len(wanted & title_words) * 2 + len(wanted & (abstract_words - title_words))
    return min(1.0, hits / (2 * len(wanted)))


def _identity_keys(work: Work) -> list[str]:
    """Every handle that identifies this work, most reliable first."""
    keys: list[str] = []
    if work.doi:
        keys.append(f"doi:{work.doi}")
    if work.arxiv_id:
        keys.append(f"arxiv:{work.arxiv_id}")
    title = normalize_title(work.title)
    if title:
        # Year is not in this key on purpose. A preprint and its published
        # version differ by a year or two and are the same work, and that is
        # exactly the collapse this exists to perform.
        keys.append(f"title:{title}|{work.first_author_surname}")
    return keys


def deduplicate(works: list[Work]) -> list[Work]:
    """Collapse records that describe the same work, keeping every identifier.

    Matching runs DOI first, then arXiv id, then normalized title plus first
    author surname. Records are merged rather than one being discarded, because
    each source knows something the others do not.
    """
    merged: list[Work] = []
    index: dict[str, int] = {}

    for work in works:
        keys = _identity_keys(work)
        position = next((index[key] for key in keys if key in index), None)

        if position is None:
            merged.append(work)
            position = len(merged) - 1
        else:
            merged[position] = merged[position].merged_with(work)

        # Re-key against the merged record, so a work that arrived with only a
        # title later becomes findable by the DOI a second source supplied.
        for key in _identity_keys(merged[position]):
            index[key] = position

    return merged


def rank(
    works: list[Work],
    query: str,
    current_year: int,
    weights: RankingWeights = DEFAULT_WEIGHTS,
) -> list[Work]:
    scored = [replace(work, relevance=text_relevance(query, work)) for work in works]
    return sorted(
        scored,
        key=lambda work: (-weights.score(work, current_year), work.normalized_title),
    )
