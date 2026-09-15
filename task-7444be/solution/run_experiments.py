"""Run optimizer on three GMPB instances, log to SQLite, write results.json."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, '/app')

import numpy as np
from gmpb import GMPB
from optimizer import run_optimizer

CONFIGS = {
    "F1": {"num_peaks": 10, "dimension": 5, "change_frequency": 5000,
            "shift_severity": 1.0, "num_environments": 30, "seed": 42},
    "F2": {"num_peaks": 10, "dimension": 5, "change_frequency": 1000,
            "shift_severity": 1.0, "num_environments": 30, "seed": 123},
    "F3": {"num_peaks": 10, "dimension": 10, "change_frequency": 5000,
            "shift_severity": 2.0, "num_environments": 30, "seed": 456},
}

DB_PATH = '/app/results.db'
JSON_PATH = '/app/results.json'


def setup_database(db_path):
    """Create the SQLite database and env_results table."""
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE env_results (
            instance TEXT NOT NULL,
            env_id INTEGER NOT NULL,
            mean_error REAL NOT NULL,
            best_found REAL NOT NULL,
            PRIMARY KEY (instance, env_id)
        )
    """)
    conn.commit()
    return conn


def run_with_tracking(gmpb, instance_name, conn):
    """Run optimizer while tracking per-environment error for SQLite."""
    # Wrap evaluate to intercept per-evaluation data
    original_evaluate = gmpb.evaluate
    current_env = [gmpb.get_environment()]
    env_errors = []
    best_found = [-1e300]

    def tracked_evaluate(x):
        # Get optimum BEFORE evaluate (before potential env change)
        optimum = gmpb.optimum
        prev_env = gmpb.get_environment()

        val = original_evaluate(x)
        new_env = gmpb.get_environment()

        if val > best_found[0]:
            best_found[0] = val
        error = max(0.0, optimum - best_found[0])
        env_errors.append(error)

        if new_env != prev_env:
            # Save completed environment data
            mean_err = sum(env_errors) / len(env_errors)
            conn.execute(
                "INSERT INTO env_results VALUES (?, ?, ?, ?)",
                (instance_name, prev_env, mean_err, best_found[0]))
            env_errors.clear()
            best_found[0] = -1e300
            current_env[0] = new_env

        return val

    gmpb.evaluate = tracked_evaluate

    np.random.seed(CONFIGS[instance_name]["seed"] + 1000)
    oe = run_optimizer(gmpb)

    # Save final environment
    if env_errors:
        mean_err = sum(env_errors) / len(env_errors)
        conn.execute(
            "INSERT INTO env_results VALUES (?, ?, ?, ?)",
            (instance_name, current_env[0], mean_err, best_found[0]))

    conn.commit()
    return oe


def main():
    conn = setup_database(DB_PATH)
    results = {}

    for name in sorted(CONFIGS):
        config = CONFIGS[name]
        gmpb = GMPB(**config)
        oe = run_with_tracking(gmpb, name, conn)

        # Verify with SQL
        cursor = conn.execute(
            "SELECT AVG(mean_error) FROM env_results WHERE instance = ?",
            (name,))
        sql_oe = cursor.fetchone()[0]

        results[name] = {"offline_error": round(sql_oe, 6)}
        print(f"{name}: C-lib offline_error = {oe:.6f}, "
              f"SQL offline_error = {sql_oe:.6f}")

    conn.close()

    with open(JSON_PATH, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {JSON_PATH}")
    print(f"SQLite database at {DB_PATH}")


if __name__ == '__main__':
    main()
