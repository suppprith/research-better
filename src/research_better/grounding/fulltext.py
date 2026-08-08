"""Getting the actual text of a cited work, when that is possible at all.

Three routes, tried in order of how much they let the tool see:

1. arXiv's rendered HTML, which is full text and needs no optional dependency.
   Only recent submissions have it.
2. An open-access PDF, read with the same adapter that reads the author's own,
   which needs the `pdf` extra. Without it this route is skipped and the reason
   is recorded rather than the failure being silent.
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

from research_better.errors import IngestError
from research_better.extras import available
from research_better.net import OfflineCacheMissError, PoliteClient, SourceUnavailableError
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

MINIMUM_FULL_TEXT = 2000
"""Characters a retrieval has to yield before it counts as full text. A stub
page, a cover sheet, or a scan comes in far under this, and labelling one of
those full text is what turns "nothing was read" into "the source does not say
it"."""


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
        text, why = _open_access_pdf(client, work.open_access_url)
        if text is not None:
            return text
        return _abstract(
            work,
            note=(
                f"The open-access PDF at {work.open_access_url} was not read, because "
                f"{why}, so only the abstract was used."
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
    if len(text) < MINIMUM_FULL_TEXT:
        return None
    return SourceText(FULL_TEXT, text, url, "Full text read from the arXiv HTML rendering.")


def _open_access_pdf(client: PoliteClient, url: str) -> tuple[SourceText | None, str]:
    """The cited work's own PDF, read with the same adapter as the author's.

    An open-access copy sits wherever the publisher or the repository put it,
    so this is the one route that fetches from a host nobody chose. Anything
    that is not a readable paper comes back with the reason instead, and the
    caller falls to the abstract carrying it. Nothing here is fatal to a run: a
    source read badly is worse evidence than a source honestly not read, and an
    abstract can never make a claim come back unsupported.

    An offline cache miss is caught here rather than left to be loud, which it
    is everywhere else. Loudness earns its place where silence would show up
    downstream as a finding about the paper, and this cannot: the fallback is
    labelled an abstract, and a claim checked against one comes back unchecked.
    """
    from research_better.ingest.pdf import prose, read_bytes

    try:
        response = client.get("open_access", url, ttl_seconds=client.limits.fulltext_ttl_seconds)
    except OfflineCacheMissError:
        return None, "it is not in the cache and this run is offline"
    except SourceUnavailableError as error:
        return None, f"the host did not answer ({error.reason})"

    if not response.ok:
        return None, f"the host answered {response.status}"
    if not response.body.startswith(b"%PDF"):
        # A repository that has moved the file answers with a landing page and
        # a 200. Extracting that would yield a navigation menu.
        return None, "what came back was not a PDF, which is what a moved file looks like"

    try:
        text = prose(read_bytes(response.body, url))
    except IngestError:
        return None, "the file could not be parsed"
    if len(text) < MINIMUM_FULL_TEXT:
        # A scan, a cover sheet, or a page of figures. Calling that full text
        # would let a claim come back unsupported on the strength of a document
        # nothing was actually read from.
        return None, "it yielded too little text to be a paper, which is what a scan does"
    return SourceText(FULL_TEXT, text, url, "Full text read from the open-access PDF."), ""


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
