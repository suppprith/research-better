# Voice preservation

Read before proposing any edit. Loaded by the edit pass only.

## The whitelist rule

`voice.json` records every term the author actually used, as an exact surface
form. That set is a whitelist. An edit may use a word from it. An edit may not
introduce a word the author never wrote.

The loudest tell of a machine edit is a synonym the author never used. A draft
that says "model" forty times and suddenly says "framework" once reads wrong to
a human before they can say why, and it reads wrong to a reviewer who knows the
author's other papers.

Exact forms, never lemmas. If the author writes `self-attention` and never
`self attention`, that distinction is the point.

## Contrast pairs

The pairs matter more than any rule statement. In each, the draft says:

> We index the corpus with BM25 and expand queries from a first-pass ranking.

### Deleting filler: keeps voice

| | |
|---|---|
| Before | It is important to note that we index the corpus with BM25. |
| After | We index the corpus with BM25. |
| Why it holds | Only the opener was removed. Every remaining word is the author's. |

### Swapping a term: breaks voice

| | |
|---|---|
| Before | We index the corpus with BM25. |
| After | We index the collection with BM25. |
| Why it breaks | The author wrote "corpus" throughout. "Collection" is not in the whitelist, and a reviewer reads the change as somebody else's hand. |

### Tightening within the whitelist: keeps voice

| | |
|---|---|
| Before | We performed an analysis of the query logs. |
| After | We analysed the query logs. |
| Why it holds | A fixed dictionary substitution, and the author already writes British spelling. Check `spelling` in the profile before choosing `analysed` over `analyzed`. |

### Smoothing rhythm: breaks voice

| | |
|---|---|
| Before | Recall rose. The cost was one third that of the dense baseline on the same hardware, measured over 5,000 queries. |
| After | Recall rose, and the cost was one third that of the dense baseline. |
| Why it breaks | The author's sentence lengths vary widely. Evening them out is a style the author does not have, and it dropped a measurement. |

### Raising a hedge: breaks voice and meaning

| | |
|---|---|
| Before | We did not observe the same gain on the long-tail split. |
| After | The gain was somewhat less pronounced on the long-tail split. |
| Why it breaks | It converts a negative result into a soft positive. Never do this. It is a change to what the paper reports, not to how it reads. |

## Reading the profile

| Field | Use it to |
|---|---|
| `terminology` | Constrain word choice. This is the whitelist |
| `hyphenation` | Pick `first-pass` over `first pass` when both appear |
| `spelling` | Pick `analysed` over `analyzed` |
| `oxford_comma` | Match list punctuation |
| `person` | Keep "we" or keep it impersonal. Do not introduce "we" into a paper that has none |
| `sentence_lengths` | Do not flatten toward the mean. The variance is the author's |
| `hedges_per_hundred_words` | Do not add hedges, and do not strip an author's normal caution |
| `passive_ratio` | Texture only. Never flag a sentence on this alone |

## Section-local first

Papers have several authors. Use `for_section` and fall back to the global
profile only when the section is too short to measure. A profile fitted to five
sentences is noise, and constraining an edit toward noise is worse than not
constraining it.

## When no edit is safe

Say so. `REVIEW` is a real answer. The author knows something the profile does
not, and an edit that satisfies every field above can still be wrong.
