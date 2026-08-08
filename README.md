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

Format support is optional so the base install stays small:

```
pip install "research-better[latex]"   # .tex and .bib
pip install "research-better[docx]"    # Word
pip install "research-better[pdf]"     # PDF, review only
pip install "research-better[all]"
```

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

## License

MIT. See [LICENSE](LICENSE).
