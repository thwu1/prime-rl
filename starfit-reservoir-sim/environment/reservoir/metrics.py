"""Reservoir system performance evaluation metrics.

See /app/specification.md for metric definitions.
"""


def compute_metrics(downstream_outflows, demand_target):
    """Compute performance metrics for the cascade system.

    Args:
        downstream_outflows: list of daily outflow rates (m3/s)
            from the most downstream reservoir
        demand_target: required flow rate (m3/s)

    Returns:
        dict with keys:
            reliability: fraction of days outflow >= demand
            resilience: probability of recovery from deficit
            vulnerability: mean relative deficit during deficit periods
    """
    raise NotImplementedError("Implement performance metrics")
