"""The AI-trace risk audit.

Half of these tests are about what the pass refuses to do. A pass that reports
which passages look machine-written is one bad decision away from being a
humanizer, and the decisions that keep it from becoming one are the ones worth
pinning down: no detection service, no score, and a texture signal that can
never flag a passage by itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from research_better import trace
from research_better.artifacts import ArtifactStore
from research_better.cli import main
from research_better.ingest import load
from research_better.model import Document
from research_better.passes import PASSES, RUN_ORDER
from research_better.trace import Standing, TraceReport

PACKAGE = Path(trace.__file__).parent

DETECTION_SERVICES = (
    "gptzero",
    "turnitin",
    "originality.ai",
    "copyleaks",
    "zerogpt",
    "winstonai",
    "crossplag",
    "contentatscale",
    "sapling.ai",
)


@pytest.fixture(scope="module")
def audit(bad_paper_module: Document) -> TraceReport:
    return trace.analyse(bad_paper_module)


@pytest.fixture(scope="module")
def bad_paper_module() -> Document:
    return load(Path(__file__).parent / "fixtures" / "bad-paper.md")


def where(report: TraceReport, needle: str) -> trace.Passage:
    return next(item for item in report.passages if needle in item.where)


# What it will not do --------------------------------------------------------


def test_no_detection_service_is_reachable_from_this_package() -> None:
    # The names appear in the docstrings that promise not to call them. What
    # must not appear is one of them at the end of a URL.
    for path in PACKAGE.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "://" not in line:
                continue
            lowered = line.lower()
            named = [service for service in DETECTION_SERVICES if service in lowered]
            assert not named, f"{path.name}:{number} points at {named}"


def test_no_detection_service_is_configured_as_a_source() -> None:
    limits = (PACKAGE / "references" / "source-limits.toml").read_text(encoding="utf-8").lower()
    assert not [service for service in DETECTION_SERVICES if service in limits]


def test_the_audit_has_no_way_to_reach_the_network() -> None:
    # Stronger than asserting it does not call one: it cannot. Nothing here
    # imports a client, and the pass is not registered as needing one.
    source = (PACKAGE / "trace.py").read_text(encoding="utf-8")
    for forbidden in ("httpx", "requests", "urllib", "research_better.net", "PoliteClient"):
        assert forbidden not in source
    assert PASSES["trace"].needs_network is False


def test_nothing_in_the_output_is_a_percentage(audit: TraceReport) -> None:
    assert "%" not in trace.to_markdown(audit)


def test_nothing_in_the_payload_is_a_score(audit: TraceReport) -> None:
    """No bare number anywhere in the artifact.

    A number on a paragraph is a number to optimize, and a tool that gives an
    author a figure that goes down when they reword a sentence has taught them
    to write towards the figure. Measurements appear inside the evidence
    sentence, where they read as what was counted rather than as a grade.
    """

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                assert "score" not in key and "confidence" not in key, f"{path}.{key}"
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        else:
            assert not isinstance(value, float), f"{path} is a bare number"

    walk(audit.to_json(), "trace")


def test_the_counts_that_do_appear_are_counts(audit: TraceReport) -> None:
    counts = audit.to_json()["counts"]
    assert set(counts) == {"flagged", "left_alone", "sections_profiled"}
    assert all(isinstance(value, int) for value in counts.values())


# Every flag names a cause and a fix -----------------------------------------


def test_every_flag_names_at_least_one_cause(audit: TraceReport) -> None:
    assert audit.flagged
    for passage in audit.flagged:
        assert passage.signals


def test_every_signal_says_why_and_what_to_do(audit: TraceReport) -> None:
    for passage in audit.passages:
        for signal in passage.signals:
            assert signal.evidence.strip()
            assert signal.why.strip()
            assert signal.fix.strip(), f"{signal.id} offers no fix, so it should not be reported"


def test_a_texture_signal_never_flags_a_passage_on_its_own(audit: TraceReport) -> None:
    # The rule that protects formulaic prose and non-native English. Rhythm and
    # shape join a flag that already stands; they never create one.
    for passage in audit.flagged:
        assert any(not signal.texture for signal in passage.signals), passage.where


# False positives ------------------------------------------------------------


def test_the_formulaic_methods_paragraph_is_left_alone(audit: TraceReport) -> None:
    passage = where(audit, "Method, paragraph 1")
    assert passage.standing is Standing.LEAVE
    assert passage in audit.left_alone


def test_the_methods_paragraph_is_called_a_likely_false_positive(audit: TraceReport) -> None:
    reason = where(audit, "Method, paragraph 1").reason
    assert "false positive" in reason
    assert "methods" in reason


def test_the_methods_paragraph_tripped_a_signal_and_was_still_left(audit: TraceReport) -> None:
    # The point is not that nothing fired. It is that what fired was rhythm,
    # and a method is uniform because it is a list of steps.
    signals = where(audit, "Method, paragraph 1").signals
    assert [signal.id for signal in signals] == ["uniform_rhythm"]


def test_a_texture_only_passage_is_told_to_leave_it_alone(audit: TraceReport) -> None:
    for passage in audit.left_alone:
        assert "leaving" in passage.reason or "leave" in passage.reason.lower()


def test_an_ordinary_universal_is_not_an_overclaim(audit: TraceReport) -> None:
    # "Search engines are used by billions of people every day" is a sentence
    # about a Tuesday, not a claim needing a citation. Reading "every" as a
    # strength marker here flagged it.
    assert not [item for item in audit.passages if "Related Work, paragraph 6" in item.where]


def test_the_paragraph_that_must_survive_produces_nothing(audit: TraceReport) -> None:
    assert not [item for item in audit.passages if "Results, paragraph 2" in item.where]


# The signals ----------------------------------------------------------------


def test_filler_is_reported_where_it_runs(audit: TraceReport) -> None:
    signals = {signal.id for signal in where(audit, "Introduction, paragraph 1").signals}
    assert "filler" in signals


def test_one_filler_phrase_is_not_a_pattern(bad_paper_module: Document) -> None:
    # Related Work paragraphs 2, 3, and 4 carry one throat-clearing opener
    # each. Everybody writes one of those on a bad afternoon.
    audit = trace.analyse(bad_paper_module)
    for number in (2, 3, 4):
        assert not [
            item for item in audit.passages if f"Related Work, paragraph {number}" in item.where
        ]


def test_stacked_hedges_are_reported(audit: TraceReport) -> None:
    signals = {signal.id for signal in where(audit, "Introduction, paragraph 2").signals}
    assert "hedge_stack" in signals


def test_a_confident_sentence_with_nothing_behind_it_is_reported(audit: TraceReport) -> None:
    passage = where(audit, "Results, paragraph 1")
    signals = {signal.id for signal in passage.signals}
    assert "ungrounded_assertion" in signals
    assert passage.standing is Standing.FIX


def test_the_fix_for_an_ungrounded_assertion_is_evidence_not_wording(
    audit: TraceReport,
) -> None:
    signal = next(
        item
        for item in where(audit, "Results, paragraph 1").signals
        if item.id == "ungrounded_assertion"
    )
    # Add the number, add the citation, or cut it. Never reword it.
    assert "measurement" in signal.fix or "citation" in signal.fix
    assert "synonym" not in signal.fix


def test_an_empty_forward_reference_is_a_cause_rather_than_texture(audit: TraceReport) -> None:
    signal = next(
        item
        for item in where(audit, "Method, paragraph 2").signals
        if item.id == "empty_forward_reference"
    )
    assert not signal.texture


def test_a_structural_signal_keeps_the_fluff_rule_name(audit: TraceReport) -> None:
    # So a reader can look the signal up in fluff.json without a translation.
    ids = {signal.id for passage in audit.passages for signal in passage.signals}
    assert "section_closing_restatement" in ids


# Claim support --------------------------------------------------------------


def test_a_missing_grounding_pass_is_recorded_as_a_gap(audit: TraceReport) -> None:
    assert any("grounding pass has not run" in gap for gap in audit.gaps)


def test_an_unsupported_claim_becomes_a_cause(bad_paper_module: Document) -> None:
    sentence = next(
        item for item in bad_paper_module.sentences if "significantly outperforms" in item.text
    )
    grounding = {
        "claims": {
            "checks": [
                {"span_id": sentence.id, "support": "UNSUPPORTED", "citation_key": "2"},
            ]
        }
    }
    audit = trace.analyse(bad_paper_module, grounding)
    signals = {signal.id for signal in where(audit, "Results, paragraph 1").signals}
    assert "unsupported_claim" in signals
    assert not audit.gaps


def test_a_supported_claim_is_not_a_cause(bad_paper_module: Document) -> None:
    sentence = next(
        item for item in bad_paper_module.sentences if "significantly outperforms" in item.text
    )
    grounding = {
        "claims": {
            "checks": [{"span_id": sentence.id, "support": "SUPPORTED", "citation_key": "2"}]
        }
    }
    audit = trace.analyse(bad_paper_module, grounding)
    signals = {signal.id for signal in where(audit, "Results, paragraph 1").signals}
    assert "unsupported_claim" not in signals


# Voice consistency ----------------------------------------------------------


def _section(title: str, opener: str, filler: str) -> str:
    body = " ".join(f"{opener} {filler} item number {index} in this list." for index in range(14))
    return f"# {title}\n\n{body}\n"


@pytest.fixture
def mixed_authorship(tmp_path: Path) -> Document:
    """A paper whose third section speaks as "I" where the rest says "we"."""
    ours = "we measured the throughput of the system and recorded"
    theirs = "I measured the throughput of the system and recorded"
    text = (
        _section("Introduction", "In this work", ours)
        + "\n"
        + _section("Method", "For each run", ours)
        + "\n"
        + _section("Results", "For each run", theirs)
        + "\n"
        + _section("Conclusion", "In this work", ours)
    )
    target = tmp_path / "mixed.md"
    target.write_text(text, encoding="utf-8")
    return load(target)


def test_a_section_in_a_different_voice_is_raised_for_review(mixed_authorship: Document) -> None:
    audit = trace.analyse(mixed_authorship)
    deviations = [item for item in audit.passages if item.standing is Standing.REVIEW]
    assert deviations
    assert any("Results" in item.where for item in deviations)


def test_the_voice_check_does_not_guess_who_wrote_it(mixed_authorship: Document) -> None:
    audit = trace.analyse(mixed_authorship)
    passage = next(item for item in audit.passages if item.standing is Standing.REVIEW)
    # Copied, drafted elsewhere, or a coauthor. The author knows which and the
    # tool does not, so it says so rather than picking one.
    assert "coauthor" in passage.reason
    assert "does not guess" in passage.reason


def test_a_consistent_paper_raises_no_authorship_question(bad_paper_module: Document) -> None:
    audit = trace.analyse(bad_paper_module)
    assert not [item for item in audit.passages if item.standing is Standing.REVIEW]


def test_too_few_sections_means_no_deviation_is_claimed(tmp_path: Path) -> None:
    # Two sections deviate from each other by construction, and putting an
    # authorship question in front of an author for that is worse than silence.
    target = tmp_path / "short.md"
    target.write_text(
        _section("Introduction", "In this work", "we measured the throughput and recorded")
        + "\n"
        + _section("Results", "For each run", "I measured the throughput and recorded"),
        encoding="utf-8",
    )
    audit = trace.analyse(load(target))
    assert not [item for item in audit.passages if item.standing is Standing.REVIEW]


# The pass -------------------------------------------------------------------


def test_trace_is_a_registered_pass() -> None:
    assert PASSES["trace"].implemented
    assert "trace" in RUN_ORDER


def test_trace_runs_after_the_passes_it_synthesizes() -> None:
    order = list(RUN_ORDER)
    assert order.index("trace") > order.index("fluff")
    assert order.index("trace") > order.index("ground")


@pytest.fixture
def draft(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "bad-paper.md"
    target = tmp_path / "paper.md"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def test_the_command_writes_an_artifact(draft: Path) -> None:
    main(["trace", str(draft), "--quiet"])
    artifact = ArtifactStore(draft).read("trace")
    assert artifact is not None
    assert artifact.payload["flagged"]


def test_the_command_writes_a_page_to_read(draft: Path) -> None:
    main(["trace", str(draft), "--quiet"])
    page = ArtifactStore(draft).path_for("trace", ".md").read_text(encoding="utf-8")
    assert "Looked at, left alone" in page
    assert "INTEGRITY.md" in page


def test_flags_make_the_command_exit_non_zero(draft: Path) -> None:
    assert main(["trace", str(draft), "--quiet"]) == 1


def test_the_audit_reads_grounding_when_it_is_there(draft: Path) -> None:
    main(["ground", str(draft), "--quiet"])
    main(["trace", str(draft), "--quiet"])
    payload = ArtifactStore(draft).read("trace")
    assert payload is not None
    assert not [gap for gap in payload.payload["not_checked"] if "grounding" in gap]


def test_the_report_names_the_flagged_passages_and_their_causes(draft: Path) -> None:
    from research_better.report import build, to_markdown

    main(["trace", str(draft), "--quiet"])
    report = build(load(draft), ArtifactStore(draft))
    assert report.trace_flagged
    page = to_markdown(report)
    assert "May read as machine-written" in page
    # The cause beside the count, always. A count on its own is a score in
    # disguise.
    where_first, causes = report.trace_flagged[0]
    assert f"{where_first}: {causes}" in page
