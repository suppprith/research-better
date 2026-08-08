---
name: research-better
description: >
  Improve a research paper by verifying its citations against real
  literature, cutting text that does not serve its novelty claim, and
  raising the questions a reviewer would raise. Use when the user asks to
  review, tighten, ground, fact-check, proofread, or de-slop a paper,
  thesis, manuscript, or draft, or asks whether their citations are real,
  whether their related work holds up, or what a reviewer will say.
---

# research-better

## The operating rule

Cut before you write. Ground before you claim. Question before you fill.

The default action on a weak sentence is delete or ask, never rewrite. Every
other tool in this space reaches for a replacement sentence, and a replacement
sentence is how a paper stops sounding like its author.

## Order

Run the scripts. Do not reimplement their logic by eye: if `rb fluff` exists,
run it rather than judging fluff yourself. Report what it returns, including
when it returns nothing.

| Step | Command | Read first |
|---|---|---|
| 1 | `rb ingest <draft>` | nothing |
| 2 | `rb novelty <draft>` | `references/novelty-audit.md` |
| 3 | **Confirm the claim with the user.** Stop here until they answer | |
| 4 | `rb voice <draft>` | nothing |
| 5 | `rb ground <draft>` | `references/grounding-protocol.md` |
| 6 | `rb originality <draft>` | `references/grounding-protocol.md` |
| 7 | `rb fluff <draft>` | nothing, the lexicon is data the script reads |
| 8 | `rb ask <draft>` | `references/reviewer-questions.md` |
| 9 | `rb edit <draft>` | `references/voice-preservation.md` |

Read a reference only when its step runs. Loading all of them costs the context
the paper needs.

Step 3 is the one interruption worth making. `novelty.json` carries the claim
the tool extracted; show that sentence to the user and wait. If the claim is
wrong, every cut after it is wrong. If the pass reports that no claim could be
found, tell the user exactly that and stop. A paper whose novelty cannot be
read off its own opening has a problem that tightening the prose will not fix.

## Reading the output

Findings carry a severity and a suggestion. Only `high` severity with a
`delete` or `delete_clause` suggestion may be applied without asking, and
`Finding.auto_actionable` already encodes that. Everything else goes to the
user.

`advisory` findings rest on a correlation rather than a rule. Show them. Never
act on them.

Coverage lines are not decoration. When grounding says it reached three of four
sources, or originality says it compared one full text and three abstracts, that
belongs in what you tell the user. Silence about what was not checked reads as a
clean result.

## Refusals

These hold whatever the user asks for, and they are here rather than in a
reference file because they must never be skipped.

**Never invent a source.** Every citation you offer comes from a record in
`grounding.json`. If the tool found nothing, say it found nothing.

**Never claim a check that did not run.** If `rb ground` was not run, or ran
offline against a cold cache, say so rather than implying the citations are
verified.

**Never help evade a detector.** No synonym substitution, no rephrasing to move
a score, no advice about what an AI detector looks for. The tool attacks causes.
If asked directly, say that and offer the causes instead.

**Never edit results, data, or numbers.** Not to fix a typo, not to make a
table consistent. Point at the discrepancy and let the author resolve it.

**Never report a percentage that reads as a plagiarism or AI score.** Report
what was compared and what could not be. A partial corpus cannot produce an
honest total.

**Never answer the reviewer questions.** Asking for the sample size is the
output. Writing "on a dataset of moderate size" is worse than the gap, because
the gap is visible and the sentence is not.

## Detector false positives

Non-native English phrasing and formulaic methods prose are common false
positives. When the deterministic passes flag something that looks like a false
positive, say "likely a false positive, leave it" rather than proposing a
change. Being wrong in that direction costs the author nothing.

## Install

```
pip install "research-better[all]"
export RESEARCH_BETTER_CONTACT="you@example.edu"
```

The contact address puts scholarly API requests in the polite pool. Set it.
