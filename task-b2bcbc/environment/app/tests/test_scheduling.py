"""Tests for scheduling algorithms."""

from intervallib.scheduling import weighted_schedule, edf_schedule, critical_path_length


class TestWeightedSchedule:
    def test_basic(self):
        jobs = [(0, 3, 5), (2, 5, 6), (4, 7, 5), (6, 9, 4)]
        weight, selected = weighted_schedule(jobs)
        assert weight == 10

    def test_empty(self):
        assert weighted_schedule([]) == (0, [])

    def test_single(self):
        weight, sel = weighted_schedule([(0, 5, 10)])
        assert weight == 10
        assert sel == [0]


class TestEdfSchedule:
    def test_ordering(self):
        tasks = [("a", 3, 10), ("b", 2, 8), ("c", 1, 5)]
        order, lateness = edf_schedule(tasks)
        assert order == ["c", "b", "a"]

    def test_single(self):
        order, lateness = edf_schedule([("x", 5, 10)])
        assert order == ["x"]
        assert lateness == -5


class TestCriticalPath:
    def test_diamond(self):
        durations = [3, 2, 4, 1]
        deps = [(0, 1), (0, 2), (1, 3), (2, 3)]
        assert critical_path_length(4, durations, deps) == 8

    def test_no_deps(self):
        assert critical_path_length(3, [3, 5, 2], []) == 5
