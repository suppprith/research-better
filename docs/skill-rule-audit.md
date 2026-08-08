# Audit: every rule in SKILL.md, and where it belongs

Committed rather than only acted on, because the value of the exercise is the
classification and the classification is what goes stale. A rule added to
`SKILL.md` without a row here is a rule nobody has decided about.

`docs/GUARANTEES.md` is the reader-facing version: what holds however you drive
this, what holds only through the skill, and what is an obligation on you. This
file is the working: rule by rule, where it lived, where it should live, and
what was done.

Columns: **Was** is where the rule lived before this audit. **Belongs** is the
category it is really in. **Now** is what happened.

## Properties of the tool

| Rule | Was | Belongs | Now |
|---|---|---|---|
| Advisory findings can never be auto-applied | code + skill | code | unchanged, already a check |
| Only high-severity deletions are auto-applicable | code + skill | code | unchanged, already a check |
| `edit` refuses without four fresh artifacts | code + skill | code | unchanged, `Pass.preflight` |
| `edit` refuses on an unconfirmed claim | code + skill | code | unchanged for the CLI, **added to the library** as `Paper.edit()` behind the same gate |
| A stale artifact is detected rather than trusted | code | code | unchanged |
| A pass with nothing behind it refuses rather than writing an empty artifact | code | code | unchanged |
| Never invent a source | code, structurally | code | unchanged, nothing generates one |
| Never report a percentage that reads as a score | code | code | unchanged, tested in three places |
| Never help evade a detector | code, structurally | code | unchanged, no detection service is reachable |
| The pass order | skill only | code | **`Paper.run()` added**, walking `RUN_ORDER`, the same list the CLI walks |
| A cut may not land on front matter or destroy a findings paragraph | nowhere | code | **added** as `edit.scope`, from SUP-517 |
| Findings are shown rather than only counted | skill only | code | **moved**, from SUP-522. The skill said "report what it returns"; the CLI now prints it |

## Instructions to a model

These stay in `SKILL.md`. Each one is about talking to a person, and there is
nothing for a check to check.

| Rule | Why it cannot be code |
|---|---|
| Show the claim and wait for the user | The tool can refuse to act on an unconfirmed claim, and does. It cannot make anyone read a sentence |
| Read a reference file at the step that needs it | Context budgeting inside the model, invisible from here |
| Say "likely a false positive, leave it" | A phrasing choice in a conversation |
| Write the final analysis rather than relaying output | The synthesis is prose. See `references/final-analysis.md` |
| Never answer a reviewer question | Nothing here generates prose, so today it is structural. The skill layer is the one place that could, so it is stated there |
| Pass on what `doctor` reports | The CLI prints it. Whether it reaches the user is the model's |

## One thing deliberately not moved

**`rb report` does not print instructions aimed at whatever model is reading
it.** The argument for it was real: the synthesis step only fires when the
skill is loaded, and an agent driving the bare CLI never sees it, so a closing
line in the report saying "now write the analysis" would reach that agent.

Decided against, for two reasons.

The bare-CLI path already got its fix. Passes print their findings now rather
than counts, so an agent driving `rb` sees what is wrong with the paper whether
or not it was told to look. That was the actual complaint, and output design
fixed it.

And a tool that writes prompts into its own stdout is putting instructions in a
data channel. Today it would be one helpful sentence to a cooperating agent.
The pattern it establishes is that this tool's output is a place to address
models, and nothing about that pattern stays one sentence long. The skill file
is the honest home for an instruction to a model, and it stays there.

## Obligations, which are neither

Written into `docs/GUARANTEES.md` rather than left implied. You cannot make a
library caller show coverage to their end user, read the left-alone list out, or
refrain from dividing two counts and calling it a score. You can put the data on
the object, refuse to return a bare verdict without it, and say plainly that the
rest is theirs.

## What this audit changed

* `Paper.run()` and `Paper.edit()` exist, so ordering and the confirmation stop
  are guarantees for a library caller rather than a document they never read.
* `docs/GUARANTEES.md` exists, and every guarantee in it names the test that
  fails when it is broken.
* `SKILL.md` keeps only instructions to a model, which also buys back room in a
  file that is at its enforced word budget.
* `docs/API.md` points at the ordered run rather than sending people to ten
  individual methods with no mention that order matters.
