
"""Comprehensive tests for BPTreeSortedSet implementation and RESP server."""

import math
import random
import subprocess
import sys
import time

import pytest

sys.path.insert(0, "/app")
from sorted_set import BPTreeSortedSet  # noqa: E402

try:
    import redis as redis_lib

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


# ════════════════════════════════════════════════════════════════════════════════
# Part 1 — Direct engine tests (same as before)
# ════════════════════════════════════════════════════════════════════════════════


# ────────────────────────── basic CRUD ──────────────────────────────────────


class TestBasicOperations:
    def test_zadd_single(self):
        ss = BPTreeSortedSet()
        assert ss.zadd([(1.0, "a")]) == 1
        assert ss.zcard() == 1
        assert ss.zscore("a") == 1.0

    def test_zadd_multiple(self):
        ss = BPTreeSortedSet()
        assert ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c")]) == 3
        assert ss.zcard() == 3

    def test_zadd_update_score(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a")])
        assert ss.zadd([(5.0, "a")]) == 0  # update, not add
        assert ss.zscore("a") == 5.0
        assert ss.zcard() == 1

    def test_zadd_same_score_no_change(self):
        ss = BPTreeSortedSet()
        ss.zadd([(3.0, "x")])
        assert ss.zadd([(3.0, "x")]) == 0
        assert ss.zscore("x") == 3.0
        assert ss.zcard() == 1

    def test_zrem_existing(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b")])
        assert ss.zrem("a") == 1
        assert ss.zcard() == 1
        assert ss.zscore("a") is None
        assert ss.zscore("b") == 2.0

    def test_zrem_nonexistent(self):
        ss = BPTreeSortedSet()
        assert ss.zrem("x") == 0

    def test_zrem_multiple(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c")])
        assert ss.zrem("a", "c", "z") == 2
        assert ss.zcard() == 1

    def test_zscore_nonexistent(self):
        ss = BPTreeSortedSet()
        assert ss.zscore("x") is None

    def test_zcard_empty(self):
        ss = BPTreeSortedSet()
        assert ss.zcard() == 0

    def test_negative_scores(self):
        ss = BPTreeSortedSet()
        ss.zadd([(-5.0, "a"), (-3.0, "b"), (0.0, "c")])
        assert ss.zscore("a") == -5.0
        result = ss.zrange(0, -1)
        assert result == [("a", -5.0), ("b", -3.0), ("c", 0.0)]


# ────────────────────────── ordering ────────────────────────────────────────


class TestCompoundOrdering:
    def test_score_ordering(self):
        ss = BPTreeSortedSet()
        ss.zadd([(3.0, "c"), (1.0, "a"), (2.0, "b")])
        result = ss.zrange(0, -1)
        assert result == [("a", 1.0), ("b", 2.0), ("c", 3.0)]

    def test_lexicographic_tiebreak(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "cherry"), (1.0, "apple"), (1.0, "banana")])
        result = ss.zrange(0, -1)
        assert result == [("apple", 1.0), ("banana", 1.0), ("cherry", 1.0)]

    def test_mixed_ordering(self):
        ss = BPTreeSortedSet()
        ss.zadd([(2.0, "b"), (1.0, "c"), (2.0, "a"), (1.0, "d")])
        result = ss.zrange(0, -1)
        assert result == [("c", 1.0), ("d", 1.0), ("a", 2.0), ("b", 2.0)]


# ────────────────────────── rank operations ─────────────────────────────────


class TestRankOperations:
    def test_zrank(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c")])
        assert ss.zrank("a") == 0
        assert ss.zrank("b") == 1
        assert ss.zrank("c") == 2

    def test_zrevrank(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c")])
        assert ss.zrevrank("a") == 2
        assert ss.zrevrank("b") == 1
        assert ss.zrevrank("c") == 0

    def test_zrank_nonexistent(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a")])
        assert ss.zrank("x") is None
        assert ss.zrevrank("x") is None

    def test_zrank_after_score_update(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c")])
        ss.zadd([(10.0, "a")])  # move a to end
        assert ss.zrank("a") == 2
        assert ss.zrank("b") == 0
        assert ss.zrank("c") == 1

    def test_zrank_tiebreak(self):
        ss = BPTreeSortedSet()
        ss.zadd([(5.0, "x"), (5.0, "a"), (5.0, "m")])
        assert ss.zrank("a") == 0
        assert ss.zrank("m") == 1
        assert ss.zrank("x") == 2


# ────────────────────────── range by rank ───────────────────────────────────


class TestRangeByRank:
    def test_zrange_all(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c")])
        assert ss.zrange(0, -1) == [("a", 1.0), ("b", 2.0), ("c", 3.0)]

    def test_zrange_subset(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c"), (4.0, "d")])
        assert ss.zrange(1, 2) == [("b", 2.0), ("c", 3.0)]

    def test_zrange_negative_indices(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c")])
        assert ss.zrange(-2, -1) == [("b", 2.0), ("c", 3.0)]

    def test_zrange_reverse(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c")])
        assert ss.zrange(0, -1, reverse=True) == [
            ("c", 3.0),
            ("b", 2.0),
            ("a", 1.0),
        ]

    def test_zrange_reverse_subset(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c"), (4.0, "d")])
        assert ss.zrange(0, 1, reverse=True) == [("d", 4.0), ("c", 3.0)]

    def test_zrange_out_of_bounds(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b")])
        assert ss.zrange(0, 100) == [("a", 1.0), ("b", 2.0)]

    def test_zrange_invalid_range(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b")])
        assert ss.zrange(3, 5) == []

    def test_zrange_empty(self):
        ss = BPTreeSortedSet()
        assert ss.zrange(0, -1) == []

    def test_zrange_without_scores(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b")])
        assert ss.zrange(0, -1, withscores=False) == ["a", "b"]

    def test_zrange_single_element(self):
        ss = BPTreeSortedSet()
        ss.zadd([(5.0, "only")])
        assert ss.zrange(0, 0) == [("only", 5.0)]
        assert ss.zrange(0, -1) == [("only", 5.0)]


# ────────────────────────── range by score ──────────────────────────────────


class TestRangeByScore:
    def test_basic(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c"), (4.0, "d")])
        result = ss.zrangebyscore(2.0, 3.0)
        assert result == [("b", 2.0), ("c", 3.0)]

    def test_exclusive_min(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c")])
        result = ss.zrangebyscore(1.0, 3.0, min_exclusive=True)
        assert result == [("b", 2.0), ("c", 3.0)]

    def test_exclusive_max(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c")])
        result = ss.zrangebyscore(1.0, 3.0, max_exclusive=True)
        assert result == [("a", 1.0), ("b", 2.0)]

    def test_both_exclusive(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c"), (4.0, "d")])
        result = ss.zrangebyscore(
            2.0, 4.0, min_exclusive=True, max_exclusive=True
        )
        assert result == [("c", 3.0)]

    def test_inf_bounds(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c")])
        result = ss.zrangebyscore(float("-inf"), float("inf"))
        assert result == [("a", 1.0), ("b", 2.0), ("c", 3.0)]

    def test_offset_count(self):
        ss = BPTreeSortedSet()
        for i in range(10):
            ss.zadd([(float(i), f"m{i}")])
        result = ss.zrangebyscore(0.0, 9.0, offset=2, count=3)
        assert result == [("m2", 2.0), ("m3", 3.0), ("m4", 4.0)]

    def test_count_limits(self):
        ss = BPTreeSortedSet()
        for i in range(10):
            ss.zadd([(float(i), f"m{i}")])
        result = ss.zrangebyscore(0.0, 9.0, count=2)
        assert result == [("m0", 0.0), ("m1", 1.0)]

    def test_empty_range(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (5.0, "b")])
        assert ss.zrangebyscore(2.0, 4.0) == []

    def test_without_scores(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b")])
        assert ss.zrangebyscore(1.0, 2.0, withscores=False) == ["a", "b"]

    def test_offset_with_various_values(self):
        """Verify LIMIT offset at several values for regression."""
        ss = BPTreeSortedSet()
        for i in range(20):
            ss.zadd([(float(i), f"e{i:02d}")])

        # offset=0 should start from first match
        r0 = ss.zrangebyscore(0.0, 19.0, offset=0, count=3)
        assert r0 == [("e00", 0.0), ("e01", 1.0), ("e02", 2.0)]

        # offset=1 should skip exactly one
        r1 = ss.zrangebyscore(0.0, 19.0, offset=1, count=3)
        assert r1 == [("e01", 1.0), ("e02", 2.0), ("e03", 3.0)]

        # offset=5
        r5 = ss.zrangebyscore(0.0, 19.0, offset=5, count=2)
        assert r5 == [("e05", 5.0), ("e06", 6.0)]

    def test_exclusive_bounds_with_limit(self):
        """Exclusive bounds combined with LIMIT pagination."""
        ss = BPTreeSortedSet()
        for i in range(15):
            ss.zadd([(float(i), f"v{i:02d}")])

        # exclusive min, skip 2, take 3: elements 1..14, skip 2 -> start at v03
        r = ss.zrangebyscore(0.0, 14.0, min_exclusive=True, offset=2, count=3)
        assert r == [("v03", 3.0), ("v04", 4.0), ("v05", 5.0)]

        # both exclusive, skip 1, take 2: elements 1..13, skip 1 -> start at v02
        r2 = ss.zrangebyscore(
            0.0, 14.0, min_exclusive=True, max_exclusive=True,
            offset=1, count=2
        )
        assert r2 == [("v02", 2.0), ("v03", 3.0)]


# ────────────────────────── zcount ──────────────────────────────────────────


class TestZcount:
    def test_basic(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c"), (4.0, "d")])
        assert ss.zcount(2.0, 3.0) == 2

    def test_exclusive(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c"), (4.0, "d")])
        assert ss.zcount(1.0, 4.0, min_exclusive=True, max_exclusive=True) == 2

    def test_all(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b")])
        assert ss.zcount(float("-inf"), float("inf")) == 2

    def test_none(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a")])
        assert ss.zcount(5.0, 10.0) == 0

    def test_empty_set(self):
        ss = BPTreeSortedSet()
        assert ss.zcount(0.0, 100.0) == 0


# ────────────────────────── ZADD flags ──────────────────────────────────────


class TestZaddFlags:
    def test_nx_prevents_update(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a")])
        assert ss.zadd([(5.0, "a")], nx=True) == 0
        assert ss.zscore("a") == 1.0

    def test_nx_allows_add(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a")])
        assert ss.zadd([(2.0, "b")], nx=True) == 1
        assert ss.zscore("b") == 2.0

    def test_xx_prevents_add(self):
        ss = BPTreeSortedSet()
        assert ss.zadd([(1.0, "a")], xx=True) == 0
        assert ss.zcard() == 0

    def test_xx_allows_update(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a")])
        assert ss.zadd([(5.0, "a")], xx=True) == 0  # returns 0 (no new adds)
        assert ss.zscore("a") == 5.0

    def test_gt_update_higher(self):
        ss = BPTreeSortedSet()
        ss.zadd([(5.0, "a")])
        assert ss.zadd([(10.0, "a")], gt=True) == 0
        assert ss.zscore("a") == 10.0

    def test_gt_skip_lower(self):
        ss = BPTreeSortedSet()
        ss.zadd([(5.0, "a")])
        assert ss.zadd([(3.0, "a")], gt=True) == 0
        assert ss.zscore("a") == 5.0

    def test_gt_allows_add(self):
        ss = BPTreeSortedSet()
        assert ss.zadd([(1.0, "a")], gt=True) == 1
        assert ss.zscore("a") == 1.0

    def test_lt_update_lower(self):
        ss = BPTreeSortedSet()
        ss.zadd([(5.0, "a")])
        assert ss.zadd([(3.0, "a")], lt=True) == 0
        assert ss.zscore("a") == 3.0

    def test_lt_skip_higher(self):
        ss = BPTreeSortedSet()
        ss.zadd([(5.0, "a")])
        assert ss.zadd([(10.0, "a")], lt=True) == 0
        assert ss.zscore("a") == 5.0

    def test_lt_allows_add(self):
        ss = BPTreeSortedSet()
        assert ss.zadd([(1.0, "a")], lt=True) == 1

    def test_ch_counts_changes(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a")])
        result = ss.zadd([(5.0, "a"), (2.0, "b")], ch=True)
        assert result == 2  # 1 updated + 1 added

    def test_ch_no_change(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a")])
        result = ss.zadd([(1.0, "a")], ch=True)
        assert result == 0  # same score, no change

    def test_gt_equal_score_no_update(self):
        ss = BPTreeSortedSet()
        ss.zadd([(5.0, "a")])
        ss.zadd([(5.0, "a")], gt=True)
        assert ss.zscore("a") == 5.0

    def test_lt_equal_score_no_update(self):
        ss = BPTreeSortedSet()
        ss.zadd([(5.0, "a")])
        ss.zadd([(5.0, "a")], lt=True)
        assert ss.zscore("a") == 5.0


# ────────────────────────── zincrby ─────────────────────────────────────────


class TestZincrby:
    def test_increment_existing(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a")])
        assert ss.zincrby("a", 2.0) == 3.0
        assert ss.zscore("a") == 3.0

    def test_increment_new(self):
        ss = BPTreeSortedSet()
        assert ss.zincrby("a", 5.0) == 5.0
        assert ss.zscore("a") == 5.0
        assert ss.zcard() == 1

    def test_negative_increment(self):
        ss = BPTreeSortedSet()
        ss.zadd([(10.0, "a")])
        assert ss.zincrby("a", -3.0) == 7.0

    def test_increment_updates_rank(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a"), (2.0, "b"), (3.0, "c")])
        ss.zincrby("a", 10.0)  # a now has score 11.0
        assert ss.zrank("a") == 2
        assert ss.zrank("b") == 0


# ────────────────────────── zpop ────────────────────────────────────────────


class TestZpop:
    def test_zpopmin_single(self):
        ss = BPTreeSortedSet()
        ss.zadd([(3.0, "c"), (1.0, "a"), (2.0, "b")])
        result = ss.zpopmin(1)
        assert result == [("a", 1.0)]
        assert ss.zcard() == 2

    def test_zpopmin_multiple(self):
        ss = BPTreeSortedSet()
        ss.zadd([(3.0, "c"), (1.0, "a"), (2.0, "b")])
        result = ss.zpopmin(2)
        assert result == [("a", 1.0), ("b", 2.0)]
        assert ss.zcard() == 1

    def test_zpopmax_single(self):
        ss = BPTreeSortedSet()
        ss.zadd([(3.0, "c"), (1.0, "a"), (2.0, "b")])
        result = ss.zpopmax(1)
        assert result == [("c", 3.0)]
        assert ss.zcard() == 2

    def test_zpopmax_multiple(self):
        ss = BPTreeSortedSet()
        ss.zadd([(3.0, "c"), (1.0, "a"), (2.0, "b")])
        result = ss.zpopmax(2)
        assert result == [("c", 3.0), ("b", 2.0)]
        assert ss.zcard() == 1

    def test_zpopmin_empty(self):
        ss = BPTreeSortedSet()
        assert ss.zpopmin() == []

    def test_zpopmax_empty(self):
        ss = BPTreeSortedSet()
        assert ss.zpopmax() == []

    def test_zpopmin_more_than_size(self):
        ss = BPTreeSortedSet()
        ss.zadd([(1.0, "a")])
        result = ss.zpopmin(5)
        assert result == [("a", 1.0)]
        assert ss.zcard() == 0

    def test_zpopmax_descending_order(self):
        """ZPOPMAX with count > 1 must return highest-score elements first."""
        ss = BPTreeSortedSet()
        for i in range(10):
            ss.zadd([(float(i), f"m{i}")])
        result = ss.zpopmax(4)
        assert result == [
            ("m9", 9.0),
            ("m8", 8.0),
            ("m7", 7.0),
            ("m6", 6.0),
        ]
        assert ss.zcard() == 6

    def test_zpop_interleaved_with_ranks(self):
        """Pop from both ends, then verify remaining ranks are consistent."""
        ss = BPTreeSortedSet()
        for i in range(100):
            ss.zadd([(float(i), f"p{i:03d}")])

        ss.zpopmin(10)
        ss.zpopmax(10)
        assert ss.zcard() == 80

        # Ranks must be contiguous 0..79
        for i, expected_score in enumerate(range(10, 90)):
            member = f"p{expected_score:03d}"
            rank = ss.zrank(member)
            assert rank == i, f"rank of {member}: expected {i}, got {rank}"


# ────────────────────────── deletion consistency ───────────────────────────


class TestDeletionConsistency:
    def test_sequential_front_delete_range_scan(self):
        """After deleting elements from the front, range scans must remain
        consistent: correct count, no duplicates, proper ordering."""
        ss = BPTreeSortedSet()
        N = 500
        for i in range(N):
            ss.zadd([(float(i), f"m{i:04d}")])

        deleted = 200
        for i in range(deleted):
            ss.zrem(f"m{i:04d}")

        remaining = N - deleted
        assert ss.zcard() == remaining

        # Full range scan via leaf linked list
        all_elems = ss.zrangebyscore(float("-inf"), float("inf"))
        assert len(all_elems) == remaining, (
            f"Range scan returned {len(all_elems)} elements, expected {remaining}"
        )

        # No duplicates
        members = [m for m, _s in all_elems]
        assert len(set(members)) == len(members), (
            "Duplicate members found in range scan after front deletions"
        )

        # Verify ordering
        for j in range(len(all_elems) - 1):
            assert all_elems[j][1] <= all_elems[j + 1][1]

    def test_alternating_insert_delete_range(self):
        """Interleave inserts and front-deletes, then verify range scan."""
        ss = BPTreeSortedSet()

        # Phase 1: insert 300 elements
        for i in range(300):
            ss.zadd([(float(i), f"k{i:04d}")])

        # Phase 2: delete first 150
        for i in range(150):
            ss.zrem(f"k{i:04d}")

        # Phase 3: insert 200 more with higher scores
        for i in range(300, 500):
            ss.zadd([(float(i), f"k{i:04d}")])

        # Phase 4: delete another 100 from the front of remaining
        for i in range(150, 250):
            ss.zrem(f"k{i:04d}")

        expected_count = 300 - 150 + 200 - 100  # = 250
        assert ss.zcard() == expected_count

        all_elems = ss.zrangebyscore(float("-inf"), float("inf"))
        assert len(all_elems) == expected_count
        members = [m for m, _s in all_elems]
        assert len(set(members)) == len(members)


# ────────────────────────── large-scale correctness ─────────────────────────


class TestLargeScale:
    def test_random_operations(self):
        """10K random add/remove ops, verify final state against reference."""
        ss = BPTreeSortedSet()
        ref = {}  # member -> score

        rng = random.Random(42)

        for _ in range(10_000):
            op = rng.choice(["add", "add", "add", "rem"])
            member = f"m{rng.randint(0, 499)}"
            score = round(rng.uniform(-100, 100), 2)

            if op == "add":
                ss.zadd([(score, member)])
                ref[member] = score
            else:
                removed = ss.zrem(member)
                if member in ref:
                    assert removed == 1
                    del ref[member]
                else:
                    assert removed == 0

        # -- final consistency --
        assert ss.zcard() == len(ref)

        sorted_ref = sorted(ref.items(), key=lambda x: (x[1], x[0]))
        full_range = ss.zrange(0, -1)
        assert len(full_range) == len(sorted_ref)

        for (rm, rs), (sm, ss_score) in zip(sorted_ref, full_range):
            assert sm == rm, f"member mismatch: {sm} != {rm}"
            assert ss_score == rs, f"score mismatch for {sm}: {ss_score} != {rs}"

        # -- verify every score --
        for member, score in ref.items():
            assert ss.zscore(member) == score

        # -- verify every rank --
        for i, (member, score) in enumerate(sorted_ref):
            assert ss.zrank(member) == i, f"rank mismatch for {member}"

    def test_interleaved_add_delete_rank(self):
        """Repeatedly add and delete to stress tree rebalancing, then check."""
        ss = BPTreeSortedSet()
        ref = {}
        rng = random.Random(99)

        for phase in range(5):
            # add phase
            for _ in range(500):
                m = f"k{rng.randint(0, 200)}"
                s = round(rng.uniform(-50, 50), 2)
                ss.zadd([(s, m)])
                ref[m] = s

            # delete phase
            keys_to_del = rng.sample(list(ref.keys()), min(200, len(ref)))
            for m in keys_to_del:
                ss.zrem(m)
                del ref[m]

        assert ss.zcard() == len(ref)
        sorted_ref = sorted(ref.items(), key=lambda x: (x[1], x[0]))
        for i, (member, score) in enumerate(sorted_ref):
            assert ss.zrank(member) == i

    def test_score_range_consistency(self):
        """Verify zrangebyscore and zcount agree with full zrange."""
        ss = BPTreeSortedSet()
        rng = random.Random(77)
        for i in range(2000):
            ss.zadd([(round(rng.uniform(0, 100), 2), f"e{i}")])

        # pick some random score ranges and verify
        for _ in range(50):
            lo = round(rng.uniform(0, 80), 2)
            hi = round(rng.uniform(lo, 100), 2)

            by_score = ss.zrangebyscore(lo, hi)
            count = ss.zcount(lo, hi)
            assert len(by_score) == count

            # verify ordering
            for j in range(len(by_score) - 1):
                s_cur = by_score[j][1]
                s_nxt = by_score[j + 1][1]
                assert s_cur <= s_nxt
                if s_cur == s_nxt:
                    assert by_score[j][0] < by_score[j + 1][0]

    def test_range_scan_matches_rank_access(self):
        """Cross-validate range scan (leaf chain) against rank-based access
        (tree traversal) to catch leaf linked-list corruption."""
        ss = BPTreeSortedSet()
        rng = random.Random(55)
        for i in range(5000):
            ss.zadd([(round(rng.uniform(-50, 50), 2), f"v{i}")])

        # Get all via range scan (traverses leaf linked list)
        all_by_score = ss.zrangebyscore(float("-inf"), float("inf"))

        # Get all via rank-based range (uses tree traversal + leaf iteration)
        all_by_rank = ss.zrange(0, -1)

        assert len(all_by_score) == len(all_by_rank), (
            f"Range scan returned {len(all_by_score)} but rank access "
            f"returned {len(all_by_rank)}"
        )
        assert all_by_score == all_by_rank, (
            "Range scan and rank-based access returned different results"
        )

    def test_bulk_zincrby_rank_consistency(self):
        """After many zincrby operations that shuffle elements across leaves,
        verify all ranks remain accurate."""
        ss = BPTreeSortedSet()
        ref = {}
        rng = random.Random(88)

        # Initial load
        for i in range(500):
            score = round(rng.uniform(-20, 20), 2)
            ss.zadd([(score, f"z{i:03d}")])
            ref[f"z{i:03d}"] = score

        # Many increments that cause large rank changes
        for _ in range(2000):
            member = f"z{rng.randint(0, 499):03d}"
            incr = round(rng.uniform(-40, 40), 2)
            new_score = ss.zincrby(member, incr)
            ref[member] = ref[member] + incr
            assert abs(new_score - ref[member]) < 1e-9, (
                f"zincrby returned {new_score} but expected {ref[member]}"
            )

        # Verify all ranks
        sorted_ref = sorted(ref.items(), key=lambda x: (x[1], x[0]))
        for i, (member, _) in enumerate(sorted_ref):
            assert ss.zrank(member) == i, (
                f"rank of {member}: expected {i}, got {ss.zrank(member)}"
            )


# ────────────────────────── structural tests ────────────────────────────────


class TestTreeStructure:
    def test_branching_factor(self):
        """max_keys_per_node must be >= 8."""
        ss = BPTreeSortedSet()
        for i in range(500):
            ss.zadd([(float(i), f"m{i:04d}")])
        info = ss._get_tree_info()
        assert info["max_keys_per_node"] >= 8, (
            f"max_keys_per_node must be >= 8, got {info['max_keys_per_node']}"
        )

    def test_height_bounded(self):
        """Tree height must be O(log_B N)."""
        ss = BPTreeSortedSet()
        N = 10_000
        for i in range(N):
            ss.zadd([(float(i), f"m{i:05d}")])

        info = ss._get_tree_info()
        B = info["max_keys_per_node"]
        min_b = max(B // 2, 2)
        max_height = int(math.ceil(math.log(max(N, 1)) / math.log(min_b))) + 2
        assert info["height"] <= max_height, (
            f"Height {info['height']} exceeds bound {max_height} "
            f"for N={N}, B={B}"
        )

    def test_total_elements_matches(self):
        ss = BPTreeSortedSet()
        for i in range(300):
            ss.zadd([(float(i), f"e{i}")])
        info = ss._get_tree_info()
        assert info["total_elements"] == 300

    def test_integrity_after_inserts(self):
        ss = BPTreeSortedSet()
        for i in range(1000):
            ss.zadd([(float(i), f"m{i:04d}")])
        assert ss._verify_integrity(), "integrity check failed after 1000 inserts"

    def test_integrity_after_mixed_ops(self):
        ss = BPTreeSortedSet()
        rng = random.Random(123)

        for _ in range(5000):
            op = rng.choice(["add", "add", "rem"])
            member = f"m{rng.randint(0, 300)}"
            if op == "add":
                ss.zadd([(round(rng.uniform(-50, 50), 2), member)])
            else:
                ss.zrem(member)

        assert ss._verify_integrity(), "integrity check failed after mixed ops"

    def test_integrity_after_front_deletes(self):
        """Insert many elements, then delete from the front.

        This exercises the merge-right path in underflow handling when the
        leftmost child cannot borrow from a left sibling."""
        ss = BPTreeSortedSet()
        for i in range(2000):
            ss.zadd([(float(i), f"d{i:04d}")])

        for i in range(1000):
            ss.zrem(f"d{i:04d}")

        assert ss._verify_integrity(), "integrity failed after front deletes"
        assert ss.zcard() == 1000

    def test_integrity_after_total_drain(self):
        """Insert and remove everything, then re-insert."""
        ss = BPTreeSortedSet()
        for i in range(500):
            ss.zadd([(float(i), f"t{i}")])
        for i in range(500):
            ss.zrem(f"t{i}")

        assert ss.zcard() == 0
        assert ss._verify_integrity()

        for i in range(200):
            ss.zadd([(float(i), f"r{i}")])
        assert ss.zcard() == 200
        assert ss._verify_integrity()

    def test_node_efficiency(self):
        """Node count must be within reasonable bounds for a B+ tree.
        With N=10000 and B=24, leaf count ~= N/12..N/24, plus internal nodes.
        Total nodes should be far less than N."""
        ss = BPTreeSortedSet()
        N = 10_000
        for i in range(N):
            ss.zadd([(float(i), f"n{i:05d}")])

        info = ss._get_tree_info()
        B = info["max_keys_per_node"]
        # Minimum leaf count: N / B (all full), maximum: N / ceil(B/2) (half full)
        min_leaves = N // B
        max_leaves = N // max(B // 2, 1) + 1
        # Total nodes includes internal nodes; for B+ tree, internals << leaves
        # Total should be at most 2 * max_leaves (generous upper bound)
        assert info["node_count"] <= 2 * max_leaves, (
            f"Too many nodes: {info['node_count']} for N={N}, B={B}. "
            f"Expected at most ~{2 * max_leaves}"
        )
        assert info["node_count"] >= min_leaves, (
            f"Too few nodes: {info['node_count']} for N={N}, B={B}. "
            f"Expected at least ~{min_leaves}"
        )


# ────────────────────────── rank performance ────────────────────────────────


class TestRankPerformance:
    def test_rank_sublinear(self):
        """Rank queries on 50K elements must be sub-linear (not O(N))."""
        ss = BPTreeSortedSet()
        N = 50_000
        for i in range(N):
            ss.zadd([(float(i), f"m{i:06d}")])

        # sample 200 members spread across the keyspace
        members = [f"m{i:06d}" for i in range(0, N, N // 200)]

        start = time.perf_counter()
        for m in members:
            rank = ss.zrank(m)
            assert rank is not None
        elapsed = time.perf_counter() - start

        avg_us = (elapsed / len(members)) * 1e6
        # O(log N) ~ 20-50 us per query; O(N) ~ 5-10 ms per query
        assert avg_us < 1000, (
            f"Rank queries too slow: {avg_us:.1f}us avg -- "
            "expected <1000us for O(log N)"
        )


# ════════════════════════════════════════════════════════════════════════════════
# Part 2 — RESP protocol server tests (network-based)
# ════════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def server_proc():
    """Start the custom sorted set server on port 6380."""
    proc = subprocess.Popen(
        [sys.executable, "/app/server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    ready = False
    if REDIS_AVAILABLE:
        for _ in range(50):
            if proc.poll() is not None:
                break
            try:
                r = redis_lib.Redis(port=6380)
                r.ping()
                r.close()
                ready = True
                break
            except Exception:
                time.sleep(0.2)

    if not ready:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        pytest.fail(
            "Custom RESP server failed to start on port 6380 within 10 seconds"
        )

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _cli(port=6380):
    """Return a redis-py client connected to the given port."""
    return redis_lib.Redis(port=port, decode_responses=True)


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="redis-py not installed")
class TestRESPServer:
    """Tests that exercise the RESP protocol server via network connections."""

    def test_ping(self, server_proc):
        r = _cli()
        assert r.ping()
        r.close()

    def test_zadd_and_zcard(self, server_proc):
        r = _cli()
        r.delete("net:basic")
        added = r.zadd("net:basic", {"a": 1.0, "b": 2.0, "c": 3.0})
        assert added == 3
        assert r.zcard("net:basic") == 3
        r.close()

    def test_zadd_zrange_withscores(self, server_proc):
        r = _cli()
        r.delete("net:range")
        r.zadd("net:range", {"c": 3.0, "a": 1.0, "b": 2.0})
        result = r.zrange("net:range", 0, -1, withscores=True)
        assert result == [("a", 1.0), ("b", 2.0), ("c", 3.0)]
        r.close()

    def test_cross_validate_ordering(self, server_proc):
        """Same ZADD + ZRANGE sequence on both servers must produce same order."""
        custom = _cli(6380)
        ref = _cli(6379)
        key = "xval:order"
        for c in [custom, ref]:
            c.delete(key)
            c.zadd(key, {"cherry": 2.0, "apple": 2.0, "banana": 1.0, "date": 3.0})

        custom_result = custom.zrange(key, 0, -1, withscores=True)
        ref_result = ref.zrange(key, 0, -1, withscores=True)
        assert custom_result == ref_result
        custom.close()
        ref.close()

    def test_cross_validate_zadd_nx(self, server_proc):
        """NX flag behaviour must match Redis."""
        custom = _cli(6380)
        ref = _cli(6379)
        key = "xval:nx"
        for c in [custom, ref]:
            c.delete(key)
            c.zadd(key, {"a": 1.0})
            c.zadd(key, {"a": 9.0}, nx=True)

        assert custom.zscore(key, "a") == ref.zscore(key, "a") == 1.0
        custom.close()
        ref.close()

    def test_cross_validate_zrangebyscore(self, server_proc):
        """ZRANGEBYSCORE with LIMIT must match Redis."""
        custom = _cli(6380)
        ref = _cli(6379)
        key = "xval:rbs"
        for c in [custom, ref]:
            c.delete(key)
            for i in range(10):
                c.zadd(key, {f"m{i}": float(i)})

        custom_r = custom.zrangebyscore(key, 2, 8, start=1, num=3, withscores=True)
        ref_r = ref.zrangebyscore(key, 2, 8, start=1, num=3, withscores=True)
        assert custom_r == ref_r
        custom.close()
        ref.close()

    def test_cross_validate_zrank(self, server_proc):
        """ZRANK and ZREVRANK must match Redis."""
        custom = _cli(6380)
        ref = _cli(6379)
        key = "xval:rank"
        for c in [custom, ref]:
            c.delete(key)
            c.zadd(key, {"a": 1.0, "b": 2.0, "c": 3.0})

        assert custom.zrank(key, "b") == ref.zrank(key, "b")
        assert custom.zrevrank(key, "b") == ref.zrevrank(key, "b")
        assert custom.zrank(key, "missing") == ref.zrank(key, "missing")
        custom.close()
        ref.close()

    def test_cross_validate_zpopmax(self, server_proc):
        """ZPOPMAX ordering must match Redis."""
        custom = _cli(6380)
        ref = _cli(6379)
        key = "xval:popmax"
        for c in [custom, ref]:
            c.delete(key)
            c.zadd(key, {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0})

        custom_r = custom.zpopmax(key, 2)
        ref_r = ref.zpopmax(key, 2)
        assert custom_r == ref_r
        custom.close()
        ref.close()

    def test_multiple_keys(self, server_proc):
        """Different keys must have independent sorted sets."""
        r = _cli()
        r.delete("net:k1")
        r.delete("net:k2")
        r.zadd("net:k1", {"a": 1.0})
        r.zadd("net:k2", {"b": 2.0})
        assert r.zcard("net:k1") == 1
        assert r.zcard("net:k2") == 1
        assert r.zscore("net:k1", "a") == 1.0
        assert r.zscore("net:k2", "b") == 2.0
        assert r.zscore("net:k1", "b") is None
        r.close()

    def test_redis_cli_interaction(self, server_proc):
        """redis-cli must be able to communicate with the server."""
        result = subprocess.run(
            ["redis-cli", "-p", "6380", "ZADD", "cli:test", "1.0", "hello",
             "2.0", "world"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"redis-cli failed: {result.stderr}"
        # Should report integer 2 (two elements added)
        assert "2" in result.stdout

        result = subprocess.run(
            ["redis-cli", "-p", "6380", "ZRANGE", "cli:test", "0", "-1",
             "WITHSCORES"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "hello" in result.stdout
        assert "world" in result.stdout

    def test_redis_benchmark_zadd(self, server_proc):
        """redis-benchmark must complete a ZADD workload without crashing."""
        result = subprocess.run(
            ["redis-benchmark", "-p", "6380", "-q", "-n", "500", "-c", "1",
             "-t", "zadd"],
            capture_output=True, text=True, timeout=120,
        )
        # redis-benchmark should produce output with "requests per second"
        combined = result.stdout + result.stderr
        assert result.returncode == 0 or "requests per second" in combined.lower(), (
            f"redis-benchmark failed: stdout={result.stdout}, stderr={result.stderr}"
        )
