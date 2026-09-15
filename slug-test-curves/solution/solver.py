#!/usr/bin/env python3

"""
High-K Slug Test Type Curve Analysis Engine.

Implements the damped-oscillator model for slug test responses in highly
permeable aquifers. The governing ODE is:

    d²wd/dtd² + CD * dwd/dtd + wd = 0,   wd(0) = 1,  wd'(0) = 0

Three regimes:
  CD < 2  (underdamped):  oscillatory decay
  CD = 2  (critically damped)
  CD > 2  (overdamped):   monotonic decay
"""

import argparse
import csv
import json
import math
import os
import sys

import numpy as np
from scipy.optimize import minimize, differential_evolution, least_squares

G = 9.80665  # standard gravity m/s²


def type_curve(td, cd):
    """Compute normalized head wd for dimensionless time td and damping CD."""
    td = np.asarray(td, dtype=float)
    cd = float(cd)
    alpha = cd / 2.0

    if cd < 2.0 - 1e-12:
        omega = math.sqrt(1.0 - alpha ** 2)
        wd = np.exp(-alpha * td) * (
            np.cos(omega * td) + (alpha / omega) * np.sin(omega * td)
        )
    elif abs(cd - 2.0) < 1e-12:
        wd = (1.0 + td) * np.exp(-td)
    else:
        beta = math.sqrt(alpha ** 2 - 1.0)
        r1 = -alpha + beta
        r2 = -alpha - beta
        coeff_a = (alpha + beta) / (2.0 * beta)
        coeff_b = (beta - alpha) / (2.0 * beta)
        wd = coeff_a * np.exp(r1 * td) + coeff_b * np.exp(r2 * td)

    return wd


def cmd_generate(args):
    """Generate a type curve CSV."""
    cd = args.cd
    td_max = args.td_max
    dt = args.dt

    n_points = int(round(td_max / dt)) + 1
    td_arr = np.array([i * dt for i in range(n_points)])
    wd_arr = type_curve(td_arr, cd)

    with open(args.output, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["td", "wd"])
        for td_val, wd_val in zip(td_arr, wd_arr):
            writer.writerow([f"{td_val:.6f}", f"{wd_val:.8f}"])


def _read_field_data(path):
    """Read field data CSV -> (time, normalized_head) arrays."""
    time_list = []
    nh_list = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            time_list.append(float(row["time"]))
            nh_list.append(float(row["normalized_head"]))
    return np.array(time_list), np.array(nh_list)


def _model_predict(params, time_arr):
    """Predict normalized head for given parameters."""
    cd, alpha, t0 = params
    td = alpha * (time_arr - t0)
    wd = np.ones_like(time_arr)
    mask = td >= 0
    if mask.any():
        wd[mask] = type_curve(td[mask], cd)
    return wd


def _fit_residual(params, time_arr, nh_arr):
    """Sum of squared residuals for fitting (scalar objective)."""
    cd, alpha, t0 = params
    if cd <= 0.05 or alpha <= 0.01:
        return 1e12
    td = alpha * (time_arr - t0)
    mask = td >= 0
    if mask.sum() < 5:
        return 1e12
    try:
        wd = _model_predict(params, time_arr)
    except (ValueError, OverflowError):
        return 1e12
    return float(np.sum((nh_arr - wd) ** 2))


def _fit_residuals_vec(params, time_arr, nh_arr):
    """Residual vector for scipy.optimize.least_squares."""
    cd, alpha, t0 = params
    try:
        wd = _model_predict(params, time_arr)
    except (ValueError, OverflowError):
        return np.full(len(time_arr), 100.0)
    return nh_arr - wd


