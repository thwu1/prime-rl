#!/usr/bin/env python3
"""

Fix the five bugs in /app/cqf.py:

Bug 1 — _find_run_start: the run-end counting walk begins at
        cluster_start + 1 instead of cluster_start, skipping a potential
        run-end marker at the very first slot of the cluster.

Bug 2 — _shift_slots_right: the is_runend flag is not copied when
        slot data is moved rightward, leaving stale metadata.

Bug 3 — merge: overlapping counts are combined with max() instead of
        being summed.

Bug 4 — resize: new quotient is computed as old_q * 2, discarding the
        MSB of the old remainder that should become the new quotient's LSB.

Bug 5 — inner_product: uses min(a, b) instead of a * b.
"""

import re

SRC = "/app/cqf.py"

with open(SRC, "r") as f:
    code = f.read()

# ------------------------------------------------------------------
# Fix 1: _find_run_start — walk from cluster_start, not cluster_start+1
# ------------------------------------------------------------------
code = code.replace(
    "pos = (cluster_start + 1) % self.size",
    "pos = cluster_start",
    1,  # only the first occurrence
)

# ------------------------------------------------------------------
# Fix 2: _shift_slots_right — copy is_runend along with data
# ------------------------------------------------------------------
old_shift = """\
            self.remainders[pos] = self.remainders[prev]
            self.counts[pos] = self.counts[prev]
            pos = prev"""

new_shift = """\
            self.remainders[pos] = self.remainders[prev]
            self.counts[pos] = self.counts[prev]
            self.is_runend[pos] = self.is_runend[prev]
            pos = prev"""

code = code.replace(old_shift, new_shift, 1)

# ------------------------------------------------------------------
# Fix 3: merge — sum counts instead of taking the maximum
# ------------------------------------------------------------------
code = code.replace(
    "entries[key] = max(entries[key], c)",
    "entries[key] = entries[key] + c",
    1,
)

# ------------------------------------------------------------------
# Fix 4: resize — incorporate old remainder's MSB into new quotient
# ------------------------------------------------------------------
code = code.replace(
    "new_q = old_q * 2",
    "new_q = (old_q << 1) | (old_r >> (old_r_bits - 1))",
    1,
)

# ------------------------------------------------------------------
# Fix 5: inner_product — multiply instead of min
# ------------------------------------------------------------------
code = code.replace(
    "total += min(c_self, c_other)",
    "total += c_self * c_other",
    1,
)

with open(SRC, "w") as f:
    f.write(code)

print("All five bugs fixed.")
