#!/usr/bin/env python3

"""Heston stochastic volatility model calibration with multi-feed anomaly detection.

1. Explores the SQLite database schema
2. Loads market data from all feeds
3. Calibrates per-feed to detect anomalous feed(s)
4. Calibrates on clean feeds only
5. Writes output files
"""

import json
import sqlite3
import numpy as np
from scipy.optimize import differential_evolution, minimize, brentq
from scipy.stats import norm


# ---------------------------------------------------------------------------
# Database exploration and data loading
# ---------------------------------------------------------------------------

def explore_and_load():
    """Explore the SQLite DB and load all relevant data."""
    conn = sqlite3.connect("/app/options.db")
    cur = conn.cursor()

    # Discover tables
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"Tables: {tables}")

    # Get market config
    cur.execute("SELECT param_name, param_value FROM market_config")
    config = {r[0]: r[1] for r in cur.fetchall()}
    S0 = config["spot_price"]
    r = config["risk_free_rate"]
    print(f"S0={S0}, r={r}")

    # Get feeds
    cur.execute("SELECT feed_id, feed_name FROM feeds")
    feeds = {r[0]: r[1] for r in cur.fetchall()}
    print(f"Feeds: {feeds}")

    # Get instruments
    cur.execute("SELECT DISTINCT expiry FROM instruments ORDER BY expiry")
    maturities = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT strike FROM instruments ORDER BY strike")
    strikes = [r[0] for r in cur.fetchall()]
    print(f"Maturities: {maturities}")
    print(f"Strikes: {strikes}")

    # Load prices per feed
    prices_by_feed = {}
    for fid, fname in feeds.items():
        cur.execute("""
            SELECT i.expiry, i.strike, p.px
            FROM price_observations p
            JOIN instruments i USING(instrument_id)
            WHERE p.feed_id = ?
            ORDER BY i.expiry, i.strike
        """, (fid,))
        rows = cur.fetchall()

        feed_prices = {}
        for expiry, strike, px in rows:
            key = str(expiry)
            if key not in feed_prices:
                feed_prices[key] = []
            feed_prices[key].append(px)
        prices_by_feed[fname] = feed_prices

    # Check quality log
    cur.execute("SELECT f.feed_name, q.message, q.severity FROM quality_log q JOIN feeds f USING(feed_id)")
    for row in cur.fetchall():
        print(f"  [{row[2]}] {row[0]}: {row[1]}")

    conn.close()
    return S0, r, maturities, strikes, feeds, prices_by_feed


# ---------------------------------------------------------------------------
# Heston characteristic function
# ---------------------------------------------------------------------------

def heston_cf(u_arr, r, tau, kappa, gamma, vbar, v0, rho):
    """Characteristic function of log(S_T / S_0) under the Heston model."""
    i = 1j
    u = np.asarray(u_arr, dtype=np.complex128)
    a1 = kappa - gamma * rho * i * u
    D = np.sqrt(a1 ** 2 + gamma ** 2 * (u ** 2 + i * u))
    g = (a1 - D) / (a1 + D)
    exp_neg = np.exp(-D * tau)

    C = (a1 - D) / (gamma ** 2) * (1.0 - exp_neg) / (1.0 - g * exp_neg)
    A = (r * i * u * tau
         + kappa * vbar / (gamma ** 2)
         * ((a1 - D) * tau
            - 2.0 * np.log((1.0 - g * exp_neg) / (1.0 - g))))
    return np.exp(A + C * v0)


# ---------------------------------------------------------------------------
# COS method for European option pricing
# ---------------------------------------------------------------------------

