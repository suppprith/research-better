"""What a deletion is allowed to land on.

Every case here is one of the five patches `edit` proposed the first time
v0.1.0 ran on a real IEEEtran paper. All five were wrong, and every existing
gate passed them: there was a real orphan record behind each, so the evidence
gate and the per-edit pointer check were satisfied; the voice lock had nothing
to say because a deletion puts no new words on the page; and the word budget
was pleased. The protected-range rule caught the two that overlapped a declared
range and had no opinion on the rest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_better.edit import scope
from research_better.edit.ledger import Category, Edit
from research_better.ingest import load
from research_better.ingest.latex import ingest
from research_better.model import Document

FIXTURES = Path(__file__).parent / "fixtures" / "latex"


@pytest.fixture(scope="module")
def ieee() -> Document:
    return load(FIXTURES / "ieeetran-preamble.tex")


def cut_over(document: Document, phrase: str, category: Category = Category.CUT) -> Edit:
    """The deletion the tool would propose over the paragraph containing `phrase`."""
    offset = document.source_text.index(phrase)
    paragraph = next(
        (p for p in document.paragraphs if p.span.contains(offset)),
        None,
    )
    start, end = (
        (paragraph.span.char_start, paragraph.span.char_end)
        if paragraph is not None
        else (offset, offset + len(phrase))
    )
    return Edit(
        span_id="s-whatever",
        category=category,
        original=document.source_text[start:end],
        proposed="",
        reason="No sentence in this paragraph serves any part of the contribution claim.",
        evidence="novelty:orphan:s-whatever",
        confidence=0.3,
        char_range=(start, end),
    )


# Front matter -------------------------------------------------------------


def test_a_cut_into_an_affiliation_is_refused(ieee: Document) -> None:
    """`Bengaluru, India` was proposed for deletion from three author blocks."""
    refusal = scope.check(ieee, cut_over(ieee, "Bengaluru, India"))
    assert refusal is not None
    assert refusal[0] == "cut_into_front_matter"


def test_a_cut_into_the_keywords_block_is_refused(ieee: Document) -> None:
    refusal = scope.check(ieee, cut_over(ieee, "indoor localization"))
    assert refusal is not None
    assert refusal[0] == "cut_into_front_matter"


# Results ------------------------------------------------------------------


def test_a_paragraph_reporting_a_measurement_is_not_cut(tmp_path: Path) -> None:
    """The one that is not an ingest bug.

    An orphan classification reaching a Results paragraph that reports a
    finding is a false negative in claim matching, and a cut is the most
    expensive possible response to one.
    """
    paper = tmp_path / "main.tex"
    paper.write_text(
        r"""\begin{document}
\section{Discussion}
Geometric placement fails outright once the budget is held fixed. Coverage
falls from 0.81 to 0.54 across the four floors we measured.
\end{document}
""",
        encoding="utf-8",
    )
    document = ingest(paper)
    refusal = scope.check(document, cut_over(document, "Geometric placement fails"))
    assert refusal is not None
    assert refusal[0] == "cut_reports_a_measurement"


def test_a_paragraph_in_a_findings_section_is_not_cut(tmp_path: Path) -> None:
    paper = tmp_path / "main.tex"
    paper.write_text(
        r"""\begin{document}
