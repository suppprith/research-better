"""What a pass produces.

Every pass emits `Finding` objects and nothing else. That uniformity is what
lets the report, the CLI, and the edit pass treat a fluff hit and a broken
citation the same way up to the point where one of them is acted on.

Severity is the whole contract with the edit pass. `high` findings are
mechanical: deleting the matched text leaves a correct sentence, and the
deletion can be applied without judgement. `medium` and `low` go to the human.
Nothing that requires choosing words is ever `high`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Suggestion(StrEnum):
    """What to do about a finding.

    Deletion is the default action wherever a deletion works, because a
    deletion cannot introduce a word the author never wrote. `REPLACE_WITH` is
    permitted only where the replacement comes from a fixed dictionary entry,
    never from generated text. `REVIEW` is the honest answer when neither
    applies: the finding is real, and fixing it needs a decision the tool is
    not entitled to make.
    """

    DELETE = "delete"
    DELETE_CLAUSE = "delete_clause"
    REPLACE_WITH = "replace_with"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class Finding:
    span_id: str
    rule: str
    severity: Severity
    matched_text: str
    char_range: tuple[int, int]
    suggestion: Suggestion
    replacement: str | None = None
    note: str | None = None
    advisory: bool = False
    """The finding rests on a correlation rather than a rule.

    Uniform sentence length correlates with generated text. It does not prove
    it, and some careful human writers are naturally uniform. An advisory
    finding is worth showing to an author and is never worth acting on for
    them, so it can never be auto-applied whatever its severity.
    """

    @property
    def auto_actionable(self) -> bool:
        """Whether the edit pass may apply this without asking.

        All three conditions are load bearing. A high-severity finding whose
        fix needs a word choice is still not something to apply silently, and
        an advisory finding never is regardless of severity.
        """
        return (
            not self.advisory
            and self.severity is Severity.HIGH
            and self.suggestion in {Suggestion.DELETE, Suggestion.DELETE_CLAUSE}
        )

    def to_json(self) -> dict[str, object]:
        return {
            "span_id": self.span_id,
            "rule": self.rule,
            "severity": str(self.severity),
            "matched_text": self.matched_text,
            "char_range": list(self.char_range),
            "suggestion": str(self.suggestion),
            "replacement": self.replacement,
            "note": self.note,
            "advisory": self.advisory,
        }


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Document order, then rule, so output is stable across runs."""
    return sorted(findings, key=lambda f: (f.char_range[0], f.char_range[1], f.rule))
