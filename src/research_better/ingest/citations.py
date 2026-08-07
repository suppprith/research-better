"""Recognising citations in running text.

Shared by every adapter that reads a plain-text-ish format. The patterns here
find the syntaxes that show up in papers people actually write, and just as
importantly they identify what must not be split by segmentation: a URL is full
of periods, and none of them ends a sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PANDOC_CITATION = re.compile(r"\[(-?@[^\]\s;]+(?:\s*;\s*-?@[^\]\s;]+)*)\]")
"""Pandoc style, `[@smith2020]` or `[@a; @b]`."""

NUMERIC_CITATION = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+|\s*[-–]\s*\d+)*)\](?!\()")
"""IEEE style, `[1]`, `[1, 2]`, `[1-3]`. The lookahead keeps a Markdown link
such as `[1](https://example.org)` from being read as a citation."""

DOI = re.compile(
    r"(?:doi:\s*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/[^\s,;\]\)]+)", re.IGNORECASE
)

ARXIV = re.compile(
    r"(?:arxiv:\s*|https?://arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)

MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)")

BARE_URL = re.compile(r"https?://[^\s<>\]\)]+")


@dataclass(frozen=True, slots=True)
class FoundCitation:
    """One citation key located in a piece of text, by relative offset."""

    key: str
    raw: str
    start: int
    end: int


def _expand_numeric(group: str) -> list[str]:
    """Turn `1, 3-5` into `1 3 4 5`.

    Each key is verified separately, because a range can be right at one end
    and wrong at the other.
    """
    keys: list[str] = []
    for part in re.split(r"[,;]", group):
        part = part.strip()
        if not part:
            continue
        span_match = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", part)
        if span_match:
            first, last = int(span_match.group(1)), int(span_match.group(2))
            if 0 < last - first < 100:
                keys.extend(str(value) for value in range(first, last + 1))
                continue
        keys.append(part)
    return keys


def find_citations(text: str) -> list[FoundCitation]:
    """Every citation key in `text`, with offsets relative to `text`.

    A multi-key form produces one entry per key, all pointing at the same
    range. Two of three keys in `[1, 2, 3]` can be correct while the third is
    not, and a report that cannot say which is not much of a report.
    """
    found: list[FoundCitation] = []
    link_ranges = [(m.start(), m.end()) for m in MARKDOWN_LINK.finditer(text)]

    def inside_link(start: int) -> bool:
        return any(low <= start < high for low, high in link_ranges)

    for match in PANDOC_CITATION.finditer(text):
        raw = match.group(0)
        for key in re.split(r"\s*;\s*", match.group(1)):
            cleaned = key.strip().lstrip("-").lstrip("@")
            if cleaned:
                found.append(FoundCitation(cleaned, raw, match.start(), match.end()))

    for match in NUMERIC_CITATION.finditer(text):
        if inside_link(match.start()):
            continue
        raw = match.group(0)
        for key in _expand_numeric(match.group(1)):
            found.append(FoundCitation(key, raw, match.start(), match.end()))

    for pattern, prefix in ((DOI, ""), (ARXIV, "arXiv:")):
        for match in pattern.finditer(text):
            found.append(
                FoundCitation(
                    f"{prefix}{match.group(1)}", match.group(0), match.start(), match.end()
                )
            )

    found.sort(key=lambda citation: (citation.start, citation.key))
    return found


def protected_ranges(text: str) -> list[tuple[int, int]]:
    """Ranges segmentation must not split inside.

    Links and bare URLs are the reason this exists. `https://doi.org/10.1145/1.2`
    contains four periods and no sentence boundary.
    """
    ranges: list[tuple[int, int]] = []
    for pattern in (MARKDOWN_LINK, BARE_URL, DOI, ARXIV, PANDOC_CITATION, NUMERIC_CITATION):
        ranges.extend((match.start(), match.end()) for match in pattern.finditer(text))
    return ranges
