# Evaluation Protocol

## 1. Passage-to-Document Aggregation

This benchmark evaluates passage-level retrieval runs against document-level relevance judgments. Document scores are computed using the Maximum Passage (MaxP) strategy: for each query, a document's score equals the maximum score among all its constituent passages.

The corpus defines passage-to-document mappings via the `parent_id` field. When this mapping is unavailable for a passage, derive the parent document identifier from the passage ID structure.

## 2. Tie-Breaking

When documents share identical aggregated scores, order by document ID in ascending lexicographic order.

## 3. Metrics

### nDCG@10

Normalized Discounted Cumulative Gain at cutoff 10:
- Gain: g(rel) = 2^rel - 1
- Discount: d(i) = log_2(i + 1), where i is the 1-based rank position
- If ideal DCG = 0, then nDCG = 0
- Unjudged documents have relevance 0
- Report arithmetic mean across all queries

### Recall@100

Binary recall at depth 100. A document is relevant if its label >= 1. If no relevant documents exist for a query, recall = 0. Report arithmetic mean across all queries.

## 4. Statistical Significance

Compare all pairs of runs using a two-sided paired permutation test on per-query nDCG@10:
- 10,000 permutations per comparison
- Reset numpy random seed to 42 before each pairwise comparison
- Swap mask: `np.random.randint(0, 2, n_queries)`
- p-value = proportion of permutations where |permuted_diff| >= |observed_diff|
- Significance threshold: p < 0.05

## 5. Data Quality

Ensure identifier consistency across relevance judgments, runs, and corpus before evaluation. Normalize identifiers appropriately.

## 6. Output

Conform to `output_schema.json`. All floating-point values rounded to 4 decimal places.
