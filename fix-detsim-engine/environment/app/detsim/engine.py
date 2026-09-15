"""Deterministic discrete-event simulation engine.

Architecture (modelled after MadSim):

* Events live in a min-heap ordered by ``(time, sequence_number)``.
* The monotonic *sequence_number* guarantees a total order even when
  two events share the same timestamp, which is essential for
  determinism.
* A *trace* log records every tagged event so that two runs with the
  same seed can be compared for equality.

Usage::

    rng = DetRng(42)
    eng = SimEngine(rng)
    eng.schedule(0.5, lambda: print("hello"), tag="greet")
    eng.run(until=1.0)
"""

import heapq
from typing import Callable, List


class SimEngine:
    """Core simulation engine with deterministic event scheduling."""

    def __init__(self, rng):
        self._rng = rng
        self._heap: list = []            # min-heap of (time, seq, cb, tag)
        self._now: float = 0.0           # current simulation time
        self._trace: List[str] = []      # tagged event log
        self._active: bool = True
        self._seq: int = 0               # monotonic tiebreaker

    # -- properties -----------------------------------------------------------

    @property
    def now(self) -> float:
        return self._now

    @property
    def trace(self) -> list:
        return list(self._trace)

    # -- scheduling -----------------------------------------------------------

    def schedule(self, delay: float, callback: Callable, tag: str = "") -> None:
        """Schedule *callback* to fire ``delay`` time-units from now."""
        assert delay >= 0, "delay must be non-negative"
        at = self._now + delay
        self._seq += 1
        heapq.heappush(self._heap, (at, self._seq, callback, tag))

    def schedule_at(self, time: float, callback: Callable, tag: str = "") -> None:
        """Schedule *callback* at an absolute simulation time."""
        assert time >= self._now, "cannot schedule in the past"
        self._seq += 1
        heapq.heappush(self._heap, (time, self._seq, callback, tag))

    # -- execution ------------------------------------------------------------

    def run(self, until: float) -> None:
        """Process events up to *until*, then advance the clock."""
        self._active = True
        while self._heap and self._active:
            t, _seq, cb, tag = self._heap[0]
            if t > until:
                break
            heapq.heappop(self._heap)
            self._now = t
            if tag:
                self._trace.append(f"{t:.9f}|{tag}")
            cb()
        self._now = until

    def stop(self) -> None:
        self._active = False

    def reset_trace(self) -> None:
        self._trace.clear()

    def pending_count(self) -> int:
        return len(self._heap)
