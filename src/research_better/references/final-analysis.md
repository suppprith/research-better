# The final analysis

Loaded at the last step, once every pass has run. This is the deliverable. Ten
passes of output relayed back is not one, and neither is a list of artifact
paths.

Run on a real paper, the skill produced summary lines and a list of files. The
author learned their paper had 28 findings and 21 orphan paragraphs. They did
not learn whether their contribution holds up, which citation is broken, or
what to fix first.

## The one constraint

**The synthesis is a reading of the artifacts. It is not a second analysis.**

Every sentence has to trace back to a record: a citation check, a claim check,
an orphan, a finding, a trace passage, a reviewer question. The moment you add
your own view of whether the paper is any good, you are producing exactly the
unverified judgement this project exists to replace, and doing it under the
tool's name where an author will trust it more than they should.

This is the evidence gate applied to prose instead of to patches. The gate
stops the tool writing before it has researched. This stops it concluding
beyond what it read.

If you want to say something the artifacts do not support, the honest form is a
question, and reviewer questions already have a place to live.

## Structure

Five sections, in this order. The order is the point: an author reads from the
top and should hit the thing that decides their paper first.

**1. The claim, and whether the body supports it.**

Quote the claim as `novelty.json` extracted it. Say which parts or items the
body picks up and which it does not, in the tool's words rather than yours.
First, because the author most needs to see it and because a wrong reading of
the claim invalidates everything under it.

If no claim was found, say that and stop the section there. Do not supply one.

**2. What would get this rejected, ranked.**

Broken citations by key, with what is wrong with each. Claims the source does
not carry, with the source quoted. Blocking reviewer questions. Ranked by what
a reviewer hits first, which is roughly: a citation that does not resolve, a
claim the cited work does not make, a contribution the body does not establish.

A retracted citation goes at the top of this list whatever else is in it.

**3. What to fix, and in what order.**

Grouped by the work involved rather than by which pass found it. An author
fixing citations wants every citation problem together, not one from `ground`
and one from `originality` in different sections. Typical groups: the
bibliography, the claims, the prose, the structure.

Say how many of each rather than listing forty. The detail is in the artifacts
and `rb findings` prints it.

**4. What was not checked.**

Carried through from the report verbatim. Not summarized, not softened, not
moved to the end as a footnote. This is the project's core commitment and it is
the first thing a summarizer drops.

If grounding ran offline, say so. If one of six cited works had retrievable
full text, say one of six. If a pass did not run, name it.

**5. What was looked at and deliberately left alone.**

From the trace audit's `left_alone` list, with the reason each was left. An
author told what was examined and not changed can trust the flags that remain.

## What it must never contain

* **A rewritten sentence.** Not as an example, not as an illustration.
* **A citation that is not in `grounding.json`.**
* **A score, a percentage, or a grade.** Including one you computed from two of
  the tool's counts.
* **An answer to a reviewer question.** Asking for the sample size is the
  output.
* **A verdict on the paper as a whole.** No artifact contains one, so no
  sentence here can trace to one. "This paper is nearly ready" is not a reading
  of anything on disk.
* **A number the artifacts do not contain.** If you find yourself adding two
  counts together, stop.

## Coverage travels with every statement

The caveats are not a section you satisfy in part 4 and then forget. A
statement about claim support inherits the coverage of the check behind it.

Wrong: "Your citations check out."

Right: "Six of eight bibliography entries resolved to real records. Two could
not be found in any of the four sources queried, which is not evidence they are
invented."

Wrong: "No unattributed overlap was found."

Right: "One of the six cited works had retrievable full text. The overlap check
compared against that one and could not see the other five."

## When there is nothing to report

Say what ran and what it found, which was nothing. Do not fill the space.

"The bibliography resolved: all eight entries matched real records across
OpenAlex, Crossref, and Semantic Scholar. Two of eight had retrievable full
text, so the claim check covers those two and could not see the rest."

That is a complete and useful answer. It is also not "your paper is good", and
the difference matters.
