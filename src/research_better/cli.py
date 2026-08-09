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

from research_better import __version__, present, synthesis
from research_better import edit as edit_layer
from research_better import report as report_pass
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
            sub.add_argument(
                "--force",
                action="store_true",
                help=(
                    "apply even to a file with uncommitted changes. A backup is still "
                    "taken, but git will not be able to give the original back"
                ),
            )
            sub.add_argument(
                "--target-reduction",
                type=float,
                default=0.0,
                metavar="SHARE",
                help=(
                    "how much shorter you want the paper, as a share, for example 0.1. "
                    "Reported against, never filled: the tool will not invent a cut to "
                    "hit a number"
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
                help=(
                    "exit 1 when the paper is over a configured threshold, for use in "
                    "CI or a pre-commit hook. Set them in .research-better.toml or "
                    "under [tool.research-better.check] in pyproject.toml"
                ),
            )
            sub.add_argument(
                "--html",
                action="store_true",
                help="print the report as one self-contained page, for a coauthor",
            )

    run = commands.add_parser("run", parents=[parent], help="every implemented pass, in order")
    run.add_argument("draft", type=Path, help="path to the paper")

    already = commands.add_parser(
        "findings",
        parents=[parent],
        help="print what the passes already found, without running anything",
    )
    already.add_argument("draft", type=Path, help="path to the paper")

    graded = commands.add_parser(
        "check-analysis",
        parents=[parent],
        help="grade a written analysis against the artifacts it claims to read",
    )
    graded.add_argument("draft", type=Path, help="path to the paper")
    graded.add_argument(
        "analysis",
        help="path to the written analysis, or - to read it from stdin",
    )

    back = commands.add_parser(
        "revert", parents=[parent], help="restore the most recent backup of a draft"
    )
    back.add_argument("draft", type=Path, help="path to the paper")

    check = commands.add_parser(
        "doctor",
        parents=[parent],
        help="report the installed version, the formats it can read, and what is missing",
    )
    check.add_argument(
        "--expect",
        metavar="VERSION",
        help=(
            "the version the caller was built against. A mismatch is reported and "
            "does not fail: the skill layer uses this to notice it is out of step "
            "with the CLI it is driving"
        ),
    )

    return parser


# Execution ----------------------------------------------------------------


def _emit(
    console: Console,
    name: str,
    result: PassResult,
    target: Path,
    document: Document | None = None,
    detailed: bool = True,
) -> None:
    console.say(f"{console.style.strong(name):<20} {result.summary}")
    console.detail(f"  wrote {target}")

    if result.findings:
        # A count says nothing about a paper. The rules behind it do, and on
        # the paper that produced this ticket the causes line alone would have
        # shown a lexicon bug immediately.
        console.say(console.style.dim(f"{'':<20} {present.top_causes(result.findings)}"))

    if detailed and result.findings:
        # An agent driving this CLI reports what it sees and does not go and
        # read a JSON file it was not told about, so this prints by default.
        # `--quiet` silences it, which is what CI wants.
        # Named relative to the artifact directory rather than absolutely. An
        # author reads `.research-better/fluff.json` and knows where to look,
        # and a line with a machine's home directory in it is noise in every
        # transcript it lands in.
        body = present.render_for_terminal(
            result.findings, document, f"{target.parent.name}/{target.name}"
        )
        if body:
            console.say(body)

    if result.stdout:
        # A page that lands in .research-better/ and is never opened is not a
        # page an author reads.
        console.say()
        console.say(result.stdout)


def _run_one(
    name: str,
    context: PassContext,
    store: ArtifactStore,
    console: Console,
    source_hash: str,
    detailed: bool = True,
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

    # A page beside the JSON, for every pass that found something, written here
    # rather than by each pass. The failure this fixes was a pass forgetting,
    # so the place to put the fix is the one path every pass goes through.
    markdown = result.markdown
    if markdown is None and result.findings:
        markdown = present.render_for_file(name, result.findings, context.document)
    if markdown is not None:
        store.write_text(entry.artifact, markdown, source_hash)

    for suffix, body in result.attachments:
        store.write_text(entry.artifact, body, source_hash, suffix=suffix)
    _emit(console, name, result, target, context.document, detailed=detailed)

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


def findings(args: argparse.Namespace, console: Console) -> int:
    """Print what the passes already found, without running anything.

    Cheap, offline, and the thing to tell somebody who ran the passes and got
    counts back. It reads the pages written beside each artifact rather than
    recomputing, so what it prints is what the run actually recorded, and a
    stale one is reported as stale rather than quietly refreshed.
    """
    draft = Path(args.draft)
    if not draft.is_file():
        raise ResearchBetterError(f"{draft} does not exist")

    store = ArtifactStore(draft)
    source_hash = Document.hash_source(draft.read_bytes().decode("utf-8"))

    shown = 0
    for name, entry in PASSES.items():
        page = store.path_for(entry.artifact, ".md")
        if not page.is_file():
            continue

        artifact = store.read(entry.artifact)
        if artifact is not None and artifact.is_stale(source_hash):
            console.warn(
                f"{page.name} describes an older version of {draft.name}. "
                f"Run: {PROGRAM} {name} {draft}"
            )

        if shown:
            console.say()
        console.say(console.style.strong(f"--- {page.name} ---"))
        # The provenance comment is for whoever opens the file. Staleness is
        # already reported above, in a line aimed at a reader rather than at a
        # diff.
        body = page.read_text(encoding="utf-8")
        if body.startswith("<!--"):
            body = body.split("-->", 1)[-1]
        console.say(body.strip())
        shown += 1

    if not shown:
        # Not an error, and not silence either. Nothing on disk and a paper
        # with nothing wrong with it look identical from here, and only one of
        # them is true.
        console.say(
            f"No analysis has been written for {draft.name} yet. Run: {PROGRAM} run {draft}"
        )
    return EXIT_CLEAN


def check_analysis(args: argparse.Namespace, console: Console) -> int:
    """Grade a written analysis against the artifacts it claims to be reading.

    The last step of the skill is prose, and prose was the one thing here that
    nothing checked. `references/final-analysis.md` says what it may and may
    not contain, and a reference file is a preference. This is the check, and
    it is the evidence gate pointed one layer up.

    Reads the analysis from a file, or from stdin with `-`, so whatever wrote
    it can pipe it straight in.
    """
    draft = Path(args.draft)
    if not draft.is_file():
        raise ResearchBetterError(f"{draft} does not exist")

    if args.analysis == "-":
        text = sys.stdin.read()
    else:
        source = Path(args.analysis)
        if not source.is_file():
            raise ResearchBetterError(f"{source} does not exist")
        text = source.read_bytes().decode("utf-8")

    if not text.strip():
        raise ResearchBetterError(
            "the analysis is empty. Nothing was checked, which is not the same as "
            "nothing being wrong with it."
        )

    store = ArtifactStore(draft)
    document = _load_document(args)
    report = report_pass.build(document, store)

    grounding_payload = store.read("grounding")
    keys = _citation_keys(grounding_payload.payload if grounding_payload else None)
    payloads = {
        entry.artifact: artifact.payload
        for entry in PASSES.values()
        if (artifact := store.read(entry.artifact)) is not None
    }

    result = synthesis.check(
        text,
        report,
        keys,
        payloads=payloads or None,
        draft_text=document.source_text,
    )
    console.say(synthesis.to_markdown(result).rstrip())
    return EXIT_CLEAN if result.clean else EXIT_FINDINGS


def _citation_keys(payload: object) -> set[str]:
    """Every key the grounding pass looked at, resolved or not.

    A failed lookup is still a record. Naming a citation the pass could not
    resolve is honest reporting; naming one it never saw is invention.
    """
    if not isinstance(payload, dict):
        return set()
    citations = payload.get("citations")
    if not isinstance(citations, dict):
        return set()
    found: set[str] = set()
    for check in citations.get("checks") or ():
        if isinstance(check, dict) and check.get("key"):
            found.add(str(check["key"]))
    return found


def revert(args: argparse.Namespace, console: Console) -> int:
    """Undo the last --apply. Not a pass: it reads no artifact and writes none."""
    draft = Path(args.draft)
    if not draft.is_file():
        raise ResearchBetterError(f"{draft} does not exist")

    restored = edit_layer.revert(draft)
    console.say(f"{draft.name} restored from {restored.name}")
    console.detail(f"  the backup was kept at {restored}")
    return EXIT_CLEAN


FORMAT_EXTRAS = (
    ("markdown", None, None, ".md"),
    ("latex", "bibtexparser", "latex", ".tex"),
    ("word", "docx", "docx", ".docx"),
    ("pdf", "pypdf", "pdf", ".pdf"),
)
"""(label, module, extra, suffix) for each format, in install order."""


def doctor(args: argparse.Namespace, console: Console) -> int:
    """Say what is installed, so a caller can find out before it depends on it.

    Written for the skill layer, which drives this CLI and has no other way to
    tell a missing install from a missing feature. A skill that cannot run its
    scripts and does not notice will analyse the paper by eye and produce
    exactly the unverified judgement this tool exists to replace, so the answer
    has to come from the tool rather than from a guess about it.
    """
    from research_better.extras import available
    from research_better.passes import PASSES

    console.say(f"{PROGRAM} {__version__}")
    console.say(f"python {sys.version.split()[0]} at {sys.executable}")
    console.say()

    console.say("formats")
    missing: list[str] = []
    for label, module, extra, suffix in FORMAT_EXTRAS:
        if module is None or available(module):
            console.say(f"  {label:<10} {suffix:<7} ready")
        else:
            missing.append(extra or label)
            console.say(f'  {label:<10} {suffix:<7} needs: pip install "{PROGRAM}[{extra}]"')

    console.say()
    console.say("passes: " + ", ".join(sorted(name for name, p in PASSES.items() if p.implemented)))

    contact = os.environ.get("RESEARCH_BETTER_CONTACT")
    console.say(
        f"contact: {contact}"
        if contact
        else (
            "contact: unset. Setting RESEARCH_BETTER_CONTACT puts scholarly API "
            "requests in the polite pool and lets a source operator email rather "
            "than block you."
        )
    )

    if args.expect and args.expect != __version__:
        # Reported and not fatal. A caller one patch ahead of the CLI is
        # usually fine, and refusing to run would block work over a difference
        # that may not matter. Saying nothing would let it matter silently.
        console.warn(
            f"the caller was built against {args.expect} and this is {__version__}. "
            f"Upgrade with: pip install --upgrade {PROGRAM}"
        )

    if args.json:
        print(
            json.dumps(
                {
                    "version": __version__,
                    "python": sys.version.split()[0],
                    "executable": sys.executable,
                    "formats_ready": [
                        label
                        for label, module, _extra, _suffix in FORMAT_EXTRAS
                        if module is None or available(module)
                    ],
                    "extras_missing": missing,
                    "contact_set": bool(contact),
                    "expected_version": args.expect,
                    "version_matches": not args.expect or args.expect == __version__,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return EXIT_CLEAN


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
            target_reduction=float(getattr(args, "target_reduction", 0.0) or 0.0),
            apply=bool(getattr(args, "apply", False)),
            force=bool(getattr(args, "force", False)),
            check=bool(getattr(args, "check", False)),
            html=bool(getattr(args, "html", False)),
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

            # Ten passes each printing every finding is a wall, not a report,
            # and `run` ends with the report anyway. Asked for a pass by name,
            # which is the path an agent takes, the findings are printed.
            outcome, entry = _run_one(
                name,
                context,
                store,
                console,
                source_hash,
                detailed=args.command != "run",
            )
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

    # Neither of these is a pass. One restores a backup and reads no artifact,
    # and the other answers questions about the install rather than about a
    # paper, so neither takes a draft.
    standalone = {
        "revert": revert,
        "doctor": doctor,
        "findings": findings,
        "check-analysis": check_analysis,
    }

    try:
        handler = standalone.get(args.command)
        return handler(args, console) if handler else run(args, console)
    except ResearchBetterError as error:
        # The user asked for a paper to be checked, not for a traceback. Only
        # errors this package raises on purpose get the short treatment. A real
        # bug still crashes loudly.
        console.fail(str(error))
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
