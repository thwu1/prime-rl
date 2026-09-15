"""
Eviction policies for the cache engine.

Provides random, FIFO, and adaptive eviction strategies. The adaptive
policy combines recency and frequency signals with an eviction pool
for improved candidate selection.

"""

from engine import EvictionPool, CLOCK_MAX, FREQ_INIT_VAL


class RandomPolicy:
    """Baseline: evict a uniformly random key."""

    def __init__(self, engine):
        self.engine = engine

    def on_hit(self, entry):
        pass

    def on_insert(self, key):
        pass

    def select_victim(self):
        if not self.engine.store:
            return None
        return self.engine.rng.choice(list(self.engine.store.keys()))


class FIFOPolicy:
    """First-in-first-out eviction."""

    def __init__(self, engine):
        self.engine = engine
        self._queue = []

    def on_hit(self, entry):
        pass

    def on_insert(self, key):
        self._queue.append(key)

    def select_victim(self):
        while self._queue:
            key = self._queue.pop(0)
            if key in self.engine.store:
                return key
        if self.engine.store:
            return self.engine.rng.choice(list(self.engine.store.keys()))
        return None


class AdaptivePolicy:
    """Adaptive eviction combining recency and frequency signals.

    Scores each candidate based on idle time (recency) and access
    frequency. Uses an eviction pool to accumulate and rank candidates
    across eviction rounds. Configurable weights control the balance
    between recency and frequency in the eviction score.
    """

    def __init__(self, engine, samples=5, decay_interval=1000,
                 recency_weight=1.0, frequency_weight=2.0, log_factor=10):
        self.engine = engine
        self.samples = samples
        self.decay_interval = decay_interval
        self.recency_weight = recency_weight
        self.frequency_weight = frequency_weight
        self.log_factor = log_factor
        self.pool = EvictionPool()

    def on_hit(self, entry):
        """Update frequency on cache hit."""
        entry.frequency += 1

    def on_insert(self, key):
        pass

    def _decayed_frequency(self, entry):
        """Get frequency after applying time-based decay."""
        current = self.engine.clock & CLOCK_MAX
        last = entry.last_decay_clock
        elapsed = current - last
        if elapsed < 0:
            elapsed = 0
        periods = elapsed // self.decay_interval if self.decay_interval > 0 else 0
        if periods > 0:
            entry.frequency = max(0, entry.frequency - periods)
            entry.last_decay_clock = current
        return entry.frequency

    def _eviction_score(self, entry):
        """Compute eviction score. Higher = better candidate for eviction.

        Combines idle time (prefer evicting idle entries) with inverse
        frequency (prefer evicting infrequently-accessed entries).
        """
        idle = entry.idle_time(self.engine.clock)
        freq = self._decayed_frequency(entry)
        recency_component = idle * self.recency_weight
        frequency_component = (1.0 / (freq + 1)) * self.frequency_weight * CLOCK_MAX
        return recency_component + frequency_component

    def select_victim(self):
        """Select a key to evict using pool-assisted sampling."""
        if not self.engine.store:
            return None

        keys = list(self.engine.store.keys())
        n = min(self.samples, len(keys))
        sample = self.engine.rng.sample(keys, n)

        for key in sample:
            if key in self.engine.store:
                entry = self.engine.store[key]
                score = self._eviction_score(entry)
                self.pool.try_insert(key, score)

        # Try the best candidate from the pool
        victim = self.pool.pop_best()
        if victim is not None and victim in self.engine.store:
            return victim

        # Fallback: highest score from current sample
        best_key = None
        best_score = -1
        for key in sample:
            if key in self.engine.store:
                score = self._eviction_score(self.engine.store[key])
                if score > best_score:
                    best_score = score
                    best_key = key
        return best_key
