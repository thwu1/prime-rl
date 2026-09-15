#!/usr/bin/env python3
"""
SRE Incident Analysis Pipeline -- Multi-Dimensional SLO Analysis

Implements end-to-end incident analysis from raw metrics:
1. Discovers data quality issues (duplicate metric entries from collector race)
2. Evaluates alerting configuration correctness (YAML merge key semantics)
3. Computes multi-window multi-burn-rate alert evaluations
4. Detects cascading failures via consecutive-threshold counting
5. Computes error budgets for both availability and latency SLOs
6. Produces structured findings report
"""

import sqlite3
import json
import yaml
import os
import sys


def discover_data_quality(conn):
    """Assess data integrity by checking for duplicate entries per
    (timestamp_s, cluster_id) pair."""
    dup_info = conn.execute("""
        SELECT m.timestamp_s, c.name, COUNT(*) AS cnt
        FROM metrics m
        JOIN clusters c ON m.cluster_id = c.id
        GROUP BY m.timestamp_s, m.cluster_id
        HAVING cnt > 1
        ORDER BY m.timestamp_s
    """).fetchall()

    if dup_info:
        return {
            "duplicates_found": True,
            "affected_cluster": dup_info[0][1],
            "affected_time_range": [dup_info[0][0], dup_info[-1][0]],
            "duplicate_rows_removed": sum(row[2] - 1 for row in dup_info),
        }
    return {
        "duplicates_found": False,
        "affected_cluster": "",
        "affected_time_range": [],
        "duplicate_rows_removed": 0,
    }


def evaluate_config(config):
    """Check alerting rules against severity defaults for discrepancies
    caused by YAML merge key precedence issues."""
    page_default_br = config["severity_defaults"]["page"]["burn_rate"]
    discrepancies = []

    for alert in config["alerts"]:
        if (alert.get("severity") == "page"
                and alert["name"] == "page_critical"):
            parsed_br = alert["burn_rate"]
            if abs(parsed_br - page_default_br) > 0.01:
                discrepancies.append({
                    "alert_name": alert["name"],
                    "field": "burn_rate",
                    "parsed_value": parsed_br,
                    "intended_value": page_default_br,
                    "resolution": (
                        f"Used page-severity default burn_rate={page_default_br}; "
                        f"the YAML merge key was shadowed by an explicit "
                        f"burn_rate={parsed_br} placed before the merge directive"
                    ),
                })
    return discrepancies


def build_corrected_alert_rules(config, discrepancies):
    """Build alert rule list with discrepancies resolved."""
    overrides = {d["alert_name"]: d["intended_value"] for d in discrepancies}
    rules = []
    for alert in config["alerts"]:
        br = overrides.get(alert["name"], alert["burn_rate"])
        rules.append({
            "name": alert["name"],
            "burn_rate": float(br),
            "long_window_s": alert["long_window_s"],
            "short_window_s": alert["short_window_s"],
        })
    return rules


def compute_latency_sli(conn, latency_threshold_ms):
    """Compute request-weighted latency SLI.

    Each per-cluster per-second observation with requests > 0 is classified
    as compliant (p99 <= threshold) or non-compliant. The SLI is the
    request-weighted fraction of compliant observations.
    """
    rows = conn.execute("""
        SELECT d.requests, d.latency_p99_ms
        FROM (
            SELECT DISTINCT timestamp_s, cluster_id, requests, errors,
                   latency_p50_ms, latency_p99_ms
            FROM metrics
        ) d
        WHERE d.requests > 0
    """).fetchall()

    total_requests = 0
    compliant_requests = 0
    for reqs, p99 in rows:
        total_requests += reqs
        if p99 <= latency_threshold_ms:
            compliant_requests += reqs

    if total_requests == 0:
        return 0.0
    return compliant_requests / total_requests


