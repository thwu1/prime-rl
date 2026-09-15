"""Tests for the interval set library and Z3 verification framework."""


import pytest
import random
import sys
import json
import inspect

sys.path.insert(0, '/app')
import intervals as iv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_iset(rng, max_intervals=8, lo_range=(-30, 30), max_len=15):
    """Generate a random valid IntervalSet using the given RNG."""
    points = set()
    n = rng.randint(0, max_intervals)
    for _ in range(n):
        lo = rng.randint(*lo_range)
        length = rng.randint(1, max_len)
        for p in range(lo, lo + length):
            points.add(p)
    return iv.from_points(points)


def _ref_union(a, b):
    return iv.from_points(iv.to_points(a) + iv.to_points(b))


def _ref_intersection(a, b):
    sa, sb = set(iv.to_points(a)), set(iv.to_points(b))
    return iv.from_points(sa & sb)


def _ref_difference(a, b):
    sa, sb = set(iv.to_points(a)), set(iv.to_points(b))
    return iv.from_points(sa - sb)


def _ref_complement(iset, lo, hi):
    s = set(iv.to_points(iset))
    return iv.from_points(set(range(lo, hi)) - s)


def _ref_sym_diff(a, b):
    sa, sb = set(iv.to_points(a)), set(iv.to_points(b))
    return iv.from_points(sa ^ sb)


# ===========================================================================
# Part 1: Interval operation correctness tests
# ===========================================================================

class TestValidate:
    def test_valid_examples(self):
        assert iv.validate([]) is True
        assert iv.validate([(0, 1)]) is True
        assert iv.validate([(1, 5), (7, 10), (20, 30)]) is True

    def test_empty_interval_rejected(self):
        with pytest.raises(ValueError):
            iv.validate([(5, 5)])

    def test_inverted_interval_rejected(self):
        with pytest.raises(ValueError):
            iv.validate([(5, 3)])

    def test_overlapping_rejected(self):
        with pytest.raises(ValueError):
            iv.validate([(1, 5), (3, 8)])

    def test_adjacent_rejected(self):
        with pytest.raises(ValueError):
            iv.validate([(1, 3), (3, 5)])

    def test_unsorted_rejected(self):
        with pytest.raises(ValueError):
            iv.validate([(5, 10), (1, 3)])


class TestPointConversion:
    def test_roundtrip(self):
        iset = [(1, 4), (7, 10)]
        assert iv.from_points(iv.to_points(iset)) == iset

    def test_empty(self):
        assert iv.from_points([]) == []
        assert iv.to_points([]) == []

    def test_single_point(self):
        assert iv.from_points([5]) == [(5, 6)]

    def test_consecutive(self):
        assert iv.from_points([1, 2, 3]) == [(1, 4)]

    def test_gaps(self):
        assert iv.from_points([1, 3, 5]) == [(1, 2), (3, 4), (5, 6)]


class TestUnion:
    def test_disjoint(self):
        result = iv.union([(1, 3)], [(5, 7)])
        assert result == [(1, 3), (5, 7)]
        iv.validate(result)

    def test_overlapping(self):
        result = iv.union([(1, 5)], [(3, 8)])
        assert result == [(1, 8)]
        iv.validate(result)

    def test_adjacent_must_merge(self):
        """Adjacent intervals [1,3) and [3,5) must merge into [1,5)."""
        result = iv.union([(1, 3)], [(3, 5)])
        assert result == [(1, 5)], f"Adjacent intervals not merged: {result}"
        iv.validate(result)

    def test_adjacent_must_merge_reverse(self):
        result = iv.union([(3, 5)], [(1, 3)])
        assert result == [(1, 5)], f"Adjacent intervals not merged: {result}"
        iv.validate(result)

    def test_empty_inputs(self):
        assert iv.union([], [(1, 3)]) == [(1, 3)]
        assert iv.union([(1, 3)], []) == [(1, 3)]
        assert iv.union([], []) == []

    def test_subset(self):
        result = iv.union([(1, 10)], [(3, 5)])
        assert result == [(1, 10)]

    def test_identical(self):
        result = iv.union([(1, 5), (7, 10)], [(1, 5), (7, 10)])
        assert result == [(1, 5), (7, 10)]
        iv.validate(result)

    def test_multiple_adjacent_chain(self):
        """Chain of adjacent intervals must all merge."""
        a = [(1, 3), (5, 7)]
        b = [(3, 5), (7, 9)]
        result = iv.union(a, b)
        assert result == [(1, 9)], f"Chain not fully merged: {result}"
        iv.validate(result)

    def test_property(self):
        rng = random.Random(1001)
        for trial in range(100):
            a = _random_iset(rng)
            b = _random_iset(rng)
            result = iv.union(a, b)
            expected = _ref_union(a, b)
            iv.validate(result)
            assert result == expected, (
                f"Trial {trial}: union({a}, {b}) = {result}, expected {expected}"
            )


