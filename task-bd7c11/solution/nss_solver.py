#!/usr/bin/env python3

"""
Nelson-Siegel-Svensson yield curve fitting pipeline.
Uses precomputed cashflow matrices and vectorized operations for speed.
"""

import csv
import json
import math
import os
from datetime import date

import numpy as np
from scipy.optimize import minimize


# ---- NSS Model (vectorized) ----

def nss_spot_rate_scalar(t, tau1, tau2, beta1, beta2, beta3, beta4):
    """Spot rate for scalar t."""
    if t < 1e-10:
        return beta1 + beta2
    x1 = t / tau1
    x2 = t / tau2
    e1 = math.exp(-x1)
    e2 = math.exp(-x2)
    f1 = (1 - e1) / x1
    f2 = (1 - e2) / x2
    return beta1 + beta2 * f1 + beta3 * (f1 - e1) + beta4 * (f2 - e2)


def nss_spot_rate_vec(t_arr, tau1, tau2, beta1, beta2, beta3, beta4):
    """Vectorized spot rate for array of maturities."""
    t = np.asarray(t_arr)
    safe_t = np.where(t < 1e-10, 1.0, t)
    x1 = safe_t / tau1
    x2 = safe_t / tau2
    e1 = np.exp(-x1)
    e2 = np.exp(-x2)
    f1 = (1 - e1) / x1
    f2 = (1 - e2) / x2
    y = beta1 + beta2 * f1 + beta3 * (f1 - e1) + beta4 * (f2 - e2)
    # Handle t near 0
    y = np.where(t < 1e-10, beta1 + beta2, y)
    return y


def nss_forward_rate_scalar(t, tau1, tau2, beta1, beta2, beta3, beta4):
    """Instantaneous forward rate."""
    if t < 1e-10:
        return beta1 + beta2
    x1 = t / tau1
    x2 = t / tau2
    return (beta1 + beta2 * math.exp(-x1)
            + beta3 * x1 * math.exp(-x1)
            + beta4 * x2 * math.exp(-x2))


def discount_vec(t_arr, tau1, tau2, beta1, beta2, beta3, beta4):
    """Vectorized discount factors."""
    t = np.asarray(t_arr)
    y = nss_spot_rate_vec(t, tau1, tau2, beta1, beta2, beta3, beta4)
    d = np.exp(-y * t)
    d = np.where(t < 1e-10, 1.0, d)
    return d


# ---- Cashflow Matrix Construction ----

def build_cashflow_structures(bonds):
    """Precompute cashflow matrix and related arrays.
    Returns: cf_matrix, cf_times_flat, bond_cf_indices, durations, observed_prices
    """
    # Collect all unique cashflow times across all bonds
    all_cf_times = set()
    bond_cf_lists = []

    for b in bonds:
        ytm = b["ytm_years"]
        n_periods = int(math.ceil(ytm * 2))
        times = []
        for i in range(n_periods):
            t = ytm - i * 0.5
            if t > 0.001:
                times.append(round(t, 8))
        times.sort()
        bond_cf_lists.append(times)
        all_cf_times.update(times)

    # Sort all unique times
    all_cf_times = sorted(all_cf_times)
    time_to_idx = {t: i for i, t in enumerate(all_cf_times)}

    n_bonds = len(bonds)
    n_times = len(all_cf_times)

    # Build cashflow matrix: cf_matrix[bond_idx, time_idx] = cashflow amount
    cf_matrix = np.zeros((n_bonds, n_times))

    for i, (b, times) in enumerate(zip(bonds, bond_cf_lists)):
        sc = b["coupon_rate"] / 2.0  # semiannual coupon
        ytm = b["ytm_years"]
        for t in times:
            j = time_to_idx[t]
            cf = sc
            if abs(t - ytm) < 0.001:
                cf += 100.0
            cf_matrix[i, j] = cf

    times_arr = np.array(all_cf_times)
    durations = np.array([max(b["duration"], 0.1) for b in bonds])
    prices = np.array([b["price"] for b in bonds])

    return cf_matrix, times_arr, durations, prices


def compute_model_prices(cf_matrix, times_arr, tau1, tau2, b1, b2, b3, b4):
    """Compute model prices using cashflow matrix and discount factors."""
    df = discount_vec(times_arr, tau1, tau2, b1, b2, b3, b4)
    return cf_matrix @ df


# ---- Data Loading ----

def load_bonds(path):
    """Load bond data from CSV."""
    bonds = []
    settlement = date(2024, 6, 15)
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            mat_parts = row["maturity_date"].split("-")
            mat_date = date(int(mat_parts[0]), int(mat_parts[1]), int(mat_parts[2]))
            ytm = (mat_date - settlement).days / 365.25
            bonds.append({
                "cusip": row["cusip"],
                "coupon_rate": float(row["coupon_rate"]),
                "price": float(row["price"]),
                "duration": float(row["duration_years"]),
                "ytm_years": ytm,
            })
    return bonds


# ---- Optimization ----

def make_objective(cf_matrix, times_arr, durations, prices):
    """Create objective function closure with precomputed structures."""
    def objective(params_arr):
        tau1, tau2, b1, b2, b3, b4 = params_arr
        if tau1 <= 0.01 or tau2 <= 0.01 or tau1 > 100 or tau2 > 100:
            return 1e15
        try:
            model_prices = compute_model_prices(cf_matrix, times_arr, tau1, tau2, b1, b2, b3, b4)
            errors = (prices - model_prices) ** 2 / durations
            return np.sum(errors)
        except (OverflowError, ValueError, FloatingPointError):
            return 1e15
    return objective


