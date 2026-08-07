"""Loader for `references/fluff-lexicon.md`.

The rule terms are data, not code. A contributor who wants to add a filler
opener edits one markdown file and changes no Python, and the skill layer reads
that same file to explain a finding to a user rather than keeping its own copy
that drifts.

The parser is deliberately forgiving about prose. Anything that is not a
heading, a `key: value` line before the first term, or a `- term` is ignored,
so the file can carry its own documentation without a separate format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from research_better.errors import ResearchBetterError
from research_better.findings import Severity, Suggestion

SECTION = re.compile(r"^##\s+(\S.*?)\s*$")
RULE_SECTION_ID = re.compile(r"^[a-z][a-z0-9_]*$")
"""A rule section is named like an identifier. Anything else under a `##` is
documentation, which lets the file explain itself without a second format."""
KEY_VALUE = re.compile(r"^([a-z_]+):\s*(.*?)\s*$")
TERM = re.compile(r"^-\s+(\S.*?)\s*$")
REPLACEMENT = re.compile(r"^(.*?)\s+->\s+(.*)$")

DEFAULT_LEXICON = "fluff-lexicon.md"


class LexiconError(ResearchBetterError):
    """The lexicon file is present but cannot be read as a rule set."""


@dataclass(frozen=True, slots=True)
class Term:
    phrase: str
    replacement: str | None = None


@dataclass(frozen=True, slots=True)
class RuleSection:
    """One `##` block: a set of terms sharing a matcher and a severity."""

    id: str
    family: str
    severity: Severity
    suggestion: Suggestion
    note: str | None
    terms: tuple[Term, ...]

    def suggestion_for(self, term: Term) -> Suggestion:
        return Suggestion.REPLACE_WITH if term.replacement else self.suggestion


@dataclass(frozen=True, slots=True)
class Lexicon:
    sections: tuple[RuleSection, ...] = ()
    _by_family: dict[str, list[RuleSection]] = field(
        default_factory=dict, repr=False, compare=False, init=False
    )

    def __post_init__(self) -> None:
        for section in self.sections:
            self._by_family.setdefault(section.family, []).append(section)

    def family(self, name: str) -> tuple[RuleSection, ...]:
        return tuple(self._by_family.get(name, ()))

    def section(self, section_id: str) -> RuleSection:
        for section in self.sections:
            if section.id == section_id:
                return section
        raise LexiconError(f"no lexicon section named {section_id!r}")

    @property
    def families(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_family))


def parse_lexicon(text: str) -> Lexicon:
    sections: list[RuleSection] = []
    current: dict[str, str] | None = None
    terms: list[Term] = []

    def close() -> None:
        if current is None:
            return
        if not terms:
            # A section with no terms is almost always a half-finished edit,
            # and silently matching nothing would hide it until somebody
            # wondered why their new rule never fired.
            raise LexiconError(f"lexicon section {current['id']!r} lists no terms")
        sections.append(
            RuleSection(
                id=current["id"],
                family=current.get("family", current["id"]),
                severity=_severity(current),
                suggestion=_suggestion(current),
                note=current.get("note"),
                terms=tuple(terms),
            )
        )

    for line in text.splitlines():
        heading = SECTION.match(line)
        if heading:
            close()
            title = heading.group(1)
            current = {"id": title} if RULE_SECTION_ID.match(title) else None
            terms = []
            continue

        if current is None:
            continue

        term = TERM.match(line)
        if term:
            replacement = REPLACEMENT.match(term.group(1))
            if replacement:
                terms.append(Term(replacement.group(1), replacement.group(2)))
            else:
                terms.append(Term(term.group(1)))
            continue

        if not terms:
            pair = KEY_VALUE.match(line)
            if pair and pair.group(1) in {"family", "severity", "suggestion", "note"}:
                current[pair.group(1)] = pair.group(2)

    close()

    if not sections:
        raise LexiconError("lexicon contains no rule sections")
    return Lexicon(tuple(sections))


def _severity(section: dict[str, str]) -> Severity:
    raw = section.get("severity", "medium")
    try:
        return Severity(raw)
    except ValueError:
        raise LexiconError(
            f"section {section['id']!r} has severity {raw!r}, expected one of "
            f"{', '.join(s.value for s in Severity)}"
        ) from None


def _suggestion(section: dict[str, str]) -> Suggestion:
    raw = section.get("suggestion", "review")
    try:
        return Suggestion(raw)
    except ValueError:
        raise LexiconError(
            f"section {section['id']!r} has suggestion {raw!r}, expected one of "
            f"{', '.join(s.value for s in Suggestion)}"
        ) from None


def lexicon_path() -> Path:
    """Where the shipped lexicon lives, inside the installed package."""
    return Path(str(files("research_better").joinpath("references", DEFAULT_LEXICON)))


@lru_cache(maxsize=4)
def load_lexicon(path: Path | None = None) -> Lexicon:
    target = path or lexicon_path()
    if not target.is_file():
        raise LexiconError(f"lexicon not found at {target}")
    return parse_lexicon(target.read_bytes().decode("utf-8"))
