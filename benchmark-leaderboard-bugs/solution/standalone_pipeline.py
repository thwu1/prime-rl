#!/usr/bin/env python3
"""Benchmark evaluation pipeline — standalone implementation.

Reads model/task metadata from SQLite, run results from Parquet (via DuckDB),
and code-similarity annotations from CSV. Computes resolved rates, SEM (with
Bessel's correction), unbiased pass@k (Chen et al. 2021), and contamination
(temporal + one-hop similarity). Outputs a ranked leaderboard JSON.
"""
import argparse
import csv
import json
import math
import os
import sqlite3

import duckdb


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_models(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT name, release_date FROM models").fetchall()
    conn.close()
    return [{"name": r["name"], "release_date": r["release_date"]} for r in rows]


def load_tasks(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, created_at, repo FROM tasks").fetchall()
    conn.close()
    return [{"id": r["id"], "created_at": r["created_at"], "repo": r["repo"]}
            for r in rows]


def load_similarity(csv_path):
    pairs = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            pairs.append((row["task_a"], row["task_b"],
                          float(row["jaccard_similarity"])))
    return pairs


def load_run_results(data_dir, model_name, run_num):
    """Load per-task resolved status for one run from Parquet via DuckDB."""
    path = os.path.join(data_dir, "runs", f"{model_name}.parquet")
    col = f"r{run_num}"
    conn = duckdb.connect()
    rows = conn.execute(
        f"SELECT instance_id, {col} AS resolved FROM read_parquet('{path}')"
    ).fetchall()
    conn.close()
    results = {}
    for instance_id, resolved in rows:
        # NULL → False (missing/error entry counts as failure)
        results[instance_id] = bool(resolved) if resolved is not None else False
    return results


def load_all_runs(data_dir, model_name, num_runs=5):
    return [load_run_results(data_dir, model_name, i)
            for i in range(1, num_runs + 1)]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_resolved_rate(runs, task_ids):
    """Mean of per-run resolved fractions. Missing entries = failure."""
    rates = []
    for run in runs:
        resolved = sum(1 for tid in task_ids if run.get(tid, False))
        rates.append(resolved / len(task_ids))
    return sum(rates) / len(rates)


def compute_sem(runs, task_ids):
    """SEM with Bessel's correction (sample variance, n-1 denominator)."""
    rates = []
    for run in runs:
        resolved = sum(1 for tid in task_ids if run.get(tid, False))
        rates.append(resolved / len(task_ids))
    mean = sum(rates) / len(rates)
    n = len(rates)
    sample_var = sum((r - mean) ** 2 for r in rates) / (n - 1)
    return math.sqrt(sample_var) / math.sqrt(n)


def compute_pass_at_k(runs, task_ids, k):
    """Unbiased pass@k estimator: 1 - C(n-c, k) / C(n, k).

    From Chen et al. (2021), "Evaluating Large Language Models Trained on Code".
    """
    n = len(runs)
    values = []
    for tid in task_ids:
        c = sum(1 for run in runs if run.get(tid, False))
        if n - c < k:
            values.append(1.0)
        else:
            values.append(1.0 - math.comb(n - c, k) / math.comb(n, k))
    return sum(values) / len(values)


# ---------------------------------------------------------------------------
# Contamination Detection
# ---------------------------------------------------------------------------

def compute_contamination(eval_tasks, all_tasks, model_release_date,
                          similarity_pairs, threshold=0.8):
    """Count contaminated tasks: temporal + one-hop similarity from temporal.

    - Temporal: created_at strictly < model_release_date (same-day = NOT contaminated)
    - Similarity: one-hop from temporally-contaminated tasks only (no transitive)
    - Temporal determination uses full task set, count restricted to eval set
    """
    # Step 1: identify temporally contaminated tasks from the full task set
    temporal = set()
    for t in all_tasks:
        if t["created_at"] < model_release_date:
            temporal.add(t["id"])

    # Step 2: one-hop similarity propagation from temporal sources only
    sim_contam = set()
    for task_a, task_b, jaccard in similarity_pairs:
        if jaccard >= threshold:
            if task_a in temporal:
                sim_contam.add(task_b)
            if task_b in temporal:
                sim_contam.add(task_a)

    contaminated = temporal | sim_contam

    # Step 3: count only tasks in the evaluation set
    eval_ids = {t["id"] for t in eval_tasks}
    return len(contaminated & eval_ids)


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Benchmark Evaluation Pipeline")
    parser.add_argument("--data-dir", default="/app/data")
    parser.add_argument("--output", default="/app/output/leaderboard.json")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    args = parser.parse_args()

    db_path = os.path.join(args.data_dir, "benchmark.db")
    csv_path = os.path.join(args.data_dir, "similarity.csv")

    models = load_models(db_path)
    all_tasks = load_tasks(db_path)
    similarity_pairs = load_similarity(csv_path)

    # Time-window filtering
    tasks = all_tasks[:]
    if args.start_date:
        tasks = [t for t in tasks if t["created_at"] >= args.start_date]
    if args.end_date:
        tasks = [t for t in tasks if t["created_at"] <= args.end_date]

    task_ids = [t["id"] for t in tasks]
    num_tasks = len(task_ids)

    # Pre-load all runs for efficiency
    all_runs = {}
    for model in models:
        all_runs[model["name"]] = load_all_runs(args.data_dir, model["name"])

    # Build per-model rankings
    rankings = []
    for model in models:
        name = model["name"]
        runs = all_runs[name]

        rr = compute_resolved_rate(runs, task_ids)
        sem = compute_sem(runs, task_ids)
        p1 = compute_pass_at_k(runs, task_ids, 1)
        p3 = compute_pass_at_k(runs, task_ids, 3)
        p5 = compute_pass_at_k(runs, task_ids, 5)
        nc = compute_contamination(tasks, all_tasks, model["release_date"],
                                   similarity_pairs)

        rankings.append({
            "model": name,
            "resolved_rate": round(rr, 5),
            "sem": round(sem, 5),
            "pass_at_1": round(p1, 5),
            "pass_at_3": round(p3, 5),
            "pass_at_5": round(p5, 5),
            "num_contaminated_tasks": nc,
            "contamination_fraction": (round(nc / num_tasks, 5)
                                       if num_tasks else 0),
        })

    # Sort by resolved_rate descending, assign ranks
    rankings.sort(key=lambda x: x["resolved_rate"], reverse=True)
    for i, r in enumerate(rankings):
        r["rank"] = i + 1

    # Compute task difficulty (sorted ascending by mean_solve_rate)
    task_difficulty = []
    for tid in task_ids:
        solve_rates = []
        num_solved = 0
        for model in models:
            runs = all_runs[model["name"]]
            c = sum(1 for run in runs if run.get(tid, False))
            solve_rates.append(c / len(runs))
            if c > 0:
                num_solved += 1
        task_difficulty.append({
            "task_id": tid,
            "mean_solve_rate": round(sum(solve_rates) / len(solve_rates), 5),
            "num_models_solved_at_least_once": num_solved,
        })
    task_difficulty.sort(key=lambda x: x["mean_solve_rate"])

    result = {
        "time_window": {"start": args.start_date, "end": args.end_date},
        "num_tasks": num_tasks,
        "num_runs_per_model": 5,
        "rankings": rankings,
        "task_difficulty": task_difficulty,
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Leaderboard written to {args.output}")


if __name__ == "__main__":
    main()
