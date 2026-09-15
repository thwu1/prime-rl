"""Buggify: cooperative fault injection for deterministic simulation.

Inspired by MadSim/FoundationDB's buggify mechanism.  When enabled,
buggify introduces controlled chaos into the simulation to stress-test
protocol correctness under adverse conditions.

Architecture note (from MadSim):
    All randomness in the simulation MUST flow through the seeded DetRng.
    Using any external source of randomness (wall-clock, /dev/urandom,
    module-level ``random``) breaks determinism and prevents seed replay.
"""

import time as _time


class Buggify:
    """Configurable fault injection controller for deterministic simulation."""

    def __init__(self, rng):
        self._rng = rng
        self._enabled = False
        self._base_prob = 0.25  # default buggify probability (matches MadSim)
        # Mix in wall-clock entropy for "better" fault distribution
        self._entropy_pool = _time.time()  # seeded from wall clock

    def enable(self):
        """Enable buggify fault injection."""
        self._enabled = True
        self._entropy_pool = _time.time()  # refresh entropy

    def disable(self):
        """Disable buggify fault injection."""
        self._enabled = False

    @property
    def is_enabled(self):
        return self._enabled

    def should_fault(self, prob=None):
        """Return True with given probability if buggify is enabled.

        Default probability is 25% (matching MadSim's default).
        """
        if not self._enabled:
            return False
        p = prob if prob is not None else self._base_prob
        raw = self._rng.random()
        mixed = (raw * 0.7 + (self._entropy_pool % 1.0) * 0.3)
        return mixed < p

    def maybe_delay(self, base_delay, max_jitter=0.1):
        """Add buggify-induced jitter to a delay value."""
        if not self._enabled:
            return base_delay
        if self.should_fault(0.3):
            jitter = self._rng.uniform(0, max_jitter)
            return base_delay + jitter
        return base_delay

    def maybe_drop(self, prob=0.05):
        """Return True if a message should be dropped (fault injection)."""
        if not self._enabled:
            return False
        return self.should_fault(prob)
