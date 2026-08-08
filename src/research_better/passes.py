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

from research_better import edit as edit_layer
from research_better import fluff, grounding, novelty, reviewer, trace, voice
from research_better import report as reporting
from research_better.artifacts import ArtifactStore
from research_better.findings import Finding, Severity, Suggestion
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
    venue: str | None = None
    claim_confirmed: bool = False
    """Set once the author has confirmed the extracted contribution claim. If
    the claim is wrong every cut downstream is wrong, so nothing acts on an
    unconfirmed one."""

    store: ArtifactStore | None = None
    """Only the edit pass reads it. Every other pass writes its artifact and
    never looks at anybody else's, which is what keeps a change to one pass from
    breaking another."""

    interactive: bool = False

    target_reduction: float = 0.0
    """How much shorter the author wants the paper. A target the run reports
    against, never a quota it fills: the ceiling on growing the paper is
    enforced, and falling short of a reduction is a fact about the draft."""

    apply: bool = False
    force: bool = False

    check: bool = False
    """Turn the report into a verdict against the configured thresholds.
    Reading a report should not fail a build; asking it to gate one should."""

    html: bool = False

    def require_client(self, pass_name: str) -> PoliteClient:
        if self.client is None:
            raise RuntimeError(f"the {pass_name} pass needs an HTTP client and was given none")
        return self.client

    def require_store(self, pass_name: str) -> ArtifactStore:
        if self.store is None:
            raise RuntimeError(f"the {pass_name} pass needs an artifact store and was given none")
        return self.store


@dataclass(frozen=True, slots=True)
class PassResult:
    payload: Any
    findings: tuple[Finding, ...] = ()
    summary: str = ""
    markdown: str | None = None
    """Set when the pass has a human-readable form worth writing beside the
    JSON. Reviewer questions are meant to be read, not parsed."""

    attachments: tuple[tuple[str, str], ...] = ()
    """(suffix, body) pairs written beside the JSON under the same name. A patch
    belongs in a `.diff` file that `git apply` and every editor already
    understand, not wrapped in a JSON string."""

    counts_as_finding: bool = False
    """Set by a pass that reports something worth a non-zero exit without
    emitting `Finding` objects. The edit pass proposes changes rather than
    findings, and a proposed change is still something a CI check should see."""

    stdout: str | None = None
    """Printed after the summary line. Only the report sets it, because only
    the report is meant to be read rather than filed: a page that lands in
    `.research-better/` and is never opened is not a page an author reads."""


@dataclass(frozen=True, slots=True)
class Pass:
    name: str
    artifact: str
    help: str
    implemented: bool
    phase: str
    run: Callable[[PassContext], PassResult] | None = None
    needs_network: bool = False
    preflight: Callable[[PassContext, ArtifactStore], None] | None = None
    """A precondition checked before the pass runs, and before the refusal a
    pass that is not built yet would raise.

    It exists for the evidence gate. A pass that writes to the paper has to
    prove it read the analysis first, and that proof is a property of the run
    rather than of the pass body, so it sits here where it cannot be skipped by
    a future rewrite of the pass itself."""


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


def _novelty(context: PassContext) -> PassResult:
    try:
        report = novelty.analyse(context.document, confirmed=context.claim_confirmed)
    except novelty.NoClaimFoundError as error:
        # Not a tool failure. It is a finding about the paper, and the most
        # useful one this pass can produce, so it is reported rather than
        # raised through to an exit code 2.
        return PassResult(
            payload={"claim": None, "error": str(error)},
            findings=(
                Finding(
                    span_id="",
                    rule="novelty_no_claim_found",
                    severity=Severity.HIGH,
                    matched_text="",
                    char_range=(0, 0),
                    suggestion=Suggestion.REVIEW,
                    note=str(error),
                ),
            ),
            summary="no contribution claim could be found",
        )

    findings = novelty.to_findings(report)
    unconfirmed = "" if report.claim_confirmed else ", claim not yet confirmed"
    return PassResult(
        payload=report.to_json(),
        findings=tuple(findings),
        summary=(
            f"{len(report.orphans)} orphan paragraph(s), "
            f"{len(report.unsupported_claim_parts)} unsupported part(s) of the claim"
            f"{unconfirmed}"
        ),
    )


