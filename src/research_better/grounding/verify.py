"""Resolving every bibliography entry against the real record.

The rule that shapes this whole module: `NOT_FOUND` is never reported as
"fabricated". Legitimate references go missing from these databases all the
time. Books, theses, standards documents, older non-English work, and plenty of
workshop papers are simply not indexed, and a tool that called them fabrications
would be wrong often enough to be worth ignoring, which is the worst thing a
checking tool can be.

So every verdict carries what was queried, what answered, and what the match
score was. The tool reports what it saw. The human draws the conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Any

from research_better.grounding.entries import BibliographyEntry
from research_better.net import PoliteClient
from research_better.sources import SearchResult, SourceAdapter, Work, find_by_doi, find_by_title
from research_better.sources.base import normalize_title

TITLE_SAME = 0.85
"""At or above this, two titles are the same work under a different
transcription. Below it and above TITLE_RELATED, they are close enough that
somebody probably meant this record and got the title wrong."""

TITLE_RELATED = 0.60
"""Below this, the candidate is a different paper and not evidence of anything."""

AUTHOR_OVERLAP = 0.5
"""Share of the entry's surnames that must appear in the record. Bibliographies
truncate author lists with "et al." constantly, so requiring all of them would
flag correct citations."""


class Verdict(StrEnum):
    VERIFIED = "VERIFIED"
    TITLE_MISMATCH = "TITLE_MISMATCH"
    AUTHOR_MISMATCH = "AUTHOR_MISMATCH"
    YEAR_MISMATCH = "YEAR_MISMATCH"
    NOT_FOUND = "NOT_FOUND"
    RETRACTED = "RETRACTED"
    PREPRINT_ONLY = "PREPRINT_ONLY"
    UNPARSEABLE = "UNPARSEABLE"


SEVERITY = {
    Verdict.RETRACTED: "high",
    Verdict.TITLE_MISMATCH: "high",
    Verdict.AUTHOR_MISMATCH: "medium",
    # Never high. NOT_FOUND is not proof of anything, and styling it as urgent
    # would train authors to dismiss it.
    Verdict.NOT_FOUND: "medium",
    Verdict.YEAR_MISMATCH: "low",
    Verdict.PREPRINT_ONLY: "low",
    Verdict.UNPARSEABLE: "low",
    Verdict.VERIFIED: "none",
}


def title_similarity(left: str | None, right: str | None) -> float:
    """Ratio of two normalized titles, using difflib's SequenceMatcher.

    Named here rather than hidden, because the threshold means nothing without
    the algorithm. SequenceMatcher on normalized text is forgiving about case,
    punctuation, accents, and a swapped article, and unforgiving about a
    genuinely different title, which is the behaviour wanted.
    """
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio()


def author_overlap(entry: BibliographyEntry, work: Work) -> float:
    wanted = set(entry.surnames)
    if not wanted:
        return 1.0
    from research_better.sources.base import surname

    found = {surname(author) for author in work.authors}
    return len(wanted & found) / len(wanted)


@dataclass(frozen=True, slots=True)
class CitationCheck:
    """One entry, one verdict, and everything needed to argue with it."""

    key: str
    verdict: Verdict
    severity: str
    raw: str
    title_score: float = 0.0
    author_score: float = 0.0
    entry_title: str | None = None
    matched_title: str | None = None
    matched_doi: str | None = None
    matched_year: int | None = None
    entry_year: int | None = None
    retraction_doi: str | None = None
    retraction_date: str | None = None
    sources_queried: tuple[str, ...] = ()
    sources_unavailable: dict[str, str] = field(default_factory=dict)
    likely_unindexed: bool = False
    note: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "verdict": str(self.verdict),
            "severity": self.severity,
            "raw": self.raw,
            "title_score": round(self.title_score, 3),
            "author_score": round(self.author_score, 3),
            "entry_title": self.entry_title,
            "matched_title": self.matched_title,
            "matched_doi": self.matched_doi,
            "matched_year": self.matched_year,
            "entry_year": self.entry_year,
            "retraction_doi": self.retraction_doi,
            "retraction_date": self.retraction_date,
            "sources_queried": list(self.sources_queried),
            "sources_unavailable": dict(self.sources_unavailable),
            "likely_unindexed": self.likely_unindexed,
            "note": self.note,
        }


def _not_found(entry: BibliographyEntry, result: SearchResult) -> CitationCheck:
    if entry.likely_unindexed:
        note = (
            f"No record found. This entry looks like a {entry.kind}, and these are "
            f"routinely absent from OpenAlex, Crossref, and arXiv even when they are "
            f"entirely real. Absence here is not evidence."
        )
    else:
        note = (
            "No record found in the sources queried. That is not proof the work "
            "does not exist. Books, theses, standards, older non-English work, and "
            "some workshop papers are not indexed. Check it yourself before "
            "concluding anything."
        )
    return CitationCheck(
        key=entry.key,
        verdict=Verdict.NOT_FOUND,
        severity=SEVERITY[Verdict.NOT_FOUND],
        raw=entry.raw,
        entry_title=entry.title,
        entry_year=entry.year,
        sources_queried=result.queried,
        sources_unavailable=result.unavailable,
        likely_unindexed=entry.likely_unindexed,
        note=note,
    )


def _judge(entry: BibliographyEntry, work: Work, result: SearchResult) -> CitationCheck:
    title_score = title_similarity(entry.title, work.title)
    authors = author_overlap(entry, work)

    def build(verdict: Verdict, note: str) -> CitationCheck:
        return CitationCheck(
            key=entry.key,
            verdict=verdict,
            severity=SEVERITY[verdict],
            raw=entry.raw,
            title_score=title_score,
            author_score=authors,
            entry_title=entry.title,
            matched_title=work.title,
            matched_doi=work.doi,
            matched_year=work.year,
            entry_year=entry.year,
            retraction_doi=work.retraction_doi,
            retraction_date=work.retraction_date,
            sources_queried=result.queried,
            sources_unavailable=result.unavailable,
            note=note,
        )

    # Retraction outranks everything. Whatever else is wrong with the entry, an
    # author citing a withdrawn paper needs to know that first.
    if work.retracted:
        where = (
            f" See the retraction notice at {work.retraction_doi}." if work.retraction_doi else ""
        )
        return build(
            Verdict.RETRACTED,
            f"This work has been retracted.{where} Citing it may still be correct "
            f"if you are discussing the retraction, but it should not be cited as "
            f"a source of findings.",
        )

    if entry.title and title_score < TITLE_SAME:
        return build(
            Verdict.TITLE_MISMATCH,
            f"The record for this identifier is titled {work.title!r}, which does not "
            f"match the entry (similarity {title_score:.2f} against a {TITLE_SAME} "
            f"threshold). Usually a copy-paste error. Check what you meant to cite.",
        )

    if entry.surnames and authors < AUTHOR_OVERLAP:
        return build(
            Verdict.AUTHOR_MISMATCH,
            f"The title matches but the authors do not. The record lists "
            f"{', '.join(work.authors[:4]) or 'no authors'}.",
        )

    if entry.year and work.year and entry.year != work.year:
        return build(
            Verdict.YEAR_MISMATCH,
            f"The record gives {work.year}, the entry says {entry.year}. Often a "
            f"preprint cited with the published year or the reverse, which most "
            f"venues do not mind.",
        )

    if work.is_preprint_only:
        return build(
            Verdict.PREPRINT_ONLY,
            "Only a preprint version exists. Not a problem in itself, though some "
            "venues ask for the published version where there is one.",
        )

    return build(Verdict.VERIFIED, "Resolves, and the title, authors, and year match.")


def verify_entry(
    client: PoliteClient,
    entry: BibliographyEntry,
    adapters: list[SourceAdapter] | None = None,
) -> CitationCheck:
    """Resolve one entry and judge what came back."""
    if not entry.readable:
        return CitationCheck(
            key=entry.key,
            verdict=Verdict.UNPARSEABLE,
            severity=SEVERITY[Verdict.UNPARSEABLE],
            raw=entry.raw,
            note=(
                "Could not read a title or an identifier out of this entry, so "
                "nothing was queried. This says the entry is malformed, not that "
                "the work is missing."
            ),
        )

    if entry.doi:
        result = find_by_doi(client, entry.doi, adapters=adapters)
        if result.works:
            return _judge(entry, result.works[0], result)
        # A DOI that resolves nowhere is a stronger signal than a title that
        # does not match, but it is still not proof, so it falls through to the
        # same honest NOT_FOUND rather than to an accusation.
        return _not_found(entry, result)

    result = find_by_title(client, entry.title or "", adapters=adapters)
    best: Work | None = None
    best_score = 0.0
    for candidate in result.works:
        score = title_similarity(entry.title, candidate.title)
        if score > best_score:
            best, best_score = candidate, score

    if best is None or best_score < TITLE_RELATED:
        return _not_found(entry, result)

    # Without a DOI, calling something a title mismatch is a claim that this
    # record is the work the author meant, and that claim needs evidence.
    # A partial title match alone is not evidence: "Ranking Under Budget
    # Constraints" scores 0.82 against "Machine learning under budget
    # constraints" and they are unrelated papers. Either the title matches
    # outright or the authors do, otherwise the work was simply not found.
    identified = best_score >= TITLE_SAME or author_overlap(entry, best) >= AUTHOR_OVERLAP
    if not identified:
        return _not_found(entry, result)
    return _judge(entry, best, result)


@dataclass(frozen=True, slots=True)
class GroundingReport:
    checks: tuple[CitationCheck, ...] = ()
    sources_queried: tuple[str, ...] = ()
    sources_unavailable: dict[str, str] = field(default_factory=dict)

    @property
    def verified(self) -> int:
        return sum(1 for check in self.checks if check.verdict is Verdict.VERIFIED)

    @property
    def problems(self) -> tuple[CitationCheck, ...]:
        return tuple(check for check in self.checks if check.verdict is not Verdict.VERIFIED)

    def coverage_note(self) -> str:
        """What was actually checked, always stated.

        A count rather than a percentage. "18 of 24 entries resolved" is a fact.
        A percentage invites being read as a score for the bibliography, and
        this tool does not issue scores.
        """
        total = len(self.checks)
        unreadable = sum(1 for check in self.checks if check.verdict is Verdict.UNPARSEABLE)
        parts = [
            f"{self.verified} of {total} entries resolved and matched",
            f"queried {', '.join(self.sources_queried) or 'no sources'}",
        ]
        if unreadable:
            parts.append(f"{unreadable} entry(s) could not be parsed and were not queried")
        if self.sources_unavailable:
            parts.append(
                "could not reach "
                + ", ".join(sorted(self.sources_unavailable))
                + ", so absence of a record means less than usual"
            )
        return ". ".join(parts) + "."

    def to_json(self) -> dict[str, Any]:
        return {
            "checks": [check.to_json() for check in self.checks],
            "verified": self.verified,
            "total": len(self.checks),
            "sources_queried": list(self.sources_queried),
            "sources_unavailable": dict(self.sources_unavailable),
            "coverage_note": self.coverage_note(),
        }


def verify_bibliography(
    client: PoliteClient,
    entries: list[BibliographyEntry],
    adapters: list[SourceAdapter] | None = None,
) -> GroundingReport:
    checks = [verify_entry(client, entry, adapters) for entry in entries]
    queried: set[str] = set()
    unavailable: dict[str, str] = {}
    for check in checks:
        queried.update(check.sources_queried)
        unavailable.update(check.sources_unavailable)
    return GroundingReport(tuple(checks), tuple(sorted(queried)), unavailable)
