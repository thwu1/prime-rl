"""Quantile sketch engine with logarithmic bucket mapping for relative-error guarantees."""
import math


class QuantileSketch:
    """Streaming quantile sketch using logarithmic bucket mapping.

    Provides approximate quantile computation with controllable accuracy.
    Supports merging for distributed aggregation.
    """

    def __init__(self, accuracy=0.01):
        self.accuracy = accuracy
        self.gamma = (1.0 + accuracy) / (1.0 - accuracy)
        self._log_gamma = math.log(self.gamma)
        self.store = {}
        self.zero_count = 0
        self.count = 0
        self.min_val = float('inf')
        self.max_val = float('-inf')

    def _key(self, v):
        """Map a positive value to its bucket key."""
        return math.ceil(math.log(v) / self._log_gamma)

    def _value(self, key):
        """Return the representative value for a bucket key."""
        return 2.0 * (self.gamma ** key) / (1.0 + self.gamma)

    def add(self, v):
        """Add a non-negative value to the sketch."""
        if v < 0:
            raise ValueError("Only non-negative values supported")
        self.count += 1
        if v == 0:
            self.zero_count += 1
            self.min_val = min(self.min_val, 0.0)
            return
        self.min_val = min(self.min_val, v)
        self.max_val = max(self.max_val, v)
        key = self._key(v)
        self.store[key] = self.store.get(key, 0) + 1

    def quantile(self, q):
        """Compute the q-th quantile (0 <= q <= 1)."""
        if self.count == 0:
            raise ValueError("Empty sketch")
        if q <= 0:
            return self.min_val
        if q >= 1:
            return self.max_val
        rank = int(math.ceil(q * self.count))
        running = self.zero_count
        if running >= rank:
            return 0.0
        for key in sorted(self.store.keys()):
            running += self.store[key]
            if running >= rank:
                return self._value(key)
        return self.max_val

    def num_buckets(self):
        """Return the number of active buckets."""
        return len(self.store)


class CollapsingQuantileSketch(QuantileSketch):
    """Quantile sketch variant with bounded memory via bucket collapsing.

    When active buckets exceed max_buckets, collapses adjacent buckets
    to stay within the memory budget.
    """

    def __init__(self, accuracy=0.01, max_buckets=128):
        super().__init__(accuracy)
        self.max_buckets = max_buckets

    def add(self, v):
        super().add(v)
        if len(self.store) > self.max_buckets:
            self._collapse()

    def _collapse(self):
        """Collapse buckets to stay within max_buckets limit."""
        while len(self.store) > self.max_buckets:
            keys = sorted(self.store.keys())
            hi_key = keys[-1]
            next_key = keys[-2]
            self.store[next_key] += self.store[hi_key]
            del self.store[hi_key]
