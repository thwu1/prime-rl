#!/usr/bin/env python3
"""
Heston Stochastic Volatility Pricing Engine with Multi-Asset Autocallable Pricer.

Implements:
1. Semi-analytical Heston European call pricing (Gatheral / Albrecher formulation)
2. Correlation matrix repair via spectral decomposition (Rebonato-Jäckel)
3. Multi-asset correlated Heston Monte Carlo simulation
4. Worst-of autocallable note pricing with coupon barriers, autocall triggers,
   snowball accumulation, and continuous knock-in monitoring
"""

import argparse
import json
import sys
import numpy as np
from scipy import integrate


# =============================================================================
# 1. HESTON ANALYTICAL PRICER
# =============================================================================

def heston_call_price(S, K, r, T, v0, theta, kappa, sigma, rho, q=0.0):
    """
    European call price under the Heston (1993) stochastic volatility model.

    Uses the "Heston 2" / Gatheral (2006) / Albrecher et al. (2007) formulation
    that avoids the complex logarithm branch-cut discontinuity
    ("Little Heston Trap").

    Parameters
    ----------
    S : float – spot price
    K : float – strike price
    r : float – risk-free rate
    T : float – time to maturity (years)
    v0 : float – initial variance
    theta : float – long-term variance
    kappa : float – mean-reversion speed
    sigma : float – vol of vol
    rho : float – spot-vol correlation
    q : float – continuous dividend yield (default 0)
    """

    def _integrand(u, j):
        """Compute Re[exp(-iu*ln(K)) * f_j(u) / (iu)] for P_j integral."""
        # Measure-dependent parameters
        if j == 1:
            uj = 0.5
            bj = kappa - rho * sigma
        else:
            uj = -0.5
            bj = kappa

        a = kappa * theta

        # xi = b_j - rho*sigma*i*u
        xi = bj - rho * sigma * 1j * u

        # Discriminant: d = sqrt(xi^2 - sigma^2*(2*u_j*i*u - u^2))
        d = np.sqrt(xi ** 2 - sigma ** 2 * (2.0 * uj * 1j * u - u ** 2))

        # Gatheral formulation: g = (xi - d) / (xi + d)
        g = (xi - d) / (xi + d)
        e_neg_dT = np.exp(-d * T)

        # Riccati solutions
        D_val = ((xi - d) / sigma ** 2) * (1.0 - e_neg_dT) / (1.0 - g * e_neg_dT)

        C_val = (r - q) * 1j * u * T + (a / sigma ** 2) * (
            (xi - d) * T - 2.0 * np.log((1.0 - g * e_neg_dT) / (1.0 - g))
        )

        # Characteristic function
        f = np.exp(C_val + D_val * v0 + 1j * u * np.log(S))

        return np.real(np.exp(-1j * u * np.log(K)) * f / (1j * u))

    # Numerical integration for P1 and P2
    I1, _ = integrate.quad(lambda u: _integrand(u, 1), 1e-15, 500.0, limit=2000)
    I2, _ = integrate.quad(lambda u: _integrand(u, 2), 1e-15, 500.0, limit=2000)

    P1 = 0.5 + I1 / np.pi
    P2 = 0.5 + I2 / np.pi

    price = S * np.exp(-q * T) * P1 - K * np.exp(-r * T) * P2
    return max(price, 0.0)


# =============================================================================
# 2. CORRELATION MATRIX CLEANING
# =============================================================================

def is_psd(matrix, tol=1e-10):
    """Check whether a symmetric matrix is positive semi-definite."""
    eigenvalues = np.linalg.eigvalsh(np.asarray(matrix, dtype=float))
    return bool(np.all(eigenvalues >= -tol))


def clean_correlation_matrix(C):
    """
    Clean a correlation matrix via spectral decomposition (Rebonato-Jäckel).

    1. Eigendecompose C = S * Lambda * S^T
    2. Floor negative eigenvalues to 0
    3. Reconstruct C' = S * Lambda' * S^T
    4. Rescale to unit diagonal: T^{-1/2} * C' * T^{-1/2}

    Returns (cleaned_matrix, max_abs_eigenvalue_change).
    """
    C = np.array(C, dtype=float)
    eigenvalues, eigenvectors = np.linalg.eigh(C)

    eigenvalues_orig = eigenvalues.copy()
    eigenvalues_floored = np.maximum(eigenvalues, 0.0)

    # Reconstruct with floored eigenvalues
    C_new = eigenvectors @ np.diag(eigenvalues_floored) @ eigenvectors.T

    # Rescale to unit diagonal
    diag_vals = np.diag(C_new)
    diag_vals = np.maximum(diag_vals, 1e-15)  # safety
    d_inv = 1.0 / np.sqrt(diag_vals)
    C_clean = np.outer(d_inv, d_inv) * C_new

    # Ensure exact symmetry and unit diagonal
    C_clean = (C_clean + C_clean.T) / 2.0
    np.fill_diagonal(C_clean, 1.0)

    max_change = float(np.max(np.abs(eigenvalues_floored - eigenvalues_orig)))

    return C_clean, max_change


