"""Shared test helpers.

`build_document` drives `DocumentBuilder` from a deliberately tiny text format:
lines of leading hashes are headings, blank lines separate paragraphs. It exists
so the model and span tests do not depend on any real ingest adapter, which
keeps a segmentation failure from looking like a Markdown failure.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from research_better.builder import DocumentBuilder
from research_better.model import Document

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

BuildDocument = Callable[[str], Document]


def _build(text: str) -> Document:
    builder = DocumentBuilder("memo.txt", "plain", text)
    offset = 0
    for block in text.split("\n\n"):
        stripped = block.strip("\n")
        lead = len(block) - len(block.lstrip("\n"))
        start = offset + lead
        heading = HEADING.match(stripped)
        if heading:
            builder.add_section(
                title=heading.group(2).strip(),
                level=len(heading.group(1)),
                heading_span=builder.span(start, start + len(stripped)),
            )
        elif stripped.strip():
            builder.add_paragraph(builder.span(start, start + len(stripped)))
        offset += len(block) + 2
    return builder.build()


@pytest.fixture
def build_document() -> BuildDocument:
    return _build
