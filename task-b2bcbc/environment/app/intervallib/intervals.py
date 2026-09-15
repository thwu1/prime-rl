"""Half-open interval [start, end) arithmetic operations."""


def overlaps(a, b):
    """Check if half-open intervals a=[a0,a1) and b=[b0,b1) overlap."""
    return a[0] < b[1] and b[0] < a[1]


def merge(intervals):
    """Merge a list of (start, end) half-open intervals into sorted non-overlapping list."""
    if not intervals:
        return []
    s = sorted(intervals)
    result = [list(s[0])]
    for start, end in s[1:]:
        if start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return [tuple(r) for r in result]


def complement(intervals, lo, hi):
    """Return intervals in [lo, hi) not covered by the input intervals."""
    merged = merge(intervals)
    gaps = []
    current = lo
    for start, end in merged:
        if start > current:
            gaps.append((current, start))
        if end > current:
            current = end
    if current < hi:
        gaps.append((current, hi))
    return gaps


def coverage(intervals, lo, hi):
    """Calculate the fraction of [lo, hi) covered by the given intervals."""
    if hi <= lo:
        return 0.0
    merged = merge(intervals)
    total = 0.0
    for start, end in merged:
        cs = max(start, lo)
        ce = min(end, hi)
        if cs < ce:
            total += ce - cs
    return total / (hi - lo)


def intersection(a, b):
    """Return the intersection of two half-open intervals, or None if disjoint."""
    s = max(a[0], b[0])
    e = min(a[1], b[1])
    if s < e:
        return (s, e)
    return None


def symmetric_difference(intervals_a, intervals_b, lo, hi):
    """Return intervals in [lo, hi) covered by exactly one of the two interval sets."""
    merged_a = merge(intervals_a)
    merged_b = merge(intervals_b)
    all_intervals = merge(merged_a + merged_b)
    both = []
    i, j = 0, 0
    while i < len(merged_a) and j < len(merged_b):
        s = max(merged_a[i][0], merged_b[j][0])
        e = min(merged_a[i][1], merged_b[j][1])
        if s < e:
            both.append((s, e))
        if merged_a[i][1] < merged_b[j][1]:
            i += 1
        else:
            j += 1
    result = complement(both, lo, hi)
    final = []
    for r in result:
        for u in all_intervals:
            inter = intersection(r, u)
            if inter:
                final.append(inter)
    return merge(final)
