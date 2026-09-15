The BioASQ-style QA evaluation pipeline at `/app/evaluator/evaluate.py` contains exactly 3 implementation bugs that cause metric values to deviate from the specification at `/app/spec.md`. Golden answers are at `/app/data/golden.json`, system submissions at `/app/data/submissions/system_{alpha..epsilon}.json`, and the buggy evaluator output at `/app/evaluator/output.json`. A historical evaluation database with 3 prior rounds for returning participants (alpha, beta, gamma) is at `/app/data/historical.db`.

Produce `/app/audit.json` containing:

```json
{
  "corrected_results": {
    "<system>": {
      "document_retrieval": {"map": float, "gmap": float},
      "yesno": {"accuracy": float, "macro_f1": float},
      "factoid": {"strict_accuracy": float, "lenient_accuracy": float, "mrr": float},
      "list": {"mean_precision": float, "mean_recall": float, "mean_f1": float}
    }
  },
  "corrected_ranking": [{"rank": int, "system": str, "avg_rank": float}],
  "bugs": [{"id": str, "description": str, "affected_metric": str, "ranking_impact": bool}],
  "bootstrap_analysis": {
    "<system>": {"rank_ci_lower": float, "rank_ci_upper": float, "prob_rank_1": float}
  },
  "historical_anomalies": [
    {"system": str, "metric": str, "current_value": float, "historical_mean": float, "z_score": float}
  ]
}
```

Requirements:

- **corrected_results / corrected_ranking**: Metrics and rankings computed according to `/app/spec.md` (Sections 1–5), with all bugs fixed.
- **bugs**: Identify the 3 bugs, describe each, name the affected metric, and indicate whether each bug changes the system ranking compared to the correct one.
- **bootstrap_analysis**: Ranking confidence analysis as specified in `/app/spec.md` Section 6.
- **historical_anomalies**: For returning systems with sufficient historical data, report ranking metrics (`yesno_macro_f1`, `factoid_mrr`, `list_mean_f1`) where the corrected current value deviates by |z_score| > 2.0 from historical rounds 1–3.

Additionally, update `/app/data/historical.db`:
- Insert round 4 ("BioASQ Round 4") with corrected metrics for all 5 systems (register delta/epsilon as new)
- Create views `v_metric_trends` and `v_current_anomalies` as specified in `/app/spec.md` Section 7