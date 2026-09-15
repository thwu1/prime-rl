"""
Full rough Heston calibration and pricing pipeline.
"""

import json
import numpy as np
import pandas as pd
import scipy.special as sp
from scipy import optimize, stats, integrate
from scipy.integrate import quad, quad_vec
from scipy.interpolate import PchipInterpolator


# ============================================================
# Black-Scholes utilities
# ============================================================

def black_price(K, T, F, vol, opttype=1.0):
    s = vol * T**0.5
    d1 = np.log(F / K) / s + 0.5 * s
    d2 = d1 - s
    price = opttype * (F * stats.norm.cdf(opttype * d1) - K * stats.norm.cdf(opttype * d2))
    return price


def black_impvol(K, T, F, value, opttype=1, TOL=1e-5, MAX_ITER=1000):
    K = np.atleast_1d(np.asarray(K, dtype=float))
    value = np.atleast_1d(np.asarray(value, dtype=float))
    opttype = np.full_like(K, opttype, dtype=float)

    IMPVOL_MIN = 1e-10
    IMPVOL_MAX = 5.0

    low = IMPVOL_MIN * np.ones_like(K)
    high = IMPVOL_MAX * np.ones_like(K)
    mid = 0.5 * (low + high)
    for _ in range(MAX_ITER):
        price = black_price(K, T, F, mid, opttype)
        diff = (price - value) / np.maximum(value, 1e-30)
        if np.all(np.abs(diff) < TOL):
            return mid
        mask = diff > 0
        high[mask] = mid[mask]
        low[~mask] = mid[~mask]
        mid = 0.5 * (low + high)
    mid = np.where(np.abs(diff) < TOL, mid, np.nan)
    return mid


# ============================================================
# Variance and Gamma swap estimation (Fukasawa robust method)
# ============================================================

def var_swap_robust(ivol_data):
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
        gs_mid[i] = gammaswap(k, mid_vol, i) / t

    return {"expiries": exp_dates, "gs_mid": gs_mid}


# ============================================================
# Mittag-Leffler function (two-parameter)
# ============================================================

def mittag_leffler_two(z, alpha, beta, n_terms=200):
    """Compute E_{alpha,beta}(z) via truncated series."""
    z = np.atleast_1d(np.asarray(z, dtype=complex))
    result = np.zeros_like(z, dtype=complex)
    for k in range(n_terms):
        term = z**k / sp.gamma(alpha * k + beta)
        result += term
        if np.all(np.abs(term) < 1e-15):
            break
    return np.real(result)


# ============================================================
# Normalized leverage contract under rough Heston
# ============================================================

def norm_lev_contract_rheston(H, nu, rho, lbd, T):
    alpha = H + 0.5
    lbdp = lbd - rho * nu
    T = np.atleast_1d(np.asarray(T))
    return (
        (1.0 - mittag_leffler_two(z=-lbdp * T**alpha, alpha=alpha, beta=2))
        * rho * nu / lbdp
    )


# ============================================================
# Forward variance curve (piecewise constant)
# ============================================================

def xi_curve_piecewise(expiries, w_in):
    xi_vec_out = np.concatenate(
        ([w_in[0] / expiries[0]], np.diff(w_in) / np.diff(expiries))
    )

    def xi_curve_raw(t):
        if t <= expiries[-1]:
            return xi_vec_out[np.sum(expiries < t)]
        else:
            return xi_vec_out[-1]

    return np.vectorize(xi_curve_raw)


# ============================================================
# Gauss-Legendre quadrature
# ============================================================

def gauss_legendre(a, b, n):
    knots, weights = np.polynomial.legendre.leggauss(n)
    knots_ab = 0.5 * (b - a) * knots + 0.5 * (b + a)
    weights_ab = 0.5 * (b - a) * weights
    return knots_ab, weights_ab


# ============================================================
# Pade [3,3] for rough Heston h(a, tau)
# ============================================================

