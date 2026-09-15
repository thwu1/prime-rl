"""
Controller for the dirty page write throttling simulator.

Implements the kernel's I/O-less dirty throttling approach with:
- Cubic polynomial position ratio for smooth negative feedback
- Per-BDI bandwidth-proportional fair share adjustment
- Proportional pause-based rate limiting
- EWMA-smoothed ratelimit convergence

"""

CONFIG = {
    "setpoint_ratio": 0.40,
    "limit_ratio": 0.60,
    "max_pause_ms": 200.0,
    "smoothing": 0.125,
}


def calc_pos_ratio(nr_dirty, setpoint, limit):
    """Global position ratio via cubic polynomial with negative feedback.

    Uses 1 - x^3 where x = (nr_dirty - setpoint) / (limit - setpoint).
    This gives the required boundary behavior:
      x = -big (dirty << setpoint) -> ratio -> 2.0 (clamped)
      x = 0    (dirty == setpoint) -> ratio = 1.0
      x = 1    (dirty == limit)    -> ratio = 0.0
    """
    if nr_dirty >= limit:
        return 0.0
    if nr_dirty <= 0:
        return 2.0
    x = (nr_dirty - setpoint) / (limit - setpoint)
    ratio = 1.0 - x * x * x
    return max(0.0, min(2.0, ratio))


def bdi_pos_ratio(base_ratio, bdi_dirty, bdi_est_bw, sys_dirty, total_bw):
    """Adjust position ratio based on BDI's bandwidth-proportional fair share.

    Compares the device's actual dirty fraction (bdi_dirty / sys_dirty)
    against its bandwidth fair share (bdi_est_bw / total_bw).
    Positive deviation means under-represented -> relax throttling.
    Negative deviation means over-represented -> tighten throttling.
    """
    if sys_dirty <= 0 or total_bw <= 0:
        return base_ratio
    bdi_frac = bdi_dirty / sys_dirty
    fair_share = bdi_est_bw / total_bw
    deviation = fair_share - bdi_frac
    return max(0.0, min(2.0, base_ratio * (1.0 + deviation)))


def compute_pause(want_rate, bdi_ratelimit, bdi_ratio, n_writers,
                  tick_ms, max_pause_ms):
    """Compute proportional pause to enforce per-task rate limit.

    per_task_allowed = (bdi_ratelimit / n_writers) * bdi_ratio
    If want_rate <= allowed, no pause needed.
    Otherwise, pause = tick_ms * (want - allowed) / want.
    """
    per_task = bdi_ratelimit / max(1, n_writers)
    allowed = per_task * bdi_ratio
    if allowed < 0.001:
        return max_pause_ms
    if want_rate <= allowed:
        return 0.0
    overshoot = want_rate - allowed
    pause = tick_ms * overshoot / want_rate
    return min(pause, max_pause_ms)


def update_ratelimit(current, target, smoothing):
    """EWMA-smoothed ratelimit update.

    new = current + smoothing * (target - current)
        = (1 - smoothing) * current + smoothing * target
    """
    result = current + smoothing * (target - current)
    return max(0.0, result)
