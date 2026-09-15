"""Fix all bugs in the benchmark evaluation pipeline."""

# Fix 1: metrics.py - correct pass@k formula and SEM and cost computation
metrics_code = '''\
"""Statistical metrics for benchmark evaluation."""
from math import comb, sqrt


def compute_pass_at_k(n: int, c: int, k: int) -> float:
    """Compute pass@k metric using the unbiased combinatorial estimator.

    pass@k = 1 - C(n-c, k) / C(n, k)

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
    denominator = comb(n, k)
    if denominator == 0:
        return 1.0 if c > 0 else 0.0
    return 1.0 - comb(n - c, k) / denominator


def compute_sem(successes: int, total: int) -> float:
    """Compute Standard Error of the Mean for binary outcomes.

    Uses Bessel\'s correction: SEM = sqrt(p*(1-p)/(n-1))

    Args:
        successes: number of successful outcomes
        total: total number of outcomes

    Returns:
        SEM value
    """
    if total <= 1:
        return 0.0
    p = successes / total
    return sqrt(p * (1.0 - p) / (total - 1))


def compute_cost_per_problem(runs, pricing):
    """Compute average cost per problem from run-level token data.

    Accounts for cached token discount:
    cost = (input - cached) * input_price + cached * cached_price + output * output_price

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
        cached_tokens = run["cached_tokens"]
        output_tokens = run["output_tokens"]
        uncached_tokens = input_tokens - cached_tokens
        cost = (uncached_tokens * pricing["input_per_mtok"] / 1_000_000 +
                cached_tokens * pricing["cached_input_per_mtok"] / 1_000_000 +
                output_tokens * pricing["output_per_mtok"] / 1_000_000)
        total_cost += cost

    return total_cost / len(runs)
'''

# Fix 2: contamination.py - correct comparison direction
contamination_code = '''\
"""Contamination detection for benchmark evaluation."""
from datetime import datetime


def parse_date(date_str: str) -> datetime:
    """Parse a date string in YYYY-MM-DD format."""
    return datetime.strptime(date_str, "%Y-%m-%d")


def is_contaminated(task_created_at: str, model_release_date: str) -> bool:
    """Check if a task-model pair is potentially contaminated.

    A task is potentially contaminated for a model if the task was created
    strictly before the model was released, since the task data could have
    appeared in the model\'s training corpus.

    Args:
        task_created_at: task creation date (YYYY-MM-DD)
        model_release_date: model release date (YYYY-MM-DD)

    Returns:
        True if potentially contaminated
    """
    task_date = parse_date(task_created_at)
    release_date = parse_date(model_release_date)
    return task_date < release_date


def get_decontaminated_tasks(tasks, model_release_date: str):
    """Get list of task IDs that are not contaminated for a given model.

    Args:
        tasks: list of task dicts with \'task_id\' and \'created_at\'
        model_release_date: model release date (YYYY-MM-DD)

    Returns:
        list of non-contaminated task IDs
    """
    return [
        t["task_id"] for t in tasks
        if not is_contaminated(t["created_at"], model_release_date)
    ]
'''

# Fix 3: leaderboard.py - proper tiebreakers and unique_solves implementation
leaderboard_code = '''\
"""Leaderboard generation and ranking."""
import json


def rank_models(model_results):
    """Rank models by resolved rate with tiebreakers.

    Primary sort: resolved_rate descending
    Tiebreaker 1: SEM ascending (lower SEM = more consistent = better)
    Tiebreaker 2: pass_at_k descending (higher = better)

    Args:
        model_results: list of dicts with model evaluation results

    Returns:
        list of model results with \'rank\' field added, sorted by rank
    """
    sorted_results = sorted(
        model_results,
        key=lambda x: (-x["resolved_rate"], x["sem"], -x["pass_at_k"]),
    )

    for i, result in enumerate(sorted_results):
        result["rank"] = i + 1

    return sorted_results


def compute_unique_solves(evaluations, models):
    """Compute tasks uniquely solved by each model.

    A unique solve is a task that was solved by exactly one model
    (in at least one of its runs) and no other model solved it.

    Args:
        evaluations: list of evaluation dicts
        models: list of model dicts

    Returns:
        dict mapping model_id to count of unique solves
    """
    task_solvers = {}
    for eval_entry in evaluations:
        task_id = eval_entry["task_id"]
        model_id = eval_entry["model_id"]
        if any(r["resolved"] for r in eval_entry["runs"]):
            if task_id not in task_solvers:
                task_solvers[task_id] = set()
            task_solvers[task_id].add(model_id)

    unique_counts = {m["model_id"]: 0 for m in models}
    for task_id, solvers in task_solvers.items():
        if len(solvers) == 1:
            model_id = next(iter(solvers))
            unique_counts[model_id] += 1

    return unique_counts


def generate_leaderboard(model_results):
    """Generate leaderboard output as JSON string.

    Args:
        model_results: ranked list of model results

    Returns:
        JSON string of leaderboard entries
    """
    leaderboard = []
    for result in model_results:
        entry = {
            "rank": result["rank"],
            "model_id": result["model_id"],
            "resolved_rate_pct": round(result["resolved_rate"] * 100, 1),
            "sem_pct": round(result["sem"] * 100, 2),
            "pass_at_k_pct": round(result["pass_at_k"] * 100, 1),
            "cost_per_problem": round(result["cost_per_problem"], 4),
            "contaminated_count": result["contaminated_count"],
            "decontaminated_resolved_rate_pct": round(
                result.get("decontaminated_resolved_rate", 0) * 100, 1
            ),
            "unique_solves": result.get("unique_solves", 0),
        }
        leaderboard.append(entry)
    return json.dumps(leaderboard, indent=2)
'''

# Write all fixed files
with open("/app/metrics.py", "w") as f:
    f.write(metrics_code)

with open("/app/contamination.py", "w") as f:
    f.write(contamination_code)

with open("/app/leaderboard.py", "w") as f:
    f.write(leaderboard_code)

print("All pipeline bugs fixed.")
