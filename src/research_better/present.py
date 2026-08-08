"""Findings, in the form a person reads.

A pass used to print how many findings it had and file the findings themselves
in JSON. Run through an agent on a real paper the entire visible output of the
analysis was four summary lines, and the author learned their paper had 28
problems and nothing about what any of them was.

`PassResult.stdout` already carried the right reasoning, applied one pass too
narrowly:

    Only the report sets it, because only the report is meant to be read rather
    than filed: a page that lands in `.research-better/` and is never opened is
    not a page an author reads.

That holds for every pass somebody is waiting on. A finding that lands in
`fluff.json` and is never opened is not a finding an author reads either.

Two things follow, and the second is the one that makes it a guarantee rather
than a habit. Findings are printed by default, because an agent driving this
CLI reports what it sees and does not go and read a JSON file it was not told
about, so a `--verbose` nobody passes solves nothing. And the rendering is
applied centrally to any pass that produced findings, rather than each pass
opting in, because the failure here was a pass forgetting.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from research_better.findings import Finding, Severity
from research_better.model import Document

PRINTED_PER_PASS = 8
"""How many findings a single pass prints before it truncates.

Enough to see the shape of the problem and short enough to read. The rest are
in the artifact and in the markdown beside it, and the truncation line says how
many and where.
"""

QUOTE_LENGTH = 96
NOTE_LENGTH = 160

SEVERITY_ORDER = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}


def _clip(text: str, limit: int) -> str:
    flattened = " ".join(text.split())
    return flattened if len(flattened) <= limit else flattened[: limit - 3].rstrip() + "..."


def _line_of(document: Document | None, finding: Finding) -> int | None:
    if document is None:
        return None
    start = finding.char_range[0]
    if start <= 0:
        return None
    return document.source_text.count("\n", 0, start) + 1


def by_severity(findings: Sequence[Finding]) -> list[Finding]:
    """Worst first, then document order. A reader who stops after three lines
    should have read the three that matter most."""
    return sorted(
        findings,
        key=lambda f: (SEVERITY_ORDER.get(f.severity, 3), f.char_range[0], f.rule),
    )


def top_causes(findings: Sequence[Finding], limit: int = 3) -> str:
    """The rules behind a count, most frequent first.

    `28 findings` says nothing about a paper. `21 empty_intensifiers, 4
    hedge_adverbs, 3 filler_openers` says what is wrong with it, and on the
    paper that produced this it would have shown a lexicon bug immediately
    rather than after a manual read of the JSON.
    """
    counts = Counter(finding.rule for finding in findings)
    named = ", ".join(f"{count} {rule}" for rule, count in counts.most_common(limit))
    remaining = len(counts) - limit
    return f"{named}, and {remaining} other rule(s)" if remaining > 0 else named


def render_finding(
    finding: Finding,
    document: Document | None = None,
    explained: set[str] | None = None,
) -> list[str]:
    """One finding: where it is, what matched, and why that is a finding.

    A rule's note is the same sentence every time it fires, so it is printed
    once per rule per block. Eleven identical explanations push the eleven
    different quotes off the screen, which is the problem this whole module
    exists to fix, one level down.
    """
    line = _line_of(document, finding)
    where = f"line {line}" if line else "-"
    head = f"  {where:<9} {finding.rule}  [{finding.severity}]"
    if finding.advisory:
        head += " advisory"

    lines = [head]
    if finding.matched_text.strip():
        lines.append(f'    "{_clip(finding.matched_text, QUOTE_LENGTH)}"')
    if finding.replacement:
        lines.append(f"    suggested: {_clip(finding.replacement, QUOTE_LENGTH)}")
    if finding.note and (explained is None or finding.rule not in explained):
        lines.append(f"    {_clip(finding.note, NOTE_LENGTH)}")
        if explained is not None:
            explained.add(finding.rule)
    return lines


def render_for_terminal(
    findings: Sequence[Finding],
    document: Document | None,
    artifact: str,
    limit: int = PRINTED_PER_PASS,
) -> str:
    """What a pass prints under its summary line.

    Truncated, with the count of what was withheld and where the rest are. A
    tool that prints forty findings and a tool that prints none are read the
    same way.
    """
    if not findings:
        return ""

    ordered = by_severity(findings)
    lines: list[str] = []
    explained: set[str] = set()
    for finding in ordered[:limit]:
        lines.extend(render_finding(finding, document, explained))

    withheld = len(ordered) - limit
    if withheld > 0:
        lines.append(f"  {withheld} more, all of them in {artifact}")
    return "\n".join(lines)


def render_for_file(
    name: str,
    findings: Sequence[Finding],
    document: Document | None = None,
) -> str:
    """Every finding, as a page beside the JSON.

    Nothing is truncated here. The terminal truncates because a wall of text is
    not read; a file does not have that problem, and an author who wants the
    rest should not have to parse JSON to get it.
    """
    ordered = by_severity(findings)
    lines = [
        f"# {name}",
        "",
        f"{len(ordered)} finding(s): {top_causes(ordered, limit=6)}.",
        "",
        "Worst first, then document order. Nothing here has been applied.",
        "",
    ]
    explained: set[str] = set()
    for finding in ordered:
        lines.extend(render_finding(finding, document, explained))
        lines.append("")
    return "\n".join(lines)
