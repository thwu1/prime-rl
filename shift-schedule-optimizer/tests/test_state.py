"""Tests for the shift scheduling optimization solution.

"""
import json
import os
import pytest

PENALTY_THRESHOLD = 600


@pytest.fixture(scope='module')
def instance():
    with open('/app/instance.json') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def solution():
    path = '/app/schedule.json'
    assert os.path.exists(path), f'{path} not found'
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def schedule(solution):
    assert 'schedule' in solution, 'schedule key missing from solution'
    return solution['schedule']


def find_sequences(row, shift_val):
    """Find all maximal contiguous sequences of shift_val in row."""
    seqs = []
    length = 0
    for v in row:
        if v == shift_val:
            length += 1
        else:
            if length > 0:
                seqs.append(length)
            length = 0
    if length > 0:
        seqs.append(length)
    return seqs


class TestSolutionFormat:
    def test_schedule_exists(self, solution):
        assert 'schedule' in solution
        assert 'penalty' in solution

    def test_schedule_dimensions(self, schedule, instance):
        num_emp = instance['num_employees']
        num_days = instance['num_weeks'] * 7
        assert len(schedule) == num_emp, \
            f'Expected {num_emp} employee rows, got {len(schedule)}'
        for e, row in enumerate(schedule):
            assert len(row) == num_days, \
                f'Employee {e}: expected {num_days} days, got {len(row)}'

    def test_valid_shift_values(self, schedule):
        for e, row in enumerate(schedule):
            for d, s in enumerate(row):
                assert s in (0, 1, 2, 3), \
                    f'Employee {e} day {d}: invalid shift {s}'


class TestHardConstraints:
    def test_fixed_assignments(self, schedule, instance):
        for e, s, d in instance['fixed_assignments']:
            actual = schedule[e][d]
            assert actual == s, \
                f'Fixed assignment violated: emp {e} day {d} ' \
                f'expected shift {s}, got {actual}'

    def test_unavailability(self, schedule, instance):
        for emp in instance['employees']:
            eid = emp['id']
            for d in emp['unavailable_days']:
                assert schedule[eid][d] == 0, \
                    f'Unavailability violated: emp {eid} day {d} ' \
                    f'should be Off(0), got {schedule[eid][d]}'

    def test_forbidden_transitions(self, schedule, instance):
        num_days = instance['num_weeks'] * 7
        for prev_s, next_s in instance['forbidden_transitions']:
            for e in range(instance['num_employees']):
                for d in range(num_days - 1):
                    if schedule[e][d] == prev_s and \
                       schedule[e][d + 1] == next_s:
                        pytest.fail(
                            f'Forbidden transition: emp {e} day {d} '
                            f'shift {prev_s}->{next_s}')

    def test_max_consecutive_working_days(self, schedule, instance):
        max_consec = instance['max_consecutive_working_days']
        num_days = instance['num_weeks'] * 7
        for e in range(instance['num_employees']):
            consec = 0
            for d in range(num_days):
                if schedule[e][d] != 0:  # working
                    consec += 1
                    if consec > max_consec:
                        pytest.fail(
                            f'Max consecutive work days exceeded: '
                            f'emp {e} at day {d}, streak={consec}')
                else:
                    consec = 0

    def test_night_recovery(self, schedule, instance):
        nr = instance['night_recovery']
        min_nights = nr['min_consecutive_nights']
        recovery = nr['required_recovery_days']
        num_days = instance['num_weeks'] * 7
        NIGHT = 3
        OFF = 0
        for e in range(instance['num_employees']):
            for d in range(min_nights - 1, num_days):
                # Check if days d-min_nights+1..d are all nights
                all_nights = all(
                    schedule[e][d - k] == NIGHT
                    for k in range(min_nights))
                if not all_nights:
                    continue
                # Check if night sequence ends here
                if d + 1 < num_days and schedule[e][d + 1] == NIGHT:
                    continue
                # Recovery required
                for r in range(1, recovery + 1):
                    if d + r >= num_days:
                        break
                    if schedule[e][d + r] != OFF:
                        pytest.fail(
                            f'Night recovery violated: emp {e}, '
                            f'night seq ends day {d}, '
                            f'day {d + r} should be Off, '
                            f'got {schedule[e][d + r]}')

    def test_shift_sequence_hard_bounds(self, schedule, instance):
        for sc in instance['shift_sequence_constraints']:
            shift = sc['shift']
            hard_min = sc['hard_min']
            hard_max = sc['hard_max']
            for e in range(instance['num_employees']):
                seqs = find_sequences(schedule[e], shift)
                for seq_len in seqs:
                    if seq_len < hard_min:
                        pytest.fail(
                            f'Sequence too short: emp {e} shift {shift} '
                            f'length {seq_len} < hard_min {hard_min}')
                    if seq_len > hard_max:
                        pytest.fail(
                            f'Sequence too long: emp {e} shift {shift} '
                            f'length {seq_len} > hard_max {hard_max}')

    def test_weekly_sum_hard_bounds(self, schedule, instance):
        num_weeks = instance['num_weeks']
        for wsc in instance['weekly_sum_constraints']:
            shift = wsc['shift']
            hard_min = wsc['hard_min']
            hard_max = wsc['hard_max']
            for e in range(instance['num_employees']):
                for w in range(num_weeks):
                    count = sum(
                        1 for d in range(w * 7, (w + 1) * 7)
                        if schedule[e][d] == shift)
                    if count < hard_min or count > hard_max:
                        pytest.fail(
                            f'Weekly sum out of bounds: emp {e} '
                            f'shift {shift} week {w} count {count} '
                            f'not in [{hard_min}, {hard_max}]')

    def test_coverage_minimums(self, schedule, instance):
        demands = instance['weekly_cover_demands']
        num_weeks = instance['num_weeks']
        num_shifts = len(instance['shifts'])
        for s in range(1, num_shifts):
            for w in range(num_weeks):
                for d in range(7):
                    day = w * 7 + d
                    count = sum(
                        1 for e in range(instance['num_employees'])
                        if schedule[e][day] == s)
                    demand = demands[d][s - 1]
                    if count < demand:
                        day_names = [
                            'Mon', 'Tue', 'Wed', 'Thu',
                            'Fri', 'Sat', 'Sun']
                        pytest.fail(
                            f'Coverage deficit: shift {s} day {day} '
                            f'(week {w} {day_names[d]}) '
                            f'has {count} workers, needs {demand}')


