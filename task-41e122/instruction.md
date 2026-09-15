Three BM25 search indexes (`/app/index_a/`, `/app/index_b/`, `/app/index_c/`) were built over the same 40-document corpus using the `bm25s` library with different scoring variants and parameters. Each index stores pre-computed BM25 scores in CSC (Compressed Sparse Column) sparse matrix format — `data.csc.index.npy`, `indices.csc.index.npy`, `indptr.csc.index.npy`, and `vocab.index.json`.

All three `params.index.json` files have been **tampered with** — they contain incorrect variant names and parameter values. One index falsely claims to use `bm25+`, causing `bm25s.BM25.load()` to crash with a missing `nonoccurrence_array` error. The other two load but produce incorrect retrieval because their claimed parameters differ from the scores actually stored in the matrices.

Graded relevance judgments are provided at `/app/qrels.json` mapping query IDs to document relevance grades (0–3 scale). The possible BM25 variants are: `robertson`, `lucene`, `atire`, `bm25l`, `bm25+` — each with distinct IDF and term-frequency-component formulas per Kamphuis et al. (2020).

## Objectives

Determine the actual BM25 scoring variant and parameters (k1, b) for each of the three indexes by analyzing the stored score matrices against the corpus. Compute nDCG@10 for each index's retrieval results against the provided relevance judgments using the standard formula DCG@k = Σ (2^rel_i − 1) / log₂(i+1) for 1-indexed positions. Design and implement a rank fusion strategy combining all three indexes that achieves higher mean nDCG@10 than any individual index, optimizing fusion parameters for maximum retrieval quality.

## Data

- `/app/corpus.jsonl` — Documents (JSON lines, fields: `id`, `text`)
- `/app/stopwords.json` — Stopwords used during tokenization
- `/app/queries.json` — 10 queries for retrieval
- `/app/qrels.json` — Graded relevance judgments: `{query_id: {doc_id: grade}}`
- `/app/index_a/`, `/app/index_b/`, `/app/index_c/` — Pre-built indexes (CSC arrays, vocabulary, tampered params)

Tokenization used to build all indexes: lowercase text, split with regex `(?u)\b\w\w+\b`, remove stopwords from the provided list, no stemming.

## Output

Write `/app/output/results.json`:

```json
{
  "indexes": {
    "a": {"method": "<variant>", "k1": <float>, "b": <float>},
    "b": {"method": "<variant>", "k1": <float>, "b": <float>},
    "c": {"method": "<variant>", "k1": <float>, "b": <float>}
  },
  "individual_ndcg": {
    "a": <float>, "b": <float>, "c": <float>
  },
  "best_individual": "<a|b|c>",
  "fusion_method": "<description of fusion approach>",
  "fusion_k": <int>,
  "fusion_ndcg": <float>,
  "fusion_rankings": {
    "0": [doc_id, doc_id, ...],
    "1": [doc_id, doc_id, ...],
    ...
  }
}
```

Each `fusion_rankings` entry is a list of 10 document IDs (0-indexed integers) ranked by descending fused score.