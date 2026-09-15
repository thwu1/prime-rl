"""
DDSketch: A quantile sketch with relative-error guarantees.

Implements the DDSketch algorithm for computing approximate quantiles
of streaming data. For a configured accuracy parameter alpha, the
sketch guarantees that returned quantile values have a relative error
of at most alpha (before any collapse).

The sketch uses logarithmic bucket mapping with base gamma =
(1+alpha)/(1-alpha), so bucket i covers the range (gamma^(i-1),
gamma^i]. The representative value for bucket i is
2*gamma^i / (1+gamma), which lies at the harmonic midpoint
of the bucket and guarantees relative error <= alpha.

When the number of bins exceeds max_num_bins, the sketch collapses
by halving all keys (ceil(k/2)) and squaring gamma, which is
equivalent to doubling the bucket width. This increases alpha but
preserves the structural invariants.

Reference: DDSketch: A Fast and Fully-Mergeable Quantile Sketch
with Relative-Error Guarantees (PVLDB 2019)
"""

import math
from collections import defaultdict


class DDSketch:

    def __init__(self, alpha=0.01, max_num_bins=2048):
        self.alpha = alpha
        self.gamma = (1 + alpha) / (1 - alpha)
        self.log_gamma = math.log(self.gamma)
        self.multiplier = 1.0 / self.log_gamma
        self.max_num_bins = max_num_bins
        self.store = defaultdict(int)
        self.count = 0
        self.min_value = float('inf')
        self.max_value = float('-inf')

    def _key(self, value):
        if value <= 0:
            raise ValueError("DDSketch only supports positive values")
        return math.ceil(math.log(value) * self.multiplier)

    def add(self, value):
        if value <= 0:
            return
        key = self._key(value)
        self.store[key] += 1
        self.count += 1
        self.min_value = min(self.min_value, value)
        self.max_value = max(self.max_value, value)
        while len(self.store) > self.max_num_bins:
            self.collapse()

    def merge(self, other):
        if other.count == 0:
            return
        for key, cnt in other.store.items():
            self.store[key] += cnt
        self.count += other.count
        self.min_value = min(self.min_value, other.min_value)
        self.max_value = max(self.max_value, other.max_value)
        while len(self.store) > self.max_num_bins:
            self.collapse()

    def collapse(self):
        new_store = defaultdict(int)
        for key, cnt in self.store.items():
            new_key = (key + 1) // 2
            new_store[new_key] += cnt
        self.store = new_store
        self.gamma = self.gamma * self.gamma
        self.alpha = (self.gamma - 1) / (self.gamma + 1)
        self.log_gamma = math.log(self.gamma)
        self.multiplier = 1.0 / self.log_gamma

    def quantile(self, q):
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
                return 2.0 * (self.gamma ** key) / (1.0 + self.gamma)
        return self.max_value
