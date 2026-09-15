"""
Tests for the merge schedule optimizer.

"""

import sys
import time
import random

sys.path.insert(0, "/app")

import pytest
from scheduler import compute_schedule


# ---------------------------------------------------------------------------
# Self-contained helper functions (not imported from /app to prevent tampering)
# ---------------------------------------------------------------------------

def _compute_tree_cost(tree, run_lengths):
    """Compute total merge cost from a merge tree (iterative)."""
    if tree is None or isinstance(tree, int):
        return 0
    size_cache = {}
    cost = 0
    stack = [(tree, False)]
    while stack:
        node, processed = stack.pop()
        if isinstance(node, int):
            size_cache[id(node)] = run_lengths[node]
            continue
        if processed:
            left, right = node
            ls = size_cache.get(id(left), run_lengths[left] if isinstance(left, int) else 0)
            rs = size_cache.get(id(right), run_lengths[right] if isinstance(right, int) else 0)
            merged = ls + rs
            cost += merged
            size_cache[id(node)] = merged
        else:
            stack.append((node, True))
            stack.append((node[1], False))
            stack.append((node[0], False))
    return cost


def _tree_leaves(tree):
    """Collect leaf indices in left-to-right order (iterative)."""
    if tree is None:
        return []
    if isinstance(tree, int):
        return [tree]
    leaves = []
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, int):
            leaves.append(node)
        else:
            stack.append(node[1])
            stack.append(node[0])
    return leaves


def _reference_optimal_cost(run_lengths):
    """O(n^2) reference DP with Knuth's optimization for exact optimal cost."""
    n = len(run_lengths)
    if n <= 1:
        return 0
    prefix = [0] * (n + 1)
    for i in range(n):
        prefix[i + 1] = prefix[i] + run_lengths[i]
    INF = float("inf")
    dp = [[INF] * n for _ in range(n)]
    opt = [[0] * n for _ in range(n)]
    for i in range(n):
        dp[i][i] = 0
        opt[i][i] = i
    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            total = prefix[j + 1] - prefix[i]
            lo_k = opt[i][j - 1]
            hi_k = opt[i + 1][j] if i + 1 <= j else j - 1
            hi_k = min(hi_k, j - 1)
            for k in range(lo_k, hi_k + 1):
                c = dp[i][k] + dp[k + 1][j] + total
                if c < dp[i][j]:
                    dp[i][j] = c
                    opt[i][j] = k
    return dp[0][n - 1]


def _balanced_merge_cost(run_lengths):
    """Cost of a balanced binary merge tree (split at midpoint)."""
    n = len(run_lengths)
    if n <= 1:
        return 0

    def build(lo, hi):
        if lo == hi:
            return lo
        mid = (lo + hi) // 2
        return (build(lo, mid), build(mid + 1, hi))

    tree = build(0, n - 1)
    return _compute_tree_cost(tree, run_lengths)


# ---------------------------------------------------------------------------
# Tests: tree structure validity
# ---------------------------------------------------------------------------

class TestTreeValidity:
    def test_empty(self):
        cost, tree = compute_schedule([])
        assert cost == 0

    def test_single_run(self):
        cost, tree = compute_schedule([42])
        assert cost == 0
        assert tree == 0

    def test_two_runs(self):
        cost, tree = compute_schedule([10, 20])
        assert cost == 30
        leaves = _tree_leaves(tree)
        assert leaves == [0, 1]

    def test_leaves_order_various_sizes(self):
        """Leaves must appear in order 0..n-1 for all sizes."""
        for n in [3, 5, 8, 13, 21, 50]:
            rng = random.Random(n)
            run_lengths = [rng.randint(1, 100) for _ in range(n)]
            cost, tree = compute_schedule(run_lengths)
            leaves = _tree_leaves(tree)
            assert leaves == list(range(n)), f"n={n}: leaves out of order"

    def test_cost_matches_tree_structure(self):
        """Reported cost must exactly match the cost implied by the tree."""
        for n in [3, 5, 8, 13, 20, 50]:
            rng = random.Random(n + 42)
            run_lengths = [rng.randint(1, 100) for _ in range(n)]
            cost, tree = compute_schedule(run_lengths)
            actual = _compute_tree_cost(tree, run_lengths)
            assert cost == actual, (
                f"n={n}: reported cost {cost} != actual tree cost {actual}"
            )


# ---------------------------------------------------------------------------
# Tests: known small optimal cases
# ---------------------------------------------------------------------------

class TestKnownOptimal:
    def test_two_runs_simple(self):
        cost, _ = compute_schedule([10, 20])
        assert cost == 30

    def test_three_runs_skewed(self):
        """Optimal: merge the two small runs first."""
        cost, _ = compute_schedule([1, 1, 100])
        assert cost == 104

    def test_four_equal_runs(self):
        """Optimal: balanced merge."""
        cost, _ = compute_schedule([10, 10, 10, 10])
        assert cost == 80

    def test_five_increasing(self):
        """Optimal is 33; accept up to 35 (within ~6%)."""
        cost, _ = compute_schedule([1, 2, 3, 4, 5])
        ref = _reference_optimal_cost([1, 2, 3, 4, 5])
        assert cost <= ref * 1.06, f"cost {cost} > 1.06 * optimal {ref}"