def cos_call_prices(S0, r, tau, strikes, cf_func, N=500, L=8):
    """Price European calls using COS Fourier cosine expansion + put-call parity."""
    i = 1j
    K = np.asarray(strikes, dtype=float).reshape(-1, 1)
    x0 = np.log(S0 / K)
    a = -L * np.sqrt(tau)
    b = L * np.sqrt(tau)

    k = np.arange(N, dtype=float).reshape(1, -1)
    u = k * np.pi / (b - a)

    c_int, d_int = a, 0.0

    psi = (np.sin(k * np.pi * (d_int - a) / (b - a))
           - np.sin(k * np.pi * (c_int - a) / (b - a)))
    psi[:, 1:] *= (b - a) / (k[:, 1:] * np.pi)
    psi[:, 0] = d_int - c_int

    denom = 1.0 + (k * np.pi / (b - a)) ** 2
    expr1 = (np.cos(k * np.pi * (d_int - a) / (b - a)) * np.exp(d_int)
             - np.cos(k * np.pi * (c_int - a) / (b - a)) * np.exp(c_int))
    expr2 = (k * np.pi / (b - a)
             * np.sin(k * np.pi * (d_int - a) / (b - a)) * np.exp(d_int)
             - k * np.pi / (b - a)
             * np.sin(k * np.pi * (c_int - a) / (b - a)) * np.exp(c_int))
    chi = (expr1 + expr2) / denom

    H_k = 2.0 / (b - a) * (-chi + psi)

    cf_vals = cf_func(u.flatten()).reshape(1, -1)

    mat = np.exp(i * (x0 - a) * u)
    temp = cf_vals * H_k
    temp[:, 0] *= 0.5

    put = np.exp(-r * tau) * K * np.real(np.sum(mat * temp, axis=1, keepdims=True))
    call = put + S0 - K * np.exp(-r * tau)
    return call.flatten()


# ---------------------------------------------------------------------------
# Implied volatility
# ---------------------------------------------------------------------------

def bs_call(S, K, sigma, T, r):
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)


def compute_iv(price, S, K, T, r):
    """Black-Scholes implied vol via Brent's method."""
    intrinsic = max(S - K * np.exp(-r * T), 0.0)
    if price <= intrinsic + 1e-8:
        return 0.001
    try:
        return brentq(lambda s: bs_call(S, K, s, T, r) - price, 0.001, 5.0)
    except (ValueError, RuntimeError):
        return 0.001


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def calibrate_heston(S0, r, maturities, strikes, market_prices_dict):
    """Calibrate Heston model to a set of market prices."""
    market_vec = []
    for T in maturities:
        T_str = str(T)
        if T_str in market_prices_dict:
            market_vec.extend(market_prices_dict[T_str])
    market_vec = np.array(market_vec)

    def objective(params):
        kappa, gamma, vbar, v0, rho = params
        model_vec = []
        for T in maturities:
            T_str = str(T)
            if T_str not in market_prices_dict:
                continue
            cf = lambda u, T=T: heston_cf(u, r, T, kappa, gamma, vbar, v0, rho)
            prices = cos_call_prices(S0, r, T, strikes, cf, N=500, L=8)
            model_vec.extend(prices)
        model_vec = np.array(model_vec)
        err = np.sum((model_vec - market_vec) ** 2)
        if not np.isfinite(err):
            return 1e12
        return err

    bounds = [
        (0.01, 10.0),    # kappa
        (0.01, 2.0),     # gamma
        (0.001, 0.5),    # vbar
        (0.001, 0.5),    # v0
        (-0.99, 0.99),   # rho
    ]

    result_global = differential_evolution(
        objective, bounds, seed=42, maxiter=200, tol=1e-10,
        popsize=20, mutation=(0.5, 1.5), recombination=0.7,
    )

    result_local = minimize(
        objective, result_global.x, method="Nelder-Mead",
        options={"maxiter": 10000, "xatol": 1e-10, "fatol": 1e-12},
    )

    return result_local.x, result_local.fun


