"""The reference pack: one file per pass, loaded on demand.

These are read by a model and by contributors, so the repo writing rules apply
to them and size is a real constraint. A reference file padded with restatement
burns the context the paper itself needs.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import pytest

REFERENCES = Path(str(files("research_better").joinpath("references")))

# One file, one pass. A reference loaded by two passes is knowledge that
# belongs somewhere else.
OWNERS = {
    "novelty-audit.md": "novelty",
    "grounding-protocol.md": "grounding",
    "fluff-lexicon.md": "fluff",
    "reviewer-questions.md": "reviewer",
    "voice-preservation.md": "edit",
    "originality-boilerplate.md": "originality",
    "rhythm-thresholds.toml": "fluff",
    "source-limits.toml": "net",
    "venue-profiles.md": "reviewer",
}

MAXIMUM_WORDS = 1400
"""A reference bigger than this is doing more than its pass needs. Review it
rather than raising the number."""


def reference_files() -> list[Path]:
    return sorted(path for path in REFERENCES.iterdir() if path.is_file())


def test_every_reference_file_has_exactly_one_owning_pass() -> None:
    on_disk = {path.name for path in reference_files()}
    assert on_disk == set(OWNERS), "a reference with no owning pass is knowledge with no reader"


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_each_reference_stays_proportionate(name: str) -> None:
    words = len((REFERENCES / name).read_bytes().decode("utf-8").split())
    assert words <= MAXIMUM_WORDS, f"{name} is {words} words, more than its pass needs"


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_no_reference_uses_an_em_dash(name: str) -> None:
    # The tool flags fluff in other people's writing, so its own knowledge
    # files hold the same line. See CONTRIBUTING.md.
    assert chr(0x2014) not in (REFERENCES / name).read_bytes().decode("utf-8")


def test_the_fluff_lexicon_parses_with_no_separate_data_file() -> None:
    from research_better.fluff.lexical import MATCHERS
    from research_better.fluff.structural import LEXICON_FAMILIES
    from research_better.lexicon import load_lexicon

    lexicon = load_lexicon()
    assert lexicon.sections
    assert set(lexicon.families) == set(MATCHERS) | set(LEXICON_FAMILIES)


def test_the_grounding_protocol_states_that_not_found_is_not_an_accusation() -> None:
    text = (REFERENCES / "grounding-protocol.md").read_bytes().decode("utf-8")
    assert "NOT_FOUND is not an accusation" in text
    for banned in ("fabricated", "invented", "made up", "hallucinated"):
        assert banned in text, f"the file must name {banned!r} as a word never to use"


def test_the_novelty_reference_states_the_stop_condition() -> None:
    text = (REFERENCES / "novelty-audit.md").read_bytes().decode("utf-8")
    assert "Stop if there is no claim" in text
    assert "never an orphan" in text


def test_the_reviewer_reference_forbids_answering() -> None:
    text = (REFERENCES / "reviewer-questions.md").read_bytes().decode("utf-8")
    rewrapped = " ".join(text.split())
    assert "Ask. Do not answer." in rewrapped
    assert "a dataset of moderate size" in rewrapped, "the anti-example has to be concrete"


def test_the_voice_reference_leads_with_contrast_pairs() -> None:
    text = (REFERENCES / "voice-preservation.md").read_bytes().decode("utf-8")
    assert "keeps voice" in text
    assert "breaks voice" in text
    # The pairs matter more than the prose.
    assert text.count("Why it holds") >= 2
    assert text.count("Why it breaks") >= 2
