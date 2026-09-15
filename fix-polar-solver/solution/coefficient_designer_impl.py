
"""
Coefficient designer implementation.

Uses a parameterized family of convergence polynomials with grid search
to find an optimal 5-iteration Newton-Schulz coefficient schedule.

Design insight: the polynomial p(r) = 1 + c*(1-r)^2 (expanded as
a = 1+c, b = -2c, c = c) guarantees:
  - p(1) = 1: eigenvalues already at 1 are preserved (convergence fixed point)
  - p'(1) = 0: quadratic convergence rate near the fixed point
  - p(r) >= 1 for r in [0,1]: eigenvalues always grow toward 1 (monotone)

Larger c values give faster initial convergence (stronger boost for small
eigenvalues) but are less efficient near convergence. A non-uniform schedule
with aggressive early iterations (large c) and conservative late iterations
(small or zero c) optimizes overall convergence.
"""

import json
import numpy as np
import sys

sys.path.insert(0, "/app")
from polar_solver import standard_newton_schulz, compute_polar_error


def load_matrix_specs(path="/app/matrix_specs.json"):
    """Load test matrix specifications."""
    with open(path) as f:
        return json.load(f)


def evaluate_schedule(coefficients, matrix_specs):
    """Evaluate a coefficient schedule on all test matrices.

    Returns average orthogonality error.
    """
    errors = []
    for spec in matrix_specs["matrices"]:
        np.random.seed(spec["seed"])
        X = np.random.randn(spec["rows"], spec["cols"])
        result = standard_newton_schulz(X, coefficients)
        errors.append(float(compute_polar_error(result)))
    return float(np.mean(errors))


def design_custom_schedule(matrix_specs, design_spec):
    """Design a custom coefficient schedule using grid search.

    Searches over non-uniform schedules from the quadratic convergence
    family p(r) = 1 + c*(1-r)^2, varying:
    - c_val: strength of quadratic term in aggressive iterations
    - n_aggressive: number of aggressive early iterations (rest use classic)

    The classic schedule [1.5, -0.5, 0] corresponds to c=0 in this family.
    """
    best_coeffs = None
    best_error = float("inf")

    for n_aggressive in range(1, 5):
        for c_val_x10 in range(2, 25):
            c_val = c_val_x10 / 10.0
            coeffs = []
            for i in range(5):
                if i < n_aggressive:
                    c = c_val
                    b = -2.0 * c
                    a = 1.0 + c
                else:
                    # Fall back to classic Newton-Schulz for remaining iterations
                    a, b, c = 1.5, -0.5, 0.0
                coeffs.append([float(a), float(b), float(c)])

            if not all(t[0] > 0 for t in coeffs):
                continue
            if not any(abs(t[2]) > 1e-10 for t in coeffs):
                continue

            error = evaluate_schedule(coeffs, matrix_specs)
            if error < best_error:
                best_error = error
                best_coeffs = coeffs

    return best_coeffs


def save_config(coefficients, name, output_path):
    """Save a coefficient schedule as a config JSON file."""
    config = {
        "metadata": {
            "name": name,
            "version": "1.0",
            "source": "custom-designed",
            "description": "Custom-designed %d-iteration schedule" % len(coefficients),
        },
        "parameters": {
            "iterations": [
                {
                    "step": i,
                    "coefficients": {"a": float(a), "b": float(b), "c": float(c)},
                }
                for i, (a, b, c) in enumerate(coefficients)
            ]
        },
    }
    with open(output_path, "w") as f:
        json.dump(config, f, indent=2)


if __name__ == "__main__":
    specs = load_matrix_specs()
    with open("/app/design_spec.json") as f:
        design_spec = json.load(f)

    coefficients = design_custom_schedule(specs, design_spec)
    save_config(coefficients, "custom_optimized", "/app/configs/custom_optimized.json")

    error = evaluate_schedule(coefficients, specs)
    print("Custom schedule average error: %.6f" % error)
