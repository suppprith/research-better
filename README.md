# research-better

A tool that improves research papers by checking them, not by rewriting them.

It verifies that cited work says what you claim it says, flags text that does not
serve the paper's novelty claim, checks for unattributed overlap with existing
literature, and raises the questions a reviewer will ask.

It does not generate replacement prose by default. When a sentence is weak, the
default action is to delete it or ask you about it, never to quietly swap in a
sentence you did not write.

## Status

Early. Ingest, the fluff pass, and voice profiling work. Citation verification,
the novelty audit, reviewer questions, editing, and reporting are not built yet,
and the commands for them say so rather than writing an empty artifact that
would look like a check that found nothing.

## Use

```
research-better run paper.md
```

Or one pass at a time:

```
research-better ingest paper.md    # parse and write the structure
research-better fluff  paper.md    # text that does not serve the argument
research-better voice  paper.md    # how the author writes, for later edits
research-better trace  paper.md    # passages that may read as machine-written
```

Results land in `.research-better/` next to the draft. Every artifact records
the hash of the draft it came from, so a pass reading stale analysis warns and
the edit pass refuses.

Exit codes: `0` nothing found, `1` findings present, `2` the tool could not do
its job. The last two are kept apart on purpose, because a build failing on a
weak paper and a build failing on a broken tool are different events.

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

### Shell completion

Completions for bash, zsh, and fish are in [`completions/`](completions), and
they are generated from the parser rather than maintained by hand:

```
source completions/research-better.bash                  # bash
cp completions/research-better.zsh ~/.zfunc/_research-better    # zsh, with ~/.zfunc on $fpath
cp completions/research-better.fish ~/.config/fish/completions/  # fish
```

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

Either way, install the Python package as well. The skill drives the CLI and
does not analyse anything itself, so a skill without the package is a skill
that cannot run. It checks on first use with `rb doctor` and stops with the
install command rather than reading the paper by eye.

To check an install by hand:

```
rb doctor
```

It prints the version, which formats it can read, which extras are missing with
the command that installs each, and whether a contact address is set.

**What the skill does when you invoke it.** It runs the passes in order:
ingest, novelty, voice, ground, originality, fluff, trace, ask, edit, report.
It stops after the novelty pass to show you the contribution claim it read off
your paper and waits for you to confirm it, because if that claim is wrong
every cut after it is wrong. It reports what the passes returned, including
when they returned nothing, and it does not read the paper and form its own
view.

**What it writes.** Everything lands in `.research-better/` beside the draft:
one JSON artifact per pass, a Markdown page for the report and the reviewer
questions, and a `.diff` for proposed edits. Each artifact records the hash of
the draft it came from, so a stale one is caught rather than trusted. Your
draft is untouched unless you ask for `rb edit --apply`, which takes a backup
first and is undone by `rb revert`.

**What it refuses.** No invented sources. No claimed check that did not run. No
rewriting to evade a detector, and no advice about what a detector looks for.
No edits to your results, data, or numbers. No percentage that reads as a
plagiarism or AI score. No answers to the reviewer questions, because asking
for the sample size is the output and inventing one is worse than the gap.

### As a Python library

```python
from research_better import Paper

paper = Paper.load("draft.tex")
for finding in paper.fluff().mechanical:
    print(finding.rule, finding.matched_text)
```

The deterministic passes need no key, no client, and no network. See
[docs/API.md](docs/API.md) for the public surface and what it promises.

## Formats

| Format   | Read | `--apply` writes back    |
| -------- | ---- | ------------------------ |
| Markdown | yes  | yes                      |
| LaTeX    | yes  | yes                      |
| Word     | yes  | yes, as tracked changes  |
| PDF      | yes  | no                       |

### PDF is review only

A PDF is a rendering rather than a source, and the common reason to read one is
that it is the only artifact there is: somebody else's paper, or the submitted
version of your own. Citation verification is the pass that works best on it.
Three limits come with it, and all three are stated rather than worked around.

1. **`--apply` refuses.** Editing a PDF would mean rebuilding a document the
   tool only partly understands, and the result would not be the file you
   compile from. Read the report and change the source.
2. **Artifacts do not carry over between builds.** A span id is a hash of the
   sentence and its section path, and a recompile reflows lines and breaks words
   in different places, so findings recorded against one PDF do not point at the
   same text in the next.
3. **Extraction quality varies, so it is measured rather than assumed.** Two
   column layouts, running headers, footers, page numbers, margin line numbers,
   and words hyphenated across a line break are handled, and tables and captions
   are located and skipped rather than read as sentences. Anything the reader was
   unsure about is printed in the report. A scan carries images rather than text,
   and ingest refuses it and says to run OCR first, because a clean report about
   a paper the tool never read is worse than no report.

## Two things this tool will not do

1. **It attacks causes, never scores.** It does not call a detection service, does
   not report a detection score, and does not suggest a change whose only
   justification is lowering a detection signal.
2. **It does not give false assurance.** It never prints a number that reads as a
   total plagiarism or AI score. Overlap checking can only compare against open
   access full text it can actually retrieve, so it reports what it could not see
   alongside what it found. It is not a substitute for Turnitin and does not
   claim to be.

`research-better trace` is where this is most visible. It names the passages
that carry the signals a human reader picks up on and gives each one a cause and
a fix, and every fix has to stand on its own as better writing: add the number,
add the citation, cut the filler. There is no row that says replace this word
with a rarer one. Signals that misfire on non-native English and on formulaic
methods prose can never flag a passage by themselves, and passages that tripped
only those are reported in a separate list as looked at and left alone.

The reasoning is written out in [docs/INTEGRITY.md](docs/INTEGRITY.md), so it
can be argued with rather than assumed.

## License

MIT. See [LICENSE](LICENSE).
