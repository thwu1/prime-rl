"""Aggregate active-rollout evidence derived from persisted trace timings."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


class TraceConcurrencyError(ValueError):
    """Trace lifecycle timing cannot support a concurrency claim."""


def _timestamp(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TraceConcurrencyError("trace_concurrency_timing_invalid")
    timestamp = float(value)
    if not math.isfinite(timestamp) or timestamp <= 0:
        raise TraceConcurrencyError("trace_concurrency_timing_invalid")
    return timestamp


def measure_peak_active_rollouts(traces: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Measure overlap from setup start through completed scoring for each trace."""

    events: list[tuple[float, int]] = []
    count = 0
    for trace in traces:
        timing = trace.get("timing") if isinstance(trace, dict) else None
        setup = timing.get("setup") if isinstance(timing, dict) else None
        scoring = timing.get("scoring") if isinstance(timing, dict) else None
        if not isinstance(setup, dict) or not isinstance(scoring, dict):
            raise TraceConcurrencyError("trace_concurrency_timing_invalid")
        start = _timestamp(setup.get("start"))
        end = _timestamp(scoring.get("end"))
        if end <= start:
            raise TraceConcurrencyError("trace_concurrency_timing_invalid")
        events.extend(((start, 1), (end, -1)))
        count += 1
    if count < 1:
        raise TraceConcurrencyError("trace_concurrency_timing_invalid")

    active = 0
    peak = 0
    for _, delta in sorted(events, key=lambda event: (event[0], event[1])):
        active += delta
        if active < 0:
            raise TraceConcurrencyError("trace_concurrency_timing_invalid")
        peak = max(peak, active)
    if active != 0 or peak < 1:
        raise TraceConcurrencyError("trace_concurrency_timing_invalid")
    return {
        "observed_rollouts": count,
        "peak_active_rollouts_lower_bound": peak,
    }
