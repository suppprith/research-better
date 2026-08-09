"""Check a written analysis against the artifacts it claims to read.

`references/final-analysis.md` tells the model what the synthesis may and may
not contain. That is a preference, and this project's own sentence about
preferences is in `edit/gate.py`: a prompt is a preference and a check is a
guarantee. This is the check.

It is the evidence gate pointed at prose. The gate refuses to write before the
research is on disk. This refuses to accept a sentence that goes beyond what
the research says. Same discipline, one layer up, and the same reason: a
synthesis that quietly adds a judgement is the unverified opinion this project
exists to replace, wearing the tool's name, where an author will trust it more
than they should.

Four rules are checkable and two are not, and saying which is which is the same
commitment as a report naming what it did not check. `AnalysisCheck.not_checked`
carries the two, so a clean result never reads as a clean bill of health.

Deliberately not a model call. A grader that needs a model to run cannot run in
CI, cannot run offline, and cannot be argued with. Every rule here is a rule two
people can disagree about by reading it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from research_better.report import Report

PERCENTAGE = re.compile(r"\d+(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?\s+per\s?cent\b", re.IGNORECASE)
NUMERIC_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
KEYED_CITATION = re.compile(r"`([A-Za-z][A-Za-z0-9_.:-]{2,})`")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
LIST_MARKER = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", re.MULTILINE)
UNRUN_PASS = re.compile(r"The (\w+) pass has not run")

VERDICT_PHRASES = (
    "ready for submission",
    "ready to submit",
    "publication ready",
    "ready to publish",
    "in good shape",
    "in great shape",
    "a strong paper",
    "a solid paper",
    "a good paper",
    "a strong contribution",
    "well written",
    "well-written",
    "your paper is good",
    "the paper is good",
    "the paper is strong",
    "the paper is sound",
    "nothing to worry about",
    "no major issues",
    "no major problems",
    "looks great",
    "looks good overall",
    "overall quality",
    "high quality",
)
"""Phrases that state a verdict on the paper as a whole.

No artifact contains one, so no sentence of a synthesis can trace to one. This
is the failure the whole check exists for: everything else on the list is a
thing a careless summarizer drops, and this is the thing it adds.

In code rather than in the reference pack because it is the checker's own rule
rather than knowledge about writing papers. The fluff lexicon is data because
contributors tune it against their own prose; this list is a contract.
"""

CANNOT_CHECK = (
    "Whether a sentence of the analysis rewrites the author's prose. Detecting "
    "a proposed replacement needs to understand the sentence, and a checker "
    "that guesses would either miss the real ones or refuse honest quotation.",
    "Whether the analysis answers a reviewer question rather than relaying it. "
    "The difference between reporting a question and supplying its answer is a "
    "judgement about meaning.",
)
"""What this checker does not look at.

