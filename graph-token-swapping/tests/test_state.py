#!/usr/bin/env python3
"""Tests for the token swapping solver.

"""

import sys
import random

sys.path.insert(0, "/app")
from solver import solve


def _verify_solution(n, edges, perm, swaps, max_swaps=None):
    """Verify a swap sequence is valid and realizes the target permutation."""
    edge_set = set()
    for e in edges:
        edge_set.add((min(e[0], e[1]), max(e[0], e[1])))

    state = list(range(n))
    for idx, s in enumerate(swaps):
        u, v = s[0], s[1]
        key = (min(u, v), max(u, v))
        assert key in edge_set, (
            f"Swap #{idx} ({u},{v}) is not a valid edge in the graph"
        )
        assert 0 <= u < n and 0 <= v < n, (
            f"Swap #{idx} ({u},{v}) has vertex out of range [0, {n})"
        )
        state[u], state[v] = state[v], state[u]

    assert state == perm, (
        f"Swap sequence does not produce target permutation.\n"
        f"  Got:      {state}\n"
        f"  Expected: {perm}"
    )

    if max_swaps is not None:
        assert len(swaps) <= max_swaps, (
            f"Too many swaps: {len(swaps)} > {max_swaps}"
        )

    return len(swaps)


def _count_inversions(perm):
    """Count inversions in a permutation using merge sort (O(n log n))."""
    if len(perm) <= 1:
        return 0

    def _merge_count(arr):
        if len(arr) <= 1:
            return arr, 0
        mid = len(arr) // 2
        left, l_inv = _merge_count(arr[:mid])
        right, r_inv = _merge_count(arr[mid:])
        merged = []
        inversions = l_inv + r_inv
        i = j = 0
        while i < len(left) and j < len(right):
            if left[i] <= right[j]:
                merged.append(left[i])
                i += 1
            else:
                merged.append(right[j])
                inversions += len(left) - i
                j += 1
        merged.extend(left[i:])
        merged.extend(right[j:])
        return merged, inversions

    _, inv = _merge_count(list(perm))
    return inv


def _count_cycles(perm):
    """Count the number of disjoint cycles in a permutation."""
    n = len(perm)
    visited = [False] * n
    cycles = 0
    for i in range(n):
        if not visited[i]:
            cycles += 1
            j = i
            while not visited[j]:
                visited[j] = True
                j = perm[j]
    return cycles


# ---------------------------------------------------------------------------
# Path graph tests — require exact optimality (swap count == inversions)
# ---------------------------------------------------------------------------


class TestPathGraphs:
    def test_path_basic(self):
        """Path n=6 with moderate permutation: 9 inversions."""
        n = 6
        edges = [[i, i + 1] for i in range(n - 1)]
        perm = [3, 5, 1, 0, 4, 2]
        expected = _count_inversions(perm)
        swaps = solve(n, edges, perm)
        count = _verify_solution(n, edges, perm, swaps, max_swaps=expected)
        assert count == expected, f"Path not optimal: {count} != {expected}"

    def test_path_reversed(self):
        """Reversed path n=8: C(8,2) = 28 inversions."""
        n = 8
        edges = [[i, i + 1] for i in range(n - 1)]
        perm = list(reversed(range(n)))
        expected = n * (n - 1) // 2
        swaps = solve(n, edges, perm)
        count = _verify_solution(n, edges, perm, swaps, max_swaps=expected)
        assert count == expected, f"Path not optimal: {count} != {expected}"

    def test_path_identity(self):
        """Identity permutation requires 0 swaps."""
        n = 5
        edges = [[i, i + 1] for i in range(n - 1)]
        perm = list(range(n))
        swaps = solve(n, edges, perm)
        _verify_solution(n, edges, perm, swaps, max_swaps=0)

    def test_path_large(self):
        """Path n=200 with deterministic random permutation."""
        n = 200
        edges = [[i, i + 1] for i in range(n - 1)]
        rng = random.Random(42)
        perm = list(range(n))
        rng.shuffle(perm)
        expected = _count_inversions(perm)
        swaps = solve(n, edges, perm)
        count = _verify_solution(n, edges, perm, swaps, max_swaps=expected)
        assert count == expected, f"Path not optimal: {count} != {expected}"


# ---------------------------------------------------------------------------
# Complete graph tests — require exact optimality (swap count == n - cycles)
# ---------------------------------------------------------------------------