\section{Results}
Peer review has been studied for many years. Reviewers disagree with each
other more often than authors expect.
\end{document}
""",
        encoding="utf-8",
    )
    document = ingest(paper)
    refusal = scope.check(document, cut_over(document, "Peer review has been"))
    assert refusal is not None
    assert refusal[0] == "cut_in_a_findings_section"


def test_a_paragraph_under_no_heading_is_not_cut(tmp_path: Path) -> None:
    """The format-neutral half.

    Word and PDF declare no front matter at all, so a rule keying on what the
    LaTeX adapter happens to recognise would not protect them. Written in
    Markdown here for the same reason: the LaTeX adapter now marks this as
    front matter, and a test it passes for that reason proves nothing about the
    formats that do not.

    Only the whole-paragraph deletion is refused. Cutting filler from an
    abstract, which is also unsectioned, stays allowed.
    """
    paper = tmp_path / "paper.md"
    paper.write_text(
        "A. Researcher, Some University, Bengaluru, India.\n\n"
        "# Introduction\n\nGreedy placement wins.\n",
        encoding="utf-8",
    )
    document = load(paper)
    refusal = scope.check(document, cut_over(document, "A. Researcher, Some University"))
    assert refusal is not None
    assert refusal[0] == "cut_outside_body_section"


# What must still be cuttable ----------------------------------------------
#
# The rules above are worth nothing if they refuse everything. A tool that
# never proposes a cut is as useless as one that proposes a destructive one,
# and easier to ship by accident.


def test_padding_in_an_ordinary_section_is_still_cut(tmp_path: Path) -> None:
    paper = tmp_path / "main.tex"
    paper.write_text(
        r"""\begin{document}
\section{Introduction}
Databases have existed since the 1960s. Relational algebra provides a formal
foundation for query languages.
\end{document}
""",
        encoding="utf-8",
    )
    document = ingest(paper)
    assert scope.check(document, cut_over(document, "Databases have existed")) is None


def test_a_roadmap_paragraph_is_still_cut(tmp_path: Path) -> None:
    """`Section 4 reports results` has digits in it and reports nothing.

    A rule keying on any digit rather than on a measurement would save the
    Results paragraph by refusing this too, which is why the pattern is
    decimals and percentages only.
    """
    paper = tmp_path / "main.tex"
    paper.write_text(
        r"""\begin{document}
\section{Introduction}
The remainder of this paper is organized as follows. Section 4 reports results
and Section 5 concludes.
\end{document}
""",
        encoding="utf-8",
    )
    document = ingest(paper)
    assert scope.check(document, cut_over(document, "The remainder of this paper")) is None


def test_a_fluff_deletion_inside_a_results_sentence_is_still_cut(tmp_path: Path) -> None:
    """Scope is about paragraph-sized deletions. Cutting `significantly` from a
    sentence in Results is a different act at any scale, and stays allowed."""
    paper = tmp_path / "main.tex"
    paper.write_text(
        r"""\begin{document}
\section{Results}
We significantly outperform the dense encoder at a fixed budget of 0.5 units.
\end{document}
""",
        encoding="utf-8",
    )
    document = ingest(paper)
    start = document.source_text.index("significantly ")
    edit = Edit(
        span_id="s-whatever",
        category=Category.CUT,
        original="significantly ",
        proposed="",
        reason="This adverb claims a magnitude with no number behind it.",
        evidence="fluff:unsupported_superlative_adverbs@0-0",
        confidence=0.9,
        char_range=(start, start + len("significantly ")),
    )
    assert scope.check(document, edit) is None


def test_a_tighten_is_not_screened_for_scope(ieee: Document) -> None:
    """These rules are about deletion. A replacement is held by the voice lock,
    which is the check that has something to say about new words."""
    edit = cut_over(ieee, "Geometric placement is reported", category=Category.TIGHTEN)
    assert scope.check(ieee, edit) is None


# The refusal has to be visible --------------------------------------------


def test_a_refusal_is_recorded_rather_than_silent(tmp_path: Path) -> None:
    """A tool that silently declines to propose something is indistinguishable
    from one that never noticed. The rule name and the reason both land in the
    ledger's `dropped` list, which the summary prints under 'Not proposed'."""
    paper = tmp_path / "main.tex"
    paper.write_text(
        r"""\begin{document}
\section{Results}
Coverage falls from 0.81 to 0.54 across the four floors we measured.
\end{document}
""",
        encoding="utf-8",
    )
    document = ingest(paper)
    refusal = scope.check(document, cut_over(document, "Coverage falls"))
    assert refusal is not None
    rule, note = refusal
    assert rule
    assert len(note.split()) > 8, "a named rule with no explanation is a shrug"
