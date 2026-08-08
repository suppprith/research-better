"""The questions a hostile reviewer would ask.

The tool does not answer them, and that constraint is the point rather than a
limitation. Answering them is where the actual research happens, and a tool
that fills the gap with plausible text produces a paper that reads as finished
and is not. If the sample size is missing, this asks for the sample size. It
does not write "on a dataset of moderate size".

Every question carries three things: the span it refers to, why a reviewer
would ask, and what would resolve it. The third is what makes the output
actionable rather than discouraging. A list of problems with no route out is
just a way of telling somebody their paper is bad.

Severity is about consequence, not about how annoyed a reviewer would be:
blocking means it would likely cause rejection, serious means a major revision,
minor means a comment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from research_better.model import Document, Sentence
from research_better.novelty import NoveltyReport
from research_better.venues import VenueProfile, for_venue

NUMBER = re.compile(r"\d")

SIGNIFICANCE_WORDS = ("significantly", "substantially", "dramatically", "markedly")
STATISTICAL_EVIDENCE = (
    "p <",
    "p<",
    "p =",
    "p=",
    "t-test",
    "t test",
    "wilcoxon",
    "mann-whitney",
    "bootstrap",
    "confidence interval",
    "effect size",
    "cohen",
    "standard deviation",
    "error bar",
    "statistically",
)

COMPARISON_WORDS = (
    "outperforms",
    "outperform",
    "beats",
    "better than",
    "faster than",
    "improves over",
    "improves on",
    "superior to",
    "exceeds",
)
NAMED_COMPARISON = ("baseline", "compared with", "compared to", "than the", "versus", "vs.")

GENERALIZATION_WORDS = (
    "in general",
    "always",
    "any dataset",
    "all domains",
    "universally",
    "in all cases",
    "for all",
    "generalizes to",
)

METHOD_DETAILS = (
    (
        "sample size",
        "How much data was this measured on?",
        ("participants", "instances", "queries", "documents", "examples", "samples"),
    ),
    (
        "hyperparameters",
        "What hyperparameters were used?",
        ("learning rate", "batch size", "epochs", "hyperparameter", "k_1", "k1"),
    ),
    (
        "hardware",
        "What hardware was this run on?",
        ("gpu", "cpu", "node", "hardware", "machine", "cluster"),
    ),
    (
        "data split",
        "How was the data split into training, validation, and test?",
        ("train", "training set", "validation", "test set", "split", "held-out"),
    ),
    (
        "number of runs",
        "How many runs was this averaged over, and how were seeds handled?",
        ("seed", "runs", "repetitions", "averaged over", "trials"),
    ),
)

REPRODUCIBILITY_CUES = (
    "available at",
    "we release",
    "we make available",
    "open source",
    "github.com",
    "zenodo",
    "code and data",
    "publicly available",
    "reproducibility",
)

ABLATION_CUES = ("ablation", "ablate", "component analysis", "leave-one-out", "without the")

VALIDITY_CUES = (
    "limitation",
    "limitations",
    "threat to validity",
    "threats to validity",
    "we did not",
    "does not generalize",
    "caveat",
)


class Severity(StrEnum):
    BLOCKING = "blocking"
    SERIOUS = "serious"
    MINOR = "minor"


ORDER = (Severity.BLOCKING, Severity.SERIOUS, Severity.MINOR)


@dataclass(frozen=True, slots=True)
class Question:
    category: str
    severity: Severity
    question: str
    why: str
    resolution: str
    span_id: str
    char_range: tuple[int, int] = (0, 0)
    quote: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": str(self.severity),
            "question": self.question,
            "why": self.why,
            "resolution": self.resolution,
            "span_id": self.span_id,
            "char_range": list(self.char_range),
            "quote": self.quote,
        }


@dataclass(frozen=True, slots=True)
class ReviewerReport:
    questions: tuple[Question, ...] = ()
    venue: str = "default"
    venue_verified: bool = False

    def by_severity(self, severity: Severity) -> tuple[Question, ...]:
        return tuple(q for q in self.questions if q.severity is severity)

    def to_json(self) -> dict[str, Any]:
        return {
            "questions": [question.to_json() for question in self.questions],
            "venue": self.venue,
            "venue_verified": self.venue_verified,
            "counts": {str(level): len(self.by_severity(level)) for level in ORDER},
        }

    def to_markdown(self) -> str:
        lines = [
            "# Reviewer questions",
            "",
            "These are questions, not corrections. Nothing here has been answered for",
            "you, because answering them is the work and a plausible-sounding filler",
            "sentence would make the paper read as finished when it is not.",
            "",
        ]
        if not self.venue_verified:
            lines += [
                f"No verified profile for venue `{self.venue}`, so nothing venue-specific",
                "was assumed. Questions that depend on venue policy say so.",
                "",
            ]

        for level in ORDER:
            questions = self.by_severity(level)
            if not questions:
                continue
            lines.append(f"## {str(level).title()}")
            lines.append("")
            for question in questions:
                lines.append(f"### {question.question}")
                lines.append("")
                if question.quote:
                    lines.append(f"> {question.quote}")
                    lines.append("")
                lines.append(f"**Why a reviewer asks this.** {question.why}")
                lines.append("")
                lines.append(f"**What resolves it.** {question.resolution}")
                lines.append("")
                lines.append(f"`{question.span_id}`")
                lines.append("")
        if not self.questions:
            lines.append("No questions raised by the checks that ran. That is a statement")
            lines.append("about the checks, not a verdict on the paper.")
            lines.append("")
        return "\n".join(lines)


def _has(text: str, cues: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in cues)


def _quote(sentence: Sentence) -> str:
    return " ".join(sentence.text.split())[:220]


def _span(sentence: Sentence) -> tuple[int, int]:
    return (sentence.span.char_start, sentence.span.char_end)


# Sentence-level checks -----------------------------------------------------


def _unquantified_significance(document: Document, sentence: Sentence) -> Question | None:
    if not _has(sentence.text, SIGNIFICANCE_WORDS):
        return None
    if _has(sentence.text, STATISTICAL_EVIDENCE):
        return None
    word = next(w for w in SIGNIFICANCE_WORDS if w in sentence.text.lower())
    return Question(
        category="unquantified_significance",
        severity=Severity.SERIOUS,
        question=f'What test supports "{word}" here?',
        why=(
            "In a results section that word is read as a claim about statistical "
            "significance. With no test, effect size, or interval behind it, a "
            "reviewer cannot tell whether it means a measured result or an "
            "impression, and will assume the latter."
        ),
        resolution=(
            "Report the test and its outcome, or the effect size with an interval. "
            f"If the difference was not tested, delete {word!r} and state the "
            "measured difference instead."
        ),
        span_id=sentence.id,
        char_range=_span(sentence),
        quote=_quote(sentence),
    )


def _missing_baseline(document: Document, sentence: Sentence) -> Question | None:
    if not _has(sentence.text, COMPARISON_WORDS):
        return None
    if _has(sentence.text, NAMED_COMPARISON) or document.citations_in_sentence(sentence.id):
        return None
    return Question(
        category="missing_baseline",
        severity=Severity.SERIOUS,
        question="Outperforms what, exactly?",
        why=(
            "A comparison with no named point of comparison cannot be checked or "
            "reproduced. A reviewer who cannot tell what you beat has to assume you "
            "chose the comparison that flattered the result."
        ),
        resolution=(
            "Name the systems compared against and cite them, or say which "
            "configuration of your own method is the baseline."
        ),
        span_id=sentence.id,
        char_range=_span(sentence),
        quote=_quote(sentence),
    )


def _generalization_overreach(document: Document, sentence: Sentence) -> Question | None:
    if not _has(sentence.text, GENERALIZATION_WORDS):
        return None
    return Question(
        category="generalization_overreach",
        severity=Severity.SERIOUS,
        question="What was actually evaluated, and does the conclusion stay inside it?",
        why=(
            "The sentence claims scope wider than any single evaluation can establish. "
            "This is the easiest thing for a reviewer to attack, because one "
            "counterexample refutes it."
        ),
        resolution=(
            "Narrow the sentence to the conditions you tested, or add the evaluation "
            "that would support the wider claim."
        ),
        span_id=sentence.id,
        char_range=_span(sentence),
        quote=_quote(sentence),
    )


SENTENCE_CHECKS = (_unquantified_significance, _missing_baseline, _generalization_overreach)


# Document-level checks -----------------------------------------------------


def _undisclosed_method_details(document: Document) -> list[Question]:
    body = " ".join(sentence.text for sentence in document.sentences).lower()
    anchor = document.sentences[0] if document.sentences else None
    if anchor is None:
        return []

    questions: list[Question] = []
    for detail, phrasing, cues in METHOD_DETAILS:
        if any(cue in body for cue in cues):
            continue
        questions.append(
            Question(
                category="undisclosed_method_detail",
                severity=Severity.SERIOUS,
                question=phrasing,
                why=(
                    f"The paper never states the {detail}. A reader cannot judge whether "
                    f"the result is solid or reproduce it without knowing, and a "
                    f"reviewer will ask rather than guess."
                ),
                resolution=f"State the {detail} in the method or in an appendix.",
                span_id=anchor.id,
                char_range=_span(anchor),
            )
        )
    return questions


def _missing_ablation(document: Document, venue: VenueProfile) -> list[Question]:
    body = " ".join(sentence.text for sentence in document.sentences).lower()
    if _has(body, ABLATION_CUES) or not document.sentences:
        return []

    # Venue policy decides how hard this is asked. With no verified profile the
    # tool does not get to assert that this venue requires one.
    if venue.expects("ablation_expected"):
        severity, caveat = Severity.SERIOUS, "This venue expects an ablation."
    else:
        severity, caveat = (
            Severity.MINOR,
            "Whether this is required depends on the venue, and no verified profile "
            "was available for yours.",
        )

    anchor = document.sentences[0]
    return [
        Question(
            category="missing_ablation",
            severity=severity,
            question="Which part of the method produces the gain?",
            why=(
                "A method with several components and no per-component evidence leaves "
                f"a reviewer unable to tell what the contribution is. {caveat}"
            ),
            resolution=(
                "Report the result with each component removed in turn, or state "
                "plainly that the components were not separated and why."
            ),
            span_id=anchor.id,
            char_range=_span(anchor),
        )
    ]


def _reproducibility(document: Document) -> list[Question]:
    body = " ".join(sentence.text for sentence in document.sentences)
    if _has(body, REPRODUCIBILITY_CUES) or not document.sentences:
        return []
    anchor = document.sentences[0]
    return [
        Question(
            category="reproducibility",
            severity=Severity.MINOR,
            question="Are the code, data, and environment available?",
            why=(
                "The paper says nothing about availability. Many venues now ask "
                "directly, and a reviewer who cannot find a statement assumes there is "
                "nothing to find."
            ),
            resolution=(
                "Add a sentence saying where the code and data are, or say why they "
                "cannot be released."
            ),
            span_id=anchor.id,
            char_range=_span(anchor),
        )
    ]


def _threats_to_validity(document: Document) -> list[Question]:
    body = " ".join(sentence.text for sentence in document.sentences)
    if _has(body, VALIDITY_CUES) or not document.sentences:
        return []
    anchor = document.sentences[0]
    return [
        Question(
            category="threat_to_validity",
            severity=Severity.SERIOUS,
            question="What would make this result not hold?",
            why=(
                "The paper states no limitations. A reviewer reads that as either "
                "overconfidence or an author who has not looked, and both invite a "
                "harder search for the flaw."
            ),
            resolution=(
                "Add a limitations paragraph naming the conditions under which the "
                "result would not hold. Stating them is stronger than hoping nobody "
                "notices."
            ),
            span_id=anchor.id,
            char_range=_span(anchor),
        )
    ]


def _unsupported_contribution(report: NoveltyReport) -> list[Question]:
    if not report.claim or not report.unsupported_claim_parts:
        return []
    # An enumerated claim names items, and its items are phrases. Joining them
    # with commas turns a list of five claims into one run-on sentence, which
    # is the form this question was asked in when every enumerator counted as a
    # missing part.
    items = bool(report.claim_items)
    missing = ("; " if items else ", ").join(report.unsupported_claim_parts)
    subject = "items of its contribution" if items else "a contribution"
    return [
        Question(
            category="unsupported_claim",
            severity=Severity.BLOCKING,
            question="Where in the paper is the stated contribution established?",
            why=(
                f"The paper claims {subject} that nothing in the body picks up: "
                f"{missing}. A reviewer checks the contribution against the results "
                f"first, and a gap there is the most common single cause of rejection."
            ),
            resolution=(
                "Either add the work that establishes it, or narrow the claim to what "
                "the paper actually shows. Narrowing is not a retreat, it is the "
                "difference between a claim you can defend and one you cannot."
            ),
            span_id=report.claim_span_id or "",
            quote=report.claim,
        )
    ]


def analyse(
    document: Document,
    novelty_report: NoveltyReport | None = None,
    venue: str | None = None,
) -> ReviewerReport:
    """Every question the checks can raise, graded by consequence."""
    profile = for_venue(venue)
    questions: list[Question] = []

    if novelty_report is not None:
        questions.extend(_unsupported_contribution(novelty_report))

    for sentence in document.sentences:
        for check in SENTENCE_CHECKS:
            question = check(document, sentence)
            if question is not None:
                questions.append(question)

    questions.extend(_undisclosed_method_details(document))
    questions.extend(_missing_ablation(document, profile))
    questions.extend(_reproducibility(document))
    questions.extend(_threats_to_validity(document))

    questions.sort(key=lambda q: (ORDER.index(q.severity), q.category, q.char_range[0]))
    return ReviewerReport(
        questions=tuple(questions),
        venue=profile.name,
        venue_verified=profile.verified and profile.name != "default",
    )
