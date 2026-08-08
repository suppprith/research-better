# Grounding protocol

Read before running the grounding pass. Loaded by that pass only.

## Which source answers what

| Need | Source | Why |
|---|---|---|
| Does this DOI exist, and what is its real title | Crossref | Canonical DOI registry |
| Widest coverage, retraction flag, citation count | OpenAlex | Largest index, retraction as a plain field |
| Abstract text for a claim check | Semantic Scholar, OpenAlex | Best abstracts. S2 rate limits hard without a key |
| Recent CS work with no publisher record yet | arXiv | Often the only place it exists |
| Full text to check a claim against | arXiv HTML | Free, no dependency, recent submissions only |

A dead source degrades the answer and never fails the run. Report which sources
answered, because "not found" means something different when three sources
looked than when one did.

## Reading a verdict

| Verdict | What it means | What it does not mean |
|---|---|---|
| `VERIFIED` | Resolved, title and authors and year match | That the work says what it is cited for. That is the claim check |
| `TITLE_MISMATCH` | The identifier resolves to a different title | Fabrication. Usually a copy-paste error |
| `AUTHOR_MISMATCH` | Title matches, authors do not | Much |
| `YEAR_MISMATCH` | Off by a year or two | A problem. Usually preprint versus published |
| `NOT_FOUND` | Nothing matched in the sources queried | **That the work does not exist** |
| `RETRACTED` | The record carries a retraction notice | That citing it is always wrong. Discussing a retraction is legitimate |
| `PREPRINT_ONLY` | No published version found | A problem in itself |
| `UNPARSEABLE` | The entry could not be read | Anything about the work. It is about the entry |

## NOT_FOUND is not an accusation

This is the rule the whole pass is shaped around.

Books, theses, standards documents, older non-English work, workshop papers,
and technical reports are routinely absent from every source here. A tool that
called those fabrications would be wrong often enough to be ignored, which is
the worst thing a checking tool can be.

Never write, imply, or let a user infer any of: fabricated, invented, made up,
does not exist, hallucinated.

Write this instead:

> No record found in OpenAlex, Crossref, or arXiv. That is not proof the work
> does not exist. Check it yourself before concluding anything.

And when the entry looks like a book or a thesis, say so:

> This entry looks like a thesis, and theses are not indexed by these sources
> even when they are entirely real. Absence here is not evidence.

## Claim support

A citation can resolve perfectly and still not support the sentence it is
attached to. Overclaiming a real source is far more common than inventing one.

| Verdict | Report it as |
|---|---|
| `SUPPORTED` | Quote the passage and give its locator |
| `PARTIAL` | Quote what the source actually says. This is the useful one |
| `UNSUPPORTED` | Only when full text was read. Say the matching is lexical |
| `UNCHECKABLE` | No full text. Not a failure and not styled as one |

Quote, never paraphrase. A paraphrase is the tool's opinion wearing the
source's clothes, and the point is that the author can check.

An abstract that does not mention something is no evidence the paper does not
say it. That case is `UNCHECKABLE`, never `UNSUPPORTED`.

## Coverage, always

Every grounding output states how many entries resolved and which sources were
queried. Counts, not percentages. A percentage invites being read as a score
for the bibliography, and this tool does not issue scores.
