"""Dictionary-driven fluff detection.

No model call anywhere in this file. That is the point: a finding here is
reproducible, and two people can argue about whether a term belongs in the
lexicon rather than about whether the tool feels right today.

Every matcher works on a whitespace-normalized view of a sentence and maps its
hits back to real source offsets, because a paragraph wrapped at 80 columns
puts line breaks in the middle of the phrases being matched.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from research_better.findings import Finding, Severity, Suggestion
from research_better.lexicon import Lexicon, RuleSection, Term, load_lexicon
from research_better.model import Document, Sentence

Sections = tuple[RuleSection, ...]
Matcher = Callable[[Document, Sections, dict[str, "_Flat"]], list[Finding]]

CLAUSE_BREAK = re.compile(r"[,;:]|\bbut\b|\bthough\b|\balthough\b|\bwhereas\b|\bwhile\b")
WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
STATISTIC = re.compile(r"\d")

MODEL_VOCABULARY_REPEAT_THRESHOLD = 3
"""At or above this document-wide count, an overused word stops looking like a
coincidence and the finding is raised from low to medium. It is never raised to
high, because no deletion of one of these words is safe without a rewrite."""


@dataclass(frozen=True, slots=True)
class _Flat:
    """A sentence with whitespace collapsed, and a map back to real offsets."""

    text: str
    offsets: tuple[int, ...]

    @classmethod
    def of(cls, sentence: Sentence) -> _Flat:
        characters: list[str] = []
        offsets: list[int] = []
        previous_was_space = False
        for index, character in enumerate(sentence.text):
            if character.isspace():
                if previous_was_space or not characters:
                    continue
                characters.append(" ")
                offsets.append(sentence.span.char_start + index)
                previous_was_space = True
                continue
            characters.append(character)
            offsets.append(sentence.span.char_start + index)
            previous_was_space = False
        while characters and characters[-1] == " ":
            characters.pop()
            offsets.pop()
        return cls("".join(characters), tuple(offsets))

    def source_range(self, start: int, end: int) -> tuple[int, int]:
        """Map a range in the flattened text back to source character offsets."""
        if not self.offsets:
            return (0, 0)
        first = self.offsets[start]
        last = self.offsets[min(end, len(self.offsets)) - 1]
        return (first, last + 1)


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Match a phrase on word boundaries, tolerant of any whitespace inside it."""
    parts = [re.escape(part) for part in phrase.split()]
    body = r"\s+".join(parts)
    leading = r"\b" if phrase[:1].isalnum() else ""
    trailing = r"\b" if phrase[-1:].isalnum() else ""
    return re.compile(leading + body + trailing, re.IGNORECASE)


def _hits(flat: _Flat, term: Term) -> Iterator[tuple[int, int, str]]:
    for match in _phrase_pattern(term.phrase).finditer(flat.text):
        yield match.start(), match.end(), match.group(0)


DELETIONS = {Suggestion.DELETE, Suggestion.DELETE_CLAUSE}


def _expand_for_deletion(flat: _Flat, start: int, end: int) -> tuple[int, int]:
    """Widen a range so cutting it leaves clean text.

    Deleting exactly the matched words leaves a double space, or a sentence
    opening with a comma. The range takes the separator that follows, or the
    space in front when the match runs up against a full stop.

    Recapitalizing a sentence whose opener was cut is the edit pass's job. It
    owns writeback and is the only layer that knows a span starts a sentence.
    """
    trailing = re.match(r"[,;]?\s+", flat.text[end:])
    if trailing:
        return start, end + trailing.end()
    leading = re.search(r"\s+$", flat.text[:start])
    if leading:
        return leading.start(), end
    return start, end


def _finding(
    sentence: Sentence,
    flat: _Flat,
    section: RuleSection,
    term: Term,
    start: int,
    end: int,
    matched: str,
    severity: Severity | None = None,
    suggestion: Suggestion | None = None,
) -> Finding:
    action = suggestion or section.suggestion_for(term)
    cut_start, cut_end = (
        _expand_for_deletion(flat, start, end) if action in DELETIONS else (start, end)
    )
    return Finding(
        span_id=sentence.id,
        rule=section.id,
        severity=severity or section.severity,
        matched_text=matched,
        char_range=flat.source_range(cut_start, cut_end),
        suggestion=action,
        replacement=term.replacement,
        note=section.note,
    )


