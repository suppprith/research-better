"""Checking the paper's citations against the actual literature.

The highest-value thing this tool does, and the one no mainstream writing
assistant offers. It resolves every bibliography entry to a real record, or
reports honestly that it could not.

The constraint that governs the whole package: absence of a record is never
reported as fabrication. Every verdict says which sources were queried and how
close the match was, so the author can disagree with it.
"""

from __future__ import annotations

from dataclasses import replace

from research_better.findings import Finding, Severity, Suggestion, sort_findings
from research_better.grounding.claims import (
    ClaimCheck,
    ClaimReport,
    Support,
    check_claim,
    claims_with_citations,
)
from research_better.grounding.entries import BibliographyEntry, bibliography, parse_entry
from research_better.grounding.fulltext import SourceText, retrieve
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
from research_better.sources import find_by_doi, find_by_title

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


def check_claims(
    document: Document,
    client: PoliteClient,
    adapters: list | None = None,
) -> ClaimReport:
    """Check every cited claim against what the cited work actually says.

    Sources are resolved once and reused across the claims that cite them,
    because retrieving a full text is by far the expensive part and a paper
    cites the same work several times.
    """
    pairs = claims_with_citations(document)
    entries = {entry.key: entry for entry in bibliography(document.citations)}

    texts: dict[str, SourceText] = {}
    notes: dict[str, str] = {}
    checks: list[ClaimCheck] = []

    for sentence, key in pairs:
        if key not in texts:
            texts[key] = _source_for(client, entries.get(key), key, adapters)
            notes[key] = texts[key].note
        checks.append(check_claim(sentence, key, texts[key]))

    return ClaimReport(
        checks=tuple(checks),
        sources_with_full_text=sum(1 for text in texts.values() if text.is_full_text),
        sources_attempted=len(texts),
        source_notes=notes,
    )


def _source_for(
    client: PoliteClient,
    entry: BibliographyEntry | None,
    key: str,
    adapters: list | None,
) -> SourceText:
    if entry is None:
        return SourceText(
            "none", "", None, f"[{key}] is cited in the text but not in the bibliography."
        )
    result = (
        find_by_doi(client, entry.doi, adapters=adapters)
        if entry.doi
        else find_by_title(client, entry.title or "", adapters=adapters)
    )
    if not result.works:
        return SourceText("none", "", None, "The cited work could not be resolved to a record.")
    return retrieve(client, result.works[0])


SUPPORT_SEVERITY = {
    Support.UNSUPPORTED: Severity.HIGH,
    Support.PARTIAL: Severity.MEDIUM,
    # Not a finding about the paper at all, but worth surfacing so the author
    # knows how much of their bibliography was actually inspected.
    Support.UNCHECKABLE: Severity.LOW,
}


def claim_findings(report: ClaimReport) -> list[Finding]:
    """Findings for claims the cited work does not carry.

    `UNCHECKABLE` is included at low severity and marked advisory, because it
    describes the retrieval and not the writing. Leaving it out entirely would
    let an author read silence as confirmation.
    """
    findings: list[Finding] = []
    for check in report.checks:
        if check.support is Support.SUPPORTED:
            continue
        quoted = f' The source says: "{check.quote}" ({check.locator}).' if check.quote else ""
        findings.append(
            Finding(
                span_id=check.span_id,
                rule=f"claim_{str(check.support).lower()}",
                severity=SUPPORT_SEVERITY[check.support],
                matched_text=check.claim[:200],
                char_range=(0, 0),
                suggestion=Suggestion.REVIEW,
                note=check.note + quoted,
                advisory=check.support is Support.UNCHECKABLE,
            )
        )
    return findings


def to_findings(
    document: Document,
    report: GroundingReport,
    claims: ClaimReport | None = None,
) -> list[Finding]:
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

    if claims is not None:
        anchored: list[Finding] = []
        by_span = {sentence.id: sentence for sentence in document.sentences}
        for finding in claim_findings(claims):
            sentence = by_span.get(finding.span_id)
            if sentence is None:
                continue
            anchored.append(
                replace(
                    finding,
                    char_range=(sentence.span.char_start, sentence.span.char_end),
                )
            )
        findings.extend(anchored)

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
