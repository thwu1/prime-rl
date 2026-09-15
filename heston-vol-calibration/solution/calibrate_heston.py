#!/usr/bin/env python3
"""
Heston stochastic volatility model calibration pipeline.
Reads market data from SQLite database, calibrates, and outputs results.
"""

import json
import sqlite3
import numpy as np
from scipy.stats import norm
from scipy.optimize import differential_evolution, minimize


# ========================================================================
# Heston characteristic function
# ========================================================================

def heston_cf(u, T, r, kappa, gamma, vbar, v0, rho):
    i = 1j
    alpha = kappa - gamma * rho * i * u
    D = np.sqrt(alpha ** 2 + gamma ** 2 * (u ** 2 + i * u))
    g = (alpha - D) / (alpha + D)
    exp_DT = np.exp(-D * T)

    C = (alpha - D) / (gamma ** 2) * (1.0 - exp_DT) / (1.0 - g * exp_DT)
    A = (r * i * u * T
         + kappa * vbar / (gamma ** 2)
         * ((alpha - D) * T
            - 2.0 * np.log((1.0 - g * exp_DT) / (1.0 - g))))

    return np.exp(A + C * v0)


# ========================================================================
# COS method for European option pricing
# ========================================================================

def cos_call_prices(S0, K_arr, T, r, kappa, gamma, vbar, v0, rho,
                    N=4096, L=12):
    i = 1j
    K_arr = np.asarray(K_arr, dtype=float).reshape(-1)
    x0 = np.log(S0 / K_arr)

    a = -L * np.sqrt(T)
    b = L * np.sqrt(T)
    bma = b - a

    k_idx = np.arange(N).reshape(-1, 1)
    omega = k_idx * np.pi / bma

    c_lo, c_hi = a, 0.0
    arg_hi = omega * (c_hi - a)
    arg_lo = omega * (c_lo - a)

    psi = np.sin(arg_hi) - np.sin(arg_lo)
    psi[1:] = psi[1:] * bma / (k_idx[1:] * np.pi)
    psi[0] = c_hi - c_lo

    denom = 1.0 + omega ** 2
    term1 = (np.cos(arg_hi) * np.exp(c_hi)
             - np.cos(arg_lo) * np.exp(c_lo))
    term2 = (omega * np.sin(arg_hi) * np.exp(c_hi)
             - omega * np.sin(arg_lo) * np.exp(c_lo))
    chi = (term1 + term2) / denom

    H_k = 2.0 / bma * (-chi + psi)

    cf_vals = heston_cf(omega, T, r, kappa, gamma, vbar, v0, rho)
    coeff = cf_vals * H_k
    coeff[0] = 0.5 * coeff[0]

    basis = np.exp(i * np.outer(x0 - a, omega.flatten()))
    put_prices = np.exp(-r * T) * K_arr * np.real(basis @ coeff).flatten()
    call_prices = put_prices + S0 - K_arr * np.exp(-r * T)
    return call_prices


# ========================================================================
# Black-Scholes and implied volatility
# ========================================================================

