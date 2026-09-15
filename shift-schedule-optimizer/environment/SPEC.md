# Shift Scheduling Problem Specification

## Overview

Schedule `num_employees` employees across `num_weeks * 7` days. Each employee is assigned exactly one shift per day from the set `["O", "M", "A", "N"]` (Off=0, Morning=1, Afternoon=2, Night=3). The objective is to minimize a weighted penalty from soft constraint violations.

## Input Format (`instance.json`)

- `num_employees`: integer
- `num_weeks`: integer (horizon = num_weeks * 7 days, 0-indexed starting Monday)
- `shifts`: list of shift labels `["O", "M", "A", "N"]`
- `employees`: list of `{id, role, unavailable_days}`
  - `role`: one of `"senior"`, `"regular"`, `"junior"`
  - `unavailable_days`: list of day indices where employee must be Off
- `fixed_assignments`: list of `[employee, shift, day]` triples that are pre-assigned
- `requests`: list of `{employee, shift, day, weight}`
  - Negative weight = employee desires this assignment (reward for assigning)
  - Positive weight = employee wants to avoid this assignment (penalty for assigning)
- `shift_sequence_constraints`: list of `{shift, hard_min, soft_min, min_cost, soft_max, hard_max, max_cost}`
  - Controls lengths of maximal contiguous sequences of a given shift
  - Sequences shorter than `hard_min` or longer than `hard_max` are **forbidden** (hard constraint)
  - Sequences shorter than `soft_min` incur penalty: `min_cost * (soft_min - length)` per sequence
  - Sequences longer than `soft_max` incur penalty: `max_cost * (length - soft_max)` per sequence
- `weekly_sum_constraints`: list of `{shift, hard_min, soft_min, min_cost, soft_max, hard_max, max_cost}`
  - Controls the count of a given shift per employee per 7-day week
  - Counts outside `[hard_min, hard_max]` are **forbidden** (hard constraint)
  - Counts below `soft_min` incur penalty: `min_cost * (soft_min - count)`
  - Counts above `soft_max` incur penalty: `max_cost * (count - soft_max)`
- `forbidden_transitions`: list of `[from_shift, to_shift]` pairs
  - Consecutive day assignments `(from_shift on day d, to_shift on day d+1)` are **forbidden**
- `penalized_transitions`: list of `{from_shift, to_shift, cost}`
  - Consecutive day transitions incur `cost` per occurrence
- `weekly_cover_demands`: list of 7 lists `[morning_demand, afternoon_demand, night_demand]`
  - Index 0 = Monday, ..., 6 = Sunday; pattern repeats each week
  - The number of employees assigned to each working shift must be **at least** the demand (hard constraint)
  - Excess employees above demand incur penalty per `excess_cover_penalties`
- `excess_cover_penalties`: list of 3 values `[morning_penalty, afternoon_penalty, night_penalty]`
  - Penalty per excess employee above demand, per shift per day
- `max_consecutive_working_days`: integer
  - No employee may work (non-Off shift) more than this many consecutive days (hard constraint)
- `night_recovery`: `{min_consecutive_nights, required_recovery_days}`
  - After a contiguous block of `min_consecutive_nights` or more night shifts, the employee must have `required_recovery_days` consecutive Off days immediately following the block (hard constraint)
  - Only enforced for recovery days within the scheduling horizon
- `senior_coverage`: `{shifts_needing_senior, min_seniors, violation_penalty}`
  - For each shift in `shifts_needing_senior` and each day, at least `min_seniors` senior-role employees should be assigned
  - Shortfall incurs penalty: `violation_penalty * max(0, min_seniors - num_seniors_assigned)` (soft constraint)

## Output Format (`schedule.json`)

```json
{
    "schedule": [
        [1, 2, 0, 3, ...],
        ...
    ],
    "penalty": 42.0
}
```

- `schedule`: list of `num_employees` lists, each containing `num_days` shift indices (0=O, 1=M, 2=A, 3=N)
- `penalty`: total objective value (sum of all soft constraint penalties)

## Objective

Minimize the sum of:
1. Shift sequence soft penalties
2. Weekly sum soft penalties
3. Request weights (for assigned request shifts)
4. Penalized transition costs
5. Coverage excess penalties
6. Senior coverage shortfall penalties
