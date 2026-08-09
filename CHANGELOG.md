# Changelog

Every release has a section here before it can be published, enforced by
`scripts/check_release.py` in the release workflow. A release nobody can read
the changes of is how a breaking change reaches people with no warning.

Versions follow semantic versioning over the public API listed in
[docs/API.md](docs/API.md). Anything reached by importing a submodule is
internal and can move in any release.

## Unreleased

Nothing yet.

## 0.3.0

### Added

- **`rb check-analysis <draft> <analysis>`**, which grades prose written about
  a paper against the artifacts it claims to be reading. Pass `-` to read the
  analysis from stdin.

  0.2.0 gave the skill a step that writes the final analysis and a reference
  file saying what it may and may not contain. A reference file is a
  preference, and this project's own sentence about those is in `edit/gate.py`:
  a prompt is a preference and a check is a guarantee. This is the check, and
  it is the evidence gate pointed one layer up: the gate refuses to write
  before the research is on disk, and this refuses a sentence that goes beyond
  what the research says.

  It refuses a citation the grounding pass never saw, a percentage, a verdict
  on the paper as a whole, a coverage caveat that was dropped, and a number no
  artifact and no part of the paper contains. Exit 1 on a violation, so it
  works in a pipeline.

  It also names the two rules it cannot check, because both need to understand
  a sentence rather than match one: whether the analysis rewrote the author's
  prose, and whether it answered a reviewer question instead of relaying it. A
  checker that reports nothing wrong without saying what it never examined
  would be making the false-assurance move this tool refuses everywhere else.

  No model call. A grader needing a model cannot run in CI, cannot run offline,
  and cannot be argued with. Every rule is one two people can disagree about by
  reading it.

- Step 13 of the skill runs it on what step 12 wrote.

### Changed

- Artifacts written by 0.2.0 are not read by 0.3.0. No payload shape moved this
  time, but the evidence gate treats any minor bump as a break before 1.0 and
  that rule is deliberate. Rerun the passes.

## 0.2.0

Everything here came from running 0.1.0 on a real IEEEtran paper for the first
time instead of on the fixture. 825 tests passed and the fixture is Markdown
with no front matter and a one-sentence contribution claim, so an entire class
of failure was structurally invisible to it. Test on real papers before
believing a green suite.

### Fixed, and one of them was dangerous

- **`edit` proposed destructive cuts and every gate passed them.** On a real
  paper it offered to delete three author affiliations, the keywords block, and
  a whole Results paragraph reporting measurements. `Finding.auto_actionable`
  treats a deletion as the safe suggestion, on the reasoning that a deletion
  cannot introduce a word the author never wrote. That is sound and incomplete:
  a deletion cannot invent text and it can absolutely destroy it. A new check
  asks what the cut lands on, refusing a cut into front matter in any format,
  and a whole-paragraph cut that sits under no heading, reports a measurement,
  or is in a findings section. Refusals are recorded in the ledger's `dropped`
  list with the rule named.
- **LaTeX front matter was read as prose.** Every template a real paper is
  written in declares `\title` and `\author` after `\begin{document}`, not in
  the preamble where the adapter was looking, so affiliations and ORCID lines
  became paragraphs no body sentence supported and were classified as orphans.
  Ten of twenty-one orphans on that paper were front matter. Front matter is
  now found structurally rather than by a list of macro names, recorded as a
  `FRONT_MATTER` float rather than dropped, and protected from patching. The
  abstract is respected in both directions, including `acmart`, which puts it
  before `\maketitle`.
- **An enumerated contributions list always reported itself as unsupported.**
  The reported unsupported parts were `ii`, `iii`, `iv`, `vi`, `five`, and
  `contributions`, none of which a body sentence can ever match, so the claim
  could never come back supported and it produced the one blocking reviewer
  question on the paper. Enumerators and structural vocabulary come out before
  the claim is tokenized, and an enumerated claim is now checked item by item.
- **`rather` in `rather than` was flagged as an empty intensifier.** 21 of 28
  fluff findings on that paper were this one term. Deleting it produces "we
  place the anchor greedily than geometrically", which is broken English the
  author did not write. The term is dropped, and a new check refuses any single
  word the tool deletes on its own that opens a multi-word phrase the lexicon
  itself lists.
- **A rate-limited source was charged the pacing cost for every retry.** The
  token bucket was acquired inside the retry loop, so four 429s cost four full
  waits. Nineteen entries against a refusing source: 375s before, 15s now.
- A comment discussing `\begin{document}` moved the body start into a note to a
  co-author. Structural searches skip comments now.
- A `\label{}` sharing a line with the heading it names survived as a paragraph.
- `Paper.run(offline=True)` passed offline to the passes but not to the client
  it built, so an offline run fetched anyway.

### Added

- **Passes print what they found, not only how many.** The entire visible
  output of an analysis used to be a few summary lines, with every finding in
  JSON that nobody opened. Findings now print by default, with the rules behind
  each count beside it, truncated with the count withheld and the artifact
  named. `--quiet` silences it for CI, and `rb run` prints summaries and causes
  only and still ends with the report.
- **`rb findings <draft>`** prints what the passes already found, without
  running anything. Every pass now also writes a readable page beside its JSON.
- **`Paper.run()`** walks the same order the CLI walks, writes the artifacts,
  and returns the report. Without it a library caller had to know the order,
  the gates, and the confirmation stop from a document they were never shown.
- **`Paper.edit()`** puts the library behind the same evidence gate as the CLI,
  so an unconfirmed claim refuses there too. It proposes and never writes.
- **`docs/GUARANTEES.md`**: what holds however you drive this, what holds only
  through the skill, and what is an obligation on you. Every guarantee names
  the test that fails when it is broken. `docs/skill-rule-audit.md` is the
  working behind it.
- **A final analysis step in the skill**, backed by
  `references/final-analysis.md`. The skill used to run the passes and stop.
  Every sentence of the synthesis has to trace back to a record in an artifact,
  which is the evidence gate applied to prose.
- **`SEMANTIC_SCHOLAR_API_KEY`** is read and sent as a header. It is free, it
  is the real remedy for a large bibliography, and nothing mentioned it. The
  key is never written to an artifact and never part of a cache key.
- A source that refuses several entries in a row is stopped being asked and
  reported in `sources_unavailable`, rather than costing the rest of the run.

### Changed

- `NoveltyReport.unsupported_claim_parts` holds parts rather than words: item
  text for an enumerated claim, content words for a one-sentence claim that has
  no smaller parts. `NoveltyReport.claim_items` is new.
- Artifacts written by 0.1.0 are not read by 0.2.0. The payload shapes moved,
  and the evidence gate treats a minor bump as a break before 1.0 on purpose.
  Rerun the passes.

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
