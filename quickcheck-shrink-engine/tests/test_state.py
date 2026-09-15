
"""Verification tests for the property-based testing library."""

import sys
import json
import os

sys.path.insert(0, "/app")

import pytest


# ---------------------------------------------------------------------------
# Buggy reference implementations (hardcoded so tests don't depend on fixes)
# ---------------------------------------------------------------------------

def _buggy_safe_divide(a, b):
    if b == 0:
        return 0
    return a // b


def _buggy_rle_encode(xs):
    if not xs:
        return []
    result = []
    count = 1
    for i in range(1, len(xs)):
        if xs[i] == xs[i - 1]:
            count += 1
        else:
            result.append((xs[i - 1], count))
            count = 1
    return result


def _buggy_rle_decode(encoded):
    result = []
    for val, count in encoded:
        result.extend([val] * count)
    return result


def _buggy_unique_sorted(xs):
    if not xs:
        return []
    s = sorted(xs)
    result = [s[0]]
    for i in range(1, len(s) - 1):
        if s[i] != result[-1]:
            result.append(s[i])
    return result


# ===========================================================================
# Test shrink_nonneg
# ===========================================================================

class TestShrinkNonneg:
    def test_zero(self):
        from pbt.shrink import shrink_nonneg
        assert list(shrink_nonneg(0)) == []

    def test_one(self):
        from pbt.shrink import shrink_nonneg
        assert list(shrink_nonneg(1)) == [0]

    def test_five(self):
        from pbt.shrink import shrink_nonneg
        assert list(shrink_nonneg(5)) == [0, 3, 4]

    def test_eleven(self):
        from pbt.shrink import shrink_nonneg
        assert list(shrink_nonneg(11)) == [0, 6, 9, 10]

    def test_hundred(self):
        from pbt.shrink import shrink_nonneg
        assert list(shrink_nonneg(100)) == [0, 50, 75, 88, 94, 97, 99]

    def test_two(self):
        from pbt.shrink import shrink_nonneg
        assert list(shrink_nonneg(2)) == [0, 1]

    def test_eight(self):
        from pbt.shrink import shrink_nonneg
        assert list(shrink_nonneg(8)) == [0, 4, 6, 7]


# ===========================================================================
# Test shrink_int
# ===========================================================================

class TestShrinkInt:
    def test_zero(self):
        from pbt.shrink import shrink_int
        assert list(shrink_int(0)) == []

    def test_positive_five(self):
        from pbt.shrink import shrink_int
        assert list(shrink_int(5)) == [0, 3, 4]

    def test_negative_five(self):
        from pbt.shrink import shrink_int
        assert list(shrink_int(-5)) == [0, 5, -3, -4]

    def test_one(self):
        from pbt.shrink import shrink_int
        assert list(shrink_int(1)) == [0]

    def test_minus_one(self):
        from pbt.shrink import shrink_int
        assert list(shrink_int(-1)) == [0]

    def test_minus_two(self):
        from pbt.shrink import shrink_int
        assert list(shrink_int(-2)) == [0, 2, -1]

    def test_large_positive(self):
        from pbt.shrink import shrink_int
        assert list(shrink_int(100)) == [0, 50, 75, 88, 94, 97, 99]

    def test_large_negative(self):
        from pbt.shrink import shrink_int
        assert list(shrink_int(-100)) == [0, 100, -50, -75, -88, -94, -97, -99]


# ===========================================================================
# Test shrink_bool
# ===========================================================================

class TestShrinkBool:
    def test_false(self):
        from pbt.shrink import shrink_bool
        assert list(shrink_bool(False)) == []

    def test_true(self):
        from pbt.shrink import shrink_bool
        assert list(shrink_bool(True)) == [False]


# ===========================================================================
# Test shrink_list
# ===========================================================================

