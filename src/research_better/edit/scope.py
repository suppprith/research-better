"""Where a deletion is allowed to land.

`Finding.auto_actionable` treats a deletion as the safe suggestion, reasoning
that a deletion cannot introduce a word the author never wrote. That reasoning
is sound and it is incomplete. A deletion cannot invent text and it can
absolutely destroy it. A cut is only safe when the thing being cut is prose
that carries no content, and until this module existed nothing checked that the
target was prose at all.

The failure that produced it: run on a real IEEEtran paper, `edit` proposed
cutting three author affiliations, the keywords block, and a whole Results
paragraph reporting measurements. Every gate passed them. The evidence gate was
satisfied because there was a real orphan record behind each one. The per-edit
pointer check was satisfied for the same reason. The voice lock had nothing to
say, because a deletion puts no new words on the page. The word budget was
delighted. The protected-range rule caught the two cuts that overlapped a
declared range and had no opinion on the five that did not.

So the checks here are about the target rather than the justification, and they
are deliberately structural. Not "is this paragraph any good", which is the
judgement that was already made and got it wrong, but "is this the kind of
place a paragraph may be deleted from at all".

Every refusal lands in the ledger's `dropped` list with the rule named. The
finding itself survives in `novelty.json` and in the report, so an author still
learns the paragraph looked unsupported. What they do not get is it applied for
them.
"""

from __future__ import annotations

import re

from research_better.edit.ledger import Category, Edit
from research_better.model import Document, FloatKind, Section

Rejection = tuple[str, str]
"""(rule, note), the same shape the voice lock returns. Declared here rather
than imported from it, because the voice lock calls into this module."""

MEASUREMENT = re.compile(r"\d+\.\d+|\d+(?:\.\d+)?\s*%|\bpercent\b")
"""What a paragraph reporting a result looks like.

Decimals and percentages only, on purpose. A bare integer is not a measurement:
`novelty` already knows that "Databases have existed since the 1960s" contains
a digit and reports nothing, and "Section 4 reports results" is a roadmap. Both
are paragraphs this tool correctly offers to cut, and a rule keying on any
digit would save the Results paragraph by refusing those too.
"""

FINDINGS_SECTIONS = ("result", "evaluation", "experiment", "finding", "measurement")
"""Sections whose paragraphs are the author's findings.

Orphan classification is least reliable exactly here. A findings paragraph
serves the claim by reporting what happened, which is a relation between a
measurement and a claim rather than a shared vocabulary, and shared vocabulary
is what the classifier can see.
"""


def _enclosing_section(document: Document, start: int, end: int) -> Section | None:
    """The deepest section containing the range, if any."""
    found: Section | None = None
    for section in document.sections:
        encloses = section.span.char_start <= start and end <= section.span.char_end
        if encloses and (found is None or section.level > found.level):
            found = section
    return found


def _covers_a_whole_paragraph(document: Document, start: int, end: int) -> bool:
    """Whether this cut takes out an entire paragraph rather than a phrase.

    The distinction the rules below turn on. Deleting `significantly` from a
    sentence in the Results section is a fluff cut and stays allowed. Deleting
    the sentence's whole paragraph is not the same act at any scale.
    """
    return any(
        start <= paragraph.span.char_start and paragraph.span.char_end <= end
        for paragraph in document.paragraphs
    )


def check(document: Document, edit: Edit) -> Rejection | None:
    """Refuse a deletion whose target is not prose that may be deleted."""
    if edit.category is not Category.CUT:
        return None

    start, end = edit.char_range

    for item in document.floats_of_kind(FloatKind.FRONT_MATTER):
        if item.span.char_start < end and start < item.span.char_end:
            return (
                "cut_into_front_matter",
                "Lands in the paper's front matter, which names the authors rather than "
                "making the argument. Nothing there is a claim, so nothing there can "
                "fail to serve one.",
            )

    if not _covers_a_whole_paragraph(document, start, end):
        return None

    section = _enclosing_section(document, start, end)
    if section is None:
        return (
            "cut_outside_body_section",
            "Deletes a whole paragraph that sits under no section heading. Text outside "
            "the body is not the argument, whatever the adapter read it as, and a "
            "paragraph-sized deletion there is the most expensive way to find that out.",
        )

    if MEASUREMENT.search(document.source_text[start:end]):
        return (
            "cut_reports_a_measurement",
            "Deletes a whole paragraph that reports a measurement. A paragraph carrying "
            "numbers is the author's findings, and a classifier that could not match it "
            "to the claim has found a gap in its own matching before it has found "
            "padding.",
        )

    title = section.title.lower()
    if any(name in title for name in FINDINGS_SECTIONS):
        return (
            "cut_in_a_findings_section",
            f"Deletes a whole paragraph from {section.title!r}. A findings paragraph "
            f"serves the claim by reporting what happened rather than by repeating its "
            f"words, which is the relation this classifier cannot see.",
        )

    return None
