"""The model has to hand back the exact bytes it was built from.

Review-only patching depends on it: the tool proposes a range and a
replacement, and the range has to land where the tool thinks it does.
"""

from __future__ import annotations

import pytest

from conftest import BuildDocument
from research_better.builder import DocumentBuilder
from research_better.model import Document, FloatKind, LineMap, Span

PAPER = """\
# Introduction

Retrieval quality has plateaued. We show a sparse index still wins.

## Setup

The corpus is Wikipedia.

# Results

Recall improves by four points.
"""


def test_spans_recover_the_exact_source_text(build_document: BuildDocument) -> None:
    document = build_document(PAPER)
    for sentence in document.sentences:
        assert document.text_of(sentence.span) == sentence.text
        assert PAPER[sentence.char_start : sentence.char_end] == sentence.text


def test_byte_range_matches_utf8_offsets() -> None:
    text = "Résumé quality improved. Naïve baselines did not.\n"
    builder = DocumentBuilder("p.txt", "plain", text)
    builder.add_paragraph(builder.span(0, len(text.rstrip("\n"))))
    document = builder.build()

    encoded = text.encode("utf-8")
    for sentence in document.sentences:
        start, end = document.byte_range(sentence.span)
        assert encoded[start:end].decode("utf-8") == sentence.text


def test_line_numbers_are_one_based(build_document: BuildDocument) -> None:
    document = build_document(PAPER)
    first = document.sentences[0]
    assert first.line == 3
    assert PAPER.splitlines()[first.line - 1].startswith("Retrieval quality")


def test_line_map_handles_offsets_at_line_starts() -> None:
    mapping = LineMap.build("a\nbb\n\nccc")
    assert mapping.line_of(0) == 1
    assert mapping.line_of(2) == 2
    assert mapping.line_of(5) == 3
    assert mapping.line_of(8) == 4


def test_sections_nest_by_level(build_document: BuildDocument) -> None:
    document = build_document(PAPER)
    titles = [section.title for section in document.sections]
    assert titles == ["Introduction", "Setup", "Results"]

    setup = next(s for s in document.sections if s.title == "Setup")
    introduction = next(s for s in document.sections if s.title == "Introduction")
    assert setup.parent_id == introduction.id
    assert setup.path == ("Introduction", "Setup")


def test_section_span_covers_its_body_up_to_the_next_peer(
    build_document: BuildDocument,
) -> None:
    document = build_document(PAPER)
    introduction = next(s for s in document.sections if s.title == "Introduction")
    results = next(s for s in document.sections if s.title == "Results")

    body = document.text_of(introduction.span)
    assert "The corpus is Wikipedia." in body, "a subsection belongs to its parent"
    assert "Recall improves" not in body, "a peer heading ends the section"
    assert introduction.span.char_end == results.heading_span.char_start


def test_sentences_are_attributed_to_the_deepest_open_section(
    build_document: BuildDocument,
) -> None:
    document = build_document(PAPER)
    setup = next(s for s in document.sections if s.title == "Setup")
    texts = [s.text for s in document.sentences_in_section(setup.id)]
    assert texts == ["The corpus is Wikipedia."]


def test_citations_attach_to_the_sentence_they_sit_in() -> None:
    text = "Sparse retrieval still wins [1]. Dense methods close the gap [2]."
    builder = DocumentBuilder("p.txt", "plain", text)
    builder.add_paragraph(builder.span(0, len(text)))
    builder.add_citation("1", "[1]", builder.span(text.index("[1]"), text.index("[1]") + 3))
    builder.add_citation("2", "[2]", builder.span(text.index("[2]"), text.index("[2]") + 3))
    document = builder.build()

    first, second = document.sentences
    assert document.citations_in_sentence(first.id)[0].key == "1"
    assert document.citations_in_sentence(second.id)[0].key == "2"


def test_a_citation_outside_any_sentence_stays_unattached() -> None:
    text = "Body sentence here.\n\n[1] Smith, A Paper, 2020.\n"
    builder = DocumentBuilder("p.txt", "plain", text)
    builder.add_paragraph(builder.span(0, len("Body sentence here.")))
    reference_start = text.index("[1] Smith")
    builder.add_float(FloatKind.BIBLIOGRAPHY, builder.span(reference_start, len(text.rstrip("\n"))))
    builder.add_citation("1", "[1]", builder.span(reference_start, reference_start + 3))
    document = builder.build()

    assert document.citations[0].sentence_id is None


def test_floats_are_never_segmented_into_sentences() -> None:
    text = "Prose sentence.\n\n| a | b |\n| 1 | 2 |\n"
    builder = DocumentBuilder("p.txt", "plain", text)
    builder.add_paragraph(builder.span(0, len("Prose sentence.")))
    builder.add_float(FloatKind.TABLE, builder.span(text.index("| a"), len(text)))
    document = builder.build()

    assert [s.text for s in document.sentences] == ["Prose sentence."]
    assert len(document.floats_of_kind(FloatKind.TABLE)) == 1


def test_word_count_excludes_floats() -> None:
    text = "Four words in here.\n\n| a | b |\n"
    builder = DocumentBuilder("p.txt", "plain", text)
    builder.add_paragraph(builder.span(0, len("Four words in here.")))
    builder.add_float(FloatKind.TABLE, builder.span(text.index("| a"), len(text)))
    assert builder.build().word_count == 4


def test_lookup_by_id_rejects_a_wrong_type(build_document: BuildDocument) -> None:
    document = build_document(PAPER)
    section_id = document.sections[0].id
    with pytest.raises(KeyError, match="not a Sentence"):
        document.sentence(section_id)
    with pytest.raises(KeyError, match="no element with id"):
        document.element("s-doesnotexist")


def test_sentence_at_offset(build_document: BuildDocument) -> None:
    document = build_document(PAPER)
    target = document.sentences[1]
    assert document.sentence_at(target.char_start + 2) is target
    assert document.sentence_at(0) is None


def test_span_rejects_a_reversed_range() -> None:
    with pytest.raises(ValueError, match="ends before it starts"):
        Span(char_start=10, char_end=4)


def test_span_overlap_and_containment() -> None:
    span = Span(char_start=5, char_end=10)
    assert span.contains(5) and span.contains(9)
    assert not span.contains(10)
    assert span.overlaps(Span(char_start=9, char_end=20))
    assert not span.overlaps(Span(char_start=10, char_end=20))
    assert span.length == 5


def test_source_hash_changes_with_the_source(build_document: BuildDocument) -> None:
    assert Document.hash_source("a") != Document.hash_source("b")
    assert build_document(PAPER).source_hash == Document.hash_source(PAPER)
