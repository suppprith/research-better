"""Markdown ingest, checked against a paper-shaped fixture.

Two properties matter more than the rest. Nothing that is not prose may reach
`sentences[]`, because everything downstream treats a sentence as something a
human wrote as an argument. And re-emitting must reproduce the source exactly,
because the tool patches byte ranges rather than rewriting files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_better.errors import UnsupportedFormatError
from research_better.ingest import emit, load, supported_suffixes
from research_better.ingest.markdown import ingest
from research_better.model import Document, FloatKind

FIXTURE = Path(__file__).parent / "fixtures" / "sample.md"


@pytest.fixture(scope="module")
def paper() -> Document:
    return load(FIXTURE)


def test_round_trip_is_byte_exact(paper: Document) -> None:
    assert emit(paper).encode("utf-8") == FIXTURE.read_bytes()


def test_round_trip_survives_crlf() -> None:
    source = "# Title\r\n\r\nOne sentence here.\r\n"
    document = ingest("crlf.md", source)
    assert emit(document) == source
    assert [s.text for s in document.sentences] == ["One sentence here."]


def test_code_fences_never_appear_in_sentences(paper: Document) -> None:
    joined = " ".join(sentence.text for sentence in paper.sentences)
    assert "def score" not in joined
    assert "must never be flagged as fluff" not in joined
    assert len(paper.floats_of_kind(FloatKind.CODE)) == 1


def test_tables_never_appear_in_sentences(paper: Document) -> None:
    joined = " ".join(sentence.text for sentence in paper.sentences)
    assert "Recall@10" not in joined
    assert "BM25+QE" not in joined
    assert len(paper.floats_of_kind(FloatKind.TABLE)) == 1


def test_math_blocks_and_quotes_are_floats(paper: Document) -> None:
    joined = " ".join(sentence.text for sentence in paper.sentences)
    assert "\\mathrm{idf}" not in joined
    assert "was not retrained" not in joined
    assert len(paper.floats_of_kind(FloatKind.EQUATION)) == 1
    assert len(paper.floats_of_kind(FloatKind.QUOTE)) == 1


def test_html_comments_are_excluded(paper: Document) -> None:
    joined = " ".join(sentence.text for sentence in paper.sentences)
    assert "reviewer note" not in joined


def test_front_matter_is_metadata_not_prose(paper: Document) -> None:
    assert paper.metadata["title"] == "Sparse Retrieval Still Wins at Equal Cost"
    assert paper.metadata["author"] == "A. Researcher"
    joined = " ".join(sentence.text for sentence in paper.sentences)
    assert "A. Researcher" not in joined
    assert len(paper.floats_of_kind(FloatKind.FRONT_MATTER)) == 1


def test_setext_and_atx_headings_build_one_tree(paper: Document) -> None:
    titles = [(section.title, section.level) for section in paper.sections]
    assert titles == [
        ("Introduction", 1),
        ("Method", 2),
        ("Index", 3),
        ("Implementation", 3),
        ("Results", 2),
        ("References", 2),
    ]
    index_section = next(s for s in paper.sections if s.title == "Index")
    assert index_section.path == ("Introduction", "Method", "Index")


def test_numeric_citations_are_found_and_split(paper: Document) -> None:
    used = {c.key for c in paper.citations if not c.in_bibliography}
    assert {"1", "2", "3"} <= used, "[2, 3] must become two separate keys"


def test_pandoc_citations_are_found(paper: Document) -> None:
    used = {c.key for c in paper.citations if not c.in_bibliography}
    assert "nakamura2024" in used


def test_bare_doi_and_arxiv_links_are_citations(paper: Document) -> None:
    keys = {c.key for c in paper.citations}
    assert "10.1145/1234.5678" in keys
    assert "arXiv:2401.01234" in keys


def test_citations_attach_to_the_sentence_that_makes_the_claim(paper: Document) -> None:
    used = [c for c in paper.citations if not c.in_bibliography and c.key == "1"]
    sentence = paper.sentence(used[0].sentence_id or "")
    assert "plateaued" in sentence.text


def test_reference_entries_are_parsed_and_stay_unattached(paper: Document) -> None:
    entries = [c for c in paper.citations if c.in_bibliography]
    assert [entry.key for entry in entries] == ["1", "2", "3"]
    assert all(entry.sentence_id is None for entry in entries)
    assert "Smith, J. and Lee, K." in entries[0].raw


def test_reference_list_is_not_treated_as_prose(paper: Document) -> None:
    references = next(s for s in paper.sections if s.title == "References")
    assert paper.sentences_in_section(references.id) == ()


def test_urls_do_not_split_sentences(paper: Document) -> None:
    with_url = [s for s in paper.sentences if "doi.org" in s.text]
    assert len(with_url) == 1
    assert with_url[0].text.endswith(".")
    assert "follows the setup in Sec. 3" in with_url[0].text


def test_list_items_are_separate_paragraphs_without_their_markers(paper: Document) -> None:
    bullets = [s.text for s in paper.sentences if s.text.startswith("Sparse retrieval")]
    assert len(bullets) == 2
    assert not any(text.startswith("-") for text in bullets)


def test_every_sentence_recovers_its_source_exactly(paper: Document) -> None:
    for sentence in paper.sentences:
        assert paper.text_of(sentence.span) == sentence.text


def test_no_sentence_overlaps_a_float(paper: Document) -> None:
    for sentence in paper.sentences:
        for item in paper.floats:
            assert not sentence.span.overlaps(item.span), (
                f"sentence {sentence.text!r} overlaps {item.kind}"
            )


def test_prose_is_not_dropped(paper: Document) -> None:
    joined = " ".join(sentence.text for sentence in paper.sentences)
    for claim in (
        "Retrieval quality on this benchmark has plateaued since 2021",
        "We show that BM25 with query expansion matches a dense encoder",
        "Recall at ten improves by four points",
        "Runs use a single node.",
    ):
        assert claim in joined


def test_unsupported_extension_names_what_is_supported(tmp_path: Path) -> None:
    target = tmp_path / "paper.rtf"
    target.write_text("body", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError, match=r"\.rtf"):
        load(target)
    assert ".md" in supported_suffixes()


def test_unterminated_front_matter_is_not_swallowed() -> None:
    document = ingest("odd.md", "---\ntitle: Broken\n\nActual prose here.\n")
    assert any(s.text == "Actual prose here." for s in document.sentences)


def test_unterminated_code_fence_does_not_lose_the_rest() -> None:
    document = ingest("odd.md", "Prose first.\n\n```\nnever closed\n")
    assert [s.text for s in document.sentences] == ["Prose first."]
    assert len(document.floats_of_kind(FloatKind.CODE)) == 1
