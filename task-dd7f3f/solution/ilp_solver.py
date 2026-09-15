#!/usr/bin/env python3

"""
ILP-based exact solver for One-Sided Crossing Minimization using GLPK (glpsol).

Formulation:
  - Binary ordering variables x_{i,j} for each pair of B-vertices (i<j).
    x_{i,j} = 1 means vertex i is placed before vertex j.
  - Transitivity inequalities enforce a consistent total order:
      x_{i,j} + x_{j,k} - x_{i,k} <= 1
      x_{i,k} - x_{i,j} - x_{j,k} <= 0
  - Binary crossing indicator variables c_p for each edge pair p.
    Linking constraints tie c_p to the ordering variable that determines
    whether the pair crosses.
  - Objective: minimize sum of c_p.
  - Model written in CPLEX LP format, solved by glpsol --lp.
"""

import os
import re
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


def solve_instance(inst_path, ilp_dir, out_dir):
    name = os.path.splitext(os.path.basename(inst_path))[0]
    n0, n1, edges = parse_instance(inst_path)
    n = n1
    b_vertices = list(range(n0 + 1, n0 + n1 + 1))
    b_idx = {v: i for i, v in enumerate(b_vertices)}

    # Identify all crossing edge pairs
    crossing_pairs = []
    for ei in range(len(edges)):
        a1, b1 = edges[ei]
        bi1 = b_idx[b1]
        for ej in range(ei + 1, len(edges)):
            a2, b2 = edges[ej]
            bi2 = b_idx[b2]
            if a1 == a2 or bi1 == bi2:
                continue
            crossing_pairs.append((a1, bi1, a2, bi2))

    lp_path = os.path.join(ilp_dir, f"{name}.lp")
    mip_sol_path = os.path.join(ilp_dir, f"{name}_mip.txt")

    # --- Write CPLEX LP file ---
    with open(lp_path, 'w') as f:
        f.write(f"\\Problem name: OSCM_{name}\n\n")
        f.write("Minimize\n")
        if crossing_pairs:
            f.write(f" obj: c0\n")
            for idx in range(1, len(crossing_pairs)):
                f.write(f" + c{idx}\n")
        else:
            f.write(f" obj: 0 x0v1\n")
        f.write("\n")

        f.write("Subject To\n")
        cidx = 0

        # Transitivity constraints
        for i in range(n):
            for j in range(i + 1, n):
                for k in range(j + 1, n):
                    cidx += 1
                    f.write(f" t{cidx}a: x{i}v{j} + x{j}v{k} - x{i}v{k} <= 1\n")
                    cidx += 1
                    f.write(f" t{cidx}b: x{i}v{k} - x{i}v{j} - x{j}v{k} <= 0\n")

        # Crossing linking constraints
        for idx, (a1, bi1, a2, bi2) in enumerate(crossing_pairs):
            cidx += 1
            if a1 < a2:
                if bi1 < bi2:
                    # crossing iff x_{bi1,bi2} = 0  =>  c = 1 - x
                    f.write(f" lk{cidx}: c{idx} + x{bi1}v{bi2} = 1\n")
                else:
                    # crossing iff x_{bi2,bi1} = 1  =>  c = x
                    f.write(f" lk{cidx}: c{idx} - x{bi2}v{bi1} = 0\n")
            else:
                if bi1 < bi2:
                    # crossing iff x_{bi1,bi2} = 1  =>  c = x
                    f.write(f" lk{cidx}: c{idx} - x{bi1}v{bi2} = 0\n")
                else:
                    # crossing iff x_{bi2,bi1} = 0  =>  c = 1 - x
                    f.write(f" lk{cidx}: c{idx} + x{bi2}v{bi1} = 1\n")

        f.write("\nBounds\n")
        for i in range(n):
            for j in range(i + 1, n):
                f.write(f" 0 <= x{i}v{j} <= 1\n")
        for idx in range(len(crossing_pairs)):
            f.write(f" 0 <= c{idx} <= 1\n")

        f.write("\nBinaries\n")
        for i in range(n):
            for j in range(i + 1, n):
                f.write(f" x{i}v{j}\n")
        for idx in range(len(crossing_pairs)):
            f.write(f" c{idx}\n")

        f.write("\nEnd\n")

    # --- Solve with glpsol ---
    result = subprocess.run(
        ['glpsol', '--lp', lp_path, '--write', mip_sol_path],
        capture_output=True, text=True, timeout=300
    )

    if result.returncode != 0:
        print(f"  glpsol error: {result.stderr[:200]}", file=sys.stderr)

    # --- Parse MIP solution ---
    objective, var_vals = parse_mip_solution(mip_sol_path)

    # Reconstruct ordering from x variables
    order_indices = list(range(n))

    def cmp(a, b):
        if a == b:
            return 0
        i, j = min(a, b), max(a, b)
        key = f"x{i}v{j}"
        val = var_vals.get(key, 0.5) > 0.5
        return (-1 if val else 1) if a < b else (1 if val else -1)

    order_indices.sort(key=cmp_to_key(cmp))
    order = [b_vertices[i] for i in order_indices]
    crossings = count_crossings(edges, order)

    # Write ILP solution for comparison
    with open(os.path.join(out_dir, f"{name}.ilp_sol"), 'w') as f:
        for v in order:
            f.write(f"{v}\n")

    return crossings


def parse_mip_solution(path):
    """Parse GLPK MIP solution file (from --write)."""
    objective = None
    var_vals = {}

    if not os.path.exists(path):
        return objective, var_vals

    with open(path) as f:
        content = f.read()

    # Objective value
    obj_match = re.search(r'obj\s*=\s*([\d.eE+\-]+)', content)
    if obj_match:
        objective = float(obj_match.group(1))

    # Variable values from the Columns section
    parsing = False
    for line in content.split('\n'):
        if 'Column name' in line:
            parsing = True
            continue
        if parsing and '---' in line:
            continue
        if parsing and line.strip() == '':
            parsing = False
            continue
        if parsing:
            parts = line.split()
            if len(parts) >= 4:
                try:
                    name = parts[1]
                    activity = float(parts[3])
                    var_vals[name] = activity
                except (ValueError, IndexError):
                    continue

    return objective, var_vals


import sys


def main():
    inst_dir = '/app/instances'
    ilp_dir = '/app/ilp'
    out_dir = '/app/output'
    os.makedirs(ilp_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    results = {}
    for fname in sorted(os.listdir(inst_dir)):
        if not fname.endswith('.gr'):
            continue
        name = fname[:-3]
        path = os.path.join(inst_dir, fname)
        print(f"ILP: {name} ...", end=' ', flush=True)
        crossings = solve_instance(path, ilp_dir, out_dir)
        results[name] = crossings
        print(f"crossings={crossings}")

    with open('/app/ilp_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("ILP solving complete.")


if __name__ == '__main__':
    main()
