"""Statistical metrics for benchmark evaluation."""
import math


def resolved_rate_per_run(run_results, task_ids):
    """Compute fraction of tasks resolved in a single run."""
    resolved = 0
    present = 0
    for tid in task_ids:
        if tid in run_results:
            present += 1
            if run_results[tid]:
                resolved += 1
    if present == 0:
        return 0.0
    return resolved / present


def compute_resolved_rate(runs, task_ids):
    """Compute mean resolved rate across all runs."""
    rates = [resolved_rate_per_run(run, task_ids) for run in runs]
    return sum(rates) / len(rates)


def compute_sem(runs, task_ids):
    """Compute standard error of the mean of resolved rates."""
    rates = [resolved_rate_per_run(run, task_ids) for run in runs]
    mean = sum(rates) / len(rates)
    n = len(rates)
    variance = sum((r - mean) ** 2 for r in rates) / n
    return math.sqrt(variance / n)


def compute_pass_at_k(runs, task_ids, k):
    """Compute pass@k metric."""
    n = len(runs)
    if k > n:
        raise ValueError(f"k={k} exceeds number of runs n={n}")

    pass_k_per_task = []
    for tid in task_ids:
        c = sum(1 for run in runs if run.get(tid, False))
        pass_k = 1.0 - (1.0 - c / n) ** k
        pass_k_per_task.append(pass_k)

    return sum(pass_k_per_task) / len(pass_k_per_task)
