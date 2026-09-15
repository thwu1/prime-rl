#!/usr/bin/env python3

"""
SGLang SLO analyzer — FIXED version.
Reads interval delta data from jq output and computes Prometheus-compatible
histogram percentiles with proper linear interpolation and counter-reset
propagation.
"""

import json
import math
from pathlib import Path


def histogram_quantile(quantile, delta_buckets):
    """Compute a quantile from delta histogram buckets using Prometheus
    linear interpolation algorithm.

    delta_buckets: list of {"upper_bound": float|"+Inf", "delta": float}
    where delta values are cumulative within the interval.
    """
    buckets = []
    for b in delta_buckets:
        ub = float("inf") if b["upper_bound"] == "+Inf" else float(b["upper_bound"])
        buckets.append((ub, b["delta"]))

    if not buckets:
        return float("nan")

    total = buckets[-1][1]
    if total == 0:
        return float("nan")

    rank = quantile * total

    for i, (bound, count) in enumerate(buckets):
        if count >= rank:
            if math.isinf(bound):
                return buckets[i - 1][0] if i > 0 else 0.0

            if i == 0:
                prev_bound, prev_count = 0.0, 0.0
            else:
                prev_bound, prev_count = buckets[i - 1]

            bucket_width = bound - prev_bound
            observations_in_bucket = count - prev_count
            rank_in_bucket = rank - prev_count

            if observations_in_bucket == 0:
                return prev_bound

            return prev_bound + bucket_width * (rank_in_bucket / observations_in_bucket)

    return buckets[-2][0] if len(buckets) > 1 else 0.0


def main():
    intervals_dir = Path("/app/intervals")
    slo_config_path = Path("/app/slo_config.json")
    report_path = Path("/app/report.json")

    with open(slo_config_path) as f:
        slo_config = json.load(f)
    slos = slo_config["slos"]

    interval_files = sorted(intervals_dir.glob("interval_*.json"))

    intervals = []
    violated_set = set()

    hist_metrics = {
        "ttft_p99": ("sglang:time_to_first_token_seconds", 0.99),
        "e2e_p99": ("sglang:e2e_request_latency_seconds", 0.99),
        "tpot_p95": ("sglang:time_per_output_token_seconds", 0.95),
    }

    for ivf in interval_files:
        with open(ivf) as f:
            iv_data = json.load(f)

        duration = iv_data["duration_sec"]

        percentiles = {}
        request_rate = 0.0

        for pname, (metric, quantile) in hist_metrics.items():
            h = iv_data["histogram_deltas"].get(metric, {})
            delta_bkts = h.get("delta_buckets", [])
            percentiles[pname] = histogram_quantile(quantile, delta_bkts)

            if metric == "sglang:time_to_first_token_seconds":
                request_rate = h.get("request_count_delta", 0) / duration

        prompt_delta = iv_data["counter_deltas"].get("sglang:prompt_tokens_total", 0)
        gen_delta = iv_data["counter_deltas"].get("sglang:generation_tokens_total", 0)

        verdicts = {}
        for sname, sdef in slos.items():
            if sdef["type"] == "histogram_percentile":
                val = percentiles.get(sname, float("inf"))
            elif sdef["type"] == "counter_rate":
                val = request_rate
            else:
                continue

            if sdef["comparator"] == "lt":
                ok = val < sdef["threshold"]
            elif sdef["comparator"] == "gte":
                ok = val >= sdef["threshold"]
            else:
                ok = False

            verdicts[sname] = ok
            if not ok:
                violated_set.add(sname)

        intervals.append({
            "start_ts": iv_data["start_ts"],
            "end_ts": iv_data["end_ts"],
            "duration_sec": duration,
            "counter_reset_detected": iv_data["counter_reset_detected"],
            "request_rate_per_sec": request_rate,
            "prompt_token_rate_per_sec": prompt_delta / duration,
            "generation_token_rate_per_sec": gen_delta / duration,
            "percentiles": percentiles,
            "slo_verdicts": verdicts,
        })

    passing = sum(1 for iv in intervals if all(iv["slo_verdicts"].values()))

    report = {
        "intervals": intervals,
        "summary": {
            "total_intervals": len(intervals),
            "intervals_passing_all_slos": passing,
            "intervals_with_violations": len(intervals) - passing,
            "violated_slo_names": sorted(violated_set),
        },
    }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
