"""Loader for `references/rhythm-thresholds.toml`.

Kept separate from the lexicon because these are numbers rather than terms, and
numbers carry an obligation the terms do not: a threshold has to be traceable
to a corpus statistic or to a definition. This module enforces that a rule
cannot be enabled without a `source` saying which.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from research_better.errors import ResearchBetterError

DEFAULT_THRESHOLDS = "rhythm-thresholds.toml"

UNCALIBRATED_PREFIX = "not calibrated"


class ThresholdError(ResearchBetterError):
    """The threshold file is present but not usable as a rule configuration."""


@dataclass(frozen=True, slots=True)
class RuleThresholds:
    """One rule's configuration, and the justification for its numbers."""

    rule: str
    enabled: bool
    source: str
    values: dict[str, float]

    def number(self, key: str) -> float:
        try:
            return self.values[key]
        except KeyError:
            raise ThresholdError(f"rule {self.rule!r} has no threshold named {key!r}") from None

    @property
    def calibrated(self) -> bool:
        return not self.source.startswith(UNCALIBRATED_PREFIX)


@dataclass(frozen=True, slots=True)
class Thresholds:
    rules: dict[str, RuleThresholds]

    def for_rule(self, rule: str) -> RuleThresholds:
        try:
            return self.rules[rule]
        except KeyError:
            raise ThresholdError(f"no threshold section for rule {rule!r}") from None

    def enabled(self, rule: str) -> bool:
        return self.rules[rule].enabled if rule in self.rules else False

    @property
    def disabled_for_want_of_a_corpus(self) -> tuple[str, ...]:
        """Rules that are off because nobody has run the calibration script.

        Surfaced so the report can say what was not checked rather than letting
        the author assume silence means clean.
        """
        return tuple(sorted(name for name, rule in self.rules.items() if not rule.calibrated))


def parse_thresholds(data: dict[str, Any]) -> Thresholds:
    rules: dict[str, RuleThresholds] = {}
    for name, section in data.items():
        if not isinstance(section, dict):
            continue
        source = str(section.get("source", "")).strip()
        enabled = bool(section.get("enabled", False))
        if enabled and not source:
            raise ThresholdError(
                f"rule {name!r} is enabled with no source. Every threshold has to be "
                f"traceable to a corpus statistic or to a definition, or the rule "
                f"flags whatever its author happened to dislike."
            )
        rules[name] = RuleThresholds(
            rule=name,
            enabled=enabled,
            source=source,
            values={
                key: float(value)
                for key, value in section.items()
                if isinstance(value, int | float) and not isinstance(value, bool)
            },
        )
    if not rules:
        raise ThresholdError("threshold file contains no rule sections")
    return Thresholds(rules)


def thresholds_path() -> Path:
    return Path(str(files("research_better").joinpath("references", DEFAULT_THRESHOLDS)))


@lru_cache(maxsize=4)
def load_thresholds(path: Path | None = None) -> Thresholds:
    target = path or thresholds_path()
    if not target.is_file():
        raise ThresholdError(f"threshold file not found at {target}")
    return parse_thresholds(tomllib.loads(target.read_bytes().decode("utf-8")))
