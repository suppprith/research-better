"""Structural and rhythm rules.

These read distributions across a paragraph or a section rather than single
sentences. They catch what makes text read as machine-written when every
individual sentence is clean: uniform rhythm, repeated templates, a closing
sentence that restates the opening one.

Everything here is advisory, and the reason is worth stating plainly rather
than burying in a docstring nobody reads. Low sentence-length variance
correlates with generated text. It does not prove it. Some careful human
writers are naturally uniform, and formulaic methods prose is uniform because
the method is formulaic. A finding from this module is worth showing to an
author and is never worth applying for them, so `advisory=True` on every one.

Two of the six rules ship disabled, because their thresholds are claims about
how humans write and no corpus has been run to support them. See
`scripts/calibrate_rhythm.py` and the comments in `rhythm-thresholds.toml`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from statistics import pstdev

from research_better.findings import Finding, Severity, Suggestion
from research_better.lexicon import Lexicon, RuleSection, load_lexicon
from research_better.model import Document, Sentence
from research_better.thresholds import Thresholds, load_thresholds

LEXICON_FAMILIES = ("balanced_clause", "empty_forward_reference")
"""Families whose terms live in the lexicon but whose matcher lives here,
because both need section-level counting rather than per-sentence matching."""

TRICOLON = re.compile(
    r"\b([A-Za-z][\w-]*),\s+([A-Za-z][\w-]*),?\s+and\s+([A-Za-z][\w-]*)\b",
    re.IGNORECASE,
)

WORDS = re.compile(r"[A-Za-z][A-Za-z'-]*")

POINTER = re.compile(
    r"\b(?:section|sec\.|chapter|appendix|figure|fig\.|table|tab\.|equation|eq\.)\b|\\ref|\d",
    re.IGNORECASE,
)

# Words that carry no content, so a sentence made only of these repeats nothing.
STOPWORDS = frozenset(
    """
        a all also an and any are as at be been being both but by can could did do does
        don each few for from had has have he her here his how i if in is it its just
        may might more most must no not now of on only or other our own s same she
        should so some such t than that the their then there these they this those to
        too us very was we were what when where which who whom whose why will with would
        you your
    """.split()
)


def _content_words(text: str) -> set[str]:
    return {word.lower() for word in WORDS.findall(text)} - STOPWORDS


def _finding(
    sentence: Sentence,
    rule: str,
    matched: str,
    note: str,
    span: tuple[int, int] | None = None,
    severity: Severity = Severity.LOW,
) -> Finding:
    return Finding(
        span_id=sentence.id,
        rule=rule,
        severity=severity,
        matched_text=matched,
        char_range=span or (sentence.span.char_start, sentence.span.char_end),
        suggestion=Suggestion.REVIEW,
        note=note,
        advisory=True,
    )


def _sentences_by_paragraph(document: Document) -> dict[str, list[Sentence]]:
    grouped: dict[str, list[Sentence]] = defaultdict(list)
    for sentence in document.sentences:
        grouped[sentence.paragraph_id].append(sentence)
    return grouped


def _sentences_by_section(document: Document) -> dict[str, list[Sentence]]:
    grouped: dict[str, list[Sentence]] = defaultdict(list)
    for sentence in document.sentences:
        if sentence.section_id:
            grouped[sentence.section_id].append(sentence)
    return grouped


# Rules --------------------------------------------------------------------


def _sentence_length_variance(document: Document, config: Thresholds) -> list[Finding]:
    rule = config.for_rule("sentence_length_variance")
    minimum = int(rule.number("minimum_sentences"))
    floor = rule.number("min_stdev_words")

    findings: list[Finding] = []
    for sentences in _sentences_by_paragraph(document).values():
        if len(sentences) < minimum:
            continue
        lengths = [len(sentence.text.split()) for sentence in sentences]
        spread = pstdev(lengths)
        if spread < floor:
            findings.append(
                _finding(
                    sentences[0],
                    "sentence_length_variance",
                    f"{len(lengths)} sentences, standard deviation {spread:.1f} words",
                    (
                        f"Sentence lengths in this paragraph vary less than the corpus "
                        f"floor of {floor:.1f} words. That correlates with generated "
                        f"text and does not prove it. If you wrote it and it reads "
                        f"well, leave it."
                    ),
                )
            )
    return findings


def _paragraph_shape_uniformity(document: Document, config: Thresholds) -> list[Finding]:
    rule = config.for_rule("paragraph_shape_uniformity")
    minimum_run = int(rule.number("minimum_run"))
    tolerance = int(rule.number("tolerance"))

    grouped = _sentences_by_paragraph(document)
    ordered = [
        (paragraph.id, grouped[paragraph.id])
        for paragraph in document.paragraphs
        if grouped.get(paragraph.id)
    ]

    findings: list[Finding] = []
    run: list[tuple[str, list[Sentence]]] = []

    def close(current: list[tuple[str, list[Sentence]]]) -> None:
        if len(current) < minimum_run:
            return
        for _, sentences in current:
            findings.append(
                _finding(
                    sentences[0],
                    "paragraph_shape_uniformity",
                    f"{len(current)} consecutive paragraphs of similar length",
                    (
                        "A run of paragraphs with near-identical sentence counts reads "
                        "as a template. This is a shape observation, not a claim about "
                        "the content."
                    ),
                )
            )

    for entry in ordered:
        if run and abs(len(entry[1]) - len(run[-1][1])) <= tolerance:
            run.append(entry)
        else:
            close(run)
            run = [entry]
    close(run)
    return findings


def _tricolon(document: Document, config: Thresholds) -> list[Finding]:
    """Three-item lists, flagged only where they repeat inside one section."""
    rule = config.for_rule("tricolon")
    minimum = int(rule.number("minimum_repeats"))

    hits: dict[str, list[tuple[Sentence, tuple[int, int], str]]] = defaultdict(list)
    for sentence in document.sentences:
        for match in TRICOLON.finditer(sentence.text):
            span = (
                sentence.span.char_start + match.start(),
                sentence.span.char_start + match.end(),
            )
            hits[sentence.section_id or ""].append((sentence, span, match.group(0)))

    findings: list[Finding] = []
    for section_hits in hits.values():
        if len(section_hits) < minimum:
            continue
        for sentence, span, matched in section_hits:
            findings.append(
                _finding(
                    sentence,
                    "tricolon",
                    matched,
                    (
                        f"This section uses {len(section_hits)} three-item lists. One is "
                        f"a stylistic choice. Several is a cadence, and a reader starts "
                        f"hearing the pattern instead of the argument."
                    ),
                    span=span,
                )
            )
    return findings


def _template_repeats(
    document: Document,
    sections: tuple[RuleSection, ...],
    rule_id: str,
    minimum: int,
) -> list[Finding]:
    """Flag a lexicon template only where it repeats inside one section."""
    hits: dict[str, list[tuple[Sentence, tuple[int, int], str, RuleSection]]] = defaultdict(list)

    for sentence in document.sentences:
        for section in sections:
            for term in section.terms:
                pattern = re.compile(
                    r"\b" + r"\s+".join(re.escape(part) for part in term.phrase.split()) + r"\b",
                    re.IGNORECASE,
                )
                for match in pattern.finditer(sentence.text):
                    span = (
                        sentence.span.char_start + match.start(),
                        sentence.span.char_start + match.end(),
                    )
                    hits[sentence.section_id or ""].append(
                        (sentence, span, match.group(0), section)
                    )

    findings: list[Finding] = []
    for section_hits in hits.values():
        if len(section_hits) < minimum:
            continue
        for sentence, span, matched, section in section_hits:
            findings.append(
                _finding(
                    sentence,
                    rule_id,
                    matched,
                    section.note or "",
                    span=span,
                    severity=section.severity,
                )
            )
    return findings


def _section_closing_restatement(document: Document, config: Thresholds) -> list[Finding]:
    """A closing sentence that adds no content word the opening did not carry.

    No similarity threshold is involved, which is why this rule can ship
    without a corpus. Either the last sentence introduces something or it does
    not, and if it does not, it is there to fill the space.
    """
    rule = config.for_rule("section_closing_restatement")
    minimum_words = int(rule.number("minimum_content_words"))

    findings: list[Finding] = []
    for sentences in _sentences_by_section(document).values():
        if len(sentences) < 2:
            continue
        opening = _content_words(sentences[0].text)
        closing = _content_words(sentences[-1].text)
        if len(closing) < minimum_words or not closing:
            continue
        if closing - opening:
            continue
        findings.append(
            _finding(
                sentences[-1],
                "section_closing_restatement",
                sentences[-1].text.strip(),
                (
                    "This sentence introduces no word the section's opening sentence "
                    "did not already carry. It restates rather than concludes, so "
                    "cutting it loses nothing."
                ),
                severity=Severity.MEDIUM,
            )
        )
    return findings


def _empty_forward_reference(
    document: Document, sections: tuple[RuleSection, ...]
) -> list[Finding]:
    findings: list[Finding] = []
    for sentence in document.sentences:
        if POINTER.search(sentence.text):
            continue
        for section in sections:
            for term in section.terms:
                pattern = re.compile(
                    r"\b" + r"\s+".join(re.escape(part) for part in term.phrase.split()) + r"\b",
                    re.IGNORECASE,
                )
                match = pattern.search(sentence.text)
                if match:
                    findings.append(
                        _finding(
                            sentence,
                            "empty_forward_reference",
                            match.group(0),
                            section.note or "",
                            span=(
                                sentence.span.char_start + match.start(),
                                sentence.span.char_start + match.end(),
                            ),
                            severity=section.severity,
                        )
                    )
                    break
    return findings


def analyse_structural(
    document: Document,
    lexicon_file: Path | None = None,
    thresholds_file: Path | None = None,
) -> list[Finding]:
    config: Thresholds = load_thresholds(thresholds_file)
    lexicon: Lexicon = load_lexicon(lexicon_file)

    findings: list[Finding] = []
    if config.enabled("sentence_length_variance"):
        findings.extend(_sentence_length_variance(document, config))
    if config.enabled("paragraph_shape_uniformity"):
        findings.extend(_paragraph_shape_uniformity(document, config))
    if config.enabled("tricolon"):
        findings.extend(_tricolon(document, config))
    if config.enabled("balanced_clause"):
        findings.extend(
            _template_repeats(
                document,
                lexicon.family("balanced_clause"),
                "balanced_clause",
                int(config.for_rule("balanced_clause").number("minimum_repeats")),
            )
        )
    if config.enabled("section_closing_restatement"):
        findings.extend(_section_closing_restatement(document, config))
    if config.enabled("empty_forward_reference"):
        findings.extend(
            _empty_forward_reference(document, lexicon.family("empty_forward_reference"))
        )
    return findings
