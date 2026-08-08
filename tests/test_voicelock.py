"""The voice lock and the word budget.

Every rule here runs after a change is proposed rather than being asked for
beforehand, and the tests are written the same way round: they construct a
proposal that breaks a rule and check that it is refused, not that a generator
was told the right thing.

Each rule gets a document built to isolate it, because a paper that trips two
rules at once tells you nothing about either.
"""

from __future__ import annotations

import pytest

from conftest import BuildDocument
from research_better import voice
from research_better.edit import ledger, voicelock
from research_better.edit.ledger import Category, Edit
from research_better.edit.voicelock import Budget, VoiceLock, WordBudgetError
from research_better.model import Document

PAPER = """\
# Method

We index the corpus with a learned sparse model and we expand each query.
We train the expansion model on the training split and we evaluate on the test
split, and we report recall at ten for every configuration we measured.
We analyse the behaviour of the model across four query lengths.

# Results

Recall rises from 0.62 to 0.71 with expansion enabled, and the cost is one
third of the dense baseline over five thousand queries we sampled.
We observe no gain on the long-tail split, and we report that result here.
"""

RHYTHM = """\
# Method

We index the corpus with a learned model.
We train the model on the training split.
We evaluate the model on the test split.
We report recall at ten for each run.
We repeat every run over five seeds.
We measure the cost of each configuration.
We analyse the behaviour of the model across four query lengths and across
three corpus sizes and across two expansion depths and across five random
seeds and across the whole grid of settings we measured for this study.
"""

TEXTURE = """\
# Results

The recall was measured on the test split and we report the cost of the run.

We measured both numbers on the same hardware and we report them again here.
"""


def profiled(document: Document, **options: object) -> VoiceLock:
    return VoiceLock.of(document, voice.extract(document).to_json(), **options)  # type: ignore[arg-type]


@pytest.fixture
def document(build_document: BuildDocument) -> Document:
    return build_document(PAPER)


@pytest.fixture
def lock(document: Document) -> VoiceLock:
    return profiled(document)


def at(document: Document, needle: str, **changes: object) -> Edit:
    """A proposal over the exact characters of `needle` in the draft."""
    start = document.source_text.index(needle)
    fields: dict[str, object] = {
        "span_id": "s-000000000001",
        "category": Category.TIGHTEN,
        "original": needle,
        "proposed": "",
        "reason": "Test.",
        "evidence": "fluff:test@0-1",
        "confidence": 0.8,
        "char_range": (start, start + len(needle)),
    }
    fields.update(changes)
    return Edit(**fields)  # type: ignore[arg-type]


def rule_of(rejection: tuple[str, str] | None) -> str | None:
    return rejection[0] if rejection else None


# Vocabulary ----------------------------------------------------------------


def test_a_word_the_author_never_wrote_is_refused(document: Document, lock: VoiceLock) -> None:
    rejection = lock(at(document, "learned sparse model", proposed="neural retrieval framework"))
    assert rule_of(rejection) == "voice_new_content_word"
    # The reason has to name the word, or the author cannot argue with it.
    assert "framework" in str(rejection)


def test_the_authors_own_words_are_allowed(document: Document, lock: VoiceLock) -> None:
    assert lock(at(document, "learned sparse model", proposed="sparse model")) is None


def test_recasing_a_word_is_not_introducing_one(document: Document, lock: VoiceLock) -> None:
    # A cut that removes a sentence's opening filler recases the word behind it,
    # and that word is the author's own.
    assert lock(at(document, "we expand", proposed="We expand")) is None


def test_a_function_word_is_not_a_new_term(document: Document, lock: VoiceLock) -> None:
    assert lock(at(document, "with a learned", proposed="through a learned")) is None


def test_a_word_from_a_cited_source_is_allowed(document: Document) -> None:
    lock = profiled(document, source_vocabulary=frozenset({"bm25"}))
    assert lock(at(document, "learned sparse model", proposed="bm25 model")) is None


# Sentence length -----------------------------------------------------------


def test_a_proposal_outside_the_length_band_is_refused(build_document: BuildDocument) -> None:
    document = build_document(RHYTHM)
    lock = profiled(document)
    rejection = lock(at(document, "the model on the training split", proposed="the model"))
    assert rule_of(rejection) == "voice_sentence_length"


def test_a_sentence_already_outside_the_band_may_be_edited_toward_it(
    build_document: BuildDocument,
) -> None:
    document = build_document(RHYTHM)
    lock = profiled(document)
    band = lock.whole_paper["sentence_lengths"]
    longest = max(document.sentences, key=lambda s: len(s.text.split()))
    assert len(longest.text.split()) > band["p90"]

    # Refusing this would freeze the author's outliers in place, and an outlier
    # is often exactly what needed the work.
    trimmed = at(document, " and across two expansion depths", proposed="", category=Category.CUT)
    assert lock(trimmed) is None


def test_deleting_a_whole_sentence_is_not_a_length_problem(
    build_document: BuildDocument,
) -> None:
    document = build_document(RHYTHM)
    whole = next(s for s in document.sentences if "five seeds" in s.text)
    assert profiled(document)(at(document, whole.text, proposed="", category=Category.CUT)) is None


# Person and texture --------------------------------------------------------


def test_a_proposal_changing_the_person_is_refused(build_document: BuildDocument) -> None:
    document = build_document(TEXTURE)
    rejection = profiled(document)(
        at(document, "and we report the cost of the run", proposed="and the cost was measured")
    )
    # Whether a paper says "we" or says nothing is a decision the author made
    # once, across the whole paper.
    assert rule_of(rejection) == "voice_person_shift"


