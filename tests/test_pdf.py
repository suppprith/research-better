"""PDF ingest, review only.

The fixture is written as raw PDF operators so every line sits at a known
coordinate. See pdf_fixture.py. Column detection is the whole difficulty of
reading a paper back out of a PDF, and a fixture produced by a typesetting
library would put the layout outside the test's control.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_fixture import build, build_scanned, build_single_column
from research_better.artifacts import ArtifactStore
from research_better.cli import EXIT_ERROR, main
from research_better.errors import IngestError
from research_better.ingest import load, supported_suffixes
from research_better.ingest.pdf import find_gutter, read
from research_better.model import Document


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build(tmp_path_factory.mktemp("pdf-source") / "paper.pdf", line_numbers=True)


@pytest.fixture
def draft(source: Path, tmp_path: Path) -> Path:
    target = tmp_path / "paper.pdf"
    target.write_bytes(source.read_bytes())
    return target


@pytest.fixture
def document(draft: Path) -> Document:
    return load(draft)


def joined(document: Document) -> str:
    return " ".join(sentence.text for sentence in document.sentences)


# Dispatch ------------------------------------------------------------------


def test_pdf_is_a_supported_format() -> None:
    assert ".pdf" in supported_suffixes()


def test_a_pdf_ingests_through_the_normal_entry_point(document: Document) -> None:
    assert document.format == "pdf"
    assert document.sentences


# Reading order -------------------------------------------------------------


def test_two_columns_are_detected(draft: Path) -> None:
    assert read(draft).columns == (2, 2)


def test_a_single_column_paper_is_not_split(tmp_path: Path) -> None:
    # A gap at the page edge is a margin, not a column boundary, and splitting
    # a thesis into two columns would interleave every paragraph.
    assert read(build_single_column(tmp_path / "single.pdf")).columns == (1,)


def test_the_columns_are_read_one_after_the_other(document: Document) -> None:
    body = joined(document)
    # Naive extraction runs down the page rather than down the column, which
    # interleaves the two and is the reason IEEE papers come out as nonsense.
    assert body.index("Dense encoders are reported") < body.index("We present a comparison")
    assert body.index("We present a comparison") < body.index("The corpus is indexed")


def test_the_second_page_follows_the_first(document: Document) -> None:
    titles = [section.title for section in document.sections]
    assert titles == ["INTRODUCTION", "METHOD", "RESULTS", "REFERENCES"]


def test_a_gutter_is_only_a_gutter_near_the_middle() -> None:
    assert find_gutter([], 612) is None


# Cleaning up ---------------------------------------------------------------


def test_a_word_hyphenated_across_a_line_break_is_rejoined(document: Document) -> None:
    body = joined(document)
    assert "sparse baselines" in body
    assert "we report recall" in body
    assert "base-" not in body


def test_a_hyphen_the_author_wrote_survives(document: Document) -> None:
    from research_better.ingest.pdf import _dehyphenate

    # Rejoining every hyphen would invent a word nobody typed, so only a break
    # before a lower-case continuation counts.
    assert _dehyphenate("state-of-the-", "art") == "state-of-theart"
    assert _dehyphenate("BM25 and", "Beyond") == "BM25 and Beyond"


def test_the_running_header_and_page_number_are_dropped(document: Document) -> None:
    body = joined(document)
    assert "Sparse Retrieval at Equal Cost" not in body


def test_margin_line_numbers_are_dropped(document: Document) -> None:
    # Left in place they turn the first word of every line into a claim about a
    # number.
    assert not any(sentence.text.strip().isdigit() for sentence in document.sentences)


def test_what_was_dropped_is_recorded(draft: Path) -> None:
    notes = read(draft).notes
    assert any("header" in note for note in notes)
    assert any("line number" in note for note in notes)


def test_a_table_row_is_skipped_rather_than_read_as_prose(document: Document) -> None:
    body = joined(document)
    # Read as prose, a table row produces a sentence the author never wrote.
    assert "BM25+QE 0.71 1.0" not in body
    assert any("BM25+QE" in document.text_of(item.span) for item in document.floats)


def test_a_caption_is_not_a_claim_sentence(document: Document) -> None:
    assert "Table 1: Systems compared." not in joined(document)


def test_what_was_skipped_is_recorded(draft: Path) -> None:
    assert any("table row or a caption" in note for note in read(draft).notes)


# References ----------------------------------------------------------------


def test_the_reference_section_becomes_entries(document: Document) -> None:
    entries = [c for c in document.citations if c.in_bibliography]
    assert [entry.key for entry in entries] == ["1", "2"]


def test_a_wrapped_entry_is_one_entry(document: Document) -> None:
    entry = next(c for c in document.citations if c.in_bibliography and c.key == "1")
    assert "Foundations and Trends" in entry.raw
    assert "10.1561/1500000019" in entry.raw


def test_in_text_citations_are_found(document: Document) -> None:
    used = [c.key for c in document.citations if not c.in_bibliography]
    assert used == ["1", "2"]


def test_citation_verification_runs_from_a_pdf_alone(draft: Path) -> None:
    # The reason to read the format at all. The entries are copied from
    # bad-paper.md so the recorded responses answer the same queries.
    main(["ground", str(draft), "--quiet"])
    artifact = ArtifactStore(draft).read("grounding")
    assert artifact is not None
    checks = artifact.payload["citations"]["checks"]
    assert len(checks) == 2
    assert any(check["verdict"] == "VERIFIED" for check in checks)


# Limits, stated --------------------------------------------------------------


def test_a_scan_is_refused_rather_than_analysed(tmp_path: Path) -> None:
    scanned = build_scanned(tmp_path / "scan.pdf")
    with pytest.raises(IngestError, match="OCR"):
        load(scanned)


def test_the_scan_message_says_nothing_was_analysed(tmp_path: Path) -> None:
    scanned = build_scanned(tmp_path / "scan.pdf")
    with pytest.raises(IngestError) as failure:
        load(scanned)
    # A clean report about a paper the tool never read is worse than no report.
    assert "Nothing was analysed" in str(failure.value)


def test_a_file_that_is_not_a_pdf_fails_as_an_ingest_error(tmp_path: Path) -> None:
    target = tmp_path / "broken.pdf"
    target.write_bytes(b"this is not a pdf")
    with pytest.raises(IngestError):
        load(target)


def test_apply_to_a_pdf_is_refused(draft: Path) -> None:
    assert main(["edit", str(draft), "--apply", "--quiet"]) == EXIT_ERROR


def test_the_report_says_the_reading_was_not_exact(draft: Path) -> None:
    from research_better.report import build as build_report

    main(["ingest", str(draft), "--quiet"])
    report = build_report(load(draft), ArtifactStore(draft))
    # Silence about a doubtful extraction reads as a confident one.
    assert any("Reading this format was not exact" in gap for gap in report.gaps)


def test_the_layout_it_found_is_recorded(document: Document) -> None:
    # Reported so a reader can see the layout was understood rather than
    # guessed at.
    assert document.metadata["columns"] == "2, 2"
    assert document.metadata["pages"] == "2"
