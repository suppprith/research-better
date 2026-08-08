"""Which passages read as machine-written, why, and whether to touch them.

This is the honest form of "zero AI traces". It names the passages that carry
the signals a human reader picks up on, says what each signal is, and offers a
fix that improves the writing whether or not anybody ever runs a detector over
the paper.

Four commitments hold the pass together, and each is a property of the code
rather than a promise in a docstring.

**No detection service is called.** Not GPTZero, not Turnitin, not
Originality.ai, not anything. This module fetches nothing, so there is nothing
to audit, and a test asserts the package names none of them anywhere.

**No score is printed.** No percentage, no likelihood, no index. A number
attached to a paper is read as a grade for its author, and a number attached to
a paragraph gets optimized against, which is the failure this whole tool exists
to avoid. Counts and causes, and nothing that can be watched go down.

**Every signal is measured against the paper's own distribution.** A paragraph
is uniform relative to the other paragraphs of this paper. A section deviates
relative to the rest of this paper. There is no corpus and no reference
population, so no threshold here encodes what "normal academic writing" is
supposed to look like. That matters most for the writers detectors treat worst:
this compares a paper with itself.

**A texture signal never flags on its own.** Rhythm and register are exactly
the signals that misfire on writers whose first language is not English, and on
methods prose, which is uniform because the method is a list of steps. So a
flag needs a content-level cause: a claim the cited source does not carry, an
assertion with nothing behind it, or filler. Texture only ever joins a flag
that already stands.

Where texture fired and nothing else did, the passage is reported as looked at
and left alone, with the reason. That list is not a footnote. Telling an author
to mangle a correctly written methods section because a detector might dislike
its rhythm is a worse outcome than the flag would have been.

See `docs/INTEGRITY.md` for why optimizing against a detector is the wrong
target in the first place.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from research_better import fluff, voice
from research_better.findings import Finding
from research_better.grounding.claims import SUPERLATIVES, UNIVERSALS
from research_better.lexicon import load_lexicon
from research_better.model import Document, Paragraph, Section, Sentence

NAME = "trace"

FILLER_FAMILIES = frozenset(
    {
        "filler_opener",
        "empty_intensifier",
        "model_vocabulary",
        "nominalization",
        "throat_clearing",
    }
)
"""Lexical families that count as filler for this pass. Each one is a phrase
the fluff pass can delete outright, which is what makes the fix here a real
writing change rather than a rewording."""

HEDGE_FAMILY = "hedge_stack"

TEXTURE_RULES = frozenset({"paragraph_shape_uniformity"})
"""Structural rules that describe a shape and name no defect. A run of
paragraphs of similar length is an observation about the layout of the page,
and there is nothing in it a writer should act on by itself."""

STRUCTURAL_SIGNALS: dict[str, tuple[str, str]] = {
    "tricolon": (
        "A three-item list repeated through a section is a cadence rather than an "
        "argument. Generated prose reaches for it because the shape is available "
        "whether or not there are three things to say.",
        "Rewrite one of them as a plain sentence, or drop the item that is there to "
        "make the list a three. One tricolon is a choice and nobody notices it.",
    ),
    "balanced_clause": (
        'A "not only, but also" frame used twice in a section is a template being '
        "filled. A reader hears the second one as a pattern and stops reading the "
        "content of it.",
        "Say the two things in two sentences. If the second half was only there to "
        "balance the first, it goes.",
    ),
    "empty_forward_reference": (
        "A forward reference that names no section, figure, or equation points at "
        "nothing. It is what a model writes because papers contain sentences of that "
        "shape, and it is what a reviewer follows and finds missing.",
        "Name what it points at, or cut the sentence. If there is nothing later that "
        "discusses this, the promise was the whole content of the sentence.",
    ),
    "section_closing_restatement": (
        "A closing sentence that introduces no word its section's opening did not "
        "already carry is filling a slot. Ending a section by restating it is a shape "
        "generated text produces reliably, because the shape is what it learned.",
        "Cut it. Nothing in the section is lost, because nothing in it was only there.",
    ),
}
"""Structural fluff rules that name a real defect: why each reads as generated,
and what to do about it. Keyed by the fluff rule and reported under the same
name, so a signal here can be looked up in fluff.json without a translation.