def par_yield_scalar(maturity, tau1, tau2, beta1, beta2, beta3, beta4):
    """Par yield for a given maturity."""
    n_periods = int(math.ceil(maturity * 2))
    times = []
    for i in range(n_periods):
        t = maturity - i * 0.5
        if t > 0.001:
            times.append(t)
    times.sort()
    if not times:
        return nss_spot_rate_scalar(maturity, tau1, tau2, beta1, beta2, beta3, beta4)
    df_sum = 0.0
    for t in times:
        y = nss_spot_rate_scalar(t, tau1, tau2, beta1, beta2, beta3, beta4)
        df_sum += math.exp(-y * t)
    y_mat = nss_spot_rate_scalar(maturity, tau1, tau2, beta1, beta2, beta3, beta4)
    df_mat = math.exp(-y_mat * maturity)
    return 2.0 * (1.0 - df_mat) / df_sum


def fit_nss(bonds):
    """Fit NSS model using multi-start optimization with vectorized objective."""
    cf_matrix, times_arr, durations, prices = build_cashflow_structures(bonds)
    obj = make_objective(cf_matrix, times_arr, durations, prices)

    starting_points = [
        [1.0, 10.0, 0.03, -0.01, 0.02, -0.01],
        [2.0, 5.0, 0.05, -0.03, 0.05, 0.0],
        [1.5, 8.0, 0.04, -0.02, 0.04, -0.01],
        [3.0, 12.0, 0.035, -0.015, 0.025, -0.005],
        [0.8, 20.0, 0.038, -0.018, 0.035, -0.008],
    ]

    best_result = None
    best_fun = float("inf")

    for x0 in starting_points:
        result = minimize(obj, x0, method="Nelder-Mead",
                          options={"maxiter": 15000, "xatol": 1e-8, "fatol": 1e-13})
        # Refine
        result2 = minimize(obj, result.x, method="Powell",
                           options={"maxiter": 5000, "ftol": 1e-14})
        candidate = result2 if result2.fun < result.fun else result
        if candidate.fun < best_fun:
            best_fun = candidate.fun
            best_result = candidate

    return best_result.x


# ---- Main ----

def main():
    print("Loading bond data...")
    bonds = load_bonds("/app/data/treasury_bonds.csv")
    print(f"Loaded {len(bonds)} bonds")

    print("Fitting NSS model (multi-start)...")
    fitted = fit_nss(bonds)
    tau1, tau2, b1, b2, b3, b4 = fitted
    print(f"Fitted: tau1={tau1:.6f}, tau2={tau2:.6f}, "
          f"beta1={b1:.6f}, beta2={b2:.6f}, beta3={b3:.6f}, beta4={b4:.6f}")

    os.makedirs("/app/output", exist_ok=True)

    # Precompute model prices for all bonds
    cf_matrix, times_arr, durations, prices = build_cashflow_structures(bonds)
    model_prices = compute_model_prices(cf_matrix, times_arr, tau1, tau2, b1, b2, b3, b4)

    # 1. Fitted parameters
    params_dict = {"tau1": float(tau1), "tau2": float(tau2),
                   "beta1": float(b1), "beta2": float(b2),
                   "beta3": float(b3), "beta4": float(b4)}
    with open("/app/output/fitted_params.json", "w") as f:
        json.dump(params_dict, f, indent=2)

    # 2-4. Rate curves
    key_mats = [0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0]

    with open("/app/output/spot_rates.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["maturity", "rate"])
        for m in key_mats:
            w.writerow([m, f"{nss_spot_rate_scalar(m, tau1, tau2, b1, b2, b3, b4):.8f}"])

    with open("/app/output/forward_rates.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["maturity", "rate"])
        for m in key_mats:
            w.writerow([m, f"{nss_forward_rate_scalar(m, tau1, tau2, b1, b2, b3, b4):.8f}"])

    with open("/app/output/par_yields.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["maturity", "rate"])
        for m in key_mats:
            w.writerow([m, f"{par_yield_scalar(m, tau1, tau2, b1, b2, b3, b4):.8f}"])

    # 5. Model prices
    with open("/app/output/model_prices.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cusip", "observed_price", "model_price", "error_pct"])
        for i, b in enumerate(bonds):
            mp = model_prices[i]
            err = (b["price"] - mp) / mp
            w.writerow([b["cusip"], f"{b['price']:.6f}", f"{mp:.6f}", f"{err:.8f}"])

    # 6. Rich/cheap classification
    threshold = 0.0015
    with open("/app/output/rich_cheap.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cusip", "classification", "error_pct"])
        for i, b in enumerate(bonds):
            mp = model_prices[i]
            err = (b["price"] - mp) / mp
            cls = "rich" if err > threshold else ("cheap" if err < -threshold else "fair")
            w.writerow([b["cusip"], cls, f"{err:.8f}"])

    print("All outputs written to /app/output/")

    # Diagnostics
    errs = np.abs(prices - model_prices) / model_prices
    print(f"\nPrice errors: mean={errs.mean()*100:.4f}%, max={errs.max()*100:.4f}%")
    for m in key_mats:
        r = nss_spot_rate_scalar(m, tau1, tau2, b1, b2, b3, b4)
        print(f"  Spot {m:5.1f}y: {r*100:.4f}%")


if __name__ == "__main__":
    main()
