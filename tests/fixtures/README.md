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
| Throat-clearing transition run | Related Work paragraphs 2, 3, and 4, consecutive, opening with Furthermore, Moreover, Additionally. Method paragraph 2 and Results paragraph 1 also open this way but stand alone, and a lone transition is not a defect |
| Uniform sentence rhythm | Method paragraph 1, five sentences between 11 and 13 words |
| Tricolon | Method paragraph 2, twice ("efficient, scalable, and robust" and "simple, fast, and general"). One tricolon is a sentence somebody wrote, so the rule needs the repetition |
| Balanced-clause template | Method paragraph 2, twice ("Not only does it reduce latency, but it also improves recall" and "not only cheaper to run but also easier to deploy") |
| Empty forward reference | Method paragraph 2 ("As will be discussed later") naming no target |
| Section-closing restatement | Conclusion's last sentence introduces no content word its first sentence did not already carry |
| Orphan paragraphs | Related Work paragraph 5 (search engines), Method paragraph 3 (databases), Results paragraph 3 (peer review). None supports any claim in the paper |

### Citations

| Key | Kind | Expected verdict |
|---|---|---|
| `[1]` | Invented. No such paper, and the DOI does not resolve | `NOT_FOUND` |
| `[2]` | Real. Robertson and Zaragoza, BM25 and Beyond, 2009 | `VERIFIED` |
| `[3]` | Real DOI carrying a wrong title. The DOI is the real Karpukhin and Oguz paper on dense passage retrieval, cited under a title they never wrote | `TITLE_MISMATCH` |
| `[4]` | Invented. Plausible-looking venue that does not exist | `NOT_FOUND` |
| `[5]` | Genuinely retracted, with a real Crossref retraction notice. Cited in Related Work as still circulating | `RETRACTED` |
| `[6]` | A real book. Books are indexed unevenly, and this one is the check that a book does not produce a false signal | `VERIFIED` |
| `[7]` | An invented thesis. Theses are not indexed at all, so the verdict must explain that rather than insinuate fabrication | `NOT_FOUND`, flagged `likely_unindexed` |

Entries `[6]` and `[7]` exist for one reason: a tool that reports an unindexed
work as missing without saying why is making a fabrication insinuation it cannot
support, and authors would be right to stop reading it. `NOT_FOUND` is never
styled as proof of anything.

### Recorded API responses

`http/` holds what OpenAlex, Crossref, Semantic Scholar, and arXiv actually
returned for these entries. CI replays them offline, so an unrecorded request
raises instead of quietly going out. Refresh with:

```
python scripts/record_fixtures.py --refresh
```

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