These are advisory in the fluff pass because they read a distribution rather
than a dictionary. They are content here rather than texture, because each one
names a specific construction and the fix for it improves the paragraph whether
or not anybody ever runs a detector."""

FILLER_RUN = 2
"""Filler phrases in one paragraph before it is a pattern rather than a slip.
One tired opener is something everybody writes on a bad afternoon."""

STACKED_HEDGES = 2
"""Hedges in a single sentence before the sentence is saying a thing and
withdrawing it in the same breath."""

RHYTHM_SENTENCES = 4
"""Sentences a paragraph needs before its spread means anything. A standard
deviation over three sentences moves more with one long sentence than with
anything about the writing."""

RHYTHM_BASELINE_SENTENCES = 10
"""Sentences the paper needs before its own spread is a baseline worth
comparing a paragraph against. The comparison is with this paper, and there has
to be enough of this paper to compare with."""

UNIFORM_SHARE = 0.5
"""Share of the paper's own sentence-length spread below which a paragraph
counts as uniform. Not a corpus threshold: it says this paragraph varies half
as much as this author's paper does, which is a statement about the draft
rather than about how humans write.

Set below one on purpose. A paragraph is always tighter than the document that
contains it, because the document's spread carries the differences between
paragraphs as well as the differences inside them."""

SECTIONS_FOR_DEVIATION = 3
"""Profiled sections needed before a section can be said to deviate. Two
sections deviate from each other by construction, and reporting that would put
an authorship question in front of an author for nothing."""

DEVIATION_SPREAD = 2.0
"""Multiples of the spread across the paper's own sections before a numeric
difference is worth reporting."""

METHOD_SECTIONS = (
    "method",
    "methods",
    "methodology",
    "materials",
    "procedure",
    "experimental setup",
    "implementation",
    "setup",
    "protocol",
    "apparatus",
)
"""Section titles whose prose is supposed to be uniform. A method is a list of
steps and reads like one, and that is the single most common false positive a
detector produces on a technical paper."""

DIGIT = re.compile(r"\d")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")

ORDINARY = frozenset({"first", "only", "all", "any", "no", "none", "every", "exact"})
"""Words the claim checker treats as strength markers that are too common in
ordinary prose to mean anything here.

