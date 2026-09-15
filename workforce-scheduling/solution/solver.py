#!/usr/bin/env python3

"""Reference solver for the workforce scheduling optimization problem.

Uses Google OR-Tools CP-SAT solver to find an optimal schedule that
satisfies all hard constraints while minimizing total soft constraint penalty.
"""

import json

from ortools.sat.python import cp_model


def negated_bounded_span(works, start, length):
    """Filters an isolated sub-sequence of variables assigned to True.

    Extract the span of Boolean variables [start, start + length), negate them,
    and if there are variables to the left/right, surround the span by them
    in non-negated form. The conjunction of the returned list is false if the
    sub-list is assigned to True and correctly bounded.
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
    """Sequence constraint on true variables with soft and hard bounds."""
    cost_literals = []
    cost_coefficients = []

    # Forbid sequences that are too short.
    for length in range(1, hard_min):
        for start in range(len(works) - length + 1):
            model.add_bool_or(negated_bounded_span(works, start, length))

    # Penalize sequences below soft_min.
    if min_cost > 0:
        for length in range(hard_min, soft_min):
            for start in range(len(works) - length + 1):
                span = negated_bounded_span(works, start, length)
                name = f": under_span(start={start}, length={length})"
                lit = model.new_bool_var(prefix + name)
                span.append(lit)
                model.add_bool_or(span)
                cost_literals.append(lit)
                cost_coefficients.append(min_cost * (soft_min - length))

    # Penalize sequences above soft_max.
    if max_cost > 0:
        for length in range(soft_max + 1, hard_max + 1):
            for start in range(len(works) - length + 1):
                span = negated_bounded_span(works, start, length)
                name = f": over_span(start={start}, length={length})"
                lit = model.new_bool_var(prefix + name)
                span.append(lit)
                model.add_bool_or(span)
                cost_literals.append(lit)
                cost_coefficients.append(max_cost * (length - soft_max))

    # Forbid sequences longer than hard_max.
    for start in range(len(works) - hard_max):
        model.add_bool_or(
            [~works[i] for i in range(start, start + hard_max + 1)]
        )

    return cost_literals, cost_coefficients


def add_soft_sum_constraint(model, works, hard_min, soft_min, min_cost,
                             soft_max, hard_max, max_cost, prefix):
    """Sum constraint with soft and hard bounds."""
    cost_variables = []
    cost_coefficients = []
    sum_var = model.new_int_var(hard_min, hard_max, "")
    model.add(sum_var == sum(works))

    if soft_min > hard_min and min_cost > 0:
        delta = model.new_int_var(-len(works), len(works), "")
        model.add(delta == soft_min - sum_var)
        excess = model.new_int_var(0, 7, prefix + ": under_sum")
        model.add_max_equality(excess, [delta, 0])
        cost_variables.append(excess)
        cost_coefficients.append(min_cost)

    if soft_max < hard_max and max_cost > 0:
        delta = model.new_int_var(-7, 7, "")
        model.add(delta == sum_var - soft_max)
        excess = model.new_int_var(0, 7, prefix + ": over_sum")
        model.add_max_equality(excess, [delta, 0])
        cost_variables.append(excess)
        cost_coefficients.append(max_cost)

    return cost_variables, cost_coefficients


def solve():
    with open("/app/problem.json") as f:
        problem = json.load(f)

    meta = problem["metadata"]
    num_employees = meta["num_employees"]
    num_days = meta["num_days"]
    num_weeks = meta["num_weeks"]
    shifts = meta["shift_types"]
    num_shifts = len(shifts)

    employees = problem["employees"]
    senior_ids = {e["id"] for e in employees if e["senior"]}

    model = cp_model.CpModel()

    # Decision variables: work[e, s, d] = 1 iff employee e works shift s on day d
    work = {}
    for e in range(num_employees):
        for s in range(num_shifts):
            for d in range(num_days):
                work[e, s, d] = model.new_bool_var(f"work_{e}_{s}_{d}")

    # Objective terms
    obj_int_vars = []
    obj_int_coeffs = []
    obj_bool_vars = []
    obj_bool_coeffs = []

    # --- HARD CONSTRAINT: Exactly one shift per employee per day ---
    for e in range(num_employees):
        for d in range(num_days):
            model.add_exactly_one(work[e, s, d] for s in range(num_shifts))

    # --- HARD CONSTRAINT: Fixed assignments ---
    for emp, shift_idx, day in problem["fixed_assignments"]:
        model.add(work[emp, shift_idx, day] == 1)

    # --- SOFT: Employee requests ---
    for emp, shift_idx, day, weight in problem["requests"]:
        obj_bool_vars.append(work[emp, shift_idx, day])
        obj_bool_coeffs.append(weight)

    # --- Shift sequence constraints (hard + soft) ---
    for sc in problem["shift_sequence_constraints"]:
        shift = sc["shift"]
        for e in range(num_employees):
            works = [work[e, shift, d] for d in range(num_days)]
            variables, coeffs = add_soft_sequence_constraint(
                model, works,
                sc["hard_min"], sc["soft_min"], sc["min_penalty"],
                sc["soft_max"], sc["hard_max"], sc["max_penalty"],
                f"seq(e={e},s={shift})"
            )
            obj_bool_vars.extend(variables)
            obj_bool_coeffs.extend(coeffs)

    # --- Weekly sum constraints (hard + soft) ---
    for wsc in problem["weekly_sum_constraints"]:
        shift = wsc["shift"]
        for e in range(num_employees):
            for w in range(num_weeks):
                works = [work[e, shift, d + w * 7] for d in range(7)]
                variables, coeffs = add_soft_sum_constraint(
                    model, works,
                    wsc["hard_min"], wsc["soft_min"], wsc["min_penalty"],
                    wsc["soft_max"], wsc["hard_max"], wsc["max_penalty"],
                    f"wsum(e={e},s={shift},w={w})"
                )
                obj_int_vars.extend(variables)
                obj_int_coeffs.extend(coeffs)

    # --- HARD CONSTRAINT: Forbidden transitions ---
    for prev_shift, next_shift in problem["forbidden_transitions"]:
        for e in range(num_employees):
            for d in range(num_days - 1):
                model.add_bool_or([
                    ~work[e, prev_shift, d],
                    ~work[e, next_shift, d + 1]
                ])

    # --- SOFT: Penalized transitions ---
    for prev_shift, next_shift, cost in problem["penalized_transitions"]:
        for e in range(num_employees):
            for d in range(num_days - 1):
                trans_var = model.new_bool_var(f"trans(e={e},d={d})")
                model.add_bool_or([
                    ~work[e, prev_shift, d],
                    ~work[e, next_shift, d + 1],
                    trans_var
                ])
                obj_bool_vars.append(trans_var)
                obj_bool_coeffs.append(cost)

    # --- HARD + SOFT: Cover demands + excess penalty ---
    demands = problem["weekly_cover_demands"]
    excess_pens = problem["excess_cover_penalties"]
    shift_name_to_idx = {name: idx for idx, name in enumerate(shifts)}

    for d in range(num_days):
        dow = d % 7
        demand = demands[dow]
        for shift_name in ["D", "E", "N"]:
            s_idx = shift_name_to_idx[shift_name]
            min_demand = demand[shift_name]
            works_list = [work[e, s_idx, d] for e in range(num_employees)]

            # Hard: at least min_demand
            worked = model.new_int_var(min_demand, num_employees, "")
            model.add(worked == sum(works_list))

            # Soft: excess penalty
            over_penalty = excess_pens[shift_name]
            if over_penalty > 0:
                excess = model.new_int_var(
                    0, num_employees - min_demand,
                    f"excess(s={shift_name},d={d})"
                )
                model.add(excess == worked - min_demand)
                obj_int_vars.append(excess)
                obj_int_coeffs.append(over_penalty)

    # --- HARD CONSTRAINT: Senior coverage ---
    senior_reqs = problem["senior_requirements"]
    for d in range(num_days):
        for shift_name, min_senior in senior_reqs.items():
            s_idx = shift_name_to_idx[shift_name]
            senior_works = [work[e, s_idx, d] for e in senior_ids]
            model.add(sum(senior_works) >= min_senior)

    # --- HARD CONSTRAINT: Incompatible pairs ---
    for pair_info in problem["incompatible_pairs"]:
        e1, e2 = pair_info["employees"]
        s_idx = pair_info["shift"]
        for d in range(num_days):
            model.add_bool_or([~work[e1, s_idx, d], ~work[e2, s_idx, d]])

    # --- SOFT: Weekend pairing penalty ---
    weekend_pen = problem["weekend_pair_penalty"]
    for e in range(num_employees):
        for w in range(num_weeks):
            sat = w * 7 + 5
            sun = w * 7 + 6
            sat_off = work[e, 0, sat]  # shift 0 = Off
            sun_off = work[e, 0, sun]
            # Penalty if exactly one is off: sat_off XOR sun_off
            pen_sat_only = model.new_bool_var(f"wknd_sat(e={e},w={w})")
            model.add_implication(pen_sat_only, sat_off)
            model.add_implication(pen_sat_only, ~sun_off)
            model.add_bool_or([~sat_off, sun_off, pen_sat_only])

            pen_sun_only = model.new_bool_var(f"wknd_sun(e={e},w={w})")
            model.add_implication(pen_sun_only, ~sat_off)
            model.add_implication(pen_sun_only, sun_off)
            model.add_bool_or([sat_off, ~sun_off, pen_sun_only])

            obj_bool_vars.append(pen_sat_only)
            obj_bool_coeffs.append(weekend_pen)
            obj_bool_vars.append(pen_sun_only)
            obj_bool_coeffs.append(weekend_pen)

    # --- SOFT: Night fairness penalty (range-based) ---
    fairness_pen = problem["night_fairness_penalty"]
    night_counts = []
    for e in range(num_employees):
        nc = model.new_int_var(0, num_days, f"night_count_{e}")
        model.add(nc == sum(work[e, 3, d] for d in range(num_days)))
        night_counts.append(nc)

    max_nc = model.new_int_var(0, num_days, "max_night_count")
    model.add_max_equality(max_nc, night_counts)
    min_nc = model.new_int_var(0, num_days, "min_night_count")
    model.add_min_equality(min_nc, night_counts)
    night_range = model.new_int_var(0, num_days, "night_range")
    model.add(night_range == max_nc - min_nc)
    obj_int_vars.append(night_range)
    obj_int_coeffs.append(fairness_pen)

    # --- Objective: minimize total penalty ---
    model.minimize(
        sum(
            obj_bool_vars[i] * obj_bool_coeffs[i]
            for i in range(len(obj_bool_vars))
        )
        + sum(
            obj_int_vars[i] * obj_int_coeffs[i]
            for i in range(len(obj_int_vars))
        )
    )

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 240.0
    solver.parameters.num_workers = 8
    solver.parameters.log_search_progress = True
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"No solution found. Status: {solver.status_name(status)}")
        with open("/app/schedule.json", "w") as f:
            json.dump({"schedule": [], "objective": -1}, f)
        return

    # Extract solution
    schedule = []
    for e in range(num_employees):
        row = []
        for d in range(num_days):
            for s in range(num_shifts):
                if solver.boolean_value(work[e, s, d]):
                    row.append(shifts[s])
                    break
        schedule.append(row)

    objective = int(round(solver.objective_value))

    # Write solution
    with open("/app/schedule.json", "w") as f:
        json.dump({"schedule": schedule, "objective": objective}, f, indent=2)

    print(f"Solution found with objective = {objective}")
    print(f"Status: {solver.status_name(status)}")
    print(f"Time: {solver.wall_time:.2f}s")
    print(f"Conflicts: {solver.num_conflicts}")


if __name__ == "__main__":
    solve()