def h_pade_33(tau, a, params):
    tau = np.asarray(tau, dtype=np.float64)
    H = params["H"]
    rho = params["rho"]
    nu = params["nu"]
    al = H + 0.5
    lbd = params["lbd"]

    lbdp = lbd / nu
    lbd_tilde = lbdp - 1j * rho * a
    aa = np.sqrt(a * (a + 1j) + lbd_tilde**2)
    rm = lbd_tilde - aa

    b1 = -a * (a + 1j) / 2 / sp.gamma(1 + al)
    b2 = -b1 * lbd_tilde * nu * sp.gamma(1 + al) / sp.gamma(1 + 2 * al)
    b3 = (
        (-b2 * lbd_tilde * nu + nu**2 * b1**2 / 2)
        * sp.gamma(1 + 2 * al) / sp.gamma(1 + 3 * al)
    )

    g0 = rm / nu
    g1 = -1 / (aa * nu) / sp.gamma(1 - al) * g0
    g2 = (
        -1 / (aa * nu)
        * (sp.gamma(1 - al) / sp.gamma(1 - 2 * al) * g1 - 0.5 * nu**2 * g1**2)
    )

    den = g0**3 + 2 * b1 * g0 * g1 - b2 * g1**2 + b1**2 * g2 + b2 * g0 * g2

    p1 = b1
    p2 = (
        b1**2 * g0**2 + b2 * g0**3 + b1**3 * g1 + b1 * b2 * g0 * g1
        - b2**2 * g1**2 + b1 * b3 * g1**2 + b2**2 * g0 * g2 - b1 * b3 * g0 * g2
    ) / den
    q1 = (
        b1 * g0**2 + b1**2 * g1 - b2 * g0 * g1 + b3 * g1**2
        - b1 * b2 * g2 - b3 * g0 * g2
    ) / den
    q2 = (
        b1**2 * g0 + b2 * g0**2 - b1 * b2 * g1 - b3 * g0 * g1
        + b2**2 * g2 - b1 * b3 * g2
    ) / den
    q3 = (b1**3 + 2 * b1 * b2 * g0 + b3 * g0**2 - b2**2 * g1 + b1 * b3 * g1) / den
    p3 = g0 * q3

    y = tau**al
    return (p1 * y + p2 * y**2 + p3 * y**3) / (1 + q1 * y + q2 * y**2 + q3 * y**3)


def deriv_h_pade(tau, a, params):
    rho = params["rho"]
    nu = params["nu"]
    lbd = params["lbd"]

    lbdp = lbd / nu
    lbd_tilde = lbdp - 1j * rho * a
    aa = np.sqrt(a * (a + 1j) + lbd_tilde**2)
    rm = lbd_tilde - aa
    rp = lbd_tilde + aa

    h = h_pade_33(tau, a, params)
    return 0.5 * (nu * h - rm) * (nu * h - rp)


def g_func(a, t, params):
    lbd = params["lbd"]
    return lbd * h_pade_33(t, a, params) + deriv_h_pade(t, a, params)


# ============================================================
# Characteristic function and implied vol
# ============================================================

def phi_rheston_rational(u, tau, params, xi_curve, n_quad=40):
    tau = np.atleast_1d(np.asarray(tau))
    x_le, w_le = gauss_legendre(0, 1, n_quad)
    log_charfunc = (
        w_le[None, :]
        * xi_curve(tau[:, None] * (1 - x_le[None, :]))
        * g_func(a=u, t=tau[:, None] * x_le[None, :], params=params)
    )
    log_charfunc = np.sum(log_charfunc, axis=1)
    return np.exp(tau * log_charfunc)


def lewis_formula_otm_price(phi, k, tau):
    k = np.atleast_1d(np.asarray(k))
    tau = np.atleast_1d(np.asarray(tau))

    def integrand(u):
        return np.real(np.exp(-1j * u * k) * phi(u - 1j / 2, tau) / (u**2 + 0.25))

    k_minus = k * (k < 0)
    integral, _ = quad_vec(integrand, 0, np.inf, epsrel=1e-10, limit=1000)
    result = np.exp(k_minus) - np.exp(k / 2) / np.pi * integral
    return result


