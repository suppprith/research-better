"""The pass registry: what the tool can do, and what it cannot do yet.

Every command in the CLI is one entry here. Entries whose pass has not been
built carry `implemented = False` and the phase they belong to, and the command
refuses with that message rather than writing an empty artifact.

That refusal is deliberate. An empty `grounding.json` sitting in the store
looks exactly like a grounding check that found nothing wrong, and this tool
does not get to imply it checked something it did not. The same rule that keeps
it from printing a plagiarism percentage keeps it from writing a hollow
artifact.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from research_better import fluff, grounding, voice
from research_better.findings import Finding
from research_better.model import Document
from research_better.net import PoliteClient
from research_better.serialize import document_to_json


@dataclass(frozen=True, slots=True)
class PassContext:
    """Everything a pass is allowed to reach for.

    The client is optional because most passes are offline by nature. Handing
    one to a pass that does not need it would let a deterministic check quietly
    grow a network dependency.
    """

    document: Document
    client: PoliteClient | None = None
    offline: bool = False
    refresh: bool = False

    def require_client(self, pass_name: str) -> PoliteClient:
        if self.client is None:
            raise RuntimeError(f"the {pass_name} pass needs an HTTP client and was given none")
        return self.client


@dataclass(frozen=True, slots=True)
class PassResult:
    payload: Any
    findings: tuple[Finding, ...] = ()
    summary: str = ""


@dataclass(frozen=True, slots=True)
class Pass:
    name: str
    artifact: str
    help: str
    implemented: bool
    phase: str
    run: Callable[[PassContext], PassResult] | None = None
    needs_network: bool = False


def _ingest(context: PassContext) -> PassResult:
    payload = document_to_json(context.document)
    counts = payload["counts"]
    return PassResult(
        payload=payload,
        summary=(
            f"{counts['sentences']} sentences, {counts['words_of_prose']} words of prose, "
            f"{counts['citations_used']} citations used, "
            f"{counts['citations_in_bibliography']} in the bibliography"
        ),
    )


def _fluff(context: PassContext) -> PassResult:
    findings = fluff.analyse(context.document)
    advisory = sum(1 for finding in findings if finding.advisory)
    actionable = sum(1 for finding in findings if finding.auto_actionable)
    return PassResult(
        payload=[finding.to_json() for finding in findings],
        findings=tuple(findings),
        summary=(f"{len(findings)} findings, {actionable} mechanical, {advisory} advisory"),
    )


def _voice(context: PassContext) -> PassResult:
    report = voice.extract(context.document)
    return PassResult(
        payload=report.to_json(),
        summary=(
            f"{report.whole_paper.word_count} words profiled, "
            f"{len(report.whole_paper.terminology)} terms recorded, "
            f"{len(report.sections)} section profile(s)"
        ),
    )


def _ground(context: PassContext) -> PassResult:
    client = context.require_client("ground")
    report = grounding.analyse(context.document, client)
    claims = grounding.check_claims(context.document, client)
    findings = grounding.to_findings(context.document, report, claims)
    return PassResult(
        payload={"citations": report.to_json(), "claims": claims.to_json()},
        findings=tuple(findings),
        # The summary says what was checked, not how clean the paper is. A
        # count of resolved entries is a fact. A share would read as a score.
        summary=(
            f"{report.verified} of {len(report.checks)} entries resolved, "
            f"{claims.sources_with_full_text} of {claims.sources_attempted} sources "
            f"had full text"
        ),
    )


def _originality(context: PassContext) -> PassResult:
    report = grounding.check_originality(context.document, context.require_client("originality"))
    findings = grounding.originality_findings(report)
    return PassResult(
        payload=report.to_json(),
        findings=tuple(findings),
        # Counts, never a share. A percentage here would be read as a
        # similarity score whatever it was labelled.
        summary=(
            f"{len(report.matches)} overlap(s) against {report.sources_compared} source(s), "
            f"{report.sources_unavailable} not retrievable"
        ),
    )


PASSES: dict[str, Pass] = {
    "ingest": Pass(
        name="ingest",
        artifact="paper",
        help="parse the draft and write its structure",
        implemented=True,
        phase="P1 foundation",
        run=_ingest,
    ),
    "fluff": Pass(
        name="fluff",
        artifact="fluff",
        help="find text that does not serve the paper's argument",
        implemented=True,
        phase="P2 deterministic analysis",
        run=_fluff,
    ),
    "voice": Pass(
        name="voice",
        artifact="voice",
        help="profile how the author writes, so edits can be held to it",
        implemented=True,
        phase="P2 deterministic analysis",
        run=_voice,
    ),
    "novelty": Pass(
        name="novelty",
        artifact="novelty",
        help="check that the body supports the stated contribution",
        implemented=False,
        phase="P4 skill layer",
    ),
    "ground": Pass(
        name="ground",
        artifact="grounding",
        help="verify citations against the literature",
        implemented=True,
        phase="P3 grounding and citation verification",
        run=_ground,
        needs_network=True,
    ),
    "originality": Pass(
        name="originality",
        artifact="originality",
        help="unattributed overlap with work the tool can actually read",
        implemented=True,
        phase="P3 grounding and citation verification",
        run=_originality,
        needs_network=True,
    ),
    "ask": Pass(
        name="ask",
        artifact="reviewer-questions",
        help="raise the questions a reviewer will ask",
        implemented=False,
        phase="P4 skill layer",
    ),
    "edit": Pass(
        name="edit",
        artifact="edits",
        help="turn findings into a patch, applied only with --apply",
        implemented=False,
        phase="P5 surgical edit",
    ),
    "report": Pass(
        name="report",
        artifact="report",
        help="one page of what was found and what could not be checked",
        implemented=False,
        phase="P6 reporting and format coverage",
    ),
}

RUN_ORDER = (
    "ingest",
    "voice",
    "novelty",
    "ground",
    "originality",
    "fluff",
    "ask",
    "edit",
    "report",
)
"""The order `run` walks. Ingest first because everything reads its output, and
voice before any pass that could propose words."""


def implemented() -> tuple[str, ...]:
    return tuple(name for name, entry in PASSES.items() if entry.implemented)


def not_yet_built() -> tuple[str, ...]:
    return tuple(name for name, entry in PASSES.items() if not entry.implemented)
