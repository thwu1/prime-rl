"""
Interval Set Library

Represents sets of integers as sorted lists of disjoint, non-adjacent,
non-empty half-open intervals [(lo, hi), ...] where each interval
represents {lo, lo+1, ..., hi-1}.

Invariants for a valid IntervalSet:
- Each interval (lo, hi) satisfies lo < hi
- Intervals are sorted by lo
- Consecutive intervals satisfy: prev_hi < next_lo (non-overlapping, non-adjacent)
"""



def validate(iset):
    """Check invariants. Returns True or raises ValueError."""
    for idx, (lo, hi) in enumerate(iset):
        if lo >= hi:
            raise ValueError(f"Empty or inverted interval at {idx}: [{lo}, {hi})")
        if idx > 0:
            prev_hi = iset[idx - 1][1]
            if lo <= prev_hi:
                raise ValueError(
                    f"Not strictly separated at {idx-1},{idx}: "
                    f"prev_hi={prev_hi}, next_lo={lo}"
                )
    return True


def from_points(points):
    """Create a normalized IntervalSet from an iterable of integer points."""
    pts = sorted(set(int(p) for p in points))
    if not pts:
        return []
    result = []
    lo = pts[0]
    hi = lo + 1
    for p in pts[1:]:
        if p == hi:
            hi += 1
        else:
            result.append((lo, hi))
            lo = p
            hi = p + 1
    result.append((lo, hi))
    return result


def to_points(iset):
    """Expand an IntervalSet to a sorted list of integer points."""
    points = []
    for lo, hi in iset:
        points.extend(range(lo, hi))
    return points


def _merge_into(result, interval):
    """Append interval to result, merging with the last entry if they overlap."""
    lo, hi = interval
    if result and result[-1][1] > lo:
        prev_lo, prev_hi = result[-1]
        result[-1] = (prev_lo, max(prev_hi, hi))
    else:
        result.append((lo, hi))


def union(a, b):
    """Return the union of two IntervalSets."""
    result = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i][0] <= b[j][0]:
            _merge_into(result, a[i])
            i += 1
        else:
            _merge_into(result, b[j])
            j += 1
    while i < len(a):
        _merge_into(result, a[i])
        i += 1
    while j < len(b):
        _merge_into(result, b[j])
        j += 1
    return result


def intersection(a, b):
    """Return the intersection of two IntervalSets."""
    result = []
    i = j = 0
    while i < len(a) and j < len(b):
        lo = max(a[i][0], b[j][0])
        hi = min(a[i][1], b[j][1])
        if lo <= hi:  # non-empty intersection
            result.append((lo, hi))
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    return result


def difference(a, b):
    """Return a minus b (elements in a but not in b)."""
    result = []
    i = j = 0
    cur_lo = None  # tracks adjusted start of current a-interval fragment
    while i < len(a):
        a_lo = cur_lo if cur_lo is not None else a[i][0]
        a_hi = a[i][1]

        if j >= len(b) or a_hi <= b[j][0]:
            # no b-interval overlaps with current a fragment
            result.append((a_lo, a_hi))
            i += 1
            cur_lo = None
            continue

        b_lo, b_hi = b[j]

        if b_hi <= a_lo:
            # b[j] is entirely before current a fragment
            j += 1
            continue

        # overlap exists
        if a_lo < b_lo:
            result.append((a_lo, b_lo))

        if a_hi <= b_hi:
            # current a fragment is fully consumed
            i += 1
            cur_lo = None
            j += 1  # advance past this b interval
        else:
            # a extends beyond b[j]; continue with remainder
            cur_lo = b_hi
            j += 1

    return result


def complement(iset, lo, hi):
    """Return the complement of iset within the range [lo, hi).

    The result contains all integers in [lo, hi) that are not in iset.
    """
    raise NotImplementedError("complement is not yet implemented")


def symmetric_difference(a, b):
    """Return the symmetric difference of two IntervalSets.

    Contains elements that are in exactly one of a or b.
    """
    raise NotImplementedError("symmetric_difference is not yet implemented")


def normalize(raw_intervals):
    """Convert an arbitrary list of intervals into a valid IntervalSet.

    Handles unsorted, overlapping, adjacent, and empty (lo >= hi) intervals.
    Filters out invalid intervals and merges overlapping/adjacent ones.
    """
    raise NotImplementedError("normalize is not yet implemented")
