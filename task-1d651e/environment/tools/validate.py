#!/usr/bin/env python3
"""Solution validator for facility location optimization pipeline.
Checks feasibility, objective accuracy, quality thresholds, and LP bounds.
"""
import sys
import math
import json


def parse_instance(filepath):
    with open(filepath) as f:
        lines = f.read().strip().split('\n')
    parts = lines[0].split()
    n_fac = int(parts[0])
    n_cust = int(parts[1])

    facilities = []
    for i in range(n_fac):
        p = lines[1 + i].split()
        facilities.append({
            'setup': float(p[0]),
            'cap': int(float(p[1])),
            'x': float(p[2]),
            'y': float(p[3])
        })

    customers = []
    for j in range(n_cust):
        p = lines[1 + n_fac + j].split()
        customers.append({
            'demand': int(float(p[0])),
            'x': float(p[1]),
            'y': float(p[2])
        })

    return facilities, customers


def euclidean(x1, y1, x2, y2):
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


def validate(instance_file, solution_file, scenario_file):
    facilities, customers = parse_instance(instance_file)
    n = len(facilities)
    m = len(customers)

    with open(solution_file) as f:
        sol_lines = f.read().strip().split('\n')

    if len(sol_lines) < 2:
        return False, "Solution must have at least 2 lines (objective + assignments)"

    # Parse first line: objective and optimality flag
    obj_parts = sol_lines[0].split()
    if len(obj_parts) < 2:
        return False, f"First line must have >= 2 values, got {len(obj_parts)}"

    try:
        reported_obj = float(obj_parts[0])
    except ValueError:
        return False, f"Cannot parse objective value: {obj_parts[0]}"

    # Parse second line: assignments
    try:
        assignment = list(map(int, sol_lines[1].split()))
    except ValueError:
        return False, "Cannot parse assignment line as integers"

    if len(assignment) != m:
        return False, f"Expected {m} assignments, got {len(assignment)}"

    # Check assignment validity
    for j, fi in enumerate(assignment):
        if fi < 0 or fi >= n:
            return False, f"Customer {j} assigned to invalid facility {fi}"

    # Check capacity constraints
    load = [0] * n
    for j, fi in enumerate(assignment):
        load[fi] += customers[j]['demand']

    for i in range(n):
        if load[i] > facilities[i]['cap']:
            return False, (f"Facility {i} over capacity: "
                          f"demand {load[i]} > capacity {facilities[i]['cap']}")

    # Compute actual objective (Euclidean distances)
    used = set(assignment)
    actual_obj = sum(facilities[i]['setup'] for i in used)
    for j in range(m):
        fi = assignment[j]
        actual_obj += euclidean(
            facilities[fi]['x'], facilities[fi]['y'],
            customers[j]['x'], customers[j]['y']
        )

    # Check reported vs actual objective
    tol = max(1.0, actual_obj * 0.002)
    if abs(actual_obj - reported_obj) > tol:
        return False, (f"Reported objective {reported_obj:.2f} differs from "
                       f"computed Euclidean objective {actual_obj:.2f}")

    # Check quality threshold
    with open(scenario_file) as f:
        scenario = json.load(f)

    threshold = scenario['max_objective']
    if actual_obj > threshold:
        return False, f"Objective {actual_obj:.2f} exceeds threshold {threshold}"

    # Check LP bound if required
    if scenario.get('require_lp_bound', False):
        lp_bound = None
        for line in sol_lines[2:]:
            stripped = line.strip()
            if stripped.startswith('LP_BOUND'):
                parts = stripped.split()
                if len(parts) >= 2:
                    try:
                        lp_bound = float(parts[-1])
                    except ValueError:
                        pass
                break

        if lp_bound is None:
            return False, "LP relaxation bound required but not found in solution"
        if lp_bound <= 0:
            return False, f"LP bound must be positive, got {lp_bound}"
        if lp_bound > actual_obj + 1.0:
            return False, f"LP bound {lp_bound:.2f} exceeds objective {actual_obj:.2f}"

    return True, f"VALID: objective={actual_obj:.2f}, threshold={threshold}"


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: validate.py <instance_file> <solution_file> <scenario_file>",
              file=sys.stderr)
        sys.exit(1)
    ok, msg = validate(sys.argv[1], sys.argv[2], sys.argv[3])
    print(msg)
    sys.exit(0 if ok else 1)
