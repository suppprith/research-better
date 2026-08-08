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
