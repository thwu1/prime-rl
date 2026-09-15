"""Variance and gamma swap estimation via robust replication methodology."""
import numpy as np
from scipy import stats
from scipy.integrate import quad
from scipy.interpolate import PchipInterpolator


def var_swap_robust(ivol_data):
    """Compute variance swap rates for each expiry using robust replication.

    Transforms implied volatilities to Bachelier-normalized coordinates,
    integrates total variance via PCHIP interpolation, and adds tail corrections.
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
        y_in = stats.norm.cdf(zm_in)
        ord_y_in = np.argsort(y_in)
        sig_in_y = sig_in[ord_y_in]
        y_min = np.min(y_in)
        y_max = np.max(y_in)
        sig_in_0 = sig_in_y[0]
        sig_in_1 = sig_in_y[-1]

        wbar_flat = quad(PchipInterpolator(np.sort(y_in), sig_in_y**2), y_min, y_max)[0]
        res_mid = wbar_flat
        z_minus = zm_in[ord_y_in][0]
        res_lh = sig_in_0**2 * stats.norm.cdf(z_minus)
        z_plus = zm_in[ord_y_in][-1]
        res_rh = sig_in_1**2 * stats.norm.cdf(-z_plus)

        return res_mid + res_lh + res_rh

    for i in range(n_slices):
        t = exp_dates[i]
        texp = ivol_data["Texp"]
        bid_vol = bid_vols[texp == t].to_numpy()
        ask_vol = ask_vols[texp == t].to_numpy()
        mid_vol = (bid_vol + ask_vol) / 2
        F = ivol_data["Fwd"][texp == t].iloc[0]
        k = np.log(ivol_data["Strike"][texp == t].to_numpy() / F)
        vs_mid[i] = varswap(k, mid_vol, i) / t

    return {"expiries": exp_dates, "vs_mid": vs_mid}


def gamma_swap_robust(ivol_data):
    """Compute gamma swap rates for each expiry using robust replication.

    Uses the same methodology as variance swaps but with the z-plus
    transformation for the integration coordinate.
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
        zp_in = zm_in + sig_in
        y_in = stats.norm.cdf(zp_in)
        ord_y_in = np.argsort(y_in)
        sig_in_y = sig_in[ord_y_in]
        y_min = np.min(y_in)
        y_max = np.max(y_in)
        sig_in_0 = sig_in_y[0]
        sig_in_1 = sig_in_y[-1]

        wbar_flat = quad(PchipInterpolator(np.sort(y_in), sig_in_y**2), y_min, y_max)[0]
        res_mid = wbar_flat
        z_minus = zp_in[ord_y_in][0]
        res_lh = sig_in_0**2 * stats.norm.cdf(z_minus)
        z_plus = zp_in[ord_y_in][-1]
        res_rh = sig_in_1**2 * stats.norm.cdf(z_plus)

        return res_mid + res_lh + res_rh

    for i in range(n_slices):
        t = exp_dates[i]
        texp = ivol_data["Texp"]
        bid_vol = bid_vols[texp == t].to_numpy()
        ask_vol = ask_vols[texp == t].to_numpy()
        mid_vol = (bid_vol + ask_vol) / 2
        F = ivol_data["Fwd"][texp == t].iloc[0]
        k = np.log(ivol_data["Strike"][texp == t].to_numpy() / F)
        gs_mid[i] = gammaswap(k, mid_vol, i) / t

    return {"expiries": exp_dates, "gs_mid": gs_mid}
