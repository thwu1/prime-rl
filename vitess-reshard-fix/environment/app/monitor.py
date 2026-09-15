"""
Shard health monitoring system.

Tracks per-shard query counts and error rates.  Provides an ``is_healthy``
predicate used by the circuit-breaker pattern in batch jobs.

A global singleton ``monitor`` is exposed for easy import::

    from monitor import monitor
    if monitor.is_healthy(shard_name):
        ...

For testing, ``inject_error_rate`` lets callers simulate a degraded shard
without generating real errors.
"""

import threading
from collections import defaultdict
from typing import Dict


class ShardMonitor:
    """Thread-safe shard health tracker."""

    def __init__(self) -> None:
        self._query_counts: Dict[str, int] = defaultdict(int)
        self._error_counts: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self._error_injection: Dict[str, float] = {}

    # ── Recording ───────────────────────────────────────────────────────

    def record_query(
        self, shard_name: str, duration_ms: float = 0, error: bool = False
    ) -> None:
        with self._lock:
            self._query_counts[shard_name] += 1
            if error:
                self._error_counts[shard_name] += 1

    # ── Querying ────────────────────────────────────────────────────────

    def get_error_rate(self, shard_name: str) -> float:
        with self._lock:
            total = self._query_counts.get(shard_name, 0)
            errors = self._error_counts.get(shard_name, 0)
            return errors / total if total else 0.0

    def get_query_count(self, shard_name: str) -> int:
        with self._lock:
            return self._query_counts.get(shard_name, 0)

    def is_healthy(self, shard_name: str, error_threshold: float = 0.5) -> bool:
        """Return *True* when the shard's error rate is below *error_threshold*.

        If an error rate has been injected via ``inject_error_rate``, that
        synthetic value is used instead of the real counters.
        """
        if shard_name in self._error_injection:
            return self._error_injection[shard_name] < error_threshold
        return self.get_error_rate(shard_name) < error_threshold

    # ── Testing helpers ─────────────────────────────────────────────────

    def inject_error_rate(self, shard_name: str, rate: float) -> None:
        """Simulate *rate* (0.0-1.0) for *shard_name*."""
        self._error_injection[shard_name] = rate

    def clear_injection(self, shard_name: str) -> None:
        self._error_injection.pop(shard_name, None)

    def reset(self) -> None:
        with self._lock:
            self._query_counts.clear()
            self._error_counts.clear()
            self._error_injection.clear()


# Global singleton
monitor = ShardMonitor()
