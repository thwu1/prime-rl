#!/usr/bin/env python3
"""Assemble the final incident analysis report from pipeline outputs."""
import json
import os

METRICS_PATH = "/tmp/pipeline/metrics.json"
ALERTS_PATH = "/tmp/pipeline/alerts.json"
CASCADE_PATH = "/tmp/pipeline/cascade.json"
SLO_CONFIG = "/app/config/slo.json"
OUTPUT_PATH = "/app/output/report.json"

SECONDS_PER_DAY = 24 * 60


def main():
    with open(METRICS_PATH) as f:
        metrics = json.load(f)
    with open(ALERTS_PATH) as f:
        alerts = json.load(f)
    with open(CASCADE_PATH) as f:
        cascade = json.load(f)
    with open(SLO_CONFIG) as f:
        slo = json.load(f)

    max_t = metrics["max_timestamp"]
    duration_s = max_t + 1

    # Compute aggregate totals
    total_reqs = sum(d["requests"] for d in metrics["global"].values())
    total_errs = sum(d["errors"] for d in metrics["global"].values())
    overall_error_rate = total_errs / total_reqs if total_reqs > 0 else 0.0

    # Error budget consumption
    slo_target = slo["target"]
    slo_period_days = slo["period_days"]
    burn_rate = overall_error_rate / (1 - slo_target)
    slo_window_s = slo_period_days * SECONDS_PER_DAY
    error_budget_pct = burn_rate * (duration_s / slo_window_s) * 100

    # Peak per-second error rate
    peak_rate = 0.0
    peak_time = 0
    for t_str, data in metrics["global"].items():
        t = int(t_str)
        if data["requests"] > 0:
            rate = data["errors"] / data["requests"]
            if rate > peak_rate:
                peak_rate = rate
                peak_time = t

    report = {
        "summary": {
            "total_requests": total_reqs,
            "total_errors": total_errs,
            "overall_error_rate": round(overall_error_rate, 6),
            "simulation_duration_s": duration_s,
            "error_budget_consumed_pct": round(error_budget_pct, 3),
        },
        "cluster_failures": cascade["cluster_failures"],
        "cascade_sequence": cascade["cascade_sequence"],
        "alerts": alerts,
        "peak_error_rate": round(peak_rate, 6),
        "peak_error_rate_time_s": peak_time,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {OUTPUT_PATH}")
    print(f"  Total requests: {total_reqs}, errors: {total_errs}")
    print(f"  Error budget consumed: {round(error_budget_pct, 3)}%")


if __name__ == "__main__":
    main()
