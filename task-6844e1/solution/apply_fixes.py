#!/usr/bin/env python3
"""
Apply fixes to the dirty page write throttling simulation.

1. Implement the four throttle controller functions in throttle.py
2. Fix three bugs in simulator.py:
   - Bug A: Writeback does not decrement system.nr_dirty, causing the
     global dirty counter to grow monotonically.
   - Bug B: Per-BDI setpoint is calculated using the BDI's current dirty
     proportion instead of its bandwidth proportion, creating a positive
     feedback loop that destabilizes the system.
   - Bug C: Per-task rate limit is updated BEFORE writer estimation,
     causing the estimation to use the newly computed rate limit instead
     of the previous tick's value, which creates a secondary positive
     feedback loop in the writer count estimation.
"""



def fix_throttle():
    """Write the complete, correct throttle.py implementation."""

    code = '''\
"""
Dirty page write throttling functions.

Implements the control loop from the Linux kernel's balance_dirty_pages()
as described in Fengguang Wu's no-I/O dirty throttling patch set.
"""

MAX_PAUSE_MS = 200
MIN_RATELIMIT = 0.001
BW_SMOOTH_FACTOR = 0.25


def pos_ratio_polynom(setpoint: int, dirty: int, limit: int) -> float:
    """Cubic polynomial: 1 + ((setpoint - dirty) / (limit - setpoint))^3, clamped >= 0."""
    if dirty >= limit:
        return 0.0
    if limit <= setpoint:
        return 1.0
    denom = limit - setpoint
    if denom == 0:
        return 1.0
    x = (setpoint - dirty) / denom
    ratio = 1.0 + x * x * x
    return max(0.0, ratio)


def calc_bdi_pos_ratio(bdi_dirty: int, bdi_setpoint: float,
                       global_pos_ratio: float) -> float:
    """Adjust global pos_ratio for a specific BDI based on its dirty deviation."""
    if bdi_setpoint <= 0:
        return global_pos_ratio
    deviation = (bdi_dirty - bdi_setpoint) / bdi_setpoint
    adjusted = global_pos_ratio * (1.0 - deviation)
    return max(0.0, adjusted)


def calc_task_pause_ms(pages_dirtied: float, task_ratelimit: float,
                       period_ms: float) -> float:
    """Calculate how long a task should sleep to stay within its rate limit."""
    if pages_dirtied <= 0:
        return 0.0
    if task_ratelimit < MIN_RATELIMIT:
        return MAX_PAUSE_MS
    pause = (pages_dirtied / task_ratelimit - 1.0) * period_ms
    return max(0.0, min(pause, MAX_PAUSE_MS))


def estimate_bdi_writers(bdi_dirty_rate: float, per_task_ratelimit: float,
                         prev_estimate: float) -> float:
    """Estimate active writer count with EMA smoothing."""
    if per_task_ratelimit < MIN_RATELIMIT:
        return max(1.0, prev_estimate)
    raw_estimate = bdi_dirty_rate / per_task_ratelimit
    smoothed = prev_estimate * (1.0 - BW_SMOOTH_FACTOR) + raw_estimate * BW_SMOOTH_FACTOR
    return max(1.0, smoothed)
'''

    with open("/app/throttle.py", "w") as f:
        f.write(code)
    print("Fixed: throttle.py - implemented all four functions")


def fix_simulator():
    """Fix three bugs in simulator.py."""

    with open("/app/simulator.py", "r") as f:
        src = f.read()

    # Bug A: Missing system.nr_dirty decrement in writeback phase.
    # The writeback loop decrements bdi.nr_dirty but never decrements
    # system.nr_dirty, causing the global counter to grow without bound.
    old_writeback = (
        "            written = min(bdi.bandwidth, bdi.nr_dirty)\n"
        "            bdi.nr_dirty -= written"
    )
    new_writeback = (
        "            written = min(bdi.bandwidth, bdi.nr_dirty)\n"
        "            bdi.nr_dirty -= written\n"
        "            system.nr_dirty -= written"
    )
    assert old_writeback in src, "Could not locate writeback code to patch"
    src = src.replace(old_writeback, new_writeback)
    print("Fixed: simulator.py Bug A - added system.nr_dirty decrement in writeback")

    # Bug B: BDI setpoint uses dirty-page proportion instead of bandwidth
    # proportion. Using bdi.nr_dirty/system.nr_dirty creates a positive
    # feedback loop; the correct denominator is bandwidth-based.
    old_setpoint = (
        "            bdi_setpoint = system.setpoint * (\n"
        "                bdi.nr_dirty / max(1, system.nr_dirty)\n"
        "            )"
    )
    new_setpoint = (
        "            bdi_setpoint = system.setpoint * (\n"
        "                bdi.bandwidth / system.total_bandwidth\n"
        "            )"
    )
    assert old_setpoint in src, "Could not locate bdi_setpoint code to patch"
    src = src.replace(old_setpoint, new_setpoint)
    print("Fixed: simulator.py Bug B - BDI setpoint uses bandwidth proportion")

    # Bug C: Per-task rate limit is updated BEFORE writer estimation.
    # This means estimate_bdi_writers uses the newly computed rate limit
    # instead of the previous tick's value, creating a positive feedback
    # loop in the estimation. Fix: move estimation before rate limit update.
    old_order = (
        "            # Update per-task rate limit\n"
        "            num_writers = max(1.0, bdi.estimated_writers)\n"
        "            bdi.per_task_ratelimit = per_bdi_ratelimit / num_writers\n"
        "\n"
        "            # Estimate number of active writers\n"
        "            bdi.estimated_writers = estimate_bdi_writers(\n"
        "                bdi.total_dirtied_this_tick,\n"
        "                bdi.per_task_ratelimit,\n"
        "                bdi.estimated_writers,\n"
        "            )"
    )
    new_order = (
        "            # Estimate number of active writers using PREVIOUS per-task limit\n"
        "            bdi.estimated_writers = estimate_bdi_writers(\n"
        "                bdi.total_dirtied_this_tick,\n"
        "                bdi.per_task_ratelimit,\n"
        "                bdi.estimated_writers,\n"
        "            )\n"
        "\n"
        "            # Update per-task rate limit\n"
        "            num_writers = max(1.0, bdi.estimated_writers)\n"
        "            bdi.per_task_ratelimit = per_bdi_ratelimit / num_writers"
    )
    assert old_order in src, "Could not locate estimation/ratelimit ordering to patch"
    src = src.replace(old_order, new_order)
    print("Fixed: simulator.py Bug C - writer estimation now uses previous tick's ratelimit")

    with open("/app/simulator.py", "w") as f:
        f.write(src)


if __name__ == "__main__":
    fix_throttle()
    fix_simulator()
    print("\nAll fixes applied.")
