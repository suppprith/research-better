"""What the paper claims to contribute, and which sentences serve it.

Everything else in the tool is downstream of this. "Does this sentence earn its
place" is meaningless without a stated claim to measure against, so the claim
comes first and the rest follows from it.

Two rules keep this from being destructive.

The first is the stop condition. If no contribution claim can be found in the
abstract, the introduction, or a contributions list, the pass stops and says so
rather than guessing one. A paper whose novelty cannot be identified from its
own abstract has a problem no editing pass can fix, and telling the author that
is worth more than tightening their prose around a claim the tool invented.

The second is the guard on what is never an orphan. The naive reading of "cut
what does not serve the novelty" deletes the related work and the limitations
section, and both are doing their jobs. Background that contextualizes is not
padding, and reviewers require limitations. So role comes before orphanhood,
and only a sentence with no role at all can be an orphan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from research_better.findings import Finding, Severity, Suggestion, sort_findings
from research_better.model import Document, Sentence

WORD = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")
NUMBER = re.compile(r"\d")

CLAIM_MARKERS = (
    "our primary contribution",
    "our main contribution",
    "our contribution",
    "the contributions of this paper",
    "our contributions are as follows",
    "we make the following contributions",
    "the following contributions",
    "contributions are as follows",
    "our contributions are",
    "contributions:",
    "the main contribution",
    "we contribute",
    "in this paper we propose",
    "in this paper we present",
    "in this paper we introduce",
    "we propose",
    "we present",
    "we introduce",
    "we show that",
    "we demonstrate that",
    "this paper proposes",
    "this paper presents",
    "we argue that",
)
"""Ordered most explicit first. A sentence saying "our primary contribution is"
is a better claim than one saying "we show that", and the first match wins."""

CLAIM_SECTIONS = ("abstract", "introduction", "contributions")

ENUMERATOR = re.compile(
    r"\(\s*(?:[ivx]{1,4}|[a-h]|\d{1,2})\s*\)|(?:(?<=\s)|^)\d{1,2}[.)](?=\s)|\\item\b",
    re.IGNORECASE,
)
"""A list marker, in the forms a contributions list is actually written in.

`(i)`, `(a)`, `1)`, and `\\item` all mark structure. None of them is a claim
about anything, and until they were stripped every one of them arrived in
`unsupported_claim_parts` as something the body was required to establish.
"""

ENUMERATOR_TOKENS = frozenset(
    """
    i ii iii iv v vi vii viii ix x xi xii
    a b c d e f g h
    one two three four five six seven eight nine ten eleven twelve
    thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty
    first second third fourth fifth sixth seventh eighth ninth tenth
    """.split()
)
"""Tokens that are list markers or counts rather than content.

The reported unsupported parts on a real paper were `ii`, `iii`, `iv`, `vi`,
`five`, and `contributions`. `i` and `v` were absent, because they occur in the
body as ordinary tokens and were marked covered by accident, which is the same
bug pointing the other way.
"""

CLAIM_STRUCTURE = frozenset(
    """
    contribution contributions paper work works propose proposes proposed
    present presents presented introduce introduces introduced show shows
    shown demonstrate demonstrates demonstrated make makes made argue argues
    argued describe describes described study studies section sections
    following follows summarize summarizes summarized
    """.split()
)
"""Vocabulary that describes a claim rather than being part of one.