class TestShrinkList:
    def test_empty(self):
        from pbt.shrink import shrink_list, shrink_nonneg
        assert list(shrink_list([], shrink_nonneg)) == []

    def test_single_one(self):
        from pbt.shrink import shrink_list, shrink_nonneg
        assert list(shrink_list([1], shrink_nonneg)) == [[], [0]]

    def test_single_eleven(self):
        from pbt.shrink import shrink_list, shrink_nonneg
        assert list(shrink_list([11], shrink_nonneg)) == [[], [0], [6], [9], [10]]

    def test_single_zero(self):
        from pbt.shrink import shrink_list, shrink_nonneg
        assert list(shrink_list([0], shrink_nonneg)) == [[]]

    def test_two_elements(self):
        from pbt.shrink import shrink_list, shrink_nonneg
        expected = [
            [],
            [5],
            [3],
            [0, 5],
            [2, 5],
            [3, 0],
            [3, 3],
            [3, 4],
        ]
        assert list(shrink_list([3, 5], shrink_nonneg)) == expected

    def test_three_elements(self):
        from pbt.shrink import shrink_list, shrink_nonneg
        expected = [
            [],
            [4, 6],
            [2, 6],
            [2, 4],
            [0, 4, 6],
            [1, 4, 6],
            [2, 0, 6],
            [2, 2, 6],
            [2, 3, 6],
            [2, 4, 0],
            [2, 4, 3],
            [2, 4, 5],
        ]
        assert list(shrink_list([2, 4, 6], shrink_nonneg)) == expected

    def test_four_elements(self):
        from pbt.shrink import shrink_list, shrink_nonneg
        result = list(shrink_list([1, 2, 3, 4], shrink_nonneg))
        assert result[0] == []
        assert result[1] == [3, 4]
        assert result[2] == [1, 2]
        assert result[3] == [2, 3, 4]
        assert result[4] == [1, 3, 4]
        assert result[5] == [1, 2, 4]
        assert result[6] == [1, 2, 3]

    def test_nested_with_bool_shrinker(self):
        from pbt.shrink import shrink_list, shrink_bool
        result = list(shrink_list([True, False], shrink_bool))
        expected = [[], [False], [True], [False, False]]
        assert result == expected


# ===========================================================================
# Test shrink_tuple
# ===========================================================================

class TestShrinkTuple:
    def test_bool_pair_both_true(self):
        from pbt.shrink import shrink_tuple, shrink_bool
        result = list(shrink_tuple((True, True), [shrink_bool, shrink_bool]))
        assert result == [(False, True), (True, False)]

    def test_bool_pair_one_true(self):
        from pbt.shrink import shrink_tuple, shrink_bool
        result = list(shrink_tuple((True, False), [shrink_bool, shrink_bool]))
        assert result == [(False, False)]

    def test_bool_pair_none_true(self):
        from pbt.shrink import shrink_tuple, shrink_bool
        result = list(shrink_tuple((False, False), [shrink_bool, shrink_bool]))
        assert result == []

    def test_int_pair(self):
        from pbt.shrink import shrink_tuple, shrink_nonneg
        result = list(shrink_tuple((3, 5), [shrink_nonneg, shrink_nonneg]))
        expected = [(0, 5), (2, 5), (3, 0), (3, 3), (3, 4)]
        assert result == expected

    def test_mixed_shrinkers(self):
        from pbt.shrink import shrink_tuple, shrink_int, shrink_nonneg
        result = list(shrink_tuple((-5, 3), [shrink_int, shrink_nonneg]))
        expected = [(0, 3), (5, 3), (-3, 3), (-4, 3), (-5, 0), (-5, 2)]
        assert result == expected


# ===========================================================================
# Test find_minimal_counterexample
# ===========================================================================

