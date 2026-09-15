"""Normal Operating Range (NOR) envelope calculations.

The NOR defines seasonal upper and lower storage targets as percentages
of reservoir capacity. Both bounds follow a sinusoidal model with
clamping to physical limits.
"""
import math

OMEGA = 1.0 / 52.0


def nor_upper(params, week):
    """Compute upper NOR bound for a given ISO week.

    Args:
        params: dict with NORhi_mu, NORhi_alpha, NORhi_beta, NORhi_min, NORhi_max
        week: ISO week number (1-52)

    Returns:
        Upper NOR bound as percentage of capacity
    """
    val = (
        params["NORhi_mu"]
        + params["NORhi_alpha"] * math.sin(2 * math.pi * OMEGA * week)
        + params["NORhi_beta"] * math.cos(2 * math.pi * OMEGA * week)
    )
    return min(params["NORhi_max"], max(params["NORhi_min"], val))


def nor_lower(params, week):
    """Compute lower NOR bound for a given ISO week.

    Args:
        params: dict with NORlo_mu, NORlo_alpha, NORlo_beta, NORlo_min, NORlo_max
        week: ISO week number (1-52)

    Returns:
        Lower NOR bound as percentage of capacity
    """
    val = (
        params["NORlo_mu"]
        + params["NORlo_alpha"] * math.cos(2 * math.pi * OMEGA * week)
        + params["NORlo_beta"] * math.sin(2 * math.pi * OMEGA * week)
    )
    return min(params["NORlo_max"], max(params["NORlo_min"], val))
