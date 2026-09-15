"""
In-memory cache engine with clock-based recency tracking.

Uses a 16-bit unsigned clock (wraps every 65536 ticks) for compact
idle-time tracking. Each cache access increments the clock by one tick.

"""

import random

CLOCK_BITS = 16
CLOCK_MAX = (1 << CLOCK_BITS) - 1  # 65535
POOL_SIZE = 16
FREQ_INIT_VAL = 5


class CacheEntry:
    """Cache entry with recency and frequency metadata."""

    __slots__ = ['key', 'access_clock', 'frequency', 'last_decay_clock']

    def __init__(self, key, clock):
        self.key = key
        self.access_clock = clock & CLOCK_MAX
        self.frequency = FREQ_INIT_VAL
        self.last_decay_clock = clock & CLOCK_MAX

    def touch(self, clock):
        """Update last-access clock on cache hit."""
        self.access_clock = clock & CLOCK_MAX

    def idle_time(self, current_clock):
        """Compute ticks elapsed since last access, handling clock wrap."""
        current = current_clock & CLOCK_MAX
        if current >= self.access_clock:
            return current - self.access_clock
        else:
            return current + self.access_clock


class EvictionPool:
    """Pool of eviction candidates sorted by score (ascending).

    Higher score indicates a better eviction candidate. Candidates are
    inserted via try_insert and the best (highest score) is retrieved
    via pop_best.
    """

    def __init__(self, max_size=POOL_SIZE):
        self.max_size = max_size
        self.entries = []  # [(score, key), ...] sorted ascending

    def try_insert(self, key, score):
        """Insert candidate if it qualifies (pool not full or score > min)."""
        for i, (s, k) in enumerate(self.entries):
            if k == key:
                if score > s:
                    self.entries.pop(i)
                    break
                return

        if len(self.entries) < self.max_size:
            self._sorted_insert(score, key)
        elif self.entries and score > self.entries[0][0]:
            self.entries.pop(0)
            self._sorted_insert(score, key)

    def _sorted_insert(self, score, key):
        lo, hi = 0, len(self.entries)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.entries[mid][0] < score:
                lo = mid + 1
            else:
                hi = mid
        self.entries.insert(lo, (score, key))

    def pop_best(self):
        """Remove and return the key with the highest score, or None."""
        if not self.entries:
            return None
        return self.entries.pop()[1]

    def __len__(self):
        return len(self.entries)


class CacheEngine:
    """Fixed-size cache with pluggable eviction policy.

    The cache tracks both recency (via clock ticks) and frequency
    (via per-entry counters) to support sophisticated eviction strategies.
    """

    def __init__(self, max_entries, policy_cls, seed=42, **policy_kwargs):
        self.max_entries = max_entries
        self.rng = random.Random(seed)
        self.store = {}
        self.clock = 0
        self.hits = 0
        self.misses = 0
        self.policy = policy_cls(self, **policy_kwargs)

    def access(self, key):
        """Access a key. Returns True on hit, False on miss."""
        self.clock = (self.clock + 1) & CLOCK_MAX

        if key in self.store:
            self.hits += 1
            entry = self.store[key]
            entry.touch(self.clock)
            self.policy.on_hit(entry)
            return True

        self.misses += 1

        if len(self.store) >= self.max_entries:
            victim = self.policy.select_victim()
            if victim is not None:
                del self.store[victim]

        self.store[key] = CacheEntry(key, self.clock)
        self.policy.on_insert(key)
        return False

    @property
    def hit_ratio(self):
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def stats(self):
        return {
            'hits': self.hits,
            'misses': self.misses,
            'hit_ratio': round(self.hit_ratio, 6),
            'size': len(self.store),
        }
