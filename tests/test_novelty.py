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


# Enumerated contribution claims -------------------------------------------
#
# `bad-paper.md` states its contribution in one plain sentence, so the pass had
# never run against the form most real CS papers use. On the first real paper
# the reported unsupported parts were `ii`, `iii`, `iv`, `vi`, `five`, and
# `contributions`. None of those is a claim about anything and none can ever be
# matched by a body sentence, so the claim could never come back supported, and
# that produced the one blocking reviewer question on the paper.

from pathlib import Path  # noqa: E402

ENUMERATED = Path(__file__).parent / "fixtures" / "enumerated-claim.md"


@pytest.fixture(scope="module")
def enumerated():
    return ingest(ENUMERATED, ENUMERATED.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def enumerated_report(enumerated) -> NoveltyReport:
    return novelty.analyse(enumerated)


def test_no_enumerator_is_reported_as_an_unsupported_part(enumerated_report) -> None:
    reported = " ".join(enumerated_report.unsupported_claim_parts).lower()
    for token in ("(i)", "(ii)", "(iii)", "(iv)", "(v)"):
        assert not reported.startswith(token.strip("()")), reported
    assert enumerated_report.unsupported_claim_parts != ()

    words = {
        part.split()[0].strip("()").lower() for part in enumerated_report.unsupported_claim_parts
    }
    assert words <= {"(i)", "(ii)", "(iii)", "(iv)", "(v)", "i", "ii", "iii", "iv", "v"}


def test_no_count_or_structural_word_is_reported(enumerated_report) -> None:
    """`five` and `contributions` describe the claim rather than being part of it."""
    parts = list(enumerated_report.unsupported_claim_parts)
    assert "five" not in parts
    assert "contributions" not in parts
    assert "contribution" not in parts


def test_an_item_the_body_never_picks_up_is_still_reported(enumerated_report) -> None:
    """The rule has to keep working. Nothing in the fixture's body mentions the
    geometric bound, and an author needs to be told that."""
    unsupported = [item for item in enumerated_report.claim_items if not item.supported]
    assert [item.label for item in unsupported] == ["(iii)"]
    assert "geometric bound is tight" in unsupported[0].text


def test_an_unsupported_item_is_named_as_an_item(enumerated_report) -> None:
    """A bag of words is the wrong shape. "item (iii) is not picked up anywhere"
    is an observation an author can act on."""
    assert enumerated_report.unsupported_claim_parts == (
        "(iii) a proof that the geometric bound is tight",
    )


def test_the_items_the_body_does_pick_up_are_supported(enumerated_report) -> None:
    supported = {item.label for item in enumerated_report.claim_items if item.supported}
    assert supported == {"(i)", "(ii)", "(iv)", "(v)"}


def test_a_plain_claim_still_reports_words(bad_paper) -> None:
    """A one-sentence claim has no parts smaller than its content words, and
    the word-level report is still the right answer for it."""
    report = novelty.analyse(bad_paper)
    assert report.claim_items == ()
    assert all(len(part.split()) == 1 for part in report.unsupported_claim_parts)


def test_a_single_parenthesis_is_not_a_list() -> None:
    """One `(i)` with no `(ii)` after it is a parenthesis. Splitting on it would
    cut a plain claim in half."""
    document = ingest(
        "p.md",
        "# Introduction\n\nWe propose a greedy placement algorithm (i.e. one that "
        "never backtracks) for anchors at a fixed budget.\n",
    )
    assert novelty.analyse(document).claim_items == ()


def test_an_item_list_written_with_item_is_read_the_same_way() -> None:
    r"""The `\item` form, which is how a LaTeX paper writes the same list."""
    assert [
        label
        for label, _ in novelty.split_claim_items(
            r"We make the following contributions: \item a convergence proof "
            r"\item a placement algorithm \item an evaluation across four floors"
        )
    ] == [r"\item", r"\item", r"\item"]


def test_the_blocking_question_clears_when_the_claim_resolves(
    enumerated, enumerated_report
) -> None:
    """The downstream half. The blocking reviewer question reads this report,
    and it was firing on `ii`, `iii`, and `contributions`."""
    from research_better import reviewer

    questions = reviewer.analyse(enumerated, enumerated_report)
    blocking = [q for q in questions.questions if q.severity is reviewer.Severity.BLOCKING]
    unsupported = [q for q in blocking if q.category == "unsupported_claim"]

    # The question is still asked, because item (iii) really is unsupported.
    assert len(unsupported) == 1
    # What it names is the item, not `ii`, `iii`, `five`, and `contributions`.
    assert "(iii) a proof that the geometric bound is tight" in unsupported[0].why
    for token in (" ii,", " iv,", " five,", " contributions,"):
        assert token not in unsupported[0].why


def test_the_blocking_question_disappears_when_every_item_is_supported() -> None:
    """The other half of the acceptance: a paper whose contribution really is
    established raises nothing, and one whose is not still does."""
    from research_better import reviewer

    document = ingest(
        "p.md",
        "# Introduction\n\nWe make the following contributions: (i) a placement "
        "algorithm at a fixed budget, and (ii) an evaluation across four floors.\n\n"
        "# Results\n\nOur algorithm places anchors at a fixed budget. Coverage rose "
        "across the four floors we evaluated.\n",
    )
    report = novelty.analyse(document)
    assert report.unsupported_claim_parts == ()
    assert all(item.supported for item in report.claim_items)

    questions = reviewer.analyse(document, report)
    assert not [q for q in questions.questions if q.category == "unsupported_claim"]