# =============================================================================
# 3. MULTI-ASSET HESTON MONTE CARLO
# =============================================================================

def build_2n_correlation(assets, equity_corr):
    """
    Build a 2N x 2N correlation matrix from:
    - N x N equity correlations (spot-spot across assets)
    - per-asset spot-vol correlations (rho_i)

    Ordering: (W_1^spot, W_1^vol, W_2^spot, W_2^vol, ...)

    Cross-asset vol-vol and cross-asset equity-vol correlations are zero.
    """
    n = len(assets)
    big = np.eye(2 * n)

    for i in range(n):
        # Intra-asset spot-vol correlation
        big[2 * i, 2 * i + 1] = assets[i]["rho"]
        big[2 * i + 1, 2 * i] = assets[i]["rho"]

        for j in range(i + 1, n):
            # Inter-asset spot-spot correlation
            big[2 * i, 2 * j] = equity_corr[i][j]
            big[2 * j, 2 * i] = equity_corr[i][j]

    # Clean to PSD if needed
    if not is_psd(big):
        big, _ = clean_correlation_matrix(big)

    return big


def simulate_multi_asset_heston(assets, equity_corr, T, n_steps, n_paths, r, seed):
    """
    Simulate correlated multi-asset Heston paths using full-truncation
    Euler discretization.

    Returns spot_paths: ndarray of shape (n_paths, n_steps+1, n_assets).
    """
    n = len(assets)
    dt = T / n_steps
    sqrt_dt = np.sqrt(dt)

    rng = np.random.default_rng(seed)

    # Build and decompose correlation matrix
    big_corr = build_2n_correlation(assets, equity_corr)
    # Small regularization for Cholesky numerical stability
    big_corr += np.eye(2 * n) * 1e-12
    L = np.linalg.cholesky(big_corr)

    # Initialize state
    log_S = np.zeros((n_paths, n))
    v = np.zeros((n_paths, n))
    for i, a in enumerate(assets):
        log_S[:, i] = np.log(a["spot"])
        v[:, i] = a["v0"]

    # Pre-allocate spot path storage
    spot_paths = np.zeros((n_paths, n_steps + 1, n))
    for i in range(n):
        spot_paths[:, 0, i] = assets[i]["spot"]

    # Time-stepping
    for t_idx in range(n_steps):
        # Generate independent normals and correlate
        Z = rng.standard_normal((n_paths, 2 * n))
        Z_corr = Z @ L.T

        for i, a in enumerate(assets):
            W_spot = Z_corr[:, 2 * i]
            W_vol = Z_corr[:, 2 * i + 1]

            v_pos = np.maximum(v[:, i], 0.0)
            sqrt_v = np.sqrt(v_pos)

            # Update log-spot
            log_S[:, i] += (r - a["div_yield"] - 0.5 * v_pos) * dt + sqrt_v * W_spot * sqrt_dt

            # Update variance (full truncation)
            v[:, i] += a["kappa"] * (a["theta"] - v_pos) * dt + a["sigma"] * sqrt_v * W_vol * sqrt_dt

        for i in range(n):
            spot_paths[:, t_idx + 1, i] = np.exp(log_S[:, i])

    return spot_paths


# =============================================================================
# 4. AUTOCALLABLE PRICER
# =============================================================================

