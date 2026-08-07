"""Every case in here is text that a naive regex split gets wrong.

Segmentation is the foundation every later pass stands on, so a regression here
is a regression everywhere. New failure modes get a case added, not a patch to
the caller.
"""

from __future__ import annotations

import pytest

from research_better.segmentation import (
    find_inline_protected,
    is_abbreviation,
    merge_ranges,
    split_sentences,
)


def sentences(text: str, protected: list[tuple[int, int]] | None = None) -> list[str]:
    return [text[start:end] for start, end in split_sentences(text, protected or [])]


def test_plain_sentences_split() -> None:
    assert sentences("We ran the model. It converged. Results follow.") == [
        "We ran the model.",
        "It converged.",
        "Results follow.",
    ]


def test_empty_and_whitespace_produce_nothing() -> None:
    assert sentences("") == []
    assert sentences("   \n\n  ") == []


def test_trailing_sentence_without_terminator_is_kept() -> None:
    assert sentences("First one. Second has no period") == [
        "First one.",
        "Second has no period",
    ]


def test_question_and_exclamation_are_boundaries() -> None:
    assert sentences("Does it scale? It does. Remarkably!") == [
        "Does it scale?",
        "It does.",
        "Remarkably!",
    ]


@pytest.mark.parametrize(
    "text",
    [
        "The method of Chen et al. improves recall on the held-out split.",
        "Some models, i.e. transformers, dominate this benchmark.",
        "Several baselines, e.g. BM25, are still competitive.",
        "The layout is shown in Fig. 4 for the largest split.",
        "The loss is given in Eq. 7 and used throughout.",
        "This follows the setup in Sec. 3 without modification.",
        "We compare against BM25 vs. dense retrieval on the same index.",
        "See cf. the appendix for the ablation we could not fit here.",
        "Reported by Dr. Nakamura in the follow-up study.",
        "The figure appears on p. 12 of the proceedings.",
        "Results are listed in Tab. 2 alongside the baselines.",
        "The corpus is described in Ch. 5 of the thesis.",
        "Approximately approx. 40 percent of spans were affected.",
        "The dataset was released in Sept. 2024 by the same group.",
        "Prof. Ito supervised the replication attempt.",
        "The change was proposed by J. Smith during review.",
    ],
)
def test_abbreviations_do_not_split(text: str) -> None:
    assert sentences(text) == [text]


def test_abbreviation_followed_by_a_real_boundary() -> None:
    text = "The method of Chen et al. improves recall. We reproduce that result."
    assert sentences(text) == [
        "The method of Chen et al. improves recall.",
        "We reproduce that result.",
    ]


def test_decimals_and_version_numbers_do_not_split() -> None:
    text = "Accuracy reached 92.4 percent using CUDA 12.1 and PyTorch 2.3.1 on one node."
    assert sentences(text) == [text]


def test_number_ending_a_sentence_still_splits() -> None:
    assert sentences("Accuracy reached 92.4. The baseline reached 88.1.") == [
        "Accuracy reached 92.4.",
        "The baseline reached 88.1.",
    ]


def test_inline_math_does_not_split() -> None:
    text = "We set $\\alpha = 0.5$. The rest follows."
    assert sentences(text) == ["We set $\\alpha = 0.5$.", "The rest follows."]


def test_period_inside_inline_math_is_not_a_boundary() -> None:
    text = "The bound $x = 1. Y$ holds throughout the derivation."
    assert sentences(text) == [text]


def test_latex_inline_math_delimiters_are_protected() -> None:
    text = "Let \\(f(x) = 1. 5\\) denote the scaling factor for all runs."
    assert sentences(text) == [text]


def test_inline_citations_mid_sentence_do_not_split() -> None:
    text = "This was first shown in [1] and later refined in [2, 3] for sparse inputs."
    assert sentences(text) == [text]


def test_bracketed_citation_before_a_boundary() -> None:
    assert sentences("Shown in [1]. Extended in [2].") == [
        "Shown in [1].",
        "Extended in [2].",
    ]


def test_period_inside_parentheses_is_not_a_boundary() -> None:
    text = "The layout is unchanged (see Fig. 2 for the full grid) across all runs."
    assert sentences(text) == [text]


def test_sentence_ending_in_a_closing_bracket_after_the_period() -> None:
    assert sentences('He reported that it works." Later work disagreed.') == [
        'He reported that it works."',
        "Later work disagreed.",
    ]


def test_closing_paren_after_period_ends_the_sentence() -> None:
    text = "The effect held (we report the full table in the appendix.) Nothing else changed."
    assert sentences(text) == [
        "The effect held (we report the full table in the appendix.)",
        "Nothing else changed.",
    ]


def test_lowercase_continuation_is_not_a_boundary() -> None:
    text = "The value was 3 kg. m per second in the original units."
    assert sentences(text) == [text]


def test_unbalanced_bracket_does_not_swallow_the_paragraph() -> None:
    text = "The result (as noted above holds. A second sentence follows."
    assert sentences(text) == [
        "The result (as noted above holds.",
        "A second sentence follows.",
    ]


def test_inline_code_is_protected() -> None:
    text = "Call `model.fit. Now` on the training split before evaluating."
    assert sentences(text) == [text]


def test_caller_supplied_protected_range_is_respected() -> None:
    text = "See \\cite{smith.2020} for details. The rest follows."
    protected = [(text.index("\\cite"), text.index("}") + 1)]
    assert sentences(text, protected) == [
        "See \\cite{smith.2020} for details.",
        "The rest follows.",
    ]


def test_offsets_are_exact() -> None:
    text = "  First one.  Second one.  "
    ranges = split_sentences(text)
    assert [text[start:end] for start, end in ranges] == ["First one.", "Second one."]
    assert ranges[0][0] == 2
    assert ranges[-1][1] == text.rstrip().__len__()


def test_no_prose_is_lost() -> None:
    text = "One claim here. Another claim, e.g. this one. A third at 1.5 units."
    rejoined = " ".join(sentences(text))
    assert rejoined == text


def test_is_abbreviation_rejects_ordinary_words() -> None:
    text = "This works."
    assert is_abbreviation(text, len(text) - 1) is False


def test_merge_ranges_coalesces_and_drops_empties() -> None:
    assert merge_ranges([(5, 9), (0, 3), (2, 6), (9, 9)]) == [(0, 9)]


def test_find_inline_protected_covers_math_and_code() -> None:
    text = "Set $a=1$ then run `go`."
    found = find_inline_protected(text)
    covered = [text[start:end] for start, end in found]
    assert "$a=1$" in covered
    assert "`go`" in covered
