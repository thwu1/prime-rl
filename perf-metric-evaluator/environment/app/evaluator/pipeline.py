"""End-to-end evaluation pipeline.

Loads benchmark data, computes metrics, runs hack detection,
and generates leaderboard rankings.
"""
import json
import os
from typing import Dict, Any

from evaluator.metrics import relative_speedup, opt_metric, opt_at_k
from evaluator.hack_detector import detect_hack


def load_data(data_path: str) -> Dict[str, Any]:
    """Load benchmark results from JSON."""
    with open(data_path) as f:
        return json.load(f)


def evaluate_attempt(human_times, attempt):
    """Evaluate a single model attempt against human baseline."""
    model_times = attempt["times"]
    correct = attempt["correct"]
    speedup = relative_speedup(human_times, model_times)
    is_hack = detect_hack(attempt.get("patch", ""))
    return {
        "speedup": round(speedup, 4),
        "correct": correct,
        "is_hack": is_hack,
    }


def run_pipeline(data_path: str, output_path: str):
    """Run the full evaluation pipeline and write leaderboard."""
    data = load_data(data_path)
    tasks = {t["task_id"]: t for t in data["tasks"]}
    model_results = data["model_results"]
    config = data["config"]
    p = config["p_threshold"]
    max_k = config["max_k"]

    # Evaluate all attempts
    details = {}
    for task_id, task in tasks.items():
        details[task_id] = {}
        human_times = task["human_times"]

        for model_id, model_data in model_results.items():
            if task_id not in model_data:
                continue
            attempts = model_data[task_id]["attempts"]
            attempt_results = []
            for i, attempt in enumerate(attempts):
                result = evaluate_attempt(human_times, attempt)
                result["attempt"] = i
                result["opt"] = opt_metric(result["speedup"], result["correct"], p)
                attempt_results.append(result)
            details[task_id][model_id] = attempt_results

    # Compute OPT@K for each model
    all_models = sorted(model_results.keys())
    all_tasks = sorted(tasks.keys())

    leaderboard = []
    for model_id in all_models:
        regular_task_results = {}
        hack_adj_task_results = {}
        num_hacks = 0

        for task_id in all_tasks:
            if task_id in details and model_id in details[task_id]:
                attempts = details[task_id][model_id]
                regular_task_results[task_id] = [
                    (a["speedup"], a["correct"]) for a in attempts
                ]
                hack_adj_task_results[task_id] = [
                    (a["speedup"], a["correct"])
                    for a in attempts
                    if not a["is_hack"]
                ]
                num_hacks += sum(1 for a in attempts if a["is_hack"])
            else:
                regular_task_results[task_id] = []
                hack_adj_task_results[task_id] = []

        entry = {
            "model": model_id,
            "opt_at_1": round(opt_at_k(regular_task_results, p, 1), 4),
            "opt_at_2": round(opt_at_k(regular_task_results, p, min(max_k, 2)), 4),
            "hack_adjusted_opt_at_1": round(
                opt_at_k(hack_adj_task_results, p, 1), 4
            ),
            "hack_adjusted_opt_at_2": round(
                opt_at_k(hack_adj_task_results, p, min(max_k, 2)), 4
            ),
            "num_hacks": num_hacks,
        }
        leaderboard.append(entry)

    # Sort by hack-adjusted OPT@2 descending, then by model name for stability
    leaderboard.sort(key=lambda x: (-x["hack_adjusted_opt_at_2"], x["model"]))
    for i, entry in enumerate(leaderboard):
        entry["rank"] = i + 1

    output = {
        "leaderboard": leaderboard,
        "details": details,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    return output
