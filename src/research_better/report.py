"""One page an author actually reads.

If it needs scrolling it is not doing its job, so this is a summary and not an
index. Every individual finding already lives in the artifact that produced it.
What belongs here is the shape of the paper's problems and, above all, the
contribution claim the tool read, stated first so a wrong reading is caught
before the author spends any time on the rest.

The last section is the one that makes this an honest report rather than a
reassuring one. Every pass that did not run, every source that could not be
reached, every rule that is switched off, and every part of the bibliography
that could not be retrieved is named. Silence about a check that did not happen
reads as a check that found nothing, which is the same false assurance as
printing a plagiarism score, and this tool does not get to give either.

Counts throughout, never percentages. "18 of 24 entries resolved" is a fact.
The same thing as a percentage invites being read as a grade for the paper.
"""

from __future__ import annotations

import html
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_better.artifacts import Artifact, ArtifactStore
from research_better.errors import ResearchBetterError
from research_better.model import Document
from research_better.thresholds import load_thresholds

NAME = "report"

CONFIG_FILE = ".research-better.toml"

REGENERATE = {
    "paper": "ingest",
    "novelty": "novelty --confirm-claim",
    "grounding": "ground",
    "originality": "originality",
    "fluff": "fluff",
    "voice": "voice",
    "reviewer-questions": "ask",
    "edits": "edit",
    "trace": "trace",
}
"""Artifact to the command that produces it. A gap the report names is only
useful with the command that fills it."""


class CheckError(ResearchBetterError):
    """The configured thresholds could not be read."""


@dataclass(frozen=True, slots=True)
class CheckThresholds:
    """What a lab or a course is willing to let through.

    Zero across the board by default, which sounds strict and is not: a
    threshold is only reached by a problem the tool could actually see, and the
    report says in the same breath how much it could not see.
    """

    max_unverified_citations: int = 0
    max_unsupported_claims: int = 0
    max_blocking_questions: int = 0
    source: str = "defaults"

    @classmethod
    def load(cls, draft: Path) -> CheckThresholds:
        """From `.research-better.toml` or `pyproject.toml`, nearest first."""
        for directory in [draft.parent.resolve(), *draft.parent.resolve().parents]:
            local = directory / CONFIG_FILE
            if local.is_file():
                return cls._from(_read_toml(local), str(local))

            project = directory / "pyproject.toml"
            if project.is_file():
                table = _read_toml(project).get("tool", {}).get("research-better", {})
                if "check" in table:
                    return cls._from(table["check"], f"{project} [tool.research-better.check]")
        return cls()

    @classmethod
    def _from(cls, table: dict[str, Any], source: str) -> CheckThresholds:
        known = {field_name for field_name in cls.__slots__ if field_name != "source"}
        unknown = sorted(set(table) - known)
        if unknown:
            raise CheckError(
                f"{source} sets {', '.join(unknown)}, which this version does not "
                f"understand. Known settings: {', '.join(sorted(known))}."
            )
        return cls(**{key: int(value) for key, value in table.items()}, source=source)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as error:
        raise CheckError(f"{path} could not be read: {error}") from None


