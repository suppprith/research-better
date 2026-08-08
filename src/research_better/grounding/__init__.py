"""Checking the paper's citations against the actual literature.

The highest-value thing this tool does, and the one no mainstream writing
assistant offers. It resolves every bibliography entry to a real record, or
reports honestly that it could not.

The constraint that governs the whole package: absence of a record is never
reported as fabrication. Every verdict says which sources were queried and how
close the match was, so the author can disagree with it.
"""

from __future__ import annotations

from research_better.findings import Finding, Severity, Suggestion, sort_findings
from research_better.grounding.entries import BibliographyEntry, bibliography, parse_entry
from research_better.grounding.verify import (
    AUTHOR_OVERLAP,
    TITLE_RELATED,
    TITLE_SAME,
    CitationCheck,
    GroundingReport,
    Verdict,
    title_similarity,
    verify_bibliography,
    verify_entry,
)
from research_better.model import Document
from research_better.net import PoliteClient

NAME = "grounding"

SEVERITY_BY_NAME = {
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
}


def analyse(
    document: Document,
    client: PoliteClient,
    adapters: list | None = None,
) -> GroundingReport:
    return verify_bibliography(client, bibliography(document.citations), adapters)


def to_findings(document: Document, report: GroundingReport) -> list[Finding]:
    """Turn verdicts into findings, anchored where the entry sits in the paper.

    Every one is `REVIEW`. A wrong citation is fixed by working out what the
    author meant to cite, which is not something a tool gets to decide, and no
    deletion is safe: removing a bad reference leaves the claim it supported
    standing with nothing behind it.
    """
    by_key = {citation.key: citation for citation in document.citations if citation.in_bibliography}
    findings: list[Finding] = []

    for check in report.problems:
        citation = by_key.get(check.key)
        if citation is None:
            continue
        findings.append(
            Finding(
                span_id=citation.id,
                rule=f"citation_{str(check.verdict).lower()}",
                severity=SEVERITY_BY_NAME.get(check.severity, Severity.LOW),
                matched_text=(check.entry_title or check.raw)[:200],
                char_range=(citation.span.char_start, citation.span.char_end),
                suggestion=Suggestion.REVIEW,
                note=check.note,
                advisory=check.verdict is Verdict.NOT_FOUND and check.likely_unindexed,
            )
        )
    return sort_findings(findings)


__all__ = [
    "AUTHOR_OVERLAP",
    "NAME",
    "TITLE_RELATED",
    "TITLE_SAME",
    "BibliographyEntry",
    "CitationCheck",
    "GroundingReport",
    "Verdict",
    "analyse",
    "bibliography",
    "parse_entry",
    "title_similarity",
    "to_findings",
    "verify_bibliography",
    "verify_entry",
]
