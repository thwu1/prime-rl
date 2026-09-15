#!/usr/bin/env python3

"""
OCM solver pipeline: PACE .gr instances -> CPLEX LP -> glpsol -> solutions -> SQLite

Formulates the One-Sided Crossing Minimization problem as an Integer Linear
Program using binary ordering variables and transitivity (3-dicycle) constraints,
solves via glpsol, and stores results in a SQLite database.
"""

import os
import glob
import subprocess
import sqlite3
import re
import sys


def parse_instance(filepath):
    """Parse a .gr file in PACE OCR format."""
    n0 = n1 = m = 0
    edges = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                parts = line.split()
                n0, n1, m = int(parts[2]), int(parts[3]), int(parts[4])
            else:
                parts = line.split()
                edges.append((int(parts[0]), int(parts[1])))
    return n0, n1, edges


def compute_pairwise_crossings(n0, n1, edges):
    """
    For each ordered pair (i, j) of B-vertices, compute the number of
    edge crossings when i is placed immediately before j in the ordering.
    cross[(i,j)] = |{(a1,a2) : a1 in N(i), a2 in N(j), a1 > a2}|
    """
    B = list(range(n0 + 1, n0 + n1 + 1))
    adj = {b: [] for b in B}
    for a, b in edges:
        adj[b].append(a)

    cross = {}
    for i in B:
        for j in B:
            if i != j:
                c = 0
                for a_i in adj[i]:
                    for a_j in adj[j]:
                        if a_i > a_j:
                            c += 1
                cross[(i, j)] = c
    return B, cross


def write_lp_file(B, cross, lp_path):
    """
    Write the OCM ILP in CPLEX LP format.

    Variables: x_i_j (for i < j among B-vertices), binary.
      x_i_j = 1  means vertex i is placed before vertex j.
      x_i_j = 0  means vertex j is placed before vertex i.

    Objective: minimize total crossings.
      For each pair (i,j) with i<j, crossing contribution =
        cross[(i,j)]*x_ij + cross[(j,i)]*(1-x_ij)
      = cross[(j,i)] + (cross[(i,j)] - cross[(j,i)])*x_ij
      Constant term dropped; only variable part in objective.

    Constraints: transitivity (3-dicycle elimination).
      For each triple a < b < c:
        x_ab + x_bc - x_ac <= 1
       -x_ab - x_bc + x_ac <= 0
    """
    pairs = [(i, j) for i in B for j in B if i < j]

    with open(lp_path, "w") as f:
        f.write(f"\\Problem: OCM_{B[0]}_{B[-1]}\n")

        # Objective
        f.write("Minimize\n")
        terms = []
        for i, j in pairs:
            coeff = cross[(i, j)] - cross[(j, i)]
            if coeff != 0:
                terms.append((coeff, f"x_{i}_{j}"))

        f.write(" obj:")
        if not terms:
            # All crossing costs symmetric — any order is optimal
            f.write(f" 0 x_{B[0]}_{B[1]}")
        else:
            for idx, (coeff, var) in enumerate(terms):
                if idx == 0:
                    if coeff == 1:
                        f.write(f" {var}")
                    elif coeff == -1:
                        f.write(f" - {var}")
                    else:
                        f.write(f" {coeff} {var}")
                else:
                    if coeff == 1:
                        f.write(f" + {var}")
                    elif coeff == -1:
                        f.write(f" - {var}")
                    elif coeff > 0:
                        f.write(f" + {coeff} {var}")
                    else:
                        f.write(f" - {-coeff} {var}")
                if (idx + 1) % 5 == 0:
                    f.write("\n    ")
        f.write("\n")

        # Constraints: transitivity
        f.write("Subject To\n")
        cn = 0
        for a in B:
            for b in B:
                for c in B:
                    if a < b < c:
                        cn += 1
                        f.write(
                            f" c{cn}f: x_{a}_{b} + x_{b}_{c}"
                            f" - x_{a}_{c} <= 1\n"
                        )
                        cn += 1
                        f.write(
                            f" c{cn}r: - x_{a}_{b} - x_{b}_{c}"
                            f" + x_{a}_{c} <= 0\n"
                        )

        # Bounds
        f.write("Bounds\n")
        for i, j in pairs:
            f.write(f" 0 <= x_{i}_{j} <= 1\n")

        # Binary
        f.write("Binary\n")
        for i, j in pairs:
            f.write(f" x_{i}_{j}\n")

        f.write("End\n")


