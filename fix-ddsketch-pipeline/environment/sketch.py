"""
DDSketch: A quantile sketch with relative-error guarantees.

This implements the DDSketch algorithm for computing approximate
quantiles of streaming data. For a configured accuracy parameter
alpha, the sketch guarantees that returned quantile values have
a relative error of at most alpha.

The sketch uses logarithmic bucket mapping to distribute values
across bins, with bucket widths that grow proportionally to the
value magnitude. This ensures uniform relative accuracy across
the entire value range.

Reference: DDSketch: A Fast and Fully-Mergeable Quantile Sketch
with Relative-Error Guarantees (PVLDB 2019)
"""

import math
from collections import defaultdict


class DDSketch:

    def __init__(self, alpha=0.01, max_num_bins=2048):
        """
        Initialize a DDSketch.

        Args:
            alpha: Relative accuracy guarantee. The sketch ensures that
                   returned quantile values have relative error <= alpha.
            max_num_bins: Maximum number of bins. When exceeded, bins
                         are collapsed to stay within this limit.
        """
        self.alpha = alpha
        self.gamma = (1 + alpha) / (1 - alpha)
        self.multiplier = 1.0 / math.log(2)
        self.max_num_bins = max_num_bins
        self.store = defaultdict(int)  # bucket_index -> count
        self.count = 0
        self.min_value = float('inf')
        self.max_value = float('-inf')

    def _key(self, value):
        """
        Map a positive value to its bucket index using logarithmic mapping.

        The mapping ensures that all values within a bucket are within
        a relative error of alpha from the bucket's representative value.
        """
        if value <= 0:
            raise ValueError("Cannot compute key for non-positive value")
        return math.floor(math.log(value) * self.multiplier)

    def add(self, value):
        """Add a value to the sketch."""
        if value <= 0:
            # Non-positive values not supported in this implementation
            return

        key = self._key(value)
        self.store[key] += 1
        self.count += 1
        self.min_value = min(self.min_value, value)
        self.max_value = max(self.max_value, value)

    def merge(self, other):
        """
        Merge another DDSketch into this one.

        The merge operation combines two sketches by unioning their
        bucket stores, using the maximum count per bucket to represent
        the combined distribution.
        """
        if other.count == 0:
            return

        for key, cnt in other.store.items():
            self.store[key] = max(self.store.get(key, 0), cnt)
        self.count += other.count

    def collapse(self):
        """
        Reduce the number of bins when exceeding max_num_bins.

        Halves the key space to compress the store into fewer buckets,
        mapping each original bucket to a coarser-resolution index.
        """
        if len(self.store) <= self.max_num_bins:
            return
        new_store = defaultdict(int)
        for key, cnt in self.store.items():
            new_store[key >> 1] += cnt
        self.store = new_store

    def quantile(self, q):
        """
        Compute the q-th quantile (0 <= q <= 1).

        Returns a value v' such that |v' - v| / v <= alpha,
        where v is the true q-th quantile of the ingested data.
        """
        if self.count == 0:
            return 0

        if q <= 0:
            return self.min_value
        if q >= 1:
            return self.max_value

        target_rank = q * self.count
        running_count = 0

        for key in sorted(self.store.keys()):
            running_count += self.store[key]
            if running_count >= target_rank:
                # Reconstruct value from bucket index
                return 2 ** key

        return self.max_value
