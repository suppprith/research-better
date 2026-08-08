"""Voice profile extraction.

The terminology tests carry the weight. Everything else in the profile shapes
how an edit reads. The terminology set decides whether an edit uses a word the
author never wrote, which is the loudest tell there is.
"""

from __future__ import annotations

from research_better import voice
from research_better.ingest.markdown import ingest
from research_better.voice import MINIMUM_SECTION_WORDS, VoiceProfile


def profile_of(text: str) -> VoiceProfile:
    return voice.extract(ingest("draft.md", text)).whole_paper


def terms(text: str) -> dict[str, int]:
    return dict(profile_of(text).terminology)


# Terminology --------------------------------------------------------------


def test_terminology_is_exact_form_not_lemmatized() -> None:
    text = "The models were trained. The models were tested. The models were released.\n"
    found = terms(text)
    assert found["models"] == 3
    # Lemmatizing would record "model", and an edit using "model" would then
    # look sanctioned when the author never wrote it.
    assert "model" not in found


def test_two_inflections_are_two_entries() -> None:
    text = "We query the index twice. We query it again. Queries are expanded. Queries help.\n"
    found = terms(text)
    assert found["query"] == 2
    assert found["Queries"] == 2


def test_case_is_preserved() -> None:
    text = "Transformer layers are stacked. Transformer layers are deep. transformer use varies.\n"
    assert "Transformer" in terms(text)


def test_a_word_used_once_is_not_yet_a_term() -> None:
    assert "serendipity" not in terms("The result showed serendipity in the ranking.\n")


def test_a_hyphenated_compound_counts_from_one_use() -> None:
    # One use already fixes the form that must not drift, so the count floor
    # does not apply to it.
    assert "self-attention" in terms("The layer applies self-attention over the sequence.\n")


def test_an_acronym_counts_from_one_use() -> None:
    assert "BM25" in terms("We index the corpus with BM25 and rank by score.\n")


def test_stopwords_are_not_terms() -> None:
    found = terms("The system is fast. The system is small. The system is cheap.\n")
    assert "the" not in found
    assert "is" not in found
    assert found["system"] == 3


def test_multi_word_terms_are_recorded() -> None:
    text = "We use query expansion here. Query expansion helps short queries.\n"
    assert any(term.lower() == "query expansion" for term in terms(text))


def test_uses_is_an_exact_string_check() -> None:
    document_profile = profile_of(
        "The models were trained. The models were tested. The models shipped.\n"
    )
    assert document_profile.uses("models")
    assert not document_profile.uses("model")
    assert not document_profile.uses("frameworks")


# Hyphenation --------------------------------------------------------------


def test_hyphenation_records_the_form_the_author_wrote() -> None:
    text = "We apply self-attention here. Then self-attention again over the sequence.\n"
    preferences = dict(profile_of(text).hyphenation)
    assert preferences["selfattention"] == "self-attention"


def test_the_more_common_variant_wins() -> None:
    text = (
        "We use first-pass retrieval. The first-pass stage is cheap.\n\n"
        "A first pass runs before reranking.\n"
    )
    assert dict(profile_of(text).hyphenation)["firstpass"] == "first-pass"


def test_a_bigram_is_not_mistaken_for_a_compound() -> None:
    # "delivers state-of-the-art" collapses to the same key shape as a real
    # compound. Only compounds the author actually hyphenates are tracked.
    text = "It delivers state-of-the-art results. It delivers state-of-the-art speed.\n"
    keys = dict(profile_of(text).hyphenation)
    assert "stateoftheart" in keys
    assert "deliversstateoftheart" not in keys


# Texture ------------------------------------------------------------------


def test_sentence_length_statistics() -> None:
    text = "One two three.\n\nOne two three four five six seven eight nine ten.\n"
    lengths = profile_of(text).sentence_lengths
    assert lengths.count == 2
    assert lengths.mean == 6.5
    assert lengths.p10 == 3
    assert lengths.p90 == 10


def test_hedging_rate_is_per_hundred_words() -> None:
    plain = profile_of("The index is small and the queries are short in every run here.\n")
    hedged = profile_of("The index may possibly be small and queries could perhaps be short.\n")
    assert plain.hedges_per_hundred_words == 0.0
    assert hedged.hedges_per_hundred_words > 20


