#!/usr/bin/env python3
"""Volatility surface calibration engine — complete solution.

"""

import csv
import json
import math
import os

import numpy as np
from scipy.optimize import minimize


# ---------------------------------------------------------------------------
# Black-Scholes primitives
# ---------------------------------------------------------------------------
def _ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x):
    return math.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)


def _d1(S, K, T, r, q, s):
    return (math.log(S / K) + (r - q + s * s / 2.0) * T) / (s * math.sqrt(T))


def bs_price(S, K, T, r, q, s, otype):
    d1 = _d1(S, K, T, r, q, s)
    d2 = d1 - s * math.sqrt(T)
    if otype == "call":
        return S * math.exp(-q * T) * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
    return K * math.exp(-r * T) * _ncdf(-d2) - S * math.exp(-q * T) * _ncdf(-d1)


def bs_vega(S, K, T, r, q, s):
    d1 = _d1(S, K, T, r, q, s)
    return S * math.exp(-q * T) * _npdf(d1) * math.sqrt(T)


def bs_delta(S, K, T, r, q, s, otype):
    d1 = _d1(S, K, T, r, q, s)
    if otype == "call":
        return math.exp(-q * T) * _ncdf(d1)
    return math.exp(-q * T) * (_ncdf(d1) - 1.0)


def bs_gamma(S, K, T, r, q, s):
    d1 = _d1(S, K, T, r, q, s)
    return math.exp(-q * T) * _npdf(d1) / (S * s * math.sqrt(T))


def bs_theta(S, K, T, r, q, s, otype):
    d1 = _d1(S, K, T, r, q, s)
    d2 = d1 - s * math.sqrt(T)
    term1 = -S * math.exp(-q * T) * _npdf(d1) * s / (2.0 * math.sqrt(T))
    if otype == "call":
        th = term1 + q * S * math.exp(-q * T) * _ncdf(d1) - r * K * math.exp(-r * T) * _ncdf(d2)
    else:
        th = term1 - q * S * math.exp(-q * T) * _ncdf(-d1) + r * K * math.exp(-r * T) * _ncdf(-d2)
    return th / 365.0


def bs_rho(S, K, T, r, q, s, otype):
    d2 = _d1(S, K, T, r, q, s) - s * math.sqrt(T)
    if otype == "call":
        return K * T * math.exp(-r * T) * _ncdf(d2) / 100.0
    return -K * T * math.exp(-r * T) * _ncdf(-d2) / 100.0


# ---------------------------------------------------------------------------
# Implied volatility — Newton-Raphson + bisection fallback
# ---------------------------------------------------------------------------
def implied_vol(price_mkt, S, K, T, r, q, otype):
    # Brenner-Subrahmanyam initial guess
    sig = max(0.01, min(math.sqrt(2.0 * math.pi / T) * price_mkt / S, 5.0))
    for _ in range(200):
        try:
            p = bs_price(S, K, T, r, q, sig, otype)
            v = bs_vega(S, K, T, r, q, sig)
            if abs(v) < 1e-20:
                break
            diff = p - price_mkt
            if abs(diff) < 1e-10:
                return sig
            sig -= diff / v
            sig = max(0.001, min(sig, 10.0))
        except (ValueError, OverflowError):
            break
    # bisection fallback
    lo, hi = 0.001, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        try:
            p = bs_price(S, K, T, r, q, mid, otype)
        except (ValueError, OverflowError):
            hi = mid
            continue
        if p < price_mkt:
            lo = mid
        else:
            hi = mid
        if abs(p - price_mkt) < 1e-10:
            return mid
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# SVI model
# ---------------------------------------------------------------------------
def svi_w(k, a, b, rho, m, sig):
    return a + b * (rho * (k - m) + math.sqrt((k - m) ** 2 + sig ** 2))


def svi_wp(k, a, b, rho, m, sig):
    return b * (rho + (k - m) / math.sqrt((k - m) ** 2 + sig ** 2))


