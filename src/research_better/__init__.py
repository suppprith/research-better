"""Check a research paper instead of rewriting it.

`Paper` is the public API. Everything re-exported here is covered by semantic
versioning from the first release; everything reached by importing a submodule
is internal and may move. See `docs/API.md` for the line between them, and
`research_better.cli` for the command line.

    from research_better import Paper

    paper = Paper.load("draft.md")
    for finding in paper.fluff().mechanical:
        print(finding.rule, finding.matched_text)
"""

__version__ = "0.1.0"

from research_better.api import Paper
from research_better.errors import (
    IngestError,
    MissingExtraError,
    ProtectedRangeError,
    ResearchBetterError,
    UnsupportedFormatError,
)
from research_better.findings import Finding, Severity, Suggestion
from research_better.fluff import FluffReport
from research_better.grounding import (
    ClaimReport,
    GroundingReport,
    OriginalityReport,
    Overlap,
    Verdict,
)
from research_better.grounding.claims import ClaimCheck, Support
from research_better.grounding.verify import CitationCheck
from research_better.model import Citation, Document, Paragraph, Section, Sentence, Span
from research_better.net import HttpCache, PoliteClient
from research_better.novelty import NoClaimFoundError, NoveltyReport
from research_better.report import Report
from research_better.reviewer import ReviewerReport
from research_better.trace import Passage, Signal, Standing, TraceReport
from research_better.voice import VoiceProfile, VoiceReport

__all__ = [
    "Citation",
    "CitationCheck",
    "ClaimCheck",
    "ClaimReport",
    "Document",
    "Finding",
    "FluffReport",
    "GroundingReport",
    "HttpCache",
    "IngestError",
    "MissingExtraError",
    "NoClaimFoundError",
    "NoveltyReport",
    "OriginalityReport",
    "Overlap",
    "Paper",
    "Paragraph",
    "Passage",
    "PoliteClient",
    "ProtectedRangeError",
    "Report",
    "ResearchBetterError",
    "ReviewerReport",
    "Section",
    "Sentence",
    "Severity",
    "Signal",
    "Span",
    "Standing",
    "Suggestion",
    "Support",
    "TraceReport",
    "UnsupportedFormatError",
    "Verdict",
    "VoiceProfile",
    "VoiceReport",
    "__version__",
]
