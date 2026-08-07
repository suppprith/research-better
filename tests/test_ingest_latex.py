"""LaTeX ingest, against a multi-file paper shaped like a real submission.

The stakes here are different from Markdown. A careless edit to a `.tex` file
does not read badly, it fails to compile, so this suite spends most of its
weight on what must never be touched and on getting a patch back to the right
file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_better.errors import IngestError, MissingExtraError, ProtectedRangeError
from research_better.ingest import load
from research_better.ingest.latex import ingest
from research_better.model import Document, FloatKind, Span

FIXTURES = Path(__file__).parent / "fixtures" / "latex"
PAPER = FIXTURES / "paper.tex"


@pytest.fixture(scope="module")
def paper() -> Document:
    return load(PAPER)


def sentence_text(document: Document) -> str:
    return " ".join(sentence.text for sentence in document.sentences)


# Multi-file assembly ------------------------------------------------------


def test_input_is_spliced_into_one_document(paper: Document) -> None:
    joined = sentence_text(paper)
    assert "The corpus is indexed with BM25" in joined, "text from method.tex is missing"
    assert "Recall at ten improves by four points" in joined, "text from paper.tex is missing"


def test_sections_from_both_files_share_one_tree(paper: Document) -> None:
    titles = [section.title for section in paper.sections]
    assert titles == ["Introduction", "Method", "Results"]


def test_spans_are_attributed_to_the_file_they_came_from(paper: Document) -> None:
    from_method = next(s for s in paper.sentences if "indexed with BM25" in s.text)
    from_root = next(s for s in paper.sentences if "Recall at ten improves" in s.text)

    method_file, local_start, local_end = paper.locate(from_method.span)
    root_file, _, _ = paper.locate(from_root.span)

    assert Path(method_file).name == "method.tex"
    assert Path(root_file).name == "paper.tex"

    # A patch goes back to the file the text lives in, at that file's offsets.
    method_source = Path(method_file).read_bytes().decode("utf-8")
    assert method_source[local_start:local_end] == from_method.text


def test_a_missing_input_file_fails_loudly(tmp_path: Path) -> None:
    root = tmp_path / "main.tex"
    root.write_text(
        "\\begin{document}\nProse here.\n\\input{absent}\n\\end{document}\n", encoding="utf-8"
    )
    with pytest.raises(IngestError, match="does not exist"):
        ingest(root)


def test_a_self_including_file_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "loop.tex"
    root.write_text("\\begin{document}\n\\input{loop}\n\\end{document}\n", encoding="utf-8")
    with pytest.raises(IngestError, match="more than once"):
        ingest(root)


# What is not prose --------------------------------------------------------


def test_math_never_appears_in_sentences(paper: Document) -> None:
    joined = sentence_text(paper)
    assert "\\mathrm{idf}" not in joined
    assert "\\sum_{t \\in q}" not in joined
    assert len(paper.floats_of_kind(FloatKind.EQUATION)) == 1


def test_protected_environments_never_appear_in_sentences(paper: Document) -> None:
    joined = sentence_text(paper)
    for fragment in ("BM25+QE", "\\toprule", "includegraphics", "\\begin{", "\\end{"):
        assert fragment not in joined, f"{fragment!r} leaked into prose"
    assert len(paper.floats_of_kind(FloatKind.FIGURE)) == 1
    assert len(paper.floats_of_kind(FloatKind.TABLE)) == 1


def test_the_preamble_is_not_prose(paper: Document) -> None:
    joined = sentence_text(paper)
    assert "documentclass" not in joined
    assert "usepackage" not in joined


def test_title_and_author_become_metadata(paper: Document) -> None:
    assert paper.metadata["title"] == "Sparse Retrieval Still Wins at Equal Cost"
    assert paper.metadata["author"] == "A. Researcher"


def test_full_line_comments_are_dropped_and_trailing_ones_are_frozen(paper: Document) -> None:
    joined = sentence_text(paper)
    assert "note to my co-author" not in joined, "a full-line comment is not prose"

    assert "soften this" not in joined, "a comment is never a claim sentence"

    trailing = next(region for region in paper.protected if "soften this" in paper.text_of(region))
    assert paper.text_of(trailing).startswith("%")
    assert not paper.is_patchable(trailing)


def test_section_titles_are_not_claim_sentences(paper: Document) -> None:
    joined = sentence_text(paper)
    assert "\\section" not in joined
    assert not any(s.text.strip() == "Introduction" for s in paper.sentences)


def test_list_items_lose_their_markers(paper: Document) -> None:
    items = [s.text for s in paper.sentences if s.text.startswith("Sparse retrieval")]
    assert len(items) == 2
    assert not any(text.startswith("\\item") for text in items)


def test_inline_math_stays_inside_its_sentence(paper: Document) -> None:
    holder = next(s for s in paper.sentences if "$k_1 = 0.9$" in s.text and "fixed" in s.text)
    assert holder.text.endswith("throughout, and Eq.~\\ref{eq:score} is unchanged.")


def test_a_ref_does_not_split_a_sentence(paper: Document) -> None:
    holder = next(s for s in paper.sentences if "hold the index size constant" in s.text)
    assert "Fig.~\\ref{fig:budget}" in holder.text


# Citations ----------------------------------------------------------------


def test_multi_key_cite_becomes_one_citation_per_key(paper: Document) -> None:
    used = [c for c in paper.citations if not c.in_bibliography]
    keys = [c.key for c in used]
    assert "smith2021" in keys
    assert "nakamura2023" in keys

    same_span = [c for c in used if c.key in {"smith2021", "nakamura2023"}]
    assert len({(c.span.char_start, c.span.char_end) for c in same_span}) == 1


def test_citet_is_recognised(paper: Document) -> None:
    used = {c.key for c in paper.citations if not c.in_bibliography}
    assert "chen2024" in used


def test_a_citation_attaches_to_the_claim_it_supports(paper: Document) -> None:
    used = next(c for c in paper.citations if c.key == "smith2021" and not c.in_bibliography)
    claim = paper.sentence(used.sentence_id or "")
    assert "Dense encoders are reported to beat sparse baselines" in claim.text


def test_bib_entries_carry_metadata_for_verification(paper: Document) -> None:
    entries = {c.key: c for c in paper.citations if c.in_bibliography}
    assert set(entries) == {"smith2021", "nakamura2023", "chen2024"}

    smith = entries["smith2021"].resolved
    assert smith is not None
    assert smith.title == "A Survey of Retrieval"
    assert smith.year == 2021
    assert smith.doi == "10.1145/1234.5678"
    assert smith.authors == ("Smith, Jane", "Lee, Kim")
    assert smith.source == "bibtex"


def test_a_missing_bib_file_fails_loudly(tmp_path: Path) -> None:
    root = tmp_path / "main.tex"
    root.write_text(
        "\\begin{document}\nProse here.\n\\bibliography{absent}\n\\end{document}\n",
        encoding="utf-8",
    )
    with pytest.raises(IngestError, match="Citation verification has nothing"):
        ingest(root)


def test_thebibliography_entries_are_read(tmp_path: Path) -> None:
    root = tmp_path / "main.tex"
    root.write_text(
        "\\begin{document}\n"
        "A claim \\cite{one}.\n\n"
        "\\begin{thebibliography}{9}\n"
        "\\bibitem{one} Smith, J. A Survey. 2021.\n"
        "\\bibitem{two} Lee, K. Another. 2022.\n"
        "\\end{thebibliography}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    document = ingest(root)
    entries = [c for c in document.citations if c.in_bibliography]
    assert [c.key for c in entries] == ["one", "two"]
    assert "Smith, J. A Survey." in entries[0].raw
    assert all(c.sentence_id is None for c in entries)


# Compile safety -----------------------------------------------------------


def test_a_patch_overlapping_math_is_rejected(paper: Document) -> None:
    math = next(region for region in paper.protected if paper.text_of(region).startswith("$k_1"))
    with pytest.raises(ProtectedRangeError, match="break the build"):
        paper.assert_patchable(math, "a rewrite of the inline term")


def test_a_patch_overlapping_a_ref_argument_is_rejected(paper: Document) -> None:
    offset = paper.source_text.index("\\ref{fig:budget}")
    span = Span(char_start=offset, char_end=offset + len("\\ref{fig:budget}"))
    assert not paper.is_patchable(span)
    with pytest.raises(ProtectedRangeError):
        paper.assert_patchable(span)


def test_a_patch_overlapping_an_environment_delimiter_is_rejected(paper: Document) -> None:
    offset = paper.source_text.index("\\begin{equation}")
    span = Span(char_start=offset, char_end=offset + 5)
    assert not paper.is_patchable(span)


def test_a_patch_on_ordinary_prose_is_allowed(paper: Document) -> None:
    plain = next(s for s in paper.sentences if "The scoring function above is unchanged" in s.text)
    assert paper.is_patchable(plain.span)
    paper.assert_patchable(plain.span)


def test_protected_ranges_cover_every_command_name(paper: Document) -> None:
    for command in ("\\section", "\\cite", "\\label", "\\includegraphics"):
        offset = paper.source_text.index(command)
        span = Span(char_start=offset, char_end=offset + len(command))
        assert not paper.is_patchable(span), f"{command} is editable, which would break the build"


# Extras gating ------------------------------------------------------------


def test_ingest_without_the_latex_extra_names_the_install_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    real_import = importlib.import_module

    def refuse(name: str, package: str | None = None) -> object:
        if name == "bibtexparser":
            raise ImportError("no bibtexparser")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", refuse)
    with pytest.raises(MissingExtraError, match=r'pip install "research-better\[latex\]"'):
        ingest(PAPER)


# Structure ----------------------------------------------------------------


def test_every_sentence_recovers_its_source_exactly(paper: Document) -> None:
    for sentence in paper.sentences:
        assert paper.text_of(sentence.span) == sentence.text


def test_no_sentence_overlaps_a_float(paper: Document) -> None:
    for sentence in paper.sentences:
        for item in paper.floats:
            assert not sentence.span.overlaps(item.span), (
                f"{sentence.text!r} overlaps a {item.kind}"
            )


def test_unbalanced_braces_fail_loudly(tmp_path: Path) -> None:
    root = tmp_path / "main.tex"
    root.write_text("\\begin{document}\n\\section{Open\nProse.\n", encoding="utf-8")
    with pytest.raises(IngestError, match="unbalanced braces"):
        ingest(root)


def test_an_unclosed_environment_fails_loudly(tmp_path: Path) -> None:
    root = tmp_path / "main.tex"
    root.write_text("\\begin{document}\n\\begin{table}\nrows\n", encoding="utf-8")
    with pytest.raises(IngestError, match="never closed"):
        ingest(root)
