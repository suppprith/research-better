"""Every change the tool proposes, written down one row at a time.

Nothing here changes a file. A ledger is a list of proposals, each one carrying
the text it would replace, the text it would put there, one line of reason, and
a pointer at the artifact record that justifies it. The author accepts or
rejects them individually. That granularity is the difference between a tool
you can check and a tool you have to trust.

Three properties hold the design together.

**Every row carries evidence.** The pointer is validated against the bundle the
evidence gate assembled before the row is admitted. A row that cannot name the
finding behind it does not get written, which is what stops the tool making a
change it merely felt like making.

**Rows are content addressed.** A row's id is a hash of the span it touches and
the text on both sides of the change, never an offset or a counter. So a
rejected edit stays rejected across runs even after the author has edited
elsewhere in the paper and every offset has moved.

**Rows never overlap.** Two proposals over the same characters would corrupt
the file when both were applied, so overlaps are detected here, at plan time,
and the lower-confidence row is dropped with a note saying which row displaced
it. Application then runs back to front, so an earlier splice cannot invalidate
the offsets of a later one.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from research_better.artifacts import ArtifactStore
from research_better.edit.gate import EvidenceBundle
from research_better.model import Document, Span
from research_better.spans import digest

REASON_LENGTH = 160
"""One line. A change needing a paragraph of justification is a reviewer
question, not an edit, and it belongs in the `ask` pass where the author is not
being invited to accept it with one keystroke."""

FIRST_SENTENCE = re.compile(r"^.*?[.!?](?:\s|$)")
NEXT_WORD = re.compile(r"\s*(\S+)")


class Category(StrEnum):
    CUT = "CUT"
    """Deletion of an orphan paragraph or a high-severity fluff hit."""

    TIGHTEN = "TIGHTEN"
    """The same claim in fewer words, with no new terminology. The replacement
    comes from a fixed lexicon entry, never from generated text."""

    GROUND = "GROUND"
    """Attach a verified citation to an existing claim, or weaken an overclaim
    to what the evidence supports.

    No deterministic rule emits one yet. Weakening a claim is a word choice, and
    a word choice is exactly what this tool hands to the human, so these will
    come from the skill layer under the voice lock rather than from a pattern
    here."""

    FIX = "FIX"
    """A factual or internal-consistency error, such as a number in the text
    that disagrees with the table it describes.

    Also unemitted so far: finding one needs a table-to-prose reconciliation
    pass that does not exist. The category is defined because the ledger format
    is what other tools read, and adding a category later would break them."""


CONFIDENCE = {
    "fluff_deletion": 0.9,
    "fluff_replacement": 0.8,
    # Cutting a whole paragraph is the largest edit this tool can propose, and
    # the one it is least equipped to judge, because it cannot see why the
    # author put it there. Low on purpose, so any contest with another row
    # loses.
    "orphan_paragraph": 0.3,
}


@dataclass(frozen=True, slots=True)
class Edit:
    """One proposed change to one range of the draft."""

    span_id: str
    category: Category
    original: str
    proposed: str
    reason: str
    evidence: str
    confidence: float
    char_range: tuple[int, int]

    @property
    def id(self) -> str:
        """Stable across runs, and independent of every offset in the file.

        Span ids are already content derived, so a sentence the author has not
        touched keeps its id after an edit elsewhere. Hashing the id together
        with both sides of the change means a decision recorded about this
        proposal still applies to this proposal next time, which is what makes
        "do not re-propose what I rejected" possible at all.
        """
        return f"e-{digest(self.span_id, str(self.category), self.original, self.proposed)}"

    @property
    def words_delta(self) -> int:
        return len(self.proposed.split()) - len(self.original.split())

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "span_id": self.span_id,
            "category": str(self.category),
            "original": self.original,
            "proposed": self.proposed,
            "reason": self.reason,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 3),
            "words_delta": self.words_delta,
            "char_range": list(self.char_range),
        }


@dataclass(frozen=True, slots=True)
class Dropped:
    """A proposal that did not make it into the ledger, and why.

    Kept and reported rather than discarded. A tool that silently declines to
    propose something is indistinguishable from a tool that never noticed it.
    """

    edit: Edit
    rule: str
    note: str

    def to_json(self) -> dict[str, Any]:
        return {"edit": self.edit.to_json(), "rule": self.rule, "note": self.note}


@dataclass(frozen=True, slots=True)
class Ledger:
    edits: tuple[Edit, ...] = ()
    dropped: tuple[Dropped, ...] = ()

    def of_category(self, category: Category) -> tuple[Edit, ...]:
        return tuple(edit for edit in self.edits if edit.category is category)

    @property
    def words_delta(self) -> int:
        return sum(edit.words_delta for edit in self.edits)

    def to_json(self) -> dict[str, Any]:
        return {
            "edits": [edit.to_json() for edit in self.edits],
            "dropped": [item.to_json() for item in self.dropped],
            "counts": {str(category): len(self.of_category(category)) for category in Category},
            "words_delta": self.words_delta,
        }


# Building ------------------------------------------------------------------


def _one_line(note: str | None, fallback: str) -> str:
    if not note:
        return fallback
    flattened = " ".join(note.split())
    match = FIRST_SENTENCE.match(flattened)
    line = (match.group(0) if match else flattened).strip()
    return line if len(line) <= REASON_LENGTH else line[: REASON_LENGTH - 3].rstrip() + "..."


def _auto_actionable(finding: dict[str, Any]) -> bool:
    return (
        not finding.get("advisory")
        and finding.get("severity") == "high"
        and finding.get("suggestion") in {"delete", "delete_clause"}
    )


def _recapitalize(document: Document, start: int, end: int) -> tuple[int, str]:
    """Extend a cut that removes a sentence's opening word, so the next one leads.

    The fluff pass deliberately leaves this alone: it knows a phrase is filler,
    and only this layer knows that the phrase started a sentence and that
    deleting it would leave the paper opening a sentence in lower case. The
    proposed text is still the author's own word, with one letter recased.
    """
    sentence = document.sentence_at(start)
    if sentence is None or sentence.span.char_start != start:
        return end, ""

    tail = document.source_text[end : sentence.span.char_end]
    match = NEXT_WORD.match(tail)
    if match is None or not match.group(1)[:1].islower():
        return end, ""

    word = match.group(1)
    return end + match.end(), tail[: match.start(1)] + word[0].upper() + word[1:]


def _fluff_edits(document: Document, bundle: EvidenceBundle) -> list[Edit]:
    payload = bundle.payload("fluff")
    if not isinstance(payload, list):
        return []

    edits: list[Edit] = []
    for finding in payload:
        start, end = finding["char_range"]
        evidence = f"fluff:{finding['rule']}@{start}-{end}"

        if _auto_actionable(finding):
            end, proposed = _recapitalize(document, start, end)
            edits.append(
                Edit(
                    span_id=finding["span_id"],
                    category=Category.CUT,
                    original=document.source_text[start:end],
                    proposed=proposed,
                    reason=_one_line(finding.get("note"), "Filler. The sentence reads without it."),
                    evidence=evidence,
                    confidence=CONFIDENCE["fluff_deletion"],
                    char_range=(start, end),
                )
            )
            continue

        replacement = finding.get("replacement")
        if finding.get("suggestion") != "replace_with" or not replacement:
            continue

        original = document.source_text[start:end]
        if len(replacement.split()) >= len(original.split()):
            # TIGHTEN means the same claim in fewer words. A lexicon entry that
            # would not shorten the sentence is a style preference, and this
            # tool does not spend the author's attention on those.
            continue

        edits.append(
            Edit(
                span_id=finding["span_id"],
                category=Category.TIGHTEN,
                original=original,
                proposed=replacement,
                reason=_one_line(finding.get("note"), f"Says the same as {replacement!r}."),
                evidence=evidence,
                confidence=CONFIDENCE["fluff_replacement"],
                char_range=(start, end),
            )
        )
    return edits


def _orphan_edits(document: Document, bundle: EvidenceBundle) -> list[Edit]:
    payload = bundle.payload("novelty")
    if not isinstance(payload, dict):
        return []

    edits: list[Edit] = []
    for orphan in payload.get("orphans") or ():
        start, end = orphan["char_range"]
        edits.append(
            Edit(
                span_id=orphan["span_id"],
                category=Category.CUT,
                original=document.source_text[start:end],
                proposed="",
                reason="No sentence in this paragraph serves any part of the contribution claim.",
                evidence=f"novelty:orphan:{orphan['span_id']}",
                confidence=CONFIDENCE["orphan_paragraph"],
                char_range=(start, end),
            )
        )
    return edits


def resolve_overlaps(edits: Iterable[Edit]) -> tuple[tuple[Edit, ...], tuple[Dropped, ...]]:
    """Keep the confident row where two rows touch the same characters.

    Applying both would splice one into the middle of the other and produce
    text neither proposal described. Detecting it here rather than at write time
    means the author sees why a row is absent instead of finding a corrupted
    paragraph afterwards.
    """
    ranked = sorted(edits, key=lambda edit: (-edit.confidence, edit.char_range, edit.id))
    kept: list[Edit] = []
    dropped: list[Dropped] = []

    for edit in ranked:
        start, end = edit.char_range
        clash = next(
            (other for other in kept if start < other.char_range[1] and other.char_range[0] < end),
            None,
        )
        if clash is None:
            kept.append(edit)
            continue
        dropped.append(
            Dropped(
                edit=edit,
                rule="overlapping_edit",
                note=(
                    f"Overlaps {clash.id} ({clash.category}, confidence "
                    f"{clash.confidence:.2f}), which was kept. Applying both would "
                    f"produce text neither one proposed."
                ),
            )
        )

    kept.sort(key=lambda edit: edit.char_range)
    return tuple(kept), tuple(dropped)


def build(
    document: Document,
    bundle: EvidenceBundle,
    rejected: frozenset[str] = frozenset(),
) -> Ledger:
    """Every change the evidence supports, minus the ones already turned down."""
    proposals = _fluff_edits(document, bundle) + _orphan_edits(document, bundle)

    admitted: list[Edit] = []
    dropped: list[Dropped] = []

    for edit in proposals:
        # The gate again, per row. A row whose pointer names no record in the
        # bundle is a change the tool wanted to make rather than one the
        # evidence asked for, and it never reaches the ledger.
        bundle.validate(edit.evidence, edit.span_id)

        if edit.id in rejected:
            continue

        protected = document.overlapping_protected(_as_span(document, edit.char_range))
        if protected:
            dropped.append(
                Dropped(
                    edit=edit,
                    rule="protected_range",
                    note=(
                        f"Overlaps source the format cannot survive an edit to "
                        f"({document.text_of(protected[0])!r} at line {protected[0].line}). "
                        f"A broken build costs the author more than the writing problem."
                    ),
                )
            )
            continue

        admitted.append(edit)

    kept, overlapping = resolve_overlaps(admitted)
    return Ledger(edits=kept, dropped=tuple(dropped) + overlapping)


def _as_span(document: Document, char_range: tuple[int, int]) -> Span:
    start, end = char_range
    return Span(start, end, line=document.source_text.count("\n", 0, start) + 1)


# Emission ------------------------------------------------------------------


def apply_to(text: str, edits: Iterable[Edit]) -> str:
    """Splice every row into the source, last one first.

    Back to front because applying an edit changes every offset after it. Doing
    it in document order would mean recomputing the rest of the ledger after
    each splice, and a single arithmetic slip there silently corrupts a paper.
    """
    ordered = sorted(edits, key=lambda edit: edit.char_range, reverse=True)
    result = text
    previous_start = len(text) + 1
    for edit in ordered:
        start, end = edit.char_range
        if end > previous_start:
            raise ValueError(
                f"edit {edit.id} at {start}..{end} overlaps a later one. "
                f"Call resolve_overlaps before applying."
            )
        result = result[:start] + edit.proposed + result[end:]
        previous_start = start
    return result


def to_diff(document: Document, edits: Iterable[Edit]) -> str:
    """The ledger as a unified diff, for review in a terminal or an editor."""
    before = document.source_text
    after = apply_to(before, edits)
    if before == after:
        return ""
    name = document.path.name
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
            n=3,
        )
    )


HEADINGS = {
    Category.CUT: "Cuts",
    Category.TIGHTEN: "Tightenings",
    Category.GROUND: "Grounding",
    Category.FIX: "Fixes",
}


def to_summary(ledger: Ledger) -> str:
    """Grouped by category, so an author can take all the cuts and think about
    the rest, rather than making the same decision forty times in a row."""
    lines = [
        "# Proposed edits",
        "",
        "Nothing here has been applied. Every row names the finding behind it, and",
        "a row you reject is not proposed again.",
        "",
    ]

    for category in Category:
        edits = ledger.of_category(category)
        if not edits:
            continue
        words = sum(edit.words_delta for edit in edits)
        lines += [f"## {HEADINGS[category]} ({len(edits)}, {words:+d} words)", ""]
        for edit in edits:
            lines += [
                f"- `{edit.id}` {edit.reason}",
                f"  - remove: {_show(edit.original)}",
            ]
            if edit.proposed:
                lines.append(f"  - insert: {_show(edit.proposed)}")
            lines.append(f"  - evidence: `{edit.evidence}`")
        lines.append("")

    if not ledger.edits:
        lines += [
            "No change is supported by the evidence that was gathered. That is a",
            "statement about the checks that ran, not a verdict on the paper.",
            "",
        ]

    if ledger.dropped:
        lines += [f"## Not proposed ({len(ledger.dropped)})", ""]
        for item in ledger.dropped:
            lines.append(f"- `{item.edit.id}` {item.note}")
        lines.append("")

    return "\n".join(lines)


def _show(text: str) -> str:
    flattened = " ".join(text.split())
    return f"{flattened[:117]}..." if len(flattened) > 120 else flattened


# Interactive review --------------------------------------------------------

ACCEPT = "accepted"
REJECT = "rejected"
SKIP = "skipped"

_ANSWERS = {
    "a": ACCEPT,
    "y": ACCEPT,
    "r": REJECT,
    "n": REJECT,
    "s": SKIP,
    "": SKIP,
}


def review(
    ledger: Ledger,
    ask: Callable[[str], str],
    say: Callable[[str], None],
    already: dict[str, str] | None = None,
) -> dict[str, str]:
    """Walk the ledger one row at a time and record what the author decided.

    Skipping is a real answer and not the same as rejecting. An author who is
    not sure yet should not have the row taken away from them, so a skip leaves
    no decision and the row comes back next run.
    """
    decisions = dict(already or {})
    for position, edit in enumerate(ledger.edits, start=1):
        if decisions.get(edit.id) in {ACCEPT, REJECT}:
            continue

        say(f"[{position}/{len(ledger.edits)}] {edit.category} {edit.reason}")
        say(f"  remove: {_show(edit.original)}")
        if edit.proposed:
            say(f"  insert: {_show(edit.proposed)}")
        say(f"  evidence: {edit.evidence}")

        answer = _ANSWERS.get(ask("  [a]ccept, [r]eject, [s]kip: ").strip().lower(), SKIP)
        if answer != SKIP:
            decisions[edit.id] = answer
    return decisions


# Persistence ---------------------------------------------------------------

DECISIONS = "edit-decisions"


def load_decisions(store: ArtifactStore) -> dict[str, str]:
    """What the author has already accepted or rejected.

    Read without the staleness check every other artifact gets, and on purpose.
    A decision is about a proposal, not about a draft, and row ids are content
    derived rather than positional. Somebody who rejected a cut should not have
    it offered again because they fixed a typo three sections away.
    """
    artifact = store.read(DECISIONS)
    if artifact is None or not isinstance(artifact.payload, dict):
        return {}
    return {str(key): str(value) for key, value in artifact.payload.items()}


def save_decisions(store: ArtifactStore, decisions: dict[str, str], source_hash: str) -> None:
    if decisions:
        store.write(DECISIONS, decisions, source_hash)


def rejected_ids(decisions: dict[str, str]) -> frozenset[str]:
    return frozenset(key for key, value in decisions.items() if value == REJECT)
