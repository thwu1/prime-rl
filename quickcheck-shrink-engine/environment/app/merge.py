"""Interval merging — property evaluation exercise.

merge_intervals_v1 is the REFERENCE (correct) implementation.
merge_intervals_v2 has a known bug.

TASK: Evaluate the four properties below. For each, determine whether it is:
  - "sound":  true for v1, false for v2 on at least one input
  - "weak":   true for both v1 and v2 on all inputs (doesn't detect the bug)
  - "strong": false even for v1 on at least one input (rejects correct code)

Write your classifications to /app/property_audit_results.json as:
  {"prop_idempotent": "...", "prop_covers_all": "...",
   "prop_no_growth": "...", "prop_each_preserved": "..."}
"""


def merge_intervals_v1(intervals):
    """Correct implementation: merge overlapping or adjacent intervals.

    Input: list of (lo, hi) integer pairs in arbitrary order.
    Output: sorted, non-overlapping list covering the same integer points.
    """
    if not intervals:
        return []
    sorted_ivs = sorted(intervals)
    merged = [list(sorted_ivs[0])]
    for lo, hi in sorted_ivs[1:]:
        if lo <= merged[-1][1]:
            merged[-1] = [merged[-1][0], max(merged[-1][1], hi)]
        else:
            merged.append([lo, hi])
    return [tuple(x) for x in merged]


def merge_intervals_v2(intervals):
    """Buggy implementation: has a subtle error when merging contained intervals."""
    if not intervals:
        return []
    sorted_ivs = sorted(intervals)
    merged = [list(sorted_ivs[0])]
    for lo, hi in sorted_ivs[1:]:
        if lo <= merged[-1][1]:
            merged[-1][1] = hi
        else:
            merged.append([lo, hi])
    return [tuple(x) for x in merged]


# ---------------------------------------------------------------------------
# Candidate properties — each takes (merge_fn, intervals) -> bool
# ---------------------------------------------------------------------------

def prop_idempotent(merge_fn, intervals):
    """Merging the already-merged output again produces the same result."""
    once = merge_fn(intervals)
    twice = merge_fn(once)
    return once == twice


def prop_covers_all(merge_fn, intervals):
    """Every integer point in some input interval is in some output interval."""
    merged = merge_fn(intervals)
    for lo, hi in intervals:
        for p in range(lo, min(hi, lo + 200)):
            if not any(mlo <= p < mhi for mlo, mhi in merged):
                return False
    return True


def prop_no_growth(merge_fn, intervals):
    """No output interval is wider than the widest input interval."""
    if not intervals:
        return True
    merged = merge_fn(intervals)
    if not merged:
        return True
    max_input_width = max(hi - lo for lo, hi in intervals)
    max_output_width = max(hi - lo for lo, hi in merged)
    return max_output_width <= max_input_width


def prop_each_preserved(merge_fn, intervals):
    """Every input interval is a subset of (contained within) some output interval."""
    merged = merge_fn(intervals)
    for in_lo, in_hi in intervals:
        if not any(mlo <= in_lo and in_hi <= mhi for mlo, mhi in merged):
            return False
    return True