class TestIntersection:
    def test_overlapping(self):
        result = iv.intersection([(1, 5)], [(3, 8)])
        assert result == [(3, 5)]
        iv.validate(result)

    def test_disjoint(self):
        result = iv.intersection([(1, 3)], [(5, 8)])
        assert result == []

    def test_touching_endpoints_empty(self):
        """[1,5) and [5,10) share no integer points; intersection is empty."""
        result = iv.intersection([(1, 5)], [(5, 10)])
        assert result == [], f"Touching intervals should have empty intersection: {result}"

    def test_touching_endpoints_empty_2(self):
        """[1,3) and [3,5) share no points."""
        result = iv.intersection([(1, 3)], [(3, 5)])
        assert result == [], f"Got {result}"

    def test_no_empty_intervals_in_output(self):
        """Output must never contain empty intervals (lo == hi)."""
        a = [(1, 5)]
        b = [(5, 10)]
        result = iv.intersection(a, b)
        for lo, hi in result:
            assert lo < hi, f"Empty interval ({lo}, {hi}) in intersection output"

    def test_subset(self):
        result = iv.intersection([(1, 10)], [(3, 7)])
        assert result == [(3, 7)]

    def test_identical(self):
        result = iv.intersection([(1, 5), (7, 10)], [(1, 5), (7, 10)])
        assert result == [(1, 5), (7, 10)]

    def test_empty_inputs(self):
        assert iv.intersection([], [(1, 3)]) == []
        assert iv.intersection([(1, 3)], []) == []

    def test_multiple_overlaps(self):
        a = [(1, 10)]
        b = [(3, 5), (7, 12)]
        result = iv.intersection(a, b)
        assert result == [(3, 5), (7, 10)]
        iv.validate(result)

    def test_property(self):
        rng = random.Random(2002)
        for trial in range(100):
            a = _random_iset(rng)
            b = _random_iset(rng)
            result = iv.intersection(a, b)
            expected = _ref_intersection(a, b)
            if result:
                iv.validate(result)
            assert result == expected, (
                f"Trial {trial}: intersection({a}, {b}) = {result}, "
                f"expected {expected}"
            )


