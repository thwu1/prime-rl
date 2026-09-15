A production SGLang deployment exports Prometheus metrics. Four consecutive 30-second scrapes are at `/app/metrics/` (filenames are Unix epoch timestamps). SLO definitions, severity classification rules, and error-budget parameters are at `/app/slo_config.json`.

A monitoring pipeline at `/app/pipeline.sh` is intended to process these scrapes and produce an SLO compliance and burn-rate report at `/app/report.json`. The conversion script `/app/prom_to_json.py` is correct and must not be modified.

Currently `bash /app/pipeline.sh` fails. Diagnose and fix all issues so the pipeline runs end-to-end and `/app/report.json` is produced with correct values conforming to the schema below.

## Output schema for `/app/report.json`

```json
{
  "intervals": [
    {
      "start_ts": <int>,
      "end_ts": <int>,
      "duration_sec": <int>,
      "counter_reset_detected": <bool>,
      "request_rate_per_sec": <float>,
      "prompt_token_rate_per_sec": <float>,
      "generation_token_rate_per_sec": <float>,
      "percentiles": {
        "ttft_p99": <float>,
        "e2e_p99": <float>,
        "tpot_p95": <float>
      },
      "slo_verdicts": {
        "ttft_p99": <bool>,
        "e2e_p99": <bool>,
        "tpot_p95": <bool>,
        "request_throughput": <bool>
      },
      "severity": "<nominal|degraded|critical>"
    }
  ],
  "summary": {
    "total_intervals": <int>,
    "intervals_passing_all_slos": <int>,
    "intervals_with_violations": <int>,
    "violated_slo_names": [<string>, ...],
    "error_budget": {
      "observation_window_seconds": <int>,
      "per_slo_burn_rates": {
        "ttft_p99": <float>,
        "e2e_p99": <float>,
        "tpot_p95": <float>,
        "request_throughput": <float>
      },
      "overall_burn_rate": <float>
    }
  }
}
```

Intervals sorted chronologically. `violated_slo_names` sorted alphabetically. Burn rates are unitless ratios: 1.0 means budget consumption matches the target rate; >1.0 means consuming budget faster than sustainable. The `observation_window_seconds` is the total duration of all observed intervals. The overall burn rate is the maximum across all per-SLO burn rates.