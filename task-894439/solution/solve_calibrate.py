"""
Rough Heston calibration via leverage swaps.

Implements the full pipeline:
1. Fukasawa robust variance/gamma swap estimation
2. Normalized leverage contract computation
3. Rough Heston model leverage formula (Mittag-Leffler)
4. Parameter calibration via weighted least squares

"""

import json
import os

import numpy as np
import pandas as pd
from numfracpy import Mittag_Leffler_two
from scipy.integrate import quad
from scipy.interpolate import PchipInterpolator
from scipy.optimize import minimize
from scipy.stats import norm


def var_swap_robust(ivol_data):
    """
    Robust estimation of variance swap rates using Fukasawa's methodology.

    Uses the z_- transform: z_- = -k/sigma - sigma/2 where sigma = vol*sqrt(T),
    maps to y = N(z_-), interpolates total variance in y-space via PCHIP,
    and integrates. Tails are extended at constant total implied variance.
    """
    ivol_data = ivol_data.dropna()
    bid_vols = ivol_data["Bid"].astype(float)
    ask_vols = ivol_data["Ask"].astype(float)
    exp_dates = np.sort(np.unique(ivol_data["Texp"]))
    n_slices = len(exp_dates)

    vs_mid = np.zeros(n_slices)

    def varswap(k_in, vol_series, slice_idx):
        t = exp_dates[slice_idx]
        sig_in = vol_series * np.sqrt(t)
        zm_in = -k_in / sig_in - sig_in / 2
        y_in = norm.cdf(zm_in)
        ord_y_in = np.argsort(y_in)
        sig_in_y = sig_in[ord_y_in]
        y_min = np.min(y_in)
        y_max = np.max(y_in)
        sig_in_0 = sig_in_y[0]
        sig_in_1 = sig_in_y[-1]

        wbar_flat = quad(
            PchipInterpolator(np.sort(y_in), sig_in_y**2), y_min, y_max
        )[0]
        res_mid = wbar_flat
        z_minus = zm_in[ord_y_in][0]
        res_lh = sig_in_0**2 * norm.cdf(z_minus)
        z_plus = zm_in[ord_y_in][-1]
        res_rh = sig_in_1**2 * norm.cdf(-z_plus)

        return res_mid + res_lh + res_rh

    for slice_idx in range(n_slices):
        t = exp_dates[slice_idx]
        texp = ivol_data["Texp"]
        bid_vol = bid_vols[texp == t].to_numpy()
        ask_vol = ask_vols[texp == t].to_numpy()
        mid_vol = (bid_vol + ask_vol) / 2
        F = ivol_data["Fwd"][texp == t].iloc[0]
        k = np.log(ivol_data["Strike"][texp == t].to_numpy() / F)
        vs_mid[slice_idx] = varswap(k, mid_vol, slice_idx) / t

    return {"expiries": exp_dates, "vs_mid": vs_mid}


def gamma_swap_robust(ivol_data):
    """
    Robust estimation of gamma swap rates using Fukasawa's methodology.

    Uses the z_+ transform: z_+ = -k/sigma + sigma/2 (note the + sign),
    maps to y = N(z_+), interpolates and integrates analogously to variance swaps.
    """
    ivol_data = ivol_data.dropna()
    bid_vols = ivol_data["Bid"].astype(float)
    ask_vols = ivol_data["Ask"].astype(float)
    exp_dates = np.sort(np.unique(ivol_data["Texp"]))
    n_slices = len(exp_dates)

    gs_mid = np.zeros(n_slices)

    def gammaswap(k_in, vol_series, slice_idx):
        t = exp_dates[slice_idx]
        sig_in = vol_series * np.sqrt(t)
        zm_in = -k_in / sig_in - sig_in / 2
        zp_in = zm_in + sig_in  # z_+ = -k/sigma + sigma/2
        y_in = norm.cdf(zp_in)
        ord_y_in = np.argsort(y_in)
        sig_in_y = sig_in[ord_y_in]
        y_min = np.min(y_in)
        y_max = np.max(y_in)
        sig_in_0 = sig_in_y[0]
        sig_in_1 = sig_in_y[-1]

        wbar_flat = quad(
            PchipInterpolator(np.sort(y_in), sig_in_y**2), y_min, y_max
        )[0]
        res_mid = wbar_flat
        z_minus = zp_in[ord_y_in][0]
        res_lh = sig_in_0**2 * norm.cdf(z_minus)
        z_plus = zp_in[ord_y_in][-1]
        res_rh = sig_in_1**2 * norm.cdf(-z_plus)

        return res_mid + res_lh + res_rh

    for slice_idx in range(n_slices):
        t = exp_dates[slice_idx]
        texp = ivol_data["Texp"]
        bid_vol = bid_vols[texp == t].to_numpy()
        ask_vol = ask_vols[texp == t].to_numpy()
        mid_vol = (bid_vol + ask_vol) / 2
        F = ivol_data["Fwd"][texp == t].iloc[0]
        k = np.log(ivol_data["Strike"][texp == t].to_numpy() / F)
        gs_mid[slice_idx] = gammaswap(k, mid_vol, slice_idx) / t

    return {"expiries": exp_dates, "gs_mid": gs_mid}


