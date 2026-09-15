"""Reservoir release computation.

Computes the daily release rate based on seasonal operating rules,
current storage level, and inflow conditions using the STARFIT framework.
"""
import math

OMEGA = 1.0 / 52.0
SECONDS_PER_DAY = 86400.0


def compute_release(params, week, q_in, storage_MCM, capacity_MCM,
                    avail, nor_hi, nor_lo):
    """Compute daily release rate.

    Args:
        params: dict of reservoir parameters
        week: ISO week number (1-52)
        q_in: current inflow rate (m3/s)
        storage_MCM: current storage (million cubic meters)
        capacity_MCM: reservoir capacity (million cubic meters)
        avail: availability status (dimensionless)
        nor_hi: upper NOR bound (% of capacity)
        nor_lo: lower NOR bound (% of capacity)

    Returns:
        Release rate in m3/s
    """
    mean_flow = params["Obs_MEANFLOW_CUMECS"]

    # Weekly volumes (m3/week)
    v_f = 7.0 * q_in * SECONDS_PER_DAY
    v_m = 7.0 * mean_flow * SECONDS_PER_DAY

    # Standardized inflow (dimensionless)
    i_std = v_f / v_m

    # Standardized seasonal release
    r_std = (
        params["Release_alpha1"] * math.sin(2 * math.pi * OMEGA * week)
        + params["Release_alpha2"] * math.sin(4 * math.pi * OMEGA * week)
        + params["Release_beta1"] * math.cos(2 * math.pi * OMEGA * week)
        + params["Release_beta2"] * math.cos(4 * math.pi * OMEGA * week)
    )

    # Release bounds (m3/day)
    r_min_vol = v_m * (1.0 + params["Release_min"]) / 7.0
    r_max_vol = v_m * (1.0 + params["Release_max"]) / 7.0

    # Base release (m3/day)
    release = v_m * (
        1.0 + r_std + params["Release_c"]
        + params["Release_p1"] * avail
        + params["Release_p2"] * i_std
    ) / 7.0

    # Override when storage is outside normal operating range
    storage_m3 = storage_MCM * 1e6
    cap_m3 = capacity_MCM * 1e6

    r_above = (storage_m3 - cap_m3 * nor_hi / 100.0 + v_f) / 7.0
    r_below = (storage_m3 - cap_m3 * nor_lo / 100.0 + v_f) / 7.0

    if avail > 1.0:
        release = r_above
    if avail < 0.0:
        release = r_below

    # Clamp to operating bounds
    release = max(r_min_vol, min(r_max_vol, release))

    # Convert m3/day to m3/s
    return release / SECONDS_PER_DAY
