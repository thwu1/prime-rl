"""
Analysis script: queries bench.db and produces report.json with per-workload
metrics, optimal shard count recommendation, and crossover analysis.
"""

import sqlite3
import json
import math
import os

OUTPUT_DIR = "/app/output"


def compute_cv(values):
    """Compute coefficient of variation (std_dev / mean)."""
    if not values or len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance) / mean


def main():
    db_path = os.path.join(OUTPUT_DIR, "bench.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Discover workloads and shard counts
    cursor.execute(
        "SELECT DISTINCT workload_name FROM workload_results ORDER BY workload_name"
    )
    workload_names = [row[0] for row in cursor.fetchall()]

    cursor.execute(
        "SELECT DISTINCT num_shards FROM workload_results ORDER BY num_shards"
    )
    shard_counts = [row[0] for row in cursor.fetchall()]

    report = {
        "workloads": {},
        "optimal_shard_count": None,
        "recommendation": "",
        "crossover_analysis": "",
    }

    # Per-shard-count aggregate scores for finding the optimal
    shard_scores = {ns: 0.0 for ns in shard_counts}

    for wl_name in workload_names:
        wl_report = {
            "shard_counts_tested": shard_counts,
            "throughput": {},
            "distribution_cv": {},
            "peak_memory_bytes": {},
        }

        for ns in shard_counts:
            # Throughput
            cursor.execute(
                "SELECT throughput_ops_per_sec FROM workload_results "
                "WHERE workload_name=? AND num_shards=?",
                (wl_name, ns),
            )
            row = cursor.fetchone()
            tp = row[0] if row else 0.0
            wl_report["throughput"][str(ns)] = round(tp, 2)

            # Shard distribution CV
            cursor.execute(
                "SELECT key_count FROM shard_distribution "
                "WHERE workload_name=? AND num_shards=? ORDER BY shard_id",
                (wl_name, ns),
            )
            counts = [row[0] for row in cursor.fetchall()]
            cv = compute_cv(counts)
            wl_report["distribution_cv"][str(ns)] = round(cv, 4)

            # Memory
            cursor.execute(
                "SELECT peak_memory_bytes FROM memory_snapshots "
                "WHERE workload_name=? AND num_shards=?",
                (wl_name, ns),
            )
            row = cursor.fetchone()
            mem = row[0] if row else 0
            wl_report["peak_memory_bytes"][str(ns)] = mem

            # Score: higher throughput and lower CV is better
            balance_factor = 1.0 - min(cv, 1.0)
            shard_scores[ns] += tp * balance_factor

        report["workloads"][wl_name] = wl_report

    # Determine optimal shard count
    if shard_scores:
        optimal = max(shard_scores, key=shard_scores.get)
    else:
        optimal = 1
    report["optimal_shard_count"] = optimal

    # Build recommendation
    total_workloads = len(workload_names)
    report["recommendation"] = (
        f"Based on profiling across {total_workloads} workloads with shard counts "
        f"{shard_counts}, {optimal} shard(s) provides the best balance of throughput "
        f"and distribution uniformity. Higher shard counts reduce per-shard lock "
        f"contention in the left-right epoch tracking but increase memory overhead "
        f"from maintaining duplicate copies per shard and add cross-shard aggregation "
        f"cost for operations like len() and keys()."
    )

    # Build crossover analysis
    crossover_parts = []
    for wl_name in workload_names:
        tps = report["workloads"][wl_name]["throughput"]
        if tps:
            sorted_sc = sorted(tps.keys(), key=int)
            peak_sc = max(sorted_sc, key=lambda s: tps[s])
            crossover_parts.append(
                f"{wl_name}: peak throughput at {peak_sc} shard(s) "
                f"({tps[peak_sc]:.0f} ops/s)"
            )

    report["crossover_analysis"] = (
        "Crossover points where adding shards stops improving throughput: "
        + "; ".join(crossover_parts)
        + ". Beyond the optimal count, the overhead of managing multiple "
        "left-right map instances (doubled memory per shard for the two-copy "
        "pattern, epoch tracking per shard, hash computation for routing) "
        "outweighs the contention reduction. Under the Python GIL, additional "
        "shards primarily help by reducing the critical section duration in "
        "publish() rather than enabling true parallelism."
    )

    # Write report
    report_path = os.path.join(OUTPUT_DIR, "report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    conn.close()
    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