def test_a_proposal_changing_the_passive_ratio_is_refused(
    build_document: BuildDocument,
) -> None:
    document = build_document(TEXTURE)
    rejection = profiled(document)(
        at(
            document,
            "The recall was measured on the test split",
            proposed="we measured the recall for the run",
        )
    )
    # The person is unchanged. What moved is how much of the paragraph sits in
    # the passive, and that texture is the author's too.
    assert rule_of(rejection) == "voice_ratio_shift"


def test_a_deletion_is_never_judged_on_texture(build_document: BuildDocument) -> None:
    # A deletion produces nothing, so it cannot introduce a voice that is not
    # the author's. Without this scoping every paragraph cut is refused for
    # having no passives left in it.
    document = build_document(TEXTURE)
    paragraph = document.paragraphs[0]
    text = document.text_of(paragraph.span)
    assert profiled(document)(at(document, text, proposed="", category=Category.CUT)) is None


def test_an_unfamiliar_connective_is_refused(document: Document, lock: VoiceLock) -> None:
    rejection = lock(at(document, "and we expand", proposed="whereas we expand"))
    assert rule_of(rejection) == "voice_unfamiliar_connective"


def test_a_connective_the_author_uses_is_allowed(build_document: BuildDocument) -> None:
    document = build_document(PAPER.replace("and we expand", "whereas we expand"))
    assert (
        profiled(document)(at(document, "whereas we expand", proposed="whereas we index")) is None
    )


# Convention ----------------------------------------------------------------


def test_flipping_the_spelling_convention_is_refused(document: Document, lock: VoiceLock) -> None:
    assert lock.whole_paper["spelling"] == "british"
    # It breaks the vocabulary rule too, and saying so would tell the author
    # nothing they can act on. The specific diagnosis comes first.
    assert rule_of(lock(at(document, "We analyse", proposed="We analyze"))) == (
        "voice_spelling_shift"
    )


def test_flipping_a_hyphenation_habit_is_refused(document: Document, lock: VoiceLock) -> None:
    assert dict(lock.whole_paper["hyphenation"])["longtail"] == "long-tail"
    rejection = lock(at(document, "long-tail split", proposed="longtail split"))
    assert rule_of(rejection) == "voice_hyphenation_shift"


# Word budget ---------------------------------------------------------------


def test_a_result_longer_than_the_original_fails_assembly(document: Document) -> None:
    grew = at(
        document,
        "We index",
        proposed="We index and we also index and we index once more",
        category=Category.GROUND,
    )
    with pytest.raises(WordBudgetError, match="Nothing was written"):
        voicelock.assemble(document, [grew])


def test_a_result_within_the_original_assembles(document: Document) -> None:
    trimmed = at(document, " and we expand each query", proposed="", category=Category.CUT)
    assert voicelock.assemble(document, [trimmed])


def test_a_row_that_adds_words_is_refused_per_edit() -> None:
    assert not voicelock.within_budget(
        Edit("s-1", Category.TIGHTEN, "a", "a b c", "r", "e", 0.8, (0, 1))
    )


def test_a_grounding_row_may_add_words() -> None:
    # Attaching a verified citation to a claim that lacked one is worth the four
    # words it costs.
    assert voicelock.within_budget(
        Edit("s-1", Category.GROUND, "a", "a [4]", "r", "e", 0.8, (0, 1))
    )


def test_the_budget_screen_runs_before_the_voice_rules(document: Document, lock: VoiceLock) -> None:
    check = voicelock.screen(lock)
    grew = at(document, "We index", proposed="We index and we evaluate the model")
    assert rule_of(check(grew)) == "word_budget"


def test_a_missed_target_is_reported_and_not_failed(document: Document) -> None:
    budget = Budget.of(document, target_reduction=0.5)
    note = budget.shortfall(budget.original_words - 1)
    # Falling short of a reduction target is a fact about the draft. Only
    # growing the paper is a failure.
    assert "not a failure of the run" in note


def test_a_met_target_says_so(document: Document) -> None:
    budget = Budget.of(document, target_reduction=0.1)
    assert "meeting the 10% target" in budget.shortfall(budget.target_words - 1)


# The rejection log ---------------------------------------------------------


def test_every_refusal_names_its_rule(bad_paper: Document) -> None:
    from research_better import fluff, novelty
    from research_better.artifacts import Artifact
    from research_better.edit.gate import EvidenceBundle, evidence_ids

    payloads = {
        "fluff": [finding.to_json() for finding in fluff.analyse(bad_paper)],
        "novelty": novelty.analyse(bad_paper, confirmed=True).to_json(),
        "voice": voice.extract(bad_paper).to_json(),
    }
    bundle = EvidenceBundle(
        source_hash=bad_paper.source_hash,
        artifacts={
            name: Artifact(name, "0.1.0", bad_paper.source_hash, "bad-paper.md", "", payload)
            for name, payload in payloads.items()
        },
        pointers=frozenset(
            pointer for name, payload in payloads.items() for pointer in evidence_ids(name, payload)
        ),
        offline=True,
    )

    lock = VoiceLock.of(bad_paper, payloads["voice"])
    built = ledger.build(bad_paper, bundle, screen=voicelock.screen(lock))

    assert built.dropped, "the fixture has to exercise at least one refusal"
    for item in built.dropped:
        assert item.rule
        assert item.note
    # A constraint nobody can inspect is indistinguishable from a tool that felt
    # like saying no.
    summary = ledger.to_summary(built)
    for item in built.dropped:
        assert f"**{item.rule}**" in summary