def main():
    # Step 1: Explore database and load data
    S0, r, maturities, strikes, feeds, prices_by_feed = explore_and_load()

    # Step 2: Per-feed calibration to detect anomalies
    print("\n=== Per-feed calibration ===")
    feed_results = {}
    for fname, fprices in prices_by_feed.items():
        print(f"\nCalibrating on {fname}...")
        params, residual = calibrate_heston(S0, r, maturities, strikes, fprices)
        feed_results[fname] = {"params": params, "residual": residual}
        print(f"  Residual: {residual:.6e}")
        print(f"  Params: kappa={params[0]:.4f}, gamma={params[1]:.4f}, "
              f"vbar={params[2]:.4f}, v0={params[3]:.4f}, rho={params[4]:.4f}")

    # Step 3: Detect anomalous feeds
    feed_names = list(prices_by_feed.keys())

    def cross_predict_error(params_from, prices_to):
        """Compute SSE when using one feed's params to price another feed's data."""
        kappa, gamma, vbar, v0, rho = params_from
        err = 0.0
        for T in maturities:
            T_str = str(T)
            if T_str not in prices_to:
                continue
            cf = lambda u, T=T: heston_cf(u, r, T, kappa, gamma, vbar, v0, rho)
            model = cos_call_prices(S0, r, T, strikes, cf, N=500, L=8)
            mkt = np.array(prices_to[T_str])
            err += np.sum((model - mkt) ** 2)
        return err

    # Compute pairwise bidirectional consistency for all feed pairs
    pair_consistency = {}
    for i in range(len(feed_names)):
        for j in range(i + 1, len(feed_names)):
            f1, f2 = feed_names[i], feed_names[j]
            err_12 = cross_predict_error(feed_results[f1]["params"], prices_by_feed[f2])
            err_21 = cross_predict_error(feed_results[f2]["params"], prices_by_feed[f1])
            pair_consistency[(f1, f2)] = err_12 + err_21
            print(f"  Pair ({f1}, {f2}): mutual error = {err_12 + err_21:.6e}")

    # The most consistent pair identifies the clean feeds
    best_pair = min(pair_consistency, key=pair_consistency.get)
    consistent_feeds = set(best_pair)
    excluded = [f for f in feed_names if f not in consistent_feeds]
    print(f"  Most consistent pair: {best_pair}")
    print(f"  -> Excluding: {excluded}")

    # Step 4: Calibrate on clean feeds only
    print(f"\n=== Final calibration (excluding {excluded}) ===")
    clean_prices = {}
    for fname, fprices in prices_by_feed.items():
        if fname in excluded:
            continue
        for T_str, plist in fprices.items():
            if T_str not in clean_prices:
                clean_prices[T_str] = []
            if not clean_prices[T_str]:
                clean_prices[T_str] = list(plist)
            else:
                # Average prices from clean feeds
                clean_prices[T_str] = [
                    (a + b) / 2.0 for a, b in zip(clean_prices[T_str], plist)
                ]

    final_params, final_residual = calibrate_heston(S0, r, maturities, strikes, clean_prices)
    kappa, gamma, vbar, v0, rho = final_params
    print(f"Final residual: {final_residual:.6e}")
    print(f"Final params: kappa={kappa:.4f}, gamma={gamma:.4f}, "
          f"vbar={vbar:.4f}, v0={v0:.4f}, rho={rho:.4f}")

    # Step 5: Write output files

    # anomaly_report.json
    anomaly_report = {"excluded_feeds": excluded}
    with open("/app/anomaly_report.json", "w") as f:
        json.dump(anomaly_report, f, indent=2)

    # calibrated_params.json
    calibrated = {
        "kappa": float(kappa),
        "gamma": float(gamma),
        "vbar": float(vbar),
        "v0": float(v0),
        "rho": float(rho),
    }
    with open("/app/calibrated_params.json", "w") as f:
        json.dump(calibrated, f, indent=2)

    # model_prices.json (higher resolution COS)
    model_prices = {}
    for T in maturities:
        cf = lambda u, T=T: heston_cf(u, r, T, kappa, gamma, vbar, v0, rho)
        prices = cos_call_prices(S0, r, T, strikes, cf, N=2048, L=10)
        model_prices[str(T)] = [round(float(p), 6) for p in prices]

    with open("/app/model_prices.json", "w") as f:
        json.dump(model_prices, f, indent=2)

    # iv_surface.json
    iv_dict = {}
    for T in maturities:
        ivs = []
        for p, K in zip(model_prices[str(T)], strikes):
            iv = compute_iv(p, S0, K, T, r)
            ivs.append(round(float(iv), 6))
        iv_dict[str(T)] = ivs

    iv_surface = {
        "maturities": maturities,
        "strikes": strikes,
        "implied_vols": iv_dict,
    }
    with open("/app/iv_surface.json", "w") as f:
        json.dump(iv_surface, f, indent=2)

    print("\nAll output files written successfully.")


if __name__ == "__main__":
    main()