class TestDifference:
    def test_disjoint(self):
        result = iv.difference([(1, 5)], [(7, 10)])
        assert result == [(1, 5)]

    def test_full_removal(self):
        result = iv.difference([(3, 5)], [(1, 10)])
        assert result == []

    def test_left_remainder(self):
        result = iv.difference([(1, 10)], [(5, 15)])
        assert result == [(1, 5)]

    def test_right_remainder(self):
        result = iv.difference([(1, 10)], [(-5, 5)])
        assert result == [(5, 10)]

    def test_middle_punch(self):
        result = iv.difference([(1, 10)], [(3, 7)])
        assert result == [(1, 3), (7, 10)]
        iv.validate(result)

    def test_b_spans_two_a_intervals(self):
        """When b[j] overlaps a[i] and a[i+1], both must be subtracted."""
        a = [(1, 5), (6, 10)]
        b = [(3, 7)]
        result = iv.difference(a, b)
        expected = [(1, 3), (7, 10)]
        assert result == expected, f"Got {result}, expected {expected}"
        iv.validate(result)

    def test_b_spans_three_a_intervals(self):
        """Single b-interval spanning three a-intervals."""
        a = [(1, 3), (5, 7), (9, 11)]
        b = [(2, 10)]
        result = iv.difference(a, b)
        expected = [(1, 2), (10, 11)]
        assert result == expected, f"Got {result}, expected {expected}"
        iv.validate(result)

    def test_b_covers_all_a(self):
        a = [(1, 3), (5, 7), (9, 11)]
        b = [(0, 20)]
        result = iv.difference(a, b)
        assert result == []

    def test_empty_inputs(self):
        assert iv.difference([(1, 3)], []) == [(1, 3)]
        assert iv.difference([], [(1, 3)]) == []

    def test_multiple_b_subtract(self):
        a = [(1, 20)]
        b = [(3, 5), (8, 10), (14, 16)]
        result = iv.difference(a, b)
        expected = [(1, 3), (5, 8), (10, 14), (16, 20)]
        assert result == expected
        iv.validate(result)

    def test_property(self):
        rng = random.Random(3003)
        for trial in range(100):
            a = _random_iset(rng)
            b = _random_iset(rng)
            result = iv.difference(a, b)
            expected = _ref_difference(a, b)
            if result:
                iv.validate(result)
            assert result == expected, (
                f"Trial {trial}: difference({a}, {b}) = {result}, "
                f"expected {expected}"
            )


class TestComplement:
    def test_empty_set(self):
        result = iv.complement([], 0, 10)
        assert result == [(0, 10)]
        iv.validate(result)

    def test_full_range(self):
        result = iv.complement([(0, 10)], 0, 10)
        assert result == []

    def test_gaps(self):
        result = iv.complement([(2, 5), (8, 10)], 0, 15)
        assert result == [(0, 2), (5, 8), (10, 15)]
        iv.validate(result)

    def test_partial_overlap_left(self):
        result = iv.complement([(-5, 3)], 0, 10)
        assert result == [(3, 10)]

    def test_partial_overlap_right(self):
        result = iv.complement([(7, 15)], 0, 10)
        assert result == [(0, 7)]

    def test_empty_range(self):
        result = iv.complement([(1, 5)], 3, 3)
        assert result == []

    def test_inverted_range(self):
        result = iv.complement([(1, 5)], 5, 3)
        assert result == []

    def test_iset_outside_range(self):
        result = iv.complement([(20, 30)], 0, 10)
        assert result == [(0, 10)]

    def test_property(self):
        rng = random.Random(4004)
        for trial in range(80):
            iset = _random_iset(rng, lo_range=(0, 40))
            lo = rng.randint(-5, 20)
            hi = rng.randint(lo, 50)
            result = iv.complement(iset, lo, hi)
            expected = _ref_complement(iset, lo, hi)
            if result:
                iv.validate(result)
            assert result == expected, (
                f"Trial {trial}: complement({iset}, {lo}, {hi}) = {result}, "
                f"expected {expected}"
            )


