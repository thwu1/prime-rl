#!/usr/bin/env python3
"""Stage 2: Transform extracted data with pass@k and contamination.

Reads extracted.json from DuckDB stage, adds:
- pass@k metrics (see spec.md for estimator requirements)
- contamination detection (temporal + similarity)
- task difficulty rankings

Writes scored.json for the jq assembly stage.
"""
import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict


def compute_pass_at_k(successes, attempts, k):
    """Compute pass@k for a single task.

    Args:
        successes: number of successful runs (c)
        attempts: total number of runs (n)
        k: number of trials

    Returns:
        Estimated probability that at least one of k runs succeeds.

    Must use an unbiased estimator appropriate for finite sample sizes.
    Reference: Chen et al. (2021), "Evaluating Large Language Models
    Trained on Code."
    """
    raise NotImplementedError("Implement pass@k estimator")


def compute_contamination(eval_tasks, all_tasks, model_release_date,
                          similarity_pairs, threshold=0.8):
    """Count contaminated tasks for a model.

    Args:
        eval_tasks: list of tasks in the evaluation window
        all_tasks: full list of all tasks (for temporal determination)
        model_release_date: YYYY-MM-DD string
        similarity_pairs: list of (task_a, task_b, jaccard) tuples
        threshold: minimum Jaccard similarity for propagation (default 0.8)

    Returns:
        Integer count of contaminated tasks in eval_tasks.

    Must implement:
    - Temporal contamination with correct date boundary semantics
    - Code similarity propagation (see spec.md for propagation rules)
    """
    raise NotImplementedError("Implement contamination detection")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    args = parser.parse_args()

    with open(args.input) as f:
        extracted = json.load(f)

    csv_path = os.path.join(args.data_dir, "similarity.csv")
    similarity_pairs = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            similarity_pairs.append(
                (row["task_a"], row["task_b"], float(row["jaccard_similarity"]))
            )

    all_tasks = extracted["tasks"]
    models = extracted["models"]
    model_metrics = extracted["model_metrics"]
    task_solve = extracted["task_solve_counts"]
    run_results = extracted["run_results"]
    num_runs = extracted["num_runs_per_model"]

    # Apply time-window filtering
    tasks = all_tasks
    if args.start_date:
        tasks = [t for t in tasks if t["created_at"] >= args.start_date]
    if args.end_date:
        tasks = [t for t in tasks if t["created_at"] <= args.end_date]

    task_ids = [t["id"] for t in tasks]
    task_id_set = set(task_ids)
    num_tasks = len(task_ids)

    # Determine if filtering is active
    filtering = num_tasks != extracted["num_tasks"]

    # Build rankings
    rankings = []
    for model in models:
        name = model["name"]

        if not filtering:
            metrics = model_metrics.get(name, {})
            resolved_rate = metrics.get("resolved_rate", 0)
            sem = metrics.get("sem", 0)
        else:
            # Recompute metrics from run_results for filtered task set
            per_run = defaultdict(list)
            for rr in run_results:
                if rr["model"] == name and rr["task"] in task_id_set:
                    per_run[rr["run"]].append(rr["resolved"])

            rates = []
            for run_name in sorted(per_run.keys()):
                resolved_count = sum(1 for r in per_run[run_name] if r)
                rates.append(resolved_count / num_tasks)

            resolved_rate = sum(rates) / len(rates) if rates else 0
            mean_rate = resolved_rate
            n = len(rates)
            if n > 1:
                sample_var = sum((r - mean_rate) ** 2 for r in rates) / (n - 1)
                sem = math.sqrt(sample_var / n)
            else:
                sem = 0

        # Compute pass@k
        pass_at = {}
        for k in [1, 3, 5]:
            values = []
            for tid in task_ids:
                sc = task_solve.get(name, {}).get(
                    tid, {"successes": 0, "attempts": num_runs}
                )
                values.append(
                    compute_pass_at_k(sc["successes"], sc["attempts"], k)
                )
            pass_at[k] = sum(values) / len(values) if values else 0

        # Compute contamination
        num_contaminated = compute_contamination(
            tasks, tasks, model["release_date"], similarity_pairs
        )

        rankings.append({
            "model": name,
            "resolved_rate": resolved_rate,
            "sem": sem,
            "pass_at_1": pass_at[1],
            "pass_at_3": pass_at[3],
            "pass_at_5": pass_at[5],
            "num_contaminated_tasks": num_contaminated,
        })

    # Compute task difficulty
    task_difficulty = []
    for tid in task_ids:
        solve_rates = []
        num_solved = 0
        for model in models:
            name = model["name"]
            sc = task_solve.get(name, {}).get(
                tid, {"successes": 0, "attempts": num_runs}
            )
            rate = sc["successes"] / sc["attempts"] if sc["attempts"] > 0 else 0
            solve_rates.append(rate)
            if sc["successes"] > 0:
                num_solved += 1
        task_difficulty.append({
            "task_id": tid,
            "mean_solve_rate": (
                sum(solve_rates) / len(solve_rates) if solve_rates else 0
            ),
            "num_models_solved_at_least_once": num_solved,
        })

    scored = {
        "time_window": {
            "start": args.start_date,
            "end": args.end_date,
        },
        "num_tasks": num_tasks,
        "num_runs_per_model": num_runs,
        "rankings": rankings,
        "task_difficulty": task_difficulty,
    }

    with open(args.output, "w") as f:
        json.dump(scored, f)


if __name__ == "__main__":
    main()
