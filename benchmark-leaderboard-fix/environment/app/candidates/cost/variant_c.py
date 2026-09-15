"""Cost computation -- cost per resolution model."""


def compute_cost_per_problem(runs, pricing):
    """Compute effective cost per successful resolution.

    Computes total cost across all runs but divides by the number
    of resolved runs rather than total runs, yielding the cost
    to produce one successful solve.

    Falls back to dividing by total runs if no runs resolved.
    """
    if not runs:
        return 0.0
    total = 0.0
    resolved_count = 0
    for r in runs:
        uncached = r["input_tokens"] - r["cached_tokens"]
        total += (uncached * pricing["input_per_mtok"] +
                  r["cached_tokens"] * pricing["cached_input_per_mtok"] +
                  r["output_tokens"] * pricing["output_per_mtok"]) / 1_000_000
        if r.get("resolved"):
            resolved_count += 1
    if resolved_count == 0:
        return total / len(runs)
    return total / resolved_count
