
import json
import os
import pytest


@pytest.fixture(scope="module")
def problem():
    with open("/app/problem.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def solution():
    with open("/app/schedule.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def schedule(solution):
    return solution["schedule"]


@pytest.fixture(scope="module")
def shifts(problem):
    return problem["metadata"]["shift_types"]


class TestSolutionFormat:
    def test_solution_file_exists(self):
        assert os.path.exists("/app/schedule.json"), "schedule.json not found"

    def test_solution_has_schedule_key(self, solution):
        assert "schedule" in solution, "Missing 'schedule' key"

    def test_solution_has_objective_key(self, solution):
        assert "objective" in solution, "Missing 'objective' key"

    def test_schedule_dimensions(self, schedule, problem):
        num_emp = problem["metadata"]["num_employees"]
        num_days = problem["metadata"]["num_days"]
        assert len(schedule) == num_emp, f"Expected {num_emp} employees, got {len(schedule)}"
        for e, row in enumerate(schedule):
            assert len(row) == num_days, f"Employee {e}: expected {num_days} days, got {len(row)}"

    def test_valid_shift_types(self, schedule, shifts):
        for e, row in enumerate(schedule):
            for d, s in enumerate(row):
                assert s in shifts, f"Employee {e}, day {d}: invalid shift '{s}'"


class TestHardConstraints:
    def test_one_shift_per_day(self, schedule, problem):
        """Each employee has exactly one shift per day (guaranteed by format)."""
        num_emp = problem["metadata"]["num_employees"]
        num_days = problem["metadata"]["num_days"]
        for e in range(num_emp):
            assert len(schedule[e]) == num_days

    def test_fixed_assignments(self, schedule, problem, shifts):
        """Pre-scheduled assignments must be respected."""
        for emp, shift_idx, day in problem["fixed_assignments"]:
            expected = shifts[shift_idx]
            actual = schedule[emp][day]
            assert actual == expected, (
                f"Fixed assignment violated: employee {emp}, day {day} "
                f"expected '{expected}', got '{actual}'"
            )

    def test_minimum_cover_demands(self, schedule, problem, shifts):
        """Minimum staffing levels must be met for each shift on each day."""
        num_days = problem["metadata"]["num_days"]
        demands = problem["weekly_cover_demands"]
        for d in range(num_days):
            dow = d % 7
            demand = demands[dow]
            for shift_name in ["D", "E", "N"]:
                count = sum(1 for e_sched in schedule if e_sched[d] == shift_name)
                required = demand[shift_name]
                assert count >= required, (
                    f"Day {d} ({demand.get('label', dow)}): shift '{shift_name}' "
                    f"has {count} workers, need >= {required}"
                )

    def test_senior_coverage(self, schedule, problem):
        """Shifts requiring senior coverage must have enough senior employees."""
        num_days = problem["metadata"]["num_days"]
        senior_reqs = problem["senior_requirements"]
        senior_ids = {e["id"] for e in problem["employees"] if e["senior"]}
        for d in range(num_days):
            for shift_name, min_senior in senior_reqs.items():
                senior_count = sum(
                    1 for e_id in senior_ids if schedule[e_id][d] == shift_name
                )
                assert senior_count >= min_senior, (
                    f"Day {d}: shift '{shift_name}' has {senior_count} seniors, "
                    f"need >= {min_senior}"
                )

    def test_forbidden_transitions(self, schedule, problem, shifts):
        """Forbidden shift transitions must not occur on consecutive days."""
        num_emp = problem["metadata"]["num_employees"]
        num_days = problem["metadata"]["num_days"]
        for prev_idx, next_idx in problem["forbidden_transitions"]:
            prev_shift = shifts[prev_idx]
            next_shift = shifts[next_idx]
            for e in range(num_emp):
                for d in range(num_days - 1):
                    assert not (
                        schedule[e][d] == prev_shift and schedule[e][d + 1] == next_shift
                    ), (
                        f"Forbidden transition: employee {e}, day {d}: "
                        f"'{prev_shift}' -> '{next_shift}'"
                    )

    def test_max_consecutive_off(self, schedule, problem):
        """Hard max consecutive off days must be respected."""
        num_emp = problem["metadata"]["num_employees"]
        num_days = problem["metadata"]["num_days"]
        for sc in problem["shift_sequence_constraints"]:
            if sc["shift"] != 0:
                continue
            hard_max = sc["hard_max"]
            for e in range(num_emp):
                consec = 0
                for d in range(num_days):
                    if schedule[e][d] == "O":
                        consec += 1
                        assert consec <= hard_max, (
                            f"Employee {e}: {consec} consecutive off days ending day {d}, "
                            f"hard max is {hard_max}"
                        )
                    else:
                        consec = 0

    def test_max_consecutive_night(self, schedule, problem):
        """Hard max consecutive night shifts must be respected."""
        num_emp = problem["metadata"]["num_employees"]
        num_days = problem["metadata"]["num_days"]
        for sc in problem["shift_sequence_constraints"]:
            if sc["shift"] != 3:
                continue
            hard_max = sc["hard_max"]
            for e in range(num_emp):
                consec = 0
                for d in range(num_days):
                    if schedule[e][d] == "N":
                        consec += 1
                        assert consec <= hard_max, (
                            f"Employee {e}: {consec} consecutive night shifts ending day {d}, "
                            f"hard max is {hard_max}"
                        )
                    else:
                        consec = 0

    def test_min_consecutive_off(self, schedule, problem):
        """Hard min consecutive off days: if off, must be off for at least hard_min days."""
        num_emp = problem["metadata"]["num_employees"]
        num_days = problem["metadata"]["num_days"]
        for sc in problem["shift_sequence_constraints"]:
            if sc["shift"] != 0:
                continue
            hard_min = sc["hard_min"]
            for e in range(num_emp):
                spans = _get_consecutive_spans(schedule[e], "O", num_days)
                for start, length in spans:
                    assert length >= hard_min, (
                        f"Employee {e}: off span of length {length} starting day {start}, "
                        f"hard min is {hard_min}"
                    )

    def test_min_consecutive_night(self, schedule, problem):
        """Hard min consecutive night shifts."""
        num_emp = problem["metadata"]["num_employees"]
        num_days = problem["metadata"]["num_days"]
        for sc in problem["shift_sequence_constraints"]:
            if sc["shift"] != 3:
                continue
            hard_min = sc["hard_min"]
            for e in range(num_emp):
                spans = _get_consecutive_spans(schedule[e], "N", num_days)
                for start, length in spans:
                    assert length >= hard_min, (
                        f"Employee {e}: night span of length {length} starting day {start}, "
                        f"hard min is {hard_min}"
                    )

    def test_weekly_off_bounds(self, schedule, problem):
        """Hard min/max off days per week per employee."""
        num_emp = problem["metadata"]["num_employees"]
        num_weeks = problem["metadata"]["num_weeks"]
        for wsc in problem["weekly_sum_constraints"]:
            if wsc["shift"] != 0:
                continue
            hard_min = wsc["hard_min"]
            hard_max = wsc["hard_max"]
            for e in range(num_emp):
                for w in range(num_weeks):
                    count = sum(
                        1 for d in range(7) if schedule[e][w * 7 + d] == "O"
                    )
                    assert hard_min <= count <= hard_max, (
                        f"Employee {e}, week {w}: {count} off days, "
                        f"must be in [{hard_min}, {hard_max}]"
                    )

    def test_weekly_night_bounds(self, schedule, problem):
        """Hard min/max night shifts per week per employee."""
        num_emp = problem["metadata"]["num_employees"]
        num_weeks = problem["metadata"]["num_weeks"]
        for wsc in problem["weekly_sum_constraints"]:
            if wsc["shift"] != 3:
                continue
            hard_min = wsc["hard_min"]
            hard_max = wsc["hard_max"]
            for e in range(num_emp):
                for w in range(num_weeks):
                    count = sum(
                        1 for d in range(7) if schedule[e][w * 7 + d] == "N"
                    )
                    assert hard_min <= count <= hard_max, (
                        f"Employee {e}, week {w}: {count} night shifts, "
                        f"must be in [{hard_min}, {hard_max}]"
                    )

    def test_incompatible_pairs(self, schedule, problem, shifts):
        """Incompatible employee pairs must not share the specified shift on any day."""
        num_days = problem["metadata"]["num_days"]
        for pair_info in problem["incompatible_pairs"]:
            e1, e2 = pair_info["employees"]
            shift_name = shifts[pair_info["shift"]]
            for d in range(num_days):
                assert not (
                    schedule[e1][d] == shift_name and schedule[e2][d] == shift_name
                ), (
                    f"Incompatible pair ({e1}, {e2}) both on shift '{shift_name}' "
                    f"on day {d}"
                )


class TestPenaltyThreshold:
    def test_penalty_below_threshold(self, schedule, problem, shifts):
        """Total penalty from soft constraints must be below threshold."""
        penalty = _compute_total_penalty(schedule, problem, shifts)
        threshold = 500
        assert penalty <= threshold, (
            f"Total penalty {penalty} exceeds threshold {threshold}"
        )

    def test_objective_matches_computed(self, solution, problem, shifts):
        """The reported objective should approximately match the computed penalty."""
        schedule = solution["schedule"]
        reported = solution["objective"]
        computed = _compute_total_penalty(schedule, problem, shifts)
        assert abs(reported - computed) <= 5, (
            f"Reported objective {reported} differs from computed penalty {computed} "
            f"by more than 5"
        )


def _get_consecutive_spans(employee_schedule, shift_name, num_days):
    """Return list of (start, length) for consecutive runs of shift_name."""
    spans = []
    start = None
    for d in range(num_days):
        if employee_schedule[d] == shift_name:
            if start is None:
                start = d
        else:
            if start is not None:
                spans.append((start, d - start))
                start = None
    if start is not None:
        spans.append((start, num_days - start))
    return spans


def _compute_total_penalty(schedule, problem, shifts):
    """Independently compute total penalty from the schedule."""
    num_emp = problem["metadata"]["num_employees"]
    num_days = problem["metadata"]["num_days"]
    num_weeks = problem["metadata"]["num_weeks"]
    penalty = 0

    # 1. Employee requests
    for emp, shift_idx, day, weight in problem["requests"]:
        shift_name = shifts[shift_idx]
        if schedule[emp][day] == shift_name:
            penalty += weight

    # 2. Shift sequence soft constraints
    for sc in problem["shift_sequence_constraints"]:
        shift_idx = sc["shift"]
        shift_name = shifts[shift_idx]
        soft_min = sc["soft_min"]
        min_pen = sc["min_penalty"]
        soft_max = sc["soft_max"]
        max_pen = sc["max_penalty"]
        for e in range(num_emp):
            spans = _get_consecutive_spans(schedule[e], shift_name, num_days)
            for _, length in spans:
                if length < soft_min and min_pen > 0:
                    penalty += min_pen * (soft_min - length)
                if length > soft_max and max_pen > 0:
                    penalty += max_pen * (length - soft_max)

    # 3. Weekly sum soft constraints
    for wsc in problem["weekly_sum_constraints"]:
        shift_idx = wsc["shift"]
        shift_name = shifts[shift_idx]
        soft_min = wsc["soft_min"]
        min_pen = wsc["min_penalty"]
        soft_max = wsc["soft_max"]
        max_pen = wsc["max_penalty"]
        for e in range(num_emp):
            for w in range(num_weeks):
                count = sum(
                    1 for d in range(7) if schedule[e][w * 7 + d] == shift_name
                )
                if count < soft_min and min_pen > 0:
                    penalty += min_pen * (soft_min - count)
                if count > soft_max and max_pen > 0:
                    penalty += max_pen * (count - soft_max)

    # 4. Penalized transitions
    for prev_idx, next_idx, cost in problem["penalized_transitions"]:
        prev_shift = shifts[prev_idx]
        next_shift = shifts[next_idx]
        for e in range(num_emp):
            for d in range(num_days - 1):
                if schedule[e][d] == prev_shift and schedule[e][d + 1] == next_shift:
                    penalty += cost

    # 5. Excess cover penalties
    demands = problem["weekly_cover_demands"]
    excess_penalties = problem["excess_cover_penalties"]
    for d in range(num_days):
        dow = d % 7
        demand = demands[dow]
        for shift_name in ["D", "E", "N"]:
            count = sum(1 for e_sched in schedule if e_sched[d] == shift_name)
            excess = max(0, count - demand[shift_name])
            penalty += excess * excess_penalties[shift_name]

    # 6. Weekend pairing penalty
    weekend_pen = problem["weekend_pair_penalty"]
    for e in range(num_emp):
        for w in range(num_weeks):
            sat = w * 7 + 5
            sun = w * 7 + 6
            sat_off = schedule[e][sat] == "O"
            sun_off = schedule[e][sun] == "O"
            if sat_off != sun_off:
                penalty += weekend_pen

    # 7. Night fairness penalty (range-based: max - min night counts)
    fairness_pen = problem["night_fairness_penalty"]
    night_counts = []
    for e in range(num_emp):
        nc = sum(1 for d in range(num_days) if schedule[e][d] == "N")
        night_counts.append(nc)
    if night_counts:
        night_range = max(night_counts) - min(night_counts)
        penalty += fairness_pen * night_range

    return penalty
