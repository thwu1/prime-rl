`/app/eval_data/` contains raw output from a GPU kernel optimization benchmark evaluation pipeline. The dataset covers 20 kernel implementations tested across 5 computational kernels on two GPU architectures (A100 and V100). Data files include hardware specifications with peak performance characteristics, problem definitions with computational profiles, and per-result evaluation records with individual timing trial measurements, correctness outcomes, and validation metadata.

Quality assurance has flagged this dataset as containing unreliable results but has not identified which results are affected or categorized the issues. Audit the complete dataset: determine which results can be trusted, classify each reliability issue, and produce corrected aggregate performance metrics computed only from trustworthy data.

Write your findings to `/app/audit_report.json`:

```json
{
  "anomalies": [
    {
      "result_id": "<str>",
      "anomaly_type": "<classification>",
      "recommendation": "exclude|correct"
    }
  ],
  "corrected_metrics": {
    "<hardware_name>": {
      "fast_0.0": <float>,
      "fast_1.0": <float>,
      "fast_2.0": <float>
    }
  },
  "total_results": <int>,
  "clean_count": <int>,
  "excluded_count": <int>
}
```

`anomaly_type`: a string classifying the category of reliability issue. Different root causes must receive distinct classification labels.

`recommendation`: `"exclude"` if the result is fundamentally unrecoverable; `"correct"` if the timing data can be adjusted and the result retained.

`fast_p(t)` = fraction of trustworthy results (per hardware) where correctness is true AND speedup >= t. Speedup = mean(reference trials) / mean(kernel trials). For corrected results, use adjusted kernel timing.

`clean_count` = total results minus excluded count.