def test_connectives_are_ranked_by_frequency() -> None:
    text = (
        "However, the gap closed. However, it reopened.\n\n"
        "However, we measured again. Therefore we stopped.\n"
    )
    assert profile_of(text).connectives[0] == ("however", 3)


def test_an_unused_connective_is_absent() -> None:
    assert dict(profile_of("The gap closed after two runs.\n").connectives) == {}


def test_person_detects_first_person_plural() -> None:
    assert profile_of("We measured the gap. Our method closed it.\n").person == "we"


def test_person_detects_first_person_singular() -> None:
    assert profile_of("I measured the gap. My method closed it.\n").person == "i"


def test_person_detects_impersonal_writing() -> None:
    assert profile_of("The gap was measured. The method closed it.\n").person == "impersonal"


def test_passive_ratio_counts_sentences_not_words() -> None:
    assert profile_of("The corpus was indexed by the system.\n").passive_ratio == 1.0
    assert profile_of("The system indexes the corpus.\n").passive_ratio == 0.0


def test_oxford_comma_habit() -> None:
    assert profile_of("It is fast, small, and cheap.\n").oxford_comma == "always"
    assert profile_of("It is fast, small and cheap.\n").oxford_comma == "never"
    assert profile_of("It is fast, small, and cheap.\n\nA is b, c and d.\n").oxford_comma == "mixed"
    assert profile_of("The index is small.\n").oxford_comma == "unknown"


def test_spelling_variant() -> None:
    assert profile_of("We analyse the behaviour of the centre.\n").spelling == "british"
    assert profile_of("We analyze the behavior of the center.\n").spelling == "american"
    assert profile_of("We analyse the behavior of the index.\n").spelling == "mixed"
    assert profile_of("We measured the index.\n").spelling == "unknown"


def test_citation_density_is_per_paragraph() -> None:
    text = "A claim [1] and another [2].\n\nA second paragraph with one [3].\n"
    assert profile_of(text).citations_per_paragraph == 1.5


# Per-section profiles -----------------------------------------------------


def test_a_section_below_the_threshold_gets_no_profile_of_its_own() -> None:
    report = voice.extract(ingest("draft.md", "# Short\n\nToo little text to measure.\n"))
    assert report.sections == ()


def test_a_long_section_gets_its_own_profile(bad_paper) -> None:
    report = voice.extract(bad_paper)
    assert [p.label for p in report.sections] == ["Introduction"]
    assert report.sections[0].word_count >= MINIMUM_SECTION_WORDS


def test_a_short_section_falls_back_to_the_global_profile(bad_paper) -> None:
    report = voice.extract(bad_paper)
    conclusion = next(s for s in bad_paper.sections if s.title == "Conclusion")
    # A profile fitted to four sentences would constrain the edit pass toward
    # noise, so a blended profile is the better answer.
    assert report.for_section(conclusion.id) is report.whole_paper


def test_a_long_section_resolves_to_its_own_profile(bad_paper) -> None:
    report = voice.extract(bad_paper)
    introduction = next(s for s in bad_paper.sections if s.title == "Introduction")
    assert report.for_section(introduction.id).label == "Introduction"


def test_an_unknown_section_falls_back(bad_paper) -> None:
    report = voice.extract(bad_paper)
    assert report.for_section(None) is report.whole_paper
    assert report.for_section("sec-does-not-exist") is report.whole_paper


# Serialization ------------------------------------------------------------


def test_the_report_serializes_with_its_threshold(bad_paper) -> None:
    payload = voice.extract(bad_paper).to_json()
    assert payload["minimum_section_words"] == MINIMUM_SECTION_WORDS
    assert payload["whole_paper"]["scope"] == "whole_paper"
    assert isinstance(payload["sections"], list)


def test_terminology_survives_a_json_round_trip(bad_paper) -> None:
    import json

    payload = json.loads(json.dumps(voice.extract(bad_paper).to_json()))
    recorded = {term for term, _ in payload["whole_paper"]["terminology"]}
    assert "state-of-the-art" in recorded, "an exact hyphenated form must survive"