# ---------------------------------------------------------------------------
# Tests: near-optimality across distributions
# ---------------------------------------------------------------------------

class TestNearOptimal:
    def test_random_medium_seeds(self):
        """Within 5% of optimal on 10 different random distributions (n=100)."""
        for seed in range(10):
            rng = random.Random(seed + 200)
            run_lengths = [rng.randint(1, 100) for _ in range(100)]
            cost, tree = compute_schedule(run_lengths)
            ref = _reference_optimal_cost(run_lengths)
            assert ref > 0
            ratio = cost / ref
            assert ratio <= 1.05, (
                f"seed={seed}: cost {cost}, optimal {ref}, ratio {ratio:.4f}"
            )

    def test_geometric_increasing(self):
        run_lengths = [max(1, int(1.5 ** i)) for i in range(30)]
        cost, tree = compute_schedule(run_lengths)
        ref = _reference_optimal_cost(run_lengths)
        assert cost <= ref * 1.05, f"cost {cost} > 1.05 * optimal {ref}"

    def test_geometric_decreasing(self):
        run_lengths = [max(1, int(1.5 ** (29 - i))) for i in range(30)]
        cost, tree = compute_schedule(run_lengths)
        ref = _reference_optimal_cost(run_lengths)
        assert cost <= ref * 1.05, f"cost {cost} > 1.05 * optimal {ref}"

    def test_alternating_short_long(self):
        run_lengths = [1 if i % 2 == 0 else 100 for i in range(40)]
        cost, tree = compute_schedule(run_lengths)
        ref = _reference_optimal_cost(run_lengths)
        assert cost <= ref * 1.05, f"cost {cost} > 1.05 * optimal {ref}"

    def test_single_spike(self):
        run_lengths = [10] * 25 + [10000] + [10] * 24
        cost, tree = compute_schedule(run_lengths)
        ref = _reference_optimal_cost(run_lengths)
        assert cost <= ref * 1.05, f"cost {cost} > 1.05 * optimal {ref}"

    def test_fibonacci_like(self):
        fib = [1, 1]
        for _ in range(18):
            fib.append(fib[-1] + fib[-2])
        cost, tree = compute_schedule(fib)
        ref = _reference_optimal_cost(fib)
        assert cost <= ref * 1.05, f"cost {cost} > 1.05 * optimal {ref}"

    def test_nearly_equal(self):
        rng = random.Random(77)
        run_lengths = [100 + rng.randint(-5, 5) for _ in range(60)]
        cost, tree = compute_schedule(run_lengths)
        ref = _reference_optimal_cost(run_lengths)
        assert cost <= ref * 1.05, f"cost {cost} > 1.05 * optimal {ref}"


# ---------------------------------------------------------------------------
# Tests: must outperform balanced baseline on skewed distributions
# ---------------------------------------------------------------------------

class TestBeatsBalanced:
    def test_exponential_powers(self):
        """Powers of 2: balanced tree is very suboptimal here."""
        run_lengths = [2 ** i for i in range(20)]
        cost_ours, _ = compute_schedule(run_lengths)
        cost_balanced = _balanced_merge_cost(run_lengths)
        assert cost_ours < cost_balanced * 0.85, (
            f"cost {cost_ours} not 15%+ better than balanced {cost_balanced}"
        )

    def test_one_dominant_run(self):
        """One huge run among many tiny ones."""
        run_lengths = [1] * 30 + [100000]
        cost_ours, _ = compute_schedule(run_lengths)
        cost_balanced = _balanced_merge_cost(run_lengths)
        assert cost_ours < cost_balanced * 0.85, (
            f"cost {cost_ours} not 15%+ better than balanced {cost_balanced}"
        )

    def test_geometric_steep(self):
        """Steeply increasing geometric."""
        run_lengths = [max(1, int(3 ** i)) for i in range(15)]
        cost_ours, _ = compute_schedule(run_lengths)
        cost_balanced = _balanced_merge_cost(run_lengths)
        assert cost_ours < cost_balanced * 0.85, (
            f"cost {cost_ours} not 15%+ better than balanced {cost_balanced}"
        )


# ---------------------------------------------------------------------------
# Tests: performance on large inputs
# ---------------------------------------------------------------------------

class TestPerformance:
    def test_200k_runs(self):
        """200,000 runs must complete within 5 seconds."""
        rng = random.Random(42)
        run_lengths = [rng.randint(1, 1000) for _ in range(200000)]
        start = time.time()
        cost, tree = compute_schedule(run_lengths)
        elapsed = time.time() - start

        assert elapsed < 5.0, f"Took {elapsed:.1f}s (limit 5s)"
        assert cost > 0, "Cost must be positive for multiple runs"

        leaves = _tree_leaves(tree)
        assert len(leaves) == 200000, f"Expected 200000 leaves, got {len(leaves)}"
        assert leaves[0] == 0, "First leaf must be 0"
        assert leaves[-1] == 199999, "Last leaf must be 199999"

    def test_50k_runs_tree_valid(self):
        """50,000 runs: full leaf order validation."""
        rng = random.Random(99)
        run_lengths = [rng.randint(1, 500) for _ in range(50000)]
        cost, tree = compute_schedule(run_lengths)
        leaves = _tree_leaves(tree)
        assert leaves == list(range(50000))
        actual_cost = _compute_tree_cost(tree, run_lengths)
        assert cost == actual_cost
