#!/usr/bin/env python3
"""Evaluate variance reduction effectiveness across the contract portfolio.

Computes sample variances under crude MC, antithetic variates, and control
variate methods, then identifies the best method for each option type.
Writes results to /app/variance_analysis.json.
"""
import json
import math
import sys

sys.path.insert(0, "/app")

from qrng_wrapper import SobolEngine, norm_inv
from gbm_paths import simulate_paths
from payoffs import european_call, asian_call, barrier_up_out_call
from geo_asian import geometric_asian_call


def sample_var(xs):
    """Compute unbiased sample variance."""
    m = sum(xs) / len(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def analyze_option(contract, n_paths=8192):
    """Compute payoff variance under different VR methods."""
    S0 = contract["S0"]
    K = contract["K"]
    r = contract["r"]
    sigma = contract["sigma"]
    T = contract["T"]
    opt_type = contract["type"]
    n_steps = 1 if opt_type.startswith("european") else contract.get("n_steps", 4)

    engine = SobolEngine(n_steps)
    pts = engine.generate(n_paths)

    crude = []
    anti = []
    geo_raw = []

    for i in range(n_paths):
        normals = [norm_inv(max(1e-10, min(1 - 1e-10, u))) for u in pts[i]]
        path = simulate_paths(S0, r, sigma, T, n_steps, normals)

        # Crude payoff
        if opt_type == "european_call":
            p = european_call(path, K, r, T)
        elif opt_type == "asian_call":
            p = asian_call(path, K, r, T, S0)
        elif opt_type == "barrier_up_out_call":
            p = barrier_up_out_call(path, K, r, T, S0, contract["barrier"])
        crude.append(p)

        # Antithetic payoff
        a_normals = [-z for z in normals]
        a_path = simulate_paths(S0, r, sigma, T, n_steps, a_normals)
        if opt_type == "european_call":
            p2 = european_call(a_path, K, r, T)
        elif opt_type == "asian_call":
            p2 = asian_call(a_path, K, r, T, S0)
        elif opt_type == "barrier_up_out_call":
            p2 = barrier_up_out_call(a_path, K, r, T, S0, contract["barrier"])
        anti.append(0.5 * (p + p2))

        # Geometric payoff for control variate
        if opt_type == "asian_call":
            g = 1.0
            for S in path:
                g *= S
            g = g ** (1.0 / len(path))
            geo_raw.append(math.exp(-r * T) * max(g - K, 0.0))

    v_crude = sample_var(crude)
    v_anti = sample_var(anti)
    anti_vr = v_crude / v_anti if v_anti > 1e-15 else 999.0

    result = {
        "crude_variance": round(v_crude, 6),
        "antithetic_variance": round(v_anti, 6),
        "antithetic_vr_ratio": round(anti_vr, 2),
    }

    if opt_type == "asian_call" and geo_raw:
        geo_analytical = geometric_asian_call(S0, K, r, sigma, T, n_steps)
        mp = sum(crude) / len(crude)
        mg = sum(geo_raw) / len(geo_raw)
        cov = sum((crude[i] - mp) * (geo_raw[i] - mg)
                  for i in range(n_paths)) / (n_paths - 1)
        vg = sample_var(geo_raw)
        if vg > 1e-15:
            beta = cov / vg
            cv_vals = [crude[i] - beta * (geo_raw[i] - geo_analytical)
                       for i in range(n_paths)]
            v_cv = sample_var(cv_vals)
            cv_vr = v_crude / v_cv if v_cv > 1e-15 else 999.0
            result["control_variate_variance"] = round(v_cv, 6)
            result["cv_vr_ratio"] = round(cv_vr, 2)

    if "cv_vr_ratio" in result and result["cv_vr_ratio"] > anti_vr:
        result["best_method"] = "control_variate"
        result["variance_reduction_ratio"] = result["cv_vr_ratio"]
    else:
        result["best_method"] = "antithetic"
        result["variance_reduction_ratio"] = result["antithetic_vr_ratio"]

    return result


def main():
    contracts = {
        "european_call": {
            "type": "european_call", "S0": 100.0, "K": 100.0,
            "r": 0.05, "sigma": 0.2, "T": 1.0
        },
        "asian_call": {
            "type": "asian_call", "S0": 100.0, "K": 100.0,
            "r": 0.05, "sigma": 0.2, "T": 1.0, "n_steps": 6
        },
        "barrier_up_out_call": {
            "type": "barrier_up_out_call", "S0": 100.0, "K": 100.0,
            "r": 0.05, "sigma": 0.2, "T": 1.0, "barrier": 140.0, "n_steps": 6
        },
    }

    report = {}
    for name, c in contracts.items():
        print(f"Analyzing {name}...")
        report[name] = analyze_option(c)

    with open("/app/variance_analysis.json", "w") as f:
        json.dump(report, f, indent=2)

    print("\nVariance analysis written to /app/variance_analysis.json")
    for name, r in report.items():
        print(f"  {name}: best={r['best_method']}, VR={r['variance_reduction_ratio']:.1f}x")


if __name__ == "__main__":
    main()
