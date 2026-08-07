"""Command line entry point, exposed as both `research-better` and `rb`.

The analysis subcommands land with the passes they drive. This module owns
argument parsing, exit codes, and turning a `ResearchBetterError` into one line
on stderr instead of a traceback.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from research_better import __version__
from research_better.errors import ResearchBetterError

PROGRAM = "research-better"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Check a research paper: verify its citations, flag text that does "
            "not serve its novelty claim, and raise the questions a reviewer "
            "will ask. Does not rewrite the paper for you."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROGRAM} {__version__}",
    )
    parser.add_subparsers(dest="command", metavar="command")
    return parser


def run(args: argparse.Namespace) -> int:
    """Dispatch a parsed command. Subcommands register here as they land."""
    raise NotImplementedError(f"command '{args.command}' has no handler")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # No subcommands are registered yet, so argparse cannot produce one.
    if args.command is None:
        parser.print_help()
        return EXIT_OK

    try:
        return run(args)
    except ResearchBetterError as exc:
        # The user asked for a paper to be checked, not for a traceback. Only
        # errors this package raises on purpose get the short treatment. A real
        # bug still crashes loudly.
        print(f"{PROGRAM}: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
