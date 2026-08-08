"""The layer that turns findings into proposed changes.

Everything here is downstream of the evidence gate in `gate`. The gate is what
makes the tool structurally incapable of writing before it has researched: no
edit exists until the analysis artifacts exist, match the current draft, and
carry a contribution claim the author has confirmed.

The gate is enforced in code rather than asked for in a prompt, because an
instruction is a preference and a check is a guarantee.
"""

from __future__ import annotations

from research_better.edit.gate import (
    REQUIRED,
    EvidenceBundle,
    EvidenceGateError,
    MissingEvidenceError,
    Requirement,
    compatible,
    evidence_ids,
    gather,
)

NAME = "edit"

__all__ = [
    "NAME",
    "REQUIRED",
    "EvidenceBundle",
    "EvidenceGateError",
    "MissingEvidenceError",
    "Requirement",
    "compatible",
    "evidence_ids",
    "gather",
]
