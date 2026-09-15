"""Main evaluation pipeline orchestration."""
import json
import os
from metrics import compute_pass_at_k, compute_sem, compute_cost_per_problem
from contamination import is_contaminated, get_decontaminated_tasks
from leaderboard import rank_models, compute_unique_solves, generate_leaderboard


def load_data(data_dir):
    """Load evaluation data from JSON files."""
    with open(os.path.join(data_dir, "models.json")) as f:
        models = json.load(f)
    with open(os.path.join(data_dir, "tasks.json")) as f:
        tasks = json.load(f)
    with open(os.path.join(data_dir, "evaluations.json")) as f:
        evaluations = json.load(f)
    return models, tasks, evaluations


def evaluate_model(model, tasks, evaluations, k=5):
    """Evaluate a single model across all tasks.

    Args:
        model: model metadata dict
        tasks: list of task metadata dicts
        evaluations: list of evaluation dicts
        k: k value for pass@k metric

    Returns:
        dict with evaluation results
    """
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

    decontaminated_tasks = get_decontaminated_tasks(tasks, model["release_date"])
    contaminated_count = len(tasks) - len(decontaminated_tasks)

    decontaminated_evals = [
        e for e in model_evals if e["task_id"] in decontaminated_tasks
    ]
    decontam_runs = []
    for eval_entry in decontaminated_evals:
        decontam_runs.extend(eval_entry["runs"])

    decontam_total = len(decontam_runs)
    decontam_successes = sum(1 for r in decontam_runs if r["resolved"])
    decontam_rate = (
        decontam_successes / decontam_total if decontam_total > 0 else 0
    )

    return {
        "model_id": model_id,
        "resolved_rate": resolved_rate,
        "sem": sem,
        "pass_at_k": avg_pass_at_k,
        "cost_per_problem": cost,
        "contaminated_count": contaminated_count,
        "decontaminated_resolved_rate": decontam_rate,
        "total_runs": total_runs,
        "total_successes": total_successes,
    }


def run_pipeline(data_dir, output_path, k=5):
    """Run the full evaluation pipeline.

    Args:
        data_dir: path to data directory
        output_path: path to write leaderboard JSON
        k: k value for pass@k metric
    """
    models, tasks, evaluations = load_data(data_dir)

    model_results = []
    for model in models:
        result = evaluate_model(model, tasks, evaluations, k)
        model_results.append(result)

    unique_solve_counts = compute_unique_solves(evaluations, models)
    for result in model_results:
        result["unique_solves"] = unique_solve_counts.get(result["model_id"], 0)

    ranked = rank_models(model_results)
    leaderboard_json = generate_leaderboard(ranked)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(leaderboard_json)

    return ranked


if __name__ == "__main__":
    run_pipeline("/app/data", "/app/output/leaderboard.json")