# Reading the artifacts -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Report:
    draft: str
    claim: str | None = None
    claim_confirmed: bool = False

    words_before: int = 0
    words_after: int | None = None

    citations: dict[str, int] = field(default_factory=dict)
    citations_with_full_text: tuple[int, int] = (0, 0)
    claims: dict[str, int] = field(default_factory=dict)

    cuts: dict[str, int] = field(default_factory=dict)
    cuts_refused: int = 0

    questions: dict[str, int] = field(default_factory=dict)
    blocking: tuple[str, ...] = ()

    trace_flagged: tuple[tuple[str, str], ...] = ()
    """(where, causes) for each passage the trace audit flagged. Named rather
    than counted alone, because the cause is the whole output: a count of
    passages with no causes beside it is a score in disguise."""

    trace_left_alone: int = 0

    gaps: tuple[str, ...] = ()

    @property
    def unverified_citations(self) -> int:
        return sum(count for verdict, count in self.citations.items() if verdict != "VERIFIED")

    @property
    def unsupported_claims(self) -> int:
        return self.claims.get("UNSUPPORTED", 0)

    @property
    def blocking_questions(self) -> int:
        return self.questions.get("blocking", 0)

    def breaches(self, thresholds: CheckThresholds) -> list[str]:
        """Every configured limit this paper is over, said as a count."""
        found = []
        for label, actual, allowed in (
            (
                "unverified citations",
                self.unverified_citations,
                thresholds.max_unverified_citations,
            ),
            ("unsupported claims", self.unsupported_claims, thresholds.max_unsupported_claims),
            ("blocking questions", self.blocking_questions, thresholds.max_blocking_questions),
        ):
            if actual > allowed:
                found.append(f"{actual} {label}, limit {allowed}")
        return found

    def to_json(self) -> dict[str, Any]:
        return {
            "draft": self.draft,
            "claim": self.claim,
            "claim_confirmed": self.claim_confirmed,
            "length": {
                "words_before": self.words_before,
                "words_after": self.words_after,
                "net": (None if self.words_after is None else self.words_after - self.words_before),
            },
            "citations": dict(self.citations),
            "citations_with_full_text": list(self.citations_with_full_text),
            "claims": dict(self.claims),
            "cuts": dict(self.cuts),
            "cuts_refused": self.cuts_refused,
            "questions": dict(self.questions),
            "blocking": list(self.blocking),
            "trace": {
                "flagged": [list(row) for row in self.trace_flagged],
                "left_alone": self.trace_left_alone,
            },
            "not_checked": list(self.gaps),
        }


def _counts(rows: Any, key: str) -> dict[str, int]:
    tally: dict[str, int] = {}
    for row in rows or ():
        tally[str(row.get(key))] = tally.get(str(row.get(key)), 0) + 1
    return dict(sorted(tally.items()))