def mittag_leffler_two(z, alpha, beta):
    """Vectorized two-parameter Mittag-Leffler function E_{alpha,beta}(z)."""
    z = np.atleast_1d(np.asarray(z, dtype=complex))
    return np.array([float(Mittag_Leffler_two(z_i, alpha, beta).real) for z_i in z])


def norm_lev_contract_rheston(H, nu, rho, lbd, T):
    """
    Normalized leverage contract for rough Heston (flat fwd variance case).

    L(T) = (rho*nu/lambda') * (1 - E_{alpha,2}(-lambda' * T^alpha))

    where alpha = H + 1/2, lambda' = lambda - rho*nu.
    """
    alpha = H + 0.5
    lbdp = lbd - rho * nu
    T = np.atleast_1d(np.asarray(T))
    ml = mittag_leffler_two(-lbdp * T**alpha, alpha, 2)
    return rho * nu / lbdp * (1.0 - ml)


def calibrate(expiries, norm_leverage):
    """
    Calibrate rough Heston parameters via weighted least squares on
    normalized leverage contract.
    """
    def obj(x):
        H, nu, rho, lbd = x
        model = norm_lev_contract_rheston(H, nu, rho, lbd, expiries)
        return np.sum((model - norm_leverage) ** 2 / (expiries**0.9)) * 1e6

    x0 = np.array([0.05, 0.25, -0.64, 0.3])
    bounds = ((1e-4, 1), (0.01, 10), (-0.999, 0), (0, 10))
    res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds)
    return res.x, res.fun


def main():
    # Read data
    df = pd.read_csv("/app/data/spx_implied_vol.csv", index_col=0)

    # Compute swap term structures
    vs_result = var_swap_robust(df)
    gs_result = gamma_swap_robust(df)

    expiries = vs_result["expiries"]
    var_swaps = vs_result["vs_mid"]
    gamma_swaps = gs_result["gs_mid"]
    norm_leverage = (gamma_swaps - var_swaps) / var_swaps

    # Write swap curves
    os.makedirs("/app/output", exist_ok=True)
    swap_out = {
        "expiries": expiries.tolist(),
        "var_swaps": var_swaps.tolist(),
        "gamma_swaps": gamma_swaps.tolist(),
        "norm_leverage": norm_leverage.tolist(),
    }
    with open("/app/output/swap_curves.json", "w") as f:
        json.dump(swap_out, f, indent=2)

    # Calibrate
    x_opt, obj_val = calibrate(expiries, norm_leverage)
    H, nu, rho, lbd = x_opt

    # Compute model values at calibrated params
    model_nl = norm_lev_contract_rheston(H, nu, rho, lbd, expiries)
    rmse = float(np.sqrt(np.mean((model_nl - norm_leverage) ** 2)))

    calib_out = {
        "H": float(H),
        "nu": float(nu),
        "rho": float(rho),
        "lbd": float(lbd),
        "rmse": rmse,
        "model_norm_leverage": model_nl.tolist(),
    }
    with open("/app/output/calibration.json", "w") as f:
        json.dump(calib_out, f, indent=2)

    print(f"Calibrated: H={H:.4f}, nu={nu:.4f}, rho={rho:.4f}, lambda={lbd:.4f}")
    print(f"RMSE: {rmse:.6f}")


if __name__ == "__main__":
    main()
