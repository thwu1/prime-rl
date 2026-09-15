#!/usr/bin/env python3

"""Solve groundwater impulse-response model calibration and comparison task.

Implements transfer function models from scratch: discretizes exponential and
gamma impulse response functions as block responses, convolves with recharge,
optimizes parameters via least squares, compares models by AIC, performs
temporal cross-validation, and computes residual diagnostics.
"""

import json
import math
import warnings

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.signal import fftconvolve
from scipy.special import gammainc

warnings.filterwarnings("ignore")

MEMORY = 2000  # impulse response memory in days


def load_data():
    """Load time series data from CSV files."""
    head = pd.read_csv(
        "/app/head.csv", parse_dates=["date"], index_col="date"
    ).squeeze("columns")
    prec = pd.read_csv(
        "/app/precipitation.csv", parse_dates=["date"], index_col="date"
    ).squeeze("columns")
    evap = pd.read_csv(
        "/app/evaporation.csv", parse_dates=["date"], index_col="date"
    ).squeeze("columns")
    return head, prec, evap


def build_daily_grid(head, prec, evap):
    """Create aligned daily arrays and map observation dates to daily indices."""
    start = min(prec.index.min(), evap.index.min())
    end = max(prec.index.max(), evap.index.max(), head.index.max())
    daily_dates = pd.date_range(start, end, freq="D")

    p = prec.reindex(daily_dates, fill_value=0.0).values.astype(np.float64)
    e = evap.reindex(daily_dates, fill_value=0.0).values.astype(np.float64)

    day_offsets = (head.index - start).days.values
    mask = (day_offsets >= 0) & (day_offsets < len(daily_dates))
    idx = day_offsets[mask]
    obs = head.values[mask].astype(np.float64)

    return p, e, idx, obs, start


def exp_block_response(A, a):
    """Exponential block response: integral of (A/a)*exp(-t/a) over [k, k+1].

    S(t) = A*(1 - exp(-t/a)), so block(k) = S(k+1) - S(k)
         = A * exp(-k/a) * (1 - exp(-1/a)).
    """
    k = np.arange(MEMORY, dtype=np.float64)
    return A * np.exp(-k / a) * (1.0 - np.exp(-1.0 / a))


def gam_block_response(A, a, n):
    """Gamma block response using regularized incomplete gamma function.

    S(t) = A * gammainc(n, t/a), so block(k) = S(k+1) - S(k).
    """
    k = np.arange(MEMORY, dtype=np.float64)
    s_lo = gammainc(n, k / a)
    s_hi = gammainc(n, (k + 1) / a)
    return A * (s_hi - s_lo)


def simulate(p, e, theta, f, d, idx):
    """Simulate head at observation times via FFT convolution."""
    recharge = p - f * e
    sim_daily = fftconvolve(recharge, theta, mode="full")[: len(recharge)]
    return sim_daily[idx] + d


def res_exp(x, p, e, idx, obs):
    """Residuals for exponential model: obs - sim."""
    A, a, f, d = x
    return obs - simulate(p, e, exp_block_response(A, a), f, d, idx)


def res_gam(x, p, e, idx, obs):
    """Residuals for gamma model: obs - sim."""
    A, a, n, f, d = x
    return obs - simulate(p, e, gam_block_response(A, a, n), f, d, idx)


def fit_exponential(p, e, idx, obs):
    """Fit exponential model with multi-start least squares."""
    d0 = float(np.mean(obs))
    d_lo = float(np.min(obs)) - 15.0
    d_hi = float(np.max(obs)) + 5.0
    lo = [1e-4, 5.0, 0.0, d_lo]
    hi = [100.0, 2000.0, 5.0, d_hi]
    best = None
    for A0 in [1.0, 5.0, 15.0, 30.0]:
        for a0 in [50, 150, 400]:
            for f0 in [0.5, 0.8]:
                try:
                    r = least_squares(
                        res_exp,
                        [A0, a0, f0, d0 - 2.0],
                        args=(p, e, idx, obs),
                        bounds=(lo, hi),
                        method="trf",
                        max_nfev=5000,
                    )
                    if best is None or r.cost < best.cost:
                        best = r
                except Exception:
                    continue
    return best


def fit_gamma(p, e, idx, obs):
    """Fit gamma model with multi-start least squares."""
    d0 = float(np.mean(obs))
    d_lo = float(np.min(obs)) - 15.0
    d_hi = float(np.max(obs)) + 5.0
    lo = [1e-4, 5.0, 0.5, 0.0, d_lo]
    hi = [100.0, 2000.0, 15.0, 5.0, d_hi]
    best = None
    for A0 in [1.0, 5.0, 15.0, 30.0]:
        for a0 in [50, 150, 400]:
            for n0 in [1.2, 3.0]:
                for f0 in [0.5, 0.8]:
                    try:
                        r = least_squares(
                            res_gam,
                            [A0, a0, n0, f0, d0 - 2.0],
                            args=(p, e, idx, obs),
                            bounds=(lo, hi),
                            method="trf",
                            max_nfev=5000,
                        )
                        if best is None or r.cost < best.cost:
                            best = r
                    except Exception:
                        continue
    return best


def compute_aic(n_obs, rss, k):
    """AIC = n * ln(RSS/n) + 2k."""
    return n_obs * math.log(rss / n_obs) + 2 * k


def compute_evp(obs, sim):
    """Explained variance percentage."""
    return float((1.0 - np.var(obs - sim) / np.var(obs)) * 100.0)


def compute_rmse(obs, sim):
    """Root mean square error."""
    return float(np.sqrt(np.mean((obs - sim) ** 2)))


def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    return float(1.0 - np.sum((obs - sim) ** 2) / np.sum((obs - np.mean(obs)) ** 2))