def price_autocallable(config):
    """
    Price a worst-of multi-asset autocallable note via Monte Carlo.

    Cash flow logic per path:
    - At each observation date (processed sequentially):
      1. If worst-of perf >= coupon_barrier and note is alive: earn coupon.
         With snowball, previously missed coupons are added.
      2. If worst-of perf >= autocall_barrier and note is alive: autocall.
         Notional is returned (discounted). No further observations.
    - At maturity (if not autocalled):
      If knock-in occurred (continuous monitoring): redemption = notional * min(1, worst_of_final)
      Otherwise: full notional.

    Returns dict with price (per unit notional), std_error, autocall_prob, expected_coupon_count.
    """
    assets = config["assets"]
    n_assets = len(assets)
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
    n_steps_per_year = config["n_steps_per_year"]
    seed = config["seed"]

    T_max = obs_times[-1]
    n_steps = max(int(round(T_max * n_steps_per_year)), 1)
    dt = T_max / n_steps

    # Simulate paths
    spot_paths = simulate_multi_asset_heston(
        assets, config["correlation_matrix"], T_max, n_steps, n_paths, r, seed
    )

    # Compute worst-of performance: S_i(t)/S_i(0)
    S0 = np.array([a["spot"] for a in assets])
    perf = spot_paths / S0[np.newaxis, np.newaxis, :]  # (n_paths, n_steps+1, n_assets)
    worst_of_all = np.min(perf, axis=2)  # (n_paths, n_steps+1)

    # Continuous knock-in monitoring
    if ki_barrier is not None:
        knocked_in = np.min(worst_of_all, axis=1) < ki_barrier  # (n_paths,)
    else:
        knocked_in = np.zeros(n_paths, dtype=bool)

    # Map observation times to step indices
    obs_steps = [min(int(round(t / dt)), n_steps) for t in obs_times]

    # Track state
    pv_cashflows = np.zeros(n_paths)
    alive = np.ones(n_paths, dtype=bool)
    missed_coupons = np.zeros(n_paths)
    coupon_count = np.zeros(n_paths)
    autocall_probs = np.zeros(n_obs)

    for k in range(n_obs):
        t_k = obs_times[k]
        df = np.exp(-r * t_k)
        wo_k = worst_of_all[:, obs_steps[k]]

        # --- Coupon check (alive paths only) ---
        earns = alive & (wo_k >= coupon_barrier)
        misses = alive & (wo_k < coupon_barrier)

        if snowball:
            # Earn current + all accumulated missed coupons
            n_c = np.where(earns, 1.0 + missed_coupons, 0.0)
            pv_cashflows += n_c * coupon_rate * notional * df
            coupon_count += n_c
            missed_coupons = np.where(earns, 0.0, missed_coupons)
            missed_coupons = np.where(misses, missed_coupons + 1.0, missed_coupons)
        else:
            pv_cashflows += np.where(earns, coupon_rate * notional * df, 0.0)
            coupon_count += np.where(earns, 1.0, 0.0)

        # --- Autocall check ---
        autocalled = alive & (wo_k >= autocall_barrier)
        if np.any(autocalled):
            autocall_probs[k] = float(np.sum(autocalled)) / n_paths
            pv_cashflows[autocalled] += notional * df
            alive[autocalled] = False

    # --- Maturity payoff for non-autocalled paths ---
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

    # Compute statistics
    price_per_unit = float(np.mean(pv_cashflows) / notional)
    std_error = float(np.std(pv_cashflows) / (notional * np.sqrt(n_paths)))

    return {
        "price": price_per_unit,
        "std_error": std_error,
        "autocall_prob": [float(p) for p in autocall_probs],
        "expected_coupon_count": float(np.mean(coupon_count)),
    }


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Heston stochastic volatility pricing engine"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- heston-call ---
    hc = sub.add_parser("heston-call", help="Heston European call price")
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

    # --- clean-corr ---
    cc = sub.add_parser("clean-corr", help="Repair correlation matrix to PSD")
    cc.add_argument("--input-file", required=True)
    cc.add_argument("--output-file", required=True)

    # --- autocallable ---
    ac = sub.add_parser("autocallable", help="Price worst-of autocallable note")
    ac.add_argument("--config", required=True)

    args = parser.parse_args()

    if args.command == "heston-call":
        p = heston_call_price(
            args.spot, args.strike, args.rate, args.maturity,
            args.v0, args.theta, args.kappa, args.sigma,
            args.rho, args.div_yield,
        )
        print(json.dumps({"price": p}))

    elif args.command == "clean-corr":
        with open(args.input_file) as f:
            matrix = json.load(f)
        M = np.array(matrix, dtype=float)
        before_psd = is_psd(M)
        if before_psd:
            cleaned = M.copy()
            max_change = 0.0
        else:
            cleaned, max_change = clean_correlation_matrix(M)
        with open(args.output_file, "w") as f:
            json.dump(cleaned.tolist(), f)
        print(json.dumps({
            "is_psd_before": before_psd,
            "is_psd_after": True,
            "max_abs_eigenvalue_change": max_change,
        }))

    elif args.command == "autocallable":
        with open(args.config) as f:
            config = json.load(f)
        result = price_autocallable(config)
        print(json.dumps(result))


if __name__ == "__main__":
    main()