The claim checker sees them inside a sentence already known to be cited to a
source, where "every" is a quantifier over a result. This pass sees every
sentence in the paper, where "every day" is a Tuesday. Flagging those turned a
paragraph about how many people use search engines into an overclaim."""

ASSERTIVE = (UNIVERSALS | SUPERLATIVES) - ORDINARY
"""Words that raise a sentence above what it can carry unaided. Taken from the
claim checker rather than copied out, so the two cannot drift into disagreeing
about what an overclaim is."""


class Standing(StrEnum):
    """What the author should do about a passage.

    There is no fourth value for "probably generated". The tool does not decide
    that and could not defend it if it did.
    """

    FIX = "fix"
    REVIEW = "review"
    LEAVE = "leave"


@dataclass(frozen=True, slots=True)
class Signal:
    """One reason a passage might read as machine-written.

    `fix` is the whole point of the type. A signal with no fix that improves the
    writing on its own terms has no business being reported, because the only
    remaining reason to act on it would be to look less machine-written, and
    that is the change this tool does not make.
    """

    id: str
    evidence: str
    why: str
    fix: str
    texture: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "evidence": self.evidence,
            "why": self.why,
            "fix": self.fix,
            "texture": self.texture,
        }


@dataclass(frozen=True, slots=True)
class Passage:
    """One paragraph or section the audit looked at, and what it concluded."""

    where: str
    span_id: str
    char_range: tuple[int, int]
    quote: str
    signals: tuple[Signal, ...]
    standing: Standing
    reason: str

    @property
    def summary(self) -> str:
        """The causes, named, for the one-line form."""
        return " + ".join(signal.id.replace("_", " ") for signal in self.signals)

    @property
    def fixes(self) -> tuple[str, ...]:
        return tuple(signal.fix for signal in self.signals if signal.fix)

    def to_json(self) -> dict[str, Any]:
        return {
            "where": self.where,
            "span_id": self.span_id,
            "char_range": list(self.char_range),
            "quote": self.quote,
            "standing": str(self.standing),
            "reason": self.reason,
            "signals": [signal.to_json() for signal in self.signals],
        }


@dataclass(frozen=True, slots=True)
class TraceReport:
    passages: tuple[Passage, ...] = ()
    gaps: tuple[str, ...] = ()
    sections_profiled: int = 0

    @property
    def flagged(self) -> tuple[Passage, ...]:
        return tuple(item for item in self.passages if item.standing is not Standing.LEAVE)

    @property
    def left_alone(self) -> tuple[Passage, ...]:
        return tuple(item for item in self.passages if item.standing is Standing.LEAVE)

    def to_json(self) -> dict[str, Any]:
        return {
            "flagged": [item.to_json() for item in self.flagged],
            "left_alone": [item.to_json() for item in self.left_alone],
            "not_checked": list(self.gaps),
            "counts": {
                "flagged": len(self.flagged),
                "left_alone": len(self.left_alone),
                "sections_profiled": self.sections_profiled,
            },
        }


# Locating things ------------------------------------------------------------


def _where(document: Document, paragraph: Paragraph, index: int) -> str:
    if paragraph.section_id is None:
        return f"paragraph {index}"
    return f"{document.section(paragraph.section_id).title}, paragraph {index}"


def _quote(text: str, limit: int = 160) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _paragraph_index(document: Document) -> dict[str, int]:
    """Each paragraph's position within its own section, counting from one."""
    seen: dict[str | None, int] = {}
    numbered: dict[str, int] = {}
    for paragraph in document.paragraphs:
        seen[paragraph.section_id] = seen.get(paragraph.section_id, 0) + 1
        numbered[paragraph.id] = seen[paragraph.section_id]
    return numbered


def _is_method(document: Document, section_id: str | None) -> bool:
    if section_id is None:
        return False
    title = document.section(section_id).title.lower().strip()
    stripped = re.sub(r"^[\d.\s]+", "", title).strip(" .:")
    return any(stripped.startswith(name) for name in METHOD_SECTIONS)


# Content signals ------------------------------------------------------------


def _unsupported_claims(sentences: list[Sentence], claims: list[dict[str, Any]]) -> list[Signal]:
    ids = {sentence.id for sentence in sentences}
    signals: list[Signal] = []
    for check in claims:
        if check.get("support") != "UNSUPPORTED" or check.get("span_id") not in ids:
            continue
        signals.append(
            Signal(
                id="unsupported_claim",
                evidence=(
                    f"cited to [{check.get('citation_key')}], and the full text that was "
                    f"read does not carry it"
                ),
                why=(
                    "A sentence whose own cited source does not support it is the "
                    "strongest content-level signal there is. Text that was generated "
                    "attaches a citation because a citation belongs in that position, "
                    "not because anybody read the source."
                ),
                fix=(
                    "Read the quoted passage in grounding.json. Cite the work that "
                    "establishes this, weaken the sentence to what the source actually "
                    "says, or cut it."
                ),
            )
        )
    return signals


