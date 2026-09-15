"""
Tests for the sorted set implementation.

"""
import sys
import os
import math
import time
import random
import gc
import ctypes
import subprocess

sys.path.insert(0, '/app')

from sorted_set import SortedSet  # noqa: E402

import pytest  # noqa: E402


# ---------------------------------------------------------------------------
# C library integration
# ---------------------------------------------------------------------------

class TestCLibrary:
    """Verify the C helper library is compiled, loadable, and functional."""

    def test_shared_library_exists(self):
        assert os.path.exists('/app/libnode_ops.so'), \
            "/app/libnode_ops.so not found -- compile with: make -C /app"

    def test_shared_library_loads(self):
        lib = ctypes.CDLL('/app/libnode_ops.so')
        assert lib is not None

    def test_score_lower_bound(self):
        lib = ctypes.CDLL('/app/libnode_ops.so')
        lib.score_lower_bound.argtypes = [
            ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_double
        ]
        lib.score_lower_bound.restype = ctypes.c_int

        arr = (ctypes.c_double * 5)(1.0, 3.0, 5.0, 7.0, 9.0)
        assert lib.score_lower_bound(arr, 5, ctypes.c_double(5.0)) == 2
        assert lib.score_lower_bound(arr, 5, ctypes.c_double(4.0)) == 2
        assert lib.score_lower_bound(arr, 5, ctypes.c_double(0.0)) == 0
        assert lib.score_lower_bound(arr, 5, ctypes.c_double(10.0)) == 5
        assert lib.score_lower_bound(arr, 5, ctypes.c_double(1.0)) == 0

    def test_score_count_in_range(self):
        lib = ctypes.CDLL('/app/libnode_ops.so')
        lib.score_count_in_range.argtypes = [
            ctypes.POINTER(ctypes.c_double), ctypes.c_int,
            ctypes.c_double, ctypes.c_double
        ]
        lib.score_count_in_range.restype = ctypes.c_int

        arr = (ctypes.c_double * 5)(1.0, 3.0, 5.0, 7.0, 9.0)
        assert lib.score_count_in_range(arr, 5,
                                        ctypes.c_double(3.0), ctypes.c_double(7.0)) == 3
        assert lib.score_count_in_range(arr, 5,
                                        ctypes.c_double(0.0), ctypes.c_double(10.0)) == 5
        assert lib.score_count_in_range(arr, 5,
                                        ctypes.c_double(2.0), ctypes.c_double(4.0)) == 1
        assert lib.score_count_in_range(arr, 5,
                                        ctypes.c_double(10.0), ctypes.c_double(20.0)) == 0

    def test_checksum_consistency(self):
        lib = ctypes.CDLL('/app/libnode_ops.so')
        lib.node_ops_checksum.argtypes = [ctypes.c_uint32]
        lib.node_ops_checksum.restype = ctypes.c_uint32

        r1 = lib.node_ops_checksum(42)
        r2 = lib.node_ops_checksum(42)
        assert r1 == r2, "Checksum must be deterministic"

        r3 = lib.node_ops_checksum(43)
        assert r1 != r3, "Different seeds must produce different checksums"

    def test_score_lower_bound_edge_cases(self):
        lib = ctypes.CDLL('/app/libnode_ops.so')
        lib.score_lower_bound.argtypes = [
            ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_double
        ]
        lib.score_lower_bound.restype = ctypes.c_int

        # Empty array
        arr = (ctypes.c_double * 0)()
        assert lib.score_lower_bound(arr, 0, ctypes.c_double(5.0)) == 0

        # Single element
        arr = (ctypes.c_double * 1)(5.0,)
        assert lib.score_lower_bound(arr, 1, ctypes.c_double(5.0)) == 0
        assert lib.score_lower_bound(arr, 1, ctypes.c_double(4.0)) == 0
        assert lib.score_lower_bound(arr, 1, ctypes.c_double(6.0)) == 1

        # Inf values
        arr = (ctypes.c_double * 3)(float('-inf'), 0.0, float('inf'))
        assert lib.score_lower_bound(arr, 3, ctypes.c_double(float('-inf'))) == 0
        assert lib.score_lower_bound(arr, 3, ctypes.c_double(0.0)) == 1
        assert lib.score_lower_bound(arr, 3, ctypes.c_double(float('inf'))) == 2

    def test_ctypes_in_implementation(self):
        """sorted_set.py must use ctypes to interface with the C library."""
        with open('/app/sorted_set.py') as f:
            src = f.read()
        assert 'ctypes' in src, \
            "sorted_set.py must import and use ctypes to interface with libnode_ops.so"
        assert 'libnode_ops' in src or 'node_ops' in src, \
            "sorted_set.py must reference the node_ops shared library"


