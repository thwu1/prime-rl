"""
Near-optimal merge scheduling using weight-balanced binary splitting.

Recursively splits the run sequence at the point where the cumulative weight
is closest to half, producing a tree where heavy runs are near the root and
light runs are deeper. This naturally handles skewed distributions (spikes,
geometric, dominant-run) that are adversarial for simpler heuristics.

"""


def compute_schedule(run_lengths):
    """Compute a near-optimal merge schedule using weight-balanced splitting.

    Args:
        run_lengths: list of positive integers, length of each run

    Returns:
        (cost, merge_tree) where cost is the total merge cost and
        merge_tree is a nested binary tree with integer leaves 0..n-1.
    """
    n = len(run_lengths)
    if n == 0:
        return (0, None)
    if n == 1:
        return (0, 0)

    # Prefix sums for O(1) range-sum queries
    prefix = [0] * (n + 1)
    for i in range(n):
        prefix[i + 1] = prefix[i] + run_lengths[i]

    # Phase 1: compute weight-balanced split points iteratively
    # For each interval [lo, hi], find k in [lo, hi-1] such that
    # prefix[k+1] is closest to the midpoint of [prefix[lo], prefix[hi+1]].
    splits = {}
    work = [(0, n - 1)]
    while work:
        lo, hi = work.pop()
        if lo >= hi:
            continue

        target = (prefix[lo] + prefix[hi + 1]) * 0.5

        # Binary search for k in [lo, hi-1] where prefix[k+1] ~ target
        left_b, right_b = lo, hi - 1
        while left_b < right_b:
            mid = (left_b + right_b) // 2
            if prefix[mid + 1] < target:
                left_b = mid + 1
            else:
                right_b = mid

        best_k = left_b
        best_diff = abs(prefix[left_b + 1] - target)
        if left_b > lo:
            d = abs(prefix[left_b] - target)
            if d < best_diff:
                best_k = left_b - 1
                best_diff = d
        if left_b + 1 <= hi - 1:
            d = abs(prefix[left_b + 2] - target)
            if d < best_diff:
                best_k = left_b + 1

        splits[(lo, hi)] = best_k
        work.append((lo, best_k))
        work.append((best_k + 1, hi))

    # Phase 2: build tree and compute cost via iterative post-order traversal
    tree_map = {}
    size_map = {}
    cost = 0

    eval_stack = [(0, n - 1, False)]
    while eval_stack:
        lo, hi, done = eval_stack.pop()
        if lo == hi:
            tree_map[(lo, hi)] = lo
            size_map[(lo, hi)] = run_lengths[lo]
            continue
        if done:
            k = splits[(lo, hi)]
            left_tree = tree_map[(lo, k)]
            right_tree = tree_map[(k + 1, hi)]
            tree_map[(lo, hi)] = (left_tree, right_tree)
            ls = size_map[(lo, k)]
            rs = size_map[(k + 1, hi)]
            merged = ls + rs
            cost += merged
            size_map[(lo, hi)] = merged
        else:
            k = splits[(lo, hi)]
            eval_stack.append((lo, hi, True))
            eval_stack.append((k + 1, hi, False))
            eval_stack.append((lo, k, False))

    return (cost, tree_map[(0, n - 1)])
