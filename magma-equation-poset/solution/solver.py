#!/usr/bin/env python3

"""
Multi-tool equational theory lattice analyzer.
Uses Z3 for counterexample finding, enumerates and classifies magmas
under Sym(3), renders Hasse diagram via Graphviz, stores results in SQLite.
"""

import json
import itertools
import os
import sqlite3
import subprocess
from z3 import Int, IntVal, If, And, Or, Solver, sat


# ============================================================
# Core helpers
# ============================================================

def eval_term(term, env, table):
    """Recursively evaluate an AST term over a concrete magma table."""
    if isinstance(term, str):
        return env[term]
    left = eval_term(term["args"][0], env, table)
    right = eval_term(term["args"][1], env, table)
    return table[left][right]


def check_equation(eq, table):
    """Check whether a magma table universally satisfies an equation."""
    n = len(table)
    for assignment in itertools.product(range(n), repeat=len(eq["vars"])):
        env = dict(zip(eq["vars"], assignment))
        if eval_term(eq["lhs"], env, table) != eval_term(eq["rhs"], env, table):
            return False
    return True


# ============================================================
# Z3 counterexample finding
# ============================================================

def z3_encode_term(term, env, table_vars, n):
    """Encode AST term as Z3 expression with table lookup via If-Then-Else."""
    if isinstance(term, str):
        return env[term]
    left = z3_encode_term(term["args"][0], env, table_vars, n)
    right = z3_encode_term(term["args"][1], env, table_vars, n)
    # Build table lookup using nested If-Then-Else over all (i,j) pairs
    result = table_vars[0][0]
    for i in range(n):
        for j in range(n):
            result = If(And(left == i, right == j), table_vars[i][j], result)
    return result


def find_z3_counterexample(eq_a, eq_b, max_size=3):
    """Find minimal magma satisfying eq_a but not eq_b using Z3 SMT solver."""
    for n in range(2, max_size + 1):
        s = Solver()
        s.set("timeout", 30000)

        # Create operation table as integer variables
        table_vars = [[Int(f"t_{i}_{j}") for j in range(n)] for i in range(n)]
        for i in range(n):
            for j in range(n):
                s.add(table_vars[i][j] >= 0, table_vars[i][j] < n)

        # eq_a must hold universally: AND over all variable assignments
        for assignment in itertools.product(range(n), repeat=len(eq_a["vars"])):
            env = {v: IntVal(a) for v, a in zip(eq_a["vars"], assignment)}
            lhs = z3_encode_term(eq_a["lhs"], env, table_vars, n)
            rhs = z3_encode_term(eq_a["rhs"], env, table_vars, n)
            s.add(lhs == rhs)

        # eq_b must fail for at least one assignment: OR of violations
        violations = []
        for assignment in itertools.product(range(n), repeat=len(eq_b["vars"])):
            env = {v: IntVal(a) for v, a in zip(eq_b["vars"], assignment)}
            lhs = z3_encode_term(eq_b["lhs"], env, table_vars, n)
            rhs = z3_encode_term(eq_b["rhs"], env, table_vars, n)
            violations.append(lhs != rhs)
        s.add(Or(*violations))

        result = s.check()
        if result == sat:
            model = s.model()
            result_table = [
                [model.evaluate(table_vars[i][j]).as_long() for j in range(n)]
                for i in range(n)
            ]
            return {"size": n, "table": result_table}

    return None


# ============================================================
# Isomorphism classification under Sym(n)
# ============================================================

def canonical_form(table, n):
    """Compute canonical (lex-min) form of a magma table under Sym(n) action.

    The symmetric group acts on operation tables by:
      T'[sigma(i)][sigma(j)] = sigma(T[i][j])
    The canonical form is the lexicographically smallest flattened table
    across all permutations.
    """
    min_form = None
    for perm in itertools.permutations(range(n)):
        new_flat = [0] * (n * n)
        for i in range(n):
            for j in range(n):
                new_flat[perm[i] * n + perm[j]] = perm[table[i][j]]
        t = tuple(new_flat)
        if min_form is None or t < min_form:
            min_form = t
    return min_form


# ============================================================
# Main pipeline
# ============================================================

