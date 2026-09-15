#!/usr/bin/env python3
"""
Fix all algorithmic bugs in the dirty page throttling simulator.

Bug 1 — calc_pos_ratio: sign error in the cubic polynomial creates
         positive feedback instead of negative feedback.
Bug 2 — bdi_pos_ratio: fair-share denominator uses system dirty page
         count instead of total write bandwidth.
Bug 3 — compute_pause: compares cumulative pages dirtied (ever-growing)
         against per-tick allowed rate, producing ever-increasing pauses.
Bug 4 — update_ratelimit: smooths toward aggregate system bandwidth
         instead of per-BDI bandwidth, collapsing all devices to the
         same rate limit.

"""

with open("/opt/task/throttle_sim.py") as f:
    code = f.read()

# Fix 1: Cubic polynomial must provide NEGATIVE feedback.
# When dirty > setpoint, x > 0, and the ratio must DECREASE (< 1).
# 1 + x^3 gives ratio > 1 (positive feedback, wrong).
# 1 - x^3 gives ratio < 1 (negative feedback, correct).
code = code.replace(
    "ratio = 1.0 + x * x * x",
    "ratio = 1.0 - x * x * x",
    1,
)

# Fix 2: Fair share is each BDI's bandwidth as a fraction of TOTAL
# bandwidth, not as a fraction of the current dirty page count.
# bdi.est_bw / sys_dirty ≈ 100/40000 = 0.0025 (nearly zero, useless).
# bdi.est_bw / total_bw = 100/125 = 0.80 (correct fair share).
code = code.replace(
    "fair_share = bdi.est_bw / sys_dirty",
    "fair_share = bdi.est_bw / total_bw",
    1,
)

# Fix 3: Overshoot must compare per-tick DESIRED RATE against per-tick
# allowed rate.  Using cumulative `dirtied` makes overshoot grow every
# tick, eventually parking all tasks permanently.
code = code.replace(
    "overshoot = task.dirtied - allowed",
    "overshoot = task.want_rate - allowed",
    1,
)

# Fix 4: Each BDI's ratelimit should converge to its OWN bandwidth
# scaled by the position ratio, not to the aggregate system bandwidth.
# Using agg_bw makes SSD and HDD share the same ratelimit.
code = code.replace(
    "target = agg_bw * ratio",
    "target = bdi.est_bw * ratio",
    1,
)

with open("/opt/task/throttle_sim.py", "w") as f:
    f.write(code)

print("Applied 4 fixes to /opt/task/throttle_sim.py")
