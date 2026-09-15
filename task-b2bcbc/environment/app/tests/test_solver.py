"""Tests for constraint propagation and resource analysis."""

from intervallib.solver import (
    propagate_precedence, resource_load_profile,
    find_overloaded_windows, schedule_with_constraints, compute_makespan
)


class TestPropagatePrecedence:
    def test_simple_chain(self):
        domains = {"A": (0, 10), "B": (0, 10), "C": (0, 10)}
        result = propagate_precedence(domains, [("A", "B"), ("B", "C")])
        assert result is not None

    def test_infeasible_reverse(self):
        domains = {"A": (0, 3), "B": (8, 10)}
        result = propagate_precedence(domains, [("B", "A")])
        assert result is None


class TestResourceLoadProfile:
    def test_single_allocation(self):
        profile = resource_load_profile([(2, 8)], 0, 10, 5)
        assert profile[0][2] == 1
        assert profile[1][2] == 1

    def test_empty(self):
        profile = resource_load_profile([], 0, 10, 5)
        assert all(slot[2] == 0 for slot in profile)


class TestFindOverloadedWindows:
    def test_no_overload(self):
        result = find_overloaded_windows([(0, 5)], 0, 10, 5, 1)
        assert result == []


class TestScheduleWithConstraints:
    def test_no_constraints(self):
        tasks = [("A", 3), ("B", 2), ("C", 4)]
        result = schedule_with_constraints(tasks, [], 3)
        assert result is not None
        assert len(result) == 3

    def test_simple_chain(self):
        tasks = [("A", 3), ("B", 2)]
        result = schedule_with_constraints(tasks, [("A", "B")], 2)
        assert result is not None
        assert result["B"][0] >= result["A"][1]


class TestComputeMakespan:
    def test_basic(self):
        assert compute_makespan({"A": (0, 5), "B": (5, 10)}) == 10

    def test_empty(self):
        assert compute_makespan({}) == 0