def compute_durbin_watson(r):
    """Durbin-Watson statistic."""
    return float(np.sum(np.diff(r) ** 2) / np.sum(r ** 2))


def compute_acf_lag1(r):
    """Autocorrelation at lag 1."""
    c = r - r.mean()
    denom = np.sum(c ** 2)
    if denom == 0:
        return 0.0
    return float(np.sum(c[:-1] * c[1:]) / denom)


def main():
    head, prec, evap = load_data()
    p, e, idx, obs, start = build_daily_grid(head, prec, evap)
    n_obs = len(obs)

    # ---- Fit exponential model ----
    print("Fitting exponential model...")
    r_exp = fit_exponential(p, e, idx, obs)
    A_e, a_e, f_e, d_e = r_exp.x
    sim_exp = obs - r_exp.fun
    rss_exp = float(np.sum(r_exp.fun ** 2))

    evp_exp = compute_evp(obs, sim_exp)
    rmse_exp = compute_rmse(obs, sim_exp)
    aic_exp = compute_aic(n_obs, rss_exp, 4)
    rt95 = -a_e * math.log(0.05)  # step response at 95%: A*(1-exp(-t/a))=0.95*A

    print(f"  A={A_e:.4f}, a={a_e:.1f}d, f={f_e:.3f}, d={d_e:.3f}")
    print(f"  EVP={evp_exp:.1f}%, RMSE={rmse_exp:.4f}m, AIC={aic_exp:.1f}, RT95={rt95:.0f}d")

    # ---- Fit gamma model ----
    print("Fitting gamma model...")
    r_gam = fit_gamma(p, e, idx, obs)
    A_g, a_g, n_g, f_g, d_g = r_gam.x
    sim_gam = obs - r_gam.fun
    rss_gam = float(np.sum(r_gam.fun ** 2))

    evp_gam = compute_evp(obs, sim_gam)
    rmse_gam = compute_rmse(obs, sim_gam)
    aic_gam = compute_aic(n_obs, rss_gam, 5)

    print(f"  A={A_g:.4f}, a={a_g:.1f}d, n={n_g:.3f}, f={f_g:.3f}, d={d_g:.3f}")
    print(f"  EVP={evp_gam:.1f}%, RMSE={rmse_gam:.4f}m, AIC={aic_gam:.1f}")

    # ---- Model selection ----
    best_name = "exponential" if aic_exp <= aic_gam else "gamma"
    best_residuals = r_exp.fun if best_name == "exponential" else r_gam.fun
    print(f"Best model by AIC: {best_name}")

    # ---- Cross-validation ----
    print("Cross-validating...")
    split = pd.Timestamp("2007-01-01")

    # Calibration subset
    cal_mask = head.index < split
    head_cal = head[cal_mask]
    cal_offsets = (head_cal.index - start).days.values
    cal_valid = (cal_offsets >= 0) & (cal_offsets < len(p))
    idx_cal = cal_offsets[cal_valid]
    obs_cal = head_cal.values[cal_valid].astype(np.float64)

    # Validation subset
    val_mask = head.index >= split
    head_val = head[val_mask]
    val_offsets = (head_val.index - start).days.values
    val_valid = (val_offsets >= 0) & (val_offsets < len(p))
    idx_val = val_offsets[val_valid]
    obs_val = head_val.values[val_valid].astype(np.float64)

    # Fit on calibration period
    if best_name == "exponential":
        r_cv = fit_exponential(p, e, idx_cal, obs_cal)
        A_cv, a_cv, f_cv, d_cv = r_cv.x
        theta_cv = exp_block_response(A_cv, a_cv)
    else:
        r_cv = fit_gamma(p, e, idx_cal, obs_cal)
        A_cv, a_cv, n_cv, f_cv, d_cv = r_cv.x
        theta_cv = gam_block_response(A_cv, a_cv, n_cv)

    sim_cv_cal = simulate(p, e, theta_cv, f_cv, d_cv, idx_cal)
    sim_cv_val = simulate(p, e, theta_cv, f_cv, d_cv, idx_val)

    cal_evp = compute_evp(obs_cal, sim_cv_cal)
    val_rmse = compute_rmse(obs_val, sim_cv_val)
    val_nse = compute_nse(obs_val, sim_cv_val)

    print(f"  Cal EVP={cal_evp:.1f}%, Val RMSE={val_rmse:.4f}m, Val NSE={val_nse:.3f}")

    # ---- Diagnostics on best model ----
    dw = compute_durbin_watson(best_residuals)
    acf1 = compute_acf_lag1(best_residuals)
    mean_res = float(np.mean(best_residuals))
    std_res = float(np.std(best_residuals))

    print(f"  DW={dw:.4f}, ACF1={acf1:.4f}, mean_res={mean_res:.6f}, std_res={std_res:.6f}")

    # ---- Write results ----
    results = {
        "exponential_model": {
            "evp": round(evp_exp, 4),
            "rmse": round(rmse_exp, 6),
            "aic": round(aic_exp, 4),
            "n_parameters": 4,
            "response_time_95pct": round(rt95, 2),
        },
        "gamma_model": {
            "evp": round(evp_gam, 4),
            "rmse": round(rmse_gam, 6),
            "aic": round(aic_gam, 4),
            "n_parameters": 5,
        },
        "best_model": best_name,
        "cross_validation": {
            "calibration_evp": round(cal_evp, 4),
            "validation_rmse": round(val_rmse, 6),
            "validation_nse": round(val_nse, 4),
        },
        "diagnostics": {
            "durbin_watson": round(dw, 4),
            "acf_lag1": round(acf1, 4),
            "mean_residual": round(mean_res, 6),
            "std_residual": round(std_res, 6),
            "n_observations": len(head),
        },
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