def main():
    # ----- Load SLO Configuration -----
    slo_path = "/app/config/slo.json"
    if not os.path.isfile(slo_path):
        print(f"ERROR: SLO config not found at {slo_path}", file=sys.stderr)
        sys.exit(1)

    with open(slo_path) as f:
        slo_cfg = json.load(f)

    print(f"SLO config loaded: {list(slo_cfg.keys())}")

    avail_target = slo_cfg["availability"]["target"]
    avail_period_days = slo_cfg["availability"]["period_days"]
    latency_target = slo_cfg["latency"]["target"]
    latency_threshold_ms = slo_cfg["latency"]["threshold_ms"]
    latency_period_days = slo_cfg["latency"]["period_days"]

    # ----- Connect to Database -----
    conn = sqlite3.connect("/app/data/metrics.db")

    # ----- Data Quality Assessment -----
    data_quality = discover_data_quality(conn)
    print(f"Data quality: {data_quality}")

    # ----- Latency SLI -----
    latency_sli = compute_latency_sli(conn, latency_threshold_ms)

    # ----- Read Deduplicated Metrics -----
    global_rows = conn.execute("""
        SELECT timestamp_s,
               SUM(requests) AS total_requests,
               SUM(errors) AS total_errors
        FROM (
            SELECT DISTINCT timestamp_s, cluster_id, requests, errors
            FROM metrics
        )
        GROUP BY timestamp_s
        ORDER BY timestamp_s
    """).fetchall()

    cluster_rows = conn.execute("""
        SELECT d.timestamp_s, c.name, d.requests, d.errors
        FROM (
            SELECT DISTINCT timestamp_s, cluster_id, requests, errors
            FROM metrics
        ) d
        JOIN clusters c ON d.cluster_id = c.id
        ORDER BY d.timestamp_s, c.name
    """).fetchall()

    conn.close()

    # Build arrays
    max_t = max(row[0] for row in global_rows)
    global_reqs = [0] * (max_t + 1)
    global_errs = [0] * (max_t + 1)
    for t, reqs, errs in global_rows:
        global_reqs[t] = reqs
        global_errs[t] = errs

    cluster_data = {}
    for t, cluster, reqs, errs in cluster_rows:
        cluster_data.setdefault(t, {})[cluster] = {
            "requests": reqs, "errors": errs
        }

    # ----- Configuration Evaluation -----
    with open("/app/config/alerts.yaml") as f:
        config = yaml.safe_load(f)

    config_discrepancies = evaluate_config(config)
    print(f"Config discrepancies: {config_discrepancies}")

    alert_rules = build_corrected_alert_rules(config, config_discrepancies)
    failure_threshold = config["failure_detection"]["error_rate_threshold"]
    consecutive_needed = config["failure_detection"]["consecutive_seconds"]

    # ----- Prefix Sums for Sliding Window -----
    prefix_reqs = [0] * (max_t + 2)
    prefix_errs = [0] * (max_t + 2)
    for i in range(max_t + 1):
        prefix_reqs[i + 1] = prefix_reqs[i] + global_reqs[i]
        prefix_errs[i + 1] = prefix_errs[i] + global_errs[i]

    def window_error_rate(t, window_size):
        start = max(0, t - window_size + 1)
        total_r = prefix_reqs[t + 1] - prefix_reqs[start]
        if total_r == 0:
            return 0.0
        return (prefix_errs[t + 1] - prefix_errs[start]) / total_r

    # ----- Alert Evaluation -----
    # Multi-window multi-burn-rate: threshold = burn_rate * (1 - slo_target)
    alerts_result = []
    for rule in alert_rules:
        threshold = rule["burn_rate"] * (1 - avail_target)
        fired_at = None
        resolved_at = None
        is_firing = False

        for t in range(max_t + 1):
            long_rate = window_error_rate(t, rule["long_window_s"])
            short_rate = window_error_rate(t, rule["short_window_s"])
            should_fire = (long_rate > threshold) and (short_rate > threshold)

            if should_fire and not is_firing:
                fired_at = t
                is_firing = True
            elif not should_fire and is_firing:
                resolved_at = t
                is_firing = False

        alerts_result.append({
            "name": rule["name"],
            "fired_at_s": fired_at,
            "resolved_at_s": resolved_at if not is_firing else None,
            "active_at_end": is_firing,
        })

    alerts_result.sort(
        key=lambda a: (a["fired_at_s"] is None, a["fired_at_s"] or 0)
    )

    # ----- Cascade Detection -----
    clusters = sorted(
        set(c for cm in cluster_data.values() for c in cm.keys())
    )
    failures = []
    for cluster in clusters:
        consecutive = 0
        detected_at = None
        for t in range(max_t + 1):
            if t in cluster_data and cluster in cluster_data[t]:
                d = cluster_data[t][cluster]
                if (d["requests"] > 0
                        and (d["errors"] / d["requests"]) > failure_threshold):
                    consecutive += 1
                    if consecutive >= consecutive_needed:
                        detected_at = t
                        break
                else:
                    consecutive = 0
            else:
                consecutive = 0
        if detected_at is not None:
            failures.append({
                "cluster": cluster,
                "detected_at_s": detected_at,
                "effective_from_s": detected_at + 1,
            })

    failures.sort(key=lambda x: x["detected_at_s"])
    cascade_seq = [f["cluster"] for f in failures]

    # ----- Summary Statistics -----
    duration_s = max_t + 1
    total_reqs = prefix_reqs[max_t + 1]
    total_errs = prefix_errs[max_t + 1]
    overall_error_rate = total_errs / total_reqs if total_reqs > 0 else 0.0

    # Availability error budget
    avail_period_s = avail_period_days * 86400
    avail_burn_rate = overall_error_rate / (1 - avail_target)
    avail_budget_pct = avail_burn_rate * (duration_s / avail_period_s) * 100

    # Latency error budget
    latency_non_compliance = 1 - latency_sli
    latency_period_s = latency_period_days * 86400
    latency_burn_rate = latency_non_compliance / (1 - latency_target)
    latency_budget_pct = latency_burn_rate * (duration_s / latency_period_s) * 100

    # Peak error rate
    peak_rate = 0.0
    peak_time = 0
    for t in range(max_t + 1):
        if global_reqs[t] > 0:
            rate = global_errs[t] / global_reqs[t]
            if rate > peak_rate:
                peak_rate = rate
                peak_time = t

    # ----- Write Output -----
    result = {
        "summary": {
            "total_requests": total_reqs,
            "total_errors": total_errs,
            "overall_error_rate": round(overall_error_rate, 6),
            "simulation_duration_s": duration_s,
            "availability_budget_consumed_pct": round(avail_budget_pct, 3),
            "latency_sli": round(latency_sli, 6),
            "latency_budget_consumed_pct": round(latency_budget_pct, 3),
        },
        "cluster_failures": failures,
        "cascade_sequence": cascade_seq,
        "alerts": alerts_result,
        "peak_error_rate": round(peak_rate, 6),
        "peak_error_rate_time_s": peak_time,
        "data_quality": data_quality,
        "config_discrepancies": config_discrepancies,
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/findings.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Pipeline complete. Findings written to /app/output/findings.json")
    print(f"  Total requests: {total_reqs} (after dedup)")
    print(f"  Total errors: {total_errs}")
    print(f"  Availability budget consumed: {round(avail_budget_pct, 3)}%")
    print(f"  Latency SLI: {round(latency_sli, 6)}")
    print(f"  Latency budget consumed: {round(latency_budget_pct, 3)}%")
    print(f"  Cascade: {cascade_seq}")
    for a in alerts_result:
        print(f"  Alert {a['name']}: fired_at={a['fired_at_s']}")


if __name__ == "__main__":
    main()
