#!/usr/bin/env python3
"""
PDE Convergence Benchmark Driver

Imports solver modules from solvers/, runs each at multiple resolutions,
computes L2 errors and convergence orders, and writes results.json.
"""
import json
import math
import os
import sys


RESOLUTIONS = [16, 32, 64, 128]
PROBLEMS = ["poisson_5pt", "poisson_compact", "heat_cn", "advection_lw"]


def compute_orders(errors):
    """Compute convergence orders from consecutive error pairs."""
    orders = []
    for i in range(len(errors) - 1):
        if errors[i] > 0 and errors[i + 1] > 0:
            orders.append(math.log(errors[i] / errors[i + 1]) / math.log(2))
    return orders


def main():
    app_dir = os.path.dirname(os.path.abspath(__file__))
    solver_dir = os.path.join(app_dir, "solvers")
    sys.path.insert(0, app_dir)
    sys.path.insert(0, solver_dir)

    results = {}

    for name in PROBLEMS:
        mod = __import__(name)
        errors = [mod.solve(N) for N in RESOLUTIONS]
        orders = compute_orders(errors)
        est = sum(orders) / len(orders) if orders else 0.0

        results[name] = {
            "resolutions": RESOLUTIONS,
            "l2_errors": errors,
            "convergence_orders": orders,
            "estimated_order": est,
        }

        e_str = ", ".join(f"{e:.4e}" for e in errors)
        o_str = ", ".join(f"{o:.2f}" for o in orders)
        print(f"{name:20s}  errors=[{e_str}]  orders=[{o_str}]  est={est:.2f}")

    out_path = os.path.join(app_dir, "results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
