#!/usr/bin/env python3
"""SGLang Prometheus metrics SLO compliance analyzer.

Parses Prometheus exposition format metric snapshots with multi-instance
histogram metrics. Aggregates bucket counts across replicas, then computes
p99 percentiles via the Prometheus histogram_quantile algorithm. Evaluates
SLO compliance with error budget tracking.
"""

import json
import math
import os
import re
import sys


# ---------------------------------------------------------------------------
# Prometheus exposition format parser
# ---------------------------------------------------------------------------

def parse_prom(text):
    """Parse Prometheus exposition format into {metric_name: [entries]}."""
    metrics = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(
            r'^([a-zA-Z_:][a-zA-Z0-9_:]*)'
            r'(?:\{([^}]*)\})?'
            r'\s+'
            r'([^\s]+)',
            line,
        )
        if not m:
            continue
        name = m.group(1)
        labels_raw = m.group(2) or ""
        val = float(m.group(3))

        labels = {}
        if labels_raw:
            for lm in re.finditer(r'(\w+)="([^"]*)"', labels_raw):
                labels[lm.group(1)] = lm.group(2)

        metrics.setdefault(name, []).append({"labels": labels, "value": val})
    return metrics


# ---------------------------------------------------------------------------
# Histogram quantile with multi-instance aggregation
# ---------------------------------------------------------------------------

def extract_and_aggregate_buckets(metrics, base_name):
    """Return sorted [(upper_bound, aggregated_cumulative_count)].

    Sums bucket counts across all instances at each le boundary.
    """
    key = f"{base_name}_bucket"
    if key not in metrics:
        return []

    le_sums = {}
    for entry in metrics[key]:
        le = entry["labels"].get("le", "")
        ub = float("inf") if le == "+Inf" else float(le)
        le_sums[ub] = le_sums.get(ub, 0.0) + entry["value"]

    buckets = sorted(le_sums.items(), key=lambda x: x[0] if not math.isinf(x[0]) else 1e308)
    return buckets


def histogram_quantile(q, buckets):
    """Compute quantile from Prometheus cumulative histogram buckets."""
    if not buckets:
        return float("nan")

    total = 0.0
    for ub, cnt in buckets:
        if math.isinf(ub):
            total = cnt
            break
    if total == 0:
        return float("nan")

    rank = q * total

    for i, (ub, cum) in enumerate(buckets):
        if cum >= rank:
            if math.isinf(ub):
                for j in range(len(buckets) - 1, -1, -1):
                    if not math.isinf(buckets[j][0]):
                        return buckets[j][0]
                return float("nan")

            if i > 0:
                prev_ub = buckets[i - 1][0]
                prev_cum = buckets[i - 1][1]
            else:
                prev_ub = 0.0
                prev_cum = 0.0

            count_in = cum - prev_cum
            rank_in = rank - prev_cum
            if count_in == 0:
                return prev_ub
            return prev_ub + (ub - prev_ub) * rank_in / count_in

    return float("nan")


# ---------------------------------------------------------------------------
# Gauge extraction
# ---------------------------------------------------------------------------

def gauge_value(metrics, name):
    """Extract a single gauge value (cluster-wide, no instance label)."""
    entries = metrics.get(name, [])
    return entries[0]["value"] if entries else float("nan")


# ---------------------------------------------------------------------------
# SLO evaluation
# ---------------------------------------------------------------------------

def eval_slo(value, threshold, op):
    if op == "<":
        return value < threshold
    if op == ">":
        return value > threshold
    if op == "<=":
        return value <= threshold
    if op == ">=":
        return value >= threshold
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open("/app/slo_config.json") as f:
        cfg = json.load(f)

    slos = cfg["slos"]
    max_viol_pct = cfg["error_budget"]["max_violation_pct"]

    mdir = "/app/metrics"
    files = sorted(fn for fn in os.listdir(mdir) if fn.endswith(".prom"))

    snapshots = []
    for fn in files:
        with open(os.path.join(mdir, fn)) as f:
            metrics = parse_prom(f.read())

        ttft_p99 = histogram_quantile(
            0.99,
            extract_and_aggregate_buckets(metrics, "sglang:time_to_first_token_seconds"),
        )
        e2e_p99 = histogram_quantile(
            0.99,
            extract_and_aggregate_buckets(metrics, "sglang:e2e_request_latency_seconds"),
        )
        tpot_p99 = histogram_quantile(
            0.99,
            extract_and_aggregate_buckets(metrics, "sglang:time_per_output_token_seconds"),
        )

        q_depth = gauge_value(metrics, "sglang:num_queue_reqs")
        cache_hr = gauge_value(metrics, "sglang:cache_hit_rate")
        gen_tp = gauge_value(metrics, "sglang:gen_throughput")

        val_map = {
            "ttft_p99": ttft_p99,
            "e2e_p99": e2e_p99,
            "tpot_p99": tpot_p99,
            "queue_depth": q_depth,
            "cache_hit_rate": cache_hr,
            "gen_throughput": gen_tp,
        }

        violations = []
        for slo_name, slo_def in slos.items():
            v = val_map.get(slo_name)
            if v is not None and not math.isnan(v):
                if not eval_slo(v, slo_def["threshold"], slo_def["operator"]):
                    violations.append(slo_name)

        snapshots.append({
            "file": fn,
            "ttft_p99": ttft_p99,
            "e2e_p99": e2e_p99,
            "tpot_p99": tpot_p99,
            "queue_depth": q_depth,
            "cache_hit_rate": cache_hr,
            "gen_throughput": gen_tp,
            "slo_violations": violations,
            "compliant": len(violations) == 0,
        })

    n = len(snapshots)
    error_budget = {"max_violation_pct": max_viol_pct}
    all_ok = True
    for slo_name in slos:
        cnt = sum(1 for s in snapshots if slo_name in s["slo_violations"])
        pct = (cnt / n) * 100.0
        within = pct <= max_viol_pct
        error_budget[slo_name] = {"violation_pct": pct, "within_budget": within}
        if not within:
            all_ok = False

    report = {
        "snapshots": snapshots,
        "error_budget": error_budget,
        "overall_healthy": all_ok,
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to /app/report.json")


if __name__ == "__main__":
    main()