def _ungrounded_assertions(document: Document, sentences: list[Sentence]) -> list[Signal]:
    """Confident assertions with no citation and no number anywhere in them.

    One signal for the paragraph rather than one per sentence. Three of these
    in a row is one problem with the paragraph, and listing it three times
    makes it look like three.
    """
    found: list[tuple[str, str]] = []
    for sentence in sentences:
        if document.citations_in_sentence(sentence.id) or DIGIT.search(sentence.text):
            continue
        words = {word.lower() for word in WORD.findall(sentence.text)}
        assertive = sorted(words & ASSERTIVE)
        if assertive:
            found.append((", ".join(assertive), _quote(sentence.text, 100)))

    if not found:
        return []

    listed = "; ".join(f'"{words}" in {quote}' for words, quote in found[:2])
    more = f"; and {len(found) - 2} more" if len(found) > 2 else ""
    return [
        Signal(
            id="ungrounded_assertion",
            evidence=(f"{len(found)} sentence(s) with no citation and no number: {listed}{more}"),
            why=(
                "Asserting confidently and citing nothing is what a model produces when "
                "it has nothing to cite, because the shape of the sentence is all it is "
                "reproducing. It is also the first sentence a reviewer attacks."
            ),
            fix=(
                "Add the measurement you took or the work that establishes it. If there "
                "is neither, this is not a sentence you can defend in review, so cut it."
            ),
        )
    ]


def _filler(matched: list[str]) -> Signal:
    listed = ", ".join(f'"{phrase}"' for phrase in matched[:4])
    more = f", and {len(matched) - 4} more" if len(matched) > 4 else ""
    return Signal(
        id="filler",
        evidence=f"{len(matched)} deletable filler phrases: {listed}{more}",
        why=(
            "Filler is what fills a required length when there is nothing to say, "
            "which is the position a model is always in. A reader registers the "
            "padding before they register the argument."
        ),
        fix=(
            "Cut the phrases listed. Each is a deletion the sentence survives, and "
            "the fluff pass already carries them as an applicable patch."
        ),
    )


def _hedge_stack(count: int, quote: str) -> Signal:
    return Signal(
        id="hedge_stack",
        evidence=f"{count} hedges in one sentence: {quote}",
        why=(
            "Stacked hedges state a thing and withdraw it in the same breath. A "
            "model hedges because it cannot tell which claim it is entitled to. An "
            "author who knows what they measured hedges once, precisely."
        ),
        fix=(
            "Keep the one hedge you mean and delete the rest, or replace the lot with "
            "the actual limit: what you did not test, and on what."
        ),
    )


# Texture signals ------------------------------------------------------------


def _uniform_rhythm(spread: float, baseline: float, count: int) -> Signal:
    return Signal(
        id="uniform_rhythm",
        evidence=(
            f"{count} sentences varying by {spread:.1f} words, against {baseline:.1f} "
            f"across this paper"
        ),
        why=(
            "Even sentence length is a texture a reader notices without being able to "
            "name it. It is also what a genuinely formulaic passage looks like, so it "
            "is never a reason to change anything on its own."
        ),
        fix=(
            "Nothing on its own. If the causes above are fixed the rhythm changes with "
            "them. Do not lengthen a sentence to break a pattern."
        ),
        texture=True,
    )


def _shape(count: int) -> Signal:
    return Signal(
        id="uniform_shape",
        evidence=f"{count} paragraph(s) of near-identical length around this one",
        why=(
            "A run of paragraphs built to the same size reads as a template. It is a "
            "shape observation and says nothing about what any of them contains."
        ),
        fix=(
            "Nothing on its own. A paragraph is the length its content needs, and "
            "padding one to break a run makes the paper worse."
        ),
        texture=True,
    )


def _structural(rule: str, matches: list[str]) -> Signal:
    """One of the structural fluff rules, restated as a cause and a fix."""
    why, fix = STRUCTURAL_SIGNALS[rule]
    listed = ", ".join(f'"{" ".join(text.split())}"' for text in matches[:3])
    return Signal(
        id=rule,
        evidence=f"{len(matches)} in this paragraph: {listed}",
        why=why,
        fix=fix,
    )