def solve_with_glpsol(lp_path, out_path):
    """Invoke glpsol on the LP file, writing solution to out_path."""
    result = subprocess.run(
        ["glpsol", "--lp", lp_path, "--output", out_path, "--tmlim", "300"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    return result.returncode, result.stdout, result.stderr


def parse_glpsol_output(out_path):
    """Parse glpsol --output file to extract variable values and status."""
    with open(out_path) as f:
        content = f.read()

    # Extract status
    status = "UNKNOWN"
    m = re.search(r"^Status:\s+(.+)$", content, re.MULTILINE)
    if m:
        status = m.group(1).strip()

    # Extract variable values from Column section
    # Lines look like:  NUM  x_i_j  *  ACTIVITY  LB  UB
    variables = {}
    col_re = re.compile(
        r"^\s*\d+\s+(x_\d+_\d+)\s+\S+\s+([\d.eE+\-]+)", re.MULTILINE
    )
    for m in col_re.finditer(content):
        name = m.group(1)
        activity = float(m.group(2))
        variables[name] = int(round(activity))

    return variables, status


def variables_to_permutation(variables, B):
    """Convert ILP solution to a vertex permutation.

    For each vertex v, rank = number of vertices that come before v.
    If x_i_j = 1 (i before j), rank(j) += 1. If x_i_j = 0, rank(i) += 1.
    Sort by rank to get the permutation.
    """
    rank = {v: 0 for v in B}
    for i in B:
        for j in B:
            if i < j:
                var = f"x_{i}_{j}"
                val = variables.get(var, 0)
                if val == 1:
                    rank[j] += 1
                else:
                    rank[i] += 1
    return sorted(B, key=lambda v: rank[v])


def count_crossings(edges, perm):
    """Count edge crossings for the given permutation of B."""
    pos = {v: i for i, v in enumerate(perm)}
    crossings = 0
    for i in range(len(edges)):
        a1, b1 = edges[i]
        for j in range(i + 1, len(edges)):
            a2, b2 = edges[j]
            if a1 == a2 or b1 == b2:
                continue
            if (a1 < a2 and pos[b1] > pos[b2]) or (
                a1 > a2 and pos[b1] < pos[b2]
            ):
                crossings += 1
    return crossings


def main():
    instances_dir = "/app/instances"
    models_dir = "/app/models"
    solutions_dir = "/app/solutions"
    db_path = "/app/results.db"

    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(solutions_dir, exist_ok=True)

    # Initialize SQLite database
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS instances (
            name TEXT PRIMARY KEY,
            n_a INTEGER NOT NULL,
            n_b INTEGER NOT NULL,
            n_edges INTEGER NOT NULL
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS solutions (
            instance_name TEXT PRIMARY KEY REFERENCES instances(name),
            crossings INTEGER NOT NULL,
            permutation TEXT NOT NULL,
            solve_status TEXT NOT NULL
        )"""
    )
    conn.commit()

    for inst_path in sorted(glob.glob(os.path.join(instances_dir, "*.gr"))):
        name = os.path.basename(inst_path).replace(".gr", "")
        lp_path = os.path.join(models_dir, f"{name}.lp")
        out_path = os.path.join(models_dir, f"{name}.out")
        sol_path = os.path.join(solutions_dir, f"{name}.sol")

        print(f"[{name}] Parsing...", file=sys.stderr)
        n0, n1, edges = parse_instance(inst_path)
        B, cross = compute_pairwise_crossings(n0, n1, edges)

        n_vars = len(B) * (len(B) - 1) // 2
        print(f"[{name}] Generating ILP: {n_vars} binary vars...", file=sys.stderr)
        write_lp_file(B, cross, lp_path)

        print(f"[{name}] Solving with glpsol...", file=sys.stderr)
        ret, stdout, stderr = solve_with_glpsol(lp_path, out_path)
        if ret != 0:
            print(f"[{name}] glpsol returned {ret}", file=sys.stderr)
            if stderr:
                print(stderr[:500], file=sys.stderr)

        print(f"[{name}] Parsing glpsol output...", file=sys.stderr)
        variables, status = parse_glpsol_output(out_path)
        perm = variables_to_permutation(variables, B)
        crossings = count_crossings(edges, perm)

        # Write PACE-format solution
        with open(sol_path, "w") as f:
            for v in perm:
                f.write(f"{v}\n")

        # Insert into SQLite
        perm_str = ",".join(str(v) for v in perm)
        cur.execute(
            "INSERT OR REPLACE INTO instances VALUES (?, ?, ?, ?)",
            (name, n0, n1, len(edges)),
        )
        cur.execute(
            "INSERT OR REPLACE INTO solutions VALUES (?, ?, ?, ?)",
            (name, crossings, perm_str, status),
        )
        conn.commit()

        print(
            f"[{name}] Done: {crossings} crossings, status={status}",
            file=sys.stderr,
        )

    conn.close()
    print("Pipeline complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
