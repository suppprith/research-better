"""Sentence segmentation for academic prose.

Everything downstream inherits this module's bugs. A missed boundary merges two
claims into one span, so a citation check reports the wrong sentence as
unsupported. A false boundary splits a claim in half, so neither half looks
like a claim at all. That is why segmentation lives alone with its own tests.

Splitting on `[.!?]\\s+` fails immediately on the text this tool reads. It cuts
"et al." in half, cuts "Fig. 3" in half, cuts version numbers, and cuts inside
inline math. The scanner below rejects a candidate boundary when any of the
following holds:

* The word before the period is a known abbreviation or a single initial.
* The period sits inside inline math, inline code, or a caller-supplied
  protected range.
* Bracket depth is above zero, so the period belongs to a parenthetical.
* The next word starts with a lowercase letter, which means the text continued.

A period followed by a closing bracket or quote is still a boundary. The
boundary lands after the closing character, so `He showed it works." Next` cuts
in the right place.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

TERMINATORS = ".!?"

# Curly quotes and guillemets are written as escapes so a reader cannot mistake
# them for the straight quotes next to them.
CLOSING_CHARACTERS = ")]}\"'”’»"

_OPENING_BRACKETS = "(["
_CLOSING_BRACKETS = ")]"

ABBREVIATIONS: frozenset[str] = frozenset(
    {
        # Reference and cross-reference shorthand, the common case in papers.
        "al",
        "et al",
        "e.g",
        "i.e",
        "cf",
        "viz",
        "vs",
        "etc",
        "resp",
        "ibid",
        "op cit",
        "fig",
        "figs",
        "eq",
        "eqs",
        "eqn",
        "eqns",
        "sec",
        "secs",
        "sect",
        "ch",
        "chap",
        "chaps",
        "tab",
        "tabs",
        "alg",
        "app",
        "ref",
        "refs",
        "no",
        "nos",
        "vol",
        "vols",
        "p",
        "pp",
        "ed",
        "eds",
        "edn",
        "rev",
        # Titles and organisations.
        "dr",
        "prof",
        "mr",
        "mrs",
        "ms",
        "jr",
        "sr",
        "st",
        "inc",
        "ltd",
        "co",
        "corp",
        "dept",
        "univ",
        "u.s",
        "u.k",
        "e.u",
        # Measurement and statistics shorthand.
        "approx",
        "avg",
        "min",
        "max",
        "std",
        "var",
        "est",
        "ca",
        "sd",
        "se",
        # Months, which appear in reference lists.
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
    }
)

_TOKEN_BEFORE_PERIOD = re.compile("([A-Za-z][A-Za-z.’']*)$")

_INLINE_PROTECTED_PATTERNS = (
    re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$", re.DOTALL),  # display math, $$ ... $$
    re.compile(r"(?<!\\)\$.*?(?<!\\)\$", re.DOTALL),  # inline math, $ ... $
    re.compile(r"\\\(.*?\\\)", re.DOTALL),  # inline math, \( ... \)
    re.compile(r"\\\[.*?\\\]", re.DOTALL),  # display math, \[ ... \]
    re.compile(r"`+[^`]*`+"),  # inline code
)


def find_inline_protected(text: str) -> list[tuple[int, int]]:
    """Ranges that segmentation must treat as opaque, detected from the text.

    Callers add format-specific ranges of their own. A LaTeX adapter passes the
    argument of every command, for example, since a period inside `\\cite{x.y}`
    is not a sentence boundary.
    """
    ranges: list[tuple[int, int]] = []
    for pattern in _INLINE_PROTECTED_PATTERNS:
        for match in pattern.finditer(text):
            ranges.append((match.start(), match.end()))
    return merge_ranges(ranges)


def merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sort and coalesce overlapping half-open ranges."""
    ordered = sorted(r for r in ranges if r[1] > r[0])
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def _protected_mask(text: str, extra: Sequence[tuple[int, int]]) -> list[bool]:
    mask = [False] * len(text)
    for start, end in merge_ranges([*find_inline_protected(text), *extra]):
        for index in range(max(0, start), min(len(text), end)):
            mask[index] = True
    return mask


