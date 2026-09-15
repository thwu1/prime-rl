"""Speedup metric computation for benchmark evaluation.

Computes aggregate speedups and relative performance metrics for comparing
model optimization patches against human expert baselines.
"""
import math
from typing import List


def compute_speedup(base_times: List[float], opt_times: List[float]) -> float:
    """Compute aggregate speedup between baseline and optimized code.

    Args:
        base_times: Execution times for baseline code per test case
        opt_times: Execution times for optimized code per test case

    Returns:
        Aggregate speedup factor
    """
    if len(base_times) != len(opt_times):
        raise ValueError("Mismatched number of test cases")

    speedups = []
    for b, o in zip(base_times, opt_times):
        if o == 0:
            speedups.append(float("inf"))
        else:
            speedups.append(b / o)

    finite = [s for s in speedups if math.isfinite(s)]
    if not finite:
        return float("inf")
    if any(s == 0 for s in finite):
        return 0.0

    # Robust aggregation via geometric mean
    log_sum = sum(math.log(s) for s in finite)
    return math.exp(log_sum / len(finite))


def relative_speedup(human_times: List[float], model_times: List[float]) -> float:
    """Compute relative speedup: human / model.

    A value > 1 means the model's optimization runs faster than the human's.

    Args:
        human_times: Execution times after human optimization per test case
        model_times: Execution times after model optimization per test case

    Returns:
        Relative speedup factor
    """
    if len(human_times) != len(model_times):
        raise ValueError("Mismatched number of test cases")

    # Compute per-test relative speedups (human / model)
    speedups = []
    for h, m in zip(human_times, model_times):
        if h == 0 and m == 0:
            speedups.append(1.0)
        elif h == 0:
            speedups.append(0.0)
        elif m == 0:
            speedups.append(float("inf"))
        else:
            speedups.append(m / h)

    finite = [s for s in speedups if math.isfinite(s)]
    if not finite:
        return float("inf")
    if any(s == 0 for s in finite):
        return 0.0

    log_sum = sum(math.log(s) for s in finite)
    return math.exp(log_sum / len(finite))


def opt_metric(speedup: float, correct: bool, p: float = 0.95) -> bool:
    """Check if a single attempt achieves OPT_p.

    Args:
        speedup: Relative speedup of model vs human
        correct: Whether the patch passes correctness tests
        p: Performance threshold

    Returns:
        True if the attempt achieves OPT_p
    """
    return speedup >= p and correct


def opt_at_k(task_results, p=0.95, k=1):
    """Compute OPT_p@K metric across tasks.

    Fraction of tasks where attempts meet the performance threshold.

    Args:
        task_results: Dict mapping task_id -> list of (speedup, correct) tuples
        p: Performance threshold
        k: Number of attempts to consider

    Returns:
        Fraction of tasks solved
    """
    if not task_results:
        return 0.0

    n_tasks = len(task_results)
    n_success = 0
    for task_id, attempts in task_results.items():
        first_k = attempts[:k]
        # Task succeeds if all of the first K attempts meet the threshold
        if first_k and all(opt_metric(s, c, p) for s, c in first_k):
            n_success += 1

    return n_success / n_tasks
