# Fixtures

## `bad-paper.md`

A short fake CS paper with defects planted on purpose. Every pass is tested
against it, so a contributor can tell whether a change improved or degraded
behaviour rather than guessing.

The paper is not subtle. It is a test instrument, not a writing sample.

### What is planted, and where

| Defect | Location |
|---|---|
| Filler openers | Introduction paragraph 1 and 2, Related Work paragraph 3, Results paragraph 1 |
| Hedge stacking | Introduction paragraph 2 ("may potentially suggest", "could possibly indicate", "seems to somewhat imply") |
| Overused model vocabulary | Introduction ("pivotal", "realm", "landscape", "testament", "tapestry", "intricate", "harness", "leverages", "seamless", "crucial", "underscore") |
| Nominalization | Introduction paragraph 2 ("performed an analysis of") |
| Stated contribution the body never supports | Introduction paragraph 3 claims a formal proof of convergence. No proof, theorem, or derivation appears anywhere |
| Citation-free superlative | Results paragraph 1 ("significantly outperforms", "best results reported to date", "novel", "substantially") with no test statistic and no citation |
| Throat-clearing transition run | Related Work paragraph 3, Method paragraph 2, and Results paragraph 1 open with Furthermore, Moreover, Additionally |
| Uniform sentence rhythm | Method paragraph 1, five sentences between 11 and 13 words |
| Tricolon | Method paragraph 2 ("efficient, scalable, and robust") |
| Balanced-clause template | Method paragraph 2 ("Not only does it reduce latency, but it also improves recall") |
| Empty forward reference | Method paragraph 2 ("As will be discussed later") with no later discussion |
| Section-closing restatement | Conclusion restates the Introduction's opening claim with no new content |
| Orphan paragraphs | Related Work paragraph 2 (search engines), Method paragraph 3 (databases), Results paragraph 3 (peer review). None supports any claim in the paper |

### Citations

| Key | Kind |
|---|---|
| `[1]` | Invented. No such paper, and the DOI does not resolve |
| `[2]` | Real. Robertson and Zaragoza, BM25 and Beyond, 2009 |
| `[3]` | Real authors, wrong title. Karpukhin and Oguz wrote about dense passage retrieval, not "A Complete Survey of Dense Retrieval Methods" |
| `[4]` | Invented. Plausible-looking venue that does not exist |
| `[5]` | Stands in for a retracted paper. Cited in Related Work as still circulating |

### The paragraph that must survive

**Results paragraph 2**, beginning "Recall at ten rises from 0.62 to 0.71".

It carries numbers, a citation, an explicit negative result, and varied sentence
lengths. Every pass must produce zero findings on it. A tool that flags
everything is useless, so this paragraph is the one that proves the passes
discriminate rather than fire.

If a change makes this paragraph produce a finding, the change is wrong, even if
it improved recall on every other case.

## `sample.md` and `latex/`

Format-conformance fixtures for the ingest adapters. They exercise parsing, not
judgement, so their prose is unremarkable on purpose.
