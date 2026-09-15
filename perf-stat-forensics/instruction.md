Three services experienced performance degradation after a code deployment. The operations team captured `perf stat` hardware counter snapshots for each service under both the previous ("baseline") and current ("modified") builds, plus folded CPU profile stacks for `matrix_multiply`.

All raw captures are in `/app/captures/`. The team's analysis configuration (bottleneck classification rules, regression parameters, validation thresholds) is at `/app/config/thresholds.json`. FlameGraph tools are installed at `/app/FlameGraph/`.

Build `/app/perf_analyzer.py` and run it to produce:

1. **`/app/analysis_report.json`** conforming to the schema below
2. **`/app/diff_flamegraph.svg`** — differential flame graph of `matrix_multiply` (modified vs baseline)

## Report Schema

```json
{
  "workloads": {
    "<name>": {
      "baseline": {
        "ipc": "<float|null>",
        "cache_miss_rate": "<float|null>",
        "branch_miss_rate": "<float|null>",
        "frontend_stall_ratio": "<float|null>",
        "backend_stall_ratio": "<float|null>",
        "classification": "<category>"
      },
      "modified": { "...same keys..." },
      "regression": {
        "detected": "<bool>",
        "ipc_delta": "<float|null>",
        "primary_cause": "<cause_label|none>",
        "severity": "<critical|moderate|minor|none>"
      }
    }
  },
  "stack_analysis": {
    "matrix_multiply": {
      "top_regressions": [
        {"function": "...", "baseline_pct": "<float>", "modified_pct": "<float>", "delta": "<float>"}
      ],
      "top_consumers_modified": [
        {"function": "...", "exclusive_pct": "<float>", "inclusive_pct": "<float>"}
      ]
    }
  },
  "validation": {
    "<name>": {"noisy_system": "<bool>", "migration_issues": "<bool>"}
  }
}
```

Stack analysis lists are top 5, sorted descending by delta (regressions) or exclusive percentage (consumers).