class TestSymmetricDifference:
    def test_disjoint(self):
        result = iv.symmetric_difference([(1, 3)], [(5, 7)])
        expected = [(1, 3), (5, 7)]
        assert result == expected
        iv.validate(result)

    def test_identical(self):
        result = iv.symmetric_difference([(1, 5), (7, 10)], [(1, 5), (7, 10)])
        assert result == []

    def test_overlapping(self):
        result = iv.symmetric_difference([(1, 5)], [(3, 8)])
        expected = [(1, 3), (5, 8)]
        assert result == expected
        iv.validate(result)

    def test_one_empty(self):
        assert iv.symmetric_difference([(1, 3)], []) == [(1, 3)]
        assert iv.symmetric_difference([], [(1, 3)]) == [(1, 3)]

    def test_both_empty(self):
        assert iv.symmetric_difference([], []) == []

    def test_adjacent(self):
        result = iv.symmetric_difference([(1, 3)], [(3, 5)])
        assert result == [(1, 5)]
        iv.validate(result)

    def test_property(self):
        rng = random.Random(5005)
        for trial in range(100):
            a = _random_iset(rng)
            b = _random_iset(rng)
            result = iv.symmetric_difference(a, b)
            expected = _ref_sym_diff(a, b)
            if result:
                iv.validate(result)
            assert result == expected, (
                f"Trial {trial}: symmetric_difference({a}, {b}) = {result}, "
                f"expected {expected}"
            )


class TestNormalize:
    def test_already_normalized(self):
        result = iv.normalize([(1, 3), (5, 8)])
        assert result == [(1, 3), (5, 8)]

    def test_unsorted(self):
        result = iv.normalize([(5, 8), (1, 3)])
        assert result == [(1, 3), (5, 8)]

    def test_overlapping(self):
        result = iv.normalize([(1, 5), (3, 8)])
        assert result == [(1, 8)]

    def test_adjacent(self):
        result = iv.normalize([(1, 3), (3, 5)])
        assert result == [(1, 5)]

    def test_empty_intervals_filtered(self):
        result = iv.normalize([(1, 3), (5, 5), (7, 9)])
        assert result == [(1, 3), (7, 9)]

    def test_inverted_intervals_filtered(self):
        result = iv.normalize([(1, 3), (8, 5), (7, 9)])
        assert result == [(1, 3), (7, 9)]

    def test_duplicates(self):
        result = iv.normalize([(1, 5), (1, 5)])
        assert result == [(1, 5)]

    def test_complex(self):
        raw = [(10, 15), (1, 3), (3, 7), (20, 20), (14, 18), (25, 30)]
        result = iv.normalize(raw)
        expected = [(1, 7), (10, 18), (25, 30)]
        assert result == expected
        iv.validate(result)

    def test_empty_input(self):
        assert iv.normalize([]) == []

    def test_all_empty(self):
        assert iv.normalize([(5, 5), (3, 3), (0, 0)]) == []

    def test_single_valid(self):
        assert iv.normalize([(3, 7)]) == [(3, 7)]

    def test_property(self):
        rng = random.Random(6006)
        for trial in range(80):
            n = rng.randint(0, 15)
            raw = []
            for _ in range(n):
                lo = rng.randint(-30, 30)
                hi = rng.randint(lo - 2, lo + 15)
                raw.append((lo, hi))
            result = iv.normalize(raw)
            # Reference: filter valid, expand to points, reconstruct
            points = []
            for lo, hi in raw:
                if lo < hi:
                    points.extend(range(lo, hi))
            expected = iv.from_points(points)
            if result:
                iv.validate(result)
            assert result == expected, (
                f"Trial {trial}: normalize({raw}) = {result}, "
                f"expected {expected}"
            )


class TestInvariantPreservation:
    """Every operation must produce outputs satisfying validate()."""

    def test_all_operations_preserve_invariants(self):
        rng = random.Random(7007)
        for _ in range(50):
            a = _random_iset(rng)
            b = _random_iset(rng)
            lo_range = rng.randint(-10, 10)
            hi_range = rng.randint(lo_range, lo_range + 40)

            for name, result in [
                ("union", iv.union(a, b)),
                ("intersection", iv.intersection(a, b)),
                ("difference(a,b)", iv.difference(a, b)),
                ("difference(b,a)", iv.difference(b, a)),
                ("complement", iv.complement(a, lo_range, hi_range)),
                ("symmetric_difference", iv.symmetric_difference(a, b)),
            ]:
                if result:
                    try:
                        iv.validate(result)
                    except ValueError as e:
                        pytest.fail(
                            f"{name}({a}, {b}) produced invalid output "
                            f"{result}: {e}"
                        )