# Matchers -----------------------------------------------------------------


def _match_plain(document: Document, sections: Sections, flats: dict[str, _Flat]) -> list[Finding]:
    """Every occurrence is a finding. Used where context does not change the call."""
    findings: list[Finding] = []
    for sentence in document.sentences:
        flat = flats[sentence.id]
        for section in sections:
            for term in section.terms:
                for start, end, matched in _hits(flat, term):
                    findings.append(_finding(sentence, flat, section, term, start, end, matched))
    return findings


def _match_empty_intensifier(
    document: Document, sections: Sections, flats: dict[str, _Flat]
) -> list[Finding]:
    findings: list[Finding] = []
    for sentence in document.sentences:
        flat = flats[sentence.id]
        # A sentence carrying a number is reporting a measurement, and an
        # intensifier next to a measurement is usually the author's voice
        # rather than padding.
        if STATISTIC.search(flat.text):
            continue
        for section in sections:
            for term in section.terms:
                for start, end, matched in _hits(flat, term):
                    if WORD.match(flat.text, end + 1) is None:
                        continue
                    findings.append(_finding(sentence, flat, section, term, start, end, matched))
    return findings


def _match_hedge_stack(
    document: Document, sections: Sections, flats: dict[str, _Flat]
) -> list[Finding]:
    """Flag the second and later hedge in a clause, never the first.

    One hedge is normal and often the correct thing to write. The finding is
    the pile-up, so the fix keeps the author's first hedge and their caution.

    Which hedge is reported matters as much as how many. Deleting an adverb
    leaves a grammatical sentence, so those are actionable. Deleting a modal or
    a hedging verb leaves wreckage, so those go to the human even though they
    count toward the stack. The counting spans both lists, which is why this
    matcher takes every section in its family at once.
    """
    findings: list[Finding] = []
    for sentence in document.sentences:
        flat = flats[sentence.id]
        for clause_start, clause_end in _clauses(flat.text):
            hits: list[tuple[int, int, str, Term, RuleSection]] = []
            for section in sections:
                for term in section.terms:
                    for start, end, matched in _hits(flat, term):
                        if clause_start <= start < clause_end:
                            hits.append((start, end, matched, term, section))
            for start, end, matched, term, section in _drop_overlaps(hits)[1:]:
                findings.append(_finding(sentence, flat, section, term, start, end, matched))
    return findings


def _match_model_vocabulary(
    document: Document, sections: Sections, flats: dict[str, _Flat]
) -> list[Finding]:
    """Frequency weighted rather than banned.

    Some of these words are correct in context, so a single use is noted and
    nothing more. Repetition across a paper is the signal.
    """
    counts: Counter[str] = Counter()
    located: list[tuple[Sentence, _Flat, RuleSection, Term, int, int, str]] = []

    for sentence in document.sentences:
        flat = flats[sentence.id]
        for section in sections:
            for term in section.terms:
                for start, end, matched in _hits(flat, term):
                    counts[term.phrase.lower()] += 1
                    located.append((sentence, flat, section, term, start, end, matched))

    return [
        _finding(
            sentence,
            flat,
            section,
            term,
            start,
            end,
            matched,
            severity=(
                Severity.MEDIUM
                if counts[term.phrase.lower()] >= MODEL_VOCABULARY_REPEAT_THRESHOLD
                else Severity.LOW
            ),
        )
        for sentence, flat, section, term, start, end, matched in located
    ]


def _match_citation_free_superlative(
    document: Document, sections: Sections, flats: dict[str, _Flat]
) -> list[Finding]:
    """Only fires where the claim has nothing behind it.

    A superlative next to a citation or a reported number is a claim the author
    can defend. The same word alone in a sentence is the one a reviewer circles.
    """
    findings: list[Finding] = []
    for sentence in document.sentences:
        flat = flats[sentence.id]
        if STATISTIC.search(flat.text) or document.citations_in_sentence(sentence.id):
            continue
        for section in sections:
            for term in section.terms:
                for start, end, matched in _hits(flat, term):
                    findings.append(_finding(sentence, flat, section, term, start, end, matched))
    return findings


