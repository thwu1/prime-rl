#!/usr/bin/env python3
"""Complete benchmark evaluation pipeline implementation."""
import argparse
import csv
import json
import math
import os
import sqlite3
import sys


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_models(db_path):
    """Load model metadata from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT name, release_date FROM models").fetchall()
    conn.close()
    return [{"name": r["name"], "release_date": r["release_date"]} for r in rows]


def load_tasks(db_path):
    """Load task metadata from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, created_at, repo FROM tasks").fetchall()
    conn.close()
    return [{"id": r["id"], "created_at": r["created_at"], "repo": r["repo"]} for r in rows]


def load_similarity(csv_path):
    """Load code similarity pairs from CSV."""
    pairs = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            pairs.append((
                row["task_a"],
                row["task_b"],
                float(row["jaccard_similarity"]),
            ))
    return pairs


def load_run_results(data_dir, model_name, run_num):
    """Load results for a single run from JSONL."""
    path = os.path.join(data_dir, "runs", model_name, f"run_{run_num}.jsonl")
    results = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            results[entry["instance_id"]] = entry.get("resolved", False)
    return results


def load_all_runs(data_dir, model_name, num_runs=5):
    """Load all runs for a model."""
    return [load_run_results(data_dir, model_name, i) for i in range(1, num_runs + 1)]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def resolved_rate_per_run(run_results, task_ids):
    """Resolved fraction for a single run. Missing entries = failure."""
    resolved = sum(1 for tid in task_ids if run_results.get(tid, False))
    return resolved / len(task_ids)


def compute_resolved_rate(runs, task_ids):
    """Mean resolved rate across runs."""
    rates = [resolved_rate_per_run(r, task_ids) for r in runs]
    return sum(rates) / len(rates)


def compute_sem(runs, task_ids):
    """SEM with Bessel's correction (n-1 denominator)."""
    rates = [resolved_rate_per_run(r, task_ids) for r in runs]
    mean = sum(rates) / len(rates)
    n = len(rates)
    sample_var = sum((r - mean) ** 2 for r in rates) / (n - 1)
    return math.sqrt(sample_var) / math.sqrt(n)


def compute_pass_at_k(runs, task_ids, k):
    """Unbiased pass@k estimator: 1 - C(n-c, k) / C(n, k)."""
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
    """Count contaminated tasks: temporal + one-hop similarity from temporal."""
    # Temporal contamination (strict <, from full task set)
    temporal = set()
    for t in all_tasks:
        if t["created_at"] < model_release_date:
            temporal.add(t["id"])

    # Similarity contamination (one-hop from temporal only)
    sim_contam = set()
    for task_a, task_b, jaccard in similarity_pairs:
        if jaccard >= threshold:
            if task_a in temporal:
                sim_contam.add(task_b)
            if task_b in temporal:
                sim_contam.add(task_a)

    contaminated = temporal | sim_contam

    # Count only tasks in the evaluation set
    eval_ids = {t["id"] for t in eval_tasks}
    return len(contaminated & eval_ids)


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def compute_leaderboard(data_dir, start_date=None, end_date=None):
    db_path = os.path.join(data_dir, "benchmark.db")
    csv_path = os.path.join(data_dir, "similarity.csv")

    models = load_models(db_path)
    all_tasks = load_tasks(db_path)
    similarity_pairs = load_similarity(csv_path)

    # Time-window filtering
    tasks = all_tasks[:]
    if start_date is not None:
        tasks = [t for t in tasks if t["created_at"] >= start_date]
    if end_date is not None:
        tasks = [t for t in tasks if t["created_at"] <= end_date]

    task_ids = [t["id"] for t in tasks]

    # Compute per-model metrics
    rankings = []
    for model in models:
        runs = load_all_runs(data_dir, model["name"])

        rr = compute_resolved_rate(runs, task_ids)
        sem = compute_sem(runs, task_ids)
        p1 = compute_pass_at_k(runs, task_ids, 1)
        p3 = compute_pass_at_k(runs, task_ids, 3)
        p5 = compute_pass_at_k(runs, task_ids, 5)
        nc = compute_contamination(
            tasks, all_tasks, model["release_date"], similarity_pairs
        )

        rankings.append({
            "model": model["name"],
            "resolved_rate": round(rr, 5),
            "sem": round(sem, 5),
            "pass_at_1": round(p1, 5),
            "pass_at_3": round(p3, 5),
            "pass_at_5": round(p5, 5),
            "num_contaminated_tasks": nc,
            "contamination_fraction": round(nc / len(task_ids), 5) if task_ids else 0,
        })

    # Rank by resolved_rate descending
    rankings.sort(key=lambda x: x["resolved_rate"], reverse=True)
    for i, r in enumerate(rankings):
        r["rank"] = i + 1

    # Task difficulty
    difficulties = []
    for tid in task_ids:
        solve_rates = []
        num_solved = 0
        for model in models:
            runs = load_all_runs(data_dir, model["name"])
            c = sum(1 for run in runs if run.get(tid, False))
            solve_rates.append(c / len(runs))
            if c > 0:
                num_solved += 1
        difficulties.append({
            "task_id": tid,
            "mean_solve_rate": round(sum(solve_rates) / len(solve_rates), 5),
            "num_models_solved_at_least_once": num_solved,
        })
    difficulties.sort(key=lambda x: x["mean_solve_rate"])

    return {
        "time_window": {"start": start_date, "end": end_date},
        "num_tasks": len(task_ids),
        "num_runs_per_model": 5,
        "rankings": rankings,
        "task_difficulty": difficulties,
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark Evaluation Pipeline")
    parser.add_argument("--data-dir", default="/app/data")
    parser.add_argument("--output", default="/app/output/leaderboard.json")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    result = compute_leaderboard(
        args.data_dir,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Leaderboard written to {args.output}")


if __name__ == "__main__":
    main()