class TestCompleteGraphs:
    def test_complete_single_cycle(self):
        """Complete K_8 with single 8-cycle: optimal = 7."""
        n = 8
        edges = [[i, j] for i in range(n) for j in range(i + 1, n)]
        perm = [1, 2, 3, 4, 5, 6, 7, 0]
        expected = n - _count_cycles(perm)
        swaps = solve(n, edges, perm)
        count = _verify_solution(n, edges, perm, swaps, max_swaps=expected)
        assert count == expected, f"Complete not optimal: {count} != {expected}"

    def test_complete_three_transpositions(self):
        """Complete K_6 with three 2-cycles: optimal = 3."""
        n = 6
        edges = [[i, j] for i in range(n) for j in range(i + 1, n)]
        perm = [1, 0, 3, 2, 5, 4]
        expected = n - _count_cycles(perm)
        swaps = solve(n, edges, perm)
        count = _verify_solution(n, edges, perm, swaps, max_swaps=expected)
        assert count == expected, f"Complete not optimal: {count} != {expected}"

    def test_complete_complex_cycles(self):
        """Complete K_10 with mixed cycle structure: (0,3,7)(1,5)(2,9,4,8,6)."""
        n = 10
        edges = [[i, j] for i in range(n) for j in range(i + 1, n)]
        perm = [3, 5, 9, 7, 8, 1, 2, 0, 6, 4]
        expected = n - _count_cycles(perm)
        swaps = solve(n, edges, perm)
        count = _verify_solution(n, edges, perm, swaps, max_swaps=expected)
        assert count == expected, f"Complete not optimal: {count} != {expected}"


# ---------------------------------------------------------------------------
# Tree graph tests — require correctness + bounded suboptimality
# ---------------------------------------------------------------------------


class TestTreeGraphs:
    def test_tree_binary(self):
        """Binary tree n=7 with two independent cycles. Optimal=5, bound=8."""
        n = 7
        edges = [[0, 1], [0, 2], [1, 3], [1, 4], [2, 5], [2, 6]]
        perm = [6, 4, 5, 1, 3, 0, 2]
        swaps = solve(n, edges, perm)
        _verify_solution(n, edges, perm, swaps, max_swaps=8)

    def test_tree_star(self):
        """Star graph n=7 (center=0) with 4-cycle and 2-cycle. Optimal=8, bound=12."""
        n = 7
        edges = [[0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [0, 6]]
        perm = [0, 3, 6, 5, 1, 4, 2]
        swaps = solve(n, edges, perm)
        _verify_solution(n, edges, perm, swaps, max_swaps=12)

    def test_tree_caterpillar(self):
        """Caterpillar tree: path 0-1-2-3-4 with pendant leaves 5-9."""
        n = 10
        edges = [
            [0, 1], [1, 2], [2, 3], [3, 4],
            [0, 5], [1, 6], [2, 7], [3, 8], [4, 9],
        ]
        perm = [5, 6, 7, 8, 9, 0, 1, 2, 3, 4]
        swaps = solve(n, edges, perm)
        _verify_solution(n, edges, perm, swaps, max_swaps=15)


# ---------------------------------------------------------------------------
# Cycle graph test
# ---------------------------------------------------------------------------


class TestCycleGraph:
    def test_cycle_two_rotations(self):
        """Cycle n=8 with two disjoint 4-cycles as rotations."""
        n = 8
        edges = [[i, (i + 1) % n] for i in range(n)]
        perm = [3, 0, 1, 2, 7, 4, 5, 6]
        swaps = solve(n, edges, perm)
        _verify_solution(n, edges, perm, swaps, max_swaps=20)


# ---------------------------------------------------------------------------
# Grid graph test
# ---------------------------------------------------------------------------


class TestGridGraph:
    def test_grid_3x3(self):
        """3x3 grid graph with reversed permutation."""
        n = 9
        edges = []
        for r in range(3):
            for c in range(3):
                v = r * 3 + c
                if c + 1 < 3:
                    edges.append([v, v + 1])
                if r + 1 < 3:
                    edges.append([v, v + 3])
        perm = [8, 7, 6, 5, 4, 3, 2, 1, 0]
        swaps = solve(n, edges, perm)
        _verify_solution(n, edges, perm, swaps, max_swaps=36)


# ---------------------------------------------------------------------------
# General (non-structured) graph test
# ---------------------------------------------------------------------------


class TestGeneralGraph:
    def test_random_connected(self):
        """Random connected graph n=20 with extra edges."""
        n = 20
        rng = random.Random(123)
        edges_set = set()
        for v in range(1, n):
            u = rng.randint(0, v - 1)
            edges_set.add((min(u, v), max(u, v)))
        for _ in range(20):
            u = rng.randint(0, n - 1)
            v = rng.randint(0, n - 1)
            if u != v:
                edges_set.add((min(u, v), max(u, v)))
        edges = [[u, v] for u, v in sorted(edges_set)]
        perm = list(range(n))
        rng.shuffle(perm)
        swaps = solve(n, edges, perm)
        _verify_solution(n, edges, perm, swaps, max_swaps=n * n)
