"""
Pipeline Latency Simulator
===========================
Discrete-event simulation of a multi-stage request processing pipeline.


Architecture:
    Arrival -> [Queue] -> Ingress -> [Queue] -> Processing -> [Queue] -> Egress -> Complete

Each stage processes one request at a time.  Service times are generated
deterministically from a seeded PRNG (Xorshift32).

Default workload (three phases):
    "normal"   (0-10 s):   200 req/s
    "overload" (10-20 s): 2000 req/s
    "recovery" (20-30 s):  200 req/s

Stage parameters:
    ingress:     base_ms=1.5  cv=0.4  spike_prob=5%  spike_factor=8x
    processing:  base_ms=2.2  cv=0.5  spike_prob=5%  spike_factor=8x
    egress:      base_ms=1.0  cv=0.3  spike_prob=5%  spike_factor=8x

KNOWN ISSUES:
    Under sustained overload the system enters a latency death spiral.
    Queue depths grow without bound and the system cannot recover even
    after the arrival rate drops back to normal.  Reported latency metrics
    significantly understate true user-experienced tail latency.
"""

import heapq
import json
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Deterministic PRNG
# ---------------------------------------------------------------------------

class Xorshift32:
    """Deterministic PRNG for reproducible service times."""

    def __init__(self, seed=42):
        self.state = seed if seed != 0 else 1

    def next_u32(self):
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= (x >> 17)
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF
        return self.state

    def uniform(self):
        """Return a float in [0, 1)."""
        return self.next_u32() / 0x100000000


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

@dataclass(order=True)
class Event:
    time: float
    seq: int
    kind: str = field(compare=False)
    data: dict = field(compare=False, default_factory=dict)


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------

PHASES = [
    ("normal", 0, 10),
    ("overload", 10, 20),
    ("recovery", 20, 30),
]


def phase_of(arrival_ms):
    """Determine which workload phase a request belongs to."""
    t_s = arrival_ms / 1000.0
    for name, start, end in PHASES:
        if start <= t_s < end:
            return name
    return "unknown"


# ---------------------------------------------------------------------------
# Pipeline Simulator
# ---------------------------------------------------------------------------

