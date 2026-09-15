#!/usr/bin/env python3
"""Correct COCO-style performance analysis pipeline with comparative analysis.

Reads data from the corrected SQLite database and computes ERT, ECDF,
algorithm rankings, scaling exponents, VBS ERT, algorithm selection,
and performance profiles following the COCO methodology.
"""

import json
import math
import os
import sqlite3

# ---------------------------------------------------------------------------
# Load experimental metadata and data from SQLite
# ---------------------------------------------------------------------------
DATA_DIR = "/app/raw_data"
DB_PATH = "/app/benchmark.db"

with open(os.path.join(DATA_DIR, "metadata.json")) as f:
    meta = json.load(f)

ALGORITHMS = meta["algorithms"]
FUNCTIONS = meta["functions"]
DIMENSIONS = meta["dimensions"]
TARGETS = meta["targets"]
FUNCTION_GROUPS = meta["function_groups"]
BUDGETS = [100, 500, 1000, 5000, 10000, 50000, 100000, 500000]
PERF_THRESHOLDS = [1.0, 1.5, 2.0, 5.0, 10.0]

# Load all runs from SQLite (no instance filter — use ALL instances)
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

all_runs: dict[str, list[dict]] = {}
for algo in ALGORITHMS:
    cursor = conn.execute(
        "SELECT r.id, r.function_id, r.dimension, r.instance, r.budget "
        "FROM runs r WHERE r.algorithm = ? "
        "ORDER BY r.function_id, r.dimension, r.instance",
        (algo,)
    )
    runs = []
    for row in cursor:
        tcursor = conn.execute(
            "SELECT target, evals FROM targets_reached WHERE run_id = ?",
            (row["id"],)
        )
        targets = {t["target"]: t["evals"] for t in tcursor}
        runs.append({
            "function_id": row["function_id"],
            "dimension": row["dimension"],
            "instance": row["instance"],
            "budget": row["budget"],
            "targets_reached": targets,
        })
    all_runs[algo] = runs

conn.close()


def get_runs(algo: str, func: int, dim: int) -> list[dict]:
    """Return all runs for a given (algorithm, function, dimension) tuple."""
    return [r for r in all_runs[algo]
            if r["function_id"] == func and r["dimension"] == dim]


# ---------------------------------------------------------------------------
# 1. ERT (Expected Running Time) with simulated restarts
# ---------------------------------------------------------------------------
ert_results: dict[str, float | None] = {}

for algo in ALGORITHMS:
    for func in FUNCTIONS:
        for dim in DIMENSIONS:
            runs = get_runs(algo, func, dim)
            for target in TARGETS:
                key = f"{algo}_f{func}_d{dim}_t{target}"
                total_cost = 0
                n_success = 0
                for run in runs:
                    if target in run["targets_reached"]:
                        total_cost += run["targets_reached"][target]
                        n_success += 1
                    else:
                        total_cost += run["budget"]
                if n_success == 0:
                    ert_results[key] = None
                else:
                    ert_results[key] = total_cost / n_success

# ---------------------------------------------------------------------------
# 2. ECDF (Empirical CDF of runtimes)
# ---------------------------------------------------------------------------
ecdf_results: dict[str, float] = {}

for algo in ALGORITHMS:
    for dim in DIMENSIONS:
        for budget_threshold in BUDGETS:
            total = 0
            solved = 0
            for func in FUNCTIONS:
                for run in get_runs(algo, func, dim):
                    for target in TARGETS:
                        total += 1
                        if (target in run["targets_reached"]
                                and run["targets_reached"][target]
                                <= budget_threshold):
                            solved += 1
            ecdf_results[f"{algo}_d{dim}_b{budget_threshold}"] = (
                solved / total if total > 0 else 0.0
            )

# ---------------------------------------------------------------------------
# 3. Algorithm rankings per function group
# ---------------------------------------------------------------------------
rankings: dict[str, list[str]] = {}

for group_name, group_funcs in FUNCTION_GROUPS.items():
    algo_geo_mean: dict[str, float] = {}
    for algo in ALGORITHMS:
        log_erts: list[float] = []
        for func in group_funcs:
            for dim in DIMENSIONS:
                key = f"{algo}_f{func}_d{dim}_t0.01"
                ert_val = ert_results[key]
                if ert_val is None:
                    log_erts.append(math.log(2 * 10000 * dim))
                else:
                    log_erts.append(math.log(ert_val))
        algo_geo_mean[algo] = math.exp(sum(log_erts) / len(log_erts))
    rankings[group_name] = sorted(
        ALGORITHMS, key=lambda a: (algo_geo_mean[a], a)
    )

