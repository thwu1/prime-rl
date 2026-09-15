#!/usr/bin/env python3
"""
Dirty Page Write Throttling Simulation Framework
=================================================

Simulates the Linux kernel's balance_dirty_pages() control loop across
multiple backing devices and concurrent writer tasks.

Usage:
    python3 /app/framework.py

Loads controller from /app/controller.py and scenarios from
/app/scenarios.json.  Outputs per-scenario metrics (.json) and
timeseries (.csv) to /app/output/.

Controller Interface
--------------------

The controller module (/app/controller.py) must export:

CONFIG : dict
    "setpoint_ratio" (float) - target dirty page fraction of total_pages
    "limit_ratio"    (float) - hard limit fraction, must exceed setpoint
    "max_pause_ms"   (float) - maximum pause per tick in milliseconds
    "smoothing"      (float) - smoothing factor in (0, 1]

calc_pos_ratio(nr_dirty: int, setpoint: int, limit: int) -> float
    Global position ratio in [0.0, 2.0].
    Returns 1.0 at setpoint, 0.0 at/above limit, 2.0 at/below 0.
    Must be monotonically non-increasing with nr_dirty.

bdi_pos_ratio(base_ratio: float, bdi_dirty: int, bdi_est_bw: float,
              sys_dirty: int, total_bw: float) -> float
    Per-BDI position ratio in [0.0, 2.0].

compute_pause(want_rate: float, bdi_ratelimit: float, bdi_ratio: float,
              n_writers: int, tick_ms: float, max_pause_ms: float) -> float
    Per-task pause in [0.0, max_pause_ms] milliseconds.

update_ratelimit(current: float, target: float, smoothing: float) -> float
    Smoothed ratelimit update.  Non-negative result.

"""

import json
import os
import sys
import importlib.util
from dataclasses import dataclass
from typing import List, Dict, Optional


def load_controller(path="/app/controller.py"):
    """Import the controller module."""
    spec = importlib.util.spec_from_file_location("controller", path)
    if spec is None or spec.loader is None:
        print(f"ERROR: controller not found at {path}", file=sys.stderr)
        sys.exit(1)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("CONFIG", "calc_pos_ratio", "bdi_pos_ratio",
                 "compute_pause", "update_ratelimit"):
        if not hasattr(mod, name):
            print(f"ERROR: controller missing '{name}'", file=sys.stderr)
            sys.exit(1)
    for key in ("setpoint_ratio", "limit_ratio", "max_pause_ms", "smoothing"):
        if key not in mod.CONFIG:
            print(f"ERROR: CONFIG missing '{key}'", file=sys.stderr)
            sys.exit(1)
    return mod


@dataclass
class BDI:
    """Backing device info -- models a storage device."""
    name: str
    max_bw: float
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
    base_want_rate: float
    want_rate: float = 0.0
    paused_ms: float = 0.0
    ticks: int = 0
    smooth_rate: float = 0.0
    burst_pattern: Optional[List[float]] = None

    def __post_init__(self):
        self.want_rate = self.base_want_rate
        self.smooth_rate = self.base_want_rate


