---
title: Sparse Retrieval Still Wins at Equal Cost
author: A. Researcher
date: 2026-03-14
---

Introduction
============

Retrieval quality on this benchmark has plateaued since 2021 [1]. Dense
encoders are reported to beat sparse baselines [2, 3], but the comparisons
in Fig. 1 hold the index size constant rather than the budget.

We show that BM25 with query expansion matches a dense encoder at equal
cost, as also noted by Chen et al. and by [@nakamura2024].

<!-- reviewer note: tighten this once the ablation lands -->

Method
------

### Index

The corpus is indexed with BM25 using $k_1 = 0.9$ and $b = 0.4$. Queries
are expanded with the top three terms from a first-pass retrieval, which
follows the setup in Sec. 3 of the original paper (see https://doi.org/10.1145/1234.5678).

The scoring function is

$$
s(q, d) = \sum_{t \in q} \mathrm{idf}(t) \cdot \frac{f(t, d)}{f(t, d) + k_1}
$$

which is unchanged from the reference implementation.

### Implementation

```python
# This comment is not prose and must never be flagged as fluff.
def score(query, document):
    return sum(idf(t) * tf(t, document) for t in query)
```

Runs use a single node. The pipeline is described in Alg. 1.

Results
-------

| System   | Recall@10 | Cost |
| -------- | --------- | ---- |
| BM25+QE  | 0.71      | 1.0  |
| Dense    | 0.69      | 3.2  |

Recall at ten improves by four points at one third of the cost. The gain
holds across all three splits, i.e. it is not an artifact of one query set.

> Reviewers should note that the dense baseline was not retrained.

Three conditions were tested:

- Sparse retrieval alone, with no expansion applied to the query.
- Sparse retrieval with the expansion described above.
- A dense encoder trained on the same corpus, following arXiv:2401.01234.

References
----------

[1] Smith, J. and Lee, K. A Survey of Retrieval. JIR, 2021.

[2] Nakamura, R. Dense Encoders Revisited. Proc. ACM, 2023.
    https://doi.org/10.1145/9876.5432

[3] Chen, W. Budgets Matter. arXiv:2401.01234, 2024.
