"""Span identifiers, derived from content rather than position.

Every later pass addresses text by span id. A citation check writes "span
s-4f1a9c2b0d33 cites work X", a fluff pass writes "span s-4f1a9c2b0d33 is
unsupported", and the edit pass reads both. Those artifacts outlive the run that
produced them, so an id has to survive the author editing the paper in between.

A running counter cannot do that. Inserting one sentence in the introduction
would shift every id after it, silently repointing every prior finding at the
wrong text. So an id is a hash of the normalized content plus the section path
it sits under. Edit a sentence and only that sentence's id changes.

The cost of content addressing is that two identical sentences under the same
heading hash the same. They are disambiguated by order of appearance with a
`.1`, `.2` suffix. That suffix is the one part of an id that is positional, so
editing the first of several identical sentences does renumber the rest. Exact
repeats under one heading are rare enough that this is the right trade.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

DIGEST_LENGTH = 12
"""Hex characters kept from the digest. 48 bits, which is far more than the
number of sentences in any paper, and short enough to read in a report."""

_FIELD_SEPARATOR = b"\x1f"

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Reduce text to what a reader would call the same sentence.

    Rewrapping a paragraph, converting tabs, or joining a line must not change
    an id, so whitespace runs collapse to one space. Case and punctuation are
    kept, because changing either changes the sentence.
    """
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def digest(*parts: str) -> str:
    """Hash the given parts into a short stable hex string."""
    hasher = hashlib.blake2b(digest_size=8)
    for part in parts:
        hasher.update(part.encode("utf-8"))
        hasher.update(_FIELD_SEPARATOR)
    return hasher.hexdigest()[:DIGEST_LENGTH]


def section_path_key(path: Sequence[str]) -> str:
    """Flatten a section path into one hashable string."""
    return " > ".join(normalize(title) for title in path)


class IdAllocator:
    """Hands out content-derived ids and disambiguates exact repeats.

    One allocator per document build. It is stateful only to count repeats, so
    two builds of the same source produce the same ids in the same order.
    """

    def __init__(self) -> None:
        self._issued: Counter[str] = Counter()

    def allocate(self, prefix: str, *parts: str) -> str:
        base = f"{prefix}-{digest(*parts)}"
        occurrence = self._issued[base]
        self._issued[base] += 1
        return base if occurrence == 0 else f"{base}.{occurrence}"