class TestFindMinimal:
    def test_int_threshold_at_5(self):
        from pbt.engine import find_minimal_counterexample
        from pbt.shrink import shrink_nonneg
        minimal = find_minimal_counterexample(
            lambda x: x < 5, 100, shrink_nonneg
        )
        assert minimal == 5

    def test_int_threshold_at_10(self):
        from pbt.engine import find_minimal_counterexample
        from pbt.shrink import shrink_nonneg
        minimal = find_minimal_counterexample(
            lambda x: x < 10, 1000, shrink_nonneg
        )
        assert minimal == 10

    def test_int_threshold_at_1(self):
        from pbt.engine import find_minimal_counterexample
        from pbt.shrink import shrink_nonneg
        minimal = find_minimal_counterexample(
            lambda x: x < 1, 50, shrink_nonneg
        )
        assert minimal == 1

    def test_list_length_threshold(self):
        from pbt.engine import find_minimal_counterexample
        from pbt.shrink import shrink_list, shrink_nonneg
        shrinker = lambda xs: list(shrink_list(xs, shrink_nonneg))
        minimal = find_minimal_counterexample(
            lambda xs: len(xs) <= 1, [5, 3, 8], shrinker
        )
        assert minimal == [0, 0]

    def test_tuple_shrinking(self):
        from pbt.engine import find_minimal_counterexample
        from pbt.shrink import shrink_tuple, shrink_nonneg
        shrinker = lambda t: list(
            shrink_tuple(t, [shrink_nonneg, shrink_nonneg])
        )
        minimal = find_minimal_counterexample(
            lambda t: t[0] + t[1] <= 3, (50, 50), shrinker
        )
        assert minimal == (0, 4)

    def test_with_test_result(self):
        from pbt.engine import find_minimal_counterexample, TestResult
        from pbt.shrink import shrink_nonneg

        def pred(x):
            if x < 5:
                return TestResult.passed()
            return TestResult.failed()

        minimal = find_minimal_counterexample(pred, 100, shrink_nonneg)
        assert minimal == 5


# ===========================================================================
# Test quickcheck
# ===========================================================================

class TestQuickCheck:
    def test_passing_property(self):
        from pbt.engine import quickcheck
        from pbt.shrink import shrink_nonneg
        result = quickcheck(
            lambda x: x >= 0,
            generator=lambda gen: gen.small_int(0, 100),
            shrinker=lambda x: list(shrink_nonneg(x)),
            seed=42,
        )
        assert result["status"] == "passed"
        assert result["num_passed"] == 100

    def test_failing_property(self):
        from pbt.engine import quickcheck
        from pbt.shrink import shrink_nonneg
        result = quickcheck(
            lambda x: x <= 10,
            generator=lambda gen: gen.small_int(0, 100),
            shrinker=lambda x: list(shrink_nonneg(x)),
            seed=42,
        )
        assert result["status"] == "failed"
        assert result["counterexample"] == 11

    def test_discard_mechanism(self):
        from pbt.engine import quickcheck, TestResult
        from pbt.shrink import shrink_nonneg

        def prop(x):
            if x % 2 == 0:
                return TestResult.discard()
            return TestResult.from_bool(True)

        result = quickcheck(
            prop,
            generator=lambda gen: gen.small_int(0, 100),
            shrinker=lambda x: list(shrink_nonneg(x)),
            seed=42,
        )
        assert result["status"] == "passed"

    def test_gave_up(self):
        from pbt.engine import quickcheck, TestResult
        from pbt.shrink import shrink_nonneg

        result = quickcheck(
            lambda x: TestResult.discard(),
            generator=lambda gen: gen.small_int(0, 100),
            shrinker=lambda x: list(shrink_nonneg(x)),
            num_tests=100,
            max_tests=200,
            seed=42,
        )
        assert result["status"] == "gave_up"
        assert result["num_passed"] == 0

    def test_returns_original_input(self):
        from pbt.engine import quickcheck
        from pbt.shrink import shrink_nonneg
        result = quickcheck(
            lambda x: x <= 10,
            generator=lambda gen: gen.small_int(0, 100),
            shrinker=lambda x: list(shrink_nonneg(x)),
            seed=42,
        )
        assert result["status"] == "failed"
        assert "original" in result
        assert result["original"] > 10


# ===========================================================================
# Test counterexamples.json
# ===========================================================================

