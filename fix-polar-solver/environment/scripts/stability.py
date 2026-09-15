#!/usr/bin/env python3
"""Compute stability metrics for each configuration.

Reads extracted config JSON files, runs eigenvalue-based stability analysis
using restart optimization for 0, 1, and 2 restarts. Writes CSV to stdout.
"""
import sys
import json
import csv
import numpy as np

sys.path.insert(0, "/app")
from polar_solver import find_optimal_restarts


def main():
    with open("/app/matrix_specs.json") as f:
        specs = json.load(f)

    eigen_vals = np.array(specs["stability_eigenvalues"]["values"])
    perturbation = specs["stability_eigenvalues"]["perturbation"]

    writer = csv.writer(sys.stdout)
    writer.writerow(["config_name", "num_restarts", "optimal_positions", "stability_metric"])

    for config_file in sorted(sys.argv[1:]):
        with open(config_file) as f:
            config = json.load(f)
        name = config["name"]
        coefficients = config["coefficients"]

        for num_restarts in [0, 1, 2]:
            best_restarts, best_metric = find_optimal_restarts(
                eigen_vals, coefficients, perturbation, num_restarts=num_restarts
            )
            positions_json = json.dumps(best_restarts)
            writer.writerow([name, num_restarts, positions_json, f"{best_metric:.10f}"])


if __name__ == "__main__":
    main()
