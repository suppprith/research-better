# research-better

A tool that improves research papers by checking them, not by rewriting them.

It verifies that cited work says what you claim it says, flags text that does
not serve the paper's novelty claim, checks for unattributed overlap with
existing literature, and raises the questions a reviewer will ask.

It does not generate replacement prose. When a sentence is weak, the action is
to delete it or ask you about it, never to quietly swap in a sentence you did
not write. Overlap checking covers the open-access full text it can actually
retrieve and says how much that was, so it is not a substitute for Turnitin and
does not claim to be.

## Install

```
pip install research-better
```

Or run it without installing anything:

```
uvx research-better run paper.md
```

Format support is optional so the base install stays small:

```
pip install "research-better[latex]"   # .tex and .bib
pip install "research-better[docx]"    # Word
pip install "research-better[pdf]"     # PDF, review only
pip install "research-better[all]"
```

The base install checks a Markdown paper with no extras at all. Both
`research-better` and `rb` are installed and do the same thing.

### As a Claude Skill

```
/plugin marketplace add suppprith/research-better
/plugin install research-better@research-better
```

Or copy it in by hand, which is the same thing without the marketplace:

```
git clone https://github.com/suppprith/research-better
mkdir -p ~/.claude/skills/research-better
cp research-better/SKILL.md ~/.claude/skills/research-better/
```

Install the Python package either way. The skill drives the CLI and analyses
nothing itself, so a skill without the package is a skill that cannot run. It
checks with `rb doctor` before it starts and stops with the install command
rather than reading the paper by eye. Run `rb doctor` yourself to see the
version, the formats it can read, the extras that are missing with the command
that installs each, and whether a contact address is set.

Invoked on a draft it runs the passes below in order and reports what they
returned, including when they returned nothing. It stops once, after the
novelty pass, to show you the contribution claim it read off your paper and
wait for you to confirm it, because if that claim is wrong every cut after it
is wrong. Artifacts land in `.research-better/` beside the draft, one per pass,
and your draft is untouched unless you ask for `rb edit --apply`, which takes a
backup first and is undone by `rb revert`. What it refuses is in
[docs/INTEGRITY.md](docs/INTEGRITY.md) and holds however the tool is driven.

### As a Python library

```python
from research_better import Paper

paper = Paper.load("draft.tex")
for finding in paper.fluff().mechanical:
    print(finding.rule, finding.matched_text)
```

The deterministic passes need no key, no client, and no network. See
[docs/API.md](docs/API.md) for the public surface and what it promises.

### Shell completion

Completions for bash, zsh, and fish are in [`completions/`](completions), and
they are generated from the parser rather than maintained by hand:

```
source completions/research-better.bash                          # bash
cp completions/research-better.zsh ~/.zfunc/_research-better     # zsh, ~/.zfunc on $fpath
cp completions/research-better.fish ~/.config/fish/completions/  # fish
```

## Use

```
research-better run paper.md
```

Or one pass at a time. This is a real run on the fixture paper, and every line
of it is reproduced by `python scripts/build_example.py`:

```
$ rb ingest paper.md
ingest               54 sentences, 701 words of prose, 9 citations used, 8 in the bibliography

$ rb novelty --confirm-claim paper.md
novelty              7 orphan paragraph(s), 7 unsupported part(s) of the claim

$ rb ground --offline paper.md
ground               3 of 8 entries resolved, 1 of 6 sources had full text

$ rb originality --offline paper.md
originality          2 overlap(s) against 4 source(s), 2 not retrievable

$ rb fluff paper.md
fluff                39 findings, 10 mechanical, 6 advisory

$ rb trace paper.md
trace                6 passage(s) flagged, 1 looked at and left alone

$ rb ask paper.md
ask                  1 blocking, 5 serious, 1 minor

$ rb edit paper.md
edit                 14 edit(s) proposed, -132 words, 4 not proposed
```

Every summary says what was checked rather than how clean the paper is. "3 of 8
entries resolved" is a fact. The same thing as a percentage invites being read
as a grade.

Results land in `.research-better/` next to the draft. Every artifact records
the hash of the draft it came from, so a pass reading stale analysis warns and
the edit pass refuses.

Exit codes: `0` nothing found, `1` findings present, `2` the tool could not do
its job. The last two are kept apart on purpose, because a build failing on a
weak paper and a build failing on a broken tool are different events.

The whole run, including the report, the reviewer questions, and the edit
ledger, is committed under [`examples/`](examples).

### Set a contact address

```
export RESEARCH_BETTER_CONTACT="you@university.edu"
```

Every scholarly source this tool queries is a public API run by a nonprofit or
a university and offered for free. OpenAlex, Crossref, and Unpaywall all run a
faster pool for clients that identify themselves, and setting this puts you in
it. It also means a source operator who sees a problem can email you rather
than block the tool.

Responses are cached under `.research-better/cache/`. `--offline` uses only
what is cached and fails loudly when something is missing, rather than
returning nothing and letting an unverified citation look like a finding about
your paper. `--refresh` fetches again.

### Set a Semantic Scholar key if your bibliography is large

```
export SEMANTIC_SCHOLAR_API_KEY="..."
```

Optional, free, and the one setting that actually changes how long `ground`
takes. Semantic Scholar rate limits an anonymous caller hard: on a 19-entry
bibliography it answered 4 and refused 15. Without a key the tool paces itself
well below the published limit and stops asking a source that has refused
several entries in a row, so a refusing source costs you its answers rather
than your afternoon. Request a key at
<https://www.semanticscholar.org/product/api>.

The key is read from the environment and sent as a header. It is never written
to an artifact, never part of a cache key, and never logged.

