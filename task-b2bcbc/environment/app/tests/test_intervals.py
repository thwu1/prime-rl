"""Tests for interval arithmetic operations."""

from intervallib.intervals import (
    overlaps, merge, complement, coverage, intersection, symmetric_difference
)


class TestOverlaps:
    def test_clear_overlap(self):
        assert overlaps((0, 5), (3, 8)) is True

    def test_no_overlap(self):
        assert overlaps((0, 5), (10, 15)) is False

    def test_same_interval(self):
        assert overlaps((3, 7), (3, 7)) is True

    def test_contained(self):
        assert overlaps((0, 10), (3, 7)) is True


class TestMerge:
    def test_overlapping(self):
        assert merge([(0, 3), (2, 5), (7, 10)]) == [(0, 5), (7, 10)]

    def test_empty(self):
        assert merge([]) == []

    def test_single(self):
        assert merge([(1, 5)]) == [(1, 5)]

    def test_nested(self):
        assert merge([(0, 10), (3, 7)]) == [(0, 10)]


class TestComplement:
    def test_gaps(self):
        assert complement([(2, 5), (7, 9)], 0, 10) == [(0, 2), (5, 7), (9, 10)]

    def test_no_intervals(self):
        assert complement([], 0, 10) == [(0, 10)]


class TestCoverage:
    def test_half(self):
        assert coverage([(0, 5)], 0, 10) == 0.5

    def test_full(self):
        assert coverage([(0, 10)], 0, 10) == 1.0

    def test_none(self):
        assert coverage([], 0, 10) == 0.0

    def test_empty_domain(self):
        assert coverage([(0, 5)], 5, 5) == 0.0


class TestIntersection:
    def test_overlap(self):
        assert intersection((0, 5), (3, 8)) == (3, 5)

    def test_disjoint(self):
        assert intersection((0, 5), (7, 10)) is None


class TestSymmetricDifference:
    def test_partial_overlap(self):
        result = symmetric_difference([(0, 5)], [(3, 8)], 0, 10)
        assert result == [(0, 3), (5, 8)]
