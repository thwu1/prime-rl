#!/usr/bin/env python3

"""Read best calibration run from SQLite, produce results.json and smile.csv."""
import numpy as np
import scipy.optimize as optimize
import scipy.stats as st
import sqlite3
import json
import csv
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
market_prices = market["call_prices"]
P0T = np.exp(-r * T)

kappa = market["szhw_fixed_params"]["kappa"]
Rxr = market["szhw_fixed_params"]["Rxr"]
lambd = market["szhw_fixed_params"]["lambd"]
eta = market["szhw_fixed_params"]["eta"]

# -----------------------------------------------------------------------
# Read best run from SQLite
# -----------------------------------------------------------------------
conn = sqlite3.connect("/app/calibration.db")
row = conn.execute(
    "SELECT gamma, sigmabar, Rrsigma, Rxsigma, sigma0, l2_error "
    "FROM runs ORDER BY l2_error ASC LIMIT 1"
).fetchone()
conn.close()

gamma, sigmabar, Rrsigma, Rxsigma, sigma0, l2_error = row
print(f"Best run: L2 error = {l2_error:.6f}")
print(f"  gamma={gamma:.4f}  sigmabar={sigmabar:.4f}  "
      f"Rrsigma={Rrsigma:.4f}  Rxsigma={Rxsigma:.4f}  sigma0={sigma0:.4f}")

# -----------------------------------------------------------------------
# Compute model prices with best parameters
# -----------------------------------------------------------------------
model_prices = compute_call_prices(
    S0, K, T, P0T, kappa, Rxr, lambd, eta,
    gamma, sigmabar, Rrsigma, Rxsigma, sigma0,
)

# -----------------------------------------------------------------------
# Black-Scholes implied volatility extraction
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
# Write results.json
# -----------------------------------------------------------------------
results = {
    "calibrated_params": {
        "gamma": gamma,
        "sigmabar": sigmabar,
        "Rrsigma": Rrsigma,
        "Rxsigma": Rxsigma,
        "sigma0": sigma0,
    },
    "model_call_prices": [float(p) for p in model_prices],
    "model_implied_vols": [float(iv) for iv in model_ivs],
}

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

# -----------------------------------------------------------------------
# Write smile.csv
# -----------------------------------------------------------------------
with open("/app/smile.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["strike", "model_price", "market_price", "implied_vol"])
    for k, mp, mktp, iv in zip(K, model_prices, market_prices, model_ivs):
        writer.writerow([k, mp, mktp, iv])

print("Report written to /app/results.json and /app/smile.csv")
