"""Does the cited work actually say what it is cited for.

A citation can resolve perfectly and still not support the sentence it is
attached to. Overclaiming a real source is the most common citation error in
practice, far more common than inventing one, and it is invisible to every
reference manager.

`PARTIAL` is the verdict this module exists for. A source that supports a
weaker version of the claim is the interesting case, so the output always
includes what the source actually says, quoted rather than paraphrased. The
point is that the author can check, and a paraphrase would just be the tool's
opinion wearing the source's clothes.

The matching is lexical. There is no embedding model and no judgment step here,
so this finds claims whose wording overlaps the source and misses claims that
are supported in different words. That is a real limit and the verdicts are
worded to survive it: a low-overlap result never comes back as `UNSUPPORTED`
unless the full text was actually read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from research_better.grounding.fulltext import ABSTRACT, SourceText
from research_better.model import Document, Sentence
from research_better.segmentation import split_sentences

WORD = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")
NUMBER = re.compile(r"\d+(?:\.\d+)?")

CITATION_MARKER = re.compile(r"\[[^\]]{1,60}\]|\\cite[a-z]*\s*(?:\[[^\]]*\])?\{[^}]*\}")
"""Citation markers are not part of the claim. Leaving `[8]` in the text makes
the number 8 look like a quantity the source has to establish, and every cited
sentence comes back as an overclaim."""


def strip_citations(text: str) -> str:
    return " ".join(CITATION_MARKER.sub(" ", text).split())


SUPPORT_COVERAGE = 0.70
"""Share of the claim's content words a passage must carry to count as saying
the same thing."""

PARTIAL_COVERAGE = 0.40
"""Below this the passage is about something else. Between the two, the source
is on topic without carrying the whole claim."""

MAXIMUM_QUOTE_WORDS = 60
"""Quote enough to show support and no more. The quote exists so the author can
check, not so the tool can reproduce the source."""

# Words that raise a claim above what a passage merely on the same topic
# supports. A source can be about hierarchical indexing without establishing
# that it works at billion-document scale.
# Annotated rather than inferred because another module imports them, and an
# import cycle leaves the checker unable to infer a name it has not reached yet.
UNIVERSALS: frozenset[str] = frozenset(
    """
    all every any always never none no entirely fully completely universally
    invariably guaranteed proves proof optimal exact
    """.split()
)

SUPERLATIVES: frozenset[str] = frozenset(
    """
    best first only novel unprecedented state-of-the-art fastest highest lowest
    largest smallest strongest outperforms significantly substantially
    dramatically
    """.split()
)

MAGNITUDES = frozenset(
    """
    hundred thousand million billion trillion
    """.split()
)
"""A claimed scale has to appear in the passage that supports it.

Word overlap alone cannot tell "recovers the exhaustive score at a billion
documents" from "recovers it at a 500K-document configuration", because the two
share almost every content word. The magnitude is the whole difference, and it
is exactly the kind of overclaim this pass exists to find."""

DEFERRAL_CUES = (
    "not yet",
    "remains open",
    "remain open",
    "future work",
    "we leave",
    "left to future",
    "is not established",
    "untested",
    "we do not",
    "does not hold",
    "no evidence",
    "remains unclear",
    "is an open question",
)
"""Phrases that turn a passage from support into a caveat.

