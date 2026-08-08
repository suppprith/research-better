"""The public API.

What is tested here is mostly the promises: that the deterministic passes run
with nothing configured, that a client the caller owns is not closed for them,
and that the root exports are the whole surface. Those are the things a caller
builds against and the things a refactor can break silently.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import research_better
from research_better import (
    FluffReport,
    HttpCache,
    NoClaimFoundError,
    Paper,
    PoliteClient,
    Standing,
)

FIXTURE = Path(__file__).parent / "fixtures" / "bad-paper.md"
FIXTURE_HTTP = Path(__file__).parent / "fixtures" / "http"


@pytest.fixture(scope="module")
def paper() -> Paper:
    return Paper.load(FIXTURE)


@pytest.fixture
def client() -> PoliteClient:
    """A caller's own client, reading the recorded responses.

    Forced offline against the fixture cache, which is what the CLI tests do.
    A live client here would query four scholarly APIs and wait out their rate
    limits, and the injection is what is under test rather than the retrieval.
    """
    with PoliteClient(HttpCache(FIXTURE_HTTP, ignore_ttl=True), offline=True) as built:
        yield built


# Zero configuration ---------------------------------------------------------


def test_a_deterministic_pass_needs_no_configuration(paper: Paper) -> None:
    # No key, no client, no cache directory, no network. Someone checking their
    # own filler should not have to set up a service to do it.
    assert len(paper.fluff()) > 0


def test_every_deterministic_pass_runs_from_a_bare_load(paper: Paper) -> None:
    assert paper.voice().whole_paper.word_count > 0
    assert paper.questions().questions
    assert paper.trace().passages
    assert paper.novelty().claim


def test_loading_reports_the_basics(paper: Paper) -> None:
    assert paper.format == "markdown"
    assert paper.path.name == "bad-paper.md"
    assert paper.word_count > 0


def test_a_paper_with_no_claim_raises_rather_than_inventing_one(tmp_path: Path) -> None:
    target = tmp_path / "thin.md"
    target.write_text("# Notes\n\nThe corpus was indexed and the queries were run.\n")
    with pytest.raises(NoClaimFoundError):
        Paper.load(target).novelty()


def test_questions_survive_a_paper_with_no_claim(tmp_path: Path) -> None:
    # Without a claim there is no blocking contribution question, and every
    # other check still applies. Raising here would lose all of them.
    target = tmp_path / "thin.md"
    target.write_text("# Notes\n\nOur method significantly outperforms the baseline.\n")
    assert Paper.load(target).questions() is not None


# Typed objects, not dicts ---------------------------------------------------


def test_results_are_typed_objects(paper: Paper) -> None:
    assert isinstance(paper.fluff(), FluffReport)
    assert not isinstance(paper.voice(), dict)
    assert not isinstance(paper.trace(), dict)


def test_the_dict_form_is_available_and_is_not_the_default(paper: Paper) -> None:
    # The artifact schema is a file format the report and the skill read. It is
    # not the API, and handing it back by default would make it one.
    report = paper.fluff()
    assert isinstance(report.to_json(), list)


def test_the_two_halves_of_the_fluff_report_are_kept_apart(paper: Paper) -> None:
    report = paper.fluff()
    assert report.mechanical
    assert report.advisory
    # An advisory finding rests on a correlation and can never be applied,
    # whatever its severity.
    assert not set(report.mechanical) & set(report.advisory)
    assert all(finding.auto_actionable for finding in report.mechanical)


def test_a_fluff_report_reads_like_the_list_it_replaced(paper: Paper) -> None:
    report = paper.fluff()
    assert len(list(report)) == len(report)


# Client injection -----------------------------------------------------------


def test_the_caller_client_is_used_rather_than_a_new_one(
    paper: Paper, client: PoliteClient
) -> None:
    # A client of its own would have an empty cache and would go to the
    # network. Getting verdicts back from a warm offline one proves the
    # injected client is what ran.
    assert paper.ground(client).checks
    assert client.requests_made == 0


def test_a_client_the_caller_owns_is_not_closed(paper: Paper, client: PoliteClient) -> None:
    # It is theirs, it may be serving other work, and closing somebody else's
    # connection pool shows up much later as an unrelated bug. A second call
    # through a closed client raises.
    paper.ground(client)
    assert paper.claims(client).checks


def test_citation_verdicts_come_back_as_checks(paper: Paper, client: PoliteClient) -> None:
    checks = paper.verify_citations(client)
    assert checks
    assert all(hasattr(check, "verdict") for check in checks)


def test_claim_support_reports_its_own_coverage(paper: Paper, client: PoliteClient) -> None:
    # A clean result with no coverage beside it is the false assurance this
    # tool exists not to give, and that obligation passes to the API.
    report = paper.claims(client)
    assert report.sources_attempted > 0
    assert report.coverage_note


def test_originality_says_how_much_it_could_compare(paper: Paper, client: PoliteClient) -> None:
    report = paper.originality(client)
    assert report.sources_unavailable >= 0
    assert report.sources_compared >= 0


# Async twins ----------------------------------------------------------------


def test_the_async_twin_returns_the_same_thing(paper: Paper, client: PoliteClient) -> None:
    direct = paper.ground(client)
    awaited = asyncio.run(paper.ground_async(client))
    assert [check.key for check in awaited.checks] == [check.key for check in direct.checks]


def test_every_network_call_has_an_async_twin() -> None:
    for name in ("ground", "verify_citations", "claims", "originality"):
        assert hasattr(Paper, f"{name}_async"), f"{name} has no awaitable form"


def test_no_deterministic_pass_has_an_async_twin() -> None:
    # Nobody should have to await a regex.
    for name in ("fluff", "voice", "novelty", "questions", "trace"):
        assert not hasattr(Paper, f"{name}_async")


# Feeding one pass into another ----------------------------------------------


def test_claim_support_can_be_handed_to_the_audit(paper: Paper, client: PoliteClient) -> None:
    audit = paper.trace(paper.claims(client))
    assert not [gap for gap in audit.gaps if "grounding pass has not run" in gap]


def test_the_audit_says_so_when_it_was_given_nothing(paper: Paper) -> None:
    assert any("grounding pass has not run" in gap for gap in paper.trace().gaps)


def test_the_audit_still_returns_a_standing_for_every_passage(paper: Paper) -> None:
    assert all(isinstance(item.standing, Standing) for item in paper.trace().passages)


# The report -----------------------------------------------------------------


def test_a_report_over_a_library_run_names_what_did_not_run(paper: Paper, tmp_path: Path) -> None:
    # A Paper used purely as a library has written nothing, so the report says
    # so about every pass. Silence would read as a clean result.
    empty = Paper.load(tmp_path / "copy.md", FIXTURE.read_text(encoding="utf-8"))
    (tmp_path / "copy.md").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    report = empty.report()
    assert any("has not run" in gap for gap in report.gaps)


# The surface ----------------------------------------------------------------


def test_everything_in_all_is_importable_from_the_root() -> None:
    for name in research_better.__all__:
        assert hasattr(research_better, name), f"{name} is exported and does not exist"


def test_the_surface_is_sorted_so_a_diff_to_it_is_readable() -> None:
    assert research_better.__all__ == sorted(research_better.__all__)


def test_paper_is_the_entry_point() -> None:
    assert "Paper" in research_better.__all__


def test_the_version_is_a_single_source_of_truth() -> None:
    from research_better.artifacts import ArtifactStore  # noqa: F401
    from research_better.net.client import user_agent

    assert research_better.__version__ in user_agent()


def test_no_submodule_is_exported_by_accident() -> None:
    # Reaching into a submodule is the thing docs/API.md asks callers not to
    # do, so the root must not make one look public.
    for name in research_better.__all__:
        attribute = getattr(research_better, name)
        assert not getattr(attribute, "__path__", None), f"{name} is a package"
