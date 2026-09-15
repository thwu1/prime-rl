#!/usr/bin/env python3

"""Calibrate SZHW model to market data.

Reads market data from /app/market_data.json, uses the SZHW pricer at
/app/szhw_pricer.py, runs global (basin-hopping) + local (L-BFGS-B)
optimization, and writes calibrated parameters + model prices to
/app/results.json.
"""
import numpy as np
import scipy.optimize as optimize
import scipy.stats as st
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
# Optimization
# -----------------------------------------------------------------------
# Bounds: gamma, sigmabar, Rrsigma, Rxsigma, sigma0
bounds = [
    (0.05, 0.8),    # gamma
    (0.01, 0.6),    # sigmabar
    (-0.85, 0.85),  # Rrsigma
    (-0.85, -0.01), # Rxsigma
    (0.01, 0.8),    # sigma0
]
initial = np.array([0.1, 0.3, 0.0, -0.5, 0.3])

print("=== Global optimization (basin-hopping) ===")
minimizer_kwargs = {"method": "L-BFGS-B", "bounds": bounds}
result_global = optimize.basinhopping(
    target, initial, niter=10,
    minimizer_kwargs=minimizer_kwargs, seed=42,
)
print(f"Global optimum error: {result_global.fun:.6f}")
print(f"Parameters: {result_global.x}")

print("\n=== Local refinement (L-BFGS-B) ===")
result_local = optimize.minimize(
    target, result_global.x, method="L-BFGS-B", bounds=bounds,
    options={"maxiter": 500},
)
print(f"Local optimum error: {result_local.fun:.6f}")
print(f"Parameters: {result_local.x}")

gamma_est, sigmabar_est, Rrsigma_est, Rxsigma_est, sigma0_est = result_local.x


# -----------------------------------------------------------------------
# Compute final model prices
# -----------------------------------------------------------------------
model_prices = compute_call_prices(
    S0, K, T, P0T, kappa, Rxr, lambd, eta,
    gamma_est, sigmabar_est, Rrsigma_est, Rxsigma_est, sigma0_est,
)


# -----------------------------------------------------------------------
# Implied volatility extraction (Black-Scholes)
# -----------------------------------------------------------------------
def bs_call(S0, K_val, sigma, T, r):
    d1 = (np.log(S0 / K_val) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return st.norm.cdf(d1) * S0 - st.norm.cdf(d2) * K_val * np.exp(-r * T)


def implied_vol(price, S0, K_val, T, r):
    func = lambda sigma: bs_call(S0, K_val, sigma, T, r) - price
    try:
        return float(optimize.brentq(func, 0.001, 5.0))
    except Exception:
        sigmas = np.linspace(0.01, 3.0, 5000)
        errors = [abs(bs_call(S0, K_val, s, T, r) - price) for s in sigmas]
        return float(sigmas[np.argmin(errors)])


model_ivs = [implied_vol(p, S0, k, T, r) for p, k in zip(model_prices, K)]


# -----------------------------------------------------------------------
# Write results
# -----------------------------------------------------------------------
results = {
    "calibrated_params": {
        "gamma": float(gamma_est),
        "sigmabar": float(sigmabar_est),
        "Rrsigma": float(Rrsigma_est),
        "Rxsigma": float(Rxsigma_est),
        "sigma0": float(sigma0_est),
    },
    "model_call_prices": [float(p) for p in model_prices],
    "model_implied_vols": [float(iv) for iv in model_ivs],
}

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

final_error = np.linalg.norm(np.array(model_prices) - market_prices)
print(f"\nFinal calibration error (L2): {final_error:.6f}")
print("Results written to /app/results.json")
