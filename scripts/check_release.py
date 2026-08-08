"""Refuse a release whose tag, version, and changelog do not agree.

Three ways to publish something wrong, all of them permanent because PyPI does
not let a version be replaced:

* A tag that does not match the version in the package, so `pip install
  research-better==0.2.0` gives you something that reports 0.1.0.
* A version already on PyPI, which fails at the last step after everything
  else has succeeded.
* A release with no changelog entry, which is how a breaking change reaches
  people who had no way to see it coming.

All three are cheap to check before the build and impossible to fix after the
upload, so they are checked first.

    python scripts/check_release.py v0.1.0
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from research_better import __version__  # noqa: E402

CHANGELOG = ROOT / "CHANGELOG.md"

SECTION = re.compile(r"^##\s+\[?(?P<version>[0-9][^\]\s]*)\]?", re.MULTILINE)


def notes_for(version: str) -> str | None:
    """The changelog body for one version, or None if it has no section."""
    text = CHANGELOG.read_text(encoding="utf-8")
    matches = list(SECTION.finditer(text))
    for index, match in enumerate(matches):
        if match.group("version") != version:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        return text[match.end() : end].strip()
    return None


def check(tag: str) -> list[str]:
    problems: list[str] = []
    version = tag.removeprefix("v")

    if version != __version__:
        problems.append(
            f"tag {tag} does not match __version__ {__version__}. "
            f"Set the version in src/research_better/__init__.py first: it is the "
            f"single source of truth and the wheel, the CLI, and the skill check all "
            f"read it."
        )

    if not CHANGELOG.is_file():
        problems.append(f"{CHANGELOG.name} does not exist")
        return problems

    notes = notes_for(version)
    if notes is None:
        problems.append(
            f"{CHANGELOG.name} has no section for {version}. A release nobody can read "
            f"the changes of is how a breaking change reaches people with no warning."
        )
    elif not notes:
        problems.append(f"the {version} section of {CHANGELOG.name} is empty")

    return problems


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_release.py <tag>", file=sys.stderr)
        return 2

    problems = check(sys.argv[1])
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1

    print(f"{sys.argv[1]} is ready: version, tag, and changelog agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
