"""Citation recognition, and the things that look like citations but are not."""

from __future__ import annotations

from research_better.ingest.citations import find_citations, protected_ranges


def keys(text: str) -> list[str]:
    return [citation.key for citation in find_citations(text)]


def test_a_markdown_link_is_not_a_citation() -> None:
    assert keys("See [1](https://example.org/docs) for the API.") == []


def test_numeric_ranges_expand_to_one_key_each() -> None:
    assert keys("Prior work [1, 3-5] disagrees.") == ["1", "3", "4", "5"]


def test_an_absurd_range_is_kept_verbatim() -> None:
    # A four-digit span is a typo or a year, not a citation range. Guessing
    # would invent hundreds of keys to go verify.
    assert keys("Reported in [1-2000].") == ["1-2000"]


def test_multiple_pandoc_keys_in_one_bracket() -> None:
    assert keys("As argued [@smith2020; @lee2021].") == ["lee2021", "smith2020"]


def test_suppressed_author_form_keeps_the_key() -> None:
    assert keys("Smith says so [-@smith2020].") == ["smith2020"]


def test_doi_forms() -> None:
    assert keys("See doi:10.1145/1234.5678 and https://doi.org/10.1000/xyz") == [
        "10.1145/1234.5678",
        "10.1000/xyz",
    ]


def test_arxiv_forms() -> None:
    assert keys("arXiv:2401.01234v2 and https://arxiv.org/abs/2312.00001") == [
        "arXiv:2401.01234v2",
        "arXiv:2312.00001",
    ]


def test_offsets_point_at_the_raw_match() -> None:
    text = "Prior work [7] showed it."
    found = find_citations(text)[0]
    assert text[found.start : found.end] == "[7]" == found.raw


def test_protected_ranges_cover_urls_and_brackets() -> None:
    text = "See https://doi.org/10.1145/1.2 and [1] for details."
    covered = [text[start:end] for start, end in protected_ranges(text)]
    assert any("doi.org" in piece for piece in covered)
    assert "[1]" in covered


def test_text_without_citations_yields_nothing() -> None:
    assert find_citations("A plain sentence with no references at all.") == []
    assert protected_ranges("A plain sentence.") == []