# ---------------------------------------------------------------------------
# Redis Lua script validation
# ---------------------------------------------------------------------------

class TestLuaScript:
    """Cross-validate the Redis Lua bulk validation script."""

    def _redis(self, *args):
        r = subprocess.run(
            ["redis-cli"] + [str(a) for a in args],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip()

    def test_lua_script_exists(self):
        assert os.path.exists('/app/bulk_validate.lua'), \
            "Missing /app/bulk_validate.lua"

    def test_lua_script_not_skeleton(self):
        """The Lua script must be completed, not left as a skeleton."""
        with open('/app/bulk_validate.lua') as f:
            src = f.read()
        assert 'TODO' not in src, \
            "bulk_validate.lua still contains TODO markers -- complete the implementation"

    def test_lua_script_executes(self):
        """The Lua script must execute without errors on Redis."""
        with open('/app/bulk_validate.lua') as f:
            script = f.read()
        r = subprocess.run(
            ['redis-cli', 'EVAL', script, '1', 'tbench:lua_exec'],
            capture_output=True, text=True, timeout=30
        )
        assert r.returncode == 0, f"Lua script error: {r.stderr}"
        output = r.stdout.strip()
        assert len(output) > 0, "Lua script returned empty output"

    def test_lua_output_format(self):
        """Lua script must return card followed by probe entries."""
        with open('/app/bulk_validate.lua') as f:
            script = f.read()
        r = subprocess.run(
            ['redis-cli', 'EVAL', script, '1', 'tbench:lua_fmt'],
            capture_output=True, text=True, timeout=30
        )
        output = r.stdout.strip()
        parts = output.split(',')
        # First part is card (integer)
        card = int(parts[0])
        assert card > 0, "Card should be positive"
        # Remaining parts are probe entries
        assert len(parts) >= 4, "Expected at least card + 3 probe entries"
        for part in parts[1:]:
            tokens = part.split(':')
            assert len(tokens) == 3, f"Probe entry must be member:rank:score, got: {part}"
            assert tokens[0].startswith('member_'), f"Probe member must start with member_"

    def test_lua_output_matches_implementation(self):
        """Cross-validate Lua script output against Python SortedSet.

        Both must agree on the final state after identical operations:
        insert 200 members (score=N*7-500), remove N%7==0, update N%3==0 (+250).
        """
        with open('/app/bulk_validate.lua') as f:
            script = f.read()
        r = subprocess.run(
            ['redis-cli', 'EVAL', script, '1', 'tbench:lua_xval'],
            capture_output=True, text=True, timeout=30
        )
        assert r.returncode == 0, f"Lua script error: {r.stderr}"
        lua_output = r.stdout.strip()

        # Apply identical operations to Python SortedSet
        ss = SortedSet()
        for n in range(200):
            ss.zadd(f"member_{n:03d}", float(n * 7 - 500))
        for n in range(0, 200, 7):
            ss.zrem(f"member_{n:03d}")
        for n in range(0, 200, 3):
            sc = ss.zscore(f"member_{n:03d}")
            if sc is not None:
                ss.zadd(f"member_{n:03d}", sc + 250.0)

        parts = lua_output.split(',')
        lua_card = int(parts[0])
        assert lua_card == ss.zcard(), \
            f"Card mismatch: Lua={lua_card}, Python={ss.zcard()}"

        for part in parts[1:]:
            tokens = part.split(':')
            member = tokens[0]
            if tokens[1] == 'nil':
                assert ss.zscore(member) is None, \
                    f"{member} should not exist in Python implementation"
            else:
                lua_rank = int(tokens[1])
                lua_score = float(tokens[2])
                py_rank = ss.zrank(member)
                py_score = ss.zscore(member)
                assert py_rank is not None, \
                    f"{member} missing from Python implementation"
                assert py_rank == lua_rank, \
                    f"{member} rank: Lua={lua_rank}, Python={py_rank}"
                assert abs(py_score - lua_score) < 1e-9, \
                    f"{member} score: Lua={lua_score}, Python={py_score}"


# ---------------------------------------------------------------------------
# Basic CRUD operations
# ---------------------------------------------------------------------------

class TestBasicOperations:
    def test_empty_set(self):
        ss = SortedSet()
        assert ss.zcard() == 0
        assert ss.zscore("x") is None
        assert ss.zrank("x") is None
        assert ss.zrevrank("x") is None
        assert ss.zrange_by_rank(0, 10) == []

    def test_zadd_new_element(self):
        ss = SortedSet()
        assert ss.zadd("alice", 1.0) is True
        assert ss.zcard() == 1
        assert ss.zscore("alice") == 1.0

    def test_zadd_update_score(self):
        ss = SortedSet()
        ss.zadd("alice", 1.0)
        assert ss.zadd("alice", 5.0) is False
        assert ss.zcard() == 1
        assert ss.zscore("alice") == 5.0

    def test_zadd_same_score_no_change(self):
        ss = SortedSet()
        ss.zadd("alice", 3.0)
        assert ss.zadd("alice", 3.0) is False
        assert ss.zcard() == 1

    def test_zrem_existing(self):
        ss = SortedSet()
        ss.zadd("alice", 1.0)
        assert ss.zrem("alice") is True
        assert ss.zcard() == 0
        assert ss.zscore("alice") is None

    def test_zrem_nonexistent(self):
        ss = SortedSet()
        assert ss.zrem("alice") is False

    def test_zrem_then_readd(self):
        ss = SortedSet()
        ss.zadd("alice", 1.0)
        ss.zrem("alice")
        assert ss.zadd("alice", 2.0) is True
        assert ss.zscore("alice") == 2.0


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

class TestOrdering:
    def test_score_ordering(self):
        ss = SortedSet()
        ss.zadd("c", 3.0)
        ss.zadd("a", 1.0)
        ss.zadd("b", 2.0)
        result = ss.zrange_by_rank(0, 2)
        assert result == [("a", 1.0), ("b", 2.0), ("c", 3.0)]

    def test_lexicographic_tiebreak(self):
        ss = SortedSet()
        ss.zadd("charlie", 1.0)
        ss.zadd("alice", 1.0)
        ss.zadd("bob", 1.0)
        result = ss.zrange_by_rank(0, 2)
        assert result == [("alice", 1.0), ("bob", 1.0), ("charlie", 1.0)]

    def test_negative_scores(self):
        ss = SortedSet()
        ss.zadd("a", -1.0)
        ss.zadd("b", -2.0)
        ss.zadd("c", 0.0)
        result = ss.zrange_by_rank(0, 2)
        assert result == [("b", -2.0), ("a", -1.0), ("c", 0.0)]

    def test_mixed_scores(self):
        ss = SortedSet()
        scores = [3.14, -2.71, 0.0, 100.5, -100.5, 1.0, 1.0]
        members = ["pi", "neg_e", "zero", "big", "neg_big", "one_a", "one_b"]
        for m, s in zip(members, scores):
            ss.zadd(m, s)
        result = ss.zrange_by_rank(0, ss.zcard() - 1)
        expected = sorted(zip(members, scores), key=lambda x: (x[1], x[0]))
        assert result == expected


# ---------------------------------------------------------------------------
# Rank queries
# ---------------------------------------------------------------------------

class TestRank:
    def test_zrank_basic(self):
        ss = SortedSet()
        for i, name in enumerate(["x", "y", "z"]):
            ss.zadd(name, float(i))
        assert ss.zrank("x") == 0
        assert ss.zrank("y") == 1
        assert ss.zrank("z") == 2

    def test_zrevrank_basic(self):
        ss = SortedSet()
        for i, name in enumerate(["x", "y", "z"]):
            ss.zadd(name, float(i))
        assert ss.zrevrank("x") == 2
        assert ss.zrevrank("y") == 1
        assert ss.zrevrank("z") == 0

    def test_rank_not_found(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        assert ss.zrank("b") is None
        assert ss.zrevrank("b") is None

    def test_rank_after_delete(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        ss.zadd("b", 2.0)
        ss.zadd("c", 3.0)
        ss.zrem("b")
        assert ss.zrank("a") == 0
        assert ss.zrank("c") == 1

    def test_rank_after_score_update(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        ss.zadd("b", 2.0)
        ss.zadd("c", 3.0)
        ss.zadd("a", 5.0)
        assert ss.zrank("b") == 0
        assert ss.zrank("c") == 1
        assert ss.zrank("a") == 2

    def test_rank_with_ties(self):
        ss = SortedSet()
        members = ["delta", "alpha", "charlie", "bravo"]
        for m in members:
            ss.zadd(m, 5.0)
        assert ss.zrank("alpha") == 0
        assert ss.zrank("bravo") == 1
        assert ss.zrank("charlie") == 2
        assert ss.zrank("delta") == 3

    def test_rank_single_element(self):
        ss = SortedSet()
        ss.zadd("only", 42.0)
        assert ss.zrank("only") == 0
        assert ss.zrevrank("only") == 0


# ---------------------------------------------------------------------------
# Range by rank
# ---------------------------------------------------------------------------

class TestRangeByRank:
    def test_full_range(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        ss.zadd("b", 2.0)
        ss.zadd("c", 3.0)
        assert ss.zrange_by_rank(0, 2) == [("a", 1.0), ("b", 2.0), ("c", 3.0)]

    def test_partial_range(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        ss.zadd("b", 2.0)
        ss.zadd("c", 3.0)
        assert ss.zrange_by_rank(1, 2) == [("b", 2.0), ("c", 3.0)]

    def test_single_element_range(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        ss.zadd("b", 2.0)
        assert ss.zrange_by_rank(0, 0) == [("a", 1.0)]

    def test_empty_range_out_of_bounds(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        assert ss.zrange_by_rank(5, 10) == []

    def test_clamped_stop(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        ss.zadd("b", 2.0)
        result = ss.zrange_by_rank(0, 100)
        assert result == [("a", 1.0), ("b", 2.0)]

    def test_revrange_full(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        ss.zadd("b", 2.0)
        ss.zadd("c", 3.0)
        assert ss.zrevrange_by_rank(0, 2) == [("c", 3.0), ("b", 2.0), ("a", 1.0)]

    def test_revrange_partial(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        ss.zadd("b", 2.0)
        ss.zadd("c", 3.0)
        assert ss.zrevrange_by_rank(0, 1) == [("c", 3.0), ("b", 2.0)]

    def test_revrange_single(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        ss.zadd("b", 2.0)
        ss.zadd("c", 3.0)
        assert ss.zrevrange_by_rank(0, 0) == [("c", 3.0)]


# ---------------------------------------------------------------------------
# Range by score and zcount
# ---------------------------------------------------------------------------

class TestRangeByScore:
    def test_basic_score_range(self):
        ss = SortedSet()
        for i in range(10):
            ss.zadd(f"m{i}", float(i))
        result = ss.zrange_by_score(2.0, 5.0)
        assert result == [(f"m{i}", float(i)) for i in range(2, 6)]

    def test_score_range_with_offset_count(self):
        ss = SortedSet()
        for i in range(10):
            ss.zadd(f"m{i}", float(i))
        result = ss.zrange_by_score(0.0, 9.0, offset=2, count=3)
        assert result == [("m2", 2.0), ("m3", 3.0), ("m4", 4.0)]

    def test_score_range_empty(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        assert ss.zrange_by_score(5.0, 10.0) == []

    def test_score_range_count_unlimited(self):
        ss = SortedSet()
        for i in range(5):
            ss.zadd(f"m{i}", float(i))
        result = ss.zrange_by_score(1.0, 3.0, count=-1)
        assert result == [("m1", 1.0), ("m2", 2.0), ("m3", 3.0)]

    def test_zcount_basic(self):
        ss = SortedSet()
        for i in range(100):
            ss.zadd(f"m{i:03d}", float(i))
        assert ss.zcount(10.0, 20.0) == 11
        assert ss.zcount(0.0, 99.0) == 100
        assert ss.zcount(50.0, 50.0) == 1
        assert ss.zcount(100.0, 200.0) == 0

    def test_zcount_empty_set(self):
        ss = SortedSet()
        assert ss.zcount(0.0, 100.0) == 0

    def test_zcount_inverted_range(self):
        ss = SortedSet()
        ss.zadd("a", 5.0)
        assert ss.zcount(10.0, 1.0) == 0

    def test_score_range_boundary(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        ss.zadd("b", 2.0)
        ss.zadd("c", 3.0)
        assert ss.zrange_by_score(1.0, 3.0) == [("a", 1.0), ("b", 2.0), ("c", 3.0)]
        assert ss.zrange_by_score(1.0, 2.0) == [("a", 1.0), ("b", 2.0)]
        assert ss.zrange_by_score(2.0, 2.0) == [("b", 2.0)]


# ---------------------------------------------------------------------------
# Structural properties
# ---------------------------------------------------------------------------

class TestStructural:
    def test_height_bounded(self):
        ss = SortedSet()
        N = 50000
        for i in range(N):
            ss.zadd(f"m{i:06d}", float(i))
        h = ss.height()
        max_h = 1 + math.ceil(math.log(N) / math.log(8))
        assert h <= max_h, f"Height {h} exceeds bound {max_h} for {N} elements"

    def test_node_count_bounded(self):
        ss = SortedSet()
        N = 50000
        for i in range(N):
            ss.zadd(f"m{i:06d}", float(i))
        nc = ss.node_count()
        assert nc < N // 4, f"Node count {nc} too high for {N} elements (no bucketing?)"

    def test_real_tree_not_flat(self):
        """A flat structure must be replaced with a real multi-level tree."""
        ss = SortedSet()
        N = 10000
        for i in range(N):
            ss.zadd(f"m{i:05d}", float(i))
        assert ss.height() >= 2, "Height must be >= 2 for 10000 elements"
        assert ss.node_count() >= 2, "Must have multiple nodes"
        assert ss.node_count() >= N // 256, "Not enough nodes for proper bucketing"

    def test_height_is_positive_int(self):
        ss = SortedSet()
        ss.zadd("a", 1.0)
        assert isinstance(ss.height(), int)
        assert ss.height() >= 1

    def test_structural_after_deletions(self):
        ss = SortedSet()
        N = 10000
        for i in range(N):
            ss.zadd(f"m{i:05d}", float(i))
        for i in range(0, N, 2):
            ss.zrem(f"m{i:05d}")
        remaining = N // 2
        assert ss.zcard() == remaining
        h = ss.height()
        max_h = 2 + math.ceil(math.log(max(remaining, 1)) / math.log(8))
        assert h <= max_h, f"Height {h} too large after deletions"


# ---------------------------------------------------------------------------
# Performance: sublinear rank queries and insertions
# ---------------------------------------------------------------------------

class TestPerformance:
    def test_rank_query_is_sublinear(self):
        """Rank queries must be O(log N), not O(N)."""
        random.seed(42)
        gc.disable()
        try:
            N_large = 100000
            ss_large = SortedSet()
            for i in range(N_large):
                ss_large.zadd(f"m{i:06d}", float(i))

            queries_large = [f"m{random.randint(0, N_large - 1):06d}" for _ in range(2000)]
            for q in queries_large[:200]:
                ss_large.zrank(q)

            start = time.perf_counter()
            for q in queries_large:
                ss_large.zrank(q)
            elapsed_large = time.perf_counter() - start

            N_small = 1000
            ss_small = SortedSet()
            for i in range(N_small):
                ss_small.zadd(f"m{i:06d}", float(i))

            queries_small = [f"m{random.randint(0, N_small - 1):06d}" for _ in range(2000)]
            for q in queries_small[:200]:
                ss_small.zrank(q)

            start = time.perf_counter()
            for q in queries_small:
                ss_small.zrank(q)
            elapsed_small = time.perf_counter() - start

            if elapsed_small > 1e-5:
                ratio = elapsed_large / elapsed_small
                assert ratio < 30, (
                    f"Rank query time ratio {ratio:.1f}x (large/small) suggests O(N) not O(log N)"
                )
        finally:
            gc.enable()

    def test_insertion_is_sublinear(self):
        """Insertions must be O(log N), not O(N)."""
        gc.disable()
        try:
            N = 50000
            ss_large = SortedSet()
            for i in range(N):
                ss_large.zadd(f"m{i:06d}", float(i))

            start = time.perf_counter()
            for i in range(N, N + 500):
                ss_large.zadd(f"m{i:06d}", float(i))
            elapsed_large = time.perf_counter() - start

            ss_small = SortedSet()
            for i in range(500):
                ss_small.zadd(f"m{i:06d}", float(i))

            start = time.perf_counter()
            for i in range(500, 1000):
                ss_small.zadd(f"m{i:06d}", float(i))
            elapsed_small = time.perf_counter() - start

            if elapsed_small > 1e-5:
                ratio = elapsed_large / elapsed_small
                assert ratio < 30, (
                    f"Insertion time ratio {ratio:.1f}x suggests O(N) not O(log N)"
                )
        finally:
            gc.enable()


# ---------------------------------------------------------------------------
# Stress tests with reference verification
# ---------------------------------------------------------------------------

class TestStress:
    def test_random_operations(self):
        """Random interleaved inserts, deletes, rank and range queries
        verified against a naive sorted-list reference."""
        random.seed(12345)

        ss = SortedSet()
        reference = {}

        for _ in range(5000):
            op = random.choice(["add", "add", "add", "rem", "rank", "range"])

            if op == "add":
                member = f"m{random.randint(0, 999)}"
                score = round(random.uniform(-100, 100), 4)
                expected_new = member not in reference
                result = ss.zadd(member, score)
                assert result == expected_new, f"zadd({member},{score}): got {result}, expected {expected_new}"
                reference[member] = score

            elif op == "rem":
                member = f"m{random.randint(0, 999)}"
                expected = member in reference
                result = ss.zrem(member)
                assert result == expected
                if expected:
                    del reference[member]

            elif op == "rank":
                member = f"m{random.randint(0, 999)}"
                if member in reference:
                    sorted_items = sorted(reference.items(), key=lambda x: (x[1], x[0]))
                    expected_rank = next(
                        i for i, (m, _) in enumerate(sorted_items) if m == member
                    )
                    got = ss.zrank(member)
                    assert got == expected_rank, (
                        f"zrank({member}): got {got}, expected {expected_rank}"
                    )
                else:
                    assert ss.zrank(member) is None

            elif op == "range":
                if reference:
                    sorted_items = sorted(reference.items(), key=lambda x: (x[1], x[0]))
                    n = len(sorted_items)
                    start = random.randint(0, n - 1)
                    stop = random.randint(start, min(start + 20, n - 1))
                    expected = [(m, s) for m, s in sorted_items[start:stop + 1]]
                    result = ss.zrange_by_rank(start, stop)
                    assert result == expected, (
                        f"zrange_by_rank({start},{stop}): got {result}, expected {expected}"
                    )

        assert ss.zcard() == len(reference)

    def test_large_scale_rank_correctness(self):
        """Insert many elements and verify all ranks are correct."""
        random.seed(99)

        ss = SortedSet()
        N = 10000
        members = {}
        for i in range(N):
            member = f"member_{i:05d}"
            score = round(random.uniform(-1000, 1000), 6)
            ss.zadd(member, score)
            members[member] = score

        sorted_items = sorted(members.items(), key=lambda x: (x[1], x[0]))

        indices = random.sample(range(N), 300)
        for idx in indices:
            member, score = sorted_items[idx]
            got = ss.zrank(member)
            assert got == idx, f"Rank mismatch for {member}: expected {idx}, got {got}"

        result = ss.zrange_by_rank(0, N - 1)
        assert len(result) == N
        for i in range(N):
            assert result[i] == sorted_items[i], f"Mismatch at rank {i}"

    def test_heavy_deletions_then_queries(self):
        """Build a large tree, delete most elements, verify remaining ranks."""
        random.seed(77)

        ss = SortedSet()
        N = 5000
        all_members = []
        for i in range(N):
            m = f"d{i:05d}"
            s = round(random.uniform(-500, 500), 4)
            ss.zadd(m, s)
            all_members.append((m, s))

        to_delete = random.sample(all_members, N * 4 // 5)
        remaining = dict(all_members)
        for m, _ in to_delete:
            ss.zrem(m)
            del remaining[m]

        assert ss.zcard() == len(remaining)

        sorted_remaining = sorted(remaining.items(), key=lambda x: (x[1], x[0]))
        result = ss.zrange_by_rank(0, len(sorted_remaining) - 1)
        assert result == sorted_remaining

        for idx, (m, s) in enumerate(sorted_remaining):
            assert ss.zrank(m) == idx

    def test_score_update_stress(self):
        """Repeatedly update scores and verify rank correctness."""
        random.seed(55)

        ss = SortedSet()
        members = {}
        for i in range(200):
            m = f"u{i:03d}"
            s = round(random.uniform(0, 100), 2)
            ss.zadd(m, s)
            members[m] = s

        keys = list(members.keys())
        for _ in range(1000):
            m = random.choice(keys)
            new_score = round(random.uniform(0, 100), 2)
            ss.zadd(m, new_score)
            members[m] = new_score

        sorted_items = sorted(members.items(), key=lambda x: (x[1], x[0]))
        for idx, (m, s) in enumerate(sorted_items):
            got = ss.zrank(m)
            assert got == idx, f"After updates, rank of {m}: expected {idx}, got {got}"

    def test_zcount_stress(self):
        """Verify zcount against reference across various ranges."""
        random.seed(88)

        ss = SortedSet()
        N = 2000
        data = {}
        for i in range(N):
            m = f"c{i:04d}"
            s = round(random.uniform(-100, 100), 3)
            ss.zadd(m, s)
            data[m] = s

        scores = sorted(data.values())

        for _ in range(200):
            lo = round(random.uniform(-100, 100), 3)
            hi = round(random.uniform(lo, 100), 3)
            expected = sum(1 for s in scores if lo <= s <= hi)
            got = ss.zcount(lo, hi)
            assert got == expected, f"zcount({lo},{hi}): got {got}, expected {expected}"


# ---------------------------------------------------------------------------
# Redis compatibility: edge cases verified against a running Redis instance
# ---------------------------------------------------------------------------

class TestRedisCompatibility:
    """Verify sorted set semantics match Redis for edge cases.
    Requires Redis running on localhost:6379 (started by test.sh)."""

    def _redis(self, *args):
        r = subprocess.run(
            ["redis-cli"] + [str(a) for a in args],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip()

    def test_inf_scores_rank(self):
        self._redis("DEL", "tbench:inf_rank")
        self._redis("ZADD", "tbench:inf_rank", "-inf", "first")
        self._redis("ZADD", "tbench:inf_rank", "0", "middle")
        self._redis("ZADD", "tbench:inf_rank", "+inf", "last")

        assert self._redis("ZRANK", "tbench:inf_rank", "first") == "0"
        assert self._redis("ZRANK", "tbench:inf_rank", "middle") == "1"
        assert self._redis("ZRANK", "tbench:inf_rank", "last") == "2"

        ss = SortedSet()
        ss.zadd("first", float('-inf'))
        ss.zadd("middle", 0.0)
        ss.zadd("last", float('inf'))
        assert ss.zrank("first") == 0
        assert ss.zrank("middle") == 1
        assert ss.zrank("last") == 2
        assert ss.zcard() == 3

    def test_inf_count_matches_redis(self):
        self._redis("DEL", "tbench:inf_count")
        N = 25
        for i in range(N):
            self._redis("ZADD", "tbench:inf_count", str(float(i)), f"e{i:02d}")
        self._redis("ZADD", "tbench:inf_count", "-inf", "neg_inf_member")
        self._redis("ZADD", "tbench:inf_count", "+inf", "pos_inf_member")

        redis_total = int(self._redis("ZCOUNT", "tbench:inf_count", "-inf", "+inf"))
        redis_card = int(self._redis("ZCARD", "tbench:inf_count"))
        assert redis_total == redis_card

        ss = SortedSet()
        for i in range(N):
            ss.zadd(f"e{i:02d}", float(i))
        ss.zadd("neg_inf_member", float('-inf'))
        ss.zadd("pos_inf_member", float('inf'))
        assert ss.zcount(float('-inf'), float('inf')) == ss.zcard()
        assert ss.zcount(float('-inf'), float('inf')) == redis_total

    def test_score_precision_matches_redis(self):
        self._redis("DEL", "tbench:precision")
        self._redis("ZADD", "tbench:precision", "1.0000001", "a")
        self._redis("ZADD", "tbench:precision", "1.0000002", "b")

        redis_rank_a = int(self._redis("ZRANK", "tbench:precision", "a"))
        redis_rank_b = int(self._redis("ZRANK", "tbench:precision", "b"))
        assert redis_rank_a == 0
        assert redis_rank_b == 1

        ss = SortedSet()
        ss.zadd("a", 1.0000001)
        ss.zadd("b", 1.0000002)
        assert ss.zrank("a") == redis_rank_a
        assert ss.zrank("b") == redis_rank_b

    def test_score_update_rank_matches_redis(self):
        self._redis("DEL", "tbench:reorder")
        self._redis("ZADD", "tbench:reorder", "10", "alice")
        self._redis("ZADD", "tbench:reorder", "20", "bob")
        self._redis("ZADD", "tbench:reorder", "30", "charlie")
        self._redis("ZADD", "tbench:reorder", "25", "alice")

        redis_rank_bob = int(self._redis("ZRANK", "tbench:reorder", "bob"))
        redis_rank_alice = int(self._redis("ZRANK", "tbench:reorder", "alice"))
        redis_rank_charlie = int(self._redis("ZRANK", "tbench:reorder", "charlie"))

        ss = SortedSet()
        ss.zadd("alice", 10.0)
        ss.zadd("bob", 20.0)
        ss.zadd("charlie", 30.0)
        ss.zadd("alice", 25.0)

        assert ss.zrank("bob") == redis_rank_bob
        assert ss.zrank("alice") == redis_rank_alice
        assert ss.zrank("charlie") == redis_rank_charlie

    def test_lex_tiebreak_matches_redis(self):
        self._redis("DEL", "tbench:lex")
        self._redis("ZADD", "tbench:lex", "1", "delta")
        self._redis("ZADD", "tbench:lex", "1", "alpha")
        self._redis("ZADD", "tbench:lex", "1", "charlie")
        self._redis("ZADD", "tbench:lex", "1", "bravo")

        redis_ranks = {}
        for m in ["alpha", "bravo", "charlie", "delta"]:
            redis_ranks[m] = int(self._redis("ZRANK", "tbench:lex", m))

        ss = SortedSet()
        ss.zadd("delta", 1.0)
        ss.zadd("alpha", 1.0)
        ss.zadd("charlie", 1.0)
        ss.zadd("bravo", 1.0)

        for m, expected in redis_ranks.items():
            got = ss.zrank(m)
            assert got == expected, (
                f"Lex tiebreak: zrank({m}) = {got}, Redis says {expected}"
            )

    def test_zcount_partial_range_matches_redis(self):
        self._redis("DEL", "tbench:partial")
        for i in range(50):
            self._redis("ZADD", "tbench:partial", str(i * 2.5), f"p{i:02d}")

        redis_count = int(self._redis("ZCOUNT", "tbench:partial", "20", "80"))

        ss = SortedSet()
        for i in range(50):
            ss.zadd(f"p{i:02d}", i * 2.5)

        assert ss.zcount(20.0, 80.0) == redis_count
