#!/usr/bin/env python3
"""
Dirty Page Write Throttling Simulator

Simulates the Linux kernel's balance_dirty_pages() control loop.
The control loop maintains system dirty page count near a configured
setpoint by dynamically adjusting per-task write rate limits using a
cubic polynomial position ratio.

Models two backing devices with different write bandwidths and six
writer tasks. Outputs simulation metrics to stdout and /opt/task/metrics.json.

"""

import json
from dataclasses import dataclass
from typing import List, Dict


# --- Configuration ---
TOTAL_PAGES = 100000
SETPOINT_RATIO = 0.40
LIMIT_RATIO = 0.60
MAX_PAUSE_MS = 200.0
SMOOTHING = 0.125
NUM_TICKS = 2000
TICK_MS = 10.0


@dataclass
class BDI:
    """Backing Device Info -- models a storage device."""
    name: str
    max_bw: float          # max writeback bandwidth (pages per tick)
    dirty: int = 0
    ratelimit: float = 0.0
    est_bw: float = 0.0

    def __post_init__(self):
        self.ratelimit = self.max_bw
        self.est_bw = self.max_bw


@dataclass
class Task:
    """A process that dirties pages on a specific BDI."""
    tid: int
    bdi: BDI
    want_rate: float       # desired dirty rate (pages per tick)
    dirtied: int = 0       # cumulative pages dirtied
    paused_ms: float = 0.0 # cumulative pause time
    ticks: int = 0
    smooth_rate: float = 0.0

    def __post_init__(self):
        self.smooth_rate = self.want_rate


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def calc_pos_ratio(nr_dirty: int, setpoint: int, limit: int) -> float:
    """
    Global position ratio via cubic polynomial.

    Controls throttling intensity based on distance from setpoint:
      >1 when below setpoint (allow more dirtying)
       1 at setpoint (equilibrium)
      <1 when above setpoint (throttle harder)
       0 at hard limit (full stop)

    The cubic provides smooth, progressive throttling that becomes
    increasingly aggressive as dirty pages approach the hard limit.
    """
    if nr_dirty >= limit:
        return 0.0
    if nr_dirty <= 0:
        return 2.0
    x = (nr_dirty - setpoint) / (limit - setpoint)
    ratio = 1.0 + x * x * x
    return max(0.0, min(2.0, ratio))


def bdi_pos_ratio(base_ratio: float, bdi: BDI,
                  sys_dirty: int, total_bw: float) -> float:
    """
    Adjust the global position ratio for a specific BDI.

    BDIs with higher write bandwidth deserve proportionally more dirty
    pages.  Relaxes throttling for under-represented BDIs, tightens
    for over-represented ones.
    """
    if sys_dirty <= 0 or total_bw <= 0:
        return base_ratio
    bdi_frac = bdi.dirty / sys_dirty
    fair_share = bdi.est_bw / sys_dirty
    deviation = fair_share - bdi_frac
    return max(0.0, min(2.0, base_ratio * (1.0 + deviation)))


def compute_pause(task: Task, bdi: BDI,
                  ratio: float, n_writers: int) -> float:
    """
    Calculate pause duration (ms) to enforce the task's rate limit.

    Each writer gets an equal share of the BDI's rate limit, scaled
    by the position ratio.  The pause reduces the effective dirty rate
    to match the allowed rate.
    """
    per_task = bdi.ratelimit / max(1, n_writers)
    allowed = per_task * ratio
    if allowed < 0.001:
        return MAX_PAUSE_MS
    overshoot = task.dirtied - allowed
    if overshoot <= 0.0:
        return 0.0
    pause = TICK_MS * overshoot / task.want_rate
    return pause


def update_ratelimit(bdi: BDI, ratio: float, agg_bw: float):
    """Smooth the BDI's rate limit toward its bandwidth-adjusted target."""
    target = agg_bw * ratio
    bdi.ratelimit += SMOOTHING * (target - bdi.ratelimit)
    bdi.ratelimit = max(0.0, bdi.ratelimit)


def count_writers(bdi: BDI, tasks: List[Task]) -> int:
    """Count active writer tasks for a given BDI."""
    return max(1, sum(1 for t in tasks
                      if t.bdi.name == bdi.name and t.smooth_rate > 0.01))


