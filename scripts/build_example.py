"""Run the tool on the fixture paper and commit what it actually printed.

Every output in `examples/` and every command output quoted in the README comes
from here. Nothing is written by hand, and a test regenerates these files and
fails on any difference.

That is not tidiness. A README about verifying claims, carrying example output
somebody typed out from memory, would be refuting itself in its own text. If
the tool's output changes, this repository's documentation is wrong until it is
regenerated, and CI says so.

The run is offline against the recorded responses in `tests/fixtures/http`, so
it produces the same verdicts on any machine and asks nothing of OpenAlex.

    python scripts/build_example.py
"""

from __future__ import annotations

import contextlib
import io
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from research_better.artifacts import ArtifactStore  # noqa: E402
from research_better.net import HttpCache, PoliteClient  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "bad-paper.md"
RECORDED = ROOT / "tests" / "fixtures" / "http"
EXAMPLE = ROOT / "examples"

STEPS = (
    ("ingest", ["ingest"]),
    ("novelty", ["novelty", "--confirm-claim"]),
    ("voice", ["voice"]),
    ("ground", ["ground", "--offline"]),
    ("originality", ["originality", "--offline"]),
    ("fluff", ["fluff"]),
    ("trace", ["trace"]),
    ("ask", ["ask"]),
    ("edit", ["edit"]),
    ("report", ["report"]),
)
"""The order the skill runs, with the claim confirmed at step two.

`edit` refuses until the analysis is on disk and the claim is confirmed, so a
run that skipped the confirmation would produce an example of the evidence gate
refusing rather than an example of an edit ledger. Both are worth seeing and
the ledger is the one this cannot show any other way."""

COPIED = {
    "report.md": "report",
    "reviewer-questions.md": "reviewer-questions",
    "trace.md": "trace",
    "edits.md": "edits",
}
"""Artifact to the file it lands in. Only the human-readable ones: the JSON
carries a timestamp and an absolute path, so committing it would produce a diff
on every run that says nothing."""


def _offline(monkeypatched: dict) -> None:
    """Point the CLI at the recorded responses, the way the tests do."""
    import research_better.cli as cli

    monkeypatched["default_cache"] = cli.default_cache
    monkeypatched["PoliteClient"] = cli.PoliteClient

    cli.default_cache = lambda _draft: HttpCache(RECORDED, ignore_ttl=True)  # type: ignore[assignment]
    cli.PoliteClient = lambda cache, **options: PoliteClient(  # type: ignore[assignment]
        cache, **{**options, "offline": True}
    )


def _restore(monkeypatched: dict) -> None:
    import research_better.cli as cli

    cli.default_cache = monkeypatched["default_cache"]
    cli.PoliteClient = monkeypatched["PoliteClient"]


def render() -> dict[str, str]:
    """Every example file, as text, without writing anything."""
    from research_better.cli import main

    monkeypatched: dict = {}
    _offline(monkeypatched)
    try:
        with tempfile.TemporaryDirectory() as workspace:
            draft = Path(workspace) / "paper.md"
            shutil.copyfile(FIXTURE, draft)

            transcript: list[str] = []
            for label, command in STEPS:
                printed = io.StringIO()
                with contextlib.redirect_stdout(printed):
                    code = main([*command, str(draft), "--no-color"])
                body = printed.getvalue().rstrip()
                shown = " ".join(command)
                transcript.append(f"$ rb {shown} paper.md\n{body}\n[exit {code}]")
                if label == "report":
                    # The report prints its whole page to stdout, which is the
                    # point of it. Repeating that inside the transcript would
                    # double the file for no reader.
                    transcript[-1] = f"$ rb {shown} paper.md\n[exit {code}]"

            store = ArtifactStore(draft)
            files = {"run.txt": "\n\n".join(transcript) + "\n"}
            for name, artifact in COPIED.items():
                path = store.path_for(artifact, ".md")
                files[name] = _strip_provenance(path.read_text(encoding="utf-8"))

            patch = store.path_for("edits", ".diff")
            if patch.is_file():
                files["edits.diff"] = _stable(
                    patch.read_text(encoding="utf-8").replace(str(draft), "paper.md")
                )
            return files
    finally:
        _restore(monkeypatched)


TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}")


def _stable(patch: str) -> str:
    """Blank the timestamps a unified diff header carries.

    They are the time of the run and nothing else. Left in, this file would
    regenerate dirty on every run and everybody would learn to ignore its diff,
    which would defeat the check that keeps the example honest.
    """
    return TIMESTAMP.sub("(generated)", patch)


def _strip_provenance(body: str) -> str:
    """Drop the header naming a temporary directory and the time of the run.

    Both change on every run and neither tells a reader anything, so leaving
    them in would make this regenerate dirty forever and train everybody to
    ignore the diff.
    """
    lines = body.splitlines()
    kept = [line for line in lines if not line.startswith("<!--")]
    return "\n".join(kept).lstrip("\n")


def main() -> int:
    target = EXAMPLE / "output"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE, EXAMPLE / "paper.md")

    for name, body in render().items():
        (target / name).write_text(body, encoding="utf-8", newline="\n")
        print(f"wrote examples/output/{name}")
    print("wrote examples/paper.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