class TestCounterexamples:
    @pytest.fixture
    def ce_data(self):
        with open("/app/counterexamples.json") as f:
            return json.load(f)

    def test_file_exists(self):
        assert os.path.exists("/app/counterexamples.json")

    def test_has_all_keys(self, ce_data):
        assert "safe_divide" in ce_data
        assert "rle_encode" in ce_data
        assert "unique_sorted" in ce_data

    def test_safe_divide_ce_fails_property(self, ce_data):
        ce = ce_data["safe_divide"]
        assert isinstance(ce, list) and len(ce) == 2
        a, b = ce
        assert b != 0, "b must be non-zero for the bug to manifest"
        q = _buggy_safe_divide(a, b)
        r = a - q * b
        assert r != 0, "remainder must be non-zero for the bug to manifest"
        assert (r > 0) != (a > 0), "sign mismatch proves the floor-division bug"

    def test_safe_divide_ce_is_minimal(self, ce_data):
        from pbt.shrink import shrink_int, shrink_tuple

        ce = tuple(ce_data["safe_divide"])

        def fails(args):
            a, b = args
            if b == 0:
                return False
            q = _buggy_safe_divide(a, b)
            r = a - q * b
            if r == 0:
                return False
            return (r > 0) != (a > 0)

        for shrunk in shrink_tuple(ce, [shrink_int, shrink_int]):
            assert not fails(shrunk), (
                f"CE {ce} is not minimal: {shrunk} also fails"
            )

    def test_rle_encode_ce_fails_property(self, ce_data):
        ce = ce_data["rle_encode"]
        assert isinstance(ce, list) and len(ce) > 0
        encoded = _buggy_rle_encode(ce)
        decoded = _buggy_rle_decode(encoded)
        assert decoded != ce, f"CE {ce} should fail rle roundtrip"

    def test_rle_encode_ce_is_minimal(self, ce_data):
        from pbt.shrink import shrink_list, shrink_nonneg

        ce = ce_data["rle_encode"]

        def fails(xs):
            if not xs:
                return False
            encoded = _buggy_rle_encode(xs)
            decoded = _buggy_rle_decode(encoded)
            return decoded != xs

        for shrunk in shrink_list(ce, shrink_nonneg):
            assert not fails(shrunk), (
                f"CE {ce} is not minimal: {shrunk} also fails"
            )

    def test_unique_sorted_ce_fails_property(self, ce_data):
        ce = ce_data["unique_sorted"]
        assert isinstance(ce, list) and len(ce) >= 2
        result = _buggy_unique_sorted(ce)
        assert set(result) != set(ce), f"CE {ce} should fail unique_sorted property"

    def test_unique_sorted_ce_is_minimal(self, ce_data):
        from pbt.shrink import shrink_list, shrink_nonneg

        ce = ce_data["unique_sorted"]

        def fails(xs):
            if len(xs) < 2:
                return False
            result = _buggy_unique_sorted(xs)
            return set(result) != set(xs)

        for shrunk in shrink_list(ce, shrink_nonneg):
            assert not fails(shrunk), (
                f"CE {ce} is not minimal: {shrunk} also fails"
            )


# ===========================================================================
# Test that bugs in targets.py have been fixed
# ===========================================================================

