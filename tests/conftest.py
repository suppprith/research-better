"""Shared test helpers.

`build_document` drives `DocumentBuilder` from a deliberately tiny text format:
lines of leading hashes are headings, blank lines separate paragraphs. It exists
so the model and span tests do not depend on any real ingest adapter, which
keeps a segmentation failure from looking like a Markdown failure.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from golden_harness import Golden
from research_better.builder import DocumentBuilder
from research_better.ingest import load
from research_better.model import Document

FIXTURES = Path(__file__).parent / "fixtures"
BAD_PAPER = FIXTURES / "bad-paper.md"

GOOD_PARAGRAPH_OPENER = "Recall at ten rises from 0.62 to 0.71"
"""The paragraph of `bad-paper.md` that every pass must leave alone. A tool
that flags everything is useless, so this is the case that proves the passes
discriminate. See tests/fixtures/README.md."""

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


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Rewrite golden files from the current output. Read the diff before committing.",
    )


@pytest.fixture
def golden(request: pytest.FixtureRequest) -> Golden:
    return Golden(update=bool(request.config.getoption("--update-golden")))


@pytest.fixture(scope="session")
def bad_paper() -> Document:
    """The fixture paper with defects planted on purpose."""
    return load(BAD_PAPER)


@pytest.fixture(scope="session")
def good_paragraph_ids(bad_paper: Document) -> frozenset[str]:
    """Span ids of the one paragraph that must survive every pass untouched."""
    paragraph = next(
        p for p in bad_paper.paragraphs if GOOD_PARAGRAPH_OPENER in bad_paper.text_of(p.span)
    )
    return frozenset(s.id for s in bad_paper.sentences if s.paragraph_id == paragraph.id)
