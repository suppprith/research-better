"""The edit ledger: proposals the author accepts or rejects one at a time.

The two guarantees worth the most here are that no row exists without evidence
behind it, and that applying the whole ledger leaves every untouched sentence
with the id it had before. The second is what makes an artifact from an earlier
run still mean something after edits land.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from research_better.artifacts import ArtifactStore
from research_better.cli import EXIT_FINDINGS, main
from research_better.edit import gate, ledger
from research_better.edit.gate import EvidenceBundle, MissingEvidenceError
from research_better.edit.ledger import Category, Edit, Ledger
from research_better.ingest import load
from research_better.model import Document


@pytest.fixture
def draft(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "bad-paper.md"
    target = tmp_path / "bad-paper.md"
    target.write_bytes(source.read_bytes())
    return target


@pytest.fixture
def ready(draft: Path) -> Path:
    main(["novelty", str(draft), "--confirm-claim", "--quiet"])
    main(["ground", str(draft), "--quiet"])
    main(["fluff", str(draft), "--quiet"])
    main(["voice", str(draft), "--quiet"])
    return draft


@pytest.fixture
def document(ready: Path) -> Document:
    return load(ready)


@pytest.fixture
def bundle(ready: Path, document: Document) -> EvidenceBundle:
    return gate.gather(ArtifactStore(ready), document.source_hash)


@pytest.fixture
def built(document: Document, bundle: EvidenceBundle) -> Ledger:
    return ledger.build(document, bundle)


def row(**changes: object) -> Edit:
    fields: dict[str, object] = {
        "span_id": "s-000000000001",
        "category": Category.CUT,
        "original": "It is important to note that ",
        "proposed": "",
        "reason": "Filler.",
        "evidence": "fluff:hedge@0-29",
        "confidence": 0.9,
        "char_range": (0, 29),
    }
    fields.update(changes)
    return Edit(**fields)  # type: ignore[arg-type]


# Rows ---------------------------------------------------------------------


def test_the_fixture_produces_edits(built: Ledger) -> None:
    assert built.edits, "the fixture has planted defects, so it must produce proposals"


def test_every_row_carries_a_valid_evidence_pointer(built: Ledger, bundle: EvidenceBundle) -> None:
    for edit in built.edits:
        assert edit.evidence
        bundle.validate(edit.evidence, edit.span_id)


def test_a_row_whose_evidence_names_nothing_never_reaches_the_ledger(
    document: Document, bundle: EvidenceBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ledger, "_fluff_edits", lambda *_: [row(evidence="fluff:invented@0-1")])
    with pytest.raises(MissingEvidenceError):
        ledger.build(document, bundle)


def test_a_row_id_ignores_where_the_text_sits(document: Document) -> None:
    # Ids are content derived so a decision survives the author editing
    # elsewhere and moving every offset in the file.
    assert row(char_range=(0, 29)).id == row(char_range=(900, 929)).id


def test_a_row_id_changes_when_the_proposal_does() -> None:
    assert row(proposed="").id != row(proposed="the").id


def test_words_delta_counts_what_a_row_removes() -> None:
    assert row(original="in order to", proposed="to").words_delta == -2


# Ordering and overlaps ----------------------------------------------------


def test_overlapping_rows_are_detected_and_the_confident_one_kept() -> None:
    strong = row(char_range=(10, 30), confidence=0.9, span_id="s-strong")
    weak = row(char_range=(20, 40), confidence=0.3, span_id="s-weak")

    kept, dropped = ledger.resolve_overlaps([weak, strong])
    assert [edit.span_id for edit in kept] == ["s-strong"]
    assert dropped[0].rule == "overlapping_edit"
    assert strong.id in dropped[0].note


def test_touching_rows_do_not_count_as_overlapping() -> None:
    kept, dropped = ledger.resolve_overlaps(
        [row(char_range=(0, 10), span_id="a"), row(char_range=(10, 20), span_id="b")]
    )
    assert len(kept) == 2 and not dropped


def test_rows_come_back_in_document_order() -> None:
    kept, _ = ledger.resolve_overlaps(
        [row(char_range=(50, 60), span_id="b"), row(char_range=(0, 10), span_id="a")]
    )
    assert [edit.char_range for edit in kept] == [(0, 10), (50, 60)]


def test_applying_runs_back_to_front() -> None:
    text = "one two three four"
    edits = [
        row(char_range=(0, 4), original="one ", proposed="", span_id="a"),
        row(char_range=(8, 14), original="three ", proposed="", span_id="b"),
    ]
    assert ledger.apply_to(text, edits) == "two four"


def test_applying_overlapping_rows_refuses_rather_than_corrupting() -> None:
    edits = [row(char_range=(0, 10), span_id="a"), row(char_range=(5, 15), span_id="b")]
    with pytest.raises(ValueError, match="resolve_overlaps"):
        ledger.apply_to("x" * 20, edits)


def test_the_ledger_never_ships_rows_that_overlap(built: Ledger) -> None:
    ranges = sorted(edit.char_range for edit in built.edits)
    for earlier, later in itertools.pairwise(ranges):
        assert earlier[1] <= later[0]


# What survives an application ---------------------------------------------


def test_unchanged_spans_keep_their_ids_after_the_ledger_is_applied(
    ready: Path, document: Document, built: Ledger
) -> None:
    # By range, not by span id: an orphan row names the paragraph's first
    # sentence and removes all of them.
    before = {
        sentence.id
        for sentence in document.sentences
        if not any(
            sentence.char_start < edit.char_range[1] and edit.char_range[0] < sentence.char_end
            for edit in built.edits
        )
    }

    after = ready.with_name("edited.md")
    after.write_text(ledger.apply_to(document.source_text, built.edits), encoding="utf-8")
    reingested = {sentence.id for sentence in load(after).sentences}

    # An artifact from an earlier run names span ids. If applying a patch
    # renumbered the untouched ones, every finding in it would silently repoint.
    assert before <= reingested


def test_the_good_paragraph_is_left_alone(
    built: Ledger, good_paragraph_ids: frozenset[str]
) -> None:
    # A tool that flags everything is useless. See tests/fixtures/README.md.
    assert not {edit.span_id for edit in built.edits} & good_paragraph_ids


def test_a_cut_that_opens_a_sentence_recases_the_word_behind_it(
    document: Document, built: Ledger
) -> None:
    openers = [
        edit
        for edit in built.edits
        if edit.category is Category.CUT
        and (sentence := document.sentence_at(edit.char_range[0])) is not None
        and sentence.span.char_start == edit.char_range[0]
    ]
    assert openers, "the fixture plants a sentence that opens on filler"
    for edit in openers:
        # Leaving a lower-case sentence opening is a defect the tool introduced,
        # and one no reader would blame on the paper.
        assert edit.proposed[:1].isupper() or not edit.proposed


# Emission -----------------------------------------------------------------


def test_the_diff_is_a_unified_diff(document: Document, built: Ledger) -> None:
    patch = ledger.to_diff(document, built.edits)
    assert patch.startswith(f"--- a/{document.path.name}")
    assert "+++ b/" in patch
    assert "@@" in patch


def test_an_empty_ledger_emits_no_diff(document: Document) -> None:
    assert ledger.to_diff(document, []) == ""


def test_the_summary_groups_by_category(built: Ledger) -> None:
    summary = ledger.to_summary(built)
    assert "# Proposed edits" in summary
    # Grouped so an author can take all the cuts and think about the rest,
    # rather than making the same decision forty times.
    assert "## Cuts" in summary
    for edit in built.edits:
        assert edit.id in summary


def test_the_summary_says_what_was_not_proposed() -> None:
    dropped = ledger.Dropped(edit=row(), rule="overlapping_edit", note="Overlaps e-1.")
    assert "## Not proposed (1)" in ledger.to_summary(Ledger(edits=(), dropped=(dropped,)))


def test_an_empty_ledger_says_so_without_claiming_the_paper_is_clean() -> None:
    summary = ledger.to_summary(Ledger())
    assert "statement about the checks that ran" in summary


# Decisions ----------------------------------------------------------------


def test_a_rejected_row_is_not_proposed_again(
    ready: Path, document: Document, bundle: EvidenceBundle, built: Ledger
) -> None:
    rejected = built.edits[0]
    store = ArtifactStore(ready)
    ledger.save_decisions(store, {rejected.id: ledger.REJECT}, document.source_hash)

    again = ledger.build(document, bundle, ledger.rejected_ids(ledger.load_decisions(store)))
    assert rejected.id not in {edit.id for edit in again.edits}


def test_an_accepted_row_is_still_proposed(
    ready: Path, document: Document, bundle: EvidenceBundle, built: Ledger
) -> None:
    accepted = built.edits[0]
    store = ArtifactStore(ready)
    ledger.save_decisions(store, {accepted.id: ledger.ACCEPT}, document.source_hash)

    again = ledger.build(document, bundle, ledger.rejected_ids(ledger.load_decisions(store)))
    # Accepting is not applying. Writeback is a separate, opt-in step.
    assert accepted.id in {edit.id for edit in again.edits}


def test_decisions_survive_an_edit_elsewhere_in_the_paper(
    ready: Path, bundle: EvidenceBundle, built: Ledger
) -> None:
    store = ArtifactStore(ready)
    ledger.save_decisions(store, {built.edits[-1].id: ledger.REJECT}, "any-hash")
    # Deliberately read without the freshness check the other artifacts get: a
    # decision is about a proposal, not about a draft.
    assert ledger.load_decisions(store) == {built.edits[-1].id: ledger.REJECT}


def test_review_records_accept_and_reject_and_leaves_a_skip_open(built: Ledger) -> None:
    answers = iter(["a", "r", "s"])
    decisions = ledger.review(
        Ledger(edits=built.edits[:3]), lambda _prompt: next(answers), lambda _line: None
    )
    ids = [edit.id for edit in built.edits[:3]]
    assert decisions[ids[0]] == ledger.ACCEPT
    assert decisions[ids[1]] == ledger.REJECT
    # A skip is not a rejection. Somebody who is unsure should get the row back.
    assert ids[2] not in decisions


def test_review_does_not_ask_twice_about_a_settled_row(built: Ledger) -> None:
    settled = {built.edits[0].id: ledger.ACCEPT}
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return "s"

    ledger.review(Ledger(edits=built.edits[:2]), ask, lambda _line: None, settled)
    assert len(asked) == 1


# The command --------------------------------------------------------------


def test_the_pass_writes_a_ledger_a_patch_and_a_summary(ready: Path) -> None:
    assert main(["edit", str(ready), "--quiet"]) == EXIT_FINDINGS
    store = ArtifactStore(ready)
    assert store.path_for("edits").is_file()
    assert store.path_for("edits", ".diff").is_file()
    assert store.path_for("edits", ".md").is_file()


def test_the_patch_file_stays_applicable(ready: Path) -> None:
    main(["edit", str(ready), "--quiet"])
    body = ArtifactStore(ready).path_for("edits", ".diff").read_text(encoding="utf-8")
    # Provenance is never bought at the cost of the file being usable: git skips
    # `#` preamble and would choke on markup.
    assert body.startswith("# research-better")
    assert "\n--- a/" in body


def test_proposing_a_change_is_a_non_zero_exit(ready: Path) -> None:
    # A proposed change is something a CI check should notice, even though the
    # edit pass emits proposals rather than findings.
    assert main(["edit", str(ready), "--quiet"]) == EXIT_FINDINGS
