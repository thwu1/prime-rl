"""Cost computation -- tiered pricing with cached token discount."""


def compute_cost_per_problem(runs, pricing):
    """Compute average cost with separate cached/uncached input pricing.

    cost = ((input - cached) * input_rate
            + cached * cached_rate
            + output * output_rate) / 1M

    Each run's cost is computed independently, then averaged.
    """
    if not runs:
        return 0.0
    total = 0.0
    for r in runs:
        uncached = r["input_tokens"] - r["cached_tokens"]
        total += (uncached * pricing["input_per_mtok"] +
                  r["cached_tokens"] * pricing["cached_input_per_mtok"] +
                  r["output_tokens"] * pricing["output_per_mtok"]) / 1_000_000
    return total / len(runs)