"We make five contributions" says nothing the body can support or fail to
support. Requiring the body to establish the word `contributions` is how a
claim comes back permanently unsupported.
"""

METHOD_CUES = (
    "we index",
    "we use",
    "we apply",
    "we train",
    "we implement",
    "we compute",
    "is indexed",
    "are expanded",
    "was applied",
    "were selected",
    "is defined",
    "the parameters",
    "our approach",
    "our method",
    "our selection",
    "the algorithm",
    "the system",
)

EVIDENCE_CUES = (
    "improves",
    "improved",
    "rose",
    "fell",
    "outperforms",
    "achieves",
    "achieved",
    "we observe",
    "we did not observe",
    "we measured",
    "recall",
    "accuracy",
    "results show",
    "the gain",
)

LIMITATION_CUES = (
    "we did not",
    "we have not",
    "does not",
    "do not",
    "cannot",
    "limitation",
    "limitations",
    "threat to validity",
    "threats to validity",
    "is not reproduced",
    "are not reproduced",
    "assumes",
    "we leave",
    "remains open",
    "future work",
    "caveat",
)

INTERPRETATION_CUES = (
    "suggests",
    "indicates",
    "implies",
    "means that",
    "this shows",
    "we interpret",
    "it follows",
    "which explains",
    "consistent with",
)

LIMITATION_SECTIONS = ("limitation", "limitations", "threats to validity", "discussion")
BACKGROUND_SECTIONS = ("related work", "background", "prior work", "literature review")

CLAIM_OVERLAP = 0.34
"""Share of the claim's content words a sentence must carry to count as serving
it. Deliberately low. A sentence supporting one part of a multi-part claim
serves it, and requiring more would call most of the paper an orphan."""

STOPWORDS = frozenset(
    """
    a an the and or but of in on at to for with by from as is are was were be
    been being it its this that these those we our us they their there here
    which who what when where why how can could may might will would should has
    have had do does did not than then so such more most other some new using
    used use also both each
    """.split()
)


class Role(StrEnum):
    CONTRIBUTION = "contribution"
    BACKGROUND = "background"
    METHOD = "method"
    EVIDENCE = "evidence"
    INTERPRETATION = "interpretation"
    LIMITATION = "limitation"
    ORPHAN = "orphan"


class NoClaimFoundError(Exception):
    """No contribution claim could be located, so nothing downstream can run.

    Not a `ResearchBetterError` subclass by accident: callers are meant to
    report this to the author as a finding about the paper, not swallow it as a
    tool failure.
    """


def content_words(text: str) -> set[str]:
    return {word.lower() for word in WORD.findall(text)} - STOPWORDS


def claim_content_words(text: str) -> set[str]:
    """The words of a claim that the body can actually be asked to establish.

    Narrower than `content_words` and only applied to the claim, because the
    claim is the side of the comparison that carries structure. A body sentence
    saying "contributions" is unremarkable. A claim requiring the body to
    establish the word "contributions" can never come back supported.
    """
    return content_words(text) - ENUMERATOR_TOKENS - CLAIM_STRUCTURE


@dataclass(frozen=True, slots=True)
class ClaimItem:
    """One item of an enumerated contribution claim.

    A five-item contributions list is five claims. The useful output is which
    of the five the body picks up, not one verdict over the union of their
    words, which is a shape that cannot say anything an author can act on.
    """

    label: str
    text: str
    supported: bool

    def to_json(self) -> dict[str, Any]:
        return {"label": self.label, "text": self.text, "supported": self.supported}


def split_claim_items(text: str) -> tuple[tuple[str, str], ...]:
    """An enumerated claim as (label, text) pairs, or empty if it is not one.

    Two markers minimum. One `(i)` with no `(ii)` after it is a parenthesis,
    not a list, and treating it as one would split a plain claim in half.
    """
    markers = list(ENUMERATOR.finditer(text))
    if len(markers) < 2:
        return ()

    items: list[tuple[str, str]] = []
    for position, marker in enumerate(markers):
        end = markers[position + 1].start() if position + 1 < len(markers) else len(text)
        body = text[marker.end() : end].strip(" \t\n,;.")
        if body:
            items.append((marker.group(0).strip(), body))
    return tuple(items)


def _section_title(document: Document, sentence: Sentence) -> str:
    if not sentence.section_id:
        return ""
    for section in document.sections:
        if section.id == sentence.section_id:
            return section.title.lower()
    return ""


def _in_any(title: str, names: tuple[str, ...]) -> bool:
    return any(name in title for name in names)


def _has_cue(text: str, cues: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in cues)


@dataclass(frozen=True, slots=True)
class Orphan:
    span_id: str
    text: str
    reason: str
    char_range: tuple[int, int]

    def to_json(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "text": self.text,
            "reason": self.reason,
            "char_range": list(self.char_range),
        }


@dataclass(frozen=True, slots=True)
class NoveltyReport:
    claim: str | None = None
    claim_span_id: str | None = None
    claim_confirmed: bool = False
    claim_evidence_spans: tuple[str, ...] = ()
    unsupported_claim_parts: tuple[str, ...] = ()
    """What the body does not pick up, named the way the claim states it.

    Parts, not words. A claim written as one sentence has no parts smaller than
    its content words, so those are what appear. A claim written as an
    enumerated list has real parts, and naming an item is something an author
    can act on in a way that a bag of its words is not.
    """

    claim_items: tuple[ClaimItem, ...] = ()
    """Set only when the claim is enumerated. Empty is not "all supported", it
    is "this claim is one sentence"."""

    roles: dict[str, str] = field(default_factory=dict)
    serves: dict[str, list[str]] = field(default_factory=dict)
    orphans: tuple[Orphan, ...] = ()

    @property
    def claim_is_supported(self) -> bool:
        return bool(self.claim_evidence_spans) and not self.unsupported_claim_parts

    def to_json(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "claim_span_id": self.claim_span_id,
            "claim_confirmed": self.claim_confirmed,
            "claim_evidence_spans": list(self.claim_evidence_spans),
            "unsupported_claim_parts": list(self.unsupported_claim_parts),
            "claim_items": [item.to_json() for item in self.claim_items],
            "roles": dict(self.roles),
            "serves": {key: list(value) for key, value in self.serves.items()},
            "orphans": [orphan.to_json() for orphan in self.orphans],
        }


def extract_claim(document: Document) -> Sentence | None:
    """The paper's contribution claim, in its own words.

    Looks only where a contribution is actually stated: the abstract, the
    introduction, and an explicit contributions list. A method sentence that
    happens to say "we use" is not a claim, and searching the whole paper would
    find dozens of them.
    """
    candidates = [
        sentence
        for sentence in document.sentences
        if not sentence.section_id or _in_any(_section_title(document, sentence), CLAIM_SECTIONS)
    ]
    for marker in CLAIM_MARKERS:
        for sentence in candidates:
            if marker in sentence.text.lower():
                return sentence
    return None


def assign_role(document: Document, sentence: Sentence, claim_words: set[str]) -> Role:
    """One role per sentence, checked in order of how strong the signal is.

    Order matters. A limitations sentence often contains method words, and a
    background sentence often contains a number, so the more specific cue is
    tested first and the vaguest last.
    """
    title = _section_title(document, sentence)
    text = sentence.text

    if _in_any(title, LIMITATION_SECTIONS) or _has_cue(text, LIMITATION_CUES):
        return Role.LIMITATION

    if _has_cue(text, CLAIM_MARKERS):
        return Role.CONTRIBUTION

    # A cited sentence is contextualizing, wherever it sits. Background that
    # contextualizes rather than directly supports the novelty is doing its job.
    if document.citations_in_sentence(sentence.id):
        return Role.BACKGROUND

    if _in_any(title, BACKGROUND_SECTIONS) and content_words(text) & claim_words:
        return Role.BACKGROUND

    if _has_cue(text, METHOD_CUES):
        return Role.METHOD

    # A bare number is not evidence. "Databases have existed since the 1960s"
    # contains a digit and reports nothing, so a digit only counts when the
    # sentence is also talking about the paper's own claim.
    if _has_cue(text, EVIDENCE_CUES) or (NUMBER.search(text) and content_words(text) & claim_words):
        return Role.EVIDENCE

    if _has_cue(text, INTERPRETATION_CUES):
        return Role.INTERPRETATION

    return Role.ORPHAN


def _orphan_paragraphs(document: Document, roles: dict[str, str]) -> tuple[Orphan, ...]:
    """Orphanhood is a property of a paragraph, not of a sentence.

    A paragraph makes one move in the argument, and a short sentence inside a
    paragraph that reports results is part of reporting those results. Judging
    sentences alone flags "Expansion helps short queries" sitting among three
    sentences of measurements, which is how a cutting tool starts deleting the
    author's actual findings.

    So a paragraph is an orphan only when every sentence in it is, and then the
    whole paragraph is offered for cutting together.
    """
    by_paragraph: dict[str, list[Sentence]] = {}
    for sentence in document.sentences:
        by_paragraph.setdefault(sentence.paragraph_id, []).append(sentence)

    orphans: list[Orphan] = []
    for paragraph in document.paragraphs:
        sentences = by_paragraph.get(paragraph.id, [])
        if not sentences:
            continue
        if not all(roles.get(s.id) == str(Role.ORPHAN) for s in sentences):
            continue
        orphans.append(
            Orphan(
                span_id=sentences[0].id,
                text=" ".join(document.text_of(paragraph.span).split()),
                reason=(
                    "No sentence in this paragraph serves any part of the contribution "
                    "claim, carries a citation, reports a result, or is background or a "
                    "limitation. Check whether the paper needs it at all."
                ),
                char_range=(paragraph.span.char_start, paragraph.span.char_end),
            )
        )
    return tuple(orphans)


def analyse(document: Document, confirmed: bool = False) -> NoveltyReport:
    """Audit the paper against its own contribution claim.

    Raises `NoClaimFoundError` when there is nothing to measure against.
    """
    claim_sentence = extract_claim(document)
    if claim_sentence is None:
        raise NoClaimFoundError(
            "No contribution claim could be found in the abstract, the introduction, "
            "or a contributions list. Nothing was cut and nothing was judged, because "
            "every downstream decision depends on knowing what the paper claims. A "
            "paper whose novelty cannot be identified from its own opening has a "
            "problem that tightening the prose will not fix. State the contribution "
            "in one sentence and run this again."
        )

    claim_words = claim_content_words(claim_sentence.text)
    items = split_claim_items(claim_sentence.text)

    roles: dict[str, str] = {}
    serves: dict[str, list[str]] = {}
    evidence: list[str] = []
    covered: set[str] = set()

    for sentence in document.sentences:
        if sentence.id == claim_sentence.id:
            roles[sentence.id] = str(Role.CONTRIBUTION)
            continue

        role = assign_role(document, sentence, claim_words)
        roles[sentence.id] = str(role)

        shared = claim_words & content_words(sentence.text)
        if shared:
            serves[sentence.id] = sorted(shared)
            covered |= shared

        if role in {Role.EVIDENCE, Role.METHOD} and len(shared) / max(1, len(claim_words)) >= (
            CLAIM_OVERLAP
        ):
            evidence.append(sentence.id)

    orphans = _orphan_paragraphs(document, roles)
    checked, unsupported = _check_claim_parts(items, claim_words, covered)

    return NoveltyReport(
        claim=" ".join(claim_sentence.text.split()),
        claim_span_id=claim_sentence.id,
        claim_confirmed=confirmed,
        claim_evidence_spans=tuple(evidence),
        unsupported_claim_parts=unsupported,
        claim_items=checked,
        roles=roles,
        serves=serves,
        orphans=tuple(orphans),
    )


def _check_claim_parts(
    items: tuple[tuple[str, str], ...], claim_words: set[str], covered: set[str]
) -> tuple[tuple[ClaimItem, ...], tuple[str, ...]]:
    """Which parts of the claim the body picks up, checked item by item.

    An enumerated claim is checked per item, because the union of five items'
    words is not a thing the body either supports or does not. An item counts
    as picked up when the body carries any of its content words: a low bar on
    purpose, matching `CLAIM_OVERLAP`, since the alternative is telling an
    author their work is missing when it is merely described in other words.
    """
    if not items:
        return (), tuple(sorted(claim_words - covered))

    checked: list[ClaimItem] = []
    unsupported: list[str] = []
    for label, text in items:
        words = claim_content_words(text)
        supported = bool(words & covered) if words else True
        checked.append(ClaimItem(label=label, text=" ".join(text.split()), supported=supported))
        if not supported:
            unsupported.append(f"{label} {' '.join(text.split())}")
    return tuple(checked), tuple(unsupported)


def confirmation_prompt(report: NoveltyReport) -> str:
    """What to show the author before anything downstream runs.

    The one point in this tool worth interrupting for. If the claim is wrong,
    every cut that follows is wrong, and the author is the only one who knows.
    """
    return (
        f"This paper appears to claim:\n\n  {report.claim}\n\n"
        f"Everything that follows is measured against that sentence. If it is not "
        f"your contribution, say what is, because every cut downstream depends on it."
    )


def to_findings(report: NoveltyReport) -> list[Finding]:
    """Orphan paragraphs and unsupported parts of the claim.

    Every one is `REVIEW`, including the orphans. Cutting a paragraph is the
    biggest edit this tool can propose and it is exactly the kind that has to
    be a person's decision, because the tool cannot see why the author put it
    there.
    """
    findings: list[Finding] = [
        Finding(
            span_id=orphan.span_id,
            rule="novelty_orphan_paragraph",
            severity=Severity.MEDIUM,
            matched_text=orphan.text[:200],
            char_range=orphan.char_range,
            suggestion=Suggestion.REVIEW,
            note=orphan.reason,
        )
        for orphan in report.orphans
    ]

    if report.claim and report.unsupported_claim_parts:
        # Items are phrases and read as a list. Words are tokens and read as a
        # set. Joining both with the same separator makes one of them look like
        # the other.
        missing = (
            "; ".join(report.unsupported_claim_parts)
            if report.claim_items
            else ", ".join(report.unsupported_claim_parts)
        )
        subject = "items of the stated contribution" if report.claim_items else "parts of the claim"
        findings.append(
            Finding(
                span_id=report.claim_span_id or "",
                rule="novelty_unsupported_contribution",
                severity=Severity.HIGH,
                matched_text=report.claim[:200],
                char_range=(0, 0),
                suggestion=Suggestion.REVIEW,
                note=(
                    f"Nothing in the body picks up these {subject}: {missing}. Either "
                    f"the paper is missing the work that supports them, or the claim is "
                    f"broader than what was done. Both are worth knowing before a "
                    f"reviewer finds out."
                ),
            )
        )
    return sort_findings(findings)
