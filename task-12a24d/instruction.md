Build a text retrieval system for the BRIGHT benchmark's Pony programming language task that achieves nDCG@10 >= 0.20 against hidden relevance judgments.

The document corpus (~7,894 Pony language documentation chunks) is at `/app/data/documents.json` -- an array of `{id, content}` objects. Document IDs are unique per instance. Queries are at `/app/data/queries.json` -- an array of `{id, query, reasoning, excluded_ids}` objects. Each query's `query` field contains a GPT-4 generated reasoning analysis of a Pony programming problem; the separate `reasoning` field is unused for this dataset. A reference `calculate_retrieval_metrics` function using pytrec_eval is at `/app/metrics.py`.

Produce `/app/scores.json` mapping each query ID to a dictionary of document ID -> retrieval score:

```json
{
  "query_id_1": {"doc_id_a": 5.32, "doc_id_b": 3.17},
  "query_id_2": {"doc_id_c": 7.01}
}
```

All query IDs from the input must have entries. Document IDs in scores must match those from `/app/data/documents.json` exactly. No document listed in a query's `excluded_ids` may appear in that query's results. Scores must originate from an actual retrieval computation over the document corpus.