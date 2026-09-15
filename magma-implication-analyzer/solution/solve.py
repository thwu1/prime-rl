#!/usr/bin/env python3
"""
Solution for the magma equational theory audit task.

Parses Prover9-format equations, enumerates all magmas of orders 1-3,
verifies every implication claim, identifies errors in the claimed matrix,
finds counterexamples, computes the Hasse diagram, and renders it via Graphviz.
"""

import json
import csv
import os
import subprocess
from itertools import product


# --- Prover9-format equation parser ---

def parse_equations(filepath):
    """Parse equations from Prover9-style notation file."""
    equations = []
    with open(filepath) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('%'):
                continue
            colon_pos = line.index(':')
            eq_id = int(line[:colon_pos].strip())
            body = line[colon_pos + 1:].strip().rstrip('.')
            lhs_str, rhs_str = body.split(' = ', 1)
            lhs = _parse_expr(lhs_str.strip())
            rhs = _parse_expr(rhs_str.strip())
            equations.append((eq_id, lhs, rhs))
    return equations


def _parse_expr(s):
    """Recursively parse 'f(x,f(y,z))' into a nested tuple tree."""
    s = s.strip()
    if s.startswith('f('):
        inner = s[2:-1]
        depth = 0
        for i, c in enumerate(inner):
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            elif c == ',' and depth == 0:
                left = _parse_expr(inner[:i])
                right = _parse_expr(inner[i + 1:])
                return ('op', left, right)
        raise ValueError(f"Could not parse: {s}")
    else:
        return ('var', s)


# --- Magma evaluation ---

def _collect_vars(expr):
    """Collect all variable names from an expression tree."""
    if expr[0] == 'var':
        return {expr[1]}
    return _collect_vars(expr[1]) | _collect_vars(expr[2])


def _eval_expr(expr, assignment, table, n):
    """Evaluate an expression given a variable assignment and magma table."""
    if expr[0] == 'var':
        return assignment[expr[1]]
    left_val = _eval_expr(expr[1], assignment, table, n)
    right_val = _eval_expr(expr[2], assignment, table, n)
    return table[left_val * n + right_val]


def check_equation(eq, table, n):
    """Check if equation holds universally on a magma of order n."""
    _, lhs, rhs = eq
    variables = sorted(_collect_vars(lhs) | _collect_vars(rhs))
    for vals in product(range(n), repeat=len(variables)):
        assignment = dict(zip(variables, vals))
        if _eval_expr(lhs, assignment, table, n) != \
           _eval_expr(rhs, assignment, table, n):
            return False
    return True


# --- Main analysis ---

def main():
    equations = parse_equations("/app/analysis/equations.p")
    num_eq = len(equations)

    # Initialize implication tracking
    implication_holds = {}
    counterexamples = {}
    for i in range(1, num_eq + 1):
        for j in range(1, num_eq + 1):
            implication_holds[(i, j)] = True

    print("Enumerating magmas and checking equations...")
    for n in [1, 2, 3]:
        total = n ** (n * n)
        print(f"  Order {n}: {total} magmas")
        count = 0
        for table_tuple in product(range(n), repeat=n * n):
            table = list(table_tuple)
            satisfies = {}
            for eq in equations:
                eid = eq[0]
                satisfies[eid] = check_equation(eq, table, n)

            for i in range(1, num_eq + 1):
                if satisfies[i]:
                    for j in range(1, num_eq + 1):
                        if i != j and not satisfies[j]:
                            key = f"{i},{j}"
                            if key not in counterexamples:
                                counterexamples[key] = {
                                    "order": n,
                                    "table": list(table_tuple)
                                }
                            implication_holds[(i, j)] = False

            count += 1
            if count % 5000 == 0:
                print(f"    {count}/{total}")

    # Build corrected implication matrix
    print("Building corrected implication matrix...")
    imp_matrix = []
    for i in range(1, num_eq + 1):
        row = []
        for j in range(1, num_eq + 1):
            row.append(1 if implication_holds[(i, j)] else 0)
        imp_matrix.append(row)

    # Load claimed matrix and identify errors
    print("Loading claimed matrix and identifying errors...")
    with open("/app/analysis/claimed_implications.csv") as fh:
        reader = csv.reader(fh)
        claimed = [[int(x) for x in row] for row in reader if row]

    errors = []
    for i in range(12):
        for j in range(12):
            if imp_matrix[i][j] != claimed[i][j]:
                errors.append({
                    "row": i + 1,
                    "col": j + 1,
                    "claimed": claimed[i][j],
                    "correct": imp_matrix[i][j]
                })

    print(f"Found {len(errors)} errors in claimed matrix:")
    for e in errors:
        kind = "false positive" if e["claimed"] == 1 else "false negative"
        print(f"  E{e['row']} -> E{e['col']}: {kind}")

    # Compute Hasse diagram (transitive reduction)
    print("Computing Hasse diagram (transitive reduction)...")
    hasse_edges = []
    for i in range(1, num_eq + 1):
        for j in range(1, num_eq + 1):
            if i != j and implication_holds[(i, j)]:
                is_cover = True
                for k in range(1, num_eq + 1):
                    if k != i and k != j:
                        if implication_holds[(i, k)] and \
                           implication_holds[(k, j)]:
                            is_cover = False
                            break
                if is_cover:
                    hasse_edges.append((i, j))

    # Write all output files
    os.makedirs("/app/results", exist_ok=True)

    with open("/app/results/corrected_matrix.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        for row in imp_matrix:
            writer.writerow(row)

    with open("/app/results/counterexamples.json", "w") as fh:
        json.dump(counterexamples, fh, indent=2)

    with open("/app/results/error_report.json", "w") as fh:
        json.dump(errors, fh, indent=2)

    # Generate Graphviz DOT file
    with open("/app/results/hasse.dot", "w") as fh:
        fh.write("digraph hasse {\n")
        fh.write("    rankdir=BT;\n")
        fh.write("    node [shape=ellipse];\n")
        for i in range(1, num_eq + 1):
            fh.write(f"    E{i};\n")
        for src, dst in hasse_edges:
            fh.write(f"    E{src} -> E{dst};\n")
        fh.write("}\n")

    # Render PNG from DOT
    subprocess.run(
        ["dot", "-Tpng", "/app/results/hasse.dot",
         "-o", "/app/results/hasse.png"],
        check=True
    )

    # Summary
    total_impl = sum(
        1 for i in range(1, num_eq + 1)
        for j in range(1, num_eq + 1)
        if i != j and implication_holds[(i, j)]
    )
    print(f"\nResults written to /app/results/")
    print(f"  Non-trivial implications: {total_impl}")
    print(f"  Non-implications (counterexamples): {len(counterexamples)}")
    print(f"  Hasse diagram edges: {len(hasse_edges)}")
    print(f"  Errors in claimed matrix: {len(errors)}")


if __name__ == "__main__":
    main()
