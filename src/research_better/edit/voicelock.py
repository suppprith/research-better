"""The constraints that keep produced text from reading as machine written.

Every rule here runs after a change has been proposed and rejects it, rather
than being handed to a generator beforehand as an instruction. That ordering is
the whole design. An instruction is a preference: a model asked to preserve the
author's vocabulary will mostly do it, and the one time it does not is the one
time a reviewer notices. A validation step is a guarantee, and it holds even
when the model would rather write something nicer.

The strongest single rule is the vocabulary check. The loudest tell of a machine
edit is a synonym the author never used: a draft that says "model" forty times
and suddenly says "framework" once reads wrong to a human before they can say
why. So a proposal may only use words already in the draft or in a source it
cites, and the voice profile records exact surface forms rather than lemmas for
exactly this reason.

Every rejection names the rule that fired. A constraint nobody can inspect is
indistinguishable from a tool that felt like saying no.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from research_better.edit.ledger import Category, Edit, apply_to
from research_better.errors import ResearchBetterError
from research_better.model import Document, Paragraph, Sentence
from research_better.voice import (
    CONNECTIVES,
    PASSIVE,
    SPELLING_PAIRS,
    STOPWORDS,
    WORD,
    person,
)

Rejection = tuple[str, str]
"""(rule, note). The rule is what fired, the note is what an author reads."""


class WordBudgetError(ResearchBetterError):
    """The assembled result is longer than what the author wrote."""

    def __init__(self, original: int, edited: int) -> None:
        self.original = original
        self.edited = edited
        super().__init__(
            f"The edited draft would be {edited} words against the original {original}. "
            f"This tool cuts and tightens, so growing the paper means something "
            f"proposed text that was not in it. Nothing was written."
        )


def _words(text: str) -> list[str]:
    return WORD.findall(text)


def _content_words(text: str) -> set[str]:
    """Lower-cased, function words removed.

    Case is folded here and only here. A cut that removes a sentence's opening
    filler recases the word behind it, and that word is the author's own. The
    rules that do care about surface form, spelling and hyphenation, check it
    themselves.
    """
    return {word.lower() for word in _words(text)} - STOPWORDS


def produces_text(edit: Edit) -> bool:
    """Whether a row puts words on the page that were not already there.

    The line the texture rules are scoped by, and it follows from what those
    rules are for: they exist to keep produced text from reading as machine
    written. A deletion produces nothing. It cannot introduce a synonym, a
    connective the author does not reach for, or a voice that is not theirs. It
    can only leave a sentence the wrong length, which the length rule checks on
    every row.

    Without this scoping the passive-ratio rule refuses every paragraph
    deletion, because a deleted paragraph has no passives left in it, and the
    person rule refuses any cut that removes the last "we" from a paragraph
    even when that "we" was sitting inside the filler being cut.
    """
    return bool(_content_words(edit.proposed) - _content_words(edit.original))


@dataclass(frozen=True, slots=True)
class VoiceLock:
    """The author's own writing, as a set of things an edit may not do."""

    document: Document
    whole_paper: dict[str, Any]
    sections: dict[str, dict[str, Any]]
    vocabulary: frozenset[str]

    @classmethod
    def of(
        cls,
        document: Document,
        voice_payload: Any,
        source_vocabulary: frozenset[str] = frozenset(),
    ) -> VoiceLock:
        """Build from the voice artifact as it was written to disk.

        From the payload rather than by rerunning the pass, for the same reason
        the evidence gate reads payloads: the constraint has to be the one that
        was recorded, not the one the tool would compute if asked again.

        `source_vocabulary` is the words of the works this paper cites. It is
        empty until full-text retrieval feeds it, and empty is the strict
        setting: a proposal may then only use words already in the draft.
        """
        payload = voice_payload if isinstance(voice_payload, dict) else {}
        return cls(
            document=document,
            whole_paper=payload.get("whole_paper") or {},
            sections={
                profile["scope"]: profile
                for profile in payload.get("sections") or ()
                if "scope" in profile
            },
            vocabulary=frozenset(_content_words(document.source_text)) | source_vocabulary,
        )

    # Context ---------------------------------------------------------------

    def profile_for(self, section_id: str | None) -> dict[str, Any]:
        if section_id and section_id in self.sections:
            return self.sections[section_id]
        return self.whole_paper

    def _sentence(self, edit: Edit) -> Sentence | None:
        return self.document.sentence_at(edit.char_range[0])

    def _paragraph(self, edit: Edit) -> Paragraph | None:
        start, end = edit.char_range
        for paragraph in self.document.paragraphs:
            if paragraph.span.char_start <= start and end <= paragraph.span.char_end:
                return paragraph
        return None

    def _rewritten(self, span_start: int, span_end: int, edit: Edit) -> str:
        original = self.document.source_text[span_start:span_end]
        start, end = edit.char_range
        return original[: start - span_start] + edit.proposed + original[end - span_start :]

    # Rules -----------------------------------------------------------------

    def _new_content_word(self, edit: Edit) -> Rejection | None:
        introduced = sorted(_content_words(edit.proposed) - self.vocabulary)
        if not introduced:
            return None
        return (
            "voice_new_content_word",
            f"Would introduce {', '.join(repr(word) for word in introduced)}, which appears "
            f"nowhere in the draft and in no source it cites. A synonym the author never "
            f"used is the loudest tell of a machine edit.",
        )

    def _sentence_length(self, edit: Edit) -> Rejection | None:
        sentence = self._sentence(edit)
        if sentence is None:
            return None
        # An edit spanning a whole sentence or more is a cut of the sentence,
        # not a reshaping of it, and there is no resulting sentence to measure.
        if not (
            sentence.span.char_start <= edit.char_range[0]
            and edit.char_range[1] < sentence.span.char_end
        ):
            return None

        lengths = self.profile_for(sentence.section_id).get("sentence_lengths") or {}
        low, high = lengths.get("p10"), lengths.get("p90")
        if not low or not high:
            return None

        before = _outside(len(sentence.text.split()), low, high)
        rewritten = self._rewritten(sentence.span.char_start, sentence.span.char_end, edit)
        after = _outside(len(rewritten.split()), low, high)

        # A sentence already outside the band may be edited toward it. Refusing
        # that would freeze the author's outliers in place, and an outlier is
        # often exactly what needed the work.
        if after == 0 or after <= before:
            return None
        return (
            "voice_sentence_length",
            f"Would leave a {len(rewritten.split())}-word sentence, further outside the "
            f"{low:.0f} to {high:.0f} word band this author writes in for this section.",
        )

    def _person_or_voice(self, edit: Edit) -> Rejection | None:
        paragraph = self._paragraph(edit)
        if paragraph is None or not produces_text(edit):
            return None
        before = self.document.text_of(paragraph.span)
        after = self._rewritten(paragraph.span.char_start, paragraph.span.char_end, edit)

        if person(before) != person(after):
            return (
                "voice_person_shift",
                f"Would move the paragraph from {person(before)} to {person(after)}. "
                f"Whether a paper says we or says nothing is a decision the author "
                f"made once, across the whole paper.",
            )
        if len(PASSIVE.findall(before)) != len(PASSIVE.findall(after)):
            return (
                "voice_ratio_shift",
                "Would change how much of the paragraph is in the passive. That texture "
                "is the author's, and a change to it reads as somebody else writing.",
            )
        return None

    def _unfamiliar_connective(self, edit: Edit) -> Rejection | None:
        if not produces_text(edit):
            return None
        used = {word for word, count in self.whole_paper.get("connectives") or () if count}
        introduced = sorted(
            word
            for word in CONNECTIVES
            if word in edit.proposed.lower() and word not in used and word not in edit.original
        )
        if not introduced:
            return None
        return (
            "voice_unfamiliar_connective",
            f"Would introduce {', '.join(introduced)}, which this author does not use. "
            f"Connectives are habit, and a new one shows.",
        )

    def _spelling(self, edit: Edit) -> Rejection | None:
        convention = self.whole_paper.get("spelling")
        if convention not in {"british", "american"}:
            return None
        wrong = {pair[1] if convention == "british" else pair[0] for pair in SPELLING_PAIRS}
        introduced = sorted({word.lower() for word in _words(edit.proposed)} & wrong)
        if not introduced:
            return None
        return (
            "voice_spelling_shift",
            f"Would write {', '.join(introduced)} in a draft that is otherwise "
            f"{convention}. Mixed spelling is the kind of thing a copy editor charges for.",
        )

    def _hyphenation(self, edit: Edit) -> Rejection | None:
        preferred = {key: form for key, form in self.whole_paper.get("hyphenation") or ()}
        if not preferred:
            return None

        for word in _words(edit.proposed):
            key = word.lower().replace("-", "").replace(" ", "")
            settled = preferred.get(key)
            if settled and settled.lower() != word.lower():
                return (
                    "voice_hyphenation_shift",
                    f"Would write {word!r} where this draft has settled on {settled!r}. "
                    f"One compound spelled two ways is what a reviewer notices first.",
                )
        return None

    RULES = (
        _spelling,
        _hyphenation,
        _unfamiliar_connective,
        _new_content_word,
        _person_or_voice,
        _sentence_length,
    )
    """Most specific diagnosis first.

    A proposal writing "analyze" in a British draft breaks the vocabulary rule
    too, because that spelling is nowhere in the paper. Told only that, the
    author learns nothing they can act on. Told it flipped their spelling
    convention, they know exactly what happened. Same for a hyphenation habit
    and for a connective they do not use."""

    def __call__(self, edit: Edit) -> Rejection | None:
        """The first rule that fires, or nothing.

        First rather than all of them. An author reading why a change was not
        offered wants the reason, and a list of six is a way of saying nothing.
        """
        for rule in self.RULES:
            rejection = rule(self, edit)
            if rejection is not None:
                return rejection
        return None


