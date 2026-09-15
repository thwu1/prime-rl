#!/usr/bin/env python3

"""Calibrate SZHW model to market data and store runs in SQLite."""
import numpy as np
import scipy.optimize as optimize
import sqlite3
import json
import sys

sys.path.insert(0, "/app")
from szhw_pricer import compute_call_prices

# -----------------------------------------------------------------------
# Load market data
# -----------------------------------------------------------------------
with open("/app/market_data.json", "r") as f:
    market = json.load(f)

S0 = market["S0"]
r = market["r"]
T = market["T"]
K = market["strikes"]
market_prices = np.array(market["call_prices"])
P0T = np.exp(-r * T)

kappa = market["szhw_fixed_params"]["kappa"]
Rxr = market["szhw_fixed_params"]["Rxr"]
lambd = market["szhw_fixed_params"]["lambd"]
eta = market["szhw_fixed_params"]["eta"]


# -----------------------------------------------------------------------
# Calibration objective
# -----------------------------------------------------------------------
def target(x):
    gamma, sigmabar, Rrsigma, Rxsigma, sigma0 = x
    if gamma <= 0 or sigmabar <= 0 or sigma0 <= 0:
        return 1e10
    if abs(Rrsigma) >= 1.0 or abs(Rxsigma) >= 1.0:
        return 1e10
    try:
        prices = compute_call_prices(
            S0, K, T, P0T, kappa, Rxr, lambd, eta,
            gamma, sigmabar, Rrsigma, Rxsigma, sigma0,
        )
        error = np.linalg.norm(np.array(prices) - market_prices)
        if np.isnan(error) or np.isinf(error):
            return 1e10
        return error
    except Exception:
        return 1e10


# -----------------------------------------------------------------------
# Set up SQLite database
# -----------------------------------------------------------------------
conn = sqlite3.connect("/app/calibration.db")
conn.execute("""
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY,
        gamma REAL, sigmabar REAL, Rrsigma REAL,
        Rxsigma REAL, sigma0 REAL, l2_error REAL
    )
""")
conn.commit()


# -----------------------------------------------------------------------
# Optimization with multiple starting points
# -----------------------------------------------------------------------
bounds = [
    (0.05, 0.8),     # gamma
    (0.01, 0.6),     # sigmabar
    (-0.85, 0.85),   # Rrsigma
    (-0.85, -0.01),  # Rxsigma
    (0.01, 0.8),     # sigma0
]

initials = [
    np.array([0.2, 0.2, 0.5, -0.5, 0.1]),
    np.array([0.1, 0.3, 0.0, -0.7, 0.3]),
    np.array([0.3, 0.15, 0.3, -0.4, 0.05]),
]

for i, x0 in enumerate(initials):
    print(f"=== Calibration run {i + 1} ===")
    minimizer_kwargs = {"method": "L-BFGS-B", "bounds": bounds}
    result_global = optimize.basinhopping(
        target, x0, niter=5,
        minimizer_kwargs=minimizer_kwargs, seed=42 + i,
    )

    result_local = optimize.minimize(
        target, result_global.x, method="L-BFGS-B", bounds=bounds,
        options={"maxiter": 500},
    )

    gamma, sigmabar, Rrsigma, Rxsigma, sigma0 = result_local.x
    l2_error = float(result_local.fun)

    conn.execute(
        "INSERT INTO runs (gamma, sigmabar, Rrsigma, Rxsigma, sigma0, l2_error) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (float(gamma), float(sigmabar), float(Rrsigma),
         float(Rxsigma), float(sigma0), l2_error),
    )
    conn.commit()
    print(f"  L2 error: {l2_error:.6f}")
    print(f"  Params: gamma={gamma:.4f} sigmabar={sigmabar:.4f} "
          f"Rrsigma={Rrsigma:.4f} Rxsigma={Rxsigma:.4f} sigma0={sigma0:.4f}")

conn.close()
print("\nCalibration complete. Results stored in /app/calibration.db.")
