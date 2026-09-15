#!/usr/bin/env python3
"""Evaluate multi-window multi-burn-rate alerting rules against extracted metrics."""
import json
import yaml
import os

METRICS_PATH = "/tmp/pipeline/metrics.json"
ALERTS_CONFIG = "/app/config/alerts.yaml"
OUTPUT_DIR = "/tmp/pipeline"


def main():
    with open(METRICS_PATH) as f:
        metrics = json.load(f)
    with open(ALERTS_CONFIG) as f:
        config = yaml.safe_load(f)

    slo_target = config["slo"]["target"]
    max_t = metrics["max_timestamp"]

    # Build arrays for prefix-sum based sliding window computation
    global_reqs = [0] * (max_t + 1)
    global_errs = [0] * (max_t + 1)
    for t_str, data in metrics["global"].items():
        t = int(t_str)
        global_reqs[t] = data["requests"]
        global_errs[t] = data["errors"]

    # Prefix sums for O(1) range queries
    prefix_reqs = [0] * (max_t + 2)
    prefix_errs = [0] * (max_t + 2)
    for i in range(max_t + 1):
        prefix_reqs[i + 1] = prefix_reqs[i] + global_reqs[i]
        prefix_errs[i + 1] = prefix_errs[i] + global_errs[i]

    def window_error_rate(t, window_size):
        """Compute error rate over a sliding window [max(0, t-W+1), t]."""
        start = max(0, t - window_size + 1)
        total_reqs = prefix_reqs[t + 1] - prefix_reqs[start]
        if total_reqs == 0:
            return 0.0
        total_errs = prefix_errs[t + 1] - prefix_errs[start]
        return total_errs / total_reqs

    alerts_result = []
    for rule in config["alerts"]:
        name = rule["name"]
        burn_rate = float(rule["burn_rate"])
        long_w = rule["long_window_s"]
        short_w = rule["short_window_s"]
        threshold = burn_rate * (1 - slo_target)

        fired_at = None
        resolved_at = None
        is_firing = False

        for t in range(max_t + 1):
            long_rate = window_error_rate(t, long_w)
            short_rate = window_error_rate(t, short_w)
            should_fire = (long_rate > threshold) and (short_rate > threshold)

            if should_fire and not is_firing:
                fired_at = t
                is_firing = True
            elif not should_fire and is_firing:
                resolved_at = t
                is_firing = False

        alerts_result.append({
            "name": name,
            "fired_at_s": fired_at,
            "resolved_at_s": resolved_at if not is_firing else None,
            "active_at_end": is_firing,
        })

    # Sort by fired_at_s ascending, nulls last
    alerts_result.sort(key=lambda a: (a["fired_at_s"] is None, a["fired_at_s"] or 0))

    with open(os.path.join(OUTPUT_DIR, "alerts.json"), "w") as f:
        json.dump(alerts_result, f, indent=2)

    fired_names = [a["name"] for a in alerts_result if a["fired_at_s"] is not None]
    print(f"Evaluated {len(alerts_result)} rules, {len(fired_names)} fired: {fired_names}")


if __name__ == "__main__":
    main()
