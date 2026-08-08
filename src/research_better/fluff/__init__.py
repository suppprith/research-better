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

from pathlib import Path

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


__all__ = ["NAME", "analyse", "analyse_lexical", "analyse_structural"]
