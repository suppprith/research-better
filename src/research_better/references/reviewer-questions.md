# Reviewer questions

Read before running the reviewer pass. Loaded by that pass only.

## The rule

Ask. Do not answer. Answering is where the research happens, and a tool that
fills the gap with plausible text produces a paper that reads as finished and
is not.

If the sample size is missing, ask for the sample size. Do not write "on a
dataset of moderate size". That sentence is worse than the gap, because the gap
is visible and the sentence is not.

Every question carries three parts. The span it refers to, why a reviewer would
ask, and what would resolve it. The third is what makes the output actionable
rather than discouraging. A list of problems with no route out is just a way of
telling somebody their paper is bad.

## Severity

By consequence, not by irritation.

| Level | Means |
|---|---|
| `blocking` | Would likely cause rejection |
| `serious` | Would likely draw a major revision |
| `minor` | Would draw a comment |

## The bank

### unsupported_claim, blocking

The stated contribution is not established anywhere in the body.

*Why a reviewer asks.* They check the contribution against the results first. A
gap there is the most common single cause of rejection.

*What resolves it.* Add the work, or narrow the claim. Narrowing is not a
retreat.

### missing_baseline, serious

A comparison with nothing named on the other side.

> Our method outperforms all prior approaches.

*Why.* A comparison that cannot be checked has to be assumed flattering.

*Resolves.* Name the systems and cite them, or name which configuration of your
own method is the baseline.

### unquantified_significance, serious

"Significantly" or "substantially" with no test, effect size, or interval.

*Why.* In a results section that word is read as a claim about statistical
significance. Without one behind it, a reviewer assumes an impression.

*Resolves.* Report the test, or the effect size with an interval. If nothing
was tested, delete the word and state the measured difference.

### undisclosed_method_detail, serious

Sample size, hyperparameters, hardware, data split, or number of runs missing.

*Why.* The result cannot be judged or reproduced without them.

*Resolves.* State them, in the method or an appendix.

### generalization_overreach, serious

A conclusion wider than any single evaluation can establish.

*Why.* Easiest thing to attack. One counterexample refutes it.

*Resolves.* Narrow to what was tested, or run what would support the wider
claim.

### missing_ablation, venue-dependent

A multi-component method with no per-component evidence.

*Why.* A reviewer cannot tell which part is the contribution.

*Resolves.* Report the result with each component removed, or say plainly that
they were not separated and why.

**Weight this by venue.** With no verified venue profile, ask it as `minor` and
say the requirement depends on the venue. Never assert a venue requires
something the tool has not checked.

### unstated_assumption, serious

A step that holds only under a condition the paper never states.

*Resolves.* State the condition, or show the step holds without it.

### threat_to_validity, serious

No limitations addressed anywhere.

*Why.* Reads as overconfidence or as an author who has not looked. Both invite
a harder search for the flaw.

*Resolves.* Name the conditions under which the result would not hold. Stating
them is stronger than hoping nobody notices.

### reproducibility, minor

Nothing said about code, data, or environment availability.

*Resolves.* Say where they are, or say why they cannot be released.

## What a satisfying resolution looks like

Not "the authors added a sentence". A resolution closes the question a reviewer
would have asked, and the test is whether the same reviewer would ask again
after reading the revision.
