A BM25-based search engine at `/app/` indexes 25 technical documents from a SQLite database (`/app/data/corpus.db`) and ranks results for queries in `/app/data/queries.json`. Run `make run` from `/app/` to execute the pipeline; output is written to `/app/output.json`.

The system currently produces poor rankings due to multiple interacting defects spanning data access, text processing, index construction, scoring, and result aggregation. The defects interact: some mask others, and partial fixes can worsen rankings rather than improve them.

An evaluation module skeleton at `/app/evaluation/metrics.py` provides stub functions for computing DCG@k and NDCG@10 (Normalized Discounted Cumulative Gain). Implement this module, then use the evaluation harness at `/app/evaluation/evaluate.py` (invoked via `make evaluate`) with the graded relevance judgments at `/app/data/qrels.json` (scale 0–3) to measure retrieval quality.

Diagnose and fix all pipeline defects so that every query achieves NDCG@10 ≥ 0.80 and the output conforms to the schema below.

## Output Schema

`/app/output.json`: a JSON object keyed by query string. Each value is an array of result objects sorted by `score` descending:

```
{
  "<query>": [
    {"doc_id": <int, valid range 1-25>, "score": <positive number>, "title": <string>},
    ...
  ]
}
```

All queries from `/app/data/queries.json` must appear as keys. Result arrays must be non-empty with unique `doc_id` values.