Listed rather than omitted, for the same reason a grounding report says how
many sources it could reach. A checker that reports no violations and does not
say what it never examined is making the false-assurance move this project
refuses everywhere else.
"""


@dataclass(frozen=True, slots=True)
class Violation:
    rule: str
    detail: str
    quote: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"rule": self.rule, "detail": self.detail, "quote": self.quote}


@dataclass(frozen=True, slots=True)
class AnalysisCheck:
    violations: tuple[Violation, ...] = ()
    not_checked: tuple[str, ...] = CANNOT_CHECK
    checked: tuple[str, ...] = field(default_factory=tuple)

    @property
    def clean(self) -> bool:
        return not self.violations

    def to_json(self) -> dict[str, Any]:
        return {
            "violations": [item.to_json() for item in self.violations],
            "checked": list(self.checked),
            "not_checked": list(self.not_checked),
        }


def _known_numbers(payloads: dict[str, Any], draft_text: str) -> set[str]:
    """Every number the analysis is entitled to use.

    Anything in an artifact, plus anything in the paper itself, because quoting
    the author's own measurement back to them is the point. A number in neither
    place was computed by whoever wrote the analysis, and the reference says
    plainly that if you are adding two counts together you should stop.
    """
    found: set[str] = set(NUMBER.findall(draft_text))

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                found.update(NUMBER.findall(str(key)))
                walk(value)
        elif isinstance(node, list | tuple):
            for item in node:
                walk(item)
        elif isinstance(node, bool):
            return
        elif isinstance(node, int | float):
            found.add(str(node))
            found.add(str(int(node)) if float(node).is_integer() else str(node))
        elif isinstance(node, str):
            found.update(NUMBER.findall(node))

    walk(payloads)
    return found


def _strip_list_markers(text: str) -> str:
    """Ordered-list markers are formatting, not claims about the paper."""
    return LIST_MARKER.sub("", text)


def _citations_mentioned(text: str) -> set[str]:
    found: set[str] = set()
    for group in NUMERIC_CITATION.findall(text):
        found.update(part.strip() for part in group.split(","))
    found.update(KEYED_CITATION.findall(text))
    return found


def check(
    analysis: str,
    report: Report,
    citation_keys: set[str],
    payloads: dict[str, Any] | None = None,
    draft_text: str = "",
) -> AnalysisCheck:
    """Grade a synthesis against the run it claims to be reading.

    Args:
        analysis: the prose the skill wrote.
        report: the report built from the artifacts on disk.
        citation_keys: every key the grounding pass actually resolved or failed
            to resolve. A key outside this set is one nothing checked.
        payloads: the artifact payloads, for the number check. Omitted skips it
            rather than failing every number, because a checker that cannot see
            the artifacts must not report the analysis as inventing things.
        draft_text: the paper, so quoting the author's own numbers is allowed.
    """
    violations: list[Violation] = []
    checked: list[str] = []
    lowered = analysis.lower()

    # 1. No percentage, ever ------------------------------------------------
    checked.append("no percentage or similarity score")
    for match in PERCENTAGE.finditer(analysis):
        violations.append(
            Violation(
                rule="percentage",
                detail=(
                    "The tool emits no percentage anywhere. A number like this in a "
                    "synthesis reads as a plagiarism or AI score whatever it is "
                    "labelled, and a partial corpus has no honest total."
                ),
                quote=match.group(0),
            )
        )

    # 2. Every citation named is one the grounding pass saw -----------------
    checked.append("every citation named appears in grounding.json")
    for mentioned in sorted(_citations_mentioned(analysis)):
        if mentioned not in citation_keys:
            violations.append(
                Violation(
                    rule="citation_not_in_grounding",
                    detail=(
                        f"{mentioned!r} is not a key the grounding pass checked. Every "
                        f"citation offered has to come from a record, and one that does "
                        f"not is the tool inventing a source under its own name."
                    ),
                    quote=mentioned,
                )
            )

    # 3. No verdict on the paper as a whole ---------------------------------
    checked.append("no verdict on the paper as a whole")
    for phrase in VERDICT_PHRASES:
        if phrase in lowered:
            violations.append(
                Violation(
                    rule="verdict_on_the_paper",
                    detail=(
                        "No artifact contains a verdict on the paper, so no sentence of "
                        "the analysis can trace back to one. Report what was found and "
                        "what was not checked, and leave the judgement to the author."
                    ),
                    quote=phrase,
                )
            )

    # 4. The coverage caveats survive ---------------------------------------
    checked.append("the coverage caveats survive from the report")
    violations.extend(_coverage_violations(analysis, report))

    # 5. Numbers come from somewhere ----------------------------------------
    if payloads is not None:
        checked.append("every number appears in an artifact or in the paper")
        known = _known_numbers(payloads, draft_text)
        for number in sorted(set(NUMBER.findall(_strip_list_markers(analysis)))):
            if number not in known:
                violations.append(
                    Violation(
                        rule="number_not_in_the_artifacts",
                        detail=(
                            f"{number} appears in neither an artifact nor the paper, so "
                            f"nothing in the run supports it. Two counts added together "
                            f"is the usual cause."
                        ),
                        quote=number,
                    )
                )

    return AnalysisCheck(
        violations=tuple(violations),
        checked=tuple(checked),
    )


def _coverage_violations(analysis: str, report: Report) -> list[Violation]:
    """What the run could not see has to travel with what it found.

    The first thing a summarizer drops, and the one this project cannot afford
    to lose: a run where one of six cited works had retrievable full text must
    not read as though six were checked.
    """
    found: list[Violation] = []
    numbers = set(NUMBER.findall(analysis))

    with_full_text, attempted = report.citations_with_full_text
    if attempted and with_full_text < attempted:
        missing = [str(value) for value in (with_full_text, attempted) if str(value) not in numbers]
        if missing:
            found.append(
                Violation(
                    rule="coverage_dropped",
                    detail=(
                        f"Only {with_full_text} of {attempted} cited works had retrievable "
                        f"full text, and the analysis does not say so. Overlap and claim "
                        f"support cover what could be read and nothing else, and prose "
                        f"that omits the ratio reads as though everything was checked."
                    ),
                    quote=f"{with_full_text} of {attempted}",
                )
            )

    unverified = report.unverified_citations
    if unverified and str(unverified) not in numbers:
        found.append(
            Violation(
                rule="coverage_dropped",
                detail=(
                    f"{unverified} bibliography entries did not resolve, and the analysis "
                    f"does not say how many. Not resolving is not evidence a work is "
                    f"invented, which is exactly why the count has to be stated rather "
                    f"than implied."
                ),
                quote=str(unverified),
            )
        )

    for gap in report.gaps:
        match = UNRUN_PASS.search(gap)
        if match and match.group(1).lower() not in analysis.lower():
            found.append(
                Violation(
                    rule="unrun_pass_not_named",
                    detail=(
                        f"The {match.group(1)} pass did not run and the analysis never "
                        f"mentions it. Silence about a check that did not happen reads as "
                        f"a check that found nothing."
                    ),
                    quote=gap,
                )
            )

    return found


def to_markdown(result: AnalysisCheck) -> str:
    """The result as a page, in the shape the rest of the tool reports things."""
    lines = ["# Analysis check", ""]

    if result.clean:
        lines += [
            "No violation found in what was checked. That is a statement about the",
            "rules below, not a verdict on the analysis.",
            "",
        ]
    else:
        lines += [f"{len(result.violations)} violation(s).", ""]
        for item in result.violations:
            lines += [f"- **{item.rule}** {item.quote!r}", f"  {item.detail}"]
        lines.append("")

    lines += ["## Checked", ""]
    lines += [f"- {rule}" for rule in result.checked]
    lines += ["", "## Not checked", ""]
    lines += [f"- {rule}" for rule in result.not_checked]
    lines.append("")
    return "\n".join(lines)
