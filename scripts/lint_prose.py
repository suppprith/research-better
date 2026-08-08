"""Check the repository's own writing against the rules in CONTRIBUTING.md.

A tool that flags fluff while emitting fluff is not credible, so the rules apply
to this repository too, and the filler-opener list is the tool's own: the lint
reads the shipped lexicon rather than keeping a copy that drifts from it. A
phrase this tool tells authors to cut cannot sit in its README.

Only mechanically checkable rules live here. The rest is review.

Three exemptions, and each is the same reason in a different place: sample input
is allowed to contain the writing this tool exists to find. Test fixtures, the
committed example output, and the lexicon itself, which is a list of the phrases
and would otherwise report every one of them.

Fenced code blocks are skipped in Markdown. A block quoting real output is
evidence rather than prose, and rewording it to satisfy a lint would make the
documentation wrong.

Run it directly:

    python scripts/lint_prose.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from research_better.lexicon import load_lexicon

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
    "examples",
    "node_modules",
    "tests",
    "venv",
}

SKIPPED_FILES = {
    # The list of filler openers, which would report every entry in it.
    "src/research_better/references/fluff-lexicon.md",
    # A before-and-after table. The "before" column is the writing being cut.
    "src/research_better/references/voice-preservation.md",
    # Carries a deliberately bad paragraph as sample input for the smoke test.
    "scripts/smoke_test.py",
}

FENCE = re.compile(r"^\s*(```|~~~)")


def filler_openers() -> list[str]:
    """The tool's own list, read from the lexicon it ships."""
    return [
        term.phrase for section in load_lexicon().family("filler_opener") for term in section.terms
    ]


def _prose_lines(path: Path, lines: list[str]) -> list[tuple[int, str]]:
    """Numbered lines outside any fenced code block."""
    if path.suffix != ".md":
        return list(enumerate(lines, start=1))

    kept: list[tuple[int, str]] = []
    inside = False
    for number, line in enumerate(lines, start=1):
        if FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            kept.append((number, line))
    return kept


def iter_checked_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in CHECKED_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if SKIPPED_DIRECTORIES.intersection(relative.parts[:-1]):
            continue
        if relative.as_posix() in SKIPPED_FILES:
            continue
        yield path


def check(root: Path) -> list[str]:
    openers = [
        (phrase, re.compile(r"\b" + r"\s+".join(map(re.escape, phrase.split())) + r"\b", re.I))
        for phrase in filler_openers()
    ]

    problems: list[str] = []
    for path in iter_checked_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(root).as_posix()

        for number, line in enumerate(lines, start=1):
            for character, reason in BANNED_CHARACTERS.items():
                if character in line:
                    problems.append(f"{relative}:{number}: {reason}")

        for number, line in _prose_lines(path, lines):
            for phrase, pattern in openers:
                found = pattern.search(line)
                if found and not _quoted(line, found.start()):
                    problems.append(
                        f"{relative}:{number}: filler opener {phrase!r}. It announces a "
                        f"sentence instead of making a claim, and the sentence reads the "
                        f"same without it."
                    )
    return problems


def _quoted(line: str, at: int) -> bool:
    """Whether an offset sits inside quotation marks on its own line.

    A rule that names the phrase it forbids has to be able to write it down.
    An odd number of quote marks before the match means the match is inside
    the pair, which is close enough on a single line.
    """
    return line.count('"', 0, at) % 2 == 1


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
