#!/usr/bin/env python3

"""
SGLang SLO burn-rate alert evaluator.
Reads interval delta data from jq output and computes:
- Prometheus-compatible histogram percentiles (linear interpolation)
- Per-interval SLO verdicts
- Severity classification (nominal / degraded / critical)
- Error-budget burn-rate analysis
"""

import json
import math
from pathlib import Path


def histogram_quantile(quantile, delta_buckets):
    """Compute a quantile from delta histogram buckets using the Prometheus
    histogram_quantile algorithm with linear interpolation.

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


def classify_severity(percentiles, verdicts, slo_config):
    """Classify interval severity based on SLO verdicts and violation magnitude.

    - nominal: all SLOs pass
    - critical: any failing histogram_percentile SLO has value >= 2x threshold
    - degraded: some SLOs fail but none reach critical threshold
    """
    if all(verdicts.values()):
        return "nominal"

    slos = slo_config["slos"]
    for sname, sdef in slos.items():
        if sdef["type"] != "histogram_percentile":
            continue
        if verdicts.get(sname, True):
            continue
        measured = percentiles.get(sname, 0.0)
        threshold = sdef["threshold"]
        if measured >= 2.0 * threshold:
            return "critical"

    return "degraded"


def compute_burn_rates(intervals, slo_config):
    """Compute error-budget burn rates for each SLO.

    burn_rate = (fraction_of_intervals_in_violation) / (1 - target_availability)
    """
    error_budget = slo_config["error_budget"]
    target_avail = error_budget["target_availability"]
    max_error_rate = 1.0 - target_avail

    slo_names = list(slo_config["slos"].keys())
    total = len(intervals)

    per_slo_rates = {}
    for sname in slo_names:
        failed_count = sum(
            1 for iv in intervals
            if not iv["slo_verdicts"].get(sname, True)
        )
        observed_error_rate = failed_count / total if total > 0 else 0.0
        per_slo_rates[sname] = observed_error_rate / max_error_rate

    overall = max(per_slo_rates.values()) if per_slo_rates else 0.0

    observation_window = sum(iv["duration_sec"] for iv in intervals)

    return {
        "observation_window_seconds": observation_window,
        "per_slo_burn_rates": per_slo_rates,
        "overall_burn_rate": overall,
    }


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

        severity = classify_severity(percentiles, verdicts, slo_config)

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
            "severity": severity,
        })

    passing = sum(1 for iv in intervals if all(iv["slo_verdicts"].values()))
    error_budget = compute_burn_rates(intervals, slo_config)

    report = {
        "intervals": intervals,
        "summary": {
            "total_intervals": len(intervals),
            "intervals_passing_all_slos": passing,
            "intervals_with_violations": len(intervals) - passing,
            "violated_slo_names": sorted(violated_set),
            "error_budget": error_budget,
        },
    }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