def _ask(context: PassContext) -> PassResult:
    try:
        audit: novelty.NoveltyReport | None = novelty.analyse(context.document)
    except novelty.NoClaimFoundError:
        # Without a claim there is no blocking contribution question to ask,
        # but every other check still applies.
        audit = None

    report = reviewer.analyse(context.document, audit, venue=context.venue)
    counts = report.to_json()["counts"]
    return PassResult(
        payload=report.to_json(),
        # Questions are not findings about correctness. They are prompts for
        # work only the author can do, so they do not fail a CI check.
        summary=(
            f"{counts['blocking']} blocking, {counts['serious']} serious, {counts['minor']} minor"
        ),
        markdown=report.to_markdown(),
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


def _edit(context: PassContext) -> PassResult:
    store = context.require_store("edit")
    document = context.document
    bundle = edit_layer.gather(store, document.source_hash)

    # The lock is built from the voice artifact as it was written, for the same
    # reason the gate reads payloads: the constraint has to be the one recorded,
    # not the one the tool would compute if asked again.
    lock = edit_layer.VoiceLock.of(document, bundle.payload("voice"))
    screen = edit_layer.screen(lock)
    budget = edit_layer.Budget.of(document, context.target_reduction)

    decisions = edit_layer.load_decisions(store)
    ledger = edit_layer.build(document, bundle, edit_layer.rejected_ids(decisions), screen)

    if context.interactive:
        decisions = edit_layer.review(ledger, input, print, decisions)
        edit_layer.save_decisions(store, decisions, document.source_hash)
        # Rebuilt rather than filtered, so a row rejected in this session leaves
        # the ledger the same way one rejected last week does.
        ledger = edit_layer.build(document, bundle, edit_layer.rejected_ids(decisions), screen)

    words = budget.check(edit_layer.apply_to(document.source_text, list(ledger.edits)))
    patch = edit_layer.to_diff(document, ledger.edits)

    payload = ledger.to_json()
    payload["budget"] = {
        "original_words": budget.original_words,
        "edited_words": words,
        "target_reduction": budget.target_reduction,
        "note": budget.shortfall(words),
    }

    summary = (
        f"{len(ledger.edits)} edit(s) proposed, {ledger.words_delta:+d} words, "
        f"{len(ledger.dropped)} not proposed"
    )
    if context.apply and ledger.edits:
        written = edit_layer.write_back(
            document,
            list(ledger.edits),
            force=context.force,
            target_reduction=budget.target_reduction,
        )
        payload["written"] = written.to_json()
        # The draft has changed, so every artifact including this one now
        # describes a file that no longer exists. Saying so here is cheaper than
        # the next run's warning, which arrives after the author has moved on.
        summary += (
            f", written to {len(written.files)} file(s), backup at "
            f"{written.backups[0].name}. Rerun the passes: the artifacts now "
            f"describe the draft as it was."
        )

    return PassResult(
        payload=payload,
        summary=summary,
        markdown=edit_layer.to_summary(ledger) + f"\n{budget.shortfall(words)}\n",
        attachments=((".diff", patch),) if patch else (),
        counts_as_finding=bool(ledger.edits),
    )


def _trace(context: PassContext) -> PassResult:
    # The grounding artifact is read rather than recomputed, because claim
    # support is the one signal here that needs the network. Everything else is
    # measured from the document, so this pass works with nothing on disk and
    # says what it could not see instead of quietly narrowing.
    store = context.require_store("trace")
    artifact = store.read("grounding")
    payload = (
        artifact.payload
        if artifact is not None and not artifact.is_stale(context.document.source_hash)
        else None
    )

    report = trace.analyse(context.document, payload)
    return PassResult(
        payload=report.to_json(),
        # Counts and causes. A share here would be read as an AI score whatever
        # it was labelled, and a number on a paragraph is a number to optimize
        # against.
        summary=(
            f"{len(report.flagged)} passage(s) flagged, "
            f"{len(report.left_alone)} looked at and left alone"
        ),
        markdown=trace.to_markdown(report),
        counts_as_finding=bool(report.flagged),
    )


def _report(context: PassContext) -> PassResult:
    store = context.require_store("report")
    thresholds = reporting.CheckThresholds.load(store.draft)
    built = reporting.build(context.document, store)
    breaches = built.breaches(thresholds)

    markdown = reporting.to_markdown(built, thresholds)
    page = reporting.to_html(built, thresholds) if context.html else markdown
    return PassResult(
        payload={
            "report": built.to_json(),
            "check": {
                "thresholds": {
                    "max_unverified_citations": thresholds.max_unverified_citations,
                    "max_unsupported_claims": thresholds.max_unsupported_claims,
                    "max_blocking_questions": thresholds.max_blocking_questions,
                    "source": thresholds.source,
                },
                "breaches": breaches,
            },
        },
        summary=(
            f"{built.unverified_citations} unverified citation(s), "
            f"{built.unsupported_claims} unsupported claim(s), "
            f"{built.blocking_questions} blocking question(s), "
            f"{len(built.gaps)} thing(s) not checked"
        ),
        markdown=markdown,
        attachments=((".html", reporting.to_html(built, thresholds)),),
        # Only --check turns a report into a verdict. Reading one should not
        # fail a build.
        counts_as_finding=bool(breaches) and context.check,
        stdout=page,
    )


def _require_evidence(context: PassContext, store: ArtifactStore) -> None:
    """The evidence gate, checked before the edit pass is allowed to start.

    Deliberately not inside the pass body. A gate a pass calls is a gate a
    rewrite of that pass can forget, and this one is the reason the tool cannot
    write before it has researched.
    """
    edit_layer.gather(store, context.document.source_hash)


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
        implemented=True,
        phase="P4 skill layer",
        run=_novelty,
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
        implemented=True,
        phase="P4 skill layer",
        run=_ask,
    ),
    "edit": Pass(
        name="edit",
        artifact="edits",
        help="turn findings into a patch, applied only with --apply",
        implemented=True,
        phase="P5 surgical edit",
        run=_edit,
        preflight=_require_evidence,
    ),
    "trace": Pass(
        name="trace",
        artifact="trace",
        help="passages that may read as machine-written, with the cause and the fix",
        implemented=True,
        phase="P6 reporting and format coverage",
        run=_trace,
    ),
    "report": Pass(
        name="report",
        artifact="report",
        help="one page of what was found and what could not be checked",
        implemented=True,
        phase="P6 reporting and format coverage",
        run=_report,
    ),
}

RUN_ORDER = (
    "ingest",
    "voice",
    "novelty",
    "ground",
    "originality",
    "fluff",
    "trace",
    "ask",
    "edit",
    "report",
)
"""The order `run` walks. Ingest first because everything reads its output,
voice before any pass that could propose words, and trace after grounding and
fluff because it is a synthesis of what they found."""


def implemented() -> tuple[str, ...]:
    return tuple(name for name, entry in PASSES.items() if entry.implemented)


def not_yet_built() -> tuple[str, ...]:
    return tuple(name for name, entry in PASSES.items() if not entry.implemented)
