"""Install the built distribution somewhere clean and check it actually runs.

The release workflow runs this before it publishes, because the failure this
catches is the one that cannot be taken back: a wheel that imports fine in the
repository, where `src/` is on the path and every extra is installed, and dies
on a machine that has only the wheel.

So this deliberately does the opposite of the test suite. A fresh interpreter,
no extras, no repository on the path, and the network cut off at the proxy, and
then the two things the base install promises: the help text, and the fluff
pass over a Markdown file.

    python scripts/smoke_test.py            # builds first
    python scripts/smoke_test.py dist/*.whl
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEAD_PROXY = "http://127.0.0.1:9"
"""Port 9 is discard. Any outbound request made by a pass that claims not to
need one fails here rather than quietly succeeding and passing this check."""

DRAFT = """# Introduction

It is important to note that retrieval has become a truly pivotal area of study
in today's rapidly evolving landscape. As we all know, this is a testament to
the intricate tapestry of the field.

Recall at ten rises from 0.62 to 0.71 when expansion is enabled, a gain of nine
points measured over five thousand queries.
"""


def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(str(part) for part in command))
    result = subprocess.run(command, text=True, capture_output=True, **options)  # type: ignore[call-overload]
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        print(result.stderr.rstrip(), file=sys.stderr)
    return result  # type: ignore[no-any-return]


def build() -> Path:
    run([sys.executable, "-m", "build", "--wheel", "--outdir", str(ROOT / "dist")], cwd=ROOT)
    wheels = sorted((ROOT / "dist").glob("research_better-*.whl"))
    if not wheels:
        raise SystemExit("no wheel was built")
    return wheels[-1]


def scripts_directory(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def main() -> int:
    wheel = Path(sys.argv[1]) if len(sys.argv) > 1 else build()
    print(f"smoke testing {wheel.name}")

    with tempfile.TemporaryDirectory() as workspace:
        area = Path(workspace)
        venv = area / "venv"
        run([sys.executable, "-m", "venv", str(venv)])
        binaries = scripts_directory(venv)
        python = binaries / ("python.exe" if os.name == "nt" else "python")

        # No extras. The base install has to be enough to check a Markdown
        # paper, and somebody installing this to look at their citations should
        # not be made to install a PDF stack first.
        if run([str(python), "-m", "pip", "install", "--quiet", str(wheel)]).returncode:
            raise SystemExit("the wheel would not install")

        draft = area / "paper.md"
        draft.write_text(DRAFT, encoding="utf-8")

        # Cut the network off rather than trusting the pass not to use it.
        environment = {
            **os.environ,
            "HTTP_PROXY": DEAD_PROXY,
            "HTTPS_PROXY": DEAD_PROXY,
            "http_proxy": DEAD_PROXY,
            "https_proxy": DEAD_PROXY,
            "NO_COLOR": "1",
        }
        environment.pop("RESEARCH_BETTER_CACHE", None)

        checks = [
            ([str(binaries / "research-better"), "--help"], "the console script"),
            ([str(binaries / "rb"), "--version"], "the short entry point"),
            ([str(binaries / "research-better"), "fluff", str(draft)], "the fluff pass"),
            ([str(binaries / "research-better"), "trace", str(draft)], "the trace audit"),
        ]
        for command, what in checks:
            result = run(command, cwd=area, env=environment)
            # The fluff pass exits 1 when it finds something, and the draft
            # above is full of things to find. Only a 2 means the tool could
            # not do its job.
            if result.returncode not in (0, 1):
                raise SystemExit(f"{what} failed with exit code {result.returncode}")

        cache = area / ".research-better" / "cache"
        if cache.exists():
            raise SystemExit(f"a pass that needs no network opened a cache at {cache}")

        if not (area / ".research-better" / "fluff.json").is_file():
            raise SystemExit("the fluff pass wrote no artifact")

    print("smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
