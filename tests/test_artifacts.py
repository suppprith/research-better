"""The artifact store, and the provenance that keeps it honest.

An artifact without the hash of the draft it came from is worse than no
artifact. It looks like current analysis and silently describes text that no
longer exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_better import __version__
from research_better.artifacts import (
    ARTIFACT_DIRECTORY,
    ArtifactStore,
    StaleArtifactError,
)
from research_better.errors import ResearchBetterError


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    draft = tmp_path / "paper.md"
    draft.write_text("# Title\n\nA sentence.\n", encoding="utf-8")
    return ArtifactStore(draft)


def test_the_store_sits_next_to_the_draft(store: ArtifactStore) -> None:
    assert store.root.name == ARTIFACT_DIRECTORY
    assert store.root.parent == store.draft.parent


def test_every_artifact_carries_its_provenance(store: ArtifactStore) -> None:
    target = store.write("fluff", [{"rule": "demo"}], "hash-one")
    written = json.loads(target.read_text(encoding="utf-8"))

    assert written["artifact"] == "fluff"
    assert written["source_hash"] == "hash-one"
    assert written["source_file"] == "paper.md"
    assert written["tool_version"] == __version__
    assert written["created_at"]
    assert written["payload"] == [{"rule": "demo"}]


def test_an_artifact_round_trips(store: ArtifactStore) -> None:
    store.write("voice", {"person": "we"}, "hash-one")
    artifact = store.read("voice")
    assert artifact is not None
    assert artifact.payload == {"person": "we"}
    assert not artifact.is_stale("hash-one")
    assert artifact.is_stale("hash-two")


def test_reading_a_missing_artifact_returns_nothing(store: ArtifactStore) -> None:
    assert store.read("grounding") is None


def test_a_corrupt_artifact_says_so(store: ArtifactStore) -> None:
    store.root.mkdir(parents=True, exist_ok=True)
    store.path_for("fluff").write_text("{not json", encoding="utf-8")
    with pytest.raises(ResearchBetterError, match="not readable as JSON"):
        store.read("fluff")


# Staleness ----------------------------------------------------------------


def test_a_stale_artifact_produces_a_warning_naming_the_file(store: ArtifactStore) -> None:
    store.write("fluff", [], "hash-one")
    warnings = store.stale_warnings("hash-two")
    assert len(warnings) == 1
    assert "fluff.json" in warnings[0]
    assert "paper.md" in warnings[0]
    assert "out of date" in warnings[0]


def test_a_current_artifact_produces_no_warning(store: ArtifactStore) -> None:
    store.write("fluff", [], "hash-one")
    assert store.stale_warnings("hash-one") == []


def test_an_artifact_from_another_draft_is_not_called_stale(tmp_path: Path) -> None:
    first = tmp_path / "one.md"
    second = tmp_path / "two.md"
    for path in (first, second):
        path.write_text("# T\n\nA sentence.\n", encoding="utf-8")

    ArtifactStore(first).write("fluff", [], "hash-one")
    warnings = ArtifactStore(second).stale_warnings("hash-two")

    # Calling it a stale copy of two.md would be a false statement about a file
    # that simply belongs to another paper.
    assert "was produced from one.md, not two.md" in warnings[0]
    assert "overwrite" in warnings[0]


def test_a_different_tool_version_is_reported(store: ArtifactStore) -> None:
    store.write("fluff", [], "hash-one")
    written = json.loads(store.path_for("fluff").read_text(encoding="utf-8"))
    written["tool_version"] = "0.0.1"
    store.path_for("fluff").write_text(json.dumps(written), encoding="utf-8")

    warnings = store.stale_warnings("hash-one")
    assert "0.0.1" in warnings[0]
    assert __version__ in warnings[0]


# require_fresh ------------------------------------------------------------


def test_require_fresh_returns_a_current_artifact(store: ArtifactStore) -> None:
    store.write("fluff", [1], "hash-one")
    assert store.require_fresh("fluff", "hash-one").payload == [1]


def test_require_fresh_refuses_a_stale_artifact(store: ArtifactStore) -> None:
    # A warning is right for reading stale analysis. It is wrong for writing
    # from it, which is what the edit pass does.
    store.write("fluff", [1], "hash-one")
    with pytest.raises(StaleArtifactError, match="patch text that no longer exists"):
        store.require_fresh("fluff", "hash-two")


def test_require_fresh_says_which_pass_to_run(store: ArtifactStore) -> None:
    with pytest.raises(ResearchBetterError, match="Run the grounding pass first"):
        store.require_fresh("grounding", "hash-one")


# Text artifacts -----------------------------------------------------------


def test_a_text_artifact_carries_the_same_provenance(store: ArtifactStore) -> None:
    target = store.write_text("report", "# Findings\n\nNothing yet.\n", "abcdef1234567890ff")
    body = target.read_text(encoding="utf-8")
    assert body.startswith("<!-- research-better")
    assert "source: paper.md" in body
    assert "abcdef1234567890" in body
    assert body.rstrip().endswith("Nothing yet.")


def test_the_cache_lives_inside_the_store(store: ArtifactStore) -> None:
    assert store.cache.parent == store.root
    assert store.cache.name == "cache"