# The voice consistency check ------------------------------------------------


def _deviation_signals(
    profile: voice.VoiceProfile,
    whole: voice.VoiceProfile,
    spreads: dict[str, float],
) -> list[Signal]:
    """How one section's voice departs from the paper's, on its own evidence."""
    signals: list[Signal] = []

    for dimension, mine, theirs, meaning in (
        (
            "person",
            profile.person,
            whole.person,
            "who the paper speaks as",
        ),
        (
            "spelling",
            profile.spelling,
            whole.spelling,
            "which spelling convention it follows",
        ),
    ):
        if mine == theirs or "unknown" in {mine, theirs} or mine == "mixed":
            continue
        signals.append(
            Signal(
                id=f"voice_{dimension}",
                evidence=f"this section is {mine}, the paper is {theirs}",
                why=(
                    f"A section that changes {meaning} partway through was written at a "
                    f"different time, by a different hand, or by a different tool. The "
                    f"tool does not guess which, because it cannot and you can."
                ),
                fix=(
                    "Decide which is right for the paper and make it consistent. If a "
                    "coauthor wrote this section, this is only worth knowing."
                ),
            )
        )

    for dimension, here, paper, unit in (
        ("passive_ratio", profile.passive_ratio, whole.passive_ratio, "of sentences"),
        (
            "hedging",
            profile.hedges_per_hundred_words,
            whole.hedges_per_hundred_words,
            "per hundred words",
        ),
        (
            "sentence_length",
            profile.sentence_lengths.mean,
            whole.sentence_lengths.mean,
            "words",
        ),
    ):
        spread = spreads.get(dimension, 0.0)
        if spread <= 0 or abs(here - paper) <= DEVIATION_SPREAD * spread:
            continue
        signals.append(
            Signal(
                id=f"voice_{dimension}",
                evidence=(
                    f"{here:.2f} {unit} here against {paper:.2f} for the paper, which is "
                    f"further than any other section sits from it"
                ),
                why=(
                    "A section whose texture departs this far from the rest of the paper "
                    "is what a reader notices as a change of voice. It is measured "
                    "against this paper only, so it says nothing about how anybody else "
                    "writes."
                ),
                fix=(
                    "Read it beside a section you know you wrote. If it is yours, leave "
                    "it. If it came from somewhere else, that is what to resolve, and no "
                    "wording change resolves it."
                ),
            )
        )
    return signals


def _section_spreads(profiles: list[voice.VoiceProfile]) -> dict[str, float]:
    """How much the paper's own sections already differ, per dimension."""

    def spread_of(values: list[float]) -> float:
        return round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0

    return {
        "passive_ratio": spread_of([p.passive_ratio for p in profiles]),
        "hedging": spread_of([p.hedges_per_hundred_words for p in profiles]),
        "sentence_length": spread_of([p.sentence_lengths.mean for p in profiles]),
    }


# The pass -------------------------------------------------------------------


