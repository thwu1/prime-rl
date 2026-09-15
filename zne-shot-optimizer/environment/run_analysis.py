#!/usr/bin/env python3
"""
Main analysis script for ZNE optimization.

Reads problem configurations from /app/problems.json,
invokes functions from zne_optimizer module, and writes
results to /app/results.json.
"""


import json
import sys
import os

sys.path.insert(0, "/app")

from noise_model import generate_measurements
from zne_optimizer import (
    compute_lagrange_coefficients,
    richardson_extrapolate,
    optimal_shot_allocation,
    richardson_variance_uniform,
    richardson_variance_optimal,
    exponential_extrapolate,
    find_optimal_scale_factors,
)


def run():
    with open("/app/problems.json") as f:
        problems = json.load(f)

    results = {}

    # --- Lagrange coefficient tests ---
    results["lagrange"] = {}
    for test in problems["lagrange_tests"]:
        sf = test["scale_factors"]
        coeffs = compute_lagrange_coefficients(sf)
        gamma_norm = sum(abs(c) for c in coeffs)
        results["lagrange"][test["id"]] = {
            "coefficients": coeffs,
            "gamma_norm": gamma_norm,
        }
        print(f"[Lagrange {test['id']}] coeffs={[round(c,6) for c in coeffs]}, Gamma={gamma_norm:.6f}")

    # --- Allocation tests ---
    results["allocation"] = {}
    for test in problems["allocation_tests"]:
        sf = test["scale_factors"]
        budget = test["total_budget"]
        alloc = optimal_shot_allocation(sf, budget)
        var_u = richardson_variance_uniform(sf, budget)
        var_o = richardson_variance_optimal(sf, budget)
        results["allocation"][test["id"]] = {
            "allocation": alloc,
            "variance_uniform": var_u,
            "variance_optimal": var_o,
            "improvement_ratio": var_u / var_o if var_o > 0 else float("inf"),
        }
        print(f"[Alloc {test['id']}] alloc={alloc}, sum={sum(alloc)}, var_u={var_u:.6f}, var_o={var_o:.6f}")

    # --- Extrapolation tests ---
    results["extrapolation"] = {}
    for test in problems["extrapolation_tests"]:
        sf = test["scale_factors"]
        measurements = generate_measurements(
            test["ideal_value"], sf, test["decay_rate"], test["asymptote"]
        )

        rich_result = richardson_extrapolate(sf, measurements)
        exp_result = exponential_extrapolate(sf, measurements, test["asymptote"])

        rich_error = abs(rich_result - test["ideal_value"])
        exp_error = abs(exp_result - test["ideal_value"])

        results["extrapolation"][test["id"]] = {
            "measurements": measurements,
            "richardson_result": rich_result,
            "exponential_result": exp_result,
            "richardson_error": rich_error,
            "exponential_error": exp_error,
            "ideal_value": test["ideal_value"],
        }
        print(
            f"[Extrap {test['id']}] rich={rich_result:.8f} (err={rich_error:.2e}), "
            f"exp={exp_result:.8f} (err={exp_error:.2e}), ideal={test['ideal_value']}"
        )

    # --- Optimization tests ---
    results["optimization"] = {}
    for test in problems["optimization_tests"]:
        best_factors, best_gamma = find_optimal_scale_factors(
            test["candidate_scale_factors"],
            test["subset_size"],
        )
        var_o = richardson_variance_optimal(best_factors, test["total_budget"])
        results["optimization"][test["id"]] = {
            "best_factors": best_factors,
            "best_gamma_norm": best_gamma,
            "variance_optimal": var_o,
        }
        print(f"[Optim {test['id']}] best={best_factors}, Gamma={best_gamma:.6f}, var={var_o:.8f}")

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    run()
