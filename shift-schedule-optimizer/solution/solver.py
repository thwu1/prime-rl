#!/usr/bin/env python3
"""Reference solver for the shift scheduling optimization problem.

"""
import json
import sys
from ortools.sat.python import cp_model


def negated_bounded_span(works, start, length):
    """Return a clause that is falsified when works[start:start+length] is an
    isolated True span (bounded by False or boundary on both sides)."""
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
    cost_literals = []
    cost_coefficients = []

    # Forbid sequences shorter than hard_min
    for length in range(1, hard_min):
        for start in range(len(works) - length + 1):
            model.add_bool_or(negated_bounded_span(works, start, length))

    # Penalize sequences below soft_min
    if min_cost > 0:
        for length in range(hard_min, soft_min):
            for start in range(len(works) - length + 1):
                span = negated_bounded_span(works, start, length)
                lit = model.new_bool_var(f'{prefix}_under_{start}_{length}')
                span.append(lit)
                model.add_bool_or(span)
                cost_literals.append(lit)
                cost_coefficients.append(min_cost * (soft_min - length))

    # Penalize sequences above soft_max
    if max_cost > 0:
        for length in range(soft_max + 1, hard_max + 1):
            for start in range(len(works) - length + 1):
                span = negated_bounded_span(works, start, length)
                lit = model.new_bool_var(f'{prefix}_over_{start}_{length}')
                span.append(lit)
                model.add_bool_or(span)
                cost_literals.append(lit)
                cost_coefficients.append(max_cost * (length - soft_max))

    # Forbid sequences longer than hard_max
    for start in range(len(works) - hard_max):
        model.add_bool_or(
            [~works[i] for i in range(start, start + hard_max + 1)])

    return cost_literals, cost_coefficients


def add_soft_sum_constraint(model, works, hard_min, soft_min, min_cost,
                             soft_max, hard_max, max_cost, prefix):
    cost_variables = []
    cost_coefficients = []
    sum_var = model.new_int_var(hard_min, hard_max, '')
    model.add(sum_var == sum(works))

    if soft_min > hard_min and min_cost > 0:
        delta = model.new_int_var(-len(works), len(works), '')
        model.add(delta == soft_min - sum_var)
        excess = model.new_int_var(0, 7, f'{prefix}_under')
        model.add_max_equality(excess, [delta, 0])
        cost_variables.append(excess)
        cost_coefficients.append(min_cost)

    if soft_max < hard_max and max_cost > 0:
        delta = model.new_int_var(-7, 7, '')
        model.add(delta == sum_var - soft_max)
        excess = model.new_int_var(0, 7, f'{prefix}_over')
        model.add_max_equality(excess, [delta, 0])
        cost_variables.append(excess)
        cost_coefficients.append(max_cost)

    return cost_variables, cost_coefficients


