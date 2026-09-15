#!/usr/bin/env python3
"""Generate the complete incident environment: config files, SQLite database, and logs."""
import sqlite3
import json
import os

for d in ["/app/data", "/app/config", "/app/logs", "/app/docs", "/app/output"]:
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------------------
# Write SLO configuration
# ---------------------------------------------------------------------------
slo_config = {
    "availability": {
        "target": 0.999,
        "period_days": 30
    },
    "latency": {
        "target": 0.99,
        "threshold_ms": 200,
        "period_days": 30
    }
}
with open("/app/config/slo.json", "w") as f:
    json.dump(slo_config, f, indent=4)
    f.write("\n")
print("Generated /app/config/slo.json")

# ---------------------------------------------------------------------------
# Write alerting configuration (raw YAML to preserve merge key semantics)
#
# NOTE: page_critical has burn_rate: 1.44 placed BEFORE the merge key <<.
# In YAML, explicit keys placed before a merge directive are NOT overridden
# by the merged mapping. So page_critical.burn_rate parses as 1.44 instead
# of the page_defaults value 14.4.  This is the intentional config bug the
# analyst must discover.
# ---------------------------------------------------------------------------
alerts_yaml = """\
# Multi-window multi-burn-rate SLO alerting configuration
# Based on Google SRE Workbook Chapter 5 (Alerting on SLOs), Approach 6
#
# Each alert evaluates two sliding windows simultaneously:
#   - A long window to detect sustained error budget consumption
#   - A short window to confirm the issue is currently ongoing
# Alert fires when BOTH windows' error rates strictly exceed:
#   threshold = burn_rate * (1 - slo_target)

slo:
  target: 0.999
  period_days: 30

# Severity-level defaults using YAML anchors
severity_defaults:
  page: &page_defaults
    severity: page
    burn_rate: 14.4
  ticket: &ticket_defaults
    severity: ticket
    burn_rate: 1.0

alerts:
  - name: ticket
    <<: *ticket_defaults
    long_window_s: 259200
    short_window_s: 21600

  - name: page_high
    <<: *page_defaults
    burn_rate: 6.0
    long_window_s: 21600
    short_window_s: 1800

  - name: page_critical
    burn_rate: 1.44
    <<: *page_defaults
    long_window_s: 3600
    short_window_s: 300

failure_detection:
  error_rate_threshold: 0.25
  consecutive_seconds: 30
"""
with open("/app/config/alerts.yaml", "w") as f:
    f.write(alerts_yaml)
print("Generated /app/config/alerts.yaml")

# ---------------------------------------------------------------------------
# Write output specification
# ---------------------------------------------------------------------------
output_spec = """\
# SRE Incident Analysis -- Output Specification

## Data Sources

- `/app/data/metrics.db` -- SQLite database with per-second per-cluster metrics
  - Table `clusters`: `id` (int PK), `name` (text), `region` (text), `capacity_qps` (int)
  - Table `metrics`: `id` (int PK), `timestamp_s` (int), `cluster_id` (int FK), `requests` (int), `errors` (int), `latency_p50_ms` (int), `latency_p99_ms` (int)
- `/app/config/slo.json` -- SLO targets and evaluation periods for both availability and latency
- `/app/config/alerts.yaml` -- Multi-window multi-burn-rate alerting rules (Google SRE Workbook methodology)
- `/app/logs/incident_summary.txt` -- On-call team incident notes
- `/app/logs/lb_events.log` -- Load balancer controller event log

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

Error budget consumption quantifies what fraction of the total allowable error budget -- determined by the SLO target over its evaluation period -- has been spent during the observation window. Both the availability and latency SLOs define independent error budgets. Apply the standard burn-rate error budget model.

### Latency SLI

The latency SLI evaluates p99 latency compliance against the configured threshold from `slo.json`. Each per-cluster per-second observation with requests > 0 is classified as compliant (p99 <= threshold) or non-compliant. The SLI is the request-weighted fraction of compliant observations.

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
"""
with open("/app/docs/output_spec.md", "w") as f:
    f.write(output_spec)
print("Generated /app/docs/output_spec.md")

# ---------------------------------------------------------------------------
# Phase definitions for the cascading failure scenario
# (start_t, end_t, {cluster: (requests, errors, latency_p50, latency_p99)})
#
# Phase 1 (0-199):   Normal operation, all clusters healthy
# Phase 2 (200-229): Gamma upstream dependency failure, 90% error rate
# Phase 3 (230-259): Gamma drained, traffic redistributed to alpha+beta
# Phase 4 (260-359): Beta overwhelmed and drained, all traffic to alpha
# Phase 5 (360-599): Manual traffic reduction, alpha recovering
# ---------------------------------------------------------------------------
PHASES = [
    (0, 199, {
        "alpha": (1000, 1, 45, 120),
        "beta":  (600, 1, 40, 110),
        "gamma": (400, 0, 35, 95),
    }),
    (200, 229, {
        "alpha": (1000, 1, 50, 130),
        "beta":  (600, 1, 45, 115),
        "gamma": (400, 360, 4500, 9800),
    }),
    (230, 259, {
        "alpha": (1250, 50, 110, 450),
        "beta":  (750, 250, 280, 950),
        "gamma": (0, 0, 0, 0),
    }),
    (260, 359, {
        "alpha": (2000, 200, 220, 800),
        "beta":  (0, 0, 0, 0),
        "gamma": (0, 0, 0, 0),
    }),
    (360, 599, {
        "alpha": (800, 1, 55, 140),
        "beta":  (0, 0, 0, 0),
        "gamma": (0, 0, 0, 0),
    }),
]