class TestFixedTargets:
    def test_safe_divide_truncates_toward_zero(self):
        from targets import safe_divide
        assert safe_divide(7, 2) == 3
        assert safe_divide(-7, 2) == -3
        assert safe_divide(7, -2) == -3
        assert safe_divide(-7, -2) == 3
        assert safe_divide(-1, 2) == 0
        assert safe_divide(-3, 2) == -1
        assert safe_divide(0, 5) == 0
        assert safe_divide(5, 0) == 0
        assert safe_divide(1, 1) == 1
        assert safe_divide(-1, 1) == -1

    def test_safe_divide_property(self):
        from targets import safe_divide
        from pbt.engine import quickcheck
        from pbt.shrink import shrink_int, shrink_tuple

        def prop(args):
            a, b = args
            if b == 0:
                return True
            q = safe_divide(a, b)
            r = a - q * b
            if r == 0:
                return True
            return (r > 0) == (a > 0)

        result = quickcheck(
            prop,
            generator=lambda gen: (
                gen.small_int(-50, 50),
                gen.small_int(-50, 50),
            ),
            shrinker=lambda args: list(
                shrink_tuple(args, [shrink_int, shrink_int])
            ),
            seed=123,
        )
        assert result["status"] == "passed"

    def test_rle_encode_includes_last_run(self):
        from targets import rle_encode, rle_decode
        assert rle_encode([]) == []
        assert rle_encode([1]) == [(1, 1)]
        assert rle_encode([1, 1, 1]) == [(1, 3)]
        assert rle_encode([1, 2, 3]) == [(1, 1), (2, 1), (3, 1)]
        assert rle_encode([1, 1, 2, 3, 3]) == [(1, 2), (2, 1), (3, 2)]

    def test_rle_roundtrip_property(self):
        from targets import rle_encode, rle_decode
        from pbt.engine import quickcheck
        from pbt.shrink import shrink_list, shrink_nonneg

        result = quickcheck(
            lambda xs: rle_decode(rle_encode(xs)) == xs,
            generator=lambda gen: gen.list(
                lambda: gen.small_int(0, 5), max_len=20
            ),
            shrinker=lambda xs: list(shrink_list(xs, shrink_nonneg)),
            seed=123,
        )
        assert result["status"] == "passed"

    def test_unique_sorted_includes_all_elements(self):
        from targets import unique_sorted
        assert unique_sorted([]) == []
        assert unique_sorted([1]) == [1]
        assert unique_sorted([1, 2, 3]) == [1, 2, 3]
        assert unique_sorted([3, 1, 2]) == [1, 2, 3]
        assert unique_sorted([3, 1, 2, 1]) == [1, 2, 3]
        assert unique_sorted([0, 1]) == [0, 1]

    def test_unique_sorted_property(self):
        from targets import unique_sorted
        from pbt.engine import quickcheck
        from pbt.shrink import shrink_list, shrink_nonneg

        result = quickcheck(
            lambda xs: set(unique_sorted(xs)) == set(xs),
            generator=lambda gen: gen.list(
                lambda: gen.small_int(0, 10), max_len=20
            ),
            shrinker=lambda xs: list(shrink_list(xs, shrink_nonneg)),
            seed=123,
        )
        assert result["status"] == "passed"


# ===========================================================================
# Test shrink_interval_set
# ===========================================================================

