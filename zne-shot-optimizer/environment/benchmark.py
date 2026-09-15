#!/usr/bin/env python3
"""
Main benchmarking script for quantum error mitigation.

Evaluates Richardson, exponential, and linear extrapolation methods
across multiple noise scenarios, computes optimal shot allocations,
and writes intermediate results to /app/raw_results.json.
"""


import json
import sys

sys.path.insert(0, "/app")

from noise_model import generate_scenario_data
from extrapolators import (
    compute_lagrange_coefficients,
    richardson_extrapolate,
    exponential_extrapolate,
    linear_extrapolate,
)
from allocator import (
    optimal_allocation,
    uniform_allocation,
    variance_uniform,
    variance_optimal,
)


def evaluate_scenario(scenario):
    sf = scenario["scale_factors"]
    ideal = scenario["ideal_value"]
    asym = scenario.get("asymptote", 0.0)
    budget = scenario.get("shot_budget", 10000)

    measurements = generate_scenario_data(scenario)
    coeffs = compute_lagrange_coefficients(sf)
    gamma_norm = sum(abs(c) for c in coeffs)

    rich_result = richardson_extrapolate(sf, measurements)
    exp_result = exponential_extrapolate(sf, measurements, asymptote=asym)
    lin_result = linear_extrapolate(sf, measurements)

    methods = {
        "richardson": {"result": rich_result, "error": abs(rich_result - ideal)},
        "exponential": {"result": exp_result, "error": abs(exp_result - ideal)},
        "linear": {"result": lin_result, "error": abs(lin_result - ideal)},
    }

    best_method = max(methods.keys(), key=lambda m: methods[m]["result"])

    opt_alloc = optimal_allocation(coeffs, budget)
    uni_alloc = uniform_allocation(len(sf), budget)
    var_u = variance_uniform(coeffs, budget)
    var_o = variance_optimal(coeffs, budget)

    return {
        "scenario_id": scenario["id"],
        "ideal_value": ideal,
        "noisy_value": measurements[0],
        "noisy_error": abs(measurements[0] - ideal),
        "measurements": measurements,
        "lagrange_coefficients": coeffs,
        "gamma_norm": gamma_norm,
        "richardson": methods["richardson"],
        "exponential": methods["exponential"],
        "linear": methods["linear"],
        "best_method": best_method,
        "best_result": methods[best_method]["result"],
        "best_error": methods[best_method]["error"],
        "allocation": {
            "shot_budget": budget,
            "optimal": opt_alloc,
            "uniform": uni_alloc,
            "variance_uniform": var_u,
            "variance_optimal": var_o,
        },
    }


def main():
    with open("/app/scenarios.json") as f:
        scenarios = json.load(f)

    results = {}
    for scenario in scenarios:
        result = evaluate_scenario(scenario)
        results[scenario["id"]] = result
        print(
            f"[{scenario['id']}] noisy_err={result['noisy_error']:.6f}, "
            f"rich_err={result['richardson']['error']:.6f}, "
            f"exp_err={result['exponential']['error']:.6f}, "
            f"best={result['best_method']}"
        )

    with open("/app/raw_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/raw_results.json")


if __name__ == "__main__":
    main()
