# Reviewer questions

These are questions, not corrections. Nothing here has been answered for
you, because answering them is the work and a plausible-sounding filler
sentence would make the paper read as finished when it is not.

No verified profile for venue `default`, so nothing venue-specific
was assumed. Questions that depend on venue policy say so.

## Blocking

### Where in the paper is the stated contribution established?

> Our primary contribution is a formal proof that adaptive retrieval converges under bounded query drift.

**Why a reviewer asks this.** The paper claims a contribution that nothing in the body picks up: bounded, converges, drift, primary, proof, under. A reviewer checks the contribution against the results first, and a gap there is the most common single cause of rejection.

**What resolves it.** Either add the work that establishes it, or narrow the claim to what the paper actually shows. Narrowing is not a retreat, it is the difference between a claim you can defend and one you cannot.

`s-2e40522fb767`

## Serious

### Outperforms what, exactly?

> Additionally, our method significantly outperforms all prior approaches and delivers the best results reported to date.

**Why a reviewer asks this.** A comparison with no named point of comparison cannot be checked or reproduced. A reviewer who cannot tell what you beat has to assume you chose the comparison that flattered the result.

**What resolves it.** Name the systems compared against and cite them, or say which configuration of your own method is the baseline.

`s-9f7ca32ca886`

### What hyperparameters were used?

**Why a reviewer asks this.** The paper never states the hyperparameters. A reader cannot judge whether the result is solid or reproduce it without knowing, and a reviewer will ask rather than guess.

**What resolves it.** State the hyperparameters in the method or in an appendix.

`s-c5d16e73f902`

### How many runs was this averaged over, and how were seeds handled?

**Why a reviewer asks this.** The paper never states the number of runs. A reader cannot judge whether the result is solid or reproduce it without knowing, and a reviewer will ask rather than guess.

**What resolves it.** State the number of runs in the method or in an appendix.

`s-c5d16e73f902`

### What test supports "significantly" here?

> Additionally, our method significantly outperforms all prior approaches and delivers the best results reported to date.

**Why a reviewer asks this.** In a results section that word is read as a claim about statistical significance. With no test, effect size, or interval behind it, a reviewer cannot tell whether it means a measured result or an impression, and will assume the latter.

**What resolves it.** Report the test and its outcome, or the effect size with an interval. If the difference was not tested, delete 'significantly' and state the measured difference instead.

`s-9f7ca32ca886`

### What test supports "substantially" here?

> This is a novel finding that substantially advances the field.

**Why a reviewer asks this.** In a results section that word is read as a claim about statistical significance. With no test, effect size, or interval behind it, a reviewer cannot tell whether it means a measured result or an impression, and will assume the latter.

**What resolves it.** Report the test and its outcome, or the effect size with an interval. If the difference was not tested, delete 'substantially' and state the measured difference instead.

`s-52c74f7fdc9e`

## Minor

### Which part of the method produces the gain?

**Why a reviewer asks this.** A method with several components and no per-component evidence leaves a reviewer unable to tell what the contribution is. Whether this is required depends on the venue, and no verified profile was available for yours.

**What resolves it.** Report the result with each component removed in turn, or state plainly that the components were not separated and why.

`s-c5d16e73f902`