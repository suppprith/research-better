"""The public Python API.

`Paper` is the whole surface. Everything else in this package is internal and
may be rearranged between releases, which is why the things a caller needs are
re-exported from the package root: if you are reaching into a submodule, you
are using something that is not promised to stay put. See `docs/API.md`.

Three rules shape it.

**Deterministic passes need no configuration at all.** `Paper.load` then
`paper.fluff()` works with no key, no client, no cache directory, and no
network. Those passes are dictionary and distribution work, and making a caller
set anything up to run them would be charging them for a service they are not
using.

**Passes that reach the network take an injected client.** Pass your own
`PoliteClient` and this package will not build one, so an application that
already has a cache directory, a contact address, and a rate policy keeps them.
Omitting it builds the same client the CLI would, beside the draft, and closes
it again.

**Typed objects come back, never dicts.** The dict form is what gets written to
`.research-better/`, and the artifact schema is a file format rather than an
API. Every result here has a `to_json` if you want that form; nothing here
gives it to you by default.

Sync is the primary surface, including for the network calls, which is a
deliberate departure from a design note that asked for them to be async. The
client underneath is synchronous, so an `async def` wrapping it would occupy
the event loop while advertising that it does not, and a lab script or a
pre-commit hook would be made to open an event loop to check a bibliography.
Each network method has an `_async` twin that runs the same call in a worker
thread, which is a real await for a caller inside an async application and a
promise this package can actually keep.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_better import fluff as fluff_pass
from research_better import grounding as grounding_pass
from research_better import novelty as novelty_pass
from research_better import report as report_pass
from research_better import reviewer as reviewer_pass
from research_better import trace as trace_pass
from research_better import voice as voice_pass
from research_better.artifacts import ArtifactStore
from research_better.edit.ledger import Ledger
from research_better.errors import ResearchBetterError
from research_better.fluff import FluffReport
from research_better.grounding import ClaimReport, GroundingReport, OriginalityReport
from research_better.grounding.verify import CitationCheck
from research_better.ingest import load
from research_better.model import Document
from research_better.net import PoliteClient, default_cache
from research_better.novelty import NoveltyReport
from research_better.report import Report
from research_better.reviewer import ReviewerReport
from research_better.trace import TraceReport
from research_better.voice import VoiceReport


@dataclass(frozen=True, slots=True)
class Paper:
    """One paper, and every check this tool knows how to run on it.

    Cheap to hold and safe to share: the underlying `Document` is frozen and no
    method here mutates anything or writes to disk. Running a pass twice runs
    it twice, which is the honest behaviour for a check whose answer depends on
    a lexicon file or a scholarly API that can change under it.
    """

    document: Document

    @classmethod
    def load(cls, path: Path | str, text: str | None = None) -> Paper:
        """Read a paper from disk, choosing the adapter by file extension.

        `text` supplies the source when it has already been read. A binary
        format ignores it, because text the adapter did not extract would not
        match the offset map it built.
        """
        return cls(load(path, text))

    @property
    def path(self) -> Path:
        return self.document.path

    @property
    def format(self) -> str:
        return self.document.format

    @property
    def word_count(self) -> int:
        """Words of prose. Floats are excluded, which is the number a venue's
        page limit cares about."""
        return self.document.word_count

    # Deterministic passes --------------------------------------------------

    def fluff(self, lexicon_file: Path | None = None) -> FluffReport:
        """Text that does not serve the argument.

        Two halves with different standing. `FluffReport.mechanical` is safe to
        apply; `FluffReport.advisory` rests on a correlation and is not.
        """
        return fluff_pass.report(self.document, lexicon_file)

    def voice(self, lexicon_file: Path | None = None) -> VoiceReport:
        """How this author writes, as a profile an edit can be held to."""
        return voice_pass.extract(self.document, lexicon_file)

    def novelty(self, confirmed: bool = False) -> NoveltyReport:
        """Whether the body supports the contribution the paper claims.

        Raises `NoClaimFoundError` when no claim can be read off the opening,
        which is a finding about the paper rather than a failure of the check.
        Nothing downstream should act on a claim the author has not confirmed,
        so `confirmed` is recorded on the result and defaults to false.
        """
        return novelty_pass.analyse(self.document, confirmed=confirmed)

    def questions(self, venue: str | None = None) -> ReviewerReport:
        """The questions a reviewer will ask. They are not answered here."""
        audit: NoveltyReport | None
        try:
            audit = novelty_pass.analyse(self.document)
        except novelty_pass.NoClaimFoundError:
            # Without a claim there is no blocking contribution question to
            # ask. Every other check still applies.
            audit = None
        return reviewer_pass.analyse(self.document, audit, venue=venue)

    def trace(self, grounding: ClaimReport | None = None) -> TraceReport:
        """Passages that may read as machine-written, with cause and fix.

        Pass the result of `claims()` to include claim support, which is the
        strongest signal the audit has. Without it the audit runs anyway and
        records that it could not see it, rather than reporting a clean paper
        on the strength of a check that did not happen.
        """
        payload = {"claims": grounding.to_json()} if grounding is not None else None
        return trace_pass.analyse(self.document, payload)

    # Passes that reach the network -----------------------------------------

    def verify_citations(self, client: PoliteClient | None = None) -> tuple[CitationCheck, ...]:
        """Resolve every bibliography entry to a real record, or say why not.

        Absence of a record is never reported as fabrication. Each verdict says
        which sources were queried and how close the match was.
        """
        return self.ground(client).checks

    def ground(self, client: PoliteClient | None = None) -> GroundingReport:
        """Citation verification for the whole bibliography."""
        with self._client(client) as http:
            return grounding_pass.analyse(self.document, http)

    def claims(self, client: PoliteClient | None = None) -> ClaimReport:
        """Whether each cited work says what it is cited for.

        A claim checked against an abstract alone comes back `UNCHECKABLE`
        rather than `UNSUPPORTED`, because an abstract not mentioning something
        is no evidence the paper does not say it.
        """
        with self._client(client) as http:
            return grounding_pass.check_claims(self.document, http)

    def originality(self, client: PoliteClient | None = None) -> OriginalityReport:
        """Unattributed overlap with work this tool can actually read.

        Covers retrievable open-access full text and nothing else, and reports
        how many sources it could compare. It is not a plagiarism check and the
        result must not be presented as one.
        """
        with self._client(client) as http:
            return grounding_pass.check_originality(self.document, http)

    async def ground_async(self, client: PoliteClient | None = None) -> GroundingReport:
        return await asyncio.to_thread(self.ground, client)

    async def claims_async(self, client: PoliteClient | None = None) -> ClaimReport:
        return await asyncio.to_thread(self.claims, client)

    async def originality_async(self, client: PoliteClient | None = None) -> OriginalityReport:
        return await asyncio.to_thread(self.originality, client)

    async def verify_citations_async(
        self, client: PoliteClient | None = None
    ) -> tuple[CitationCheck, ...]:
        return await asyncio.to_thread(self.verify_citations, client)

    # The whole check, in order ---------------------------------------------

    def run(
        self,
        store: ArtifactStore | None = None,
        client: PoliteClient | None = None,
        confirmed: bool = False,
        venue: str | None = None,
        offline: bool = False,
    ) -> Report:
        """Every pass, in the order they have to run in, and then the report.

        The method this API was missing. Without it a caller got ten individual
        passes and had to know the order, the gates, and the confirmation stop
        themselves, from a document they were never shown. That made the
        ordering a preference for a library user and a guarantee for a CLI
        user, from the same code.

        The order is `passes.RUN_ORDER`, which is the one the CLI walks:
        ingest first because everything reads it, voice before any pass that
        could propose words, trace after grounding and fluff because it is a
        synthesis of what they found.

        Artifacts are written beside the draft exactly as the CLI writes them,
        because that is what the evidence gate reads and what lets the report
        name the passes that did not run. A pass that refuses is recorded and
        the run continues, so one missing artifact does not cost the rest.

        `confirmed=False` is the honest default and it stops `edit` here, the
        same way it stops it on the command line. Read the claim off the
        `novelty()` result, show it to whoever wrote the paper, and pass
        `confirmed=True` only once they have said it is right.
        """
        from research_better.passes import PASSES, RUN_ORDER, PassContext

        store = store or ArtifactStore(self.document.path)
        source_hash = self.document.source_hash

        with self._client(client, offline=offline) as http:
            context = PassContext(
                document=self.document,
                client=http,
                offline=offline,
                venue=venue,
                claim_confirmed=confirmed,
                store=store,
            )
            for name in RUN_ORDER:
                entry = PASSES[name]
                if not entry.implemented or entry.run is None:
                    continue
                if entry.preflight is not None:
                    try:
                        entry.preflight(context, store)
                    except ResearchBetterError:
                        # The same refusal the CLI reports and keeps going
                        # from. `report` reads what exists and names what does
                        # not, so the gap is in the returned page rather than
                        # swallowed.
                        continue
                result = entry.run(context)
                store.write(entry.artifact, result.payload, source_hash, offline=offline)
                if result.markdown is not None:
                    store.write_text(entry.artifact, result.markdown, source_hash)

        return self.report(store)

    def edit(
        self,
        store: ArtifactStore | None = None,
    ) -> Ledger:
        """The changes the evidence supports, as proposals. Nothing is written.

        Behind the same evidence gate the CLI is behind, and for the same
        reason: a prompt is a preference and a check is a guarantee. It refuses
        unless the novelty, grounding, fluff, and voice artifacts all exist,
        all carry the hash of the draft as it is on disk right now, and the
        contribution claim has been confirmed. Run `run()` first, or the
        matching passes by hand.

        Raises `EvidenceGateError` naming the first thing missing and the
        command that produces it.

        Proposing is the whole surface. Writing the patch back into somebody's
        draft stays on the command line, where `--apply` is a thing a person
        typed, a backup is taken, and `rb revert` undoes it.
        """
        from research_better import edit as edit_layer

        store = store or ArtifactStore(self.document.path)
        bundle = edit_layer.gather(store, self.document.source_hash)
        lock = edit_layer.VoiceLock.of(self.document, bundle.payload("voice"))
        decisions = edit_layer.load_decisions(store)
        return edit_layer.build(
            self.document,
            bundle,
            edit_layer.rejected_ids(decisions),
            edit_layer.screen(lock),
        )

    # The one page ----------------------------------------------------------

    def report(self, store: ArtifactStore | None = None) -> Report:
        """One page of what was found and what could not be checked.

        Built from the artifacts written beside the draft rather than from
        anything held in memory, which is what lets it name the passes that did
        not run. A `Paper` used purely as a library has written nothing, so a
        report over it will say so about every pass, which is the truth.
        """
        return report_pass.build(self.document, store or ArtifactStore(self.document.path))

    def to_json(self) -> dict[str, Any]:
        """The document structure, as the ingest artifact records it."""
        from research_better.serialize import document_to_json

        return document_to_json(self.document)

    # Internals -------------------------------------------------------------

    @contextmanager
    def _client(self, client: PoliteClient | None, offline: bool = False) -> Iterator[PoliteClient]:
        """Use the caller's client, or build and close one just like the CLI.

        A client the caller passed is never closed here. It is theirs, it may
        be serving other work, and closing somebody else's connection pool
        because one function finished with it is the kind of thing that shows
        up much later as an unrelated bug.

        `offline` only applies to a client built here. A caller who passed
        their own already decided this, and quietly overriding it would mean
        `offline=False` could put a deliberately offline client on the network.
        """
        if client is not None:
            yield client
            return
        with PoliteClient(default_cache(self.document.path), offline=offline) as built:
            yield built
