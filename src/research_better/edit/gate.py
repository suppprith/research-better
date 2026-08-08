"""The check that stops the tool writing before it has researched.

This is the core anti-slop control, and the reason it lives in code rather than
in a prompt is that a prompt is a preference and a check is a guarantee. A model
asked nicely to consult the evidence first will usually do it. A command that
refuses to start without four fresh artifacts on disk will always do it.

Two levels of check, and both are load bearing.

**The file gate.** `edit` refuses unless the novelty, grounding, fluff, and
voice artifacts all exist, all carry the hash of the draft as it is on disk
right now, all came from a compatible version of this tool, and the novelty
artifact carries a contribution claim the author confirmed.

The hash is the part worth defending. Without it, an author edits a paragraph,
reruns `edit`, and gets suggestions computed against the previous draft. Those
suggestions would look entirely reasonable and be silently wrong, which makes
staleness the failure most likely to ship unnoticed. So it fails hard, names the
artifact, and prints the command that regenerates it.

**The per-edit gate.** Every proposed edit carries a pointer at the artifact
record that justifies it: a fluff finding, an orphan paragraph, a citation
check, a claim check. An edit with no pointer, or with one naming a record that
is not in the evidence, is rejected before the ledger is written. That is what
stops the tool making a change it merely felt like making.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research_better import __version__
from research_better.artifacts import Artifact, ArtifactStore
from research_better.errors import ResearchBetterError


@dataclass(frozen=True, slots=True)
class Requirement:
    """One artifact `edit` cannot run without, and how to produce it."""

    artifact: str
    command: str
    why: str

    def regenerate(self, draft: str) -> str:
        return f"research-better {self.command} {draft}"


REQUIRED = (
    Requirement(
        artifact="novelty",
        command="novelty --confirm-claim",
        why="nothing can be judged as serving the paper until the claim is known",
    ),
    Requirement(
        artifact="grounding",
        command="ground",
        why="a cut near a citation needs to know whether that citation holds",
    ),
    Requirement(
        artifact="fluff",
        command="fluff",
        why="the deletions come from here",
    ),
    Requirement(
        artifact="voice",
        command="voice",
        why="every proposed change is held to the author's own vocabulary and rhythm",
    ),
)
"""In the order a person would run them. The message names the first failure
only, because a list of four commands is a wall and the author has to run them
in this order anyway."""


class EvidenceGateError(ResearchBetterError):
    """The evidence needed to propose an edit is missing, stale, or unconfirmed."""

    def __init__(self, reason: str, artifact: str, message: str) -> None:
        self.reason = reason
        self.artifact = artifact
        super().__init__(message)


class MissingEvidenceError(ResearchBetterError):
    """An edit was constructed without a pointer at the record justifying it."""

    def __init__(self, pointer: str, span_id: str) -> None:
        self.pointer = pointer
        self.span_id = span_id
        named = f"{pointer!r}" if pointer else "nothing"
        super().__init__(
            f"An edit to span {span_id} cites {named} as its evidence, which is not "
            f"a record in the artifacts this run read. Every change has to point at "
            f"the finding that justifies it, or the tool is editing on a hunch."
        )


def _series(version: str) -> tuple[str, ...]:
    """Major and minor. Artifacts survive a patch release and nothing more.

    Before 1.0 the payload shapes are still moving, so a minor bump is treated
    as a break. Reading a payload whose shape has changed produces findings that
    point at the wrong text, which is the failure this whole module exists to
    prevent.
    """
    return tuple(version.split(".")[:2])


def compatible(tool_version: str) -> bool:
    return _series(tool_version) == _series(__version__)


# Evidence pointers ---------------------------------------------------------
#
# A pointer is `artifact:record`. It is built from the artifact payload on disk
# rather than by rerunning a pass, because the point of the gate is that the
# edit is justified by what was actually written down, not by what the tool
# would say if asked again.


def _fluff_ids(payload: Any) -> set[str]:
    if not isinstance(payload, list):
        return set()
    found = set()
    for finding in payload:
        span = finding.get("char_range") or [0, 0]
        found.add(f"fluff:{finding.get('rule')}@{span[0]}-{span[1]}")
    return found


def _novelty_ids(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    found = {f"novelty:orphan:{orphan.get('span_id')}" for orphan in payload.get("orphans") or ()}
    if payload.get("unsupported_claim_parts"):
        found.add("novelty:unsupported_contribution")
    return found


def _grounding_ids(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    found = set()
    citations = payload.get("citations") or {}
    for check in citations.get("checks") or ():
        found.add(f"grounding:citation:{check.get('key')}")
    claims = payload.get("claims") or {}
    for check in claims.get("checks") or ():
        found.add(f"grounding:claim:{check.get('span_id')}:{check.get('citation_key')}")
    return found


_POINTERS = {
    "fluff": _fluff_ids,
    "novelty": _novelty_ids,
    "grounding": _grounding_ids,
    # Voice deliberately contributes none. A voice profile constrains what an
    # edit may say. It never justifies making one, and an edit whose only reason
    # is "this does not sound like you" is a rewrite wearing a checker's coat.
    "voice": lambda _payload: set(),
}


def evidence_ids(name: str, payload: Any) -> set[str]:
    """Every record in one artifact that an edit is allowed to cite."""
    builder = _POINTERS.get(name)
    return builder(payload) if builder else set()


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """The artifacts an edit run is allowed to reason from, all verified fresh."""

    source_hash: str
    artifacts: dict[str, Artifact]
    pointers: frozenset[str]
    offline: bool
    """True when any artifact in the bundle was produced without network access.
    A run built on cached grounding checked citations against what was cached,
    which is a weaker claim than checking them against the live literature, and
    anything written from this bundle has to be able to say so."""

    def payload(self, name: str) -> Any:
        return self.artifacts[name].payload

    def validate(self, pointer: str, span_id: str) -> None:
        """Refuse an edit whose evidence is absent or names nothing real."""
        if not pointer or pointer not in self.pointers:
            raise MissingEvidenceError(pointer, span_id)


def gather(store: ArtifactStore, source_hash: str) -> EvidenceBundle:
    """Read every required artifact, or refuse and say how to produce it.

    Raises `EvidenceGateError` naming the first artifact that fails and the
    exact command that fixes it.
    """
    draft = store.draft.name
    artifacts: dict[str, Artifact] = {}
    pointers: set[str] = set()
    offline = False

    for requirement in REQUIRED:
        artifact = store.read(requirement.artifact)
        target = store.path_for(requirement.artifact).name

        if artifact is None:
            raise EvidenceGateError(
                "missing",
                requirement.artifact,
                f"{target} does not exist, and {requirement.why}. "
                f"Run: {requirement.regenerate(draft)}",
            )

        if artifact.is_stale(source_hash):
            raise EvidenceGateError(
                "stale",
                requirement.artifact,
                f"{target} was produced from an older version of {draft}. Editing from "
                f"it would patch text that no longer exists, and the suggestions would "
                f"look reasonable while being wrong. "
                f"Run: {requirement.regenerate(draft)}",
            )

        if not compatible(artifact.tool_version):
            raise EvidenceGateError(
                "version",
                requirement.artifact,
                f"{target} was produced by research-better {artifact.tool_version} and "
                f"this is {__version__}. The payload shape may have changed, so it is "
                f"not read. Run: {requirement.regenerate(draft)}",
            )

        artifacts[requirement.artifact] = artifact
        pointers |= evidence_ids(requirement.artifact, artifact.payload)
        offline = offline or artifact.offline

    claim = artifacts["novelty"].payload
    if not (isinstance(claim, dict) and claim.get("claim_confirmed")):
        raise EvidenceGateError(
            "unconfirmed",
            "novelty",
            f"The contribution claim in {store.path_for('novelty').name} has not been "
            f"confirmed. Every cut is measured against that one sentence, so if it is "
            f"wrong then every change below it is wrong too. Read the claim and, if it "
            f"is right, run: "
            f"{Requirement('novelty', 'novelty --confirm-claim', '').regenerate(draft)}",
        )

    return EvidenceBundle(
        source_hash=source_hash,
        artifacts=artifacts,
        pointers=frozenset(pointers),
        offline=offline,
    )
