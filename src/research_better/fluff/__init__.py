"""The fluff pass: text that does not serve the paper's argument.

Two halves with different standing. The lexical half is dictionary driven and
deterministic, so a finding is reproducible and arguable. The structural half
reads distributions across paragraphs and is advisory only, because uniformity
correlates with generated text without proving it.
"""

from __future__ import annotations

from research_better.findings import Finding, sort_findings
from research_better.fluff.lexical import analyse_lexical
from research_better.model import Document

NAME = "fluff"


def analyse(document: Document) -> list[Finding]:
    return sort_findings(analyse_lexical(document))


__all__ = ["NAME", "analyse", "analyse_lexical"]
