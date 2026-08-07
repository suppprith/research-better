"""Golden-file comparison with diffs a human can read.

A pass produces a nested structure. Asserting on it inline means every change
to the structure edits a dozen tests, and dumping both sides on failure means
reading two hundred lines of JSON to find one changed field. So the payload
goes to a file, and a mismatch is reported as a list of paths that differ.

Regenerate deliberately:

    pytest --update-golden

Never regenerate to make a red test green. The point of a golden file is that
somebody has to look at the diff and agree with it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOLDEN_DIR = Path(__file__).parent / "golden"

MISSING = object()


class GoldenMismatchError(AssertionError):
    pass


def _format(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 120 else text[:117] + "..."


def diff(expected: Any, actual: Any, path: str = "") -> list[str]:
    """Paths where two JSON-able structures differ, deepest difference first."""
    where = path or "(root)"

    if expected is MISSING:
        return [f"{where}: unexpected, only in actual: {_format(actual)}"]
    if actual is MISSING:
        return [f"{where}: missing from actual: {_format(expected)}"]

    if type(expected) is not type(actual):
        return [
            f"{where}: type changed, "
            f"{type(expected).__name__} -> {type(actual).__name__} ({_format(actual)})"
        ]

    if isinstance(expected, dict):
        problems: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            problems.extend(
                diff(
                    expected.get(key, MISSING),
                    actual.get(key, MISSING),
                    f"{path}.{key}" if path else str(key),
                )
            )
        return problems

    if isinstance(expected, list):
        problems = []
        if len(expected) != len(actual):
            problems.append(f"{where}: length {len(expected)} -> {len(actual)}")
        for index in range(max(len(expected), len(actual))):
            problems.extend(
                diff(
                    expected[index] if index < len(expected) else MISSING,
                    actual[index] if index < len(actual) else MISSING,
                    f"{path}[{index}]",
                )
            )
        return problems

    if expected != actual:
        return [f"{where}: {_format(expected)} -> {_format(actual)}"]
    return []


class Golden:
    """Compares a payload against its stored copy, or rewrites it on request."""

    def __init__(self, update: bool) -> None:
        self.update = update

    def path_for(self, name: str) -> Path:
        return GOLDEN_DIR / f"{name}.json"

    def check(self, name: str, payload: Any) -> None:
        target = self.path_for(name)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

        if self.update or not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(serialized, encoding="utf-8")
            if not self.update:
                raise GoldenMismatchError(
                    f"No golden file for {name!r}. One was written to {target}. "
                    f"Read it, confirm it is what the pass should produce, and commit it."
                )
            return

        expected = json.loads(target.read_text(encoding="utf-8"))
        problems = diff(expected, payload)
        if problems:
            shown = "\n  ".join(problems[:25])
            more = f"\n  ...and {len(problems) - 25} more" if len(problems) > 25 else ""
            raise GoldenMismatchError(
                f"{name} differs from {target.name} in {len(problems)} place(s):\n"
                f"  {shown}{more}\n\n"
                f"If the new behaviour is correct, rerun with --update-golden and "
                f"commit the diff so a reviewer sees exactly what changed."
            )
