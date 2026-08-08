"""Getting the actual text of a cited work, when that is possible at all.

Three routes, tried in order of how much they let the tool see:

1. arXiv's rendered HTML, which is full text and needs no optional dependency.
   Only recent submissions have it.
2. An open-access PDF, which needs the `pdf` extra. Without it this route is
   skipped and the reason is recorded rather than the failure being silent.
3. The abstract, which is not full text and is labelled as such everywhere it
   is used.

The distinction between route 3 and routes 1 and 2 is not cosmetic. An abstract
that does not mention something is no evidence the paper does not say it, so a
claim checked against an abstract alone can never come back unsupported. It
comes back unchecked, which is the truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from research_better.extras import available
from research_better.net import PoliteClient, SourceUnavailableError
from research_better.sources.base import Work

ARXIV_HTML = "https://arxiv.org/html/{arxiv_id}"

SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
HEADING = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.DOTALL | re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")
BLOCK_END = re.compile(r"</(p|div|section|li|h[1-6])>", re.IGNORECASE)
ENTITY = re.compile(r"&(#\d+|[a-z]+);", re.IGNORECASE)

FULL_TEXT = "full_text"
ABSTRACT = "abstract"
NONE = "none"


@dataclass(frozen=True, slots=True)
class SourceText:
    """What could actually be read of a cited work."""

    kind: str
    text: str
    url: str | None = None
    note: str = ""

    @property
    def is_full_text(self) -> bool:
        return self.kind == FULL_TEXT

    @property
    def available(self) -> bool:
        return self.kind != NONE and bool(self.text.strip())

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "url": self.url,
            "characters": len(self.text),
            "note": self.note,
        }


def html_to_text(html: str) -> str:
    """Flatten HTML into readable prose, keeping block boundaries.

    Deliberately not a parser. The job is to recover sentences that can be
    quoted back to the author, and a tag stripper does that without adding a
    dependency to a tool somebody installed to check citations.
    """
    body = SCRIPT_OR_STYLE.sub(" ", html)
    body = HEADING.sub(lambda match: f"\n\n{TAG.sub(' ', match.group(1))}\n\n", body)
    body = BLOCK_END.sub("\n\n", body)
    body = TAG.sub(" ", body)
    body = ENTITY.sub(" ", body)
    paragraphs = [" ".join(part.split()) for part in body.split("\n\n")]
    return "\n\n".join(part for part in paragraphs if part)


def retrieve(client: PoliteClient, work: Work) -> SourceText:
    """The best available text for a work, and an honest label for what it is."""
    if work.arxiv_id:
        text = _arxiv_html(client, work.arxiv_id)
        if text is not None:
            return text

    if work.open_access_url and work.open_access_url.lower().endswith(".pdf"):
        if not available("pypdf"):
            return _abstract(
                work,
                note=(
                    f"An open-access PDF exists at {work.open_access_url}, but the "
                    f'"pdf" extra is not installed, so only the abstract was read. '
                    f'Install it with: pip install "research-better[pdf]"'
                ),
            )
        return _abstract(
            work,
            note=(
                "PDF extraction is not wired up yet, so only the abstract was read. "
                "It lands with the PDF ingest adapter."
            ),
        )

    return _abstract(work)


def _arxiv_html(client: PoliteClient, arxiv_id: str) -> SourceText | None:
    url = ARXIV_HTML.format(arxiv_id=arxiv_id)
    try:
        response = client.get("arxiv", url, ttl_seconds=client.limits.fulltext_ttl_seconds)
    except SourceUnavailableError:
        return None
    if not response.ok:
        # Older submissions have no rendered HTML. Not an error, just a limit.
        return None
    text = html_to_text(response.text)
    if len(text) < 2000:
        return None
    return SourceText(FULL_TEXT, text, url, "Full text read from the arXiv HTML rendering.")


def _abstract(work: Work, note: str = "") -> SourceText:
    if not work.abstract:
        return SourceText(
            NONE,
            "",
            work.open_access_url,
            note or "No open-access full text and no abstract could be retrieved.",
        )
    return SourceText(
        ABSTRACT,
        work.abstract,
        work.open_access_url,
        note
        or (
            "Only the abstract was retrievable. An abstract not mentioning "
            "something is no evidence the paper does not say it."
        ),
    )