def fit_data(time_arr, nh_arr):
    """Fit field data to recover CD, alpha=sqrt(g/Le), t0."""
    best_x = None
    best_cost = float("inf")

    t_max = float(time_arr[-1])
    lb = np.array([0.1, 0.05, -2.0])
    ub = np.array([50.0, 5.0, max(t_max * 0.3, 2.0)])
    bounds_de = list(zip(lb, ub))

    def update_best(x, cost):
        nonlocal best_x, best_cost
        if cost < best_cost:
            best_cost = cost
            best_x = np.array(x, dtype=float).copy()

    # Stage 1: Differential Evolution with multiple seeds for global search
    for seed in [42, 123, 7]:
        try:
            de_result = differential_evolution(
                _fit_residual, bounds_de, args=(time_arr, nh_arr),
                seed=seed, maxiter=400, tol=1e-12, polish=False,
                mutation=(0.5, 1.5), recombination=0.9, popsize=30,
            )
            update_best(de_result.x, de_result.fun)
            # Refine each DE result with gradient-based least_squares
            x0 = np.clip(de_result.x, lb + 1e-4, ub - 1e-4)
            lsq = least_squares(
                _fit_residuals_vec, x0,
                args=(time_arr, nh_arr),
                bounds=(lb, ub), method='trf', max_nfev=5000,
                ftol=1e-15, xtol=1e-15, gtol=1e-15,
            )
            update_best(lsq.x, 2.0 * lsq.cost)
        except Exception:
            pass

    # Stage 2: Multi-start least_squares with trust-region reflective
    for cd_init in [0.3, 0.8, 1.5, 2.0, 3.0, 4.0, 5.0, 8.0, 15.0]:
        for alpha_init in [0.3, 0.7, 1.0, 1.5, 2.5]:
            for t0_init in [0.0, 0.2, 0.5]:
                x0 = np.clip([cd_init, alpha_init, t0_init],
                             lb + 1e-4, ub - 1e-4)
                try:
                    lsq = least_squares(
                        _fit_residuals_vec, x0,
                        args=(time_arr, nh_arr),
                        bounds=(lb, ub), method='trf', max_nfev=3000,
                        ftol=1e-14, xtol=1e-14, gtol=1e-14,
                    )
                    update_best(lsq.x, 2.0 * lsq.cost)
                except Exception:
                    pass

    # Stage 3: Final Nelder-Mead polish on best result
    if best_x is not None:
        try:
            res = minimize(
                _fit_residual, best_x, args=(time_arr, nh_arr),
                method='Nelder-Mead',
                options={'maxiter': 50000, 'xatol': 1e-12, 'fatol': 1e-16},
            )
            update_best(res.x, res.fun)
        except Exception:
            pass

    if best_x is None:
        raise RuntimeError("Fitting failed to converge")

    cd, alpha, t0 = best_x
    cd = abs(cd)
    alpha = abs(alpha)
    le = G / (alpha ** 2)

    return {
        "cd": round(cd, 6),
        "le": round(le, 6),
        "alpha": round(alpha, 6),
        "t0": round(t0, 6),
    }


def cmd_fit(args):
    """Fit field data and write result JSON."""
    time_arr, nh_arr = _read_field_data(args.data)
    result = fit_data(time_arr, nh_arr)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)


def cmd_batch(args):
    """Batch process multiple scenarios."""
    with open(args.config) as f:
        config = json.load(f)

    os.makedirs(args.output_dir, exist_ok=True)

    for scenario in config["scenarios"]:
        name = scenario["name"]
        data_file = scenario["data_file"]
        time_arr, nh_arr = _read_field_data(data_file)
        result = fit_data(time_arr, nh_arr)
        out_path = os.path.join(args.output_dir, f"{name}.json")
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="High-K Slug Test Analyzer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    gen_parser = subparsers.add_parser("generate")
    gen_parser.add_argument("--cd", type=float, required=True)
    gen_parser.add_argument("--td-max", type=float, required=True)
    gen_parser.add_argument("--dt", type=float, required=True)
    gen_parser.add_argument("--output", required=True)

    fit_parser = subparsers.add_parser("fit")
    fit_parser.add_argument("--data", required=True)
    fit_parser.add_argument("--output", required=True)

    batch_parser = subparsers.add_parser("batch")
    batch_parser.add_argument("--config", required=True)
    batch_parser.add_argument("--output-dir", required=True)

    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "fit":
        cmd_fit(args)
    elif args.command == "batch":
        cmd_batch(args)


if __name__ == "__main__":
    main()
