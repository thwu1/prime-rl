"""Main evaluation pipeline orchestration.

THIS FILE IS READ-ONLY. Do not modify.

Implements a SWE-bench-style evaluation pipeline that:
1. Loads evaluation data from a SQLite database
2. Computes statistical metrics for each model
3. Detects data contamination
4. Ranks models according to configurable criteria
5. Outputs a JSON leaderboard
"""
import json
import os
import sys

sys.path.insert(0, "/app")

import yaml

from pipeline.data_loader import load_from_sqlite
from pipeline.metrics import compute_pass_at_k, compute_sem, compute_cost_per_problem
from pipeline.contamination import is_contaminated, get_clean_task_ids
from pipeline.ranking import rank_models, compute_unique_solves


def run_pipeline(db_path, config_path, output_path):
    """Run the full evaluation pipeline.

    Args:
        db_path: path to SQLite evaluation database
        config_path: path to YAML configuration file
        output_path: path to write leaderboard JSON

    Returns:
        ranked list of model results
    """
    with open(config_path) as f:
        config = yaml.safe_load(f)

    k = config["pipeline"]["k"]

    models, tasks, evaluations = load_from_sqlite(db_path)

    model_results = []
    for model in models:
        model_id = model["model_id"]
        model_evals = [e for e in evaluations if e["model_id"] == model_id]

        all_runs = []
        task_pass_at_k = []
        for eval_entry in model_evals:
            runs = eval_entry["runs"]
            all_runs.extend(runs)
            n = len(runs)
            c = sum(1 for r in runs if r["resolved"])
            task_pass_at_k.append(compute_pass_at_k(n, c, k))

        total_runs = len(all_runs)
        total_successes = sum(1 for r in all_runs if r["resolved"])
        resolved_rate = total_successes / total_runs if total_runs > 0 else 0
        sem = compute_sem(total_successes, total_runs)
        avg_pass_at_k = (
            sum(task_pass_at_k) / len(task_pass_at_k) if task_pass_at_k else 0
        )
        cost = compute_cost_per_problem(all_runs, model["pricing"])

        clean_ids = get_clean_task_ids(tasks, model["release_date"])
        contaminated_count = len(tasks) - len(clean_ids)

        decontam_evals = [e for e in model_evals if e["task_id"] in clean_ids]
        decontam_runs = []
        for e in decontam_evals:
            decontam_runs.extend(e["runs"])
        decontam_total = len(decontam_runs)
        decontam_successes = sum(1 for r in decontam_runs if r["resolved"])
        decontam_rate = (
            decontam_successes / decontam_total if decontam_total > 0 else 0
        )

        model_results.append({
            "model_id": model_id,
            "resolved_rate": resolved_rate,
            "sem": sem,
            "pass_at_k": avg_pass_at_k,
            "cost_per_problem": cost,
            "contaminated_count": contaminated_count,
            "decontaminated_resolved_rate": decontam_rate,
        })

    unique_counts = compute_unique_solves(evaluations, models)
    for result in model_results:
        result["unique_solves"] = unique_counts.get(result["model_id"], 0)

    ranked = rank_models(model_results, config["ranking"])

    leaderboard = []
    for result in ranked:
        leaderboard.append({
            "rank": result["rank"],
            "model_id": result["model_id"],
            "resolved_rate_pct": round(result["resolved_rate"] * 100, 1),
            "sem_pct": round(result["sem"] * 100, 2),
            "pass_at_k_pct": round(result["pass_at_k"] * 100, 1),
            "cost_per_problem": round(result["cost_per_problem"], 4),
            "contaminated_count": result["contaminated_count"],
            "decontaminated_resolved_rate_pct": round(
                result["decontaminated_resolved_rate"] * 100, 1
            ),
            "unique_solves": result["unique_solves"],
        })

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(leaderboard, f, indent=2)

    return ranked


if __name__ == "__main__":
    run_pipeline("/app/eval.db", "/app/config.yaml", "/app/output/leaderboard.json")
