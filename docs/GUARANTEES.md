# What holds, and how you are relying on it

This tool ships three ways and they are all first-class: a Claude Skill, a CLI,
and a Python library. `SKILL.md` loads for one of them. So anything in that file
which is really a rule about how the tool behaves is a rule a library user and
a bare CLI user never get.

The project already has the sentence that decides this, in `edit/gate.py`:

> a prompt is a preference and a check is a guarantee

That was written about the evidence gate. It applies to the whole file. Every
rule is one of two things, and mixing them with no marking let the first kind
quietly live as the second:

* **A property of the tool.** It should hold however the tool is driven, so it
  belongs in code.
* **An instruction to a model.** How to phrase a finding, what to read before
  which step, when to interrupt and wait. It only means anything to a model and
  belongs exactly where it is.

Three levels below, and the distinction between them is the point of the
document. A **guarantee** is enforced by code and something fails when it is
broken; every one names the test that does the failing. A **skill rule** holds
only when the skill is loaded. An **obligation** is on you, because nothing in
a library can reach into your interface and make you do it.

No rule is listed as a guarantee unless a test fails when it is removed. If you
want a rule moved up a level, the work is a check and a test, not a stronger
sentence here.

## Guarantees

These hold whether you use the skill, the CLI, or the library.

| Guarantee | Enforced by | Test |
|---|---|---|
| An advisory finding can never be auto-applied, whatever its severity | `Finding.auto_actionable` | `test_fluff_structural.py::test_an_advisory_finding_stays_advisory_even_at_high_severity` |
| Only a high-severity deletion is auto-applicable. Anything needing a word choice goes to a person | `Finding.auto_actionable` | `test_fluff_structural.py::test_no_structural_finding_can_be_auto_applied` |
| `edit` refuses without four fresh artifacts | `edit.gate.gather`, run as `Pass.preflight` | `test_edit_gate.py::test_deleting_a_required_artifact_names_the_command_that_rebuilds_it` |
| `edit` refuses while the contribution claim is unconfirmed | `edit.gate.gather` | `test_edit_gate.py::test_an_unconfirmed_claim_stops_the_gate` |
| A stale artifact is detected by hash rather than trusted | `Artifact.is_stale` | `test_edit_gate.py::test_one_changed_character_makes_the_gate_fail_as_stale` |
| Every proposed edit names the record that justifies it, or is dropped | `EvidenceBundle.validate` | `test_edit_ledger.py::test_a_row_whose_evidence_names_nothing_never_reaches_the_ledger` |
| A pass with nothing behind it refuses rather than writing an empty artifact | `cli._run_one` | `test_cli.py::test_an_unbuilt_pass_refuses_rather_than_writing_an_empty_artifact` |
| No code path can invent a source, because none generates one | no generator exists | `test_edit_gate.py::test_the_voice_profile_justifies_nothing` |
| No detection service is reachable from this package | no such adapter or source | `test_trace.py::test_no_detection_service_is_reachable_from_this_package` |
| The trace audit emits no number that reads as a score | `trace.TraceReport` | `test_trace.py::test_nothing_in_the_payload_is_a_score` |
| No report prints a percentage that reads as a plagiarism or AI score | `report`, `originality` | `test_report.py::test_the_page_carries_no_percentage` |
| A patch never touches a range the format cannot survive | `Document.assert_patchable` | `test_ingest_latex.py::test_front_matter_is_protected_from_patching` |
| A deletion is refused when its target is front matter, a whole paragraph under no heading, a paragraph reporting a measurement, or a paragraph in a findings section | `edit.scope.check` | `test_edit_scope.py` |
| The passes run in an order, and the library runs them in the same one | `passes.RUN_ORDER`, `Paper.run` | `test_api.py::test_run_walks_the_same_order_the_cli_does` |
| Findings are shown, not only counted | `cli._emit`, `present` | `test_cli.py::test_a_single_pass_prints_findings_a_reader_can_act_on` |

### The two that moved for this document

**The pass order.** `RUN_ORDER` existed and only the CLI honoured it. The
library had no equivalent at all: a caller got ten individual methods and had
to know the order, the gates, and the confirmation stop themselves, from a
document they were never shown. `Paper.run()` closes that, and it walks
`RUN_ORDER` rather than a second list, so the two cannot drift.

Calling individual `Paper` methods in any order is still fine and is not a
loophole. The ordering constraint exists because voice must be profiled before
anything proposes words, and nothing in the library proposes words except
`Paper.edit()`, which is behind the gate.

**The claim confirmation stop.** Enforced for the CLI through the gate, and
unreachable from the library, because the library had no `edit` at all. It has
one now, behind the same `gather()` call, so `Paper.edit()` raises
`EvidenceGateError` on an unconfirmed claim exactly as `rb edit` exits 2.

`Paper.edit()` proposes and never writes. Applying a patch to somebody's draft
stays on the command line, where `--apply` is a thing a person typed, a backup
is taken first, and `rb revert` undoes it.

## Skill rules

These hold when `SKILL.md` is loaded and not otherwise. They are instructions
to a model about how to talk to a person, which is not a thing code can check.

* Show the extracted claim to the user and wait before running anything that
  depends on it. The tool can refuse to act on an unconfirmed claim, and it
  does. It cannot make anyone read the sentence.
* Read a reference file at the step that needs it rather than loading them all.
* Say "likely a false positive, leave it" rather than proposing a change, when
  a flag has the shape of one.
* Write the final analysis rather than relaying ten passes of output.
* Never answer a reviewer question. Structural today, since nothing in this
  package generates prose, and stated here because the skill layer is the one
  place that could.

## Obligations on the caller

The honest goal is not "impossible to misuse". It is that every rule which can
be a check is one, and the rest are written down as obligations rather than
left implied. These are the rest.

**Show the coverage.** Every report object carries what was checked and what
could not be: how many bibliography entries resolved, how many cited works had
retrievable full text, whether the run was offline. The objects carry it and
nothing can make you surface it. Presenting a partial overlap check as a
plagiarism result is outside what this package can stop you doing, and it is
the single most damaging thing you can do with it.

**Read the left-alone list out.** `TraceReport.left_alone` holds the passages
the audit examined and deliberately did not flag. An author told what was
looked at and not changed can trust the flags that remain. Dropping it is
lossless for you and expensive for them.

**Do not present any count as a score.** The tool never emits a percentage. It
cannot stop you dividing two of its counts.

**Confirm the claim with a person.** `Paper.novelty(confirmed=True)` is you
asserting that somebody read the sentence and agreed with it. The gate believes
you. Nothing checks it, and nothing can.
