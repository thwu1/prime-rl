#!/usr/bin/env python3
"""Prometheus metrics analysis engine for LLM serving observability.

Parses Prometheus exposition format scrapes, computes histogram percentiles
via histogram_quantile, counter rates with reset detection, and SLO burn-rate
evaluation.
"""


import json
import math
import os
import re
from collections import defaultdict


def parse_prometheus_text(text):
    """Parse Prometheus exposition text format into structured metrics.

    Returns dict:
      {metric_base_name: {"type": str, "samples": [{"name": str, "labels": dict, "value": float}]}}
    """
    metrics = {}
    current_type = {}

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        if line.startswith("# HELP"):
            continue

        if line.startswith("# TYPE"):
            parts = line.split()
            if len(parts) >= 4:
                metric_name = parts[2]
                metric_type = parts[3]
                current_type[metric_name] = metric_type
                if metric_name not in metrics:
                    metrics[metric_name] = {"type": metric_type, "samples": []}
            continue

        if line.startswith("#"):
            continue

        # Parse sample line: metric_name{labels} value
        match = re.match(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\{([^}]*)\}\s+(.+)$', line)
        if not match:
            # Try without labels
            match = re.match(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+(.+)$', line)
            if match:
                name = match.group(1)
                value = float(match.group(2))
                labels = {}
            else:
                continue
        else:
            name = match.group(1)
            labels_str = match.group(2)
            value = float(match.group(3))
            labels = parse_labels(labels_str)

        # Find the base metric name for histograms
        base_name = name
        for suffix in ("_bucket", "_sum", "_count"):
            if name.endswith(suffix):
                base_name = name[: -len(suffix)]
                break

        if base_name not in metrics:
            # Infer type from current_type or default
            mtype = current_type.get(base_name, "untyped")
            metrics[base_name] = {"type": mtype, "samples": []}

        metrics[base_name]["samples"].append(
            {"name": name, "labels": labels, "value": value}
        )

    return metrics


def parse_labels(labels_str):
    """Parse label string like 'le="0.5",model_name="foo"' into dict."""
    labels = {}
    # Match key="value" pairs
    for match in re.finditer(r'(\w+)="([^"]*)"', labels_str):
        labels[match.group(1)] = match.group(2)
    return labels


def extract_histogram_buckets(metric_data):
    """Extract sorted bucket boundaries and cumulative counts from histogram samples."""
    buckets = []
    count = 0

    for sample in metric_data["samples"]:
        if sample["name"].endswith("_bucket"):
            le = sample["labels"].get("le", "")
            if le == "+Inf":
                le_val = float("inf")
            else:
                le_val = float(le)
            buckets.append((le_val, sample["value"]))
        elif sample["name"].endswith("_count"):
            count = sample["value"]

    # Sort by bucket boundary
    buckets.sort(key=lambda x: x[0])
    return buckets, count


def histogram_quantile(quantile, buckets):
    """Compute a quantile from histogram buckets using linear interpolation.

    This implements the standard Prometheus histogram_quantile algorithm.

    Args:
        quantile: float in [0, 1]
        buckets: list of (upper_bound, cumulative_count) sorted by upper_bound

    Returns:
        Estimated quantile value
    """
    if not buckets:
        return float("nan")

    # The total count is the +Inf bucket count (last bucket)
    total = buckets[-1][1]
    if total == 0:
        return float("nan")

    target = quantile * total

    # Find the bucket where cumulative count first >= target
    for i, (upper, cum_count) in enumerate(buckets):
        if cum_count >= target:
            # Found the target bucket
            if math.isinf(upper):
                # Quantile falls in +Inf bucket - return last finite upper bound
                for j in range(len(buckets) - 2, -1, -1):
                    if not math.isinf(buckets[j][0]):
                        return buckets[j][0]
                return float("nan")

            if i == 0:
                # First bucket: interpolate from 0
                lower_bound = 0.0
                lower_count = 0.0
            else:
                lower_bound = buckets[i - 1][0]
                lower_count = buckets[i - 1][1]

            # Linear interpolation within the bucket
            bucket_width = upper - lower_bound
            bucket_count = cum_count - lower_count

            if bucket_count == 0:
                return lower_bound

            fraction = (target - lower_count) / bucket_count
            return lower_bound + bucket_width * fraction

    # Should not reach here if +Inf bucket is present
    return buckets[-1][0]


def compute_delta_buckets(buckets_prev, buckets_curr):
    """Compute delta between two sets of cumulative histogram buckets.

    Both must have the same bucket boundaries.
    Returns list of (upper_bound, delta_cumulative_count).
    """
    delta = []
    prev_dict = {ub: count for ub, count in buckets_prev}
    for ub, count in buckets_curr:
        prev_count = prev_dict.get(ub, 0)
        delta.append((ub, count - prev_count))
    return delta


def compute_counter_rate(prev_value, curr_value, time_delta):
    """Compute per-second counter rate, handling counter resets.

    If current value < previous value, a counter reset is assumed.
    """
    if curr_value < prev_value:
        # Counter reset: treat new value as increase since reset
        return curr_value / time_delta
    else:
        return (curr_value - prev_value) / time_delta


def main():
    # Load scrape metadata
    with open("/app/scrape_metadata.json") as f:
        metadata = json.load(f)

    scrapes_info = metadata["scrapes"]

    # Load SLO config
    with open("/app/slo_config.json") as f:
        slo_config = json.load(f)

    # Parse all scrapes
    parsed_scrapes = []
    for scrape in scrapes_info:
        filepath = os.path.join("/app/scrapes", scrape["file"])
        with open(filepath) as f:
            text = f.read()
        parsed = parse_prometheus_text(text)
        parsed_scrapes.append({
            "timestamp": scrape["timestamp_unix"],
            "metrics": parsed,
        })

    # Identify metric types
    counter_metrics = []
    histogram_metrics = []
    for name, data in parsed_scrapes[0]["metrics"].items():
        if data["type"] == "counter":
            counter_metrics.append(name)
        elif data["type"] == "histogram":
            histogram_metrics.append(name)

    report = {
        "counter_rates": {},
        "interval_percentiles": {},
        "slo_evaluation": {},
    }

    # --- Counter rates ---
    for metric_name in counter_metrics:
        rates = {}
        for i in range(len(parsed_scrapes) - 1):
            prev_scrape = parsed_scrapes[i]
            curr_scrape = parsed_scrapes[i + 1]

            time_delta = curr_scrape["timestamp"] - prev_scrape["timestamp"]

            # Get counter value (first sample for this metric)
            prev_val = prev_scrape["metrics"][metric_name]["samples"][0]["value"]
            curr_val = curr_scrape["metrics"][metric_name]["samples"][0]["value"]

            rate = compute_counter_rate(prev_val, curr_val, time_delta)
            rates[f"interval_{i}_{i+1}"] = rate

        report["counter_rates"][metric_name] = rates

    # --- Interval percentiles ---
    for metric_name in histogram_metrics:
        interval_pcts = {}

        for i in range(len(parsed_scrapes) - 1):
            prev_scrape = parsed_scrapes[i]
            curr_scrape = parsed_scrapes[i + 1]

            buckets_prev, _ = extract_histogram_buckets(
                prev_scrape["metrics"][metric_name]
            )
            buckets_curr, _ = extract_histogram_buckets(
                curr_scrape["metrics"][metric_name]
            )

            delta_buckets = compute_delta_buckets(buckets_prev, buckets_curr)

            p50 = histogram_quantile(0.50, delta_buckets)
            p95 = histogram_quantile(0.95, delta_buckets)
            p99 = histogram_quantile(0.99, delta_buckets)

            interval_pcts[f"interval_{i}_{i+1}"] = {
                "p50": p50,
                "p95": p95,
                "p99": p99,
            }

        report["interval_percentiles"][metric_name] = interval_pcts

    # --- SLO evaluation ---
    alert_rules = slo_config["alert_rules"]
    for slo in slo_config["slos"]:
        slo_name = slo["name"]
        metric_name = slo["metric"]
        percentile = slo["percentile"]
        threshold = slo["threshold"]
        target = slo["target"]

        interval_results = []
        for i in range(len(parsed_scrapes) - 1):
            interval_key = f"interval_{i}_{i+1}"

            # Get the percentile value for this interval
            pct_key = f"p{int(percentile * 100)}"
            pct_value = report["interval_percentiles"][metric_name][interval_key][
                pct_key
            ]

            # Evaluate SLO: less_than comparison
            if slo["comparison"] == "less_than":
                met = pct_value < threshold
            else:
                met = pct_value > threshold

            interval_results.append(met)

        # Compliance ratio
        num_compliant = sum(1 for r in interval_results if r)
        compliance_ratio = num_compliant / len(interval_results)

        # Burn rate
        error_ratio = 1.0 - compliance_ratio
        error_budget = 1.0 - target
        burn_rate = error_ratio / error_budget

        # Alert level
        if burn_rate >= alert_rules["critical"]["burn_rate_threshold"]:
            alert_level = "critical"
        elif burn_rate >= alert_rules["warning"]["burn_rate_threshold"]:
            alert_level = "warning"
        else:
            alert_level = "none"

        report["slo_evaluation"][slo_name] = {
            "interval_results": interval_results,
            "compliance_ratio": compliance_ratio,
            "burn_rate": burn_rate,
            "alert_level": alert_level,
        }

    # Write report
    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
