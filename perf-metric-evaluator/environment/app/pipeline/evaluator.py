"""Evaluation logic for benchmark results.

Processes benchmark data, evaluates model attempts against human baselines,
and builds leaderboard entries with OPT@K metrics.
"""
import json
from pipeline.metrics import relative_speedup, opt_metric, opt_at_k
from pipeline.hack_detector import detect_hack


def evaluate_attempt(human_times, attempt):
    """Evaluate a single model attempt against human baseline."""
    model_times = attempt["times"]
    correct = attempt["correct"]
    speedup = relative_speedup(human_times, model_times)
    patch = attempt.get("patch", "")
    is_hack = detect_hack(patch)
    return {
        "speedup": round(speedup, 4),
        "correct": correct,
        "is_hack": is_hack,
    }


def build_leaderboard(data_path):
    """Build leaderboard from benchmark data file."""
    with open(data_path) as f:
        data = json.load(f)

    tasks = {t["task_id"]: t for t in data["tasks"]}
    model_results = data["model_results"]
    p = data["config"]["p_threshold"]
    max_k = data["config"]["max_k"]

    # Evaluate all attempts
    details = {}
    for task_id in sorted(tasks.keys()):
        task = tasks[task_id]
        details[task_id] = {}
        human_times = task["human_times"]

        for model_id in sorted(model_results.keys()):
            model_data = model_results[model_id]
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
        regular = {}
        hack_adj = {}
        num_hacks = 0
        for task_id in all_tasks:
            if task_id in details and model_id in details[task_id]:
                attempts = details[task_id][model_id]
                regular[task_id] = [(a["speedup"], a["correct"]) for a in attempts]
                hack_adj[task_id] = [
                    (a["speedup"], a["correct"]) for a in attempts if not a["is_hack"]
                ]
                num_hacks += sum(1 for a in attempts if a["is_hack"])
            else:
                regular[task_id] = []
                hack_adj[task_id] = []

        entry = {
            "model": model_id,
            "opt_at_1": round(opt_at_k(regular, p, 1), 4),
            "opt_at_2": round(opt_at_k(regular, p, min(max_k, 2)), 4),
            "hack_adjusted_opt_at_1": round(opt_at_k(hack_adj, p, 1), 4),
            "hack_adjusted_opt_at_2": round(opt_at_k(hack_adj, p, min(max_k, 2)), 4),
            "num_hacks": num_hacks,
        }
        leaderboard.append(entry)

    return leaderboard, details
