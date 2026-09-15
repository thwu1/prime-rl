
"""Tests for multi-department shift scheduling solution verification."""

import json
import os
import pytest


@pytest.fixture(scope="module")
def instance():
    with open("/app/instance.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def solution():
    assert os.path.exists("/app/output.json"), \
        "Output file /app/output.json does not exist"
    with open("/app/output.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def schedule(solution):
    return {int(k): v for k, v in solution["schedule"].items()}


class TestOutputFormat:
    def test_output_has_required_keys(self, solution):
        assert "objective" in solution, "Missing 'objective' key"
        assert "schedule" in solution, "Missing 'schedule' key"
        assert "status" in solution, "Missing 'status' key"

    def test_status_valid(self, solution):
        assert solution["status"] in ("OPTIMAL", "FEASIBLE"), \
            f"Invalid status: {solution['status']}"

    def test_objective_is_integer(self, solution):
        assert isinstance(solution["objective"], int), \
            f"Objective must be int, got {type(solution['objective'])}"

    def test_schedule_completeness(self, instance, schedule):
        num_employees = instance["num_employees"]
        num_days = instance["num_weeks"] * 7
        for e in range(num_employees):
            assert e in schedule, f"Employee {e} missing from schedule"
            assert len(schedule[e]) == num_days, \
                f"Employee {e}: {len(schedule[e])} days, expected {num_days}"

    def test_valid_shift_values(self, instance, schedule):
        num_shifts = len(instance["shifts"])
        for e, shifts in schedule.items():
            for d, s in enumerate(shifts):
                assert isinstance(s, int), \
                    f"Employee {e} day {d}: shift must be int, got {type(s)}"
                assert 0 <= s < num_shifts, \
                    f"Employee {e} day {d}: invalid shift {s}"


class TestHardConstraints:
    def test_skill_constraints(self, instance, schedule):
        skills = {int(k): v for k, v in instance["skills"].items()}
        for e, shifts in schedule.items():
            for d, s in enumerate(shifts):
                assert s in skills[e], \
                    f"Employee {e} day {d}: shift {s} not in skills {skills[e]}"

    def test_fixed_assignments(self, instance, schedule):
        for e, s, d in instance["fixed_assignments"]:
            assert schedule[e][d] == s, \
                f"Fixed assignment violated: emp {e} day {d} expected {s}, got {schedule[e][d]}"

    def test_forbidden_transitions(self, instance, schedule):
        num_days = instance["num_weeks"] * 7
        forbidden = [(p, n) for p, n, c in instance["penalized_transitions"]
                     if c == 0]
        for e, shifts in schedule.items():
            for d in range(num_days - 1):
                pair = (shifts[d], shifts[d + 1])
                assert pair not in forbidden, \
                    f"Forbidden transition {pair} for emp {e} day {d}->{d+1}"

    def test_off_sequence_hard_bounds(self, instance, schedule):
        off_ct = None
        for ct in instance["shift_constraints"]:
            if ct[0] == 0:
                off_ct = ct
                break
        if off_ct is None:
            return
        shift_id, hard_min, _, _, _, hard_max, _ = off_ct
        num_days = instance["num_weeks"] * 7
        for e, shifts in schedule.items():
            seq_len = 0
            for d in range(num_days):
                if shifts[d] == shift_id:
                    seq_len += 1
                else:
                    if seq_len > 0:
                        assert hard_min <= seq_len <= hard_max, \
                            f"Emp {e}: off seq len {seq_len} at day {d - seq_len}, " \
                            f"bounds [{hard_min}, {hard_max}]"
                    seq_len = 0
            if seq_len > 0:
                assert hard_min <= seq_len <= hard_max, \
                    f"Emp {e}: trailing off seq len {seq_len}, " \
                    f"bounds [{hard_min}, {hard_max}]"

    def test_night_sequence_hard_bounds(self, instance, schedule):
        night_ct = None
        for ct in instance["shift_constraints"]:
            if ct[0] == 3:
                night_ct = ct
                break
        if night_ct is None:
            return
        shift_id, hard_min, _, _, _, hard_max, _ = night_ct
        num_days = instance["num_weeks"] * 7
        for e, shifts in schedule.items():
            seq_len = 0
            for d in range(num_days):
                if shifts[d] == shift_id:
                    seq_len += 1
                else:
                    if seq_len > 0:
                        assert hard_min <= seq_len <= hard_max, \
                            f"Emp {e}: night seq len {seq_len} at day {d - seq_len}, " \
                            f"bounds [{hard_min}, {hard_max}]"
                    seq_len = 0
            if seq_len > 0:
                assert hard_min <= seq_len <= hard_max, \
                    f"Emp {e}: trailing night seq len {seq_len}, " \
                    f"bounds [{hard_min}, {hard_max}]"

    def test_weekly_sum_hard_bounds(self, instance, schedule):
        num_weeks = instance["num_weeks"]
        for ct in instance["weekly_sum_constraints"]:
            shift_id, hard_min, _, _, _, hard_max, _ = ct
            for e, shifts in schedule.items():
                for w in range(num_weeks):
                    week_shifts = shifts[w * 7:(w + 1) * 7]
                    count = sum(1 for s in week_shifts if s == shift_id)
                    assert hard_min <= count <= hard_max, \
                        f"Emp {e} week {w}: {count} of shift {shift_id}, " \
                        f"bounds [{hard_min}, {hard_max}]"

    def test_incompatible_night_pairs(self, instance, schedule):
        num_days = instance["num_weeks"] * 7
        night = 3
        for e1, e2 in instance["incompatible_night_pairs"]:
            for d in range(num_days):
                both_night = (schedule[e1][d] == night and
                              schedule[e2][d] == night)
                assert not both_night, \
                    f"Incompatible pair ({e1},{e2}) both night on day {d}"

    def test_weekend_completeness(self, instance, schedule):
        if not instance.get("weekend_completeness", False):
            return
        num_weeks = instance["num_weeks"]
        off = 0
        for e, shifts in schedule.items():
            for w in range(num_weeks):
                sat = w * 7 + 5
                sun = w * 7 + 6
                sat_off = (shifts[sat] == off)
                sun_off = (shifts[sun] == off)
                assert sat_off == sun_off, \
                    f"Emp {e} week {w}: weekend completeness violated " \
                    f"(Sat off={sat_off}, Sun off={sun_off})"

    def test_coverage_minimums(self, instance, schedule):
        num_weeks = instance["num_weeks"]
        num_shifts = len(instance["shifts"])
        for dept_name, employees in instance["departments"].items():
            dept_demands = instance["weekly_cover_demands"][dept_name]
            for w in range(num_weeks):
                for dow in range(7):
                    day = w * 7 + dow
                    for s in range(1, num_shifts):
                        count = sum(1 for e in employees
                                    if schedule[e][day] == s)
                        min_demand = dept_demands[str(dow)][s - 1]
                        assert count >= min_demand, \
                            f"Dept {dept_name} day {day} shift {s}: " \
                            f"{count} workers < demand {min_demand}"


class TestObjectiveComputation:
    def _compute_objective(self, instance, schedule):
        """Independently compute the objective value from the schedule."""
        num_employees = instance["num_employees"]
        num_weeks = instance["num_weeks"]
        num_shifts = len(instance["shifts"])
        num_days = num_weeks * 7
        total = 0

        # 1. Sequence penalties
        for ct in instance["shift_constraints"]:
            shift_id, hard_min, soft_min, min_cost, soft_max, hard_max, max_cost = ct
            for e in range(num_employees):
                shifts = schedule[e]
                seq_len = 0
                for d in range(num_days):
                    if shifts[d] == shift_id:
                        seq_len += 1
                    else:
                        if seq_len > 0:
                            if seq_len < soft_min and min_cost > 0:
                                total += min_cost * (soft_min - seq_len)
                            if seq_len > soft_max and max_cost > 0:
                                total += max_cost * (seq_len - soft_max)
                        seq_len = 0
                if seq_len > 0:
                    if seq_len < soft_min and min_cost > 0:
                        total += min_cost * (soft_min - seq_len)
                    if seq_len > soft_max and max_cost > 0:
                        total += max_cost * (seq_len - soft_max)

        # 2. Weekly sum penalties
        for ct in instance["weekly_sum_constraints"]:
            shift_id, hard_min, soft_min, min_cost, soft_max, hard_max, max_cost = ct
            for e in range(num_employees):
                shifts_list = schedule[e]
                for w in range(num_weeks):
                    week = shifts_list[w * 7:(w + 1) * 7]
                    count = sum(1 for s in week if s == shift_id)
                    if count < soft_min and min_cost > 0:
                        total += min_cost * (soft_min - count)
                    if count > soft_max and max_cost > 0:
                        total += max_cost * (count - soft_max)

        # 3. Transition penalties
        for prev_shift, next_shift, cost in instance["penalized_transitions"]:
            if cost > 0:
                for e in range(num_employees):
                    shifts_list = schedule[e]
                    for d in range(num_days - 1):
                        if (shifts_list[d] == prev_shift and
                                shifts_list[d + 1] == next_shift):
                            total += cost

        # 4. Coverage excess penalties
        for dept_name, employees in instance["departments"].items():
            dept_demands = instance["weekly_cover_demands"][dept_name]
            for w in range(num_weeks):
                for dow in range(7):
                    day = w * 7 + dow
                    for s in range(1, num_shifts):
                        count = sum(1 for e in employees
                                    if schedule[e][day] == s)
                        min_demand = dept_demands[str(dow)][s - 1]
                        excess = max(0, count - min_demand)
                        penalty = instance["excess_cover_penalties"][s - 1]
                        total += excess * penalty

        # 5. Request penalties
        for e, s, d, w in instance["requests"]:
            if schedule[e][d] == s:
                total += w

        return total

    def test_objective_matches_computed(self, instance, solution, schedule):
        computed = self._compute_objective(instance, schedule)
        claimed = solution["objective"]
        assert computed == claimed, \
            f"Claimed objective {claimed} != computed {computed}"

    def test_objective_quality_bound(self, instance, solution, schedule):
        assert solution["objective"] <= 200, \
            f"Objective {solution['objective']} exceeds quality bound 200"
