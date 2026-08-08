"""The fluff pass: text that does not serve the paper's argument.

Two halves with different standing, and the difference is not cosmetic.

The lexical half is dictionary driven and deterministic. A finding says a
specific phrase is filler, and you can disagree by arguing about the lexicon.
Its high-severity findings are mechanical deletions and can be applied.

The structural half reads distributions. It says a paragraph's rhythm looks
uniform, or a section repeats a template. Those correlate with generated text
and do not prove it, so every structural finding is advisory and none is ever
auto-applied, whatever its severity.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_better.findings import Finding, sort_findings
from research_better.fluff.lexical import analyse_lexical
from research_better.fluff.structural import analyse_structural
from research_better.model import Document

NAME = "fluff"


def analyse(
    document: Document,
    lexicon_file: Path | None = None,
    thresholds_file: Path | None = None,
) -> list[Finding]:
    return sort_findings(
        analyse_lexical(document, lexicon_file)
        + analyse_structural(document, lexicon_file, thresholds_file)
    )


@dataclass(frozen=True, slots=True)
class FluffReport:
    """What the pass found, with the two halves kept apart.

    The split is the whole reason this is a type rather than a list. A caller
    who treats an advisory rhythm observation like a deletable filler phrase
    will apply the first one, and that is the mistake worth making structurally
    impossible to reach by accident.
    """

    findings: tuple[Finding, ...] = ()

    @property
    def mechanical(self) -> tuple[Finding, ...]:
        """Findings a deletion fixes, which the edit pass may apply unasked."""
        return tuple(finding for finding in self.findings if finding.auto_actionable)

    @property
    def advisory(self) -> tuple[Finding, ...]:
        """Findings resting on a correlation. Show them, never act on them."""
        return tuple(finding for finding in self.findings if finding.advisory)

    def __len__(self) -> int:
        return len(self.findings)

    def __iter__(self) -> Iterator[Finding]:
        return iter(self.findings)

    def to_json(self) -> list[dict[str, Any]]:
        return [finding.to_json() for finding in self.findings]


def report(
    document: Document,
    lexicon_file: Path | None = None,
    thresholds_file: Path | None = None,
) -> FluffReport:
    """The same analysis as `analyse`, as the typed result the API returns."""
    return FluffReport(tuple(analyse(document, lexicon_file, thresholds_file)))


__all__ = [
    "NAME",
    "FluffReport",
    "analyse",
    "analyse_lexical",
    "analyse_structural",
    "report",
]
