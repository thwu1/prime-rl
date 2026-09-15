
import subprocess
import random
import os
import pytest

BINARY = "/app/wt"


def run_wt(n, sigma, seq, queries):
    """Run the wavelet tree binary with given input and return parsed outputs."""
    lines = [f"{n} {sigma}"]
    if n > 0:
        lines.append(" ".join(map(str, seq)))
    else:
        lines.append("")
    lines.append(str(len(queries)))
    for q in queries:
        lines.append(q)
    inp = "\n".join(lines) + "\n"
    result = subprocess.run(
        [BINARY], input=inp, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"Binary crashed: {result.stderr[:500]}"
    out = result.stdout.strip().split("\n") if result.stdout.strip() else []
    assert len(out) == len(queries), (
        f"Expected {len(queries)} output lines, got {len(out)}"
    )
    return [int(x) for x in out]


# ---- Brute-force oracles ----

def bf_access(seq, n, sigma, i):
    return seq[i] if 0 <= i < n else -1


def bf_rank(seq, n, sigma, c, i):
    if c < 0 or c >= sigma or i <= 0:
        return 0
    return sum(1 for x in seq[: min(i, n)] if x == c)


def bf_select(seq, n, sigma, c, j):
    if j <= 0 or c < 0 or c >= sigma:
        return -1
    cnt = 0
    for idx, x in enumerate(seq):
        if x == c:
            cnt += 1
            if cnt == j:
                return idx
    return -1


def bf_kth(seq, n, sigma, l, r, k):
    if l < 0 or r > n or l >= r or k <= 0 or k > r - l:
        return -1
    return sorted(seq[l:r])[k - 1]


def bf_count(seq, n, sigma, l, r, lo, hi):
    if l < 0 or r > n or l >= r or lo >= hi:
        return 0
    return sum(1 for x in seq[l:r] if lo <= x < hi)


def bf_range_next(seq, n, sigma, l, r, c):
    if l < 0 or r > n or l >= r:
        return -1
    cands = [x for x in seq[l:r] if x >= c]
    return min(cands) if cands else -1


def bf_range_prev(seq, n, sigma, l, r, c):
    if l < 0 or r > n or l >= r:
        return -1
    cands = [x for x in seq[l:r] if x <= c]
    return max(cands) if cands else -1


# ---- Test classes ----

class TestBasicAccess:
    def test_small_sequence(self):
        seq = [3, 1, 4, 1, 5, 9, 2, 6]
        n, sigma = 8, 10
        queries = [f"A {i}" for i in range(n)]
        results = run_wt(n, sigma, seq, queries)
        for i in range(n):
            assert results[i] == seq[i], f"access({i}) = {results[i]}, expected {seq[i]}"

    def test_access_out_of_range(self):
        seq = [0, 1, 2]
        n, sigma = 3, 3
        queries = ["A -1", "A 3", "A 100"]
        results = run_wt(n, sigma, seq, queries)
        assert all(r == -1 for r in results), f"Out-of-range access returned {results}"


class TestRank:
    def test_exhaustive_small(self):
        seq = [3, 1, 4, 1, 5, 9, 2, 6]
        n, sigma = 8, 10
        queries = []
        expected = []
        for c in range(sigma):
            for i in range(n + 1):
                queries.append(f"R {c} {i}")
                expected.append(bf_rank(seq, n, sigma, c, i))
        results = run_wt(n, sigma, seq, queries)
        for idx, (r, e) in enumerate(zip(results, expected)):
            assert r == e, f"Query {queries[idx]}: got {r}, expected {e}"

    def test_rank_invalid_symbol(self):
        seq = [0, 1, 2]
        n, sigma = 3, 3
        queries = ["R -1 2", "R 3 2", "R 100 2"]
        results = run_wt(n, sigma, seq, queries)
        assert all(r == 0 for r in results), f"Invalid symbol rank returned {results}"

    def test_rank_boundary_positions(self):
        seq = [0, 0, 0]
        n, sigma = 3, 1
        queries = ["R 0 0", "R 0 1", "R 0 3", "R 0 4"]
        results = run_wt(n, sigma, seq, queries)
        assert results == [0, 1, 3, 3], f"Boundary rank returned {results}"

    def test_rank_beyond_n(self):
        seq = [2, 2, 3, 3, 3]
        n, sigma = 5, 4
        queries = ["R 2 10", "R 3 10", "R 0 10"]
        results = run_wt(n, sigma, seq, queries)
        assert results == [2, 3, 0], f"Beyond-n rank returned {results}"


class TestRankPow2Sigma:
    """Test rank with power-of-2 sigma to isolate rank bugs from build bugs."""

    def test_rank_sigma_8(self):
        seq = [0, 7, 3, 4, 5, 1, 6, 2]
        n, sigma = 8, 8
        queries = []
        expected = []
        for c in range(sigma):
            for i in range(n + 1):
                queries.append(f"R {c} {i}")
                expected.append(bf_rank(seq, n, sigma, c, i))
        results = run_wt(n, sigma, seq, queries)
        for idx, (r, e) in enumerate(zip(results, expected)):
            assert r == e, f"Query {queries[idx]}: got {r}, expected {e}"

    def test_rank_sigma_16(self):
        random.seed(3456)
        n, sigma = 50, 16
        seq = [random.randint(0, sigma - 1) for _ in range(n)]
        queries = []
        expected = []
        for c in range(sigma):
            for i in range(0, n + 1, 5):
                queries.append(f"R {c} {i}")
                expected.append(bf_rank(seq, n, sigma, c, i))
        results = run_wt(n, sigma, seq, queries)
        for idx, (r, e) in enumerate(zip(results, expected)):
            assert r == e, f"Query {queries[idx]}: got {r}, expected {e}"


class TestSelect:
    def test_exhaustive_small(self):
        seq = [3, 1, 4, 1, 5, 9, 2, 6]
        n, sigma = 8, 10
        queries = []
        expected = []
        for c in range(sigma):
            for j in range(1, n + 1):
                queries.append(f"S {c} {j}")
                expected.append(bf_select(seq, n, sigma, c, j))
        results = run_wt(n, sigma, seq, queries)
        for idx, (r, e) in enumerate(zip(results, expected)):
            assert r == e, f"Query {queries[idx]}: got {r}, expected {e}"

    def test_select_not_found(self):
        seq = [0, 1, 2]
        n, sigma = 3, 3
        queries = ["S 0 2", "S 1 2", "S 2 2"]
        results = run_wt(n, sigma, seq, queries)
        assert all(r == -1 for r in results), f"Select-not-found returned {results}"

    def test_select_invalid(self):
        seq = [0, 1]
        n, sigma = 2, 2
        queries = ["S 0 0", "S -1 1", "S 2 1"]
        results = run_wt(n, sigma, seq, queries)
        assert all(r == -1 for r in results), f"Select-invalid returned {results}"

    def test_select_first_position_zero(self):
        """Ensure select returns 0 when first occurrence is at index 0."""
        seq = [5, 3, 7, 5, 2]
        n, sigma = 5, 8
        queries = ["S 5 1", "S 3 1", "S 7 1", "S 2 1"]
        results = run_wt(n, sigma, seq, queries)
        assert results == [0, 1, 2, 4], f"First-occ select returned {results}"


class TestKth:
    def test_exhaustive_small(self):
        seq = [3, 1, 4, 1, 5, 9, 2, 6]
        n, sigma = 8, 10
        queries = []
        expected = []
        for l in range(n):
            for r in range(l + 1, n + 1):
                for k in range(1, r - l + 1):
                    queries.append(f"K {l} {r} {k}")
                    expected.append(bf_kth(seq, n, sigma, l, r, k))
        results = run_wt(n, sigma, seq, queries)
        for idx, (res, exp) in enumerate(zip(results, expected)):
            assert res == exp, f"Query {queries[idx]}: got {res}, expected {exp}"

    def test_kth_invalid(self):
        seq = [1, 2, 3]
        n, sigma = 3, 4
        queries = ["K 0 0 1", "K 2 1 1", "K 0 3 0", "K 0 3 4", "K -1 3 1", "K 0 4 1"]
        results = run_wt(n, sigma, seq, queries)
        assert all(r == -1 for r in results), f"Kth-invalid returned {results}"

    def test_kth_full_range(self):
        seq = [5, 3, 8, 1, 7]
        n, sigma = 5, 9
        queries = [f"K 0 {n} {k}" for k in range(1, n + 1)]
        results = run_wt(n, sigma, seq, queries)
        expected = sorted(seq)
        assert results == expected, f"Full-range kth: got {results}, expected {expected}"

    def test_kth_boundary_at_partition(self):
        """Test kth when k equals the left-child count exactly."""
        seq = [0, 2, 1, 3]
        n, sigma = 4, 4
        queries = []
        expected = []
        for l in range(n):
            for r in range(l + 1, n + 1):
                for k in range(1, r - l + 1):
                    queries.append(f"K {l} {r} {k}")
                    expected.append(bf_kth(seq, n, sigma, l, r, k))
        results = run_wt(n, sigma, seq, queries)
        for idx, (res, exp) in enumerate(zip(results, expected)):
            assert res == exp, f"Query {queries[idx]}: got {res}, expected {exp}"


class TestRangeCount:
    def test_basic(self):
        seq = [3, 1, 4, 1, 5, 9, 2, 6]
        n, sigma = 8, 10
        queries = []
        expected = []
        test_ranges = [(0, n), (0, 4), (4, n), (2, 6), (0, 1), (7, 8)]
        test_vals = [(0, 10), (0, 5), (3, 7), (1, 2), (9, 10), (0, 1)]
        for l, r in test_ranges:
            for lo, hi in test_vals:
                queries.append(f"C {l} {r} {lo} {hi}")
                expected.append(bf_count(seq, n, sigma, l, r, lo, hi))
        results = run_wt(n, sigma, seq, queries)
        for idx, (res, exp) in enumerate(zip(results, expected)):
            assert res == exp, f"Query {queries[idx]}: got {res}, expected {exp}"

    def test_count_empty(self):
        seq = [0, 1, 2]
        n, sigma = 3, 3
        queries = ["C 0 0 0 3", "C 1 1 0 3", "C 0 3 5 3"]
        results = run_wt(n, sigma, seq, queries)
        assert all(r == 0 for r in results), f"Count-empty returned {results}"


class TestRangeSuccessor:
    def test_basic(self):
        seq = [3, 1, 4, 1, 5, 9, 2, 6]
        n, sigma = 8, 10
        queries = []
        expected = []
        for l in [0, 2, 4]:
            for r in [4, 6, 8]:
                if l >= r:
                    continue
                for c in [0, 1, 3, 5, 7, 8, 10]:
                    queries.append(f"V {l} {r} {c}")
                    expected.append(bf_range_next(seq, n, sigma, l, r, c))
        results = run_wt(n, sigma, seq, queries)
        for idx, (res, exp) in enumerate(zip(results, expected)):
            assert res == exp, f"Query {queries[idx]}: got {res}, expected {exp}"

    def test_no_successor(self):
        seq = [1, 2, 3]
        n, sigma = 3, 4
        queries = ["V 0 3 4", "V 0 1 2"]
        results = run_wt(n, sigma, seq, queries)
        assert results == [-1, -1], f"No-successor returned {results}"

    def test_successor_exact(self):
        seq = [5, 10, 3, 8]
        n, sigma = 4, 11
        queries = ["V 0 4 5", "V 0 4 3", "V 0 4 10"]
        results = run_wt(n, sigma, seq, queries)
        assert results == [5, 3, 10], f"Successor-exact returned {results}"


class TestRangePredecessor:
    def test_basic(self):
        seq = [3, 1, 4, 1, 5, 9, 2, 6]
        n, sigma = 8, 10
        queries = []
        expected = []
        for l in [0, 2, 4]:
            for r in [4, 6, 8]:
                if l >= r:
                    continue
                for c in [0, 1, 3, 5, 8, 9, 10]:
                    queries.append(f"P {l} {r} {c}")
                    expected.append(bf_range_prev(seq, n, sigma, l, r, c))
        results = run_wt(n, sigma, seq, queries)
        for idx, (res, exp) in enumerate(zip(results, expected)):
            assert res == exp, f"Query {queries[idx]}: got {res}, expected {exp}"

    def test_no_predecessor(self):
        seq = [5, 6, 7]
        n, sigma = 3, 8
        queries = ["P 0 3 4", "P 1 2 5"]
        results = run_wt(n, sigma, seq, queries)
        assert results == [-1, -1], f"No-predecessor returned {results}"

    def test_predecessor_exact(self):
        seq = [5, 10, 3, 8]
        n, sigma = 4, 11
        queries = ["P 0 4 5", "P 0 4 10", "P 0 4 3"]
        results = run_wt(n, sigma, seq, queries)
        assert results == [5, 10, 3], f"Predecessor-exact returned {results}"


class TestPredecessorAtSplitBoundary:
    """Test predecessor when c equals a power-of-two split point in the tree."""

    def test_pred_equals_val_mid(self):
        seq = [4, 8, 2, 8, 6, 1, 12, 3]
        n, sigma = 8, 16
        queries = []
        expected = []
        for l in range(n):
            for r in range(l + 1, n + 1):
                for c in [0, 2, 4, 8, 12, 15]:
                    queries.append(f"P {l} {r} {c}")
                    expected.append(bf_range_prev(seq, n, sigma, l, r, c))
        results = run_wt(n, sigma, seq, queries)
        for idx, (res, exp) in enumerate(zip(results, expected)):
            assert res == exp, f"Query {queries[idx]}: got {res}, expected {exp}"

    def test_pred_at_multiple_midpoints(self):
        seq = [4, 16, 8, 24, 12, 28, 0, 20]
        n, sigma = 8, 32
        queries = []
        expected = []
        for c in [4, 8, 12, 16, 20, 24, 28]:
            queries.append(f"P 0 {n} {c}")
            expected.append(bf_range_prev(seq, n, sigma, 0, n, c))
        results = run_wt(n, sigma, seq, queries)
        for idx, (res, exp) in enumerate(zip(results, expected)):
            assert res == exp, f"Query {queries[idx]}: got {res}, expected {exp}"


class TestCountPowerOfTwoSigma:
    """Test range count when sigma is a power of 2 (catches missing overflow guard)."""

    def test_full_range_equals_length(self):
        seq = [0, 31, 16, 8, 4, 24, 31, 0]
        n, sigma = 8, 32
        queries = [f"C 0 {n} 0 {sigma}"]
        results = run_wt(n, sigma, seq, queries)
        assert results[0] == n, f"Full range count: expected {n}, got {results[0]}"

    def test_range_count_split_at_half(self):
        seq = [0, 31, 16, 8, 4, 24, 31, 0]
        n, sigma = 8, 32
        lo_count = sum(1 for x in seq if x < 16)
        hi_count = sum(1 for x in seq if 16 <= x < 32)
        queries = [f"C 0 {n} 0 16", f"C 0 {n} 16 {sigma}"]
        results = run_wt(n, sigma, seq, queries)
        assert results[0] == lo_count, f"Low half: expected {lo_count}, got {results[0]}"
        assert results[1] == hi_count, f"High half: expected {hi_count}, got {results[1]}"

    def test_sigma_256_full_count(self):
        random.seed(99887)
        n, sigma = 100, 256
        seq = [random.randint(0, sigma - 1) for _ in range(n)]
        queries = [f"C 0 {n} 0 {sigma}"]
        results = run_wt(n, sigma, seq, queries)
        assert results[0] == n, f"sigma=256 full count: expected {n}, got {results[0]}"


class TestEmptySequence:
    def test_all_ops(self):
        queries = ["A 0", "R 0 0", "S 0 1", "K 0 0 1", "C 0 0 0 1", "V 0 0 0", "P 0 0 0"]
        results = run_wt(0, 1, [], queries)
        assert results == [-1, 0, -1, -1, 0, -1, -1], f"Empty-seq returned {results}"


class TestSingleElement:
    def test_single(self):
        seq = [5]
        n, sigma = 1, 10
        queries = [
            "A 0", "A 1",
            "R 5 1", "R 5 0", "R 3 1",
            "S 5 1", "S 5 2", "S 3 1",
            "K 0 1 1", "K 0 1 2",
            "C 0 1 0 10", "C 0 1 5 6", "C 0 1 6 7",
            "V 0 1 3", "V 0 1 5", "V 0 1 6",
            "P 0 1 5", "P 0 1 4", "P 0 1 7",
        ]
        results = run_wt(n, sigma, seq, queries)
        expected = [5, -1, 1, 0, 0, 0, -1, -1, 5, -1, 1, 1, 0, 5, 5, -1, 5, -1, 5]
        assert results == expected, f"Single-elem: got {results}, expected {expected}"


class TestUniformSequence:
    def test_all_same(self):
        seq = [7] * 20
        n, sigma = 20, 10
        queries = [
            "R 7 10", "R 7 20", "R 0 20",
            "S 7 1", "S 7 20", "S 7 21",
            "K 0 20 1", "K 0 20 20",
            "C 0 20 7 8", "C 0 20 0 7",
            "V 0 20 5", "V 0 20 8",
            "P 0 20 7", "P 0 20 6",
        ]
        results = run_wt(n, sigma, seq, queries)
        expected = [10, 20, 0, 0, 19, -1, 7, 7, 20, 0, 7, -1, 7, -1]
        assert results == expected, f"Uniform-seq: got {results}, expected {expected}"


class TestBinaryAlphabet:
    def test_binary(self):
        random.seed(9999)
        n, sigma = 200, 2
        seq = [random.randint(0, 1) for _ in range(n)]
        queries = []
        expected = []

        for i in range(n):
            queries.append(f"A {i}")
            expected.append(seq[i])

        for c in [0, 1]:
            for i in range(0, n + 1, 10):
                queries.append(f"R {c} {i}")
                expected.append(bf_rank(seq, n, sigma, c, i))

        for c in [0, 1]:
            cnt = seq.count(c)
            for j in [1, cnt // 2, cnt]:
                if j >= 1:
                    queries.append(f"S {c} {j}")
                    expected.append(bf_select(seq, n, sigma, c, j))
            queries.append(f"S {c} {cnt + 1}")
            expected.append(-1)

        results = run_wt(n, sigma, seq, queries)
        for idx, (res, exp) in enumerate(zip(results, expected)):
            assert res == exp, f"Binary query #{idx} '{queries[idx]}': got {res}, expected {exp}"


class TestRandomMedium:
    def test_random_all_ops(self):
        random.seed(42)
        n, sigma = 500, 64
        seq = [random.randint(0, sigma - 1) for _ in range(n)]
        queries = []
        expected = []

        for _ in range(100):
            i = random.randint(0, n - 1)
            queries.append(f"A {i}")
            expected.append(bf_access(seq, n, sigma, i))

        for _ in range(100):
            c = random.randint(0, sigma - 1)
            i = random.randint(0, n)
            queries.append(f"R {c} {i}")
            expected.append(bf_rank(seq, n, sigma, c, i))

        for _ in range(100):
            c = random.randint(0, sigma - 1)
            j = random.randint(1, 20)
            queries.append(f"S {c} {j}")
            expected.append(bf_select(seq, n, sigma, c, j))

        for _ in range(100):
            l = random.randint(0, n - 1)
            r = random.randint(l + 1, n)
            k = random.randint(1, r - l)
            queries.append(f"K {l} {r} {k}")
            expected.append(bf_kth(seq, n, sigma, l, r, k))

        for _ in range(100):
            l = random.randint(0, n - 1)
            r = random.randint(l + 1, n)
            lo = random.randint(0, sigma - 1)
            hi = random.randint(lo + 1, sigma)
            queries.append(f"C {l} {r} {lo} {hi}")
            expected.append(bf_count(seq, n, sigma, l, r, lo, hi))

        for _ in range(50):
            l = random.randint(0, n - 1)
            r = random.randint(l + 1, n)
            c = random.randint(0, sigma)
            queries.append(f"V {l} {r} {c}")
            expected.append(bf_range_next(seq, n, sigma, l, r, c))

        for _ in range(50):
            l = random.randint(0, n - 1)
            r = random.randint(l + 1, n)
            c = random.randint(0, sigma - 1)
            queries.append(f"P {l} {r} {c}")
            expected.append(bf_range_prev(seq, n, sigma, l, r, c))

        results = run_wt(n, sigma, seq, queries)
        for idx, (res, exp) in enumerate(zip(results, expected)):
            assert res == exp, f"Random query #{idx} '{queries[idx]}': got {res}, expected {exp}"


class TestStress:
    def test_large_sequence(self):
        random.seed(12345)
        n, sigma = 50000, 256
        seq = [random.randint(0, sigma - 1) for _ in range(n)]
        queries = []
        expected = []

        for _ in range(200):
            op = random.randint(0, 6)
            if op == 0:
                i = random.randint(0, n - 1)
                queries.append(f"A {i}")
                expected.append(bf_access(seq, n, sigma, i))
            elif op == 1:
                c = random.randint(0, sigma - 1)
                i = random.randint(0, n)
                queries.append(f"R {c} {i}")
                expected.append(bf_rank(seq, n, sigma, c, i))
            elif op == 2:
                c = random.randint(0, sigma - 1)
                j = random.randint(1, max(1, n // sigma))
                queries.append(f"S {c} {j}")
                expected.append(bf_select(seq, n, sigma, c, j))
            elif op == 3:
                l = random.randint(0, n - 1)
                r = random.randint(l + 1, min(l + 1000, n))
                k = random.randint(1, r - l)
                queries.append(f"K {l} {r} {k}")
                expected.append(bf_kth(seq, n, sigma, l, r, k))
            elif op == 4:
                l = random.randint(0, n - 1)
                r = random.randint(l + 1, min(l + 1000, n))
                lo = random.randint(0, sigma - 1)
                hi = random.randint(lo + 1, sigma)
                queries.append(f"C {l} {r} {lo} {hi}")
                expected.append(bf_count(seq, n, sigma, l, r, lo, hi))
            elif op == 5:
                l = random.randint(0, n - 1)
                r = random.randint(l + 1, min(l + 1000, n))
                c = random.randint(0, sigma)
                queries.append(f"V {l} {r} {c}")
                expected.append(bf_range_next(seq, n, sigma, l, r, c))
            else:
                l = random.randint(0, n - 1)
                r = random.randint(l + 1, min(l + 1000, n))
                c = random.randint(0, sigma - 1)
                queries.append(f"P {l} {r} {c}")
                expected.append(bf_range_prev(seq, n, sigma, l, r, c))

        results = run_wt(n, sigma, seq, queries)
        for idx, (res, exp) in enumerate(zip(results, expected)):
            assert res == exp, f"Stress query #{idx} '{queries[idx]}': got {res}, expected {exp}"


class TestLargeAlphabet:
    def test_sigma_1024(self):
        random.seed(7777)
        n, sigma = 1000, 1024
        seq = [random.randint(0, sigma - 1) for _ in range(n)]
        queries = []
        expected = []

        for _ in range(100):
            i = random.randint(0, n - 1)
            queries.append(f"A {i}")
            expected.append(seq[i])

        for _ in range(100):
            c = random.randint(0, sigma - 1)
            i = random.randint(0, n)
            queries.append(f"R {c} {i}")
            expected.append(bf_rank(seq, n, sigma, c, i))

        for _ in range(50):
            l = random.randint(0, n - 1)
            r = random.randint(l + 1, n)
            k = random.randint(1, r - l)
            queries.append(f"K {l} {r} {k}")
            expected.append(bf_kth(seq, n, sigma, l, r, k))

        for _ in range(50):
            l = random.randint(0, n - 1)
            r = random.randint(l + 1, n)
            c = random.randint(0, sigma)
            queries.append(f"V {l} {r} {c}")
            expected.append(bf_range_next(seq, n, sigma, l, r, c))

        for _ in range(50):
            l = random.randint(0, n - 1)
            r = random.randint(l + 1, n)
            c = random.randint(0, sigma - 1)
            queries.append(f"P {l} {r} {c}")
            expected.append(bf_range_prev(seq, n, sigma, l, r, c))

        results = run_wt(n, sigma, seq, queries)
        for idx, (res, exp) in enumerate(zip(results, expected)):
            assert res == exp, f"LargeAlpha query #{idx} '{queries[idx]}': got {res}, expected {exp}"


class TestConsistency:
    """Cross-validate operations against each other."""

    def test_access_rank_select_consistency(self):
        random.seed(5555)
        n, sigma = 300, 16
        seq = [random.randint(0, sigma - 1) for _ in range(n)]

        queries = []
        for i in range(n):
            queries.append(f"A {i}")
        results_a = run_wt(n, sigma, seq, queries)

        queries2 = []
        for i in range(n):
            c = results_a[i]
            queries2.append(f"R {c} {i}")
            queries2.append(f"R {c} {i + 1}")
        results_r = run_wt(n, sigma, seq, queries2)

        queries3 = []
        for i in range(n):
            c = results_a[i]
            rank_at_i = results_r[2 * i]
            rank_at_ip1 = results_r[2 * i + 1]
            assert rank_at_ip1 == rank_at_i + 1, (
                f"Position {i}, symbol {c}: rank(c,{i})={rank_at_i}, "
                f"rank(c,{i+1})={rank_at_ip1}"
            )
            j = rank_at_ip1
            queries3.append(f"S {c} {j}")
        results_s = run_wt(n, sigma, seq, queries3)

        for i in range(n):
            assert results_s[i] == i, (
                f"select(access({i}), rank+1) = {results_s[i]}, expected {i}"
            )

    def test_kth_count_consistency(self):
        random.seed(6666)
        n, sigma = 200, 32
        seq = [random.randint(0, sigma - 1) for _ in range(n)]
        l, r = 10, 100

        kth_queries = [f"K {l} {r} {k}" for k in range(1, r - l + 1)]
        kth_results = run_wt(n, sigma, seq, kth_queries)
        assert kth_results == sorted(seq[l:r]), "Kth sort mismatch"

        distinct = set(seq[l:r])
        count_queries = [f"C {l} {r} {v} {v + 1}" for v in distinct]
        count_results = run_wt(n, sigma, seq, count_queries)
        for v, cnt in zip(distinct, count_results):
            expected = sum(1 for x in seq[l:r] if x == v)
            assert cnt == expected, f"Count({v}) in [{l},{r}) = {cnt}, expected {expected}"

        total_query = [f"C {l} {r} 0 {sigma}"]
        total_result = run_wt(n, sigma, seq, total_query)
        assert total_result[0] == r - l, (
            f"Total count = {total_result[0]}, expected {r - l}"
        )
