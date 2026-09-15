A search evaluation pipeline at `/app/pipeline.py` processes TREC-format retrieval data in `/app/data/` to compute IR metrics (nDCG@10, ERR@10, MAP@10) for five retrieval systems. The pipeline's metric outputs have been flagged as inconsistent with reference implementations, and the input data may contain quality issues that affect metric accuracy.

`trec_eval` is available at `/usr/local/bin/trec_eval`. Supporting data: `/app/data/query_taxonomy.json` (maps each query ID to a category), `/app/data/clicks.tsv` (production click log collected from the bm25 system under position bias), and `/app/data/README.txt` (data conventions and quality expectations).

Write `/app/audit_report.json` conforming to this schema:

```json
{
  "pipeline_bugs": [
    {"function_name": "...", "description": "..."}
  ],
  "data_issues": {
    "duplicate_qrels": [["query_id", "doc_id"], ...],
    "invalid_click_count": 0
  },
  "corrected_metrics": {
    "system_name": {"ndcg@10": 0.0, "err@10": 0.0, "map@10": 0.0}
  },
  "category_best_system": {
    "category_name": "best_system_name"
  },
  "fusion": {
    "optimal_k": 60,
    "fused_ndcg@10": 0.0
  },
  "click_model": {
    "power_law_exponent": 0.0,
    "r_squared": 0.0
  },
  "metric_concordance": {
    "ndcg_err_tau": 0.0,
    "ndcg_map_tau": 0.0,
    "err_map_tau": 0.0
  },
  "oracle_analysis": {
    "best_single_system": "system_name",
    "best_single_ndcg": 0.0,
    "oracle_ndcg": 0.0,
    "oracle_improvement_pct": 0.0
  }
}
```

**Field requirements:**

- `pipeline_bugs`: Every function in `pipeline.py` whose implementation produces incorrect metric values, with the function name and a description of the defect.
- `data_issues.duplicate_qrels`: All query-doc pairs appearing in the qrels file with conflicting relevance grades.
- `data_issues.invalid_click_count`: Total click log entries with non-positive position values.
- `corrected_metrics`: All three metrics recomputed correctly for each of the five systems, with all pipeline bugs and data quality issues resolved.
- `category_best_system`: For each query category, the system with the highest corrected mean nDCG@10.
- `fusion.optimal_k`: The integer k in [1,100] for RRF fusion across all five systems that maximizes mean nDCG@10 (tiebreak by ascending doc ID). `fused_ndcg@10`: the mean nDCG@10 achieved at that k.
- `click_model`: Model how user examination probability decays with result position using the click log (excluding invalid entries with position <= 0). Report the decay exponent and goodness-of-fit (R²).
- `metric_concordance`: Pairwise rank-order agreement between the three metrics across the five systems, measured at the system level using corrected values.
- `oracle_analysis`: The best single system by mean nDCG@10, the oracle mean nDCG@10 obtained by selecting the best-performing system independently for each query, and the percentage improvement ((oracle - best_single) / best_single * 100).