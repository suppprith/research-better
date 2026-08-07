# research-better

A tool that improves research papers by checking them, not by rewriting them.

It verifies that cited work says what you claim it says, flags text that does not
serve the paper's novelty claim, checks for unattributed overlap with existing
literature, and raises the questions a reviewer will ask.

It does not generate replacement prose by default. When a sentence is weak, the
default action is to delete it or ask you about it, never to quietly swap in a
sentence you did not write.

## Status

Early. The foundation is landing first: document model, ingest adapters, and the
deterministic analysis passes. See the issue tracker for the build order.

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
