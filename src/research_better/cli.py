"""Command line entry point, exposed as both `research-better` and `rb`.

Exit codes are the contract that makes `--check` usable in CI:

* `0` the pass ran and found nothing
* `1` the pass ran and found something
* `2` the tool could not do its job

The distinction between 1 and 2 is the one that matters. A build that fails
because the paper has problems and a build that fails because a scholarly API
was down are different events, and collapsing them teaches people to ignore
both.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from research_better import __version__
from research_better.artifacts import ArtifactStore
from research_better.errors import ResearchBetterError
from research_better.ingest import load
from research_better.model import Document
from research_better.net import PoliteClient, default_cache
from research_better.passes import PASSES, RUN_ORDER, PassContext, PassResult

PROGRAM = "research-better"

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


@dataclass(frozen=True, slots=True)
class Style:
    """Terminal colour, or nothing at all."""

    enabled: bool

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def warn(self, text: str) -> str:
        return self._wrap("33", text)

    def error(self, text: str) -> str:
        return self._wrap("31", text)

    def strong(self, text: str) -> str:
        return self._wrap("1", text)


class Console:
    def __init__(self, quiet: bool, verbose: bool, style: Style) -> None:
        self.quiet = quiet
        self.verbose = verbose
        self.style = style

    def say(self, text: str = "") -> None:
        if not self.quiet:
            print(text)

    def detail(self, text: str) -> None:
        if self.verbose and not self.quiet:
            print(self.style.dim(text))

    def warn(self, text: str) -> None:
        # Warnings go to stderr even under --quiet. Suppressing the news that
        # an artifact is out of date is how somebody trusts a stale report.
        print(self.style.warn(f"warning: {text}"), file=sys.stderr)

    def fail(self, text: str) -> None:
        print(self.style.error(f"{PROGRAM}: {text}"), file=sys.stderr)


def _colour_wanted(no_color: bool) -> bool:
    if no_color or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _global_flags() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--offline",
        action="store_true",
        help=(
            "never reach the network, use only what is already cached. "
            "Recorded in every artifact produced, so a report can say whether "
            "a citation was checked against the live literature or not."
        ),
    )
    parent.add_argument(
        "--refresh",
        action="store_true",
        help="ignore what is cached and fetch again. Use after a source has corrected a record",
    )
    parent.add_argument(
        "--venue",
        help="target venue, so questions are weighted for it. Falls back to conservative defaults",
    )
    parent.add_argument("--json", action="store_true", help="machine-readable output")
    parent.add_argument(
        "--format",
        dest="format_override",
        help="override format detection, for example when a draft has no extension",
    )
    parent.add_argument("--no-color", action="store_true", help="never emit colour")
    parent.add_argument("--quiet", "-q", action="store_true", help="print nothing but warnings")
    parent.add_argument("--verbose", "-v", action="store_true", help="print what each pass did")
    return parent


def build_parser() -> argparse.ArgumentParser:
    parent = _global_flags()
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        parents=[parent],
        description=(
            "Check a research paper: verify its citations, flag text that does "
            "not serve its novelty claim, and raise the questions a reviewer "
            "will ask. Does not rewrite the paper for you."
        ),
    )
    parser.add_argument("--version", action="version", version=f"{PROGRAM} {__version__}")

    commands = parser.add_subparsers(dest="command", metavar="command")

    for name, entry in PASSES.items():
        help_text = entry.help if entry.implemented else f"{entry.help} (not built yet)"
        sub = commands.add_parser(name, parents=[parent], help=help_text)
        sub.add_argument("draft", type=Path, help="path to the paper")
        if name == "edit":
            sub.add_argument(
                "--apply",
                action="store_true",
                help="write the patch to the draft instead of only reporting it",
            )
            sub.add_argument(
                "--interactive",
                action="store_true",
                help=(
                    "walk the proposed edits one at a time. Decisions are kept, so "
                    "a change you reject is not offered again"
                ),
            )
        if name == "novelty":
            sub.add_argument(
                "--confirm-claim",
                action="store_true",
                help=(
                    "confirm the extracted contribution claim is correct. Nothing "
                    "downstream should act on an unconfirmed claim, because if the "
                    "claim is wrong every cut that follows is wrong"
                ),
            )
        if name == "report":
            sub.add_argument(
                "--check",
                action="store_true",
                help="exit 1 when there are findings, for use in CI",
            )

    run = commands.add_parser("run", parents=[parent], help="every implemented pass, in order")
    run.add_argument("draft", type=Path, help="path to the paper")

    return parser


# Execution ----------------------------------------------------------------


def _emit(console: Console, name: str, result: PassResult, target: Path) -> None:
    console.say(f"{console.style.strong(name):<20} {result.summary}")
    console.detail(f"  wrote {target}")


def _run_one(
    name: str,
    context: PassContext,
    store: ArtifactStore,
    console: Console,
    source_hash: str,
) -> tuple[int, dict[str, object]]:
    entry = PASSES[name]
    if not entry.implemented or entry.run is None:
        raise ResearchBetterError(
            f"the {name} pass is not built yet. It lands in {entry.phase}. "
            f"Nothing was written, because an empty {entry.artifact} artifact "
            f"would look exactly like a check that found nothing wrong."
        )

    result = entry.run(context)
    target = store.write(entry.artifact, result.payload, source_hash, offline=context.offline)
    if result.markdown is not None:
        store.write_text(entry.artifact, result.markdown, source_hash)
    for suffix, body in result.attachments:
        store.write_text(entry.artifact, body, source_hash, suffix=suffix)
    _emit(console, name, result, target)

    return (
        EXIT_FINDINGS if result.findings or result.counts_as_finding else EXIT_CLEAN,
        {
            "pass": name,
            "artifact": str(target),
            "summary": result.summary,
            "findings": len(result.findings),
        },
    )


def _load_document(args: argparse.Namespace) -> Document:
    path = Path(args.draft)
    if not path.is_file():
        raise ResearchBetterError(f"{path} does not exist")
    if args.format_override:
        text = path.read_bytes().decode("utf-8")
        adapter = args.format_override.lower().lstrip(".")
        suffixes = {"markdown": ".md", "md": ".md", "latex": ".tex", "tex": ".tex"}
        if adapter not in suffixes:
            raise ResearchBetterError(
                f"unknown format {args.format_override!r}, expected markdown or latex"
            )
        return load(path.with_suffix(suffixes[adapter]), text=text)
    return load(path)


def run(args: argparse.Namespace, console: Console) -> int:
    document = _load_document(args)
    source_hash = document.source_hash
    store = ArtifactStore(Path(args.draft))

    for warning in store.stale_warnings(source_hash):
        console.warn(warning)

    names = (
        [name for name in RUN_ORDER if PASSES[name].implemented]
        if args.command == "run"
        else [args.command]
    )

    status = EXIT_CLEAN
    report: list[dict[str, object]] = []
    blocked: list[tuple[str, str]] = []
    # The client is built only when a pass in this run actually needs one, so a
    # purely local check never opens a socket or creates a cache directory.
    needs_network = any(PASSES[name].needs_network for name in names)

    with ExitStack() as resources:
        client: PoliteClient | None = None
        if needs_network:
            client = resources.enter_context(
                PoliteClient(
                    default_cache(Path(args.draft)),
                    offline=args.offline,
                    refresh=args.refresh,
                )
            )
        context = PassContext(
            document=document,
            client=client,
            offline=args.offline,
            refresh=args.refresh,
            venue=args.venue,
            claim_confirmed=bool(getattr(args, "confirm_claim", False)),
            store=store,
            interactive=bool(getattr(args, "interactive", False)),
        )
        for name in names:
            entry_pass = PASSES[name]
            if entry_pass.preflight is not None:
                try:
                    entry_pass.preflight(context, store)
                except ResearchBetterError as error:
                    # Asked for this pass by name, the author gets the error and
                    # exit 2. Asked for everything, they get told which pass did
                    # not run and why, because a survey that aborts partway
                    # through is less useful than one that reports its gaps.
                    if args.command != "run":
                        raise
                    blocked.append((name, str(error)))
                    continue

            outcome, entry = _run_one(name, context, store, console, source_hash)
            status = max(status, outcome)
            report.append(entry)

    if args.command == "run":
        # Saying what did not run is the same commitment as never printing a
        # total score. Silence about an unrun pass reads as a clean result.
        skipped = [name for name in RUN_ORDER if not PASSES[name].implemented]
        if skipped:
            console.say()
            console.say(
                console.style.dim(
                    "not checked, these passes are not built yet: " + ", ".join(skipped)
                )
            )
        for name, reason in blocked:
            console.say()
            console.say(console.style.dim(f"not run, {name}: {reason}"))

    if args.json:
        print(
            json.dumps(
                {
                    "passes": report,
                    "blocked": [{"pass": name, "reason": reason} for name, reason in blocked],
                    "exit_code": status,
                },
                indent=2,
                sort_keys=True,
            )
        )

    return status


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_CLEAN

    console = Console(
        quiet=args.quiet,
        verbose=args.verbose,
        style=Style(enabled=_colour_wanted(args.no_color)),
    )

    try:
        return run(args, console)
    except ResearchBetterError as error:
        # The user asked for a paper to be checked, not for a traceback. Only
        # errors this package raises on purpose get the short treatment. A real
        # bug still crashes loudly.
        console.fail(str(error))
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
