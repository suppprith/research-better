"""Unattributed overlap between the draft and work it can actually read.

What this is not, stated first because the confusion is the whole risk: it is
not Turnitin and must never be presented as one. It compares the draft against
open-access full text that could be retrieved, and nothing else. It cannot see
paywalled work, most books, unindexed theses, or the web. A clean result means
"no overlap found in what could be checked", and every output path says so with
the number of sources actually compared.

No output here is a percentage that could be read as a total plagiarism score.
That phrasing is banned, and `coverage_note` reports counts.

The three checks are separated because their fixes are completely different:

* Verbatim text with a citation but no quote marks is the most common honest
  mistake in early-career writing, and the fix is two quotation marks. It gets
  its own verdict so it is never lumped in with unattributed copying.
* Verbatim text with no citation at all is the serious one.
* Overlap with the authors' own earlier work is a real integrity question that
  authors routinely do not realize applies to them, and some venues permit a
  degree of it. Separate verdict, separate severity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from research_better.findings import Finding, Severity, Suggestion, sort_findings
from research_better.grounding.fulltext import SourceText
from research_better.lexicon import Lexicon, load_lexicon
from research_better.model import Document, Sentence
from research_better.spans import normalize

SHINGLE_SIZE = 8
"""Words per shingle. Eight is long enough that an accidental collision on
ordinary English is rare and short enough to catch a lifted clause rather than
only a lifted paragraph."""

MINIMUM_MATCH_WORDS = 10
"""A contiguous run shorter than this is not worth an author's attention, even
when it is a genuine match."""

COMMON_WORD_CEILING = 0.75
"""A run made almost entirely of the commonest words in the language is a
coincidence of English, not evidence of anything."""

BOILERPLATE_LEXICON = "originality-boilerplate.md"

QUOTE_MARKS = ('"', "“", "”", "'", "‘", "’", "`")

WORD = re.compile(r"[a-z0-9]+")

# The hundred-odd words that carry no distinctiveness. A match made of these is
# a match on English itself.
COMMON = frozenset(
    """
    a an the and or but if of in on at to for with by from as is are was were be been
    being it its this that these those we our us you your they their there here which
    who what when where why how all any both each few more most other some such only own
    same so than then too very can could may might must will would should do does did
    have has had not no nor them he she his her i me my also into over under between
    during about after before above below up down out off again further once because
    while until although though whether
    """.split()
)


class Overlap(StrEnum):
    UNATTRIBUTED_OVERLAP = "UNATTRIBUTED_OVERLAP"
    NEEDS_QUOTE_MARKS = "NEEDS_QUOTE_MARKS"
    CLOSE_PARAPHRASE_UNCITED = "CLOSE_PARAPHRASE_UNCITED"
    SELF_OVERLAP = "SELF_OVERLAP"
    BOILERPLATE_IGNORED = "BOILERPLATE_IGNORED"


SEVERITY = {
    Overlap.UNATTRIBUTED_OVERLAP: Severity.HIGH,
    Overlap.CLOSE_PARAPHRASE_UNCITED: Severity.MEDIUM,
    # The fix is two quotation marks. Filing it with unattributed copying would
    # frighten an author over a typographic slip.
    Overlap.NEEDS_QUOTE_MARKS: Severity.MEDIUM,
    Overlap.SELF_OVERLAP: Severity.MEDIUM,
    Overlap.BOILERPLATE_IGNORED: Severity.LOW,
}


def words_of(text: str) -> list[str]:
    return WORD.findall(text.lower())


def shingles(words: list[str], size: int = SHINGLE_SIZE) -> dict[tuple[str, ...], int]:
    """Every overlapping window of `size` words, mapped to where it starts."""
    found: dict[tuple[str, ...], int] = {}
    for start in range(len(words) - size + 1):
        found.setdefault(tuple(words[start : start + size]), start)
    return found


def distinctiveness(words: list[str]) -> float:
    """How unusual a matched run is, from 0 for pure boilerplate to 1.

    A ten-word match on a rare phrase matters more than a fifteen-word match on
    common words, so this ranks the output rather than only its length.
    """
    if not words:
        return 0.0
    uncommon = sum(1 for word in words if word not in COMMON)
    return uncommon / len(words)


def load_boilerplate(path: Path | None = None) -> tuple[str, ...]:
    """Normalized boilerplate phrases, from the shipped whitelist."""
    lexicon: Lexicon = load_lexicon(
        path or _default_boilerplate_path(),
    )
    return tuple(
        normalize(term.phrase).lower() for section in lexicon.sections for term in section.terms
    )


def _default_boilerplate_path() -> Path:
    from importlib.resources import files

    return Path(str(files("research_better").joinpath("references", BOILERPLATE_LEXICON)))


def is_boilerplate(text: str, phrases: tuple[str, ...]) -> bool:
    flat = normalize(text).lower()
    return any(phrase in flat or flat in phrase for phrase in phrases)


@dataclass(frozen=True, slots=True)
class OverlapMatch:
    span_id: str
    verdict: Overlap
    matched_text: str
    length: int
    distinctiveness: float
    source_title: str | None = None
    source_doi: str | None = None
    source_locator: str | None = None
    char_range: tuple[int, int] = (0, 0)
    note: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "verdict": str(self.verdict),
            "matched_text": self.matched_text,
            "length": self.length,
            "distinctiveness": round(self.distinctiveness, 3),
            "source_title": self.source_title,
            "source_doi": self.source_doi,
            "source_locator": self.source_locator,
            "char_range": list(self.char_range),
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class OriginalityReport:
    matches: tuple[OverlapMatch, ...] = ()
    sources_compared: int = 0
    sources_with_full_text: int = 0
    sources_unavailable: int = 0
    boilerplate_ignored: int = 0
    unavailable_titles: tuple[str, ...] = field(default_factory=tuple)

    def coverage_note(self) -> str:
        """What was compared against, always, and never as a score.

        Counts rather than a percentage. A percentage here would be read as a
        similarity score no matter how it was labelled, and this tool cannot
        produce one honestly from a partial corpus.
        """
        # Saying "compared against 4 sources" when three of them were abstracts
        # would overstate what was actually read by a wide margin.
        abstracts = self.sources_compared - self.sources_with_full_text
        parts = [
            f"Compared against {self.sources_compared} source(s): "
            f"{self.sources_with_full_text} as full text and {abstracts} as abstract "
            f"only, which sees almost none of the paper"
        ]
        if self.sources_unavailable:
            parts.append(
                f"{self.sources_unavailable} cited source(s) could not be retrieved and "
                f"were not compared"
            )
        if self.boilerplate_ignored:
            parts.append(f"{self.boilerplate_ignored} standard-phrasing match(es) ignored")
        parts.append(
            "This is not a plagiarism service. It cannot see paywalled work, most "
            "books, unindexed theses, or the web. A clean result means no overlap was "
            "found in what could be checked, and nothing about what could not"
        )
        return ". ".join(parts) + "."

    def to_json(self) -> dict[str, Any]:
        return {
            "matches": [match.to_json() for match in self.matches],
            "sources_compared": self.sources_compared,
            "sources_with_full_text": self.sources_with_full_text,
            "sources_unavailable": self.sources_unavailable,
            "boilerplate_ignored": self.boilerplate_ignored,
            "unavailable_titles": list(self.unavailable_titles),
            "coverage_note": self.coverage_note(),
        }


def _longest_run(
    draft_words: list[str], source_shingles: dict[tuple[str, ...], int], start: int
) -> int:
    """How far a match starting at `start` continues, in words."""
    length = 0
    position = start
    while position + SHINGLE_SIZE <= len(draft_words):
        window = tuple(draft_words[position : position + SHINGLE_SIZE])
        if window not in source_shingles:
            break
        length = position + SHINGLE_SIZE - start
        position += 1
    return length


def _has_quote_marks(text: str) -> bool:
    return any(mark in text for mark in QUOTE_MARKS)


def compare_sentence(
    sentence: Sentence,
    cited_keys: set[str],
    source: SourceText,
    source_title: str | None,
    source_doi: str | None,
    phrases: tuple[str, ...],
    is_own_prior_work: bool = False,
) -> OverlapMatch | None:
    """Find the longest verbatim run this sentence shares with one source."""
    draft_words = words_of(sentence.text)
    if len(draft_words) < MINIMUM_MATCH_WORDS:
        return None

    source_shingles = shingles(words_of(source.text))
    best_start, best_length = 0, 0
    position = 0
    while position + SHINGLE_SIZE <= len(draft_words):
        run = _longest_run(draft_words, source_shingles, position)
        if run > best_length:
            best_start, best_length = position, run
        position += max(1, run) if run else 1

    if best_length < MINIMUM_MATCH_WORDS:
        return None

    matched = draft_words[best_start : best_start + best_length]
    matched_text = " ".join(matched)
    rarity = distinctiveness(matched)

    if is_boilerplate(matched_text, phrases) or rarity < (1 - COMMON_WORD_CEILING):
        return OverlapMatch(
            span_id=sentence.id,
            verdict=Overlap.BOILERPLATE_IGNORED,
            matched_text=matched_text,
            length=best_length,
            distinctiveness=rarity,
            source_title=source_title,
            source_doi=source_doi,
            char_range=(sentence.span.char_start, sentence.span.char_end),
            note=(
                "Matches standard phrasing that most papers in the field write the "
                "same way. Not reported as an overlap."
            ),
        )

    if is_own_prior_work:
        verdict = Overlap.SELF_OVERLAP
        note = (
            "This overlaps your own earlier work. Some venues accept a degree of "
            "methods reuse and some do not, and extending a conference paper into a "
            "journal version is where this usually happens. Check what your venue "
            "asks for and cite the earlier paper."
        )
    elif not cited_keys:
        verdict = Overlap.UNATTRIBUTED_OVERLAP
        note = (
            "This run of words appears in a published source and the sentence carries "
            "no citation. Quote it and cite it, or write it in your own words."
        )
    elif not _has_quote_marks(sentence.text):
        verdict = Overlap.NEEDS_QUOTE_MARKS
        note = (
            "The sentence cites a source and reproduces its wording without quotation "
            "marks. This is the most common honest mistake in academic writing and it "
            "is also the one that gets flagged as plagiarism. The fix is quotation "
            "marks around the borrowed words."
        )
    else:
        return None

    return OverlapMatch(
        span_id=sentence.id,
        verdict=verdict,
        matched_text=matched_text,
        length=best_length,
        distinctiveness=rarity,
        source_title=source_title,
        source_doi=source_doi,
        source_locator=source.url,
        char_range=(sentence.span.char_start, sentence.span.char_end),
        note=note,
    )


def analyse_originality(
    document: Document,
    sources: dict[str, tuple[SourceText, str | None, str | None]],
    own_prior_keys: set[str] | None = None,
    boilerplate: Path | None = None,
) -> OriginalityReport:
    """Compare every prose sentence against every source that could be read.

    `sources` maps a citation key to the text retrieved for it plus its title
    and DOI. `own_prior_keys` names the ones written by this paper's authors.
    """
    phrases = load_boilerplate(boilerplate)
    own = own_prior_keys or set()

    keys_by_sentence: dict[str, set[str]] = {}
    for citation in document.citations:
        if citation.sentence_id and not citation.in_bibliography:
            keys_by_sentence.setdefault(citation.sentence_id, set()).add(citation.key)

    readable = {
        key: value for key, value in sources.items() if value[0].available and value[0].text
    }
    matches: list[OverlapMatch] = []

    for sentence in document.sentences:
        cited = keys_by_sentence.get(sentence.id, set())
        for key, (source, title, doi) in readable.items():
            match = compare_sentence(
                sentence,
                cited,
                source,
                title,
                doi,
                phrases,
                is_own_prior_work=key in own,
            )
            if match is not None:
                matches.append(match)

    reported = [m for m in matches if m.verdict is not Overlap.BOILERPLATE_IGNORED]
    reported.sort(key=lambda m: (-m.distinctiveness, -m.length))

    unavailable = [
        title or key
        for key, (source, title, _doi) in sources.items()
        if not (source.available and source.text)
    ]

    return OriginalityReport(
        matches=tuple(reported),
        sources_compared=len(readable),
        sources_with_full_text=sum(
            1 for source, _t, _d in readable.values() if source.is_full_text
        ),
        sources_unavailable=len(unavailable),
        boilerplate_ignored=sum(1 for m in matches if m.verdict is Overlap.BOILERPLATE_IGNORED),
        unavailable_titles=tuple(sorted(unavailable)),
    )


def to_findings(report: OriginalityReport) -> list[Finding]:
    """Overlap findings. Every one goes to the human.

    Nothing here is auto-actionable. Rewriting a passage to avoid an overlap is
    exactly the synonym-substitution this project rules out, and adding a
    citation requires knowing what the author meant to say.
    """
    return sort_findings(
        [
            Finding(
                span_id=match.span_id,
                rule=f"originality_{str(match.verdict).lower()}",
                severity=SEVERITY[match.verdict],
                matched_text=match.matched_text[:200],
                char_range=match.char_range,
                suggestion=Suggestion.REVIEW,
                note=(
                    f"{match.note} Source: {match.source_title or 'unknown'}"
                    f"{f' ({match.source_doi})' if match.source_doi else ''}."
                ),
            )
            for match in report.matches
        ]
    )