class PipelineSimulator:
    """
    Discrete-event simulation of a three-stage request processing pipeline.

    Current behaviour:
      - All queues are unbounded.
      - Every arriving request is accepted unconditionally.
      - Latency metrics are recorded only for completed requests.
      - No back-pressure is propagated between stages.
    """

    def __init__(self, seed=42):
        self.rng = Xorshift32(seed)
        self.seq = 0
        self.heap = []
        self.now = 0.0

        # Stage configuration
        self.stage_names = ["ingress", "processing", "egress"]
        self.stage_service_ms = {"ingress": 1.5, "processing": 2.2, "egress": 1.0}
        self.stage_cv = {"ingress": 0.4, "processing": 0.5, "egress": 0.3}
        self.spike_prob = 0.05
        self.spike_factor = 8

        # Per-stage runtime state
        self.queues = {name: [] for name in self.stage_names}
        self.busy = {name: False for name in self.stage_names}

        # Request tracking
        self.next_id = 0
        self.arrival_times = {}   # request_id -> arrival_time_ms

        # Metrics
        self.completed = []       # [(id, arrival_ms, completion_ms), ...]
        self.rejected = []        # [(id, arrival_ms, rejection_ms), ...]
        self.max_queue_depth = {n: 0 for n in self.stage_names}

    # ------------------------------------------------------------------ #
    # Event helpers                                                       #
    # ------------------------------------------------------------------ #

    def _push(self, time, kind, **kw):
        self.seq += 1
        heapq.heappush(self.heap, Event(time, self.seq, kind, kw))

    # ------------------------------------------------------------------ #
    # Service time generation                                             #
    # ------------------------------------------------------------------ #

    def _service_time(self, stage_name):
        """Generate a deterministic service time for *stage_name*.

        5 % of calls produce an 8x spike (models GC pauses, cache misses,
        page faults, etc.).  The remaining 95 % are normally distributed
        around the base service time.
        """
        mean = self.stage_service_ms[stage_name]
        cv = self.stage_cv[stage_name]
        u = self.rng.uniform()

        if u < self.spike_prob:
            base = mean * self.spike_factor
            jitter = mean * cv * (self.rng.uniform() - 0.5)
            return base + jitter
        jitter = mean * cv * (2 * u - 1)
        return max(0.1, mean + jitter)

    # ------------------------------------------------------------------ #
    # Queue operations                                                    #
    # ------------------------------------------------------------------ #

    def _enqueue(self, stage_name, request_id):
        """Add *request_id* to the tail of *stage_name*'s queue.

        Always succeeds — queues are unbounded.
        """
        self.queues[stage_name].append(request_id)
        depth = len(self.queues[stage_name])
        if depth > self.max_queue_depth[stage_name]:
            self.max_queue_depth[stage_name] = depth
        return True

    # ------------------------------------------------------------------ #
    # Stage processing                                                    #
    # ------------------------------------------------------------------ #

    def _try_start(self, stage_name):
        """If *stage_name* is idle and has queued work, start processing."""
        if self.busy[stage_name]:
            return
        if not self.queues[stage_name]:
            return
        self.busy[stage_name] = True
        rid = self.queues[stage_name].pop(0)
        svc = self._service_time(stage_name)
        self._push(self.now + svc, "complete", stage=stage_name, request_id=rid)

    # ------------------------------------------------------------------ #
    # Event handlers                                                      #
    # ------------------------------------------------------------------ #

    def _on_arrive(self, data):
        """Handle a new request arriving at the pipeline."""
        rid = self.next_id
        self.next_id += 1
        self.arrival_times[rid] = data["arrival_ms"]

        # Unconditionally enqueue at the first stage
        first = self.stage_names[0]
        self._enqueue(first, rid)
        self._try_start(first)

    def _on_complete(self, data):
        """Handle completion of processing at a stage."""
        stage = data["stage"]
        rid = data["request_id"]
        self.busy[stage] = False

        idx = self.stage_names.index(stage)
        if idx < len(self.stage_names) - 1:
            nxt = self.stage_names[idx + 1]
            self._enqueue(nxt, rid)
            self._try_start(nxt)
        else:
            # Final stage — record completion
            arr = self.arrival_times.pop(rid)
            self.completed.append((rid, arr, self.now))

        # Process next queued item at this stage
        self._try_start(stage)

    # ------------------------------------------------------------------ #
    # Workload generation                                                 #
    # ------------------------------------------------------------------ #

    def generate_workload(self, phases):
        """Schedule deterministic arrival events.

        *phases*: list of ``(start_s, end_s, rate_per_s)`` tuples.
        """
        for start_s, end_s, rate in phases:
            if rate <= 0:
                continue
            interval = 1000.0 / rate
            t = start_s * 1000.0
            end_ms = end_s * 1000.0
            while t < end_ms:
                self._push(t, "arrive", arrival_ms=t)
                t += interval

    # ------------------------------------------------------------------ #
    # Main loop                                                           #
    # ------------------------------------------------------------------ #

    def run(self, duration_s=30):
        """Run the simulation for *duration_s* seconds of simulated time."""
        limit = duration_s * 1000.0
        while self.heap:
            ev = heapq.heappop(self.heap)
            if ev.time > limit:
                break
            self.now = ev.time
            if ev.kind == "arrive":
                self._on_arrive(ev.data)
            elif ev.kind == "complete":
                self._on_complete(ev.data)

    # ------------------------------------------------------------------ #
    # Results                                                             #
    # ------------------------------------------------------------------ #

    def results(self):
        """Compute and return a results dictionary."""

        def pct(vals, p):
            if not vals:
                return 0.0
            s = sorted(vals)
            return s[min(int(len(s) * p / 100), len(s) - 1)]

        # Per-phase completed latencies
        phase_lats = {n: [] for n, _, _ in PHASES}
        for _, arr, comp in self.completed:
            ph = phase_of(arr)
            if ph in phase_lats:
                phase_lats[ph].append(comp - arr)

        # Per-phase arrival counts (completed + rejected + in-flight)
        phase_arrived = {n: 0 for n, _, _ in PHASES}
        for _, arr, _ in self.completed:
            ph = phase_of(arr)
            if ph in phase_arrived:
                phase_arrived[ph] += 1
        for _, arr, _ in self.rejected:
            ph = phase_of(arr)
            if ph in phase_arrived:
                phase_arrived[ph] += 1
        for _, arr in self.arrival_times.items():
            ph = phase_of(arr)
            if ph in phase_arrived:
                phase_arrived[ph] += 1

        # Per-phase rejections
        phase_rej = {n: 0 for n, _, _ in PHASES}
        for _, arr, _ in self.rejected:
            ph = phase_of(arr)
            if ph in phase_rej:
                phase_rej[ph] += 1

        phases = {}
        for name, _, _ in PHASES:
            lats = phase_lats[name]
            phases[name] = {
                "arrived": phase_arrived[name],
                "completed": len(lats),
                "rejected": phase_rej[name],
                "p50_ms": round(pct(lats, 50), 3),
                "p99_ms": round(pct(lats, 99), 3),
                "mean_ms": round(sum(lats) / len(lats), 3) if lats else 0,
            }

        all_lats = [c - a for _, a, c in self.completed]

        return {
            "total_arrived": self.next_id,
            "total_completed": len(self.completed),
            "total_rejected": len(self.rejected),
            "in_flight_at_end": len(self.arrival_times),
            "max_queue_depths": dict(self.max_queue_depth),
            "overall_latency": {
                "p50_ms": round(pct(all_lats, 50), 3),
                "p99_ms": round(pct(all_lats, 99), 3),
                "mean_ms": round(sum(all_lats) / len(all_lats), 3) if all_lats else 0,
            },
            "phases": phases,
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    sim = PipelineSimulator(seed=42)
    sim.generate_workload([
        (0, 10, 200),     # normal:   200 req/s
        (10, 20, 2000),   # overload: 2000 req/s
        (20, 30, 200),    # recovery: 200 req/s
    ])
    sim.run(duration_s=30)
    res = sim.results()

    with open("/app/results.json", "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
