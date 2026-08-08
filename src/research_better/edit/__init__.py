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
from research_better.edit.ledger import (
    ACCEPT,
    REJECT,
    SKIP,
    Category,
    Dropped,
    Edit,
    Ledger,
    apply_to,
    build,
    load_decisions,
    rejected_ids,
    resolve_overlaps,
    review,
    save_decisions,
    to_diff,
    to_summary,
)
from research_better.edit.voicelock import (
    Budget,
    VoiceLock,
    WordBudgetError,
    assemble,
    screen,
    within_budget,
)

NAME = "edit"

__all__ = [
    "ACCEPT",
    "NAME",
    "REJECT",
    "REQUIRED",
    "SKIP",
    "Budget",
    "Category",
    "Dropped",
    "Edit",
    "EvidenceBundle",
    "EvidenceGateError",
    "Ledger",
    "MissingEvidenceError",
    "Requirement",
    "VoiceLock",
    "WordBudgetError",
    "apply_to",
    "assemble",
    "build",
    "compatible",
    "evidence_ids",
    "gather",
    "load_decisions",
    "rejected_ids",
    "resolve_overlaps",
    "review",
    "save_decisions",
    "screen",
    "to_diff",
    "to_summary",
    "within_budget",
]
