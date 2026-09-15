# SRE Incident Analysis — Output Specification

## Data Sources

- `/app/data/metrics.db` — SQLite database with per-second per-cluster metrics
  - Table `clusters`: `id` (int PK), `name` (text), `region` (text), `capacity_qps` (int)
  - Table `metrics`: `id` (int PK), `timestamp_s` (int), `cluster_id` (int FK), `requests` (int), `errors` (int), `latency_p50_ms` (int), `latency_p99_ms` (int)
- `/app/config/slo.json` — SLO targets and evaluation periods for both availability and latency
- `/app/config/alerts.yaml` — Multi-window multi-burn-rate alerting rules (Google SRE Workbook methodology)
- `/app/logs/incident_summary.txt` — On-call team incident notes
- `/app/logs/lb_events.log` — Load balancer controller event log

## Output

Write a JSON file to `/app/output/findings.json` with the following structure:

```json
{
  "summary": {
    "total_requests": "<int: aggregate requests, corrected for any data quality issues>",
    "total_errors": "<int: aggregate errors, corrected for any data quality issues>",
    "overall_error_rate": "<float: total_errors / total_requests>",
    "simulation_duration_s": "<int: count of distinct timestamps>",
    "availability_budget_consumed_pct": "<float: percentage of the availability error budget consumed during the observation window>",
    "latency_sli": "<float: request-weighted fraction of compliant observations>",
    "latency_budget_consumed_pct": "<float: percentage of the latency error budget consumed during the observation window>"
  },
  "cluster_failures": [
    {
      "cluster": "<str: cluster name>",
      "detected_at_s": "<int: first timestamp meeting failure criteria>",
      "effective_from_s": "<int: detected_at_s + 1>"
    }
  ],
  "cascade_sequence": ["<str: clusters ordered by failure time>"],
  "alerts": [
    {
      "name": "<str: alert rule name>",
      "fired_at_s": "<int or null>",
      "resolved_at_s": "<int or null>",
      "active_at_end": "<bool>"
    }
  ],
  "peak_error_rate": "<float: maximum instantaneous global error rate>",
  "peak_error_rate_time_s": "<int: earliest timestamp achieving peak rate>",
  "data_quality": {
    "duplicates_found": "<bool>",
    "affected_cluster": "<str>",
    "affected_time_range": ["<int: start_ts>", "<int: end_ts>"],
    "duplicate_rows_removed": "<int>"
  },
  "config_discrepancies": [
    {
      "alert_name": "<str>",
      "field": "<str>",
      "parsed_value": "<float>",
      "intended_value": "<float>",
      "resolution": "<str>"
    }
  ]
}
```

## Methodology

### Alerting Evaluation

This system uses the **multi-window multi-burn-rate** alerting methodology from the Google SRE Workbook (Chapter 5, Approach 6). Each alert rule specifies a burn rate and two observation windows (long and short). The alert fires when error rates in both windows simultaneously indicate error budget consumption exceeding the specified burn rate. Consult the alert rule definitions in `alerts.yaml` for window sizes and burn rates, and the SLO target in `slo.json`.

### Cluster Failure Detection

The `failure_detection` section in `alerts.yaml` specifies the per-cluster error rate threshold and the number of consecutive seconds required to declare a cluster failed.

### Error Budget

Error budget consumption quantifies what fraction of the total allowable error budget — determined by the SLO target over its evaluation period — has been spent during the observation window. Both the availability and latency SLOs define independent error budgets. Apply the standard burn-rate error budget model.

### Latency SLI

The latency SLI evaluates p99 latency compliance against the configured threshold from `slo.json`. Each per-cluster per-second observation with requests > 0 is classified as compliant (p99 ≤ threshold) or non-compliant. The SLI is the request-weighted fraction of compliant observations.

### Data Quality & Configuration Audit

The analysis must independently assess the integrity of the metrics data and the correctness of the alerting configuration against its declared severity defaults. Any issues discovered must be reported and corrected for in all downstream computations.

## Implementation Notes

- A sliding window of W seconds at time t covers timestamps [max(0, t-W+1), t]. Window error rate = sum(errors)/sum(requests) across those timestamps; zero if total requests is zero.
- An alert fires at the first timestamp where both the long and short window error rates strictly exceed the threshold. It resolves at the first subsequent timestamp where the condition no longer holds.
- A second with zero requests for a cluster resets the consecutive failure count for that cluster.
- Peak error rate is per-second across all clusters. Report the maximum and its earliest timestamp.

## Ordering

- `cluster_failures`: ascending by `detected_at_s`
- `cascade_sequence`: ordered by failure time
- `alerts`: ascending by `fired_at_s`; `null` entries last
