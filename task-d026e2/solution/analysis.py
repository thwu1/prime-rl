"""
Generalization analysis module.

Classifies held-out evaluation outcomes into generalization quadrants
and computes aggregate statistics including conditional correctness.
"""
import statistics


def classify_generalization(orig_correct, opt_correct):
    """
    Classify the held-out outcome into one of four generalization quadrants.

    Returns one of:
        "both_pass"       — orig correct, opt correct
        "opt_regression"  — orig correct, opt failed
        "both_fail"       — both failed
        "opt_improvement" — orig failed, opt correct
    """
    if orig_correct and opt_correct:
        return "both_pass"
    if orig_correct and not opt_correct:
        return "opt_regression"
    if not orig_correct and not opt_correct:
        return "both_fail"
    return "opt_improvement"


def _stats(values):
    """Compute mean, median, std for a list of numbers."""
    if not values:
        return {"mean": 0.0, "median": 0.0, "std": 0.0}
    mean = sum(values) / len(values)
    median = statistics.median(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "mean": round(mean, 4),
        "median": round(median, 4),
        "std": round(std, 4),
    }


def compute_summary(task_results):
    """
    Compute aggregate generalization statistics from per-task results.

    Each element of task_results should be a dict with keys:
        task_name, generalization_status, orig_heldout_pass_correctness,
        opt_pass_correctness, heldout_speedup, original_run_speedup,
        heldout_score, original_run_score

    Returns a dict with:
        total_tasks, quadrant_counts, conditional_correctness,
        heldout_speedup_stats, original_run_speedup_stats,
        generalization_gap, per_task
    """
    total = len(task_results)

    # Quadrant counts
    quadrants = {"both_pass": 0, "opt_regression": 0, "both_fail": 0, "opt_improvement": 0}
    for r in task_results:
        status = r.get("generalization_status", "both_fail")
        quadrants[status] = quadrants.get(status, 0) + 1

    # Conditional correctness: P(opt correct | orig correct)
    orig_correct_tasks = [r for r in task_results if r["orig_heldout_pass_correctness"]]
    n_orig_correct = len(orig_correct_tasks)
    n_opt_correct_given_orig = sum(1 for r in orig_correct_tasks if r["opt_pass_correctness"])
    conditional_correctness_pct = (
        round(n_opt_correct_given_orig / n_orig_correct * 100, 1)
        if n_orig_correct > 0 else 0.0
    )

    # Speedup stats (only for both_pass tasks with positive speedup)
    both_pass = [r for r in task_results if r["generalization_status"] == "both_pass"]
    heldout_speedups = [r["heldout_speedup"] for r in both_pass if r["heldout_speedup"] > 0]
    orig_run_speedups = [r["original_run_speedup"] for r in both_pass if r["original_run_speedup"] > 0]

    heldout_stats = _stats(heldout_speedups)
    orig_stats = _stats(orig_run_speedups)

    # Generalization gap
    gap = {
        "correctness_retention_pct": conditional_correctness_pct,
        "speedup_mean_delta": round(heldout_stats["mean"] - orig_stats["mean"], 4),
    }

    # Per-task details
    per_task = []
    for r in task_results:
        per_task.append({
            "task_name": r["task_name"],
            "generalization_status": r["generalization_status"],
            "orig_heldout_correct": r["orig_heldout_pass_correctness"],
            "opt_heldout_correct": r["opt_pass_correctness"],
            "heldout_speedup": round(r.get("heldout_speedup", 0.0), 4),
            "original_run_speedup": round(r.get("original_run_speedup", 0.0), 4),
            "heldout_score": round(r.get("heldout_score", 0.0), 2),
            "original_run_score": round(r.get("original_run_score", 0.0), 2),
        })

    return {
        "total_tasks": total,
        "quadrant_counts": quadrants,
        "conditional_correctness": {
            "orig_correct_count": n_orig_correct,
            "opt_also_correct_count": n_opt_correct_given_orig,
            "rate_pct": conditional_correctness_pct,
        },
        "heldout_speedup_stats": heldout_stats,
        "original_run_speedup_stats": orig_stats,
        "generalization_gap": gap,
        "per_task": per_task,
    }
