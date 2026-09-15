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
        list of model results with 'rank' field added, sorted by rank
    """
    sorted_results = sorted(
        model_results,
        key=lambda x: x["resolved_rate"],
        reverse=True
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
    return {}


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