def run_scenario(name: str, scenario: dict, ctrl) -> tuple:
    """Run one workload scenario.

    Returns (metrics_dict, timeseries_list, device_name_list).
    """
    total_pages = scenario["total_pages"]
    num_ticks = scenario["num_ticks"]
    tick_ms = scenario["tick_ms"]

    cfg = ctrl.CONFIG
    setpoint = int(total_pages * cfg["setpoint_ratio"])
    limit = int(total_pages * cfg["limit_ratio"])
    max_pause = cfg["max_pause_ms"]
    smoothing = cfg["smoothing"]

    # Create devices
    devs: Dict[str, BDI] = {}
    for dc in scenario["devices"]:
        devs[dc["name"]] = BDI(dc["name"], dc["max_bw"])
    dev_list = list(devs.values())
    dev_names = [d.name for d in dev_list]
    total_bw = sum(d.max_bw for d in dev_list)

    # Create tasks
    tasks: List[Task] = []
    for i, tc in enumerate(scenario["tasks"]):
        t = Task(i, devs[tc["device"]], tc["want_rate"])
        if "burst_pattern" in tc:
            t.burst_pattern = tc["burst_pattern"]
        tasks.append(t)

    # State tracking
    timeseries: List[dict] = []
    all_pauses: List[float] = []
    neg_pauses = 0
    ticks_above = 0
    sys_dirty = 0

    for tick in range(num_ticks):
        # Apply burst patterns
        for task in tasks:
            if task.burst_pattern is not None:
                plen = max(1, num_ticks // len(task.burst_pattern))
                idx = min(tick // plen, len(task.burst_pattern) - 1)
                task.want_rate = task.base_want_rate * task.burst_pattern[idx]

        tick_pages = 0
        # Snapshot BDI dirty counts so all tasks in the same tick see
        # consistent state regardless of processing order.
        bdi_snap = {d.name: d.dirty for d in dev_list}

        for task in tasks:
            task.ticks += 1

            # Position ratios (using snapshot, not live bdi.dirty)
            g = ctrl.calc_pos_ratio(sys_dirty, setpoint, limit)
            b = ctrl.bdi_pos_ratio(g, bdi_snap[task.bdi.name],
                                   task.bdi.est_bw, sys_dirty, total_bw)

            # Count co-writers on this device
            nw = max(1, sum(1 for t in tasks
                           if t.bdi.name == task.bdi.name
                           and t.smooth_rate > 0.01))

            # Pause calculation
            p = ctrl.compute_pause(task.want_rate, task.bdi.ratelimit,
                                   b, nw, tick_ms, max_pause)
            all_pauses.append(p)
            if p < 0:
                neg_pauses += 1

            # Effective dirty rate
            eff = 0.0 if p >= tick_ms else task.want_rate * (1.0 - p / tick_ms)
            pg = max(0, int(eff))
            task.bdi.dirty += pg
            task.paused_ms += max(0.0, p)
            tick_pages += pg
            task.smooth_rate = ((1 - smoothing) * task.smooth_rate
                                + smoothing * eff)

        # Pre-writeback dirty count
        sys_dirty = sum(d.dirty for d in dev_list)

        # Writeback: each device flushes up to max_bw pages
        for d in dev_list:
            wb = min(d.dirty, int(d.max_bw))
            d.dirty -= wb

        # Post-writeback dirty count
        sys_dirty = sum(d.dirty for d in dev_list)

        # Update per-device ratelimits using global position ratio.
        # The per-BDI adjustment is applied only in the pause calculation
        # to avoid double-counting.
        g_update = ctrl.calc_pos_ratio(sys_dirty, setpoint, limit)
        for d in dev_list:
            target = d.est_bw * g_update
            d.ratelimit = ctrl.update_ratelimit(d.ratelimit, target, smoothing)

        dr = sys_dirty / total_pages
        if dr > cfg["limit_ratio"]:
            ticks_above += 1

        row = {"tick": tick, "dirty_ratio": dr, "throughput": tick_pages}
        for d in dev_list:
            row[f"{d.name}_share"] = (d.dirty / sys_dirty
                                      if sys_dirty > 0 else 0.0)
        timeseries.append(row)

    # Tail statistics (last 25%)
    tail_start = num_ticks * 3 // 4
    tail = timeseries[tail_start:]
    tail_dr = [r["dirty_ratio"] for r in tail]
    tail_tp = [r["throughput"] for r in tail]

    metrics = {
        "scenario": name,
        "avg_tail_dirty_ratio": sum(tail_dr) / len(tail_dr),
        "max_tail_dirty_ratio": max(tail_dr),
        "min_tail_dirty_ratio": min(tail_dr),
        "ticks_above_limit": ticks_above,
        "max_pause_ms": max(all_pauses) if all_pauses else 0.0,
        "negative_pauses": neg_pauses,
        "avg_tail_throughput": sum(tail_tp) / len(tail_tp),
    }
    for d in dev_list:
        ts = [r[f"{d.name}_share"] for r in tail]
        metrics[f"avg_tail_bdi_{d.name}_share"] = sum(ts) / len(ts)

    return metrics, timeseries, dev_names


def write_csv(path: str, ts: list, dev_names: list):
    """Write timeseries data to CSV."""
    cols = ["tick", "dirty_ratio", "throughput"]
    cols += [f"{d}_share" for d in dev_names]
    with open(path, "w") as f:
        f.write(",".join(cols) + "\n")
        for row in ts:
            vals = []
            for c in cols:
                v = row[c]
                vals.append(f"{v:.6f}" if isinstance(v, float) else str(v))
            f.write(",".join(vals) + "\n")


def main():
    os.makedirs("/app/output", exist_ok=True)
    ctrl = load_controller()

    with open("/app/scenarios.json") as f:
        scenarios = json.load(f)

    print("=" * 60)
    print("DIRTY PAGE THROTTLING SIMULATION")
    print("=" * 60)

    for sname, sconfig in scenarios.items():
        metrics, ts, dnames = run_scenario(sname, sconfig, ctrl)

        with open(f"/app/output/{sname}_metrics.json", "w") as f:
            json.dump(metrics, f, indent=2)
        write_csv(f"/app/output/{sname}_timeseries.csv", ts, dnames)

        print(f"\n[{sname}]")
        for k, v in sorted(metrics.items()):
            if k == "scenario":
                continue
            if isinstance(v, float):
                print(f"  {k:40s}  {v:.4f}")
            else:
                print(f"  {k:40s}  {v}")

    print("\n" + "=" * 60)
    print("Output written to /app/output/")


if __name__ == "__main__":
    main()