def impvol_rheston(k, tau, params, xi, n_quad=40):
    otm_price = lewis_formula_otm_price(
        lambda u, tau: phi_rheston_rational(u=u, tau=tau, params=params, xi_curve=xi, n_quad=n_quad),
        k=k, tau=tau,
    )
    opttype = 2 * (k > 0) - 1
    iv = black_impvol(K=np.exp(k), T=tau, F=1, value=otm_price, opttype=opttype)
    return iv


# ============================================================
# Main pipeline
# ============================================================

def main():
    # Load data
    df_spx = pd.read_csv("/app/spx_implied_vol_20230215.csv", index_col=0)

    # Step 1: Compute variance and gamma swaps
    vs_result = var_swap_robust(df_spx)
    gs_result = gamma_swap_robust(df_spx)
    var_swaps = vs_result["vs_mid"]
    gamma_swaps = gs_result["gs_mid"]
    spx_expiries = vs_result["expiries"]

    # Step 2: Normalized leverage contract
    norm_leverage = (gamma_swaps - var_swaps) / var_swaps

    # Step 3: Calibrate rough Heston parameters
    def obj(x):
        H, nu, rho, lbd = x
        norm_lev_model = norm_lev_contract_rheston(H, nu, rho, lbd, spx_expiries)
        return np.sum((norm_lev_model - norm_leverage) ** 2 / (spx_expiries**0.9)) * 1e6

    x0 = np.array([0.05, 0.25, -0.64, 0.3])
    bounds = ((1e-4, 1), (0.01, 10), (-0.999, 0), (0, 10))
    res_optim = optimize.minimize(obj, x0, method="L-BFGS-B", bounds=bounds)
    x_opt = res_optim.x
    H_opt, nu_opt, rho_opt, lbd_opt = x_opt

    print(f"Calibrated: H={H_opt:.6f}, nu={nu_opt:.6f}, rho={rho_opt:.6f}, lbd={lbd_opt:.6f}")

    # Compute model leverage at calibrated params
    model_leverage = norm_lev_contract_rheston(H_opt, nu_opt, rho_opt, lbd_opt, spx_expiries)

    # Step 4: Build forward variance curve
    w_in = var_swaps * spx_expiries  # total variance = var_swap_rate * T
    xi = xi_curve_piecewise(spx_expiries, w_in)

    # Step 5: Compute model implied vols with FIXED rough parameters
    params = {"H": 0.05, "nu": 0.3, "rho": -0.65, "lbd": 0.3}
    maturities = [0.25, 0.5, 1.0]
    log_strikes = [-0.1, -0.05, 0.0, 0.05, 0.1]
    impvols = []
    for tau in maturities:
        row = []
        for k in log_strikes:
            try:
                iv = impvol_rheston(k, tau, params, xi, n_quad=40)
                iv_val = float(iv) if np.isscalar(iv) else float(iv[0])
            except Exception:
                iv_val = float("nan")
            row.append(round(iv_val, 8))
        impvols.append(row)
        print(f"  tau={tau}: {row}")

    # Write outputs
    with open("/app/calibrated_params.json", "w") as f:
        json.dump({
            "H": round(float(H_opt), 8),
            "nu": round(float(nu_opt), 8),
            "rho": round(float(rho_opt), 8),
            "lbd": round(float(lbd_opt), 8),
        }, f, indent=2)

    with open("/app/normalized_leverage.json", "w") as f:
        json.dump({
            "expiries": [round(float(e), 8) for e in spx_expiries],
            "empirical": [round(float(v), 8) for v in norm_leverage],
            "model": [round(float(v), 8) for v in model_leverage],
        }, f, indent=2)

    with open("/app/model_impvols.json", "w") as f:
        json.dump({
            "maturities": maturities,
            "log_strikes": log_strikes,
            "impvols": impvols,
        }, f, indent=2)

    print("Done. Outputs written to /app/")


if __name__ == "__main__":
    main()
