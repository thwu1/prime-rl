An information retrieval shared task evaluated three retrieval systems against a graded test collection. The experiment data resides at `/app/experiment/` containing relevance judgments and system run files in standard TREC format.

The script at `/app/eval_pipeline.py` was used to produce the evaluation report at `/app/published_report.json`. A post-hoc review has flagged that multiple metric values in the report are incorrect. The reviewer did not specify which values are affected or what caused the errors.

Audit the evaluation, identify all issues, and produce a corrected evaluation report at `/app/corrected_report.json` with the following schema:

```json
{
  "systems": {
    "<system_name>": {
      "ndcg@10": <float>,
      "err@10": <float>,
      "map": <float>,
      "per_query": {
        "<query_id>": {
          "ndcg@10": <float>,
          "err@10": <float>,
          "ap": <float>
        }
      }
    }
  },
  "ranking": ["<best_system>", "<second>", "<third>"]
}
```

System names must match run file basenames (without `.run`). The `ranking` array orders systems by mean nDCG@10 descending. All floats rounded to 4 decimal places. Corrected metric values must agree with established IR evaluation tool implementations.