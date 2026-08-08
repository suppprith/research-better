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
other tool in this space reaches for a replacement sentence, and that is how a
paper stops sounding like its author.

## Before anything else

```
rb doctor --expect 0.2.0
```

**If that command is not found, stop** and tell the user to run
`pip install "research-better[all]"` and set `RESEARCH_BETTER_CONTACT` to their
email. A skill that falls back to reading the paper itself produces the
unverified opinion this tool exists to replace, wearing its name.

Pass on whatever `doctor` reports: a version warning with its upgrade command,
a missing extra before a draft in that format fails at ingest.

## Order

Run the scripts. Do not reimplement their logic by eye: if `rb fluff` exists,
run it rather than judging fluff yourself. Report what it returns, including
when it returns nothing.

| Step | Command | Read first |
|---|---|---|
| 1 | `rb ingest <draft>` | nothing |
| 2 | `rb novelty <draft>` | `references/novelty-audit.md` |
| 3 | **Confirm the claim with the user.** Stop here until they answer, then rerun step 2 with `--confirm-claim` | |
| 4 | `rb voice <draft>` | nothing |
| 5 | `rb ground <draft>` | `references/grounding-protocol.md` |
| 6 | `rb originality <draft>` | `references/grounding-protocol.md` |
| 7 | `rb fluff <draft>` | nothing, the lexicon is data the script reads |
| 8 | `rb trace <draft>` | `docs/INTEGRITY.md` |
| 9 | `rb ask <draft>` | `references/reviewer-questions.md` |
| 10 | `rb edit <draft>` | `references/voice-preservation.md` |
| 11 | `rb report <draft>` | nothing |
| 12 | **Write the analysis.** | `references/final-analysis.md` |

Read a reference only when its step runs: loading all of them costs the context
the paper needs.

Step 3 is the one interruption worth making. Show the user the claim
`novelty.json` extracted and wait: if it is wrong, every cut after it is wrong.
If no claim was found, tell them that and stop.

Step 8 names passages that may read as machine-written, each with a cause.
Never turn a cause into a rewording.

Step 10 refuses until the earlier passes have run against the current draft and
the claim is confirmed, so a refusal there means a step was skipped rather than
that the paper is clean.

Step 12 is the deliverable and the run is not finished without it. Relaying
eleven passes of output is not an analysis. Every sentence you write there has
to trace back to a record in an artifact, which is the evidence gate applied to
prose, and `references/final-analysis.md` is not optional reading.

## Reading the output

Each pass prints what it found, not only how many, and `rb findings <draft>`
prints everything already on disk without rerunning anything. The tool enforces
what it can: an advisory finding is never auto-applicable,
only a high-severity deletion is, `edit` refuses without fresh evidence and a
confirmed claim, and nothing emits a percentage. Those are checks rather than
things to remember, listed with their tests in `docs/GUARANTEES.md`. What is
left to you is what code cannot reach:

**Coverage lines are not decoration.** When grounding reached three of four
sources, or originality compared one full text and three abstracts, say so.
Silence about what was not checked reads as a clean result, and it is the first
thing a summarizer drops.

**Read the trace audit's `left_alone` list out.** An author told what was
looked at and deliberately not changed can trust the flags that remain.

## Refusals

These are here rather than in a reference file because they must never be
skipped, and because each is a thing you could do that the tool cannot stop.

**Never invent a source.** Every citation you offer comes from a record in
`grounding.json`. If the tool found nothing, say it found nothing.

**Never claim a check that did not run.** If `rb ground` was not run, or ran
offline against a cold cache, say so rather than implying the citations are
verified.

**Never help evade a detector.** No synonym substitution, no rephrasing to move
a score, no advice about what a detector looks for. If asked directly, say the
tool attacks causes and offer those instead.

**Never edit results, data, or numbers.** Not to fix a typo, not to make a
table consistent. Point at the discrepancy and let the author resolve it.

**Never present a count as a score.** The tool emits no percentage. Do not
build one from two of its numbers: a partial corpus has no honest total.

**Never answer the reviewer questions.** Asking for the sample size is the
output. "On a dataset of moderate size" is worse than the gap, because the gap
is visible and the sentence is not.

## Detector false positives

Non-native English phrasing and formulaic methods prose are common false
positives. When a pass flags something with that shape, say "likely a false
positive, leave it" rather than proposing a change. Being wrong that way costs
the author nothing.

## Artifacts

One per pass in `.research-better/`, as JSON and as a page beside it. The draft
is untouched unless the user asks for `rb edit --apply`, which backs it up
first and is undone by `rb revert`.
