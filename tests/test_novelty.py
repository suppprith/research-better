"""The novelty audit, and the guards that keep it from gutting the paper.

Two failure modes matter more than any true positive here. Guessing a claim
when none is stated makes every downstream cut wrong, and the naive reading of
"cut what does not serve the novelty" deletes the related work and the
limitations section. Both are tested directly.
"""

from __future__ import annotations

import pytest

from research_better import novelty
from research_better.findings import Severity, Suggestion
from research_better.ingest.markdown import ingest
from research_better.novelty import NoClaimFoundError, NoveltyReport, Role


@pytest.fixture(scope="module")
def report(bad_paper):
    return novelty.analyse(bad_paper)


def roles_in(bad_paper, report: NoveltyReport, section_title: str) -> set[str]:
    section = next(s for s in bad_paper.sections if s.title == section_title)
    return {
        report.roles[s.id]
        for s in bad_paper.sentences
        if s.section_id == section.id and s.id in report.roles
    }


# The claim ----------------------------------------------------------------


def test_the_contribution_claim_is_extracted(report: NoveltyReport) -> None:
    assert report.claim
    assert "formal proof that adaptive retrieval converges" in report.claim


def test_the_claim_starts_unconfirmed(report: NoveltyReport) -> None:
    # If the claim is wrong, every cut downstream is wrong, and the author is
    # the only one who knows.
    assert not report.claim_confirmed


def test_confirmation_is_asked_for_in_the_author_s_own_words(report: NoveltyReport) -> None:
    prompt = novelty.confirmation_prompt(report)
    assert report.claim in prompt
    assert "every cut downstream depends on it" in prompt


def test_a_paper_with_no_claim_stops_rather_than_guessing() -> None:
    draft = ingest(
        "d.md",
        "# Introduction\n\nRetrieval is hard. Many people have studied it.\n\n"
        "# Method\n\nThe corpus was indexed and queries were run.\n",
    )
    with pytest.raises(NoClaimFoundError) as error_info:
        novelty.analyse(draft)
    message = str(error_info.value)
    assert "Nothing was cut and nothing was judged" in message
    assert "State the contribution in one sentence" in message


def test_a_method_sentence_is_not_mistaken_for_a_claim() -> None:
    # "we use" appears all over a method section and is not a contribution.
    draft = ingest("d.md", "# Method\n\nWe use BM25 with default parameters.\n")
    with pytest.raises(NoClaimFoundError):
        novelty.analyse(draft)


# The planted unsupported contribution -------------------------------------


def test_the_unsupported_contribution_is_caught(report: NoveltyReport) -> None:
    # The fixture claims a formal proof of convergence and never proves
    # anything.
    assert not report.claim_is_supported
    for word in ("proof", "converges", "bounded", "drift"):
        assert word in report.unsupported_claim_parts


def test_the_unsupported_contribution_becomes_a_high_finding(report: NoveltyReport) -> None:
    finding = next(
        f for f in novelty.to_findings(report) if f.rule == "novelty_unsupported_contribution"
    )
    assert finding.severity is Severity.HIGH
    assert "the claim is broader than what was done" in (finding.note or "")


# Orphans ------------------------------------------------------------------


def test_the_three_planted_orphan_paragraphs_are_flagged(report: NoveltyReport) -> None:
    flagged = " ".join(orphan.text for orphan in report.orphans)
    assert "Search engines are used by billions" in flagged
    assert "Databases have existed since the 1960s" in flagged
    assert "Peer review has been studied for many years" in flagged


def test_the_good_paragraph_is_never_an_orphan(bad_paper, report, good_paragraph_ids) -> None:
    # A short sentence sitting among three sentences of measurements is part of
    # reporting those measurements. Judging sentences alone is how a cutting
    # tool starts deleting the author's actual findings.
    for orphan in report.orphans:
        assert orphan.span_id not in good_paragraph_ids
        assert "Recall at ten rises" not in orphan.text


def test_the_limitations_section_is_not_cut(bad_paper, report: NoveltyReport) -> None:
    # Reviewers require limitations. Cutting them because they do not advance
    # the novelty claim would fail the paper.
    assert roles_in(bad_paper, report, "Limitations") == {str(Role.LIMITATION)}
    flagged = " ".join(orphan.text for orphan in report.orphans)
    assert "did not evaluate on non-English" not in flagged


def test_cited_related_work_is_not_cut(bad_paper, report: NoveltyReport) -> None:
    # Background that contextualizes rather than directly supports the novelty
    # is doing its job.
    assert str(Role.BACKGROUND) in roles_in(bad_paper, report, "Related Work")
    flagged = " ".join(orphan.text for orphan in report.orphans)
    assert "Sparse retrieval has a long history" not in flagged


def test_orphans_are_whole_paragraphs(bad_paper, report: NoveltyReport) -> None:
    for orphan in report.orphans:
        start, end = orphan.char_range
        assert " ".join(bad_paper.source_text[start:end].split()) == orphan.text


def test_a_bare_number_is_not_evidence() -> None:
    # "Databases have existed since the 1960s" contains a digit and reports
    # nothing about the paper.
    draft = ingest(
        "d.md",
        "# Introduction\n\nWe propose a faster index.\n\n"
        "# Background\n\nDatabases have existed since the 1960s. "
        "Relational algebra came later. Many systems still use it.\n",
    )
    result = novelty.analyse(draft)
    assert any("Databases have existed" in orphan.text for orphan in result.orphans)


# Roles --------------------------------------------------------------------


def test_every_sentence_gets_exactly_one_role(bad_paper, report: NoveltyReport) -> None:
    assert set(report.roles) == {s.id for s in bad_paper.sentences}
    assert set(report.roles.values()) <= {str(role) for role in Role}


def test_a_cited_sentence_is_background_wherever_it_sits() -> None:
    draft = ingest(
        "d.md",
        "# Introduction\n\nWe propose a faster index.\n\n"
        "# Method\n\nPrior work established the baseline [1].\n",
    )
    result = novelty.analyse(draft)
    cited = next(s for s in draft.sentences if "[1]" in s.text)
    assert result.roles[cited.id] == str(Role.BACKGROUND)


def test_serves_records_which_claim_words_a_sentence_carries(report: NoveltyReport) -> None:
    assert report.serves
    for parts in report.serves.values():
        assert parts == sorted(parts)


# Findings -----------------------------------------------------------------


def test_nothing_is_auto_applied(report: NoveltyReport) -> None:
    for finding in novelty.to_findings(report):
        # Cutting a paragraph is the biggest edit this tool can propose and the
        # tool cannot see why the author put it there.
        assert finding.suggestion is Suggestion.REVIEW
        assert not finding.auto_actionable


def test_orphan_findings_are_medium_not_high(report: NoveltyReport) -> None:
    orphan_findings = [
        f for f in novelty.to_findings(report) if f.rule == "novelty_orphan_paragraph"
    ]
    assert orphan_findings
    assert all(f.severity is Severity.MEDIUM for f in orphan_findings)


def test_the_report_serializes(report: NoveltyReport) -> None:
    payload = report.to_json()
    assert payload["claim"]
    assert payload["claim_confirmed"] is False
    assert isinstance(payload["orphans"], list)
    assert isinstance(payload["roles"], dict)
