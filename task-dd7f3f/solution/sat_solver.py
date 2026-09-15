#!/usr/bin/env python3

"""
SAT-based exact solver for One-Sided Crossing Minimization using MiniSat.

Encoding:
  - Boolean ordering variables x_{i,j} for each pair of B-vertices (i<j).
    x_{i,j} = True means vertex i is placed before vertex j.
  - Transitivity axioms ensure a consistent total order.
  - Each edge pair that can cross contributes a crossing indicator literal
    (a positive or negative ordering variable).
  - Optimization via binary search: for a target bound k, a sequential
    counter cardinality constraint (Sinz, CP 2005) encodes "at most k
    crossing indicators are true". MiniSat determines satisfiability.
  - The minimum k for which SAT holds is the optimal crossing number.
"""

import os
import sys
import subprocess
import json
from functools import cmp_to_key


def parse_instance(filepath):
    n0 = n1 = 0
    edges = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('c'):
                continue
            if line.startswith('p'):
                parts = line.split()
                n0, n1 = int(parts[2]), int(parts[3])
            else:
                parts = line.split()
                edges.append((int(parts[0]), int(parts[1])))
    return n0, n1, edges


def build_crossing_literals(n0, n1, edges, order_var):
    """Build list of SAT literals, each indicating one edge-pair crossing.

    For edges (a1,b1) and (a2,b2) with a1 < a2 and b1 != b2:
      crossing iff pos(b1) > pos(b2)
    This maps to a positive or negative ordering variable literal.
    """
    b_idx = {n0 + 1 + i: i for i in range(n1)}
    lits = []
    for ei in range(len(edges)):
        a1, b1 = edges[ei]
        bi1 = b_idx[b1]
        for ej in range(ei + 1, len(edges)):
            a2, b2 = edges[ej]
            bi2 = b_idx[b2]
            if a1 == a2 or bi1 == bi2:
                continue
            # Normalize so a_small < a_large
            if a1 < a2:
                # crossing iff b1 is placed after b2
                if bi1 < bi2:
                    lits.append(-order_var[(bi1, bi2)])  # crossing iff NOT(bi1 before bi2)
                else:
                    lits.append(order_var[(bi2, bi1)])   # crossing iff bi2 before bi1
            else:
                # crossing iff b1 is placed before b2
                if bi1 < bi2:
                    lits.append(order_var[(bi1, bi2)])    # crossing iff bi1 before bi2
                else:
                    lits.append(-order_var[(bi2, bi1)])   # crossing iff NOT(bi2 before bi1)
    return lits


def build_transitivity_clauses(n, order_var):
    """Two clauses per triple enforce a consistent total order."""
    clauses = []
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                vij = order_var[(i, j)]
                vjk = order_var[(j, k)]
                vik = order_var[(i, k)]
                # x_{i,j} AND x_{j,k} => x_{i,k}
                clauses.append([-vij, -vjk, vik])
                # x_{i,k} => x_{i,j} OR x_{j,k}
                clauses.append([-vik, vij, vjk])
    return clauses


def sequential_counter_atmost(lits, k, next_var):
    """Encode 'at most k of lits are true' via the sequential counter (Sinz 2005).

    Uses O(n*k) auxiliary register variables and O(n*k) clauses.
    Returns (new_clauses, next_available_variable_id).
    """
    n = len(lits)
    if k >= n:
        return [], next_var
    if k == 0:
        return [[-l] for l in lits], next_var

    # Register variables r[i][j] for i in 0..n-1, j in 0..k-1
    r = [[0] * k for _ in range(n)]
    for i in range(n):
        for j in range(k):
            r[i][j] = next_var
            next_var += 1

    clauses = []

    # First input (i=0)
    clauses.append([-lits[0], r[0][0]])
    for j in range(1, k):
        clauses.append([-r[0][j]])

    # Subsequent inputs (i=1..n-1)
    for i in range(1, n):
        xi = lits[i]
        # If xi fires, at least 1 among first i+1
        clauses.append([-xi, r[i][0]])
        # Monotonicity: count from first i carries forward
        clauses.append([-r[i - 1][0], r[i][0]])

        for j in range(1, k):
            # If xi fires and count was >=j among first i, count is >=j+1 among first i+1
            clauses.append([-xi, -r[i - 1][j - 1], r[i][j]])
            # Monotonicity
            clauses.append([-r[i - 1][j], r[i][j]])

        # Overflow: xi cannot fire if count already at k
        clauses.append([-xi, -r[i - 1][k - 1]])

    return clauses, next_var


def write_dimacs(path, num_vars, clauses):
    with open(path, 'w') as f:
        f.write(f"p cnf {num_vars} {len(clauses)}\n")
        for c in clauses:
            f.write(' '.join(str(l) for l in c) + ' 0\n')