# ===========================================================================
# Part 2: Z3 Verification Framework tests
# ===========================================================================

class TestVerifierStructure:
    """Test that verifier.py exists, uses Z3, and has required interface."""

    def test_verifier_importable(self):
        """verifier.py must exist at /app/ and be importable."""
        import importlib
        verifier = importlib.import_module('verifier')
        assert verifier is not None

    def test_verifier_uses_z3(self):
        """verifier.py must import and use the z3 package."""
        import importlib
        verifier = importlib.import_module('verifier')
        source = inspect.getsource(verifier)
        has_z3 = ('import z3' in source or 'from z3' in source
                  or 'z3.' in source)
        assert has_z3, "verifier.py does not reference z3"

    def test_has_check_law(self):
        """verifier must provide check_law function."""
        import importlib
        verifier = importlib.import_module('verifier')
        assert hasattr(verifier, 'check_law'), "verifier missing check_law"
        assert callable(verifier.check_law)

    def test_has_check_operation(self):
        """verifier must provide check_operation function."""
        import importlib
        verifier = importlib.import_module('verifier')
        assert hasattr(verifier, 'check_operation'), \
            "verifier missing check_operation"
        assert callable(verifier.check_operation)


class TestVerifierLaws:
    """Test that the Z3 verifier correctly verifies all algebraic laws."""

    def test_union_commutative(self):
        import importlib
        verifier = importlib.import_module('verifier')
        result = verifier.check_law("union_commutative", 8)
        assert result['verified'] is True, f"Failed: {result}"
        assert result['bound'] >= 8

    def test_intersection_commutative(self):
        import importlib
        verifier = importlib.import_module('verifier')
        result = verifier.check_law("intersection_commutative", 8)
        assert result['verified'] is True, f"Failed: {result}"

    def test_union_associative(self):
        import importlib
        verifier = importlib.import_module('verifier')
        result = verifier.check_law("union_associative", 8)
        assert result['verified'] is True, f"Failed: {result}"

    def test_intersection_associative(self):
        import importlib
        verifier = importlib.import_module('verifier')
        result = verifier.check_law("intersection_associative", 8)
        assert result['verified'] is True, f"Failed: {result}"

    def test_distributivity(self):
        import importlib
        verifier = importlib.import_module('verifier')
        result = verifier.check_law("distributivity", 8)
        assert result['verified'] is True, f"Failed: {result}"

    def test_absorption_union(self):
        import importlib
        verifier = importlib.import_module('verifier')
        result = verifier.check_law("absorption_union", 8)
        assert result['verified'] is True, f"Failed: {result}"

    def test_absorption_intersection(self):
        import importlib
        verifier = importlib.import_module('verifier')
        result = verifier.check_law("absorption_intersection", 8)
        assert result['verified'] is True, f"Failed: {result}"

    def test_difference_decomposition(self):
        import importlib
        verifier = importlib.import_module('verifier')
        result = verifier.check_law("difference_decomposition", 8)
        assert result['verified'] is True, f"Failed: {result}"

    def test_demorgan_union(self):
        import importlib
        verifier = importlib.import_module('verifier')
        result = verifier.check_law("demorgan_union", 8)
        assert result['verified'] is True, f"Failed: {result}"

    def test_demorgan_intersection(self):
        import importlib
        verifier = importlib.import_module('verifier')
        result = verifier.check_law("demorgan_intersection", 8)
        assert result['verified'] is True, f"Failed: {result}"

    def test_complement_involution(self):
        import importlib
        verifier = importlib.import_module('verifier')
        result = verifier.check_law("complement_involution", 8)
        assert result['verified'] is True, f"Failed: {result}"

    def test_intersection_complement_empty(self):
        import importlib
        verifier = importlib.import_module('verifier')
        result = verifier.check_law("intersection_complement_empty", 8)
        assert result['verified'] is True, f"Failed: {result}"


