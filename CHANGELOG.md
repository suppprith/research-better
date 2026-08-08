# Changelog

Every release has a section here before it can be published, enforced by
`scripts/check_release.py` in the release workflow. A release nobody can read
the changes of is how a breaking change reaches people with no warning.

Versions follow semantic versioning over the public API listed in
[docs/API.md](docs/API.md). Anything reached by importing a submodule is
internal and can move in any release.

## Unreleased

Nothing yet.

## 0.1.0

First release. Everything below is new.

### Reading a paper

- Markdown, LaTeX, Word, and PDF ingest. LaTeX, Word, and PDF live behind the
  `[latex]`, `[docx]`, and `[pdf]` extras so the base install stays small.
- PDF is review only. `--apply` refuses, span ids do not survive a recompile,
  and a scan is refused with a pointer to OCR rather than analysed.
- Span ids are a hash of the sentence and its section path, so a finding
  recorded today still points at the same sentence after a paragraph is
  inserted above it.

### Checking it

- `ground` verifies every bibliography entry against OpenAlex, Crossref,
  Semantic Scholar, and arXiv, and checks whether each cited work says what it
  is cited for. Absence of a record is never reported as fabrication.
- `originality` reports unattributed overlap against retrievable open-access
  full text, and says how many sources it could actually compare.
- `fluff` finds text that does not serve the argument, split into deletions
  that can be applied and advisory observations that cannot.
- `novelty` checks that the body supports the contribution the paper claims.
- `ask` raises the questions a reviewer will ask, and answers none of them.
- `trace` reports passages that may read as machine-written, with a cause and a
  fix for each. See [docs/INTEGRITY.md](docs/INTEGRITY.md).
- `voice` profiles how the author writes, which every proposed edit is held to.

### Changing it

- `edit` turns findings into a patch and writes nothing without `--apply`. It
  refuses to run at all until the analysis on disk matches the current draft.
- Word drafts are written back as tracked changes.
- `revert` restores the backup taken before any write.

### Reporting

- `report` prints one page, in Markdown or as a self-contained HTML file, and
  names every check that did not run. `--check` turns it into a CI verdict
  against configured thresholds.
- No output anywhere is a percentage that could be read as a plagiarism or an
  AI score.

### Shipping

- `research-better` and `rb` on the command line, with completions for bash,
  zsh, and fish.
- `Paper` as a public Python API, typed and covered by semantic versioning.
- `SKILL.md` for use as a Claude Skill.
