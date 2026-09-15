A research group submitted 8 ML experiments for publication review. Each experiment stores its training and evaluation artifacts in different data formats (HDF5 with nested training diagnostics, Apache Parquet with per-sample scores, structured text logs, JSONL). Some experiments may contain fabricated results, statistically anomalous distributions, or evidence of evaluation tampering.

## Environment

- `/app/experiments.db` — SQLite database with experiment metadata, claimed metric values, and an `integrity_rules` table defining the fraud categories to detect. The rules specify WHAT anomalies to look for — determining the appropriate detection methodology, statistical tests, and thresholds is part of the challenge.
- `/app/experiments/` — 8 experiment directories, each containing YAML configs and raw artifacts. HDF5 files may contain multiple diagnostic datasets beyond loss curves (e.g., gradient statistics). Text logs may contain multiple appended runs with different seeds.
- `/app/reference.duckdb` — DuckDB database with reference score distributions and training profile statistics from previously validated experiments, indexed by dataset, model class, optimizer type, and modality.

## Objective

Create `/app/audit.py` that, when executed via `python3 /app/audit.py`, produces `/app/audit_report.json`:

```json
{
  "experiments": {
    "<experiment_id>": {
      "verdict": "PASS" or "SUSPICIOUS",
      "metrics": { "<metric_name>": <value>, ... },
      "violations": [{"type": "<rule_name>", "detail": "<description>"}]
    }
  },
  "summary": {
    "total": 8,
    "pass": <count>,
    "suspicious": <count>,
    "flagged_experiments": ["<experiment_id>", ...]
  }
}
```

An experiment is `SUSPICIOUS` if it triggers one or more integrity violations. Violation `type` values must correspond to `rule_name` entries from the `integrity_rules` table. Metric keys must match `metric_name` values from the `claimed_results` table.

## Success Criteria

- All 8 experiments present with correct verdicts
- Extracted metrics accurate within +/-0.5 for percentage-scale metrics, +/-0.02 for ratio-scale metrics
- All integrity violations correctly identified with proper type labels
- Zero false positives on clean experiments