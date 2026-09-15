#!/usr/bin/env python3
"""
Fix the buggy DDSketch implementation at /app/sketch.py.

The implementation has multiple subtly incorrect behaviors that must be
identified by evaluating each method against the DDSketch specification:

1. __init__: multiplier uses 1/ln(2) (log base 2 mapping) instead of
   1/ln(gamma) (log base gamma mapping). The DDSketch requires buckets
   defined by powers of gamma, not powers of 2.

2. _key(): uses floor() instead of ceil(). With ceil, bucket i covers
   the range (gamma^(i-1), gamma^i], ensuring values map to the correct
   bucket for the relative-error guarantee.

3. add(): does not call collapse() when the number of bins exceeds
   max_num_bins, allowing unbounded memory growth.

4. merge(): uses max() to combine per-bucket counts instead of +=.
   This loses count information — merge must sum counts since each
   sketch independently accumulated data. Also fails to update
   min_value and max_value from the other sketch.

5. collapse(): uses key >> 1 (integer halving of keys) which destroys
   the logarithmic bucket mapping invariant. Correct collapse merges
   two adjacent bins with the lowest combined count, preserving the
   bucket-to-value mapping for all other bins.

6. quantile(): reconstructs values as 2^key instead of the correct
   representative value 2*gamma^key/(1+gamma), which is the harmonic
   midpoint of the bucket [gamma^(key-1), gamma^key] and guarantees
   relative error <= alpha.
"""

import math

# Verify the mathematical properties of the representative value
alpha = 0.01
gamma = (1 + alpha) / (1 - alpha)

# Representative = 2*gamma^i/(1+gamma) lies in [gamma^(i-1), gamma^i]
# At lower bound: ratio = 2*gamma/(1+gamma) = 2*(1+alpha)/2 = 1+alpha
# At upper bound: ratio = 2/(1+gamma) = 2*(1-alpha)/2 = 1-alpha
# So relative error is exactly alpha at boundaries, less inside. QED.
assert abs(2 * gamma / (1 + gamma) - (1 + alpha)) < 1e-12
assert abs(2 / (1 + gamma) - (1 - alpha)) < 1e-12

corrected_source = '''"""
DDSketch: A quantile sketch with relative-error guarantees.

Implements the DDSketch algorithm using logarithmic bucket mapping
where gamma = (1+alpha)/(1-alpha). For any value v in bucket i,
the representative value r satisfies |r - v| / v <= alpha.

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
        self.zero_count = 0
        self.count = 0
        self.min_value = float('inf')
        self.max_value = float('-inf')

    def _key(self, value):
        """Map a positive value to its bucket index.

        Uses ceil(log_gamma(value)) so that bucket i covers
        the range (gamma^(i-1), gamma^i].
        """
        if value <= 0:
            raise ValueError("Cannot compute key for non-positive value")
        return math.ceil(math.log(value) * self.multiplier)

    def add(self, value):
        """Add a value to the sketch."""
        if value < 0:
            return
        if value == 0:
            self.zero_count += 1
            self.count += 1
            self.min_value = min(self.min_value, 0.0)
            self.max_value = max(self.max_value, 0.0)
            return

        key = self._key(value)
        self.store[key] += 1
        self.count += 1
        self.min_value = min(self.min_value, value)
        self.max_value = max(self.max_value, value)

        if len(self.store) > self.max_num_bins:
            self.collapse()

    def merge(self, other):
        """Merge another DDSketch into this one.

        Sums corresponding bucket counts. Since both sketches use
        the same gamma, bucket indices are directly compatible.
        """
        if other.count == 0:
            return

        for key, cnt in other.store.items():
            self.store[key] += cnt

        self.zero_count += other.zero_count
        self.count += other.count

        if other.min_value < self.min_value:
            self.min_value = other.min_value
        if other.max_value > self.max_value:
            self.max_value = other.max_value

        while len(self.store) > self.max_num_bins:
            self.collapse()

    def collapse(self):
        """Collapse bins by merging the two adjacent bins with lowest
        combined count, reducing bin count by one."""
        if len(self.store) <= 1:
            return

        sorted_keys = sorted(self.store.keys())
        min_combined = float('inf')
        merge_idx = 0

        for i in range(len(sorted_keys) - 1):
            combined = self.store[sorted_keys[i]] + self.store[sorted_keys[i + 1]]
            if combined < min_combined:
                min_combined = combined
                merge_idx = i

        lower_key = sorted_keys[merge_idx]
        upper_key = sorted_keys[merge_idx + 1]
        self.store[lower_key] += self.store[upper_key]
        del self.store[upper_key]

    def quantile(self, q):
        """Compute the q-th quantile (0 <= q <= 1).

        Returns 2 * gamma^key / (1 + gamma), the harmonic midpoint
        of the bucket, which guarantees relative error <= alpha.
        """
        if self.count == 0:
            return 0

        if q <= 0:
            return self.min_value
        if q >= 1:
            return self.max_value

        target_rank = q * self.count
        running_count = 0

        # Account for zeros first
        running_count += self.zero_count
        if running_count >= target_rank and self.zero_count > 0:
            return 0.0

        for key in sorted(self.store.keys()):
            running_count += self.store[key]
            if running_count >= target_rank:
                return 2.0 * (self.gamma ** key) / (1.0 + self.gamma)

        return self.max_value
'''

with open('/app/sketch.py', 'w') as f:
    f.write(corrected_source)

print("Fixed sketch.py: corrected log mapping, rounding, merge, collapse, quantile")
