#!/usr/bin/env python3
"""
Fix the pipeline simulator's latency death spiral.


Root causes identified:
  1. Unbounded queues → backlog grows without limit under overload
  2. No load shedding → every request accepted regardless of capacity
  3. No backpressure → ingress stage feeds processing faster than it can
     consume, so even with ingress load-shedding the processing queue
     grows unboundedly
  4. Metrics only count completed requests → coordinated omission hides
     the true tail latency of in-flight requests

Solution approach:
  1. Compute effective service times accounting for 5% spike probability
     (spike_factor=8).
  2. Derive per-stage queue bounds from Little's Law:
       bound = ceil(target_delay_ms / effective_service_ms * safety)
  3. Override _enqueue to enforce bounds (return False when at capacity).
  4. Override _try_start with backpressure: stall when downstream queue
     is at capacity.
  5. Override _on_arrive: reject (load-shed) when ingress queue is full.
  6. Override _on_complete: after forwarding to next stage, wake upstream
     stages (backpressure relief).
  7. Override results(): include in-flight requests' elapsed times in a
     corrected percentile computation (CO correction).
"""

import sys
sys.path.insert(0, "/app")

import json
import math
from simulation import PipelineSimulator, PHASES, phase_of


# ------------------------------------------------------------------ #
# Queueing-theory helpers                                             #
# ------------------------------------------------------------------ #

def effective_mean_service_time(base_ms, spike_prob, spike_factor):
    """Expected service time including spike probability.

    E[T] = (1 - p) * base + p * base * factor
    """
    return (1 - spike_prob) * base_ms + spike_prob * base_ms * spike_factor


def queue_bound_from_littles_law(target_delay_ms, eff_service_ms, safety=1.5):
    """Max queue depth to keep queueing delay under *target_delay_ms*.

    From Little's Law  L = lambda * W:
      At steady state, the number of items in the queue (L) equals the
      arrival rate (lambda) times the average wait (W).
      Rearranging: L_max = target_W / service_time  (per-item wait)
    The safety factor absorbs variance from the spike distribution.
    """
    raw = target_delay_ms / eff_service_ms
    return max(10, int(math.ceil(raw * safety)))


# ------------------------------------------------------------------ #
# Fixed pipeline                                                      #
# ------------------------------------------------------------------ #

class FixedPipeline(PipelineSimulator):
    """Pipeline with bounded queues, backpressure, load shedding, and
    coordinated-omission-corrected latency metrics."""

    def __init__(self, seed=42):
        super().__init__(seed)

        # Compute effective service times (accounting for spikes)
        eff = {}
        for name in self.stage_names:
            eff[name] = effective_mean_service_time(
                self.stage_service_ms[name],
                self.spike_prob,
                self.spike_factor,
            )

        # Derive queue bounds: target max queueing delay = 100 ms
        self.queue_bounds = {
            name: queue_bound_from_littles_law(100.0, eff[name])
            for name in self.stage_names
        }

    # -- bounded enqueue --

    def _enqueue(self, stage_name, request_id):
        """Add to queue if below capacity; return False otherwise."""
        if len(self.queues[stage_name]) >= self.queue_bounds[stage_name]:
            return False
        self.queues[stage_name].append(request_id)
        depth = len(self.queues[stage_name])
        if depth > self.max_queue_depth[stage_name]:
            self.max_queue_depth[stage_name] = depth
        return True

    # -- backpressure-aware processing --

    def _try_start(self, stage_name):
        """Start processing only if downstream can accept our output."""
        if self.busy[stage_name] or not self.queues[stage_name]:
            return

        idx = self.stage_names.index(stage_name)
        # Backpressure: stall when the downstream queue is at capacity
        if idx < len(self.stage_names) - 1:
            nxt = self.stage_names[idx + 1]
            if len(self.queues[nxt]) >= self.queue_bounds[nxt]:
                return

        self.busy[stage_name] = True
        rid = self.queues[stage_name].pop(0)
        svc = self._service_time(stage_name)
        self._push(self.now + svc, "complete", stage=stage_name, request_id=rid)

    # -- load shedding on arrival --

    def _on_arrive(self, data):
        """Accept or reject: shed load when ingress queue is full."""
        rid = self.next_id
        self.next_id += 1
        arrival_ms = data["arrival_ms"]
        self.arrival_times[rid] = arrival_ms

        first = self.stage_names[0]
        if not self._enqueue(first, rid):
            # Load shedding — immediate rejection
            self.rejected.append((rid, arrival_ms, self.now))
            del self.arrival_times[rid]
            return
        self._try_start(first)

    # -- completion with backpressure relief --

    def _on_complete(self, data):
        """Forward to next stage, then wake upstream stages."""
        stage = data["stage"]
        rid = data["request_id"]
        self.busy[stage] = False

        idx = self.stage_names.index(stage)
        if idx < len(self.stage_names) - 1:
            nxt = self.stage_names[idx + 1]
            self._enqueue(nxt, rid)
            self._try_start(nxt)
        else:
            arr = self.arrival_times.pop(rid)
            self.completed.append((rid, arr, self.now))

        # Continue at this stage
        self._try_start(stage)

        # Backpressure relief: downstream freed a slot, so upstream
        # stages that were stalled may now be able to proceed.
        for i in range(idx - 1, -1, -1):
            self._try_start(self.stage_names[i])

    # -- results with CO correction --

    def results(self):
        """Add coordinated-omission-corrected P99 to each phase."""
        base = super().results()

        def pct(vals, p):
            if not vals:
                return 0.0
            s = sorted(vals)
            return s[min(int(len(s) * p / 100), len(s) - 1)]

        sim_end = self.now

        # Corrected latencies = completed latencies ∪ in-flight lower bounds
        phase_corr = {n: [] for n, _, _ in PHASES}
        for _, arr, comp in self.completed:
            ph = phase_of(arr)
            if ph in phase_corr:
                phase_corr[ph].append(comp - arr)
        for _, arr in self.arrival_times.items():
            ph = phase_of(arr)
            if ph in phase_corr:
                # Lower bound: request has been waiting at least this long
                phase_corr[ph].append(sim_end - arr)

        for name, _, _ in PHASES:
            base["phases"][name]["p99_corrected_ms"] = round(
                pct(phase_corr[name], 99), 3
            )

        return base


# ------------------------------------------------------------------ #
# Entry point                                                         #
# ------------------------------------------------------------------ #

def main():
    sim = FixedPipeline(seed=42)
    sim.generate_workload([
        (0, 10, 200),
        (10, 20, 2000),
        (20, 30, 200),
    ])
    sim.run(duration_s=30)
    res = sim.results()

    with open("/app/results.json", "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
