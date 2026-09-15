"""Cost computation -- simple model, ignores cached token pricing."""


def compute_cost_per_problem(runs, pricing):
    """Compute average cost treating all input tokens at the full input rate.

    cost = (input_tokens * input_rate + output_tokens * output_rate) / 1M

    Does not distinguish between cached and uncached input tokens.
    """
    if not runs:
        return 0.0
    total = 0.0
    for r in runs:
        total += (r["input_tokens"] * pricing["input_per_mtok"] +
                  r["output_tokens"] * pricing["output_per_mtok"]) / 1_000_000
    return total / len(runs)
