#!/usr/bin/env python3
"""Facility location solver - WIP implementation
Assigns customers to nearest feasible facility using greedy heuristic.
"""
import sys
import math


def solve(input_file):
    with open(input_file) as f:
        lines = f.read().strip().split('\n')

    parts = lines[0].split()
    n_facilities = int(parts[0])
    n_customers = int(parts[1])

    facilities = []
    for i in range(n_facilities):
        p = lines[1 + i].split()
        facilities.append({
            'setup': float(p[0]),
            'cap': int(float(p[1])),
            'x': float(p[2]),
            'y': float(p[3])
        })

    customers = []
    for j in range(n_customers):
        p = lines[1 + n_facilities + j].split()
        customers.append({
            'demand': int(float(p[0])),
            'x': float(p[1]),
            'y': float(p[2])
        })

    # Greedy nearest-facility assignment
    assignment = [-1] * n_customers
    remaining_cap = [f['cap'] for f in facilities]

    for j in range(n_customers):
        best_f = -1
        best_dist = float('inf')
        for i in range(n_facilities):
            d = abs(facilities[i]['x'] - customers[j]['x']) + \
                abs(facilities[i]['y'] - customers[j]['y'])
            if d < best_dist and remaining_cap[i] >= customers[j]['demand']:
                best_dist = d
                best_f = i

        if best_f == -1:
            # fallback: just use facility 0
            best_f = 0

        assignment[j] = best_f
        remaining_cap[best_f] -= customers[j]['demand']

    # Calculate objective
    used = set(assignment)
    obj = sum(facilities[i]['setup'] for i in used)
    for j in range(n_customers):
        fi = assignment[j]
        obj += abs(facilities[fi]['x'] - customers[j]['x']) + \
               abs(facilities[fi]['y'] - customers[j]['y'])

    print(f"{obj:.2f} 0")
    print(' '.join(str(a) for a in assignment))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: solver.py <instance_file>", file=sys.stderr)
        sys.exit(1)
    solve(sys.argv[1])