class TestShrinkIntervalSet:
    def test_empty(self):
        from pbt.structured import shrink_interval_set
        assert list(shrink_interval_set([])) == []

    def test_single_minimal(self):
        from pbt.structured import shrink_interval_set
        # (0,1) is the smallest valid interval — can only shrink to empty
        assert list(shrink_interval_set([(0, 1)])) == [[]]

    def test_single_interval(self):
        from pbt.structured import shrink_interval_set
        # (2,5): gap for hi = 5-(2+1) = 2, shrink_nonneg(2) = [0,1]
        #        gap for lo = 2-0 = 2, shrink_nonneg(2) = [0,1]
        expected = [
            [],
            [(2, 3)],   # hi shrunk: lo+1+0 = 3
            [(2, 4)],   # hi shrunk: lo+1+1 = 4
            [(0, 5)],   # lo shrunk: 0+0 = 0
            [(1, 5)],   # lo shrunk: 0+1 = 1
        ]
        assert list(shrink_interval_set([(2, 5)])) == expected

    def test_two_intervals(self):
        from pbt.structured import shrink_interval_set
        expected = [
            [],                       # phase 0
            [(5, 8)],                 # remove index 0
            [(1, 3)],                 # remove index 1
            [(1, 2), (5, 8)],         # shrink hi of idx 0: gap=1, [0] -> hi=2
            [(0, 3), (5, 8)],         # shrink lo of idx 0: gap=1, [0] -> lo=0
            [(1, 3), (5, 6)],         # shrink hi of idx 1: gap=2, [0,1] -> hi=6
            [(1, 3), (5, 7)],         # shrink hi of idx 1: gap=2, [0,1] -> hi=7
            [(1, 3), (3, 8)],         # shrink lo of idx 1: gap=2, [0,1] -> lo=3
            [(1, 3), (4, 8)],         # shrink lo of idx 1: gap=2, [0,1] -> lo=4
        ]
        assert list(shrink_interval_set([(1, 3), (5, 8)])) == expected

    def test_adjacent_intervals(self):
        from pbt.structured import shrink_interval_set
        # (0,2),(2,4): adjacent (hi_0 == lo_1)
        expected = [
            [],                       # phase 0
            [(2, 4)],                 # remove index 0
            [(0, 2)],                 # remove index 1
            [(0, 1), (2, 4)],         # shrink hi of idx 0: gap=1, [0] -> hi=1
            # shrink lo of idx 0: gap=0, nothing
            [(0, 2), (2, 3)],         # shrink hi of idx 1: gap=1, [0] -> hi=3
            # shrink lo of idx 1: lower_bound=2, gap=0, nothing
        ]
        assert list(shrink_interval_set([(0, 2), (2, 4)])) == expected

    def test_three_intervals_structure(self):
        from pbt.structured import shrink_interval_set
        result = list(shrink_interval_set([(0, 2), (4, 6), (8, 10)]))
        # Phase 0
        assert result[0] == []
        # Phase 1: removals
        assert result[1] == [(4, 6), (8, 10)]
        assert result[2] == [(0, 2), (8, 10)]
        assert result[3] == [(0, 2), (4, 6)]
        # Total: 1 (empty) + 3 (removals) + 7 (endpoint shrinks) = 11
        assert len(result) == 11

    def test_three_intervals_endpoint_shrinks(self):
        from pbt.structured import shrink_interval_set
        result = list(shrink_interval_set([(0, 2), (4, 6), (8, 10)]))
        # idx 0: (0,2), hi gap=1 -> [(0,1),...], lo gap=0 -> nothing
        assert result[4] == [(0, 1), (4, 6), (8, 10)]
        # idx 1: (4,6), hi gap=1 -> [(4,5),...], lo lower_bound=2, gap=2 -> [0,1]
        assert result[5] == [(0, 2), (4, 5), (8, 10)]
        assert result[6] == [(0, 2), (2, 6), (8, 10)]   # lo shrunk to 2
        assert result[7] == [(0, 2), (3, 6), (8, 10)]   # lo shrunk to 3
        # idx 2: (8,10), hi gap=1 -> [(8,9),...], lo lower_bound=6, gap=2 -> [0,1]
        assert result[8] == [(0, 2), (4, 6), (8, 9)]
        assert result[9] == [(0, 2), (4, 6), (6, 10)]   # lo shrunk to 6
        assert result[10] == [(0, 2), (4, 6), (7, 10)]  # lo shrunk to 7

    def test_invariants_maintained(self):
        """All shrunk interval sets must maintain structural invariants."""
        from pbt.structured import shrink_interval_set
        test_cases = [
            [(0, 1)],
            [(2, 5)],
            [(1, 3), (5, 8)],
            [(0, 2), (2, 4)],
            [(0, 2), (4, 6), (8, 10)],
            [(3, 7)],
            [(0, 5), (10, 15), (20, 25)],
        ]
        for intervals in test_cases:
            for shrunk in shrink_interval_set(intervals):
                assert isinstance(shrunk, list), f"Expected list, got {type(shrunk)}"
                for j, (lo, hi) in enumerate(shrunk):
                    assert 0 <= lo < hi, (
                        f"Invalid interval ({lo}, {hi}) in shrunk {shrunk} "
                        f"from input {intervals}"
                    )
                    if j > 0:
                        assert shrunk[j - 1][1] <= lo, (
                            f"Overlapping/unsorted intervals "
                            f"{shrunk[j-1]} and ({lo},{hi}) in shrunk {shrunk} "
                            f"from input {intervals}"
                        )

    def test_wide_interval(self):
        from pbt.structured import shrink_interval_set
        # (0, 100): hi gap=99, lo gap=0
        # shrink_nonneg(99) = [0, 50, 75, 88, 94, 97, 99... wait]
        # shrink_nonneg(99) = [0, 50, 75, 88, 94, 97, 99-1=98]
        # Actually: i=49 -> 99-49=50, i=24 -> 99-24=75, i=12->87, i=6->93, i=3->96, i=1->98
        # So [0, 50, 75, 87, 93, 96, 98]
        result = list(shrink_interval_set([(0, 100)]))
        assert result[0] == []
        assert result[1] == [(0, 1)]   # hi shrunk to minimum: 0+1+0=1
        assert (0, 100) not in [tuple(r[0]) if r else None for r in result]


