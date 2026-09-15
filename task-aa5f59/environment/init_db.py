#!/usr/bin/env python3
"""Create the benchmarks SQLite database with property propagation rules,
transpose mappings, and empirical cost measurements for matrix multiplication
with structural properties."""

import sqlite3
import os

DB_PATH = "/app/input/benchmarks.db"


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ---- Property propagation rules ----
    c.execute("""CREATE TABLE propagation_rules (
        left_prop TEXT NOT NULL,
        right_prop TEXT NOT NULL,
        result_prop TEXT NOT NULL,
        PRIMARY KEY (left_prop, right_prop)
    )""")

    prop_rules = [
        ("diagonal", "diagonal", "diagonal"),
        ("upper_triangular", "upper_triangular", "upper_triangular"),
        ("lower_triangular", "lower_triangular", "lower_triangular"),
        ("diagonal", "upper_triangular", "upper_triangular"),
        ("diagonal", "lower_triangular", "lower_triangular"),
        ("upper_triangular", "diagonal", "upper_triangular"),
        ("lower_triangular", "diagonal", "lower_triangular"),
        ("diagonal", "symmetric", "general"),
        ("symmetric", "diagonal", "general"),
        ("diagonal", "general", "general"),
        ("general", "diagonal", "general"),
        ("symmetric", "general", "general"),
        ("general", "symmetric", "general"),
        ("symmetric", "symmetric", "general"),
        ("upper_triangular", "general", "general"),
        ("general", "upper_triangular", "general"),
        ("lower_triangular", "general", "general"),
        ("general", "lower_triangular", "general"),
        ("upper_triangular", "lower_triangular", "general"),
        ("lower_triangular", "upper_triangular", "general"),
        ("symmetric", "upper_triangular", "general"),
        ("upper_triangular", "symmetric", "general"),
        ("symmetric", "lower_triangular", "general"),
        ("lower_triangular", "symmetric", "general"),
        ("general", "general", "general"),
    ]
    c.executemany("INSERT INTO propagation_rules VALUES (?,?,?)", prop_rules)

    # ---- Transpose property mappings ----
    c.execute("""CREATE TABLE transpose_properties (
        original_prop TEXT PRIMARY KEY,
        transposed_prop TEXT NOT NULL
    )""")

    transpose_map = [
        ("symmetric", "symmetric"),
        ("upper_triangular", "lower_triangular"),
        ("lower_triangular", "upper_triangular"),
        ("diagonal", "diagonal"),
        ("general", "general"),
    ]
    c.executemany("INSERT INTO transpose_properties VALUES (?,?)", transpose_map)

    # ---- Empirical cost measurements ----
    # These encode the FLOP cost model for BLAS kernel selection:
    #   diagonal x diagonal   -> element-wise (k FLOPs)
    #   diagonal x any        -> row/col scaling (m*n FLOPs)
    #   any x diagonal        -> row/col scaling (m*n FLOPs)
    #   structured present    -> exploits structure (m*n*k FLOPs)
    #   general x general     -> standard DGEMM (2*m*n*k FLOPs)

    c.execute("""CREATE TABLE cost_measurements (
        left_prop TEXT NOT NULL,
        right_prop TEXT NOT NULL,
        m INTEGER NOT NULL,
        k INTEGER NOT NULL,
        n INTEGER NOT NULL,
        measured_cost INTEGER NOT NULL
    )""")

    # Three measurement points per combination using varied dimensions
    # Point sets: (m,k,n) = (10,20,30), (50,100,200), (8,15,25)
    dims = [(10, 20, 30), (50, 100, 200), (8, 15, 25)]

    properties = ["general", "symmetric", "upper_triangular",
                  "lower_triangular", "diagonal"]
    structured = {"symmetric", "upper_triangular", "lower_triangular"}

    measurements = []
    for lp in properties:
        for rp in properties:
            for m, k, n in dims:
                if lp == "diagonal" and rp == "diagonal":
                    cost = k
                elif lp == "diagonal":
                    cost = m * n
                elif rp == "diagonal":
                    cost = m * n
                elif lp in structured or rp in structured:
                    cost = m * n * k
                else:
                    cost = 2 * m * n * k
                measurements.append((lp, rp, m, k, n, cost))

    c.executemany(
        "INSERT INTO cost_measurements VALUES (?,?,?,?,?,?)", measurements
    )

    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH} with {len(measurements)} "
          f"cost measurements, {len(prop_rules)} propagation rules, "
          f"and {len(transpose_map)} transpose mappings")


if __name__ == "__main__":
    main()
