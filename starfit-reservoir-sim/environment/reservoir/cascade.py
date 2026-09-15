"""Multi-reservoir cascade simulation.

Orchestrates 3 reservoirs connected in series by channel reaches.
See /app/specification.md for the cascade structure and policy definitions.
"""

from .simulation import simulate_day, iso_week, M3PS_TO_MCM_DAY


def run_cascade(reservoir_params, reach_params, dates, lateral_inflows,
                mode="independent", demand_target=None):
    """Run the 3-reservoir cascade simulation.

    The cascade consists of:
        Reservoir 0 -> Reach 0 -> Reservoir 1 -> Reach 1 -> Reservoir 2

    Each reservoir receives lateral inflows plus routed upstream outflows.

    Args:
        reservoir_params: list of 3 parameter dicts
        reach_params: list of 2 dicts with keys 'K' and 'x'
        dates: list of date objects
        lateral_inflows: list of 3 inflow arrays (m3/s)
        mode: "independent" or "coordinated"
        demand_target: downstream demand (m3/s), used in coordinated mode

    Returns:
        results: list of 3 lists of daily result dicts
            Each dict has: date, storage_MCM, release_cms, spill_cms,
                          outflow_cms, availability_status, total_inflow_cms
        routed: list of 2 lists of daily routed flow dicts
            Each dict has: date, inflow_cms, outflow_cms
        balance: dict with system-wide mass balance info including
            'system_mass_balance_relative_error'
    """
    raise NotImplementedError("Implement cascade simulation")
