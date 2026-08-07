"""Span ids have to survive the author editing the paper between runs.

Every artifact this tool writes names span ids. If an id moves when unrelated
text changes, findings from an earlier pass silently point at the wrong
sentence, which is worse than having no findings at all.
"""

from __future__ import annotations

from conftest import BuildDocument
from research_better.model import Document
from research_better.spans import IdAllocator, digest, normalize, section_path_key

PAPER = """\
# Introduction

Retrieval quality has plateaued on this benchmark. We show that a sparse
index still beats a dense one at equal cost.

# Method

We index the corpus with BM25. Queries are expanded with the top three
terms from a first-pass retrieval.

# Results

Recall at ten improves by four points. The gain holds across all splits.
"""


def ids(document: Document) -> list[str]:
    return [sentence.id for sentence in document.sentences]


def test_reingest_produces_identical_ids(build_document: BuildDocument) -> None:
    first = build_document(PAPER)
    second = build_document(PAPER)
    assert ids(first) == ids(second)
    assert first.source_hash == second.source_hash


def test_editing_one_sentence_leaves_every_other_id_unchanged(
    build_document: BuildDocument,
) -> None:
    before = build_document(PAPER)
    edited = PAPER.replace(
        "Recall at ten improves by four points.",
        "Recall at ten improves by six points.",
    )
    after = build_document(edited)

    changed = set(ids(before)) ^ set(ids(after))
    assert len(changed) == 2, "exactly one id should have left and one arrived"

    unchanged = set(ids(before)) & set(ids(after))
    assert len(unchanged) == len(before.sentences) - 1


def test_inserting_a_sentence_does_not_renumber_the_rest(
    build_document: BuildDocument,
) -> None:
    before = build_document(PAPER)
    inserted = PAPER.replace(
        "We index the corpus with BM25.",
        "We index the corpus with BM25. Stopwords are kept.",
    )
    after = build_document(inserted)

    # This is the case a running counter gets wrong: every id after the
    # insertion point would shift, invalidating every prior finding.
    assert set(ids(before)).issubset(set(ids(after)))
    assert len(after.sentences) == len(before.sentences) + 1


def test_rewrapping_a_paragraph_does_not_change_ids(build_document: BuildDocument) -> None:
    before = build_document(PAPER)
    original_wrap = (
        "Retrieval quality has plateaued on this benchmark. We show that a sparse\n"
        "index still beats a dense one at equal cost."
    )
    new_wrap = (
        "Retrieval quality has plateaued on this benchmark.\n"
        "We show that a sparse index still beats a dense one at equal cost."
    )
    after = build_document(PAPER.replace(original_wrap, new_wrap))
    assert ids(before) == ids(after)


def test_same_sentence_under_different_headings_gets_different_ids(
    build_document: BuildDocument,
) -> None:
    document = build_document("# One\n\nThe result holds.\n\n# Two\n\nThe result holds.\n")
    assert len(document.sentences) == 2
    assert document.sentences[0].id != document.sentences[1].id


def test_repeated_sentence_under_one_heading_is_disambiguated() -> None:
    allocator = IdAllocator()
    first = allocator.allocate("s", "The result holds.", "Method")
    second = allocator.allocate("s", "The result holds.", "Method")
    third = allocator.allocate("s", "The result holds.", "Method")
    assert first != second != third
    assert second == f"{first}.1"
    assert third == f"{first}.2"


def test_normalize_collapses_whitespace_only() -> None:
    assert normalize("  The   result\nholds.  ") == "The result holds."
    assert normalize("The Result") != normalize("the result")


def test_digest_is_stable_and_field_separated() -> None:
    assert digest("a", "b") == digest("a", "b")
    # Without a separator these two would hash the same, which would let a
    # sentence collide with a section title.
    assert digest("ab", "") != digest("a", "b")


def test_section_path_key_normalizes_each_title() -> None:
    assert section_path_key(["  Method ", "Setup\n"]) == "Method > Setup"