def run_minisat(cnf_path, sol_path):
    """Run MiniSat on a DIMACS CNF file. Returns assignment dict or None."""
    try:
        subprocess.run(
            ['minisat', cnf_path, sol_path],
            capture_output=True, timeout=180
        )
    except subprocess.TimeoutExpired:
        return None

    if not os.path.exists(sol_path):
        return None

    with open(sol_path) as f:
        lines = f.readlines()

    if not lines or lines[0].strip() != 'SAT':
        return None

    assignment = {}
    for line in lines[1:]:
        for tok in line.split():
            lit = int(tok)
            if lit == 0:
                break
            assignment[abs(lit)] = (lit > 0)
    return assignment


def reconstruct_order(assignment, n, order_var, b_vertices):
    """Reconstruct B-vertex ordering from SAT variable assignment."""
    indices = list(range(n))

    def cmp(a, b):
        if a == b:
            return 0
        i, j = min(a, b), max(a, b)
        val = assignment.get(order_var[(i, j)], True)
        return (-1 if val else 1) if a < b else (1 if val else -1)

    indices.sort(key=cmp_to_key(cmp))
    return [b_vertices[i] for i in indices]


def count_crossings(edges, order):
    pos = {v: i for i, v in enumerate(order)}
    c = 0
    for i in range(len(edges)):
        a1, b1 = edges[i]
        for j in range(i + 1, len(edges)):
            a2, b2 = edges[j]
            if a1 == a2 or b1 == b2:
                continue
            if (a1 < a2 and pos[b1] > pos[b2]) or (a1 > a2 and pos[b1] < pos[b2]):
                c += 1
    return c


def solve_instance(inst_path, sat_dir):
    name = os.path.splitext(os.path.basename(inst_path))[0]
    n0, n1, edges = parse_instance(inst_path)
    n = n1
    b_vertices = list(range(n0 + 1, n0 + n1 + 1))

    # Create ordering variables (1-based for DIMACS)
    var_count = 0
    order_var = {}
    for i in range(n):
        for j in range(i + 1, n):
            var_count += 1
            order_var[(i, j)] = var_count

    cross_lits = build_crossing_literals(n0, n1, edges, order_var)
    base_clauses = build_transitivity_clauses(n, order_var)

    # Upper bound from identity vs reverse ordering
    id_cross = sum(1 for l in cross_lits if l > 0)
    rev_cross = len(cross_lits) - id_cross
    if id_cross <= rev_cross:
        upper = id_cross
        best_assign = {v: True for v in range(1, var_count + 1)}
    else:
        upper = rev_cross
        best_assign = {v: False for v in range(1, var_count + 1)}

    lower = 0

    # Binary search for optimal crossing number
    while lower < upper:
        mid = (lower + upper) // 2
        clauses = list(base_clauses)
        nv = var_count
        cc, nv = sequential_counter_atmost(cross_lits, mid, nv + 1)
        clauses.extend(cc)

        cnf_tmp = os.path.join(sat_dir, f"{name}_tmp.cnf")
        sol_tmp = os.path.join(sat_dir, f"{name}_tmp.sol")
        write_dimacs(cnf_tmp, nv, clauses)
        result = run_minisat(cnf_tmp, sol_tmp)

        if result is not None:
            upper = mid
            best_assign = result
        else:
            lower = mid + 1

    # Save final CNF (at-most-upper, which is SAT)
    final_clauses = list(base_clauses)
    nv = var_count
    cc, nv = sequential_counter_atmost(cross_lits, upper, nv + 1)
    final_clauses.extend(cc)
    write_dimacs(os.path.join(sat_dir, f"{name}.cnf"), nv, final_clauses)

    # Clean up temp files
    for suffix in ('_tmp.cnf', '_tmp.sol'):
        p = os.path.join(sat_dir, f"{name}{suffix}")
        if os.path.exists(p):
            os.remove(p)

    order = reconstruct_order(best_assign, n, order_var, b_vertices)
    crossings = count_crossings(edges, order)
    return order, crossings


def main():
    inst_dir = '/app/instances'
    sat_dir = '/app/sat'
    out_dir = '/app/output'
    os.makedirs(sat_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    results = {}
    for fname in sorted(os.listdir(inst_dir)):
        if not fname.endswith('.gr'):
            continue
        name = fname[:-3]
        path = os.path.join(inst_dir, fname)
        print(f"SAT: {name} ...", end=' ', flush=True)
        order, crossings = solve_instance(path, sat_dir)
        results[name] = crossings

        with open(os.path.join(out_dir, f"{name}.sol"), 'w') as f:
            for v in order:
                f.write(f"{v}\n")
        print(f"crossings={crossings}")

    with open('/app/sat_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("SAT solving complete.")


if __name__ == '__main__':
    main()
