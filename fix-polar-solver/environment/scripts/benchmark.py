#!/usr/bin/env python3
"""Compute benchmark metrics for each config x matrix pair.

Reads extracted config JSON files (one per CLI argument), loads matrix
specifications from /app/matrix_specs.json, evaluates standard and Gram
Newton-Schulz decompositions, and writes results as CSV to stdout.
"""
import sys
import json
import csv
import numpy as np

sys.path.insert(0, "/app")
from polar_solver import standard_newton_schulz, gram_newton_schulz, compute_polar_error


def main():
    with open("/app/matrix_specs.json") as f:
        specs = json.load(f)

    writer = csv.writer(sys.stdout)
    writer.writerow(["config_name", "matrix_name", "orthogonality_error", "gram_matches_standard"])

    for config_file in sorted(sys.argv[1:]):
        with open(config_file) as f:
            config = json.load(f)
        name = config["name"]
        coefficients = config["coefficients"]

        for mat_spec in specs["matrices"]:
            np.random.seed(mat_spec["seed"])
            X = np.random.randn(mat_spec["rows"], mat_spec["cols"])

            standard_result = standard_newton_schulz(X, coefficients)
            gram_result = gram_newton_schulz(X, coefficients, reset_iterations=[])

            orth_error = float(compute_polar_error(standard_result))
            rel_diff = float(
                np.linalg.norm(standard_result - gram_result)
                / (np.linalg.norm(standard_result) + 1e-10)
            )
            gram_matches = 1 if rel_diff < 1e-5 else 0

            writer.writerow([name, mat_spec["name"], f"{orth_error:.10f}", gram_matches])


if __name__ == "__main__":
    main()
