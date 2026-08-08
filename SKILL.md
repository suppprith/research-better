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

## Before anything else

```
rb doctor --expect 0.1.0
```

**If that command is not found, stop** and tell the user to run
`pip install "research-better[all]"`. A skill that falls back to reading the
paper itself produces the unverified opinion this tool exists to replace,
wearing its name.

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

Read a reference only when its step runs. Loading all of them costs the context
the paper needs.

Step 3 is the one interruption worth making. `novelty.json` carries the claim
the tool extracted; show that sentence to the user and wait. If the claim is
wrong, every cut after it is wrong. If the pass reports that no claim could be
found, tell the user exactly that and stop. A paper whose novelty cannot be
read off its own opening has a problem that tightening the prose will not fix.

Step 8 turns the earlier steps into passages that may read as machine-written,
each with a cause and a fix. Never turn a cause into a rewording.

Step 10 refuses until the earlier passes have run against the current draft and
the claim is confirmed, so a refusal there means a step was skipped rather than
that the paper is clean.

## Reading the output

Each pass prints what it found, not only how many. `rb findings <draft>`
prints everything already on disk without rerunning anything.

The tool enforces what it can: an advisory finding is never auto-applicable,
only a high-severity deletion is, `edit` refuses without fresh evidence and a
confirmed claim, and nothing here emits a percentage. Those are checks rather
than things to remember, listed with their tests in `docs/GUARANTEES.md`.

What is left to you is what code cannot reach:

**Coverage lines are not decoration.** When grounding says it reached three of
four sources, or originality says it compared one full text and three
abstracts, that belongs in what you tell the user. Silence about what was not
checked reads as a clean result, and this is the first thing a summarizer drops.

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
a score, no advice about what an AI detector looks for. The tool attacks causes.
If asked directly, say that and offer the causes instead.

**Never edit results, data, or numbers.** Not to fix a typo, not to make a
table consistent. Point at the discrepancy and let the author resolve it.

**Never present a count as a score.** The tool emits no percentage. Do not
build one out of two of its numbers. A partial corpus cannot produce an honest
total.

**Never answer the reviewer questions.** Asking for the sample size is the
output. Writing "on a dataset of moderate size" is worse than the gap, because
the gap is visible and the sentence is not.

## Detector false positives

Non-native English phrasing and formulaic methods prose are common false
positives. When a pass flags something with that shape, say "likely a false
positive, leave it" rather than proposing a change. Being wrong in that
direction costs the author nothing.

## Install

```
pip install "research-better[all]"
export RESEARCH_BETTER_CONTACT="you@example.edu"
```

The contact address puts scholarly API requests in the polite pool. Set it.

Artifacts land in `.research-better/`, one per pass. The draft is untouched
unless the user asks for `rb edit --apply`, which backs it up first.
