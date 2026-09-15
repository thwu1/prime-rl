#!/usr/bin/env python3
"""Extract per-second metrics from the incident database."""
import sqlite3
import json
import os

DB_PATH = "/app/data/metrics.db"
OUTPUT_DIR = "/tmp/pipeline"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    # Global per-second aggregates
    rows = conn.execute("""
        SELECT timestamp_s,
               SUM(requests) AS total_requests,
               SUM(errors) AS total_errors
        FROM metrics
        GROUP BY timestamp_s
        ORDER BY timestamp_s
    """).fetchall()

    global_metrics = {}
    for t, reqs, errs in rows:
        global_metrics[str(t)] = {"requests": reqs, "errors": errs}

    # Per-cluster per-second aggregates
    rows = conn.execute("""
        SELECT m.timestamp_s,
               c.name AS cluster_name,
               SUM(m.requests) AS requests,
               SUM(m.errors) AS errors
        FROM metrics m
        JOIN clusters c ON m.cluster_id = c.id
        GROUP BY m.timestamp_s, c.name
        ORDER BY m.timestamp_s, c.name
    """).fetchall()

    cluster_metrics = {}
    for t, cluster, reqs, errs in rows:
        key = str(t)
        if key not in cluster_metrics:
            cluster_metrics[key] = {}
        cluster_metrics[key][cluster] = {"requests": reqs, "errors": errs}

    max_t = max(int(k) for k in global_metrics.keys())
    clusters = sorted(set(c for cm in cluster_metrics.values() for c in cm.keys()))

    result = {
        "global": global_metrics,
        "per_cluster": cluster_metrics,
        "max_timestamp": max_t,
        "clusters": clusters,
    }

    with open(os.path.join(OUTPUT_DIR, "metrics.json"), "w") as f:
        json.dump(result, f)

    conn.close()
    total = sum(d["requests"] for d in global_metrics.values())
    print(f"Extracted {len(global_metrics)} timestamps, {len(clusters)} clusters, {total} total requests")


if __name__ == "__main__":
    main()