The overclaim in the fixture matches its source on almost every word, and the
source's sentence ends "though not yet at billion scale". Word overlap cannot
see a negation, so a passage carrying one of these can never come back as
support. It becomes PARTIAL with the sentence quoted, and the author reads what
the source actually said."""

STOPWORDS = frozenset(
    """
    a an the and or but of in on at to for with by from as is are was were be
    been being it its this that these those we our us they their there here
    which who what when where why how can could may might will would should
    has have had do does did not than then so such more most other some
    """.split()
)


class Support(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    UNCHECKABLE = "UNCHECKABLE"


def content_words(text: str) -> set[str]:
    return {word.lower() for word in WORD.findall(strip_citations(text))} - STOPWORDS


def strength_markers(text: str) -> set[str]:
    """The parts of a claim that a merely on-topic passage does not establish."""
    lowered = strip_citations(text).lower()
    words = set(WORD.findall(lowered))
    markers = (words & UNIVERSALS) | (words & SUPERLATIVES) | (words & MAGNITUDES)
    return markers | set(NUMBER.findall(lowered))


def passages(text: str) -> list[tuple[str, str]]:
    """Split retrieved text into quotable units, labelled for the locator.

    Sentences, and adjacent pairs of sentences, rather than whole paragraphs.
    That granularity is the difference between a real check and a useless one.
    An abstract paragraph contains every word of several different assertions,
    so scoring against the paragraph says "the source is about this", and every
    claim on the topic comes back supported.

    The overclaim this exists to catch reads exactly that way: a source that
    recovers 0.9 of the exhaustive score at 500K documents, cited for doing it
    at a billion. Both facts live in the same paragraph and in no one sentence.
    """
    found: list[tuple[str, str]] = []
    for index, block in enumerate(part.strip() for part in text.split("\n\n")):
        if len(block.split()) < 8:
            continue
        sentences = [block[start:end] for start, end in split_sentences(block)]
        for position, sentence in enumerate(sentences):
            if len(sentence.split()) >= 5:
                found.append((f"block {index + 1}, sentence {position + 1}", sentence))
            # Adjacent pairs, so a claim carried across a sentence boundary is
            # still found without letting a whole paragraph count as one place.
            if position + 1 < len(sentences):
                pair = f"{sentence} {sentences[position + 1]}"
                found.append((f"block {index + 1}, sentences {position + 1}-{position + 2}", pair))
    return found


def coverage(claim: str, passage: str) -> float:
    wanted = content_words(claim)
    if not wanted:
        return 0.0
    return len(wanted & content_words(passage)) / len(wanted)


def trim_quote(passage: str, claim: str) -> str:
    """The window of the passage that carries the claim, capped in length."""
    words = passage.split()
    if len(words) <= MAXIMUM_QUOTE_WORDS:
        return passage

    wanted = content_words(claim)
    best_start, best_hits = 0, -1
    for start in range(0, max(1, len(words) - MAXIMUM_QUOTE_WORDS + 1), 10):
        window = words[start : start + MAXIMUM_QUOTE_WORDS]
        hits = len(wanted & content_words(" ".join(window)))
        if hits > best_hits:
            best_start, best_hits = start, hits

    window = words[best_start : best_start + MAXIMUM_QUOTE_WORDS]
    prefix = "" if best_start == 0 else "... "
    suffix = "" if best_start + MAXIMUM_QUOTE_WORDS >= len(words) else " ..."
    return f"{prefix}{' '.join(window)}{suffix}"


@dataclass(frozen=True, slots=True)
class ClaimCheck:
    span_id: str
    citation_key: str
    support: Support
    claim: str
    quote: str | None = None
    locator: str | None = None
    source_kind: str = "none"
    source_url: str | None = None
    coverage: float = 0.0
    unmet: tuple[str, ...] = ()
    note: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "citation_key": self.citation_key,
            "support": str(self.support),
            "claim": self.claim,
            "quote": self.quote,
            "locator": self.locator,
            "source_kind": self.source_kind,
            "source_url": self.source_url,
            "coverage": round(self.coverage, 3),
            "unmet": list(self.unmet),
            "note": self.note,
        }


def check_claim(sentence: Sentence, citation_key: str, source: SourceText) -> ClaimCheck:
    """Judge one claim against one retrieved source."""

    def build(
        support: Support,
        note: str,
        quote: str | None = None,
        locator: str | None = None,
        found: float = 0.0,
        unmet: tuple[str, ...] = (),
    ) -> ClaimCheck:
        return ClaimCheck(
            span_id=sentence.id,
            citation_key=citation_key,
            support=support,
            claim=" ".join(sentence.text.split()),
            quote=quote,
            locator=locator,
            source_kind=source.kind,
            source_url=source.url,
            coverage=found,
            unmet=unmet,
            note=note,
        )

    if not source.available:
        return build(
            Support.UNCHECKABLE,
            source.note or "No retrievable text for this source.",
        )

    best_where, best_passage, best_score = "", "", 0.0
    for where, passage in passages(source.text):
        score = coverage(sentence.text, passage)
        if score > best_score:
            best_where, best_passage, best_score = where, passage, score

    locator = f"{source.kind}, {best_where}" if best_passage else None
    quote = trim_quote(best_passage, sentence.text) if best_passage else None
    unmet = tuple(sorted(strength_markers(sentence.text) - strength_markers(best_passage)))
    deferrals = tuple(
        cue
        for cue in DEFERRAL_CUES
        if cue in best_passage.lower() and cue not in sentence.text.lower()
    )

    if best_score >= SUPPORT_COVERAGE and not unmet and not deferrals:
        return build(
            Support.SUPPORTED,
            "The source carries this claim.",
            quote=quote,
            locator=locator,
            found=best_score,
        )

    if best_score >= PARTIAL_COVERAGE or deferrals:
        if deferrals:
            reason = (
                f"The closest passage matches your wording but qualifies it: it says "
                f'"{deferrals[0]}". Read the quote. The source may be deferring '
                f"exactly what your sentence asserts."
            )
        else:
            missing = ", ".join(unmet) if unmet else "the strength of the claim"
            reason = (
                f"The source is about this, and the closest passage does not carry "
                f"{missing}. Read the quote and check whether your sentence claims "
                f"more than the source establishes."
            )
        return build(
            Support.PARTIAL,
            reason,
            quote=quote,
            locator=locator,
            found=best_score,
            unmet=unmet,
        )

    if source.kind == ABSTRACT:
        return build(
            Support.UNCHECKABLE,
            (
                "Only the abstract was retrievable and it does not discuss this. "
                "An abstract not mentioning something is no evidence the paper "
                "does not say it, so this was not checked rather than found wanting."
            ),
            found=best_score,
        )

    return build(
        Support.UNSUPPORTED,
        (
            "The full text was read and no passage overlaps this claim. Matching is "
            "lexical, so a claim supported in quite different words could be missed. "
            "Worth checking by hand before changing anything."
        ),
        quote=quote,
        locator=locator,
        found=best_score,
    )


@dataclass(frozen=True, slots=True)
class ClaimReport:
    checks: tuple[ClaimCheck, ...] = ()
    sources_with_full_text: int = 0
    sources_attempted: int = 0
    source_notes: dict[str, str] = field(default_factory=dict)

    def coverage_note(self) -> str:
        """How much of the bibliography could actually be inspected.

        A count, and no percentage beside it. The share was there once and
        labelled retrieval coverage, which did not help: a reader scanning a
        report sees a figure attached to their paper and reads it as a mark,
        whatever the words around it say. "1 of 6" cannot be read that way and
        carries the same fact.
        """
        if not self.sources_attempted:
            return "No cited work had a claim attached to it, so nothing was checked."
        return (
            f"{self.sources_with_full_text} of {self.sources_attempted} cited works had "
            f"retrievable full text. The rest were checked against an abstract or not at "
            f"all. Nothing here is a judgment of the paper."
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "checks": [check.to_json() for check in self.checks],
            "sources_with_full_text": self.sources_with_full_text,
            "sources_attempted": self.sources_attempted,
            "source_notes": dict(self.source_notes),
            "coverage_note": self.coverage_note(),
        }


def claims_with_citations(document: Document) -> list[tuple[Sentence, str]]:
    """Every sentence that carries a citation, paired with the key it cites."""
    pairs: list[tuple[Sentence, str]] = []
    for citation in document.citations:
        if citation.in_bibliography or not citation.sentence_id:
            continue
        sentence = next((s for s in document.sentences if s.id == citation.sentence_id), None)
        if sentence is not None:
            pairs.append((sentence, citation.key))
    return pairs
