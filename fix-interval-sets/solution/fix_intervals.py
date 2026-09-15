#!/usr/bin/env python3
"""Fix bugs and implement missing functions in /app/intervals.py.

Bug 1 (_merge_into): Uses > instead of >= — adjacent intervals not merged.
Bug 2 (intersection): Uses <= instead of < — produces empty intervals.
Bug 3 (difference): Premature j advancement when a-fragment is consumed.
"""


with open('/app/intervals.py', 'r') as f:
    code = f.read()

# === Bug Fix 1: _merge_into comparison ===
# Adjacent intervals like [1,3) and [3,5) must merge; requires >= not >
code = code.replace(
    "if result and result[-1][1] > lo:",
    "if result and result[-1][1] >= lo:",
    1
)

# === Bug Fix 2: intersection empty-interval check ===
# When endpoints coincide (e.g. lo=hi=5), no points are shared
code = code.replace(
    "if lo <= hi:  # non-empty intersection\n",
    "if lo < hi:\n",
    1
)

# === Bug Fix 3: difference premature iterator advancement ===
# When a-fragment is consumed by b[j], b[j] may still overlap a[i+1]
code = code.replace(
    "            j += 1  # advance past this b interval\n",
    "",
    1
)

# === Implement complement ===
old_complement = '''def complement(iset, lo, hi):
    """Return the complement of iset within the range [lo, hi).

    The result contains all integers in [lo, hi) that are not in iset.
    """
    raise NotImplementedError("complement is not yet implemented")'''

new_complement = '''def complement(iset, lo, hi):
    """Return the complement of iset within the range [lo, hi)."""
    if lo >= hi:
        return []
    result = []
    cur = lo
    for iv_lo, iv_hi in iset:
        if iv_hi <= lo:
            continue
        if iv_lo >= hi:
            break
        clipped_lo = max(iv_lo, lo)
        if cur < clipped_lo:
            result.append((cur, clipped_lo))
        cur = max(cur, min(iv_hi, hi))
    if cur < hi:
        result.append((cur, hi))
    return result'''

code = code.replace(old_complement, new_complement)

# === Implement symmetric_difference ===
old_symdiff = '''def symmetric_difference(a, b):
    """Return the symmetric difference of two IntervalSets.

    Contains elements that are in exactly one of a or b.
    """
    raise NotImplementedError("symmetric_difference is not yet implemented")'''

new_symdiff = '''def symmetric_difference(a, b):
    """Return the symmetric difference of two IntervalSets."""
    return union(difference(a, b), difference(b, a))'''

code = code.replace(old_symdiff, new_symdiff)

# === Implement normalize ===
old_normalize = '''def normalize(raw_intervals):
    """Convert an arbitrary list of intervals into a valid IntervalSet.

    Handles unsorted, overlapping, adjacent, and empty (lo >= hi) intervals.
    Filters out invalid intervals and merges overlapping/adjacent ones.
    """
    raise NotImplementedError("normalize is not yet implemented")'''

new_normalize = '''def normalize(raw_intervals):
    """Convert an arbitrary list of intervals into a valid IntervalSet."""
    filtered = sorted((lo, hi) for lo, hi in raw_intervals if lo < hi)
    if not filtered:
        return []
    result = [filtered[0]]
    for lo, hi in filtered[1:]:
        prev_lo, prev_hi = result[-1]
        if lo <= prev_hi:
            result[-1] = (prev_lo, max(prev_hi, hi))
        else:
            result.append((lo, hi))
    return result'''

code = code.replace(old_normalize, new_normalize)

with open('/app/intervals.py', 'w') as f:
    f.write(code)

# --- Verification ---
import sys
sys.path.insert(0, '/app')
import importlib
import intervals as iv
importlib.reload(iv)

# Verify bug fix 1: adjacent intervals merge
r = iv.union([(1, 3)], [(3, 5)])
assert r == [(1, 5)], f"Bug fix 1 failed: {r}"
iv.validate(r)

# Verify bug fix 2: no empty intervals from intersection
r = iv.intersection([(1, 5)], [(5, 10)])
assert r == [], f"Bug fix 2 failed: {r}"

# Verify bug fix 3: no premature advancement
r = iv.difference([(1, 5), (6, 10)], [(3, 7)])
assert r == [(1, 3), (7, 10)], f"Bug fix 3 failed: {r}"

# Verify complement
r = iv.complement([(2, 5), (8, 10)], 0, 15)
assert r == [(0, 2), (5, 8), (10, 15)], f"complement failed: {r}"

# Verify symmetric_difference
r = iv.symmetric_difference([(1, 5)], [(3, 8)])
assert r == [(1, 3), (5, 8)], f"symmetric_difference failed: {r}"

# Verify normalize
r = iv.normalize([(5, 8), (1, 3), (3, 7), (20, 20)])
assert r == [(1, 8)], f"normalize failed: {r}"

print("All fixes and implementations verified successfully")