def is_abbreviation(text: str, period_index: int) -> bool:
    """Whether the period at `period_index` closes an abbreviation.

    Two cases are accepted. A known abbreviation such as `Fig` or `e.g`, and a
    single capital letter, which is an initial in a name like `J. Smith`.
    """
    match = _TOKEN_BEFORE_PERIOD.search(text[:period_index])
    if match is None:
        return False

    token = match.group(1)
    if len(token) == 1 and token.isupper():
        return True

    candidate = token.rstrip(".").lower()
    if candidate in ABBREVIATIONS:
        return True

    # `et al.` and `op. cit.` carry a space, so also test the two-word form.
    prefix = text[: match.start()].rstrip()
    previous = _TOKEN_BEFORE_PERIOD.search(prefix)
    if previous is not None:
        two_words = f"{previous.group(1).rstrip('.').lower()} {candidate}"
        if two_words in ABBREVIATIONS:
            return True

    return False


def _starts_new_sentence(text: str, index: int) -> bool:
    """Whether the first non-space character at or after `index` can open one."""
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text):
        return True
    character = text[index]
    # A lowercase word means the text ran on, most often because the period was
    # part of something this scanner failed to recognise as an abbreviation.
    return not (character.isalpha() and character.islower())


def split_sentences(text: str, protected: Sequence[tuple[int, int]] = ()) -> list[tuple[int, int]]:
    """Split `text` into sentence ranges.

    Args:
        text: The paragraph to split.
        protected: Half-open ranges, relative to `text`, that must be treated as
            opaque. Inline math and inline code are detected automatically, so
            callers only pass what is specific to their format.

    Returns:
        Half-open `(start, end)` ranges with surrounding whitespace excluded.
        Concatenating `text[start:end]` never loses a character of prose.
    """
    if not text.strip():
        return []

    mask = _protected_mask(text, protected)
    sentences: list[tuple[int, int]] = []
    # One stray opening bracket would otherwise suppress every boundary after
    # it. When the brackets do not balance, stop trusting depth rather than
    # returning the whole paragraph as a single sentence.
    track_depth = _brackets_balance(text)
    depth = 0
    start = 0
    index = 0

    while index < len(text):
        character = text[index]

        if mask[index]:
            index += 1
            continue

        if track_depth and character in _OPENING_BRACKETS:
            depth += 1
        elif track_depth and character in _CLOSING_BRACKETS:
            depth = max(0, depth - 1)
        elif character in TERMINATORS:
            # A closing bracket or quote after the terminator belongs to the
            # sentence that is ending, so the boundary lands after it. Closers
            # consumed here also close their bracket, which is what makes
            # "(the aside ends here.)" a complete sentence rather than an
            # unterminated one.
            end = index + 1
            closed = 0
            while end < len(text) and text[end] in CLOSING_CHARACTERS:
                if text[end] in _CLOSING_BRACKETS:
                    closed += 1
                end += 1

            at_text_end = end >= len(text)
            followed_by_space = not at_text_end and text[end].isspace()
            remaining_depth = depth - closed if track_depth else 0

            if (at_text_end or followed_by_space) and remaining_depth <= 0:
                if character == "." and is_abbreviation(text, index):
                    index += 1
                    continue
                if at_text_end or _starts_new_sentence(text, end):
                    sentences.append((start, end))
                    start = end
                    index = end
                    depth = 0
                    continue

        index += 1

    if start < len(text):
        sentences.append((start, len(text)))

    return [trimmed for trimmed in (_trim(text, s, e) for s, e in sentences) if trimmed]


def _brackets_balance(text: str) -> bool:
    return text.count("(") == text.count(")") and text.count("[") == text.count("]")


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None
