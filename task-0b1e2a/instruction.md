A production SGLang LLM serving cluster running three replicas exported Prometheus metrics during a sustained load test. Five metric snapshots are at `/app/metrics/snapshot_001.prom` through `snapshot_005.prom` in Prometheus exposition format. The SLO policy and error-budget configuration are at `/app/slo_config.json`.

Prometheus (v2.53.0) and `promtool` are installed and available in PATH. A draft Prometheus configuration at `/app/prometheus/prometheus.yml` has validation errors that prevent it from passing `promtool check config`. The directory `/app/prometheus/rules/` exists but is empty.

Deliver the following three artifacts:

1. `/app/prometheus/prometheus.yml` — must pass `promtool check config`.

2. One or more `.yml` rule files in `/app/prometheus/rules/` — Prometheus recording and alerting rules. Every file must pass `promtool check rules`. Recording rules should express the p99 latency percentile computations for the three histogram metrics in valid PromQL. Alerting rules should encode the SLO threshold conditions from `slo_config.json`.

3. `/app/report.json` — an SLO compliance report with the exact structure:

```json
{
  "snapshots": [
    {
      "file": "<filename>",
      "ttft_p99": <float>,
      "e2e_p99": <float>,
      "tpot_p99": <float>,
      "queue_depth": <float>,
      "cache_hit_rate": <float>,
      "gen_throughput": <float>,
      "slo_violations": ["<slo_name>", ...],
      "compliant": <bool>
    }
  ],
  "error_budget": {
    "max_violation_pct": <float>,
    "<slo_name>": {"violation_pct": <float>, "within_budget": <bool>}
  },
  "overall_healthy": <bool>
}
```

The `ttft_p99`, `e2e_p99`, and `tpot_p99` values must be the correctly computed 99th percentile latencies derived from the histogram bucket data in each snapshot, consistent with standard Prometheus histogram semantics. The `queue_depth`, `cache_hit_rate`, and `gen_throughput` values come from gauge metrics in the snapshots. For each snapshot, `slo_violations` lists SLO key names (matching the keys in `slo_config.json`) whose threshold condition is not met. A snapshot is `compliant` when `slo_violations` is empty. Snapshots must be ordered by filename. `violation_pct` is `(number_of_snapshots_violating_this_SLO / total_snapshots) * 100`. `within_budget` is `true` when `violation_pct <= max_violation_pct`. `overall_healthy` is `true` only when every SLO is within its error budget.