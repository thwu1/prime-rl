"""
Balanced binary merge: split runs at the midpoint regardless of run lengths.

O(n) time but ignores length distribution, giving poor results on skewed inputs.

"""


def compute_schedule(run_lengths):
    """Balanced: recursively split runs at the midpoint."""
    n = len(run_lengths)
    if n == 0:
        return (0, None)
    if n == 1:
        return (0, 0)

    def build(lo, hi):
        if lo == hi:
            return lo
        mid = (lo + hi) // 2
        return (build(lo, mid), build(mid + 1, hi))

    tree = build(0, n - 1)

    def tree_cost(t):
        if isinstance(t, int):
            return run_lengths[t], 0
        left_len, left_cost = tree_cost(t[0])
        right_len, right_cost = tree_cost(t[1])
        merged = left_len + right_len
        return merged, left_cost + right_cost + merged

    _, cost = tree_cost(tree)
    return (cost, tree)
