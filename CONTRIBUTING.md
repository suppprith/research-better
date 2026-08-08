# Contributing

## Writing rules

These apply to every word that ships: code comments, docstrings, CLI output,
report text, commit messages, and docs.

* **No em dashes.** Use a comma, a full stop, or a colon. A sentence that needs an
  em dash usually needs to be two sentences.
* **No filler openers.** Cut "It is important to note that", "In today's
  landscape", "Let's dive in", "Notably", "Furthermore" used as a throat clear.
  Start with the claim.
* **No emoji in headings.** No decorative emoji anywhere in docs or output.
* **No hedged padding.** "This may potentially help improve" is one word of
  content wrapped in four of insulation. Say what it does.
* **Say the number or say you do not have it.** Never present an estimate with
  the confidence of a measurement.

The tool's own reports are held to this standard, because a tool that flags
fluff while emitting fluff is not credible. `ruff` and the docs lint in CI check
the mechanical parts of this. The rest is review.

## Product boundaries

Two rules constrain what a change is allowed to do. A pull request that crosses
either one will be closed regardless of how well it is written.

1. **Attack causes, never scores.** No calls to AI detection or plagiarism
   scoring services. No reported detection score. No change whose only
   justification is that it lowers a detection signal. Synonym substitution to
   evade detectors is out of scope permanently.
2. **No false assurance.** Never emit a percentage that a user could read as a
   total plagiarism or AI score. Any coverage claim must be paired with what
   could not be checked, including how many sources were retrievable and how
   many were not.

A related consequence: detector false positives are treated as first-class. Non
native English phrasing and formulaic methods prose are common false positives.
When the tool sees one, the correct output is "likely a false positive, leave
it", not a suggested change.

## Development

```
python -m venv .venv
.venv/bin/pip install -e ".[all,dev]"
```

Then:

```
ruff check .
ruff format --check .
mypy
pytest
```

### Golden files

Every pass is tested against `tests/fixtures/bad-paper.md`, a short paper with
defects planted on purpose. Its output is stored in `tests/golden/` and compared
field by field, so a failure names the paths that changed rather than dumping
two structures at you.

Regenerate deliberately:

```
pytest --update-golden
```

Then read the diff and commit it. Never regenerate to turn a red test green.
The whole point is that somebody looks at what changed and agrees with it.

One paragraph of the fixture, in Results, must produce zero findings from every
pass. A tool that flags everything is useless, so that paragraph is what proves
the passes discriminate rather than fire. If a change makes it produce a
finding, the change is wrong, however much it improved elsewhere.

### Thresholds

A number in `references/rhythm-thresholds.toml` has to be traceable to one of
two things, and the `source` field says which:

* A corpus statistic, produced by `scripts/calibrate_rhythm.py` over accepted
  open-access papers. The source records the percentile, the corpus, and the
  date.
* A structural definition. "Two or more is a repetition" is a definition.
  "Below 4.2 words of standard deviation is machine-like" is a claim about how
  humans write, and needs a corpus.

A rule with neither ships disabled, and the loader refuses to enable a rule
with an empty source. This is not bureaucracy. A threshold picked because it
looked about right flags whatever its author happened to dislike, and nobody
can argue with it.

### Network tests

Tests that hit a live external API are marked `@pytest.mark.network` and are
excluded from the default run. CI runs against recorded fixtures so the build
does not break when someone else's API is slow. A weekly scheduled job runs the
live suite, which is what catches an upstream API changing its response shape.

## Commits

One commit per logical change. The message describes the change itself. Do not
reference issue tracker IDs in commit messages.
