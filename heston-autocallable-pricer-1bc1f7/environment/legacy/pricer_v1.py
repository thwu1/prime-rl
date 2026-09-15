#!/usr/bin/env python3
"""Derivatives Pricing Engine v1 — prototype implementation."""

import argparse
import json
import sys
import numpy as np
from scipy import integrate


# ---------------------------------------------------------------------------
# Heston semi-analytical European call
# ---------------------------------------------------------------------------

def heston_call_price(S, K, r, T, v0, theta, kappa, sigma, rho, q=0.0):
    def _integrand(u, j):
        if j == 1:
            uj = 0.5
            bj = kappa - rho * sigma
        else:
            uj = -0.5
            bj = kappa
        a = kappa * theta
        xi = bj - rho * sigma * 1j * u
        d = np.sqrt(xi ** 2 - sigma ** 2 * (2.0 * uj * 1j * u - u ** 2))

        g = (xi + d) / (xi - d)
        e_dT = np.exp(d * T)

        D_val = ((xi + d) / sigma ** 2) * (1.0 - e_dT) / (1.0 - g * e_dT)
        C_val = (r - q) * 1j * u * T + (a / sigma ** 2) * (
            (xi + d) * T - 2.0 * np.log((1.0 - g * e_dT) / (1.0 - g))
        )
        f = np.exp(C_val + D_val * v0 + 1j * u * np.log(S))
        return np.real(np.exp(-1j * u * np.log(K)) * f / (1j * u))

    I1, _ = integrate.quad(lambda u: _integrand(u, 1), 1e-15, 500.0, limit=2000)
    I2, _ = integrate.quad(lambda u: _integrand(u, 2), 1e-15, 500.0, limit=2000)
    P1 = 0.5 + I1 / np.pi
    P2 = 0.5 + I2 / np.pi
    return max(S * np.exp(-q * T) * P1 - K * np.exp(-r * T) * P2, 0.0)


# ---------------------------------------------------------------------------
# Correlation matrix cleaning
# ---------------------------------------------------------------------------

def is_psd(matrix, tol=1e-10):
    eigenvalues = np.linalg.eigvalsh(np.asarray(matrix, dtype=float))
    return bool(np.all(eigenvalues >= -tol))


def clean_correlation_matrix(C):
    C = np.array(C, dtype=float)
    eigenvalues, eigenvectors = np.linalg.eigh(C)
    eigenvalues_orig = eigenvalues.copy()
    eigenvalues_floored = np.maximum(eigenvalues, 0.0)

    C_new = eigenvectors @ np.diag(eigenvalues_floored) @ eigenvectors.T
    C_clean = (C_new + C_new.T) / 2.0
    np.fill_diagonal(C_clean, 1.0)

    max_change = float(np.max(np.abs(eigenvalues_floored - eigenvalues_orig)))
    return C_clean, max_change


# ---------------------------------------------------------------------------
# Multi-asset Heston Monte Carlo
# ---------------------------------------------------------------------------

def build_2n_correlation(assets, equity_corr):
    n = len(assets)
    big = np.eye(2 * n)
    for i in range(n):
        big[2 * i, 2 * i + 1] = assets[i]["rho"]
        big[2 * i + 1, 2 * i] = assets[i]["rho"]
        for j in range(i + 1, n):
            big[2 * i, 2 * j] = equity_corr[i][j]
            big[2 * j, 2 * i] = equity_corr[i][j]
    if not is_psd(big):
        big, _ = clean_correlation_matrix(big)
    return big


def simulate_multi_asset_heston(assets, equity_corr, T, n_steps, n_paths, r, seed):
    n = len(assets)
    dt = T / n_steps
    sqrt_dt = np.sqrt(dt)
    rng = np.random.default_rng(seed)

    big_corr = build_2n_correlation(assets, equity_corr)
    big_corr += np.eye(2 * n) * 1e-12
    L = np.linalg.cholesky(big_corr)

    log_S = np.zeros((n_paths, n))
    v = np.zeros((n_paths, n))
    for i, a in enumerate(assets):
        log_S[:, i] = np.log(a["spot"])
        v[:, i] = a["v0"]

    spot_paths = np.zeros((n_paths, n_steps + 1, n))
    for i in range(n):
        spot_paths[:, 0, i] = assets[i]["spot"]

    for t_idx in range(n_steps):
        Z = rng.standard_normal((n_paths, 2 * n))
        Z_corr = Z @ L.T
        for i, a in enumerate(assets):
            W_spot = Z_corr[:, 2 * i]
            W_vol = Z_corr[:, 2 * i + 1]
            sqrt_v = np.sqrt(np.maximum(v[:, i], 0.0))
            log_S[:, i] += (r - a["div_yield"] - 0.5 * v[:, i]) * dt + sqrt_v * W_spot * sqrt_dt
            v[:, i] += a["kappa"] * (a["theta"] - v[:, i]) * dt + a["sigma"] * sqrt_v * W_vol * sqrt_dt
            v[:, i] = np.maximum(v[:, i], 0.0)
        for i in range(n):
            spot_paths[:, t_idx + 1, i] = np.exp(log_S[:, i])

    return spot_paths