def build(document: Document, store: ArtifactStore) -> Report:
    """Read whatever is on disk and say plainly what is missing.

    No evidence gate here, on purpose. The edit pass refuses without complete
    evidence because it writes. This one reports, and a report of a partial run
    that names its own gaps is worth more to an author than a refusal.
    """
    source_hash = document.source_hash
    gaps: list[str] = []

    def read(name: str) -> Any:
        artifact: Artifact | None = store.read(name)
        if artifact is None:
            gaps.append(
                f"The {name} pass has not run. "
                f"Run: research-better {REGENERATE[name]} {store.draft.name}"
            )
            return None
        if artifact.is_stale(source_hash):
            gaps.append(
                f"{name}.json describes an older version of {store.draft.name} and was "
                f"not read. Run: research-better {REGENERATE[name]} {store.draft.name}"
            )
            return None
        if artifact.offline:
            gaps.append(
                f"The {name} pass ran offline, so it checked against what was cached "
                f"rather than against the live literature."
            )
        return artifact.payload

    paper = read("paper") or {}
    novelty = read("novelty") or {}
    grounding = read("grounding") or {}
    fluff = read("fluff") or []
    questions = read("reviewer-questions") or {}
    originality = read("originality") or {}
    edits = read("edits") or {}
    trace = read("trace") or {}

    citations = grounding.get("citations") or {}
    claims = grounding.get("claims") or {}

    if extraction := (paper.get("metadata") or {}).get("extraction_notes"):
        # A format the tool had to guess its way through says so. Silence about
        # a doubtful extraction reads as a confident one.
        gaps.append(f"Reading this format was not exact. {extraction}")

    if not novelty.get("claim"):
        gaps.append(
            "No contribution claim was identified, so nothing below was measured against one."
        )
    elif not novelty.get("claim_confirmed"):
        gaps.append(
            "The contribution claim has not been confirmed. Everything measured "
            "against it inherits that doubt."
        )

    if note := claims.get("coverage_note"):
        gaps.append(note)
    if unavailable := citations.get("sources_unavailable"):
        gaps.append(
            f"Could not reach {', '.join(sorted(unavailable))}, so a missing record "
            f"means less than usual."
        )
    if originality:
        gaps.append(
            f"Overlap was compared against {originality.get('sources_compared', 0)} "
            f"source(s); {originality.get('sources_unavailable', 0)} could not be "
            f"retrieved. This is not a plagiarism check and does not cover anything "
            f"the tool cannot read."
        )
    for rule in load_thresholds().disabled_for_want_of_a_corpus:
        gaps.append(f"The {rule} rule is switched off until it has been calibrated.")

    mechanical = sum(
        1
        for finding in fluff
        if not finding.get("advisory")
        and finding.get("severity") == "high"
        and finding.get("suggestion") in {"delete", "delete_clause"}
    )

    return Report(
        draft=store.draft.name,
        claim=novelty.get("claim"),
        claim_confirmed=bool(novelty.get("claim_confirmed")),
        words_before=document.word_count,
        words_after=(edits.get("budget") or {}).get("edited_words"),
        citations=_counts(citations.get("checks"), "verdict"),
        citations_with_full_text=(
            int(claims.get("sources_with_full_text", 0)),
            int(claims.get("sources_attempted", 0)),
        ),
        claims=_counts(claims.get("checks"), "support"),
        cuts={
            "mechanical fluff": mechanical,
            "orphan paragraphs": len(novelty.get("orphans") or ()),
            "proposed": len(edits.get("edits") or ()),
        },
        cuts_refused=len(edits.get("dropped") or ()),
        trace_flagged=tuple(
            (
                str(row.get("where")),
                " + ".join(
                    str(signal.get("id")).replace("_", " ") for signal in row.get("signals") or ()
                ),
            )
            for row in trace.get("flagged") or ()
        ),
        trace_left_alone=len(trace.get("left_alone") or ()),
        questions=dict(questions.get("counts") or {}),
        blocking=tuple(
            question["question"]
            for question in questions.get("questions") or ()
            if question.get("severity") == "blocking"
        ),
        gaps=tuple(gaps),
    )


# Rendering -----------------------------------------------------------------


def _tally(counts: dict[str, int]) -> str:
    """Counts and their labels, in English. Never a percentage.

    "18 of 24 entries resolved" is a fact. The same thing as a share invites
    being read as a grade for the bibliography, and this tool does not grade.
    """
    named = ", ".join(
        f"{count} {label.lower().replace('_', ' ')}" for label, count in counts.items() if count
    )
    return named or "none"


def to_markdown(report: Report, thresholds: CheckThresholds | None = None) -> str:
    lines = [f"# {report.draft}", ""]

    if report.claim:
        confirmed = "" if report.claim_confirmed else " *(not confirmed)*"
        lines += [f"**The paper claims{confirmed}:** {report.claim}", ""]
    else:
        lines += ["**No contribution claim could be found.**", ""]

    net = "" if report.words_after is None else f", {report.words_after - report.words_before:+d}"
    after = "" if report.words_after is None else f" to {report.words_after}"
    lines += [f"**Length.** {report.words_before} words of prose{after}{net}.", ""]

    resolved, attempted = report.citations_with_full_text
    lines += [
        f"**Citations.** {sum(report.citations.values())} entries: "
        f"{_tally(report.citations)}. {resolved} of {attempted} cited works had "
        f"retrievable full text.",
        "",
        f"**Claims.** {sum(report.claims.values())} cited claims: {_tally(report.claims)}.",
        "",
        f"**Cuts.** {_tally(report.cuts)}. {report.cuts_refused} refused or displaced.",
        "",
        f"**Reviewer questions.** {_tally(report.questions)}.",
        "",
    ]

    for question in report.blocking:
        lines.append(f"- {question}")
    if report.blocking:
        lines.append("")

    # Causes beside the count, always. A count on its own is a score in
    # disguise, and a score is the thing an author starts writing towards.
    lines += [
        f"**May read as machine-written.** {len(report.trace_flagged)} passage(s), "
        f"{report.trace_left_alone} looked at and left alone as likely false positives.",
        "",
    ]
    for where, causes in report.trace_flagged:
        lines.append(f"- {where}: {causes}")
    if report.trace_flagged:
        lines.append("")

    lines += ["## Not checked", ""]
    lines += [f"- {gap}" for gap in report.gaps] or ["- Nothing was skipped."]
    lines.append("")

    if thresholds is not None:
        breaches = report.breaches(thresholds)
        lines += [
            "## Check",
            "",
            ("- " + "\n- ".join(breaches) if breaches else "- Within every configured threshold."),
            f"- Thresholds from {thresholds.source}.",
            "",
        ]

    return "\n".join(lines)


