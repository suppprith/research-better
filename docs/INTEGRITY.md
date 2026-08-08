# Integrity

Why this tool attacks causes and never scores, written down so the reasoning
can be argued with rather than assumed.

## The goal people actually have

Somebody arrives wanting zero AI traces and zero plagiarism in their paper.
That is a real goal and it is worth taking seriously. What it means, though,
depends entirely on which of two things is being asked for:

1. A paper whose sentences the author can defend, whose claims are supported by
   the sources cited for them, and whose prose says something.
2. A paper that a detector scores as human.

The first is the goal. The second is a proxy for it that stopped tracking it.
This tool builds for the first and refuses the second, and everything below is
why.

## Optimizing against a detector degrades the writing

A detector scores text on surface statistics: word rarity, how evenly the
sentence lengths fall, how predictable the next word is. Lowering that score
means changing those statistics. It does not mean adding a measurement, finding
the right citation, or cutting a paragraph that says nothing.

So a tool that optimizes the score reaches for the only levers available to it:
swap common words for rarer ones, break up an even rhythm, insert a subordinate
clause. Every one of those makes the paper harder to read and none of them
makes it more true. A methods section written cleanly as a list of steps is
uniform because the method is a list of steps, and roughening it up costs the
reader and buys the author nothing.

Worse, the change is invisible to the author as a loss. The score moved, so it
looks like progress.

## The arms race is unwinnable, and losing it is not the point

Detectors change weekly, disagree with each other, and are retrained on
whatever the last generation of evasion tools produced. A paper tuned against
today's detector is untuned by definition against next month's.

But the arms race is a distraction from the real objection, which holds even if
some detector were permanently perfect: a change whose only justification is
lowering a detection signal is a change made to alter how the paper is
classified rather than what it says. A tool that makes those changes is a
laundering tool. That is true regardless of what its user intended, and it is
true when the underlying text is entirely the author's own work.

So the rule this tool follows is not "do not evade detectors well". It is: if
the only reason to make a change is to look less machine-written, the change is
not offered.

## What is offered instead

The audit (`research-better trace`) reports passages that carry the signals a
human reader picks up on, and for each one it names the cause and a fix. Every
fix has to stand on its own as better writing:

| Signal | Fix |
| --- | --- |
| A claim the cited source does not carry | Cite the work that establishes it, weaken the sentence to what the source says, or cut it |
| A confident assertion with no citation and no number | Add the measurement, add the citation, or cut the sentence |
| Filler phrases | Cut them; the sentence survives |
| Stacked hedges | Keep the one hedge you mean, or state the actual limit |
| A section whose voice departs from the paper's | Read it beside a section you know you wrote, and resolve where it came from |

Notice what is missing: there is no row that says "replace this word with a
rarer synonym" or "vary the sentence lengths". Those are what a humanizer does
and this tool does not do them.

## False positives are treated as first-class

Detectors have a documented false-positive problem, and it falls hardest on:

* Writers whose first language is not English.
* Formulaic technical and methods prose, which is supposed to be uniform.
* Standard academic register in general.

An author told to mangle a correctly written methods section because a detector
might dislike its rhythm has been made worse off than the flag would have made
them. So the audit is built so that a texture signal can never flag a passage
on its own. Rhythm and shape only ever join a flag that already has a
content-level cause behind it. Where texture fired and nothing else did, the
passage is reported in a separate list as looked at and left alone, with the
reason it was left.

That list is part of the output, not a footnote to it.

## Every signal is measured against the paper itself

There is no corpus and no reference population behind any threshold in the
audit. A paragraph is uniform relative to the other paragraphs of the same
paper; a section deviates relative to the rest of the same paper.

This is partly practical: a threshold calibrated on a corpus of accepted papers
would encode what that corpus's authors write like, and would be wrong for
everybody else. It is mostly about who gets hurt. Comparing a paper with itself
cannot penalize somebody for writing English differently from the corpus.

## No score, anywhere

No output of this tool is a percentage, a likelihood, or an index, for the
audit or for overlap checking. Two reasons, and the second is the load-bearing
one.

A number attached to a paper gets read as a grade for its author, whatever
label sits beside it. And a number is a thing to optimize: give somebody a
figure that goes down when they change a sentence, and they will start writing
towards the figure instead of towards the paper. Counts and named causes cannot
be gamed the same way, because moving them means actually fixing something.

The same rule is why overlap checking reports how many sources could be
compared and how many could not. Overlap can only be checked against
open-access full text that is actually retrievable, so a clean result is a
statement about what was reachable rather than about the paper. Presenting it
as a similarity score would be false assurance, and this tool is not a
substitute for Turnitin and does not claim to be.

## No detection service is ever called

Not GPTZero, not Turnitin, not Originality.ai, not any other. Nothing in this
package sends a draft to a classifier, and a test asserts the package names
none of them. Sending an unpublished paper to a third-party scoring service is
its own harm, separately from what would be done with the answer.

## The other four refusals

These are properties of the passes rather than instructions to a model, so they
hold however the tool is driven: from the command line, through the Python API,
or through the skill.

**No fabricated citations.** Every reference the tool offers comes from a record
it actually resolved. When a source cannot be found, the verdict is
`NOT_FOUND` and it says which databases were queried, because absence of a
record is not evidence of fabrication. Books and theses are indexed unevenly,
and a `NOT_FOUND` on one is flagged as likely unindexed rather than left to
imply something it cannot support.

**No claimed check that did not run.** A pass with nothing behind it refuses
rather than writing an empty artifact, because an empty `grounding.json` reads
exactly like a grounding check that found nothing wrong. The report names every
pass that did not run, every source that could not be reached, and every rule
that is switched off. A run made with `--offline` records that in each artifact
it produced, so a citation checked against a cache is never presented as one
checked against the live literature.

**No edits to results, data, or numbers.** Not to fix an apparent typo, not to
make a table agree with the prose. Where the tool sees a discrepancy it points
at it and stops. A number in a paper is a claim about what happened in an
experiment, and only the people who ran the experiment know which side of a
discrepancy is right.

**No answers to the reviewer questions.** Asking for the sample size is the
output. Writing "on a dataset of moderate size" would make the paper read as
finished when it is not, and the gap is visible in a way the sentence is not.

## Disclosing that you used it

Venue policies on tool assistance differ, they change, and some of them require
a declaration. Check the policy of the venue you are submitting to. This tool
does not know it and will not guess at it for you.

What is worth knowing when you read that policy: on a default run this tool
writes no prose into your paper. It reports, and every change it proposes is a
deletion of your own words or a request that you supply something. `rb edit`
proposes a patch and writes nothing without `--apply`. So the assistance is
closer to a checker than to a writing tool, and the honest description of it is
along these lines:

> The manuscript was checked with research-better, an open-source tool that
> verifies citations against bibliographic databases, flags unsupported claims,
> and identifies text for deletion. No text in this manuscript was generated by
> it.

That last sentence is true of a default run and it stops being true if you use
the tool to write. Do not paste it in without knowing which you did.

If a policy requires disclosing a tool's use and you would rather not disclose
it, the answer is to not use the tool on that submission. This is not the kind
of assistance that becomes undetectable by being undisclosed, and nothing here
is designed to make it so.
