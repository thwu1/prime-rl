"""
Dirty Page Write Throttling Simulator

Simulates the Linux kernel's balance_dirty_pages() mechanism for controlling
the rate at which processes dirty memory pages, preventing the system from
being overwhelmed by writeback I/O.

This simulator models:
- Multiple backing devices (BDIs) with different write bandwidths
- Multiple writer tasks dirtying pages on specific BDIs
- A feedback control loop that throttles writers to maintain dirty page
  count near a configurable setpoint
- Writeback that drains dirty pages from each BDI at device bandwidth

The simulation runs in discrete ticks. Each tick:
1. Writers generate dirty pages, capped by their per-task rate limit
2. The throttle control loop recalculates rate limits for the next tick
3. Writeback drains dirty pages from each BDI

Results are collected as a list of per-tick state snapshots.
"""


import json
import os

from throttle import (
    pos_ratio_polynom,
    calc_bdi_pos_ratio,
    calc_task_pause_ms,
    estimate_bdi_writers,
    MAX_PAUSE_MS,
)


class BDI:
    """Backing Device Info - models a storage device with fixed write bandwidth."""

    def __init__(self, name: str, bandwidth: float):
        self.name = name
        self.bandwidth = bandwidth
        self.nr_dirty = 0
        self.estimated_writers = 1.0
        self.per_task_ratelimit = bandwidth  # Initial: assume 1 writer per BDI
        self.total_dirtied_this_tick = 0


class Task:
    """A writer process that dirties pages on a specific BDI."""

    def __init__(self, name: str, bdi: BDI, write_rate: float):
        self.name = name
        self.bdi = bdi
        self.write_rate = write_rate
        self.pages_dirtied = 0.0
        self.ratelimit = bdi.bandwidth
        self.equiv_pause_ms = 0.0


class SystemState:
    """Aggregate system state for the simulation."""

    def __init__(self, config: dict):
        self.total_pages = config["system"]["total_pages"]
        dirty_limit_ratio = config["system"]["dirty_limit_ratio"]
        setpoint_ratio = config["system"]["setpoint_ratio"]

        self.dirty_limit = int(self.total_pages * dirty_limit_ratio)
        self.setpoint = int(self.dirty_limit * setpoint_ratio)
        self.nr_dirty = 0.0
        self.period_ms = config["system"]["period_ms"]

        self.bdis = []
        for bdi_conf in config["bdis"]:
            self.bdis.append(BDI(bdi_conf["name"], bdi_conf["bandwidth"]))

        self.total_bandwidth = sum(b.bandwidth for b in self.bdis)

        self.tasks = []
        for task_conf in config["tasks"]:
            bdi = next(b for b in self.bdis if b.name == task_conf["bdi"])
            self.tasks.append(Task(task_conf["name"], bdi, task_conf["write_rate"]))

        self.tick = 0
        self.history = []


def run_simulation(config: dict) -> list:
    """
    Run the dirty throttling simulation.

    Returns a list of per-tick state snapshots suitable for JSON serialization.
    """
    system = SystemState(config)
    num_ticks = config["simulation"]["num_ticks"]

    for tick in range(num_ticks):
        system.tick = tick

        # Reset per-tick counters
        for bdi in system.bdis:
            bdi.total_dirtied_this_tick = 0

        # ================================================================
        # Phase 1: Writers dirty pages, capped by their rate limits
        # ================================================================
        for task in system.tasks:
            effective_rate = min(task.write_rate, max(0.0, task.ratelimit))
            headroom = max(0.0, system.dirty_limit - system.nr_dirty)
            pages_to_dirty = min(effective_rate, headroom)

            if pages_to_dirty > 0:
                task.bdi.nr_dirty += pages_to_dirty
                task.bdi.total_dirtied_this_tick += pages_to_dirty
                system.nr_dirty += pages_to_dirty
                task.pages_dirtied = pages_to_dirty

        # ================================================================
        # Phase 2: Throttle calculation — update rate limits for next tick
        # ================================================================
        global_pos_ratio = pos_ratio_polynom(
            system.setpoint, system.nr_dirty, system.dirty_limit
        )

        for bdi in system.bdis:
            # Determine this BDI's share of the system setpoint
            bdi_setpoint = system.setpoint * (
                bdi.nr_dirty / max(1, system.nr_dirty)
            )

            bdi_pos_ratio = calc_bdi_pos_ratio(
                bdi.nr_dirty, bdi_setpoint, global_pos_ratio
            )

            # Total rate limit for this BDI
            per_bdi_ratelimit = bdi.bandwidth * bdi_pos_ratio

            # Update per-task rate limit
            num_writers = max(1.0, bdi.estimated_writers)
            bdi.per_task_ratelimit = per_bdi_ratelimit / num_writers

            # Estimate number of active writers
            bdi.estimated_writers = estimate_bdi_writers(
                bdi.total_dirtied_this_tick,
                bdi.per_task_ratelimit,
                bdi.estimated_writers,
            )

            # Apply new rate limit to all tasks on this BDI
            for task in system.tasks:
                if task.bdi.name != bdi.name:
                    continue
                task.ratelimit = bdi.per_task_ratelimit

                # Compute equivalent pause for diagnostics
                task.equiv_pause_ms = calc_task_pause_ms(
                    task.pages_dirtied, task.ratelimit, system.period_ms
                )
                task.pages_dirtied = 0

        # ================================================================
        # Phase 3: Writeback — drain dirty pages from each BDI
        # ================================================================
        for bdi in system.bdis:
            written = min(bdi.bandwidth, bdi.nr_dirty)
            bdi.nr_dirty -= written

        # ================================================================
        # Record state snapshot
        # ================================================================
        bdi_state = {}
        for bdi in system.bdis:
            bdi_state[bdi.name] = {
                "dirty": bdi.nr_dirty,
                "writers_est": round(bdi.estimated_writers, 2),
                "dirtied": bdi.total_dirtied_this_tick,
                "ratelimit": round(bdi.per_task_ratelimit, 2),
            }

        system.history.append({
            "tick": tick,
            "nr_dirty": system.nr_dirty,
            "setpoint": system.setpoint,
            "limit": system.dirty_limit,
            "pos_ratio": round(global_pos_ratio, 4),
            "bdi": bdi_state,
        })

    return system.history
