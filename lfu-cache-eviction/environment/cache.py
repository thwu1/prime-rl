"""
Cache simulation framework implementing Redis-style eviction policies.

Implements approximated LRU with eviction pool (Redis 3.0) and LFU with
logarithmic counter (Redis 4.0). Based on the algorithms described in
antirez's blog post "Random notes on improving the Redis LRU algorithm".

"""

import random
import bisect

# Redis-style constants
LFU_INIT_VAL = 5
EVPOOL_SIZE = 16
LRU_CLOCK_MAX = (1 << 24) - 1  # 16777215, wraps ~194 days at 1 tick/sec


def lfu_log_incr(counter, log_factor, rng):
    """Logarithmically increment the LFU counter.

    The probability of incrementing decreases as the counter grows:
        P(increment) = 1.0 / ((baseval * log_factor) + 1)
    where baseval = max(0, counter - LFU_INIT_VAL).

    Counter saturates at 255. With default log_factor=10:
        ~100 hits  -> counter ~ 10
        ~1000 hits -> counter ~ 18
        ~1M hits   -> counter = 255

    Args:
        counter: Current 8-bit counter value (0-255)
        log_factor: Controls increment aggressiveness
        rng: random.Random instance
    Returns:
        Updated counter value
    """
    raise NotImplementedError("Implement Redis-style LFU logarithmic counter increment")


def lfu_decay_and_return(counter, last_decr_time, current_time_minutes, decay_time):
    """Apply time-based decay to LFU counter.

    Computes elapsed minutes (handling 16-bit wrap), divides by decay_time
    to get number of decay periods, and decrements counter by that amount.

    Args:
        counter: Current 8-bit counter value
        last_decr_time: 16-bit timestamp of last decrement (minutes)
        current_time_minutes: Current time in minutes
        decay_time: Minutes per decay period (0 = no decay)
    Returns:
        Decayed counter value (>= 0)
    """
    raise NotImplementedError("Implement Redis-style LFU counter decay")


class CacheEntry:
    """Cache entry with LRU and LFU metadata packed in 24 bits each."""

    __slots__ = ['key', 'lru_clock', 'lfu_field']

    def __init__(self, key, clock_seconds):
        self.key = key
        self.lru_clock = clock_seconds & LRU_CLOCK_MAX
        # LFU: 24 bits = [16-bit last-decrement-time (minutes)][8-bit counter]
        minutes = (clock_seconds // 60) & 0xFFFF
        self.lfu_field = (minutes << 8) | LFU_INIT_VAL

    @property
    def lfu_counter(self):
        return self.lfu_field & 0xFF

    @lfu_counter.setter
    def lfu_counter(self, val):
        self.lfu_field = (self.lfu_field & 0xFFFF00) | (val & 0xFF)

    @property
    def lfu_ldt(self):
        return (self.lfu_field >> 8) & 0xFFFF

    @lfu_ldt.setter
    def lfu_ldt(self, val):
        self.lfu_field = ((val & 0xFFFF) << 8) | (self.lfu_field & 0xFF)

    def touch_lru(self, clock_seconds):
        """Update LRU clock on access."""
        self.lru_clock = clock_seconds & LRU_CLOCK_MAX

    def touch_lfu(self, rng, log_factor):
        """Update LFU counter on access."""
        self.lfu_counter = lfu_log_incr(self.lfu_counter, log_factor, rng)

    def idle_time(self, current_clock):
        """Compute idle time handling 24-bit clock wrap."""
        current = current_clock & LRU_CLOCK_MAX
        if current >= self.lru_clock:
            return current - self.lru_clock
        else:
            return current + self.lru_clock

    def effective_lfu(self, current_clock_seconds, decay_time):
        """Get effective LFU counter after applying decay."""
        current_minutes = (current_clock_seconds // 60) & 0xFFFF
        counter = lfu_decay_and_return(
            self.lfu_counter, self.lfu_ldt, current_minutes, decay_time
        )
        self.lfu_counter = counter
        self.lfu_ldt = current_minutes
        return counter


class EvictionPool:
    """Sorted pool of eviction candidates (Redis 3.0 style).

    Maintains up to `size` entries sorted ascending by idle time.
    New candidates enter if their idle time exceeds the pool minimum
    or if there is empty space. Best candidate (highest idle time)
    is popped from the end.
    """

    def __init__(self, size=EVPOOL_SIZE):
        self.size = size
        self.entries = []  # [(idle_time, key), ...] sorted ascending

    def try_insert(self, key, idle_time):
        """Try to insert a candidate into the pool.

        Insert if: (a) pool has space, or (b) idle_time > pool minimum.
        If full and inserting, remove the minimum entry.
        Maintain sorted order (ascending by idle time).
        If key already in pool with higher idle time, skip.
        """
        raise NotImplementedError("Implement eviction pool insertion")

    def pop_best(self):
        """Remove and return the key with highest idle time, or None."""
        raise NotImplementedError("Implement eviction pool pop")

    def __len__(self):
        return len(self.entries)


class CacheSimulator:
    """Cache simulator with configurable eviction policies.

    Policies:
        'random'     - Baseline random eviction
        'approx_lru' - Approximated LRU with eviction pool (Redis 3.0)
        'lfu'        - LFU with logarithmic counter (Redis 4.0)
    """

    def __init__(self, max_size, policy='random', samples=5,
                 log_factor=10, decay_time=1, seed=42):
        self.max_size = max_size
        self.policy = policy
        self.samples = samples
        self.log_factor = log_factor
        self.decay_time = decay_time
        self.rng = random.Random(seed)
        self.store = {}
        self.clock = 0
        self.hits = 0
        self.misses = 0
        self.pool = EvictionPool()

    def access(self, key):
        """Access a key (get-or-set semantics)."""
        self.clock += 1
        if key in self.store:
            self.hits += 1
            entry = self.store[key]
            if self.policy == 'approx_lru':
                entry.touch_lru(self.clock)
            elif self.policy == 'lfu':
                entry.touch_lfu(self.rng, self.log_factor)
            return
        self.misses += 1
        if len(self.store) >= self.max_size:
            self._evict()
        self.store[key] = CacheEntry(key, self.clock)

    def _evict(self):
        if self.policy == 'random':
            self._evict_random()
        elif self.policy == 'approx_lru':
            self._evict_approx_lru()
        elif self.policy == 'lfu':
            self._evict_lfu()

    def _evict_random(self):
        """Baseline: evict a random key."""
        key = self.rng.choice(list(self.store.keys()))
        del self.store[key]

    def _evict_approx_lru(self):
        """Approximated LRU with eviction pool.

        1. Sample `self.samples` random keys from the store
        2. For each sampled key, compute idle time and try to insert into pool
        3. Pop the best candidate (highest idle time) from pool and evict it
        4. If popped key no longer in store (stale), continue popping
        5. Fallback: evict sampled key with highest idle time
        """
        raise NotImplementedError("Implement approximated LRU eviction with pool")

    def _evict_lfu(self):
        """LFU eviction: sample keys, evict the one with lowest counter."""
        raise NotImplementedError("Implement LFU eviction")

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
            'policy': self.policy,
        }