def analyse(
    document: Document,
    grounding: dict[str, Any] | None = None,
    lexicon_file: Path | None = None,
) -> TraceReport:
    """Audit the paper, using whatever evidence is actually available.

    `grounding` is the grounding artifact's payload, or None when that pass has
    not run. Its absence is recorded as a gap rather than worked around: claim
    support is the strongest content signal this pass has, and an audit that
    ran without it and said nothing about that would be reporting a clean paper
    on the strength of a check it never made.
    """
    gaps: list[str] = []
    claims: list[dict[str, Any]] = []
    if grounding is None:
        gaps.append(
            "The grounding pass has not run, so no passage here was checked against "
            "the sources it cites. That is the strongest signal this audit has."
        )
    else:
        claims = list((grounding.get("claims") or {}).get("checks") or [])

    lexicon = load_lexicon(lexicon_file)
    families = {section.id: section.family for section in lexicon.sections}
    findings = fluff.analyse(document, lexicon_file)

    by_paragraph: dict[str, list[Sentence]] = {}
    for sentence in document.sentences:
        by_paragraph.setdefault(sentence.paragraph_id, []).append(sentence)

    baseline = _rhythm_baseline(document)
    numbered = _paragraph_index(document)

    passages = [
        _audit_paragraph(
            document=document,
            paragraph=paragraph,
            sentences=by_paragraph.get(paragraph.id, []),
            findings=findings,
            families=families,
            claims=claims,
            baseline=baseline,
            index=numbered[paragraph.id],
        )
        for paragraph in document.paragraphs
    ]

    profiled = voice.extract(document, lexicon_file)
    return TraceReport(
        passages=tuple(item for item in passages if item is not None)
        + _audit_sections(document, profiled),
        gaps=tuple(gaps),
        sections_profiled=len(profiled.sections),
    )


def _rhythm_baseline(document: Document) -> float | None:
    """How much this paper's sentence lengths vary, or None if it is too short.

    Returning None rather than a default is the point. A short draft gives
    nothing to compare a paragraph against, and a fixed number in that position
    would be a claim about writing in general rather than about this paper.
    """
    lengths = [len(sentence.text.split()) for sentence in document.sentences]
    if len(lengths) < RHYTHM_BASELINE_SENTENCES:
        return None
    return float(statistics.pstdev(lengths))


def _audit_paragraph(
    document: Document,
    paragraph: Paragraph,
    sentences: list[Sentence],
    findings: list[Finding],
    families: dict[str, str],
    claims: list[dict[str, Any]],
    baseline: float | None,
    index: int,
) -> Passage | None:
    if not sentences:
        return None

    ids = {sentence.id for sentence in sentences}
    mine = [finding for finding in findings if finding.span_id in ids]

    content: list[Signal] = []
    content += _unsupported_claims(sentences, claims)
    content += _ungrounded_assertions(document, sentences)

    filler = [
        finding.matched_text for finding in mine if families.get(finding.rule) in FILLER_FAMILIES
    ]
    if len(filler) >= FILLER_RUN:
        content.append(_filler(filler))

    for sentence in sentences:
        hedges = [
            finding
            for finding in mine
            if finding.span_id == sentence.id and families.get(finding.rule) == HEDGE_FAMILY
        ]
        if len(hedges) >= STACKED_HEDGES:
            content.append(_hedge_stack(len(hedges), _quote(sentence.text, 110)))

    structural: dict[str, list[str]] = {}
    for finding in mine:
        if finding.rule in STRUCTURAL_SIGNALS:
            structural.setdefault(finding.rule, []).append(finding.matched_text)
    content += [_structural(rule, matches) for rule, matches in sorted(structural.items())]

    texture: list[Signal] = []
    lengths = [len(sentence.text.split()) for sentence in sentences]
    if baseline is not None and len(sentences) >= RHYTHM_SENTENCES:
        spread = statistics.pstdev(lengths)
        if spread < baseline * UNIFORM_SHARE:
            texture.append(_uniform_rhythm(spread, baseline, len(sentences)))

    shaped = [finding for finding in mine if finding.rule in TEXTURE_RULES]
    if shaped:
        texture.append(_shape(len(shaped)))

    if not content and not texture:
        return None

    where = _where(document, paragraph, index)
    quote = _quote(document.text_of(paragraph.span))

    if not content:
        return Passage(
            where=where,
            span_id=paragraph.id,
            char_range=(paragraph.span.char_start, paragraph.span.char_end),
            quote=quote,
            signals=tuple(texture),
            standing=Standing.LEAVE,
            reason=_leave_reason(document, paragraph),
        )

    return Passage(
        where=where,
        span_id=paragraph.id,
        char_range=(paragraph.span.char_start, paragraph.span.char_end),
        quote=quote,
        signals=tuple(content + texture),
        standing=Standing.FIX,
        reason=(
            "Flagged on the content signals above. The texture, if any is listed, is "
            "recorded because it is there and is not a reason to change anything."
        ),
    )