# ---------------------------------------------------------------------------
# 4. Scaling exponents (log-log regression of ERT vs dimension)
# ---------------------------------------------------------------------------
scaling_exponents: dict[str, float | None] = {}

for algo in ALGORITHMS:
    for func in FUNCTIONS:
        log_dims: list[float] = []
        log_erts: list[float] = []
        for dim in DIMENSIONS:
            key = f"{algo}_f{func}_d{dim}_t1e-08"
            ert_val = ert_results[key]
            if ert_val is not None:
                log_dims.append(math.log(dim))
                log_erts.append(math.log(ert_val))

        skey = f"{algo}_f{func}"
        if len(log_dims) < 2:
            scaling_exponents[skey] = None
        else:
            n = len(log_dims)
            x_mean = sum(log_dims) / n
            y_mean = sum(log_erts) / n
            numerator = sum(
                (x - x_mean) * (y - y_mean)
                for x, y in zip(log_dims, log_erts)
            )
            denominator = sum((x - x_mean) ** 2 for x in log_dims)
            if denominator == 0:
                scaling_exponents[skey] = None
            else:
                scaling_exponents[skey] = numerator / denominator

# ---------------------------------------------------------------------------
# 5. Virtual Best Solver (VBS) ERT — oracle lower bound
# ---------------------------------------------------------------------------
vbs_ert: dict[str, float | None] = {}

for func in FUNCTIONS:
    for dim in DIMENSIONS:
        for target in TARGETS:
            key = f"f{func}_d{dim}_t{target}"
            best = None
            for algo in ALGORITHMS:
                algo_key = f"{algo}_f{func}_d{dim}_t{target}"
                ert_val = ert_results[algo_key]
                if ert_val is not None:
                    if best is None or ert_val < best:
                        best = ert_val
            vbs_ert[key] = best

# ---------------------------------------------------------------------------
# 6. Algorithm selection — which algorithm achieves VBS ERT
# ---------------------------------------------------------------------------
algorithm_selection: dict[str, str | None] = {}

for func in FUNCTIONS:
    for dim in DIMENSIONS:
        for target in TARGETS:
            key = f"f{func}_d{dim}_t{target}"
            best_ert = None
            best_algo = None
            for algo in sorted(ALGORITHMS):  # alphabetical tie-breaking
                algo_key = f"{algo}_f{func}_d{dim}_t{target}"
                ert_val = ert_results[algo_key]
                if ert_val is not None:
                    if best_ert is None or ert_val < best_ert:
                        best_ert = ert_val
                        best_algo = algo
            algorithm_selection[key] = best_algo

# ---------------------------------------------------------------------------
# 7. Performance profile (Dolan-More methodology)
# ---------------------------------------------------------------------------
performance_profile: dict[str, float] = {}

for algo in ALGORITHMS:
    for tau in PERF_THRESHOLDS:
        total = 0
        within = 0
        for func in FUNCTIONS:
            for dim in DIMENSIONS:
                for target in TARGETS:
                    vbs_key = f"f{func}_d{dim}_t{target}"
                    vbs_val = vbs_ert[vbs_key]
                    if vbs_val is not None:
                        total += 1
                        algo_key = f"{algo}_f{func}_d{dim}_t{target}"
                        ert_val = ert_results[algo_key]
                        if ert_val is not None and ert_val <= tau * vbs_val:
                            within += 1
        performance_profile[f"{algo}_tau{tau}"] = (
            within / total if total > 0 else 0.0
        )

# ---------------------------------------------------------------------------
# Write results
# ---------------------------------------------------------------------------
output = {
    "ert": ert_results,
    "ecdf": ecdf_results,
    "rankings": rankings,
    "scaling_exponents": scaling_exponents,
    "vbs_ert": vbs_ert,
    "algorithm_selection": algorithm_selection,
    "performance_profile": performance_profile,
}

with open("/app/results.json", "w") as f:
    json.dump(output, f, indent=2)

print("Results written to /app/results.json")
