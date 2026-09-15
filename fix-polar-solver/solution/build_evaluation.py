#!/usr/bin/env python3

"""
Evaluation pipeline for polar decomposition configurations.
Extracts configs, benchmarks against test matrices, performs stability
analysis, stores results in SQLite, and produces a ranked JSON report.
"""

import json
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, "/app")
from polar_solver import (
    standard_newton_schulz,
    gram_newton_schulz,
    simulate_eigenvalue_evolution,
    stability_metric,
    find_optimal_restarts,
    compute_polar_error,
)


def extract_coefficients(config_path):
    """Extract coefficient list from a nested config JSON file."""
    with open(config_path) as f:
        config = json.load(f)
    iterations = config["parameters"]["iterations"]
    return [
        [it["coefficients"]["a"], it["coefficients"]["b"], it["coefficients"]["c"]]
        for it in sorted(iterations, key=lambda x: x["step"])
    ]


def load_matrix_specs(path="/app/matrix_specs.json"):
    """Load matrix specifications."""
    with open(path) as f:
        return json.load(f)


def generate_matrix(spec):
    """Generate a matrix from a specification with fixed seed."""
    np.random.seed(spec["seed"])
    return np.random.randn(spec["rows"], spec["cols"])


def create_database(db_path, schema_path):
    """Create the SQLite database from the provided schema."""
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    with open(schema_path) as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def run_evaluation():
    """Run the full evaluation pipeline."""
    specs = load_matrix_specs()
    db_path = "/app/benchmark.db"
    schema_path = "/app/benchmark_schema.sql"

    conn = create_database(db_path, schema_path)
    cursor = conn.cursor()

    # Discover and load all configs
    config_dir = "/app/configs"
    config_files = sorted(f for f in os.listdir(config_dir) if f.endswith(".json"))

    configs = {}
    for cf in config_files:
        path = os.path.join(config_dir, cf)
        with open(path) as f:
            raw = json.load(f)
        name = raw["metadata"]["name"]
        coefficients = extract_coefficients(path)
        configs[name] = coefficients

        cursor.execute(
            "INSERT INTO configurations (name, num_iterations, coefficients) VALUES (?, ?, ?)",
            (name, len(coefficients), json.dumps(coefficients)),
        )
    conn.commit()

    # Insert matrix specs
    matrices = specs["matrices"]
    for mat_spec in matrices:
        cursor.execute(
            "INSERT INTO matrices (name, category, rows, cols, seed) VALUES (?, ?, ?, ?, ?)",
            (
                mat_spec["name"],
                mat_spec["category"],
                mat_spec["rows"],
                mat_spec["cols"],
                mat_spec["seed"],
            ),
        )
    conn.commit()

    # Stability analysis parameters
    eigen_vals = np.array(specs["stability_eigenvalues"]["values"])
    perturbation = specs["stability_eigenvalues"]["perturbation"]

    # Evaluate each configuration
    report_configs = []

    for config_name, coefficients in configs.items():
        config_id = cursor.execute(
            "SELECT id FROM configurations WHERE name=?", (config_name,)
        ).fetchone()[0]

        # Benchmark against each matrix
        errors = []
        for mat_spec in matrices:
            X = generate_matrix(mat_spec)
            matrix_id = cursor.execute(
                "SELECT id FROM matrices WHERE name=?", (mat_spec["name"],)
            ).fetchone()[0]

            standard_result = standard_newton_schulz(X, coefficients)
            gram_result = gram_newton_schulz(X, coefficients, reset_iterations=[])

            orth_error = float(compute_polar_error(standard_result))
            rel_diff = float(
                np.linalg.norm(standard_result - gram_result)
                / (np.linalg.norm(standard_result) + 1e-10)
            )
            gram_matches = 1 if rel_diff < 1e-5 else 0

            cursor.execute(
                "INSERT INTO benchmark_results (config_id, matrix_id, orthogonality_error, gram_matches_standard) VALUES (?, ?, ?, ?)",
                (config_id, matrix_id, orth_error, gram_matches),
            )
            errors.append(orth_error)

        avg_error = float(np.mean(errors))

        # Stability analysis: find optimal restarts for 0, 1, and 2 restarts
        for num_restarts in [0, 1, 2]:
            best_restarts, best_metric = find_optimal_restarts(
                eigen_vals, coefficients, perturbation, num_restarts=num_restarts
            )
            cursor.execute(
                "INSERT INTO stability_results (config_id, num_restarts, optimal_positions, stability_metric) VALUES (?, ?, ?, ?)",
                (config_id, num_restarts, json.dumps(best_restarts), float(best_metric)),
            )

        conn.commit()

        # Get no-restart stability metric for the report
        q_vals = simulate_eigenvalue_evolution(
            eigen_vals, coefficients, perturbation, reset_indices=[]
        )
        stab_metric = float(stability_metric(q_vals))

        # Get optimal 1-restart positions for the report
        opt_1_restarts, _ = find_optimal_restarts(
            eigen_vals, coefficients, perturbation, num_restarts=1
        )

        report_configs.append(
            {
                "name": config_name,
                "avg_orthogonality_error": avg_error,
                "stability_metric": stab_metric,
                "optimal_restarts_1": opt_1_restarts,
                "rank": None,
            }
        )

    conn.close()

    # Rank by average orthogonality error (lower = better)
    report_configs.sort(key=lambda c: c["avg_orthogonality_error"])
    for i, cfg in enumerate(report_configs):
        cfg["rank"] = i + 1

    # Write report
    report = {"configurations": report_configs}
    with open("/app/evaluation_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Evaluation complete.")
    for cfg in report_configs:
        print(
            f"  Rank {cfg['rank']}: {cfg['name']} "
            f"(avg_error={cfg['avg_orthogonality_error']:.6f}, "
            f"stability={cfg['stability_metric']:.2f})"
        )


if __name__ == "__main__":
    run_evaluation()
