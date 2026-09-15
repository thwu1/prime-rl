#!/usr/bin/env python3

"""Reference solver for multi-department shift scheduling optimization."""

import json
from ortools.sat.python import cp_model


def negated_bounded_span(works, start, length):
    """Return literals whose disjunction is falsified by an isolated True span.

    The returned clause is False exactly when works[start:start+length] are all
    True AND the span is bounded by False (or array edges) on both sides.
    """
    sequence = []
    if start > 0:
        sequence.append(works[start - 1])
    for i in range(length):
        sequence.append(~works[start + i])
    if start + length < len(works):
        sequence.append(works[start + length])
    return sequence


def add_soft_sequence_constraint(model, works, hard_min, soft_min, min_cost,
                                 soft_max, hard_max, max_cost, prefix):
    """Sequence constraint on true variables with soft and hard bounds.

    Forbids maximal contiguous sequences shorter than hard_min or longer than
    hard_max. Penalizes sequences shorter than soft_min or longer than soft_max.
    """
    cost_literals = []
    cost_coefficients = []

    # Forbid sequences that are too short.
    for length in range(1, hard_min):
        for start in range(len(works) - length + 1):
            model.add_bool_or(negated_bounded_span(works, start, length))

    # Penalize sequences below the soft limit.
    if min_cost > 0:
        for length in range(hard_min, soft_min):
            for start in range(len(works) - length + 1):
                span = negated_bounded_span(works, start, length)
                lit = model.new_bool_var(f"{prefix}: under(s={start},l={length})")
                span.append(lit)
                model.add_bool_or(span)
                cost_literals.append(lit)
                cost_coefficients.append(min_cost * (soft_min - length))

    # Penalize sequences above the soft limit.
    if max_cost > 0:
        for length in range(soft_max + 1, hard_max + 1):
            for start in range(len(works) - length + 1):
                span = negated_bounded_span(works, start, length)
                lit = model.new_bool_var(f"{prefix}: over(s={start},l={length})")
                span.append(lit)
                model.add_bool_or(span)
                cost_literals.append(lit)
                cost_coefficients.append(max_cost * (length - soft_max))

    # Forbid sequences that are too long.
    for start in range(len(works) - hard_max):
        model.add_bool_or(
            [~works[i] for i in range(start, start + hard_max + 1)])

    return cost_literals, cost_coefficients


def add_soft_sum_constraint(model, works, hard_min, soft_min, min_cost,
                            soft_max, hard_max, max_cost, prefix):
    """Sum constraint with soft and hard bounds.

    Enforces hard bounds on the sum of True variables, and penalizes sums
    outside the [soft_min, soft_max] range.
    """
    cost_variables = []
    cost_coefficients = []
    sum_var = model.new_int_var(hard_min, hard_max, "")
    model.add(sum_var == sum(works))

    # Penalize sums below the soft_min target.
    if soft_min > hard_min and min_cost > 0:
        delta = model.new_int_var(-len(works), len(works), "")
        model.add(delta == soft_min - sum_var)
        excess = model.new_int_var(0, 7, f"{prefix}: under_sum")
        model.add_max_equality(excess, [delta, 0])
        cost_variables.append(excess)
        cost_coefficients.append(min_cost)

    # Penalize sums above the soft_max target.
    if soft_max < hard_max and max_cost > 0:
        delta = model.new_int_var(-7, 7, "")
        model.add(delta == sum_var - soft_max)
        excess = model.new_int_var(0, 7, f"{prefix}: over_sum")
        model.add_max_equality(excess, [delta, 0])
        cost_variables.append(excess)
        cost_coefficients.append(max_cost)

    return cost_variables, cost_coefficients


