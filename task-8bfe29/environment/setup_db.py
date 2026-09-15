#!/usr/bin/env python3
"""Create reference SQLite database for LABS optimization framework."""

import sqlite3
import json

DB_PATH = "/app/data/reference.db"


def create_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Known optimal energies
    c.execute("""CREATE TABLE known_optima (
        N INTEGER PRIMARY KEY,
        optimal_energy INTEGER,
        merit_factor REAL
    )""")
    optima = [
        (3, 1, 4.5),
        (4, 2, 4.0),
        (5, 2, 6.25),
        (7, 3, 8.166666666666666),
        (11, 5, 12.1),
        (13, 6, 14.083333333333334),
        (21, 26, 8.480769230769230),
    ]
    c.executemany("INSERT INTO known_optima VALUES (?, ?, ?)", optima)

    # Interaction set sizes and Gamma1
    c.execute("""CREATE TABLE interaction_counts (
        N INTEGER PRIMARY KEY,
        g2_size INTEGER,
        g4_size INTEGER,
        gamma1 INTEGER
    )""")
    counts = [
        (4, 2, 1, 320),
        (5, 4, 3, 896),
        (6, 6, 7, 1984),
        (7, 9, 13, 3616),
        (8, 12, 22, 6016),
        (9, 16, 34, 9216),
        (10, 20, 50, 13440),
    ]
    c.executemany("INSERT INTO interaction_counts VALUES (?, ?, ?, ?)", counts)

    # Exact G2 indices for small N (JSON-encoded lists of pairs)
    c.execute("""CREATE TABLE g2_exact (
        N INTEGER PRIMARY KEY,
        pairs_json TEXT
    )""")
    g2_n5 = [[0, 1], [0, 2], [1, 2], [2, 3]]
    g2_n6 = [[0, 1], [0, 2], [1, 2], [1, 3], [2, 3], [3, 4]]
    c.execute("INSERT INTO g2_exact VALUES (?, ?)", (5, json.dumps(g2_n5)))
    c.execute("INSERT INTO g2_exact VALUES (?, ?)", (6, json.dumps(g2_n6)))

    # Exact G4 indices for small N (JSON-encoded lists of quadruples)
    c.execute("""CREATE TABLE g4_exact (
        N INTEGER PRIMARY KEY,
        quads_json TEXT
    )""")
    g4_n4 = [[0, 1, 2, 3]]
    g4_n5 = [[0, 1, 2, 3], [0, 1, 3, 4], [1, 2, 3, 4]]
    g4_n6 = [
        [0, 1, 2, 3], [0, 1, 3, 4], [0, 1, 4, 5],
        [0, 2, 3, 5], [1, 2, 3, 4], [1, 2, 4, 5], [2, 3, 4, 5],
    ]
    c.execute("INSERT INTO g4_exact VALUES (?, ?)", (4, json.dumps(g4_n4)))
    c.execute("INSERT INTO g4_exact VALUES (?, ?)", (5, json.dumps(g4_n5)))
    c.execute("INSERT INTO g4_exact VALUES (?, ?)", (6, json.dumps(g4_n6)))

    # Theta reference values
    c.execute("""CREATE TABLE theta_reference (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        N INTEGER,
        t REAL,
        dt REAL,
        total_time REAL,
        theta_value REAL
    )""")
    theta_vals = [
        (5, 0.3333333333333333, 0.3333333333333333, 1.0, 0.0199632005),
        (5, 0.6666666666666666, 0.3333333333333333, 1.0, 0.0067391696),
        (5, 1.0, 0.3333333333333333, 1.0, 0.0),
        (7, 0.3333333333333333, 0.3333333333333333, 1.0, 0.0187622966),
    ]
    c.executemany(
        "INSERT INTO theta_reference (N, t, dt, total_time, theta_value) VALUES (?, ?, ?, ?, ?)",
        theta_vals,
    )

    # Gamma2 reference values
    c.execute("""CREATE TABLE gamma2_reference (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        N INTEGER,
        lambda_val REAL,
        gamma2_value REAL
    )""")
    c.execute(
        "INSERT INTO gamma2_reference (N, lambda_val, gamma2_value) VALUES (?, ?, ?)",
        (5, 0.25, -20352.0),
    )

    # Energy examples for validation
    c.execute("""CREATE TABLE energy_examples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sequence_json TEXT,
        energy INTEGER,
        description TEXT
    )""")
    examples = [
        ("[1,-1,-1]", 1, "N=3 optimal"),
        ("[1,-1,1,1,1]", 2, "N=5 optimal"),
        ("[1,-1,1,1,-1,-1,-1]", 3, "N=7 optimal"),
        ("[1,1,1]", 5, "N=3 all-positive"),
        ("[1,1,-1,-1]", 6, "N=4 non-optimal"),
        ("[1,1,1,-1]", 2, "N=4 optimal"),
        ("[1,-1,1,1,-1,1,1,1,-1,-1,-1]", 5, "N=11 optimal"),
    ]
    c.executemany(
        "INSERT INTO energy_examples (sequence_json, energy, description) VALUES (?, ?, ?)",
        examples,
    )

    # Autocorrelation coefficient examples
    c.execute("""CREATE TABLE autocorrelation_examples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sequence_json TEXT,
        k INTEGER,
        c_value INTEGER
    )""")
    auto_examples = [
        ("[1,-1,-1,1,-1]", 1, -2),
        ("[1,-1,-1,1,-1]", 2, -1),
        ("[1,-1,-1,1,-1]", 3, 2),
        ("[1,-1,-1,1,-1]", 4, -1),
    ]
    c.executemany(
        "INSERT INTO autocorrelation_examples (sequence_json, k, c_value) VALUES (?, ?, ?)",
        auto_examples,
    )

    conn.commit()
    conn.close()
    print(f"Created reference database at {DB_PATH}")


if __name__ == "__main__":
    create_database()
