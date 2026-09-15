"""Targeted tests that kill all 13 non-equivalent mutations from mutations.json."""

from intervallib.intervals import overlaps, merge, complement, coverage
from intervallib.scheduling import weighted_schedule, edf_schedule
from intervallib.solver import (
    propagate_precedence, resource_load_profile,
    find_overloaded_windows, schedule_with_constraints,
)


class TestOverlapsBoundary:
    """Kill M01 and M02: comparison boundary swaps in overlaps()."""

    def test_touching_left_not_overlapping(self):
        # M01: a[0] <= b[1] would incorrectly return True for touching intervals
        # [5,10) and [0,5) share no points under half-open semantics
        assert overlaps((5, 10), (0, 5)) is False

    def test_touching_right_not_overlapping(self):
        # M02: b[0] <= a[1] would incorrectly return True for touching intervals
        # [0,5) and [5,10) share no points under half-open semantics
        assert overlaps((0, 5), (5, 10)) is False

    def test_genuine_overlap_sanity(self):
        assert overlaps((0, 6), (5, 10)) is True


class TestMergeAdjacent:
    """Kill M03: <= to < in merge condition breaks adjacent-interval merging."""

    def test_adjacent_intervals_merge(self):
        # [0,5) and [5,10) must merge to [0,10) under half-open convention
        assert merge([(0, 5), (5, 10)]) == [(0, 10)]

    def test_chain_of_adjacent(self):
        assert merge([(0, 3), (3, 6), (6, 9)]) == [(0, 9)]


class TestComplementBoundary:
    """Kill M04 and M05: boundary swaps in complement()."""

    def test_interval_at_domain_start(self):
        # M04: >= would add a zero-width gap (0,0) at start
        assert complement([(0, 5)], 0, 10) == [(5, 10)]

    def test_interval_at_domain_end(self):
        # M05: <= would add a zero-width gap (10,10) at end
        assert complement([(5, 10)], 0, 10) == [(0, 5)]

    def test_full_coverage_no_gaps(self):
        assert complement([(0, 10)], 0, 10) == []


class TestCoverageArithmetic:
    """Kill M06 and M07: arithmetic operator swaps in coverage()."""

    def test_offset_interval(self):
        # M06: ce + cs instead of ce - cs gives wrong result when cs != 0
        # coverage([(3,7)], 0, 10): cs=3, ce=7. Correct: (7-3)/10=0.4. Mutant: (7+3)/10=1.0
        assert abs(coverage([(3, 7)], 0, 10) - 0.4) < 1e-9

    def test_nonzero_domain_start(self):
        # M07: hi + lo instead of hi - lo gives wrong denominator when lo != 0
        # coverage([(2,4)], 1, 5): total=2. Correct: 2/(5-1)=0.5. Mutant: 2/(5+1)=0.333
        assert abs(coverage([(2, 4)], 1, 5) - 0.5) < 1e-9

    def test_interval_past_domain(self):
        assert abs(coverage([(-5, 3)], 0, 10) - 0.3) < 1e-9


class TestWeightedScheduleBoundary:
    """Kill M08: <= to < in binary search breaks abutting-job detection."""

    def test_abutting_jobs_both_selected(self):
        # Jobs [0,5) and [5,10) abut — both should be schedulable
        weight, selected = weighted_schedule([(0, 5, 3), (5, 10, 4)])
        assert weight == 7
        assert set(selected) == {0, 1}


class TestEdfAccumulation:
    """Kill M09: += to = in EDF loses accumulated completion time."""

    def test_accumulated_lateness(self):
        # Two tasks: a(proc=5, deadline=6), b(proc=5, deadline=7)
        # Correct: a finishes at 5, b finishes at 10. Lateness: max(-1, 3) = 3
        # Mutant: a finishes at 5, b finishes at 5. Lateness: max(-1, -2) = -1
        tasks = [("a", 5, 6), ("b", 5, 7)]
        order, lateness = edf_schedule(tasks)
        assert order == ["a", "b"]
        assert lateness == 3


class TestPropagationFeasibility:
    """Kill M12: >= to > in feasibility check misses empty point-domains."""

    def test_point_domain_infeasible(self):
        # Domain [5,5) is empty in half-open semantics — should be infeasible
        # Original: dp[0]=5 >= dp[1]=5 -> True -> return None
        # Mutant:   dp[0]=5 >  dp[1]=5 -> False -> continues (wrong)
        result = propagate_precedence(
            {"A": (5, 5), "B": (0, 10)},
            [("A", "B")]
        )
        assert result is None, "Domain [5, 5) is empty and should be infeasible"


class TestLoadProfileBoundary:
    """Kill M13: < to <= in loop bound produces extra zero-width slot."""

    def test_exact_slot_count(self):
        # [0,10) with resolution 5 should produce exactly 2 slots: [0,5) and [5,10)
        # Mutant adds a third zero-width slot [10,10)
        profile = resource_load_profile([(0, 10)], 0, 10, 5)
        assert len(profile) == 2


class TestOverloadThreshold:
    """Kill M14: > to >= in overload check incorrectly flags at-capacity loads."""

    def test_at_capacity_not_overloaded(self):
        # Two overlapping allocations, capacity=2. Load meets but doesn't exceed capacity.
        # Original: 2 > 2 -> False -> not overloaded
        # Mutant:   2 >= 2 -> True -> incorrectly flagged
        result = find_overloaded_windows([(0, 5), (0, 5)], 0, 10, 2, 5)
        assert result == [], "Load == capacity is not overloaded"


class TestResourceCapacity:
    """Kill M15: >= to > in capacity check allows over-subscription."""

    def test_sequential_with_capacity_one(self):
        # With capacity=1, tasks must run sequentially (no overlap)
        # Mutant allows scheduling 2 tasks concurrently
        tasks = [("A", 5), ("B", 5), ("C", 5)]
        result = schedule_with_constraints(tasks, [], resource_capacity=1)
        assert result is not None
        intervals = sorted(result.values())
        for i in range(len(intervals) - 1):
            assert intervals[i][1] <= intervals[i + 1][0], (
                f"Tasks overlap with capacity 1: {intervals[i]} and {intervals[i+1]}"
            )
