"""Print one version's changelog section, for the release body.

Kept apart from `check_release.py` so the workflow reads the notes from the
same parser that refused to release without them. Two parsers would eventually
disagree about which section belongs to which version, and the release would
carry somebody else's notes.

    python scripts/release_notes.py v0.1.0
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_release import notes_for


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: release_notes.py <tag>", file=sys.stderr)
        return 2

    notes = notes_for(sys.argv[1].removeprefix("v"))
    if notes is None:
        print(f"no changelog section for {sys.argv[1]}", file=sys.stderr)
        return 1

    print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