class TestVerifierBugDetection:
    """Test that the verifier can detect known-buggy implementations."""

    def test_detects_adjacency_bug_in_union(self):
        """check_operation must detect a union that fails to merge adjacent intervals."""
        import importlib
        verifier = importlib.import_module('verifier')

        def _buggy_merge(result, interval):
            lo, hi = interval
            if result and result[-1][1] > lo:  # BUG: > instead of >=
                result[-1] = (result[-1][0], max(result[-1][1], hi))
            else:
                result.append((lo, hi))

        def buggy_union(a, b):
            result = []
            i = j = 0
            while i < len(a) and j < len(b):
                if a[i][0] <= b[j][0]:
                    _buggy_merge(result, a[i]); i += 1
                else:
                    _buggy_merge(result, b[j]); j += 1
            while i < len(a):
                _buggy_merge(result, a[i]); i += 1
            while j < len(b):
                _buggy_merge(result, b[j]); j += 1
            return result

        def ref_union(a, b):
            return iv.from_points(iv.to_points(a) + iv.to_points(b))

        is_correct, cx = verifier.check_operation(
            buggy_union, ref_union, 2, 6
        )
        assert not is_correct, \
            "Verifier failed to detect adjacency bug in union"
        assert cx is not None

    def test_detects_empty_interval_bug_in_intersection(self):
        """check_operation must detect an intersection that produces empty intervals."""
        import importlib
        verifier = importlib.import_module('verifier')

        def buggy_intersection(a, b):
            result = []
            i = j = 0
            while i < len(a) and j < len(b):
                lo = max(a[i][0], b[j][0])
                hi = min(a[i][1], b[j][1])
                if lo <= hi:  # BUG: should be <
                    result.append((lo, hi))
                if a[i][1] <= b[j][1]:
                    i += 1
                else:
                    j += 1
            return result

        def ref_intersection(a, b):
            sa, sb = set(iv.to_points(a)), set(iv.to_points(b))
            return iv.from_points(sa & sb)

        is_correct, cx = verifier.check_operation(
            buggy_intersection, ref_intersection, 2, 6
        )
        assert not is_correct, \
            "Verifier failed to detect empty-interval bug in intersection"


# ===========================================================================
# Part 3: Verification report tests
# ===========================================================================

class TestVerificationReport:
    """Test that the verification report is complete and correct."""

    def test_report_exists_and_valid_json(self):
        """verification_report.json must exist and be valid JSON."""
        with open('/app/verification_report.json') as f:
            report = json.load(f)
        assert isinstance(report, dict)

    def test_report_covers_all_laws(self):
        """Report must contain results for every law in laws.json."""
        with open('/app/laws.json') as f:
            laws = json.load(f)
        with open('/app/verification_report.json') as f:
            report = json.load(f)
        for law in laws:
            assert law['name'] in report, \
                f"Law '{law['name']}' missing from verification report"

    def test_report_all_verified(self):
        """All laws must be verified as True with bound >= 8."""
        with open('/app/verification_report.json') as f:
            report = json.load(f)
        for name, result in report.items():
            assert 'verified' in result, \
                f"Missing 'verified' key for law '{name}'"
            assert result['verified'] is True, \
                f"Law '{name}' not verified: {result}"
            assert 'bound' in result, \
                f"Missing 'bound' key for law '{name}'"
            assert result['bound'] >= 8, \
                f"Bound too small for law '{name}': {result['bound']}"

    def test_report_has_no_extra_keys(self):
        """Report entries should have expected structure."""
        with open('/app/verification_report.json') as f:
            report = json.load(f)
        for name, result in report.items():
            assert isinstance(result, dict), \
                f"Result for '{name}' should be a dict"
            assert 'verified' in result
            assert 'bound' in result
