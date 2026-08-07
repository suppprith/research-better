"""Check the repository's own writing against the rules in CONTRIBUTING.md.

A tool that flags fluff while emitting fluff is not credible, so the rules apply
to this repository too. Only mechanically checkable rules live here. The rest is
review.

Test fixtures are exempt. A fixture paper is sample input, and sample input is
allowed to contain exactly the writing this tool exists to find.

Run it directly:

    python scripts/lint_prose.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Built with chr() so this file does not trip its own check.
EM_DASH = chr(0x2014)

BANNED_CHARACTERS = {
    EM_DASH: "em dash. Use a comma, a colon, or two sentences.",
}

CHECKED_SUFFIXES = {".py", ".md", ".toml", ".yml", ".yaml", ".txt", ".cfg"}

SKIPPED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".research-better",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "tests",
    "venv",
}


def iter_checked_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in CHECKED_SUFFIXES:
            continue
        if SKIPPED_DIRECTORIES.intersection(path.relative_to(root).parts[:-1]):
            continue
        yield path


def check(root: Path) -> list[str]:
    problems: list[str] = []
    for path in iter_checked_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, start=1):
            for character, reason in BANNED_CHARACTERS.items():
                if character in line:
                    relative = path.relative_to(root).as_posix()
                    problems.append(f"{relative}:{number}: {reason}")
    return problems


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    problems = check(root)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} prose problem(s). See CONTRIBUTING.md.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