def bs_call_vec(S0, K, T, r, sigma):
    sigma = np.asarray(sigma, dtype=float)
    d1 = (np.log(S0 / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S0 * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)


def bs_vega_vec(S0, K, T, r, sigma):
    sigma = np.asarray(sigma, dtype=float)
    d1 = (np.log(S0 / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return S0 * np.sqrt(T) * norm.pdf(d1)


def implied_vol_fast(price, S0, K, T, r):
    intrinsic = max(S0 - K * np.exp(-r * T), 0.0)
    if price <= intrinsic + 1e-10:
        return 0.001

    lo, hi = 0.01, 3.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        p_mid = float(bs_call_vec(S0, K, T, r, mid))
        if p_mid < price:
            lo = mid
        else:
            hi = mid
    sigma = 0.5 * (lo + hi)

    for _ in range(100):
        d1 = (np.log(S0 / K) + (r + 0.5 * sigma ** 2) * T) / (
            sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        bs_p = S0 * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        vega = S0 * np.sqrt(T) * norm.pdf(d1)
        if vega < 1e-14:
            sigma += 0.05
            continue
        diff = bs_p - price
        if abs(diff) < 1e-12:
            break
        sigma -= diff / vega
        sigma = np.clip(sigma, 1e-4, 5.0)
    return float(sigma)


# ========================================================================
# Calibration
# ========================================================================

def precompute_market_prices(S0, r, maturities, strikes, market_ivs):
    prices = []
    vegas = []
    for i, T in enumerate(maturities):
        row_p = []
        row_v = []
        for j, K in enumerate(strikes):
            sigma = market_ivs[i][j]
            p = float(bs_call_vec(S0, K, T, r, sigma))
            v = float(bs_vega_vec(S0, K, T, r, sigma))
            row_p.append(p)
            row_v.append(max(v, 1e-6))
        prices.append(row_p)
        vegas.append(row_v)
    return np.array(prices), np.array(vegas)


def calibration_objective(params, S0, r, maturities, strikes,
                          market_prices, market_vegas, N_cos=1024, L_cos=10):
    kappa, gamma, vbar, v0, rho = params
    total = 0.0
    count = 0
    try:
        for i, T in enumerate(maturities):
            model_prices = cos_call_prices(
                S0, strikes, T, r, kappa, gamma, vbar, v0, rho,
                N=N_cos, L=L_cos)
            for j in range(len(strikes)):
                p_model = model_prices[j]
                if np.isnan(p_model) or p_model < -1.0:
                    return 100.0
                diff = (p_model - market_prices[i][j]) / market_vegas[i][j]
                total += diff ** 2
                count += 1
    except Exception:
        return 100.0
    return np.sqrt(total / count)


def calibrate(S0, r, maturities, strikes, market_ivs):
    market_prices, market_vegas = precompute_market_prices(
        S0, r, maturities, strikes, market_ivs)

    bounds = [
        (0.01, 10.0),
        (0.01, 2.0),
        (0.001, 0.5),
        (0.001, 0.5),
        (-0.99, -0.01),
    ]

    args = (S0, r, maturities, strikes, market_prices, market_vegas)

    print("Running differential evolution...", flush=True)
    result_de = differential_evolution(
        calibration_objective,
        bounds,
        args=args,
        seed=42,
        maxiter=200,
        popsize=15,
        tol=1e-9,
        mutation=(0.5, 1.5),
        recombination=0.8,
        polish=False,
    )
    print(f"  DE result: {result_de.x}, obj={result_de.fun:.8f}", flush=True)

    print("Running Nelder-Mead local refinement...", flush=True)
    result_nm = minimize(
        calibration_objective,
        result_de.x,
        args=args,
        method="Nelder-Mead",
        options={"maxiter": 10000, "xatol": 1e-10, "fatol": 1e-12},
    )
    print(f"  NM result: {result_nm.x}, obj={result_nm.fun:.8f}", flush=True)

    x = result_nm.x
    x[0] = np.clip(x[0], 0.01, 10.0)
    x[1] = np.clip(x[1], 0.01, 2.0)
    x[2] = np.clip(x[2], 0.001, 0.5)
    x[3] = np.clip(x[3], 0.001, 0.5)
    x[4] = np.clip(x[4], -0.99, 0.0)
    return x


# ========================================================================
# Data extraction from SQLite
# ========================================================================

def load_market_data():
    conn = sqlite3.connect("/app/options.db")
    c = conn.cursor()

    # Spot price
    c.execute("SELECT value FROM market_info WHERE key='spot_price'")
    S0 = float(c.fetchone()[0])

    # OIS rate (latest date, nearest tenor)
    c.execute("""SELECT rate FROM yield_curves
                 WHERE curve_id='OIS'
                 ORDER BY as_of_date DESC, tenor_years ASC LIMIT 1""")
    r = float(c.fetchone()[0])

    # Clean GOOD-quality call implied vols
    c.execute("""SELECT maturity_years, strike, implied_vol
                 FROM option_quotes
                 WHERE quality_flag='GOOD' AND option_type='C'
                       AND implied_vol IS NOT NULL
                 ORDER BY maturity_years, strike""")
    rows = c.fetchall()
    conn.close()

    maturities = sorted(set(row[0] for row in rows))
    strikes = sorted(set(row[1] for row in rows))
    iv_map = {(row[0], row[1]): row[2] for row in rows}
    market_ivs = [[iv_map[(T, K)] for K in strikes] for T in maturities]

    return S0, r, maturities, strikes, market_ivs


# ========================================================================
# Main pipeline
# ========================================================================

def main():
    S0, r, maturities, strikes, market_ivs = load_market_data()
    print(f"Loaded: spot={S0}, rate={r}, "
          f"{len(maturities)} maturities x {len(strikes)} strikes", flush=True)

    # Calibrate
    params = calibrate(S0, r, maturities, strikes, market_ivs)
    kappa, gamma, vbar, v0, rho = [float(x) for x in params]
    print(f"\nCalibrated: kappa={kappa:.6f} gamma={gamma:.6f} "
          f"vbar={vbar:.6f} v0={v0:.6f} rho={rho:.6f}", flush=True)

    # Reprice and extract IVs
    N_final = 4096
    L_final = 12
    repriced_ivs = []
    sq_err_sum = 0.0
    count = 0
    for i, T in enumerate(maturities):
        prices = cos_call_prices(S0, strikes, T, r,
                                 kappa, gamma, vbar, v0, rho,
                                 N=N_final, L=L_final)
        row_ivs = []
        for j, K in enumerate(strikes):
            iv_m = implied_vol_fast(float(prices[j]), S0, K, T, r)
            row_ivs.append(round(iv_m, 8))
            sq_err_sum += (iv_m - market_ivs[i][j]) ** 2
            count += 1
        repriced_ivs.append(row_ivs)

    rmse_pct = 100.0 * np.sqrt(sq_err_sum / count)
    print(f"Calibration RMSE: {rmse_pct:.6f} pp", flush=True)

    # Feller condition
    feller = bool(2.0 * kappa * vbar > gamma ** 2)

    # Forward variance
    fwd_var = {}
    for T_val in [0.5, 1.0, 2.0, 5.0]:
        ev = vbar + (v0 - vbar) * np.exp(-kappa * T_val)
        fwd_var[f"T_{T_val}"] = round(float(ev), 10)

    # Greeks via finite differences
    dS = 0.5
    dv0 = 0.001
    delta_grid = []
    vega_grid = []

    for i, T in enumerate(maturities):
        prices_up = cos_call_prices(S0 + dS, strikes, T, r,
                                     kappa, gamma, vbar, v0, rho,
                                     N=N_final, L=L_final)
        prices_dn = cos_call_prices(S0 - dS, strikes, T, r,
                                     kappa, gamma, vbar, v0, rho,
                                     N=N_final, L=L_final)
        deltas = ((prices_up - prices_dn) / (2.0 * dS)).tolist()
        delta_grid.append([round(float(d), 8) for d in deltas])

        prices_v_up = cos_call_prices(S0, strikes, T, r,
                                       kappa, gamma, vbar, v0 + dv0, rho,
                                       N=N_final, L=L_final)
        prices_v_dn = cos_call_prices(S0, strikes, T, r,
                                       kappa, gamma, vbar, v0 - dv0, rho,
                                       N=N_final, L=L_final)
        vegas = ((prices_v_up - prices_v_dn) / (2.0 * dv0)).tolist()
        vega_grid.append([round(float(v), 8) for v in vegas])

    results = {
        "calibrated_params": {
            "kappa": round(kappa, 8),
            "gamma": round(gamma, 8),
            "vbar": round(vbar, 8),
            "v0": round(v0, 8),
            "rho": round(rho, 8),
        },
        "calibration_rmse_iv_pct": round(float(rmse_pct), 8),
        "feller_satisfied": feller,
        "forward_variance": fwd_var,
        "repriced_ivs": repriced_ivs,
        "greeks": {
            "delta": delta_grid,
            "vega": vega_grid,
        },
    }

    with open("/app/results.json", "w") as fh:
        json.dump(results, fh, indent=2)

    print("Results written to /app/results.json", flush=True)


if __name__ == "__main__":
    main()