# ---------------------------------------------------------------------------
# Autocallable pricer
# ---------------------------------------------------------------------------

def price_autocallable(config):
    assets = config["assets"]
    obs_times = sorted(config["observation_times"])
    n_obs = len(obs_times)
    autocall_barrier = config["autocall_barrier"]
    coupon_barrier = config["coupon_barrier"]
    coupon_rate = config["coupon_rate"]
    ki_barrier = config.get("knock_in_barrier")
    snowball = config.get("snowball", False)
    notional = config["notional"]
    r = config["risk_free_rate"]
    n_paths = config["n_paths"]
    seed = config["seed"]

    T_max = obs_times[-1]
    n_steps = max(int(round(T_max * config["n_steps_per_year"])), 1)
    dt = T_max / n_steps

    spot_paths = simulate_multi_asset_heston(
        assets, config["correlation_matrix"], T_max, n_steps, n_paths, r, seed
    )

    S0 = np.array([a["spot"] for a in assets])
    perf = spot_paths / S0[np.newaxis, np.newaxis, :]
    worst_of_all = np.min(perf, axis=2)

    obs_steps = [min(int(round(t / dt)), n_steps) for t in obs_times]

    if ki_barrier is not None:
        knocked_in = np.zeros(n_paths, dtype=bool)
        for step_idx in obs_steps:
            knocked_in |= worst_of_all[:, step_idx] < ki_barrier
    else:
        knocked_in = np.zeros(n_paths, dtype=bool)

    pv_cashflows = np.zeros(n_paths)
    alive = np.ones(n_paths, dtype=bool)
    coupon_count = np.zeros(n_paths)
    autocall_probs = np.zeros(n_obs)

    for k in range(n_obs):
        t_k = obs_times[k]
        df = np.exp(-r * t_k)
        wo_k = worst_of_all[:, obs_steps[k]]

        earns = alive & (wo_k >= coupon_barrier)
        pv_cashflows += np.where(earns, coupon_rate * notional * df, 0.0)
        coupon_count += np.where(earns, 1.0, 0.0)

        autocalled = alive & (wo_k >= autocall_barrier)
        if np.any(autocalled):
            autocall_probs[k] = float(np.sum(autocalled)) / n_paths
            pv_cashflows[autocalled] += notional * df
            alive[autocalled] = False

    not_autocalled = alive
    if np.any(not_autocalled):
        t_mat = obs_times[-1]
        df_mat = np.exp(-r * t_mat)
        wo_final = worst_of_all[:, obs_steps[-1]]
        if ki_barrier is not None:
            ki_alive = not_autocalled & knocked_in
            nki_alive = not_autocalled & ~knocked_in
            pv_cashflows[ki_alive] += notional * np.minimum(1.0, wo_final[ki_alive]) * df_mat
            pv_cashflows[nki_alive] += notional * df_mat
        else:
            pv_cashflows[not_autocalled] += notional * df_mat

    price = float(np.mean(pv_cashflows) / notional)
    std_err = float(np.std(pv_cashflows) / (notional * np.sqrt(n_paths)))

    return {
        "price": price,
        "std_error": std_err,
        "autocall_prob": [float(p) for p in autocall_probs],
        "expected_coupon_count": float(np.mean(coupon_count)),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    hc = sub.add_parser("heston-call")
    hc.add_argument("--spot", type=float, required=True)
    hc.add_argument("--strike", type=float, required=True)
    hc.add_argument("--rate", type=float, required=True)
    hc.add_argument("--maturity", type=float, required=True)
    hc.add_argument("--v0", type=float, required=True)
    hc.add_argument("--theta", type=float, required=True)
    hc.add_argument("--kappa", type=float, required=True)
    hc.add_argument("--sigma", type=float, required=True)
    hc.add_argument("--rho", type=float, required=True)
    hc.add_argument("--div-yield", type=float, default=0.0)

    cc = sub.add_parser("clean-corr")
    cc.add_argument("--input-file", required=True)
    cc.add_argument("--output-file", required=True)

    ac = sub.add_parser("autocallable")
    ac.add_argument("--config", required=True)

    args = parser.parse_args()

    if args.command == "heston-call":
        p = heston_call_price(
            args.spot, args.strike, args.rate, args.maturity,
            args.v0, args.theta, args.kappa, args.sigma,
            args.rho, args.div_yield,
        )
        print(json.dumps({"price": float(p)}))
    elif args.command == "clean-corr":
        with open(args.input_file) as f:
            matrix = json.load(f)
        M = np.array(matrix, dtype=float)
        before = is_psd(M)
        if before:
            cleaned = M.copy()
            mc = 0.0
        else:
            cleaned, mc = clean_correlation_matrix(M)
        with open(args.output_file, "w") as f:
            json.dump(cleaned.tolist(), f)
        print(json.dumps({
            "is_psd_before": before,
            "is_psd_after": True,
            "max_abs_eigenvalue_change": mc,
        }))
    elif args.command == "autocallable":
        with open(args.config) as f:
            config = json.load(f)
        print(json.dumps(price_autocallable(config)))


if __name__ == "__main__":
    main()