def svi_wpp(k, a, b, rho, m, sig):
    return b * sig ** 2 / ((k - m) ** 2 + sig ** 2) ** 1.5


def fit_svi(ks, ws):
    """Fit SVI parameters via L-BFGS-B with multi-start."""
    ks_np = np.asarray(ks)
    ws_np = np.asarray(ws)

    def obj(p):
        a, b, rho, m, sig = p
        pred = a + b * (rho * (ks_np - m) + np.sqrt((ks_np - m) ** 2 + sig ** 2))
        return float(np.sum((pred - ws_np) ** 2))

    bounds = [(None, None), (1e-8, None), (-0.999, 0.999), (None, None), (1e-5, None)]
    best, best_cost = None, float("inf")
    for a0 in [0.001, 0.005, 0.01, 0.02]:
        for b0 in [0.01, 0.025, 0.05]:
            for rho0 in [-0.5, -0.3, -0.1]:
                x0 = [a0, b0, rho0, 0.0, 0.1]
                try:
                    res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds,
                                   options={"maxiter": 10000, "ftol": 1e-18})
                    if res.fun < best_cost:
                        best_cost = res.fun
                        best = res.x
                except Exception:
                    pass
    if best is None:
        raise RuntimeError("SVI fitting failed for all initial guesses")
    a, b, rho, m, sig = best
    return {"a": float(a), "b": float(b), "rho": float(rho), "m": float(m), "sigma": float(sig)}


# ---------------------------------------------------------------------------
# Arbitrage checks
# ---------------------------------------------------------------------------
def check_butterfly(p, n=400):
    a, b, rho, m, sig = p["a"], p["b"], p["rho"], p["m"], p["sigma"]
    for k in (i * 0.0025 for i in range(-200, 201)):
        w = svi_w(k, a, b, rho, m, sig)
        if w <= 0:
            return False
        wp = svi_wp(k, a, b, rho, m, sig)
        wpp = svi_wpp(k, a, b, rho, m, sig)
        g = (1.0 - k * wp / (2.0 * w)) ** 2 - wp ** 2 / 4.0 * (1.0 / w + 0.25) + wpp / 2.0
        if g < -1e-8:
            return False
    return True


def check_calendar(all_p, S, r, q, strikes):
    exps = sorted(all_p.keys(), key=int)
    for K in strikes:
        prev = None
        for es in exps:
            T = int(es) / 365.0
            F = S * math.exp((r - q) * T)
            k = math.log(K / F)
            p = all_p[es]
            w = svi_w(k, p["a"], p["b"], p["rho"], p["m"], p["sigma"])
            if prev is not None and w < prev - 1e-8:
                return False
            prev = w
    return True


# ---------------------------------------------------------------------------
# Monte Carlo — vectorised, flat vol from SVI surface per exotic
# ---------------------------------------------------------------------------
def _get_exotic_vol(spec, all_p, S0, r, q):
    """Look up the BS implied vol from the calibrated SVI surface at the
    exotic's strike and expiration."""
    T = spec["expiry_days"] / 365.0
    K = spec["strike"]
    F = S0 * math.exp((r - q) * T)
    k = math.log(K / F)
    exp_str = str(spec["expiry_days"])

    # Use closest expiration's SVI params (exact match expected)
    exps = sorted(all_p.keys(), key=int)
    if exp_str in all_p:
        p = all_p[exp_str]
    else:
        # Interpolate total variance between bracketing slices
        ed = [int(e) for e in exps]
        tau_days = spec["expiry_days"]
        for i in range(len(ed) - 1):
            if ed[i] <= tau_days <= ed[i + 1]:
                p1, p2 = all_p[exps[i]], all_p[exps[i + 1]]
                w1 = svi_w(k, p1["a"], p1["b"], p1["rho"], p1["m"], p1["sigma"])
                w2 = svi_w(k, p2["a"], p2["b"], p2["rho"], p2["m"], p2["sigma"])
                alpha = (tau_days - ed[i]) / (ed[i + 1] - ed[i])
                w = w1 * (1.0 - alpha) + w2 * alpha
                return max(math.sqrt(max(w, 1e-10) / T), 0.01)
        p = all_p[exps[-1]]

    w = svi_w(k, p["a"], p["b"], p["rho"], p["m"], p["sigma"])
    return max(math.sqrt(max(w, 1e-10) / T), 0.01)


