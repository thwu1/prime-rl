"""Muskingum channel routing between reservoirs.

See /app/specification.md for the mathematical formulation.
"""


def compute_muskingum_coefficients(K, x, dt=1.0):
    """Compute Muskingum routing coefficients C0, C1, C2.

    Args:
        K: travel time parameter (days)
        x: weighting factor (dimensionless, 0 to 0.5)
        dt: time step (days)

    Returns:
        (C0, C1, C2) tuple
    """
    raise NotImplementedError("Implement Muskingum coefficient computation")


def route_flow(inflows, C0, C1, C2, initial_outflow=None):
    """Route a flow timeseries through a channel reach.

    Args:
        inflows: list of inflow rates (m3/s), length T
        C0, C1, C2: Muskingum coefficients
        initial_outflow: outflow at t=0 (m3/s); defaults to inflows[0]

    Returns:
        list of routed outflow rates (m3/s), length T
    """
    raise NotImplementedError("Implement Muskingum flow routing")