def main():
    with open("/app/equations.json") as f:
        equations = json.load(f)
    with open("/app/magmas.json") as f:
        magmas = json.load(f)

    os.makedirs("/app/results", exist_ok=True)
    eq_names = sorted(equations.keys())
    n = 3

    # ---- Step 1: Z3 counterexample finding ----
    print("=== Z3 Counterexample Search ===")
    z3_results = {}
    for ei in eq_names:
        for ej in eq_names:
            if ei == ej:
                continue
            key = f"{ei}->{ej}"
            print(f"  Z3: {key}...", end=" ", flush=True)
            result = find_z3_counterexample(equations[ei], equations[ej])
            z3_results[key] = result
            if result:
                print(f"counterexample size {result['size']}")
            else:
                print("implication holds")

    with open("/app/results/z3_counterexamples.json", "w") as f:
        json.dump(z3_results, f, indent=2)
    print(f"Z3: {sum(1 for v in z3_results.values() if v)} non-implications found\n")

    # ---- Step 2: Full enumeration + isomorphism classification ----
    print("=== Enumerating all 19683 size-3 magmas ===")
    counts = {e: 0 for e in eq_names}
    satisfying_sets = {e: set() for e in eq_names}
    iso_class_eq_sets = {e: set() for e in eq_names}
    all_iso_classes = set()

    for idx, flat in enumerate(itertools.product(range(n), repeat=n * n)):
        table = [list(flat[i * n:(i + 1) * n]) for i in range(n)]
        canon = canonical_form(table, n)
        all_iso_classes.add(canon)

        for ename in eq_names:
            if check_equation(equations[ename], table):
                counts[ename] += 1
                satisfying_sets[ename].add(idx)
                iso_class_eq_sets[ename].add(canon)

        if (idx + 1) % 5000 == 0:
            print(f"  Processed {idx + 1}/19683")

    total_iso_classes = len(all_iso_classes)
    iso_class_per_eq = {e: len(iso_class_eq_sets[e]) for e in eq_names}

    print(f"Total isomorphism classes: {total_iso_classes}")
    for e in eq_names:
        print(f"  {e}: {iso_class_per_eq[e]} classes, {counts[e]} tables")

    with open("/app/results/iso_classes.json", "w") as f:
        json.dump({
            "total_classes": total_iso_classes,
            "per_equation": iso_class_per_eq
        }, f, indent=2)

    # ---- Step 3: Implication matrix ----
    print("\n=== Computing implication matrix ===")
    implications = {}
    for ei in eq_names:
        for ej in eq_names:
            implications[f"{ei}->{ej}"] = satisfying_sets[ei].issubset(
                satisfying_sets[ej]
            )

    with open("/app/results/implications.json", "w") as f:
        json.dump(implications, f, indent=2)

    true_count = sum(1 for v in implications.values() if v)
    print(f"Implications: {true_count}/64 hold")

    # ---- Step 4: Hasse diagram (transitive reduction) ----
    print("\n=== Computing Hasse diagram ===")
    strict = {e: set() for e in eq_names}
    for ei in eq_names:
        for ej in eq_names:
            if ei != ej and implications[f"{ei}->{ej}"] \
               and not implications[f"{ej}->{ei}"]:
                strict[ei].add(ej)

    hasse = {}
    for ei in eq_names:
        hasse[ei] = []
        for ej in strict[ei]:
            redundant = any(
                ek in strict[ei] and ej in strict[ek]
                for ek in eq_names if ek != ei and ek != ej
            )
            if not redundant:
                hasse[ei].append(ej)
        hasse[ei].sort()

    with open("/app/results/hasse.json", "w") as f:
        json.dump(hasse, f, indent=2)
    print(f"Hasse edges: {sum(len(v) for v in hasse.values())}")

    # ---- Step 5: Graphviz SVG rendering ----
    print("\n=== Rendering Hasse diagram as SVG ===")
    dot_lines = [
        "digraph hasse {",
        "  rankdir=BT;",
        "  node [shape=box, style=rounded, fontname=\"Helvetica\"];",
        "  edge [color=\"#555555\"];",
    ]
    for ename in eq_names:
        display = equations[ename]["display"]
        label = f"{ename}\\n{display}"
        dot_lines.append(f'  {ename} [label="{label}"];')
    for ei in eq_names:
        for ej in hasse[ei]:
            dot_lines.append(f"  {ei} -> {ej};")
    dot_lines.append("}")

    dot_path = "/app/results/hasse.dot"
    svg_path = "/app/results/hasse.svg"
    with open(dot_path, "w") as f:
        f.write("\n".join(dot_lines) + "\n")

    subprocess.run(
        ["dot", "-Tsvg", "-o", svg_path, dot_path],
        check=True
    )
    svg_size = os.path.getsize(svg_path)
    print(f"SVG written: {svg_size} bytes")

    # ---- Step 6: SQLite database ----
    print("\n=== Creating SQLite database ===")
    db_path = "/app/results/magma_theory.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE equations (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        display TEXT NOT NULL,
        num_vars INTEGER NOT NULL
    )""")

    c.execute("""CREATE TABLE implications (
        premise_id TEXT NOT NULL,
        conclusion_id TEXT NOT NULL,
        holds INTEGER NOT NULL,
        counterexample_size INTEGER,
        counterexample_table TEXT,
        PRIMARY KEY (premise_id, conclusion_id)
    )""")

    c.execute("""CREATE TABLE iso_class_stats (
        equation_id TEXT PRIMARY KEY,
        num_satisfying_classes INTEGER NOT NULL,
        num_satisfying_tables INTEGER NOT NULL
    )""")

    # Populate equations
    for ename in eq_names:
        eq = equations[ename]
        c.execute(
            "INSERT INTO equations VALUES (?, ?, ?, ?)",
            (ename, eq["name"], eq["display"], len(eq["vars"]))
        )

    # Populate implications with Z3 counterexamples
    for ei in eq_names:
        for ej in eq_names:
            key = f"{ei}->{ej}"
            holds = 1 if implications[key] else 0
            cx = z3_results.get(key) if ei != ej else None
            cx_size = cx["size"] if cx else None
            cx_table = json.dumps(cx["table"]) if cx else None
            c.execute(
                "INSERT INTO implications VALUES (?, ?, ?, ?, ?)",
                (ei, ej, holds, cx_size, cx_table)
            )

    # Populate isomorphism class statistics
    for ename in eq_names:
        c.execute(
            "INSERT INTO iso_class_stats VALUES (?, ?, ?)",
            (ename, iso_class_per_eq[ename], counts[ename])
        )

    conn.commit()
    conn.close()
    print(f"Database written: {os.path.getsize(db_path)} bytes")

    print("\n=== Pipeline complete ===")


if __name__ == "__main__":
    main()
