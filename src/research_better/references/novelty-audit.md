# Novelty audit

Read before running the novelty pass. Loaded by that pass only.

## Extracting the claim

Look in three places, in this order: an explicit contributions list, the last
paragraph of the introduction, the abstract. Take one sentence. If several
qualify, take the most specific.

A claim says what is new. A method sentence says what was done. They read
alike and are not the same.

| Sentence | Claim? |
|---|---|
| Our primary contribution is a convergence proof for adaptive expansion. | Yes |
| We show that sparse retrieval matches dense retrieval at equal cost. | Yes |
| We use BM25 with k1 = 0.9. | No, that is method |
| Retrieval quality has plateaued since 2021. | No, that is background |
| We evaluate on three benchmarks. | No, that is method |

**Stop if there is no claim.** Do not assemble one from the abstract's general
sense. A paper whose novelty cannot be read off its own opening has a problem
that tightening the prose will not fix, and saying so is the useful output. The
pass raises `NoClaimFoundError` and the correct response is to show the author
that message, not to work around it.

**Confirm before cutting.** The claim goes back to the author before anything
downstream acts on it. If the claim is wrong every cut that follows is wrong.
This is the only interruption in the tool worth making.

## Roles

One per sentence. Assign the most specific that fits.

| Role | Recognized by | Example |
|---|---|---|
| `contribution` | States what is new | Our contribution is a convergence proof. |
| `background` | Carries a citation, or contextualizes | Dense encoders were introduced in 2020 [3]. |
| `method` | Describes what was done | The corpus is indexed with BM25. |
| `evidence` | Reports a measurement | Recall at ten rose from 0.62 to 0.71. |
| `interpretation` | Reads meaning into evidence | This suggests expansion helps short queries. |
| `limitation` | Names what does not hold | We did not evaluate on non-English collections. |
| `orphan` | None of the above | Peer review has been studied for many years. |

## What is never an orphan

The naive reading of "cut what does not serve the novelty" deletes the related
work and the limitations section. Both are doing their jobs.

* **A cited sentence is background, wherever it sits.** Background that
  contextualizes rather than directly supports the novelty is not padding.
* **A limitations section is never cut.** Reviewers require one. A paper that
  states its limits is stronger than one that hopes nobody looks.
* **A bare number is not evidence.** "Databases have existed since the 1960s"
  contains a digit and reports nothing about this paper.

## Orphanhood is a property of a paragraph

A paragraph makes one move in the argument. A short sentence inside a paragraph
that reports results is part of reporting those results.

Judging sentences alone flags this:

> Recall at ten rises from 0.62 to 0.71 when expansion is enabled, a gain of
> nine points. The cost is one third that of the dense baseline. We did not
> observe the same gain on the long-tail split. **Expansion helps short
> queries.**

The bold sentence carries no number, no citation, and no method. Alone it looks
like padding. In place it is the conclusion of the measurements above it, and
cutting it removes the finding.

So a paragraph is an orphan only when every sentence in it is, and the whole
paragraph is offered for cutting together.

## Reporting an unsupported claim

Say which parts of the claim nothing in the body picks up, and offer both exits:

> Nothing in the body establishes: proof, converges, bounded, drift. Either add
> the work that supports them, or narrow the claim to what the paper shows.
> Narrowing is not a retreat. It is the difference between a claim you can
> defend and one you cannot.