def solve():
    """Read instance, build CP-SAT model, solve, write output."""
    with open("/app/instance.json") as f:
        data = json.load(f)

    num_employees = data["num_employees"]
    num_weeks = data["num_weeks"]
    shifts = data["shifts"]
    num_shifts = len(shifts)
    num_days = num_weeks * 7
    departments = data["departments"]
    skills = {int(k): v for k, v in data["skills"].items()}
    fixed_assignments = data["fixed_assignments"]
    requests = data["requests"]
    shift_constraints = data["shift_constraints"]
    weekly_sum_constraints = data["weekly_sum_constraints"]
    penalized_transitions = data["penalized_transitions"]
    weekly_cover_demands = data["weekly_cover_demands"]
    excess_cover_penalties = data["excess_cover_penalties"]
    incompatible_night_pairs = data["incompatible_night_pairs"]
    weekend_completeness = data["weekend_completeness"]

    model = cp_model.CpModel()

    # Decision variables: work[e, s, d] = 1 iff employee e works shift s on day d.
    work = {}
    for e in range(num_employees):
        for s in range(num_shifts):
            for d in range(num_days):
                work[e, s, d] = model.new_bool_var(f"w_{e}_{s}_{d}")

    # Objective accumulators.
    obj_int_vars = []
    obj_int_coeffs = []
    obj_bool_vars = []
    obj_bool_coeffs = []

    # --- Hard + soft constraints ---

    # C1: Exactly one shift per employee per day.
    for e in range(num_employees):
        for d in range(num_days):
            model.add_exactly_one(work[e, s, d] for s in range(num_shifts))

    # C2: Skill constraint — forbid shifts the employee cannot work.
    for e in range(num_employees):
        for s in range(num_shifts):
            if s not in skills[e]:
                for d in range(num_days):
                    model.add(work[e, s, d] == 0)

    # C3: Fixed assignments.
    for e, s, d in fixed_assignments:
        model.add(work[e, s, d] == 1)

    # C4: Employee requests (soft objective terms).
    for e, s, d, w in requests:
        obj_bool_vars.append(work[e, s, d])
        obj_bool_coeffs.append(w)

    # C5: Shift sequence constraints.
    for ct in shift_constraints:
        shift_id, hard_min, soft_min, min_cost, soft_max, hard_max, max_cost = ct
        for e in range(num_employees):
            works = [work[e, shift_id, d] for d in range(num_days)]
            variables, coeffs = add_soft_sequence_constraint(
                model, works, hard_min, soft_min, min_cost, soft_max,
                hard_max, max_cost, f"seq(e={e},s={shift_id})")
            obj_bool_vars.extend(variables)
            obj_bool_coeffs.extend(coeffs)

    # C6: Weekly sum constraints.
    for ct in weekly_sum_constraints:
        shift_id, hard_min, soft_min, min_cost, soft_max, hard_max, max_cost = ct
        for e in range(num_employees):
            for w in range(num_weeks):
                works = [work[e, shift_id, d + w * 7] for d in range(7)]
                variables, coeffs = add_soft_sum_constraint(
                    model, works, hard_min, soft_min, min_cost, soft_max,
                    hard_max, max_cost, f"wsum(e={e},s={shift_id},w={w})")
                obj_int_vars.extend(variables)
                obj_int_coeffs.extend(coeffs)

    # C7: Penalized and forbidden transitions.
    for prev_shift, next_shift, cost in penalized_transitions:
        for e in range(num_employees):
            for d in range(num_days - 1):
                transition = [
                    ~work[e, prev_shift, d],
                    ~work[e, next_shift, d + 1],
                ]
                if cost == 0:
                    model.add_bool_or(transition)
                else:
                    trans_var = model.new_bool_var(
                        f"trans(e={e},d={d},{prev_shift}->{next_shift})")
                    transition.append(trans_var)
                    model.add_bool_or(transition)
                    obj_bool_vars.append(trans_var)
                    obj_bool_coeffs.append(cost)

    # C8: Coverage constraints per department.
    for dept_name, dept_employees in departments.items():
        dept_demands = weekly_cover_demands[dept_name]
        for s in range(1, num_shifts):  # skip Off shift
            for w in range(num_weeks):
                for dow in range(7):
                    day = w * 7 + dow
                    works = [work[e, s, day] for e in dept_employees]
                    min_demand = dept_demands[str(dow)][s - 1]
                    worked = model.new_int_var(
                        min_demand, len(dept_employees), "")
                    model.add(worked == sum(works))
                    over_penalty = excess_cover_penalties[s - 1]
                    if over_penalty > 0:
                        name = f"excess({dept_name},s={s},w={w},d={dow})"
                        excess = model.new_int_var(
                            0, len(dept_employees) - min_demand, name)
                        model.add(excess == worked - min_demand)
                        obj_int_vars.append(excess)
                        obj_int_coeffs.append(over_penalty)

    # C9: Incompatible night pairs.
    night_shift = 3
    for e1, e2 in incompatible_night_pairs:
        for d in range(num_days):
            model.add_bool_or([
                ~work[e1, night_shift, d],
                ~work[e2, night_shift, d],
            ])

    # C10: Weekend completeness — off on Saturday iff off on Sunday.
    if weekend_completeness:
        off_shift = 0
        for w in range(num_weeks):
            sat = w * 7 + 5
            sun = w * 7 + 6
            for e in range(num_employees):
                model.add(work[e, off_shift, sat] == work[e, off_shift, sun])

    # Objective: minimize total penalty.
    model.minimize(
        sum(obj_bool_vars[i] * obj_bool_coeffs[i]
            for i in range(len(obj_bool_vars)))
        + sum(obj_int_vars[i] * obj_int_coeffs[i]
              for i in range(len(obj_int_vars)))
    )

    # Solve.
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 120.0
    solver.parameters.num_workers = 1
    solution_printer = cp_model.ObjectiveSolutionPrinter()
    status = solver.solve(model, solution_printer)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        schedule = {}
        for e in range(num_employees):
            employee_schedule = []
            for d in range(num_days):
                for s in range(num_shifts):
                    if solver.boolean_value(work[e, s, d]):
                        employee_schedule.append(s)
                        break
            schedule[str(e)] = employee_schedule

        status_str = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        result = {
            "objective": int(solver.objective_value),
            "schedule": schedule,
            "status": status_str,
        }

        with open("/app/output.json", "w") as f:
            json.dump(result, f, indent=2)

        print(f"Solved: objective={int(solver.objective_value)}, "
              f"status={status_str}")
    else:
        print("ERROR: No solution found!")
        import sys
        sys.exit(1)


if __name__ == "__main__":
    solve()