def price_exotic(spec, all_p, S0, r, q, rng, n_paths=200_000):
    T = spec["expiry_days"] / 365.0
    K = spec["strike"]
    vol = _get_exotic_vol(spec, all_p, S0, r, q)

    n_steps = max(int(252 * T), 1)
    dt = T / n_steps

    # Build monitor set for Asian
    monitor_set = None
    if spec["type"] == "arithmetic_asian_call":
        freq = spec.get("monitoring_frequency_days", 1)
        monitor_set = set()
        n_mon = max(int(spec["expiry_days"] / freq), 1)
        for m_idx in range(1, n_mon + 1):
            idx = min(int(m_idx * freq / 365.0 / dt), n_steps - 1)
            monitor_set.add(idx)
        monitor_set.add(n_steps - 1)

    # Simulate GBM paths with constant vol
    Z = rng.standard_normal((n_paths, n_steps))
    log_increments = (r - q - vol ** 2 / 2.0) * dt + vol * math.sqrt(dt) * Z
    log_S = np.log(S0) + np.cumsum(log_increments, axis=1)
    S_all = np.exp(log_S)

    S_final = S_all[:, -1]
    S_min = np.minimum(S0, np.min(S_all, axis=1))
    S_max = np.maximum(S0, np.max(S_all, axis=1))

    if spec["type"] == "down_and_out_call":
        barrier = spec["barrier"]
        alive = S_min > barrier
        payoffs = np.maximum(S_final - K, 0) * alive
    elif spec["type"] == "up_and_out_call":
        barrier = spec["barrier"]
        alive = S_max < barrier
        payoffs = np.maximum(S_final - K, 0) * alive
    elif spec["type"] == "arithmetic_asian_call":
        monitor_indices = sorted(monitor_set) if monitor_set else list(range(n_steps))
        avg_price = np.mean(S_all[:, monitor_indices], axis=1)
        payoffs = np.maximum(avg_price - K, 0)
    elif spec["type"] == "down_and_in_put":
        barrier = spec["barrier"]
        knocked_in = S_min <= barrier
        payoffs = np.maximum(K - S_final, 0) * knocked_in
    else:
        raise ValueError(f"Unknown exotic type: {spec['type']}")

    disc = math.exp(-r * T)
    price = disc * float(np.mean(payoffs))
    se = disc * float(np.std(payoffs)) / math.sqrt(n_paths)
    return price, se


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # ---- Read data ----
    chain = []
    with open("/app/data/option_chain.csv") as f:
        for row in csv.DictReader(f):
            chain.append({
                "expiry_days": int(row["expiry_days"]),
                "strike": int(row["strike"]),
                "option_type": row["option_type"],
                "mid_price": float(row["mid_price"]),
            })
    S = 5000.0
    r = 0.045
    q = 0.015

    os.makedirs("/app/output", exist_ok=True)

    # ---- Step 1: Implied vols ----
    iv_rows = []
    for o in chain:
        T = o["expiry_days"] / 365.0
        iv = implied_vol(o["mid_price"], S, o["strike"], T, r, q, o["option_type"])
        iv_rows.append({
            "expiry_days": o["expiry_days"],
            "strike": o["strike"],
            "option_type": o["option_type"],
            "implied_vol": iv,
        })

    with open("/app/output/implied_vols.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["expiry_days", "strike", "option_type", "implied_vol"])
        w.writeheader()
        w.writerows(iv_rows)
    print("Wrote implied_vols.csv")

    # ---- Step 2: Fit SVI per expiration ----
    expirations = sorted(set(row["expiry_days"] for row in iv_rows))
    svi_params = {}
    for exp in expirations:
        T = exp / 365.0
        F = S * math.exp((r - q) * T)
        strike_iv = {}
        for row in iv_rows:
            if row["expiry_days"] != exp:
                continue
            strike_iv.setdefault(row["strike"], []).append(row["implied_vol"])
        ks, ws = [], []
        for K in sorted(strike_iv):
            avg_iv = sum(strike_iv[K]) / len(strike_iv[K])
            ks.append(math.log(K / F))
            ws.append(avg_iv ** 2 * T)
        svi_params[str(exp)] = fit_svi(ks, ws)

    with open("/app/output/svi_params.json", "w") as f:
        json.dump(svi_params, f, indent=2)
    print("Wrote svi_params.json")

    # ---- Step 3: Arbitrage checks ----
    bf = all(check_butterfly(svi_params[e]) for e in svi_params)
    strikes_all = sorted(set(row["strike"] for row in iv_rows))
    cf = check_calendar(svi_params, S, r, q, strikes_all)
    with open("/app/output/arbitrage_check.json", "w") as f:
        json.dump({"butterfly_free": bf, "calendar_free": cf}, f, indent=2)
    print(f"Wrote arbitrage_check.json  butterfly_free={bf}  calendar_free={cf}")

    # ---- Step 4: Exotic prices ----
    with open("/app/data/exotic_specs.json") as f:
        specs = json.load(f)
    rng = np.random.default_rng(42)
    exotic_out = {}
    for name, spec in specs.items():
        price, se = price_exotic(spec, svi_params, S, r, q, rng, n_paths=250_000)
        exotic_out[name] = {"price": round(price, 4), "std_error": round(se, 4)}
        print(f"  {name}: price={price:.4f}  se={se:.4f}")
    with open("/app/output/exotic_prices.json", "w") as f:
        json.dump(exotic_out, f, indent=2)
    print("Wrote exotic_prices.json")

    # ---- Step 5: Portfolio Greeks ----
    with open("/app/data/portfolio.json") as f:
        portfolio = json.load(f)

    iv_map = {(r["expiry_days"], r["strike"], r["option_type"]): r["implied_vol"] for r in iv_rows}
    totals = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    for pos in portfolio["positions"]:
        exp = pos["expiry_days"]
        K = pos["strike"]
        ot = pos["option_type"]
        qty = pos["quantity"]
        sign = 1 if pos["side"] == "long" else -1
        T = exp / 365.0

        iv_val = iv_map.get((exp, K, ot))
        if iv_val is None:
            F = S * math.exp((r - q) * T)
            k = math.log(K / F)
            p = svi_params[str(exp)]
            wv = svi_w(k, p["a"], p["b"], p["rho"], p["m"], p["sigma"])
            iv_val = math.sqrt(max(wv, 1e-10) / T)

        totals["delta"] += sign * qty * bs_delta(S, K, T, r, q, iv_val, ot)
        totals["gamma"] += sign * qty * bs_gamma(S, K, T, r, q, iv_val)
        totals["vega"] += sign * qty * bs_vega(S, K, T, r, q, iv_val)
        totals["theta"] += sign * qty * bs_theta(S, K, T, r, q, iv_val, ot)
        totals["rho"] += sign * qty * bs_rho(S, K, T, r, q, iv_val, ot)

    totals = {k: round(v, 8) for k, v in totals.items()}
    with open("/app/output/portfolio_greeks.json", "w") as f:
        json.dump(totals, f, indent=2)
    print(f"Wrote portfolio_greeks.json: {totals}")


if __name__ == "__main__":
    main()
