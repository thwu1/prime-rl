"""Single-day reservoir simulation logic.

Provides the core simulate_day function used by the cascade orchestrator.
"""
from .nor import nor_upper, nor_lower
from .release import compute_release

SECONDS_PER_DAY = 86400.0
M3PS_TO_MCM_DAY = SECONDS_PER_DAY / 1e6
MCM_TO_M3PS_DAY = 1e6 / SECONDS_PER_DAY


def iso_week(d):
    """ISO 8601 week number capped at 52."""
    return min(d.isocalendar()[1], 52)


def simulate_day(params, q_in, storage, cap, ew):
    """Simulate a single day for one reservoir.

    Args:
        params: reservoir parameter dict
        q_in: total inflow rate (m3/s)
        storage: start-of-day storage (MCM)
        cap: reservoir capacity (MCM)
        ew: ISO week number

    Returns:
        (new_storage, release_cms, spill_cms, outflow_cms, avail)
    """
    hi = nor_upper(params, ew)
    lo = nor_lower(params, ew)

    storage_pct = 100.0 * storage / cap
    avail = (storage_pct - lo) / (hi - lo)

    release_cms = compute_release(params, ew, q_in, storage, cap, avail, hi, lo)

    ds = (q_in - release_cms) * M3PS_TO_MCM_DAY

    # Negative storage protection
    if (storage + ds) < 0.0:
        ds = -storage
        storage = 0.0
    else:
        storage = storage + ds

    spill_cms = 0.0
    if storage > cap:
        spill_cms = (storage - cap) * MCM_TO_M3PS_DAY
        storage = cap

    outflow_cms = release_cms + spill_cms

    return storage, release_cms, spill_cms, outflow_cms, avail