HTML_STYLE = """
body { max-width: 44rem; margin: 2rem auto; padding: 0 1rem;
  font: 16px/1.5 system-ui, sans-serif; color: #1a1a1a; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 1.6rem; }
li { margin: .2rem 0; } .quiet { color: #555; }
"""


def to_html(report: Report, thresholds: CheckThresholds | None = None) -> str:
    """One self-contained file, for sending to a coauthor.

    Built from the report rather than from the markdown, and with no external
    stylesheet or script, so it opens the same way in a mail client as it does
    in a browser.
    """

    def escape(text: str) -> str:
        return html.escape(text, quote=False)

    body = [f"<h1>{escape(report.draft)}</h1>"]
    claim = (
        f"<p><strong>The paper claims"
        f"{'' if report.claim_confirmed else ' (not confirmed)'}:</strong> "
        f"{escape(report.claim)}</p>"
        if report.claim
        else "<p><strong>No contribution claim could be found.</strong></p>"
    )
    body.append(claim)

    after = "" if report.words_after is None else f" to {report.words_after}"
    resolved, attempted = report.citations_with_full_text
    body += [
        f"<p><strong>Length.</strong> {report.words_before} words of prose{after}.</p>",
        f"<p><strong>Citations.</strong> {sum(report.citations.values())} entries: "
        f"{escape(_tally(report.citations))}. {resolved} of {attempted} cited works had "
        f"retrievable full text.</p>",
        f"<p><strong>Claims.</strong> {sum(report.claims.values())} cited claims: "
        f"{escape(_tally(report.claims))}.</p>",
        f"<p><strong>Cuts.</strong> {escape(_tally(report.cuts))}. "
        f"{report.cuts_refused} refused or displaced.</p>",
        f"<p><strong>Reviewer questions.</strong> {escape(_tally(report.questions))}.</p>",
    ]
    if report.blocking:
        body.append(
            "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in report.blocking) + "</ul>"
        )

    body.append(
        f"<p><strong>May read as machine-written.</strong> "
        f"{len(report.trace_flagged)} passage(s), {report.trace_left_alone} looked at "
        f"and left alone as likely false positives.</p>"
    )
    if report.trace_flagged:
        body.append(
            "<ul>"
            + "".join(
                f"<li>{escape(where)}: {escape(causes)}</li>"
                for where, causes in report.trace_flagged
            )
            + "</ul>"
        )

    body += [
        "<h2>Not checked</h2>",
        "<ul class='quiet'>"
        + "".join(f"<li>{escape(gap)}</li>" for gap in report.gaps or ["Nothing was skipped."])
        + "</ul>",
    ]

    if thresholds is not None:
        breaches = report.breaches(thresholds) or ["Within every configured threshold."]
        body += [
            "<h2>Check</h2>",
            "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in breaches) + "</ul>",
        ]

    return (
        "<!doctype html>\n<html lang='en'><head><meta charset='utf-8'>"
        f"<title>{escape(report.draft)}</title><style>{HTML_STYLE}</style></head>"
        "<body>" + "".join(body) + "</body></html>\n"
    )
