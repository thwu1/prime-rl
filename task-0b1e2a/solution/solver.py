#!/usr/bin/env python3
"""Fix Prometheus config, create recording rules, and generate SLO compliance report.

Handles multi-instance histogram metrics: aggregates bucket counts across
all replica instances before computing percentiles (mirrors the PromQL
pattern: histogram_quantile(0.99, sum by (le) (metric_bucket))).
"""

import json
import os
import re
import glob

# ============================================================
# Step 1: Fix Prometheus configuration
# ============================================================

FIXED_CONFIG = """\
global:
  scrape_interval: 30s
  evaluation_interval: 15s

rule_files:
  - '/app/prometheus/rules/*.yml'

scrape_configs:
  - job_name: 'sglang-metrics'
    honor_timestamps: true
    static_configs:
      - targets: ['localhost:9090']

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['localhost:9093']
      timeout: 5s
"""

with open("/app/prometheus/prometheus.yml", "w") as f:
    f.write(FIXED_CONFIG)
print("Fixed /app/prometheus/prometheus.yml")

# ============================================================
# Step 2: Write Prometheus recording and alerting rules
# ============================================================

os.makedirs("/app/prometheus/rules", exist_ok=True)

RULES = """\
groups:
  - name: sglang_slo_recording
    rules:
      - record: sglang:ttft_p99
        expr: histogram_quantile(0.99, sum by (le) (sglang:time_to_first_token_seconds_bucket))
      - record: sglang:e2e_p99
        expr: histogram_quantile(0.99, sum by (le) (sglang:e2e_request_latency_seconds_bucket))
      - record: sglang:tpot_p99
        expr: histogram_quantile(0.99, sum by (le) (sglang:time_per_output_token_seconds_bucket))

  - name: sglang_slo_alerts
    rules:
      - alert: TTFTp99High
        expr: sglang:ttft_p99 > 10.0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: TTFT p99 exceeds SLO threshold of 10s
      - alert: E2Ep99High
        expr: sglang:e2e_p99 > 55.0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: E2E p99 exceeds SLO threshold of 55s
      - alert: TPOTp99High
        expr: sglang:tpot_p99 > 0.3
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: TPOT p99 exceeds SLO threshold of 0.3s
      - alert: QueueDepthHigh
        expr: sglang:num_queue_reqs > 1000
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: Queue depth exceeds 1000
      - alert: CacheHitRateLow
        expr: sglang:cache_hit_rate < 0.1
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: Cache hit rate below 10 percent
      - alert: ThroughputLow
        expr: sglang:gen_throughput < 50.0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: Generation throughput below 50 tok/s
"""

with open("/app/prometheus/rules/slo_rules.yml", "w") as f:
    f.write(RULES)
print("Created /app/prometheus/rules/slo_rules.yml")

# ============================================================
# Step 3: Parse Prometheus metric snapshots
# ============================================================


def parse_prom_file(filepath):
    """Parse Prometheus exposition format metrics file.

    Aggregates histogram bucket counts across all instances (replicas).
    Gauges are cluster-wide (no instance label) and read directly.
    """
    histograms = {}  # base_name -> {le_str: summed_count}
    gauges = {}      # metric_name -> value

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if "_bucket{" in line:
                m = re.match(
                    r'^(.+)_bucket\{.*?le="([^"]+)".*?\}\s+([\d.eE+\-]+)$',
                    line,
                )
                if m:
                    name = m.group(1)
                    le_str = m.group(2)
                    val = float(m.group(3))
                    if name not in histograms:
                        histograms[name] = {}
                    histograms[name][le_str] = histograms[name].get(le_str, 0.0) + val
            elif "_sum{" in line or "_count{" in line:
                continue
            else:
                m = re.match(
                    r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\{.*?\}\s+([\d.eE+\-]+)$',
                    line,
                )
                if m:
                    gauges[m.group(1)] = float(m.group(2))

    # Convert aggregated histogram dicts to lists of (le_str, count) tuples
    hist_tuples = {}
    for name, le_counts in histograms.items():
        hist_tuples[name] = list(le_counts.items())

    return hist_tuples, gauges


def histogram_quantile(quantile, bucket_data):
    """Compute quantile from cumulative histogram buckets.

    Implements the standard Prometheus histogram_quantile algorithm:
    linear interpolation within the bucket where the target rank falls.
    """
    finite = sorted(
        [(float(le), count) for le, count in bucket_data if le != "+Inf"],
        key=lambda x: x[0],
    )
    inf_entries = [count for le, count in bucket_data if le == "+Inf"]
    total = inf_entries[0] if inf_entries else finite[-1][1]

    rank = quantile * total
    prev_bound = 0.0
    prev_count = 0.0

    for bound, count in finite:
        if count >= rank:
            in_bucket = count - prev_count
            if in_bucket == 0:
                return prev_bound
            return prev_bound + (bound - prev_bound) * (rank - prev_count) / in_bucket
        prev_bound = bound
        prev_count = count

    # Rank falls in +Inf bucket: return last finite upper bound
    return finite[-1][0] if finite else 0.0


# ============================================================
# Step 4: Compute SLO compliance report
# ============================================================

with open("/app/slo_config.json") as f:
    slo_config = json.load(f)

metric_files = sorted(glob.glob("/app/metrics/snapshot_*.prom"))
snapshots = []

for filepath in metric_files:
    filename = os.path.basename(filepath)
    histograms, gauges = parse_prom_file(filepath)

    values = {
        "ttft_p99": histogram_quantile(
            0.99, histograms["sglang:time_to_first_token_seconds"]
        ),
        "e2e_p99": histogram_quantile(
            0.99, histograms["sglang:e2e_request_latency_seconds"]
        ),
        "tpot_p99": histogram_quantile(
            0.99, histograms["sglang:time_per_output_token_seconds"]
        ),
        "queue_depth": gauges["sglang:num_queue_reqs"],
        "cache_hit_rate": gauges["sglang:cache_hit_rate"],
        "gen_throughput": gauges["sglang:gen_throughput"],
    }

    violations = []
    for slo_name, slo_def in slo_config["slos"].items():
        val = values[slo_name]
        op = slo_def["operator"]
        thr = slo_def["threshold"]
        if op == "<" and not (val < thr):
            violations.append(slo_name)
        elif op == ">" and not (val > thr):
            violations.append(slo_name)

    snapshots.append(
        {
            "file": filename,
            **values,
            "slo_violations": violations,
            "compliant": len(violations) == 0,
        }
    )

max_viol_pct = slo_config["error_budget"]["max_violation_pct"]
error_budget = {"max_violation_pct": max_viol_pct}
all_within = True

for slo_name in slo_config["slos"]:
    n_violations = sum(1 for s in snapshots if slo_name in s["slo_violations"])
    viol_pct = (n_violations / len(snapshots)) * 100
    within = viol_pct <= max_viol_pct
    error_budget[slo_name] = {"violation_pct": viol_pct, "within_budget": within}
    if not within:
        all_within = False

report = {
    "snapshots": snapshots,
    "error_budget": error_budget,
    "overall_healthy": all_within,
}

with open("/app/report.json", "w") as f:
    json.dump(report, f, indent=2)
print("Report written to /app/report.json")