def _outside(length: int, low: float, high: float) -> float:
    """How far a sentence length sits outside the author's band. Zero inside."""
    return max(0.0, low - length, length - high)


# Word budget ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Budget:
    """A hard ceiling on the assembled result, and a target for the run.

    The ceiling and the target are different things and are treated
    differently. Growing the paper means text was proposed that the author did
    not write, so that fails. Falling short of a reduction target means the
    evidence did not support more cutting than it did, which is a fact about the
    draft and is reported rather than enforced.
    """

    original_words: int
    target_reduction: float = 0.0

    @classmethod
    def of(cls, document: Document, target_reduction: float = 0.0) -> Budget:
        return cls(len(document.source_text.split()), target_reduction)

    @property
    def target_words(self) -> int:
        return int(self.original_words * (1 - self.target_reduction))

    def check(self, edited: str) -> int:
        """Word count of the result, or a refusal if it grew."""
        words = len(edited.split())
        if words > self.original_words:
            raise WordBudgetError(self.original_words, words)
        return words

    def shortfall(self, words: int) -> str:
        """One line on the target, said plainly, never as a pass or a fail."""
        if self.target_reduction <= 0:
            return f"{self.original_words} words to {words}, {words - self.original_words:+d}."
        if words <= self.target_words:
            return (
                f"{self.original_words} words to {words}, meeting the "
                f"{self.target_reduction:.0%} target."
            )
        return (
            f"{self.original_words} words to {words}. The {self.target_reduction:.0%} target "
            f"was {self.target_words}. The evidence gathered did not support cutting further, "
            f"which is a fact about this draft and not a failure of the run."
        )


def assemble(document: Document, edits: list[Edit], target_reduction: float = 0.0) -> str:
    """Apply the whole ledger and hold the result to the budget.

    The ceiling is checked on the assembled document rather than edit by edit,
    because a `GROUND` row that attaches a citation is allowed to add words and
    the paper as a whole still may not grow.
    """
    budget = Budget.of(document, target_reduction)
    result = apply_to(document.source_text, edits)
    budget.check(result)
    return result


def within_budget(edit: Edit) -> bool:
    """Whether one row may add words on its own.

    Only `GROUND` may, and only because attaching a verified citation to a claim
    that lacked one is worth the four words it costs.
    """
    return edit.category is Category.GROUND or edit.words_delta <= 0


def screen(lock: VoiceLock) -> Callable[[Edit], Rejection | None]:
    """The per-row check the ledger runs: budget first, then the voice rules.

    Budget first because it is arithmetic and the voice rules are judgement. A
    row that makes the paper longer is out whatever else is true of it.
    """

    def check(edit: Edit) -> Rejection | None:
        if not within_budget(edit):
            return (
                "word_budget",
                f"Would add {edit.words_delta} words. Only a row attaching a verified "
                f"citation is allowed to grow the paper.",
            )
        return lock(edit)

    return check