def solve():
    with open('/app/instance.json') as f:
        data = json.load(f)

    num_employees = data['num_employees']
    num_weeks = data['num_weeks']
    num_days = num_weeks * 7
    num_shifts = len(data['shifts'])
    employees = data['employees']

    model = cp_model.CpModel()

    # Decision variables: work[e, s, d] = 1 iff employee e works shift s on day d
    work = {}
    for e in range(num_employees):
        for s in range(num_shifts):
            for d in range(num_days):
                work[e, s, d] = model.new_bool_var(f'w_{e}_{s}_{d}')

    # Objective terms
    obj_bool_vars = []
    obj_bool_coeffs = []
    obj_int_vars = []
    obj_int_coeffs = []

    # ========== HARD CONSTRAINTS ==========

    # HC1: Exactly one shift per employee per day
    for e in range(num_employees):
        for d in range(num_days):
            model.add_exactly_one(work[e, s, d] for s in range(num_shifts))

    # HC2: Fixed assignments
    for e, s, d in data['fixed_assignments']:
        model.add(work[e, s, d] == 1)

    # HC3: Unavailability (must be Off)
    for emp in employees:
        for d in emp['unavailable_days']:
            model.add(work[emp['id'], 0, d] == 1)

    # HC4: Forbidden transitions
    for prev_s, next_s in data['forbidden_transitions']:
        for e in range(num_employees):
            for d in range(num_days - 1):
                model.add_bool_or(
                    [work[e, prev_s, d].Not(), work[e, next_s, d + 1].Not()])

    # HC5: Max consecutive working days
    max_consec = data['max_consecutive_working_days']
    for e in range(num_employees):
        for start in range(num_days - max_consec):
            model.add_bool_or(
                [work[e, 0, start + i] for i in range(max_consec + 1)])

    # HC6: Night recovery constraint
    nr = data['night_recovery']
    min_nights = nr['min_consecutive_nights']
    recovery = nr['required_recovery_days']
    NIGHT = 3
    OFF = 0
    for e in range(num_employees):
        for d in range(min_nights - 1, num_days):
            for r in range(1, recovery + 1):
                if d + r >= num_days:
                    break
                # Clause: NOT(all nights d-k..d) OR night[d+1] OR off[d+r]
                clause = [work[e, NIGHT, d - k].Not()
                          for k in range(min_nights)]
                if d + 1 < num_days:
                    clause.append(work[e, NIGHT, d + 1])
                clause.append(work[e, OFF, d + r])
                model.add_bool_or(clause)

    # HC7 + SC1: Shift sequence constraints (hard bounds + soft penalties)
    for sc in data['shift_sequence_constraints']:
        shift = sc['shift']
        for e in range(num_employees):
            works_list = [work[e, shift, d] for d in range(num_days)]
            variables, coeffs = add_soft_sequence_constraint(
                model, works_list,
                sc['hard_min'], sc['soft_min'], sc['min_cost'],
                sc['soft_max'], sc['hard_max'], sc['max_cost'],
                f'seq_{e}_{shift}')
            obj_bool_vars.extend(variables)
            obj_bool_coeffs.extend(coeffs)

    # HC8 + SC2: Weekly sum constraints (hard bounds + soft penalties)
    for wsc in data['weekly_sum_constraints']:
        shift = wsc['shift']
        for e in range(num_employees):
            for w in range(num_weeks):
                works_list = [work[e, shift, d + w * 7] for d in range(7)]
                variables, coeffs = add_soft_sum_constraint(
                    model, works_list,
                    wsc['hard_min'], wsc['soft_min'], wsc['min_cost'],
                    wsc['soft_max'], wsc['hard_max'], wsc['max_cost'],
                    f'wksum_{e}_{shift}_{w}')
                obj_int_vars.extend(variables)
                obj_int_coeffs.extend(coeffs)

    # HC9: Coverage minimums (hard) + SC5: excess penalties (soft)
    demands = data['weekly_cover_demands']
    penalties = data['excess_cover_penalties']
    for s in range(1, num_shifts):
        for w in range(num_weeks):
            for d in range(7):
                works_list = [work[e, s, w * 7 + d]
                              for e in range(num_employees)]
                min_demand = demands[d][s - 1]
                worked = model.new_int_var(min_demand, num_employees, '')
                model.add(worked == sum(works_list))
                over_penalty = penalties[s - 1]
                if over_penalty > 0:
                    excess = model.new_int_var(
                        0, num_employees - min_demand,
                        f'excess_{s}_{w}_{d}')
                    model.add(excess == worked - min_demand)
                    obj_int_vars.append(excess)
                    obj_int_coeffs.append(over_penalty)

    # ========== SOFT CONSTRAINTS ==========

    # SC3: Requests
    for req in data['requests']:
        e = req['employee']
        s = req['shift']
        d = req['day']
        w = req['weight']
        obj_bool_vars.append(work[e, s, d])
        obj_bool_coeffs.append(w)

    # SC4: Penalized transitions
    for pt in data['penalized_transitions']:
        prev_s = pt['from_shift']
        next_s = pt['to_shift']
        cost = pt['cost']
        for e in range(num_employees):
            for d in range(num_days - 1):
                trans = model.new_bool_var(
                    f'trans_{e}_{d}_{prev_s}_{next_s}')
                model.add_bool_or(
                    [work[e, prev_s, d].Not(),
                     work[e, next_s, d + 1].Not(),
                     trans])
                obj_bool_vars.append(trans)
                obj_bool_coeffs.append(cost)

    # SC6: Senior coverage (soft)
    sc_data = data['senior_coverage']
    senior_ids = [emp['id'] for emp in employees if emp['role'] == 'senior']
    for s in sc_data['shifts_needing_senior']:
        for d in range(num_days):
            senior_works = [work[e, s, d] for e in senior_ids]
            shortfall = model.new_int_var(
                0, sc_data['min_seniors'], f'sr_short_{s}_{d}')
            model.add(shortfall >= sc_data['min_seniors'] - sum(senior_works))
            obj_int_vars.append(shortfall)
            obj_int_coeffs.append(sc_data['violation_penalty'])

    # ========== OBJECTIVE ==========
    model.minimize(
        sum(obj_bool_vars[i] * obj_bool_coeffs[i]
            for i in range(len(obj_bool_vars)))
        + sum(obj_int_vars[i] * obj_int_coeffs[i]
              for i in range(len(obj_int_vars))))

    # ========== SOLVE ==========
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 120.0
    solver.parameters.num_workers = 1
    status = solver.solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        schedule = []
        for e in range(num_employees):
            row = []
            for d in range(num_days):
                for s in range(num_shifts):
                    if solver.boolean_value(work[e, s, d]):
                        row.append(s)
                        break
            schedule.append(row)

        penalty = solver.objective_value
        result = {
            'schedule': schedule,
            'penalty': penalty,
            'status': 'OPTIMAL' if status == cp_model.OPTIMAL else 'FEASIBLE'
        }
        with open('/app/schedule.json', 'w') as f:
            json.dump(result, f, indent=2)
        print(f'Solution: penalty={penalty}, status={result["status"]}')
    else:
        print('No solution found!', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    solve()