def do_writeback(bdis: List[BDI]) -> int:
    """Simulate one tick of writeback across all devices."""
    total = 0
    for b in bdis:
        wb = min(b.dirty, int(b.max_bw))
        b.dirty -= wb
        total += wb
    return total


# ---------------------------------------------------------------------------
# Simulation loop
# ---------------------------------------------------------------------------

def simulate() -> dict:
    """Run the full simulation and return a metrics dictionary."""
    setpoint = int(TOTAL_PAGES * SETPOINT_RATIO)
    limit = int(TOTAL_PAGES * LIMIT_RATIO)

    ssd = BDI("ssd", max_bw=100.0)
    hdd = BDI("hdd", max_bw=25.0)
    devs = [ssd, hdd]
    total_bw = sum(d.max_bw for d in devs)

    tasks: List[Task] = [Task(i, ssd, 40.0) for i in range(4)]
    tasks += [Task(4 + i, hdd, 20.0) for i in range(2)]

    dirty_hist: List[float] = []
    throughput_hist: List[int] = []
    bdi_shares: Dict[str, List[float]] = {d.name: [] for d in devs}
    all_pauses: List[float] = []
    neg_pauses = 0
    ticks_above_limit = 0
    sys_dirty = 0

    for tick in range(NUM_TICKS):
        tick_pages = 0

        for task in tasks:
            task.ticks += 1
            g = calc_pos_ratio(sys_dirty, setpoint, limit)
            b = bdi_pos_ratio(g, task.bdi, sys_dirty, total_bw)
            nw = count_writers(task.bdi, tasks)
            p = compute_pause(task, task.bdi, b, nw)

            all_pauses.append(p)
            if p < 0:
                neg_pauses += 1

            if p >= TICK_MS:
                eff = 0.0
            else:
                eff = task.want_rate * (1.0 - p / TICK_MS)

            pg = max(0, int(eff))
            task.bdi.dirty += pg
            task.dirtied += pg
            task.paused_ms += max(0.0, p)
            tick_pages += pg

            task.smooth_rate = ((1 - SMOOTHING) * task.smooth_rate
                                + SMOOTHING * eff)

        sys_dirty = min(sum(d.dirty for d in devs), TOTAL_PAGES)
        do_writeback(devs)
        sys_dirty = sum(d.dirty for d in devs)
        throughput_hist.append(tick_pages)

        for d in devs:
            g = calc_pos_ratio(sys_dirty, setpoint, limit)
            b = bdi_pos_ratio(g, d, sys_dirty, total_bw)
            update_ratelimit(d, b, total_bw)

        dr = sys_dirty / TOTAL_PAGES
        dirty_hist.append(dr)
        if dr > LIMIT_RATIO:
            ticks_above_limit += 1

        for d in devs:
            share = d.dirty / sys_dirty if sys_dirty > 0 else 0.0
            bdi_shares[d.name].append(share)

    # --- Tail statistics (last 25% of simulation) ---
    tail_start = NUM_TICKS * 3 // 4
    tail_dirty = dirty_hist[tail_start:]
    tail_tp = throughput_hist[tail_start:]

    mx_pause = max(all_pauses) if all_pauses else 0.0

    metrics: Dict[str, object] = {
        "avg_tail_dirty_ratio": sum(tail_dirty) / len(tail_dirty),
        "max_tail_dirty_ratio": max(tail_dirty),
        "min_tail_dirty_ratio": min(tail_dirty),
        "ticks_above_limit": ticks_above_limit,
        "max_pause_ms": mx_pause,
        "negative_pauses": neg_pauses,
        "avg_tail_throughput": sum(tail_tp) / len(tail_tp),
    }
    for bname, shares in bdi_shares.items():
        tail = shares[tail_start:]
        metrics[f"avg_tail_bdi_{bname}_share"] = (
            sum(tail) / len(tail) if tail else 0)

    return metrics


def main():
    metrics = simulate()
    sep = "=" * 60
    print(sep)
    print("DIRTY PAGE THROTTLING SIMULATION RESULTS")
    print(sep)
    for k in sorted(metrics):
        v = metrics[k]
        if isinstance(v, float):
            print(f"  {k:40s}  {v:.4f}")
        else:
            print(f"  {k:40s}  {v}")
    print(sep)

    with open("/opt/task/metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)


if __name__ == "__main__":
    main()