def _leave_reason(document: Document, paragraph: Paragraph) -> str:
    if _is_method(document, paragraph.section_id):
        return (
            "Likely a false positive, and worth leaving. This is a methods section, "
            "and methods prose is uniform because the method is a list of steps. This "
            "is the passage detectors get wrong most often on a technical paper, and "
            "mangling a correctly written method to break up its rhythm makes the "
            "paper worse."
        )
    return (
        "Likely a false positive, and worth leaving. Only texture fired here: rhythm "
        "and shape, which a careful writer can have naturally and which detectors get "
        "wrong most often on writers whose first language is not English. Nothing here "
        "is a reason to change a sentence."
    )


def _audit_sections(document: Document, profiled: voice.VoiceReport) -> tuple[Passage, ...]:
    """The internal voice-consistency check, section by section."""
    profiles = list(profiled.sections)
    if len(profiles) < SECTIONS_FOR_DEVIATION:
        return ()

    spreads = _section_spreads(profiles)
    found: list[Passage] = []
    for profile in profiles:
        signals = _deviation_signals(profile, profiled.whole_paper, spreads)
        if not signals:
            continue
        section: Section = document.section(profile.scope)
        found.append(
            Passage(
                where=f"{section.title} (whole section)",
                span_id=section.id,
                char_range=(section.span.char_start, section.span.char_end),
                quote=_quote(document.text_of(section.heading_span)),
                signals=tuple(signals),
                standing=Standing.REVIEW,
                reason=(
                    "A voice that departs from the rest of the paper is copied, drafted "
                    "elsewhere, or written by a coauthor. Which one it is, is a question "
                    "for you: the tool reports the inconsistency and does not guess."
                ),
            )
        )
    return tuple(found)


# Rendering ------------------------------------------------------------------


def to_markdown(report: TraceReport) -> str:
    lines = [
        "# Passages that may read as machine-written",
        "",
        "Causes, not a score. Nothing here was checked against a detection service,",
        "and every fix below is a change that improves the paper on its own terms.",
        "If a change would only make the text look less machine-written, it is not",
        "offered. See docs/INTEGRITY.md.",
        "",
        f"**Flagged:** {len(report.flagged)}. "
        f"**Looked at and left alone:** {len(report.left_alone)}.",
        "",
    ]

    if report.flagged:
        lines += ["## Flagged", ""]
        for passage in report.flagged:
            lines += [
                f"### {passage.where}",
                "",
                f"> {passage.quote}",
                "",
                f"*{passage.standing!s}: {passage.summary}*",
                "",
            ]
            for signal in passage.signals:
                lines += [
                    f"- **{signal.id.replace('_', ' ')}.** {signal.evidence}",
                    f"  - Why this reads as generated: {signal.why}",
                    f"  - What to do: {signal.fix}",
                ]
            lines += ["", passage.reason, "", f"`{passage.span_id}`", ""]

    if report.left_alone:
        lines += [
            "## Looked at, left alone",
            "",
            "These tripped a texture signal and nothing else. A detector might dislike",
            "them. That is not a reason to change writing that is doing its job.",
            "",
        ]
        for passage in report.left_alone:
            lines += [f"### {passage.where}", ""]
            lines += [f"- {signal.evidence}" for signal in passage.signals]
            lines += ["", passage.reason, ""]

    if not report.passages:
        lines += [
            "No passage carried a content-level signal, and no section's voice",
            "departed from the paper's. That is a statement about the checks that",
            "ran, not a verdict on the paper.",
            "",
        ]

    lines += ["## Not checked", ""]
    lines += [f"- {gap}" for gap in report.gaps] or ["- Nothing was skipped."]
    lines.append("")
    return "\n".join(lines)
