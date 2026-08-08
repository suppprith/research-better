"""Golden coverage for every pass, and the guarantees the fixture exists to hold.

The list of passes grows as passes land. A pass without a golden file is a pass
whose behaviour nobody can review a change to, so the registry check fails
rather than skipping.
"""

from __future__ import annotations

import re

import pytest

from conftest import GOOD_PARAGRAPH_OPENER
from golden_harness import Golden, GoldenMismatchError, diff
from research_better import fluff, voice
from research_better.model import Document

PASSES = ("ingest", "fluff", "voice")
"""Every pass that produces a reviewable artifact. Extended as passes land."""


def summarize_ingest(document: Document) -> dict[str, object]:
    """A stable view of ingest output. Offsets are excluded on purpose: a
    reworded paragraph would shift every one of them and bury the real change."""
    return {
        "metadata": document.metadata,
        "sections": [
            {"title": section.title, "level": section.level, "path": list(section.path)}
            for section in document.sections
        ],
        "sentences": [
            {"id": sentence.id, "section": sentence.section_id, "text": sentence.text}
            for sentence in document.sentences
        ],
        "citations": [
            {"key": citation.key, "in_bibliography": citation.in_bibliography}
            for citation in document.citations
        ],
        "floats": [{"kind": str(item.kind), "label": item.label} for item in document.floats],
    }


def test_ingest_matches_its_golden(bad_paper: Document, golden: Golden) -> None:
    golden.check("ingest", summarize_ingest(bad_paper))


def test_fluff_matches_its_golden(bad_paper: Document, golden: Golden) -> None:
    golden.check("fluff", [finding.to_json() for finding in fluff.analyse(bad_paper)])


def test_voice_matches_its_golden(bad_paper: Document, golden: Golden) -> None:
    golden.check("voice", voice.extract(bad_paper).to_json())


def test_every_pass_has_a_golden_file(golden: Golden) -> None:
    missing = [name for name in PASSES if not golden.path_for(name).exists()]
    assert not missing, f"passes with no golden file: {', '.join(missing)}"


# The fixture's own guarantees ---------------------------------------------


def test_the_good_paragraph_is_findable(
    bad_paper: Document, good_paragraph_ids: frozenset[str]
) -> None:
    assert len(good_paragraph_ids) == 4, "the paragraph that must survive has four sentences"
    opener = next(s for s in bad_paper.sentences if s.id in good_paragraph_ids)
    assert opener.text.startswith(GOOD_PARAGRAPH_OPENER)


def test_the_good_paragraph_has_varied_sentence_lengths(
    bad_paper: Document, good_paragraph_ids: frozenset[str]
) -> None:
    lengths = [len(s.text.split()) for s in bad_paper.sentences if s.id in good_paragraph_ids]
    assert max(lengths) - min(lengths) >= 10, "it must not read as uniform rhythm"


def test_the_fixture_carries_its_planted_defects(bad_paper: Document) -> None:
    # Sentences keep their source line breaks, so compare against rewrapped text.
    joined = re.sub(r"\s+", " ", " ".join(s.text for s in bad_paper.sentences))
    for planted in (
        "It is important to note that",
        "may potentially suggest",
        "performed an analysis of",
        "significantly outperforms",
        "efficient, scalable, and robust",
        "Not only does it reduce latency",
        "As will be discussed later",
    ):
        assert planted in joined, f"the fixture lost its planted {planted!r}"


def test_the_fixture_has_five_reference_entries(bad_paper: Document) -> None:
    entries = [c for c in bad_paper.citations if c.in_bibliography]
    assert [entry.key for entry in entries] == ["1", "2", "3", "4", "5"]


# The harness itself -------------------------------------------------------


def test_diff_reports_a_changed_leaf() -> None:
    assert diff({"rule": "hedge"}, {"rule": "filler"}) == ['rule: "hedge" -> "filler"']


def test_diff_reports_added_and_removed_keys() -> None:
    problems = diff({"a": 1}, {"b": 2})
    assert any("missing from actual" in line for line in problems)
    assert any("only in actual" in line for line in problems)


def test_diff_reports_list_length_and_element_changes() -> None:
    problems = diff([1, 2, 3], [1, 9])
    assert problems[0] == "(root): length 3 -> 2"
    assert any("[1]" in line for line in problems)
    assert any("[2]" in line for line in problems)


def test_diff_is_empty_for_equal_structures() -> None:
    payload = {"findings": [{"rule": "a", "severity": "high"}]}
    assert diff(payload, {"findings": [{"rule": "a", "severity": "high"}]}) == []


def test_diff_names_a_type_change() -> None:
    assert "type changed" in diff({"n": 1}, {"n": "1"})[0]


def test_a_mismatch_explains_how_to_regenerate(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import golden_harness

    monkeypatch.setattr(golden_harness, "GOLDEN_DIR", tmp_path)
    writer = Golden(update=True)
    writer.check("demo", {"value": 1})

    reader = Golden(update=False)
    with pytest.raises(GoldenMismatchError, match="--update-golden"):
        reader.check("demo", {"value": 2})


def test_a_new_golden_is_written_but_still_fails(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import golden_harness

    monkeypatch.setattr(golden_harness, "GOLDEN_DIR", tmp_path)
    checker = Golden(update=False)
    # Writing the file and passing would let a pass ship with nobody having read
    # its output once.
    with pytest.raises(GoldenMismatchError, match="confirm it is what the pass should produce"):
        checker.check("fresh", {"value": 1})
    assert (tmp_path / "fresh.json").exists()