## How it works

Ten passes, run in this order because each reads what the one before it
established.

| Pass | What it does |
| --- | --- |
| `ingest` | Parses the draft into sentences, sections, citations, and floats, with a stable id for each |
| `novelty` | Reads the contribution claim off the opening and checks the body against it |
| `voice` | Profiles how you write, so every later change can be held to it |
| `ground` | Resolves each bibliography entry against real databases and checks whether the cited work says what it is cited for |
| `originality` | Compares the draft against the full text of what it cites, and says how many sources it could read |
| `fluff` | Finds text that does not serve the argument, split into deletions and observations |
| `trace` | Reports passages that may read as machine-written, with a cause and a fix for each |
| `ask` | Raises the questions a reviewer will ask, and answers none of them |
| `edit` | Turns the findings into a patch, and writes nothing without `--apply` |
| `report` | One page of what was found and what could not be checked |

## Why the constraints exist

**The evidence gate.** `edit` refuses to start until the novelty, grounding,
fluff, and voice artifacts all exist and all carry the hash of the draft as it
is on disk right now. A model asked nicely to consult the evidence first will
usually do it; a command that will not start without four fresh artifacts will
always do it. Every proposed edit also carries a pointer at the record that
justifies it, and one with no pointer is rejected before the ledger is written.

**The voice lock.** Every change that puts new words on the page is checked
against your own profile: your vocabulary, your sentence lengths, your person,
your hedging rate. A replacement using a word you never wrote is refused. The
loudest tell of a machine edit is a synonym the author never used, and a draft
that says "model" forty times and suddenly says "framework" once reads wrong to
a human before they can say why.

**The word budget.** The assembled result may not be longer than what you
wrote. Growing the paper means text was proposed that you did not write, so
that fails. A reduction target is different: falling short of one is a fact
about the draft and is reported rather than enforced, because the alternative
is inventing a cut to hit a number.

## Formats

| Format | Read | `--apply` writes back |
| --- | --- | --- |
| Markdown | yes | yes |
| LaTeX | yes | yes |
| Word | yes | yes, as tracked changes |
| PDF | yes | no |

### PDF is review only

A PDF is a rendering rather than a source, and the common reason to read one is
that it is the only artifact there is: somebody else's paper, or the submitted
version of your own. Citation verification is the pass that works best on it.
Three limits come with it, and all three are stated rather than worked around.

1. **`--apply` refuses.** Editing a PDF would mean rebuilding a document the
   tool only partly understands, and the result would not be the file you
   compile from. Read the report and change the source.
2. **Artifacts do not carry over between builds.** A span id is a hash of the
   sentence and its section path, and a recompile reflows lines and breaks
   words in different places, so findings recorded against one PDF do not point
   at the same text in the next.
3. **Extraction quality varies, so it is measured rather than assumed.** Two
   column layouts, running headers, footers, page numbers, margin line numbers,
   and words hyphenated across a line break are handled, and tables and
   captions are located and skipped rather than read as sentences. Anything the
   reader was unsure about is printed in the report. A scan carries images
   rather than text, and ingest refuses it and says to run OCR first, because a
   clean report about a paper the tool never read is worse than no report.

## Limitations

Specific rather than modest. Each of these is a thing the tool cannot do, and
each one is reported in the run rather than left for you to discover.

**Claim support is lexical.** There is no embedding model and no judgment step.
A claim supported by its source in quite different words is missed, and a low
overlap never comes back `UNSUPPORTED` unless the full text was actually read.

**Full text is often not retrievable.** On the fixture paper, one of six cited
works had readable full text; the rest were checked against an abstract or not
at all. A claim checked against an abstract comes back `UNCHECKABLE` rather
than `UNSUPPORTED`, because an abstract not mentioning something is no evidence
the paper does not say it.

**Overlap checking is not plagiarism detection.** It covers open-access full
text this tool could fetch, and nothing else. No closed-access paper, no
student repository, no unpublished draft.

**Two rhythm rules ship switched off.** Their thresholds are claims about how
humans write and no corpus has been run to support them, so they report as
unchecked rather than firing on numbers nobody has justified.
`scripts/calibrate_rhythm.py` finishes them and needs twenty or more accepted
open-access papers from your target venues.

**Venue profiles are default only.** IEEE, ACM, Springer, and Elsevier could
not be verified from their published author guidance, so nothing venue-specific
is assumed. Every shipped profile records where it came from and when it was
checked.

**Nothing here resolves your own prior work.** Self-overlap detection works and
has nothing to feed it: the tool does not look up the paper's authors to find
what they published before.

## Two things this tool will not do

1. **It attacks causes, never scores.** It does not call a detection service,
   does not report a detection score, and does not suggest a change whose only
   justification is lowering a detection signal.
2. **It does not give false assurance.** It never prints a number that reads as
   a total plagiarism or AI score. It reports what it could not see alongside
   what it found.

`research-better trace` is where this is most visible. It names the passages
that carry the signals a human reader picks up on and gives each one a cause
and a fix, and every fix has to stand on its own as better writing: add the
number, add the citation, cut the filler. There is no row that says replace
this word with a rarer one. Signals that misfire on non-native English and on
formulaic methods prose can never flag a passage by themselves, and passages
that tripped only those are reported separately as looked at and left alone.

The reasoning, and guidance on disclosing tool assistance to a venue that asks
for it, is in [docs/INTEGRITY.md](docs/INTEGRITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The writing rules there apply to this
repository as well as to the papers it checks, and CI enforces the mechanical
ones: no em dashes, and no phrase from the tool's own filler-opener list.

## License

MIT. See [LICENSE](LICENSE).
