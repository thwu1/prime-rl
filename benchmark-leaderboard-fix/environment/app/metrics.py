"""Statistical metrics for benchmark evaluation."""
from math import comb, sqrt


def compute_pass_at_k(n: int, c: int, k: int) -> float:
    """Compute pass@k metric.

    Args:
        n: total number of runs
        c: number of successful runs
        k: k value for pass@k

    Returns:
        pass@k value between 0 and 1
    """
    if n <= 0 or k <= 0:
        return 0.0
    if c < 0:
        c = 0
    if c > n:
        c = n
    if k > n:
        return 1.0 if c > 0 else 0.0
    p = c / n
    return 1.0 - (1.0 - p) ** k


def compute_sem(successes: int, total: int) -> float:
    """Compute Standard Error of the Mean for binary outcomes.

    Args:
        successes: number of successful outcomes
        total: total number of outcomes

    Returns:
        SEM value
    """
    if total <= 1:
        return 0.0
    p = successes / total
    return sqrt(p * (1.0 - p) / total)


def compute_cost_per_problem(runs, pricing):
    """Compute average cost per problem from run-level token data.

    Args:
        runs: list of run dicts with input_tokens, cached_tokens, output_tokens
        pricing: dict with input_per_mtok, cached_input_per_mtok, output_per_mtok

    Returns:
        average cost per problem in dollars
    """
    if not runs:
        return 0.0

    total_cost = 0.0
    for run in runs:
        input_tokens = run["input_tokens"]
        output_tokens = run["output_tokens"]
        cost = (input_tokens * pricing["input_per_mtok"] / 1_000_000 +
                output_tokens * pricing["output_per_mtok"] / 1_000_000)
        total_cost += cost

    return total_cost / len(runs)