class TestPenaltyScore:
    def compute_penalty(self, schedule, instance):
        """Independently compute the total soft penalty."""
        penalty = 0.0
        num_days = instance['num_weeks'] * 7
        num_weeks = instance['num_weeks']
        num_employees = instance['num_employees']
        num_shifts = len(instance['shifts'])

        # Shift sequence soft penalties
        for sc in instance['shift_sequence_constraints']:
            shift = sc['shift']
            soft_min = sc['soft_min']
            min_cost = sc['min_cost']
            soft_max = sc['soft_max']
            max_cost = sc['max_cost']
            for e in range(num_employees):
                seqs = find_sequences(schedule[e], shift)
                for seq_len in seqs:
                    if seq_len < soft_min and min_cost > 0:
                        penalty += min_cost * (soft_min - seq_len)
                    if seq_len > soft_max and max_cost > 0:
                        penalty += max_cost * (seq_len - soft_max)

        # Weekly sum soft penalties
        for wsc in instance['weekly_sum_constraints']:
            shift = wsc['shift']
            soft_min = wsc['soft_min']
            min_cost = wsc['min_cost']
            soft_max = wsc['soft_max']
            max_cost = wsc['max_cost']
            for e in range(num_employees):
                for w in range(num_weeks):
                    count = sum(
                        1 for d in range(w * 7, (w + 1) * 7)
                        if schedule[e][d] == shift)
                    if count < soft_min and min_cost > 0:
                        penalty += min_cost * (soft_min - count)
                    if count > soft_max and max_cost > 0:
                        penalty += max_cost * (count - soft_max)

        # Request penalties
        for req in instance['requests']:
            e = req['employee']
            s = req['shift']
            d = req['day']
            w = req['weight']
            if schedule[e][d] == s:
                penalty += w

        # Penalized transitions
        for pt in instance['penalized_transitions']:
            prev_s = pt['from_shift']
            next_s = pt['to_shift']
            cost = pt['cost']
            for e in range(num_employees):
                for d in range(num_days - 1):
                    if schedule[e][d] == prev_s and \
                       schedule[e][d + 1] == next_s:
                        penalty += cost

        # Coverage excess penalties
        demands = instance['weekly_cover_demands']
        penalties = instance['excess_cover_penalties']
        for s in range(1, num_shifts):
            for w in range(num_weeks):
                for d in range(7):
                    day = w * 7 + d
                    count = sum(
                        1 for e in range(num_employees)
                        if schedule[e][day] == s)
                    demand = demands[d][s - 1]
                    excess = max(0, count - demand)
                    penalty += penalties[s - 1] * excess

        # Senior coverage penalties
        sc_data = instance['senior_coverage']
        senior_ids = [emp['id'] for emp in instance['employees']
                      if emp['role'] == 'senior']
        for s in sc_data['shifts_needing_senior']:
            for d in range(num_days):
                num_seniors = sum(
                    1 for e in senior_ids if schedule[e][d] == s)
                shortfall = max(0, sc_data['min_seniors'] - num_seniors)
                penalty += sc_data['violation_penalty'] * shortfall

        return penalty

    def test_penalty_below_threshold(self, schedule, instance):
        computed = self.compute_penalty(schedule, instance)
        assert computed <= PENALTY_THRESHOLD, \
            f'Penalty {computed} exceeds threshold {PENALTY_THRESHOLD}. ' \
            f'Solution requires better optimization.'

    def test_reported_penalty_consistent(self, schedule, instance, solution):
        computed = self.compute_penalty(schedule, instance)
        reported = solution.get('penalty', None)
        if reported is not None:
            # Allow small floating point tolerance
            assert abs(computed - reported) < 1.0, \
                f'Reported penalty {reported} != computed {computed}'