CLUSTERS = {
    "alpha": (1, "us-east-1", 2500),
    "beta":  (2, "eu-west-1", 1000),
    "gamma": (3, "ap-south-1", 500),
}

# ---------------------------------------------------------------------------
# Create SQLite database
# ---------------------------------------------------------------------------
db_path = "/app/data/metrics.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("""CREATE TABLE clusters (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    region TEXT NOT NULL,
    capacity_qps INTEGER NOT NULL
)""")

c.execute("""CREATE TABLE metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_s INTEGER NOT NULL,
    cluster_id INTEGER NOT NULL,
    requests INTEGER NOT NULL,
    errors INTEGER NOT NULL,
    latency_p50_ms INTEGER NOT NULL,
    latency_p99_ms INTEGER NOT NULL,
    FOREIGN KEY (cluster_id) REFERENCES clusters(id)
)""")

c.execute("CREATE INDEX idx_metrics_ts ON metrics(timestamp_s)")
c.execute("CREATE INDEX idx_metrics_cluster ON metrics(cluster_id)")
c.execute("CREATE INDEX idx_metrics_ts_cluster ON metrics(timestamp_s, cluster_id)")

for name, (cid, region, capacity) in CLUSTERS.items():
    c.execute("INSERT INTO clusters VALUES (?, ?, ?, ?)", (cid, name, region, capacity))

for start, end, clusters in PHASES:
    for t in range(start, end + 1):
        for cluster_name in ["alpha", "beta", "gamma"]:
            reqs, errs, p50, p99 = clusters[cluster_name]
            cid = CLUSTERS[cluster_name][0]
            c.execute(
                "INSERT INTO metrics (timestamp_s, cluster_id, requests, errors, "
                "latency_p50_ms, latency_p99_ms) VALUES (?, ?, ?, ?, ?, ?)",
                (t, cid, reqs, errs, p50, p99),
            )
            # Data quality issue: gamma metrics for t=200-229 were ingested
            # twice due to a collector race condition during the incident.
            if cluster_name == "gamma" and 200 <= t <= 229:
                c.execute(
                    "INSERT INTO metrics (timestamp_s, cluster_id, requests, errors, "
                    "latency_p50_ms, latency_p99_ms) VALUES (?, ?, ?, ?, ?, ?)",
                    (t, cid, reqs, errs, p50, p99),
                )

conn.commit()

total_rows = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
conn.close()
print(f"Generated {db_path}: {total_rows} rows")

# ---------------------------------------------------------------------------
# Generate load balancer event log
# ---------------------------------------------------------------------------
with open("/app/logs/lb_events.log", "w") as f:
    base = "2024-01-15T10"

    # Periodic health checks during normal operation (every 30s)
    for s in range(0, 200, 30):
        m, sec = divmod(s, 60)
        ts = f"{base}:{m:02d}:{sec:02d}Z"
        f.write(f"{ts} INFO lb-controller healthcheck cluster=alpha status=healthy "
                f"backends=50/50 error_rate=0.001\n")
        f.write(f"{ts} INFO lb-controller healthcheck cluster=beta status=healthy "
                f"backends=30/30 error_rate=0.002\n")
        f.write(f"{ts} INFO lb-controller healthcheck cluster=gamma status=healthy "
                f"backends=20/20 error_rate=0.000\n")

    # Gamma spike at t=200
    f.write(f"{base}:03:20Z WARN lb-controller anomaly cluster=gamma "
            f"error_rate=0.900 threshold=0.250 action=monitoring\n")

    # Sustained gamma failure warnings
    for s in [210, 220]:
        m, sec = divmod(s, 60)
        f.write(f"{base}:{m:02d}:{sec:02d}Z WARN lb-controller anomaly "
                f"cluster=gamma error_rate=0.900 sustained_seconds={s - 200}\n")

    # Gamma marked unhealthy at t=229
    f.write(f"{base}:03:49Z CRIT lb-controller failure cluster=gamma "
            f"status=unhealthy consecutive_seconds=30 action=drain\n")
    f.write(f"{base}:03:50Z INFO lb-controller redistribution cluster=gamma "
            f"drained=true targets=alpha,beta\n")

    # Beta degradation after redistribution
    f.write(f"{base}:03:50Z WARN lb-controller anomaly cluster=beta "
            f"error_rate=0.333 threshold=0.250 action=monitoring\n")
    for s in [240, 250]:
        m, sec = divmod(s, 60)
        f.write(f"{base}:{m:02d}:{sec:02d}Z WARN lb-controller anomaly "
                f"cluster=beta error_rate=0.333 sustained_seconds={s - 230}\n")

    # Beta marked unhealthy at t=259
    f.write(f"{base}:04:19Z CRIT lb-controller failure cluster=beta "
            f"status=unhealthy consecutive_seconds=30 action=drain\n")
    f.write(f"{base}:04:20Z INFO lb-controller redistribution cluster=beta "
            f"drained=true targets=alpha\n")

    # Alpha overload
    f.write(f"{base}:04:20Z WARN lb-controller overload cluster=alpha "
            f"error_rate=0.100 qps=2000 capacity=2500\n")

    # Manual intervention at t=360
    f.write(f"{base}:06:00Z INFO lb-controller manual_action operator=oncall-sre1 "
            f"action=traffic_reduction cluster=alpha reduction_pct=60\n")

    # Recovery
    f.write(f"{base}:06:30Z INFO lb-controller recovery cluster=alpha "
            f"error_rate=0.001 status=stabilizing\n")
    f.write(f"{base}:10:00Z INFO lb-controller recovery cluster=alpha "
            f"status=healthy error_rate=0.001 incident=resolved\n")

print("Generated /app/logs/lb_events.log")

# ---------------------------------------------------------------------------
# Generate incident summary (realistic on-call notes, no answer keys)
# ---------------------------------------------------------------------------
with open("/app/logs/incident_summary.txt", "w") as f:
    f.write("INCIDENT REPORT #2024-0115-001\n")
    f.write("Severity: P1 - Service Degradation\n")
    f.write("Duration: ~10 minutes (10:03:20 - 10:10:00 UTC, Jan 15 2024)\n")
    f.write("Affected: Multi-cluster API service (alpha, beta, gamma)\n")
    f.write("Status: Resolved\n")
    f.write("\n")
    f.write("TIMELINE (from on-call notes):\n")
    f.write("- 10:03:20 UTC - Pagerduty alert from monitoring: gamma cluster anomalous\n")
    f.write("- 10:03:49 UTC - gamma marked unhealthy by load balancer, traffic drain initiated\n")
    f.write("- 10:03:50 UTC - Traffic redistributed to remaining clusters (alpha, beta)\n")
    f.write("- 10:04:19 UTC - Second cascade event: beta reported unhealthy under load\n")
    f.write("- 10:04:20 UTC - beta drained, all traffic routed to alpha\n")
    f.write("- 10:06:00 UTC - Manual intervention: traffic reduction applied to alpha\n")
    f.write("- ~10:10:00 UTC - Service stabilized, incident closed\n")
    f.write("\n")
    f.write("ON-CALL NOTES (sre-oncall1@):\n")
    f.write('"Initial gamma failure traced to upstream dependency outage -- gamma\'s error\n')
    f.write("rate went through the roof instantly. We noticed something odd on the metrics\n")
    f.write("dashboard during the gamma window; numbers looked inflated, like the collector\n")
    f.write("hiccupped. Might have been a race condition in the ingestion pipeline -- worth\n")
    f.write("investigating. Beta went down classic cascade-style: we dumped gamma's full\n")
    f.write("traffic onto it without any shedding, and it buckled. Alpha survived only\n")
    f.write("because we manually cut incoming traffic at 10:06. Latency was brutal across\n")
    f.write("the board during the redistribution phases -- p99 went way above our SLO\n")
    f.write("threshold on every cluster that was absorbing extra load.\n")
    f.write("\n")
    f.write("Also, page_critical alert fired noticeably later than I'd expect for a burn\n")
    f.write("rate that high. Might want someone to double-check the alerting config -- the\n")
    f.write("YAML uses anchors and merge keys for the severity defaults and I've seen those\n")
    f.write('cause surprises before."\n')
    f.write("\n")
    f.write("FOLLOW-UP ITEMS:\n")
    f.write("- [ ] Verify metrics pipeline data integrity for gamma during incident window\n")
    f.write("- [ ] Audit alerting YAML configuration for merge key issues\n")
    f.write("- [ ] Review load redistribution strategy to prevent future cascades\n")
    f.write("- [ ] Assess latency SLO impact -- p99 violations during incident phases\n")

print("Generated /app/logs/incident_summary.txt")

# ---------------------------------------------------------------------------
# Verify all generated files
# ---------------------------------------------------------------------------
for path in [
    "/app/config/slo.json",
    "/app/config/alerts.yaml",
    "/app/docs/output_spec.md",
    "/app/data/metrics.db",
    "/app/logs/lb_events.log",
    "/app/logs/incident_summary.txt",
]:
    assert os.path.isfile(path), f"MISSING: {path}"
    assert os.path.getsize(path) > 0, f"EMPTY: {path}"

# Quick sanity: verify slo.json has expected keys
with open("/app/config/slo.json") as f:
    slo = json.load(f)
assert "availability" in slo, "slo.json missing 'availability'"
assert "latency" in slo, "slo.json missing 'latency'"
assert "threshold_ms" in slo["latency"], "slo.json missing 'latency.threshold_ms'"
print("All files generated and verified successfully.")
