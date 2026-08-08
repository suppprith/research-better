# The Python API

For using the passes inside something else: a journal's submission checker, a
lab's pre-submission script, a CI job that is not a shell.

```python
from research_better import Paper

paper = Paper.load("draft.tex")

for finding in paper.fluff().mechanical:
    print(finding.rule, finding.matched_text)

profile = paper.voice()
audit = paper.trace()
```

Nothing above needs a key, a client, a cache directory, or a network. Those
passes are dictionary and distribution work, and a caller who only wants them
should not have to configure a service they are not using.

## What is public

Everything re-exported from the package root, and nothing else:

| Entry point | Returns |
| --- | --- |
| `Paper.load(path, text=None)` | `Paper` |
| `paper.fluff(lexicon_file=None)` | `FluffReport` |
| `paper.voice(lexicon_file=None)` | `VoiceReport` |
| `paper.novelty(confirmed=False)` | `NoveltyReport`, raises `NoClaimFoundError` |
| `paper.questions(venue=None)` | `ReviewerReport` |
| `paper.trace(grounding=None)` | `TraceReport` |
| `paper.ground(client=None)` | `GroundingReport` |
| `paper.verify_citations(client=None)` | `tuple[CitationCheck, ...]` |
| `paper.claims(client=None)` | `ClaimReport` |
| `paper.originality(client=None)` | `OriginalityReport` |
| `paper.report(store=None)` | `Report` |

Plus the types those results are made of: `Finding`, `Severity`, `Suggestion`,
`Document`, `Section`, `Paragraph`, `Sentence`, `Span`, `Citation`,
`CitationCheck`, `Verdict`, `ClaimCheck`, `Support`, `Overlap`, `Passage`,
`Signal`, `Standing`, `VoiceProfile`, and the exception hierarchy rooted at
`ResearchBetterError`. `PoliteClient` and `HttpCache` are public because
injecting a client is part of the contract.

`__version__` is public and is the single source of truth. The CLI, the skill's
version check, and the artifact provenance header all read it.

## What is internal

Everything reached by importing a submodule. `research_better.fluff.lexical`,
`research_better.grounding.verify`, `research_better.passes`,
`research_better.ingest.latex`, and the rest are implementation and may be
renamed, split, or removed in any release.

If a symbol you need is not exported from the root, that is a gap worth
raising as an issue rather than a submodule worth importing.

The artifact JSON under `.research-better/` is a file format rather than an
API. Every result object has `to_json()` if you want that shape, but the shape
is written for the report and the skill layer to read and it changes when they
need it to.

## Network calls

`ground`, `verify_citations`, `claims`, and `originality` reach scholarly APIs.
Pass your own client and this package will not build one, so an application
that already has a cache directory, a contact address, and a rate policy keeps
all three:

```python
from research_better import HttpCache, PoliteClient, Paper

with PoliteClient(HttpCache("~/.cache/rb"), contact="you@university.edu") as client:
    paper = Paper.load("draft.tex")
    grounding = paper.ground(client)
    claims = paper.claims(client)
    audit = paper.trace(claims)
```

Reusing one client across the calls is worth doing. Retrieving a source's full
text is by far the expensive part and the cache makes the second call nearly
free.

Omit the client and one is built beside the draft, exactly as the CLI would,
and closed again. A client you passed is never closed for you.

### Async

These are synchronous, including the network ones. The client underneath is
synchronous, so an `async def` wrapping it would hold the event loop while
advertising that it does not, and a lab script or a pre-commit hook would be
made to open an event loop to check a bibliography.

Inside an async application, use the `_async` twin. It runs the same call in a
worker thread, which is a real await rather than a decorated blocking one:

```python
grounding = await paper.ground_async(client)
claims = await paper.claims_async(client)
overlap = await paper.originality_async(client)
```

## Reading a result

Findings carry a severity and a suggestion, and `Finding.auto_actionable`
encodes the only combination safe to apply without asking a human: high
severity, a deletion, and not advisory. `FluffReport` splits the two halves for
you, and the split is why it is a type rather than a list:

```python
report = paper.fluff()
apply_these = report.mechanical  # deletions, safe
show_these = report.advisory  # correlations, never act on them
```

Coverage is part of every result that has any. `ClaimReport` says how many
cited works had retrievable full text, `OriginalityReport` says how many
sources it could compare. Reporting a clean result without those numbers beside
it is the false assurance this tool exists not to give, and that obligation
passes to anything built on this API.

## Stability

Semantic versioning applies to the public surface from the first release. A
breaking change to anything in the table above means a major version. Adding a
pass, adding a field to a result, or adding a keyword argument with a default
is a minor version.

Before 1.0 the surface may still move, and a release that moves it will say so
in the changelog rather than leaving it to be discovered.

## What this API will not do for you

The refusals in [INTEGRITY.md](INTEGRITY.md) are properties of the passes, so
they hold here too. No result fabricates a source, none reports a check that
did not run, and nothing in this package will rewrite a sentence to evade a
detector. Building a wrapper that presents a partial overlap check as a
plagiarism score is outside what this package can stop you doing and inside
what it asks you not to.