# ===========================================================================
# Test property audit results
# ===========================================================================

class TestPropertyAudit:
    @pytest.fixture
    def audit_data(self):
        with open("/app/property_audit_results.json") as f:
            return json.load(f)

    def test_file_exists(self):
        assert os.path.exists("/app/property_audit_results.json")

    def test_has_all_keys(self, audit_data):
        for key in ["prop_idempotent", "prop_covers_all",
                     "prop_no_growth", "prop_each_preserved"]:
            assert key in audit_data, f"Missing key: {key}"

    def test_valid_classifications(self, audit_data):
        valid = {"sound", "weak", "strong"}
        for key, val in audit_data.items():
            assert val in valid, f"{key} has invalid classification '{val}'"

    def test_prop_idempotent_is_weak(self, audit_data):
        # Both v1 and v2 produce idempotent output since their outputs
        # are always valid non-overlapping interval sets
        assert audit_data["prop_idempotent"] == "weak"

    def test_prop_covers_all_is_sound(self, audit_data):
        # v1 covers all input points; v2 loses coverage when
        # contained intervals overwrite the hi endpoint
        assert audit_data["prop_covers_all"] == "sound"

    def test_prop_no_growth_is_strong(self, audit_data):
        # Correct merging can produce intervals wider than any input
        # (e.g., merging (0,2) and (1,3) produces (0,3) with width 3 > 2)
        assert audit_data["prop_no_growth"] == "strong"

    def test_prop_each_preserved_is_sound(self, audit_data):
        # Correct merging always contains all input intervals within outputs;
        # v2 fails because buggy hi can shrink the merged interval
        assert audit_data["prop_each_preserved"] == "sound"

    def test_ground_truth_verification(self):
        """Independently verify the expected classifications are correct."""
        from merge import (
            merge_intervals_v1, merge_intervals_v2,
            prop_idempotent, prop_covers_all, prop_no_growth, prop_each_preserved,
        )

        inputs = [
            [],
            [(0, 1)],
            [(0, 2), (1, 3)],
            [(0, 3), (1, 2)],
            [(0, 5), (1, 3), (2, 4)],
            [(0, 1), (1, 2), (2, 3)],
            [(0, 2), (3, 5)],
            [(0, 10), (1, 2), (3, 4), (5, 6)],
        ]

        # prop_idempotent: should pass for both v1 and v2
        for inp in inputs:
            assert prop_idempotent(merge_intervals_v1, inp)
            assert prop_idempotent(merge_intervals_v2, inp)

        # prop_covers_all: should pass for v1, fail for v2 on some input
        for inp in inputs:
            assert prop_covers_all(merge_intervals_v1, inp)
        assert not all(prop_covers_all(merge_intervals_v2, inp) for inp in inputs)

        # prop_no_growth: should fail for v1 on some input
        assert not all(prop_no_growth(merge_intervals_v1, inp) for inp in inputs)

        # prop_each_preserved: should pass for v1, fail for v2 on some input
        for inp in inputs:
            assert prop_each_preserved(merge_intervals_v1, inp)
        assert not all(prop_each_preserved(merge_intervals_v2, inp) for inp in inputs)
