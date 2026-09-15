A search engine deployment at `/app/` contains a binary inverted index, evaluation queries, relevance judgments, and associated metadata. A previous evaluation attempt failed — diagnostic artifacts are in `/app/logs/`.

Investigate the deployment environment, determine the binary formats and encoding schemes used across all index files, extract configuration and term metadata from the metadata store, and build a query evaluation pipeline that produces correct ranked results with dynamic pruning. Evaluate the results against the provided relevance judgments using the evaluation tool source at `/app/tools/trec_eval/` (compilation required).

Write output files:

**`/app/results.run`** — TREC run format:

    <qid> Q0 <external_doc_id> <rank> <score> maxscore

**`/app/results.json`**:

    {
      "index_stats": {
        "num_docs": <int>,
        "num_terms": <int>,
        "avg_doc_len": <float>,
        "total_postings": <int>
      },
      "queries": [
        {
          "qid": "<query_id>",
          "results": [{"docid": <int>, "score": <float>}, ...],
          "num_scored": <int>
        }
      ],
      "eval_metrics": {
        "ndcg_cut_10": <float>,
        "map": <float>
      }
    }

- `results`: sorted by score descending, then document ID ascending for ties.
- `num_scored`: documents that received full scoring across all query terms during that query's processing. For queries with 3+ terms, this count must be strictly less than the total number of unique documents containing any of the query terms.
- `eval_metrics`: aggregate metrics from evaluating the run file against `/app/qrels/eval.qrels`.