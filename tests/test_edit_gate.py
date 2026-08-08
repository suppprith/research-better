"""The evidence gate: the check that stops the tool writing before it researches.

The staleness cases carry the most weight. A missing artifact is a loud failure
that anybody would notice. An artifact computed against yesterday's draft
produces suggestions that look entirely reasonable and patch text that is no
longer there, and nothing about the output says so. That is why the gate fails
hard rather than warning.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_better import __version__
from research_better.artifacts import ArtifactStore
from research_better.cli import EXIT_ERROR, main
from research_better.edit import gate
from research_better.edit.gate import (
    REQUIRED,
    EvidenceGateError,
    MissingEvidenceError,
    compatible,
    evidence_ids,
)


@pytest.fixture
def draft(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "bad-paper.md"
    target = tmp_path / "bad-paper.md"
    target.write_bytes(source.read_bytes())
    return target


@pytest.fixture
def ready(draft: Path) -> Path:
    """A draft with every artifact the gate requires, all fresh."""
    main(["novelty", str(draft), "--confirm-claim", "--quiet"])
    main(["ground", str(draft), "--quiet"])
    main(["fluff", str(draft), "--quiet"])
    main(["voice", str(draft), "--quiet"])
    return draft


def rewrite(store: ArtifactStore, name: str, **changes: object) -> None:
    target = store.path_for(name)
    raw = json.loads(target.read_text(encoding="utf-8"))
    raw.update(changes)
    target.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


# The file gate ------------------------------------------------------------


def test_the_gate_passes_once_every_artifact_is_fresh(ready: Path) -> None:
    bundle = gate.gather(ArtifactStore(ready), _hash_of(ready))
    assert set(bundle.artifacts) == {requirement.artifact for requirement in REQUIRED}


@pytest.mark.parametrize("requirement", REQUIRED, ids=lambda r: r.artifact)
def test_deleting_a_required_artifact_names_the_command_that_rebuilds_it(
    ready: Path, requirement: gate.Requirement, capsys: pytest.CaptureFixture[str]
) -> None:
    ArtifactStore(ready).path_for(requirement.artifact).unlink()

    assert main(["edit", str(ready), "--quiet"]) == EXIT_ERROR
    message = capsys.readouterr().err
    assert f"{requirement.artifact}.json" in message
    assert requirement.regenerate(ready.name) in message


def test_one_changed_character_makes_the_gate_fail_as_stale(
    ready: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ready.write_text(ready.read_text(encoding="utf-8").replace("Recall", "Racall", 1))

    assert main(["edit", str(ready), "--quiet"]) == EXIT_ERROR
    message = capsys.readouterr().err
    assert "older version" in message
    # The failure has to name a command, not just a complaint. An author told
    # their artifacts are stale and not told what to run will run everything.
    assert "research-better" in message


def test_staleness_is_reported_as_a_gate_failure_not_a_warning(ready: Path) -> None:
    ready.write_text(ready.read_text(encoding="utf-8") + "\nOne more sentence.\n")

    with pytest.raises(EvidenceGateError) as failure:
        gate.gather(ArtifactStore(ready), _hash_of(ready))
    assert failure.value.reason == "stale"


def test_an_unconfirmed_claim_stops_the_gate(draft: Path) -> None:
    main(["novelty", str(draft), "--quiet"])
    main(["ground", str(draft), "--quiet"])
    main(["fluff", str(draft), "--quiet"])
    main(["voice", str(draft), "--quiet"])

    with pytest.raises(EvidenceGateError) as failure:
        gate.gather(ArtifactStore(draft), _hash_of(draft))
    # If the claim is wrong then every cut measured against it is wrong, and the
    # author is the only one who can say.
    assert failure.value.reason == "unconfirmed"
    assert "--confirm-claim" in str(failure.value)


def test_an_artifact_from_an_incompatible_version_is_refused(ready: Path) -> None:
    rewrite(ArtifactStore(ready), "fluff", tool_version="0.0.1")

    with pytest.raises(EvidenceGateError) as failure:
        gate.gather(ArtifactStore(ready), _hash_of(ready))
    assert failure.value.reason == "version"
    assert failure.value.artifact == "fluff"


def test_a_patch_release_still_reads_its_artifacts() -> None:
    major, minor, _patch = __version__.split(".")
    assert compatible(f"{major}.{minor}.99")
    assert not compatible(f"{major}.{int(minor) + 1}.0")


def test_the_gate_runs_before_the_pass_reports_itself_unbuilt(
    draft: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Told "the edit pass is not built yet" when the real problem is a missing
    # artifact, an author would wait for a release that would not have helped.
    assert main(["edit", str(draft), "--quiet"]) == EXIT_ERROR
    message = capsys.readouterr().err
    assert "novelty.json does not exist" in message
    assert "not built yet" not in message


def test_the_gate_writes_nothing(draft: Path) -> None:
    main(["edit", str(draft), "--quiet"])
    assert not ArtifactStore(draft).path_for("edits").exists()


def test_one_offline_artifact_marks_the_whole_bundle(ready: Path) -> None:
    assert gate.gather(ArtifactStore(ready), _hash_of(ready)).offline is False

    main(["ground", str(ready), "--offline", "--quiet"])
    # Citations checked against a cache is a weaker claim than citations checked
    # against the live literature, and anything written from this bundle has to
    # be able to say which one it was.
    assert gate.gather(ArtifactStore(ready), _hash_of(ready)).offline is True


# Per-edit evidence --------------------------------------------------------


def test_an_edit_with_no_evidence_pointer_is_rejected(ready: Path) -> None:
    bundle = gate.gather(ArtifactStore(ready), _hash_of(ready))
    with pytest.raises(MissingEvidenceError):
        bundle.validate("", "s-abcdef123456")


def test_an_edit_citing_a_record_that_does_not_exist_is_rejected(ready: Path) -> None:
    bundle = gate.gather(ArtifactStore(ready), _hash_of(ready))
    with pytest.raises(MissingEvidenceError, match="editing on a hunch"):
        bundle.validate("fluff:invented_rule@0-1", "s-abcdef123456")


def test_every_fluff_finding_is_citable(ready: Path) -> None:
    store = ArtifactStore(ready)
    bundle = gate.gather(store, _hash_of(ready))
    findings = store.read("fluff")
    assert findings is not None and findings.payload

    for finding in findings.payload:
        start, end = finding["char_range"]
        bundle.validate(f"fluff:{finding['rule']}@{start}-{end}", finding["span_id"])


def test_an_orphan_paragraph_is_citable(ready: Path) -> None:
    store = ArtifactStore(ready)
    bundle = gate.gather(store, _hash_of(ready))
    novelty = store.read("novelty")
    assert novelty is not None

    for orphan in novelty.payload["orphans"]:
        bundle.validate(f"novelty:orphan:{orphan['span_id']}", orphan["span_id"])


def test_a_citation_check_is_citable(ready: Path) -> None:
    store = ArtifactStore(ready)
    bundle = gate.gather(store, _hash_of(ready))
    grounding = store.read("grounding")
    assert grounding is not None

    for check in grounding.payload["citations"]["checks"]:
        bundle.validate(f"grounding:citation:{check['key']}", "s-abcdef123456")


def test_the_voice_profile_justifies_nothing(ready: Path) -> None:
    store = ArtifactStore(ready)
    profile = store.read("voice")
    assert profile is not None
    # A voice profile says what an edit may sound like. An edit whose only
    # reason is "this does not sound like you" is a rewrite in a checker's coat.
    assert evidence_ids("voice", profile.payload) == set()


def test_pointers_survive_a_payload_the_gate_has_never_seen() -> None:
    assert evidence_ids("fluff", None) == set()
    assert evidence_ids("novelty", []) == set()
    assert evidence_ids("nothing-registered", {"anything": 1}) == set()


def _hash_of(draft: Path) -> str:
    from research_better.model import Document

    return Document.hash_source(draft.read_bytes().decode("utf-8"))
