"""Performance benchmark metrics computation.

This module computes speedup metrics for evaluating code optimization patches
against human expert baselines.
"""
import math
from typing import List, Dict, Any, Tuple


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

    speedups = [b / o for b, o in zip(base_times, opt_times)]
    # Use geometric mean for robust aggregation
    log_sum = sum(math.log(s) for s in speedups)
    return math.exp(log_sum / len(speedups))


def relative_speedup(human_times: List[float], model_times: List[float]) -> float:
    """Compute relative speedup of model optimization vs human optimization.

    Measures how the model's optimization compares to the human expert's.
    A value > 1 means the model is faster than the human optimization.

    Args:
        human_times: Execution times after human optimization per test case
        model_times: Execution times after model optimization per test case

    Returns:
        Relative speedup factor
    """
    if len(human_times) != len(model_times):
        raise ValueError("Mismatched number of test cases")

    # Compute per-test relative speedups
    speedups = [m / h for m, h in zip(model_times, human_times)]
    log_sum = sum(math.log(s) for s in speedups)
    return math.exp(log_sum / len(speedups))


def opt_metric(speedup: float, correct: bool, p: float = 0.95) -> bool:
    """Determine if an attempt achieves OPT_p.

    Args:
        speedup: Relative speedup of model vs human
        correct: Whether the model's patch passes correctness tests
        p: Performance threshold

    Returns:
        True if the attempt achieves OPT_p
    """
    return speedup >= p and correct


def opt_at_k(
    task_results: Dict[str, List[Tuple[float, bool]]], p: float = 0.95, k: int = 1
) -> float:
    """Compute OPT_p@K metric across tasks.

    Args:
        task_results: Dict mapping task_id -> list of (speedup, correct) tuples
        p: Performance threshold
        k: Number of attempts to consider

    Returns:
        Fraction of tasks where at least one of K attempts achieves OPT_p
    """
    raise NotImplementedError("OPT@K metric computation not yet implemented")