def _match_throat_clearing(
    document: Document, sections: Sections, flats: dict[str, _Flat]
) -> list[Finding]:
    """Only a run counts. One transition word is not a defect."""
    hits: list[tuple[int, Sentence, RuleSection, Term, int, int, str]] = []

    for position, sentence in _paragraph_openers(document):
        flat = flats[sentence.id]
        for section in sections:
            for term in section.terms:
                match = _phrase_pattern(term.phrase).match(flat.text)
                if match:
                    hits.append(
                        (
                            position,
                            sentence,
                            section,
                            term,
                            match.start(),
                            match.end(),
                            match.group(0),
                        )
                    )
                    break

    in_a_run = set().union(*_consecutive_runs([hit[0] for hit in hits], minimum=3)) or set()
    return [
        _finding(sentence, flats[sentence.id], section, term, start, end, matched)
        for position, sentence, section, term, start, end, matched in hits
        if position in in_a_run
    ]


MATCHERS: dict[str, Matcher] = {
    "filler_opener": _match_plain,
    "nominalization": _match_plain,
    "empty_intensifier": _match_empty_intensifier,
    "hedge_stack": _match_hedge_stack,
    "model_vocabulary": _match_model_vocabulary,
    "citation_free_superlative": _match_citation_free_superlative,
    "throat_clearing": _match_throat_clearing,
}


# Helpers ------------------------------------------------------------------


def _clauses(text: str) -> list[tuple[int, int]]:
    bounds: list[tuple[int, int]] = []
    cursor = 0
    for separator in CLAUSE_BREAK.finditer(text):
        if separator.start() > cursor:
            bounds.append((cursor, separator.start()))
        cursor = separator.end()
    if cursor < len(text):
        bounds.append((cursor, len(text)))
    return bounds


def _drop_overlaps(
    hits: list[tuple[int, int, str, Term, RuleSection]],
) -> list[tuple[int, int, str, Term, RuleSection]]:
    """Keep the longest match at each position, in document order.

    `tends to` and `tend` would both match the same text, and counting it twice
    would turn one hedge into a stack.
    """
    kept: list[tuple[int, int, str, Term, RuleSection]] = []
    for hit in sorted(hits, key=lambda h: (h[0], -(h[1] - h[0]))):
        if kept and hit[0] < kept[-1][1]:
            continue
        kept.append(hit)
    return kept


def _paragraph_openers(document: Document) -> list[tuple[int, Sentence]]:
    """The first sentence of each paragraph, numbered in document order."""
    first_by_paragraph: dict[str, Sentence] = {}
    for sentence in document.sentences:
        first_by_paragraph.setdefault(sentence.paragraph_id, sentence)
    ordered = [p.id for p in document.paragraphs if p.id in first_by_paragraph]
    return [(position, first_by_paragraph[pid]) for position, pid in enumerate(ordered)]


def _consecutive_runs(positions: list[int], minimum: int) -> list[set[int]]:
    runs: list[set[int]] = []
    current: list[int] = []
    for position in sorted(positions):
        if current and position == current[-1] + 1:
            current.append(position)
        else:
            if len(current) >= minimum:
                runs.append(set(current))
            current = [position]
    if len(current) >= minimum:
        runs.append(set(current))
    return runs


def analyse_lexical(document: Document, lexicon_file: Path | None = None) -> list[Finding]:
    """Run every lexical rule family over a document."""
    lexicon: Lexicon = load_lexicon(lexicon_file)
    flats = {sentence.id: _Flat.of(sentence) for sentence in document.sentences}

    findings: list[Finding] = []
    for family, matcher in MATCHERS.items():
        sections = lexicon.family(family)
        if sections:
            findings.extend(matcher(document, sections, flats))
    return findings
