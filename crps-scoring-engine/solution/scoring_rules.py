#!/usr/bin/env python3
"""
Probabilistic forecast scoring engine implementing CRPS for various distributions.
"""

import numpy as np
from scipy.special import erf, expi, gamma as gamma_func, gammaincc

EULER_MASCHERONI = 0.57721566490153286060651209008240243


def _norm_pdf(x):
    """Standard normal PDF."""
    return np.exp(-0.5 * x ** 2) / np.sqrt(2.0 * np.pi)


def _norm_cdf(x):
    """Standard normal CDF."""
    return 0.5 * (1.0 + erf(np.asarray(x, dtype=float) / np.sqrt(2.0)))


def _gev_cdf(x, xi):
    """Standard GEV CDF (location=0, scale=1)."""
    x = np.asarray(x, dtype=float)
    xi = np.asarray(xi, dtype=float)

    zero_shape = xi == 0.0

    # Gumbel case: F(x) = exp(-exp(-x))
    gumbel = np.exp(-np.exp(-x))

    # General case: F(x) = exp(-(1 + xi*x)^{-1/xi}) when 1 + xi*x > 0
    safe_xi = np.where(zero_shape, 1.0, xi)
    t = 1.0 + safe_xi * x
    valid = t > 0
    safe_t = np.where(valid, t, 1.0)

    with np.errstate(invalid="ignore", divide="ignore"):
        general = np.exp(-np.power(safe_t, -1.0 / safe_xi))

    result = np.where(zero_shape, gumbel, np.where(valid, general, np.nan))

    # Boundary: xi > 0, x <= -1/xi => F = 0
    result = np.where((~zero_shape) & (xi > 0) & (~valid), 0.0, result)
    # Boundary: xi < 0, x >= -1/xi => F = 1
    result = np.where((~zero_shape) & (xi < 0) & (~valid), 1.0, result)

    return result


def _gpd_cdf(x, shape):
    """Standard GPD CDF (location=0, scale=1)."""
    x = np.asarray(x, dtype=float)
    shape = np.asarray(shape, dtype=float)

    zero_shape = shape == 0.0
    safe_shape = np.where(zero_shape, 1.0, shape)

    # Exponential case (shape=0): F(x) = 1 - exp(-x) for x >= 0
    exp_cdf = np.where(x >= 0, 1.0 - np.exp(-x), 0.0)

    # General case: F(x) = 1 - (1 + shape*x)^(-1/shape) for 1+shape*x > 0
    t = 1.0 + safe_shape * x
    valid = (t > 0) & (x >= 0)
    safe_t = np.where(valid, t, 1.0)
    with np.errstate(invalid="ignore"):
        gen_cdf = np.where(valid, 1.0 - np.power(safe_t, -1.0 / safe_shape), 0.0)

    # shape < 0, beyond upper endpoint: F = 1
    gen_cdf = np.where((shape < 0) & (~valid) & (x >= 0), 1.0, gen_cdf)
    # x < 0: F = 0
    gen_cdf = np.where(x < 0, 0.0, gen_cdf)

    result = np.where(zero_shape, exp_cdf, gen_cdf)
    return np.clip(result, 0.0, 1.0)


def crps_gev(obs, shape, location=0.0, scale=1.0):
    """Compute CRPS for the Generalized Extreme Value (GEV) distribution."""
    obs = np.atleast_1d(np.asarray(obs, dtype=float))
    shape = np.atleast_1d(np.asarray(shape, dtype=float))
    location = np.atleast_1d(np.asarray(location, dtype=float))
    scale = np.atleast_1d(np.asarray(scale, dtype=float))

    # Standardize
    y = (obs - location) / scale

    # CDF at standardized observation
    F = _gev_cdf(y, shape)

    zero_shape = shape == 0.0

    with np.errstate(invalid="ignore", divide="ignore"):
        # --- Gumbel case (xi = 0) ---
        log_F = np.log(np.clip(F, 1e-300, None))
        gumbel_crps = -y - 2.0 * expi(log_F) + EULER_MASCHERONI - np.log(2.0)

        # --- General case (xi != 0) ---
        safe_xi = np.where(zero_shape, np.nan, shape)
        n_inv_xi = -1.0 / safe_xi

        # Upper incomplete gamma: Gamma(1-xi, -log(F))
        a_param = 1.0 - safe_xi
        x_arg = -log_F
        safe_a = np.where(np.isnan(a_param) | (a_param <= 0), 1.0, a_param)
        safe_x = np.where(np.isnan(x_arg) | (x_arg < 0), 0.0, x_arg)
        uig = gammaincc(safe_a, safe_x) * gamma_func(safe_a)

        gen_G = n_inv_xi * F + uig / safe_xi

        # Build G based on sign of xi
        G = np.full_like(y, np.nan, dtype=float)
        p_xi = safe_xi > 0
        n_xi = safe_xi < 0

        G = np.where(p_xi & (y <= n_inv_xi), 0.0, G)
        G = np.where(p_xi & (y > n_inv_xi), gen_G, G)
        G = np.where(n_xi & (y < n_inv_xi), gen_G, G)
        G = np.where(
            n_xi & (y >= n_inv_xi),
            n_inv_xi + gamma_func(1.0 - safe_xi) / safe_xi,
            G,
        )

        general_crps = (
            y * (2.0 * F - 1.0)
            - 2.0 * G
            - (1.0 - (2.0 - np.power(2.0, safe_xi)) * gamma_func(1.0 - safe_xi))
            / safe_xi
        )

    result = np.where(zero_shape, gumbel_crps, general_crps) * scale

    return float(result.squeeze()) if result.size == 1 else result.squeeze()


def crps_gpd(obs, shape, location=0.0, scale=1.0, mass=0.0):
    """Compute CRPS for the Generalized Pareto Distribution."""
    obs = np.atleast_1d(np.asarray(obs, dtype=float))
    shape = np.atleast_1d(np.asarray(shape, dtype=float))
    location = np.atleast_1d(np.asarray(location, dtype=float))
    scale = np.atleast_1d(np.asarray(scale, dtype=float))
    mass = np.atleast_1d(np.asarray(mass, dtype=float))

    # Validate constraints
    shape = np.where(shape < 1.0, shape, np.nan)
    mass = np.where((mass >= 0.0) & (mass <= 1.0), mass, np.nan)

    omega = (obs - location) / scale
    F = _gpd_cdf(omega, shape)

    with np.errstate(invalid="ignore"):
        s = (
            np.abs(omega)
            - 2.0
            * (1.0 - mass)
            * (1.0 - np.power(np.maximum(1.0 - F, 0.0), 1.0 - shape))
            / (1.0 - shape)
            + (1.0 - mass) ** 2 / (2.0 - shape)
        )

    result = scale * s
    return float(result.squeeze()) if result.size == 1 else result.squeeze()


def crps_normal(obs, mu, sigma):
    """Compute CRPS for the normal distribution."""
    obs = np.atleast_1d(np.asarray(obs, dtype=float))
    mu = np.atleast_1d(np.asarray(mu, dtype=float))
    sigma = np.atleast_1d(np.asarray(sigma, dtype=float))

    omega = (obs - mu) / sigma
    result = sigma * (
        omega * (2.0 * _norm_cdf(omega) - 1.0)
        + 2.0 * _norm_pdf(omega)
        - 1.0 / np.sqrt(np.pi)
    )

    return float(result.squeeze()) if result.size == 1 else result.squeeze()


def crps_gtcnormal(
    obs,
    location,
    scale,
    lower=float("-inf"),
    upper=float("inf"),
    lmass=0.0,
    umass=0.0,
):
    """Compute CRPS for the generalized truncated/censored normal distribution."""
    obs = np.atleast_1d(np.asarray(obs, dtype=float))
    mu = np.atleast_1d(np.asarray(location, dtype=float))
    sigma = np.atleast_1d(np.asarray(scale, dtype=float))
    lower = np.atleast_1d(np.asarray(lower, dtype=float))
    upper = np.atleast_1d(np.asarray(upper, dtype=float))
    lmass = np.atleast_1d(np.asarray(lmass, dtype=float))
    umass = np.atleast_1d(np.asarray(umass, dtype=float))

    # Standardize
    omega = (obs - mu) / sigma
    u = (upper - mu) / sigma
    l = (lower - mu) / sigma
    z = np.minimum(np.maximum(omega, l), u)

    F_u = _norm_cdf(u)
    F_l = _norm_cdf(l)
    F_z = _norm_cdf(z)
    F_u2 = _norm_cdf(u * np.sqrt(2.0))
    F_l2 = _norm_cdf(l * np.sqrt(2.0))
    f_u = _norm_pdf(u)
    f_l = _norm_pdf(l)
    f_z = _norm_pdf(z)

    # Handle infinite bounds
    u_inf = np.isinf(u) & (u > 0)
    l_inf = np.isinf(l) & (l < 0)

    u_safe = np.where(u_inf, np.nan, u)
    l_safe = np.where(l_inf, np.nan, l)

    s1_u = np.where(u_inf & (umass == 0.0), 0.0, u_safe * umass ** 2)
    s1_l = np.where(l_inf & (lmass == 0.0), 0.0, l_safe * lmass ** 2)

    c = (1.0 - lmass - umass) / (F_u - F_l)

    s1 = np.abs(omega - z) + s1_u - s1_l
    s2 = c * z * (
        2.0 * F_z
        - ((1.0 - 2.0 * lmass) * F_u + (1.0 - 2.0 * umass) * F_l)
        / (1.0 - lmass - umass)
    )
    s3 = c * (2.0 * f_z - 2.0 * f_u * umass - 2.0 * f_l * lmass)
    s4 = c ** 2 * (F_u2 - F_l2) / np.sqrt(np.pi)

    result = sigma * (s1 + s2 + s3 - s4)

    return float(result.squeeze()) if result.size == 1 else result.squeeze()


def crps_mixnorm(obs, m, s, w=None):
    """Compute CRPS for a mixture of normal distributions."""
    obs = np.asarray(obs, dtype=float)
    m = np.asarray(m, dtype=float)
    s = np.asarray(s, dtype=float)

    if w is None:
        M = m.shape[-1]
        w = np.ones_like(m) / M
    else:
        w = np.asarray(w, dtype=float)

    def A_func(mu, sigma):
        ratio = mu / sigma
        return mu * (2.0 * _norm_cdf(ratio) - 1.0) + 2.0 * sigma * _norm_pdf(ratio)

    # First term: sum_i w_i A(obs - m_i, s_i)
    m_y = obs[..., None] - m
    sc_1 = np.sum(w * A_func(m_y, s), axis=-1)

    # Second term: sum_i sum_j w_i w_j A(m_i - m_j, sqrt(s_i^2 + s_j^2))
    m_X = m[..., :, None] - m[..., None, :]
    s_X = np.sqrt(s[..., :, None] ** 2 + s[..., None, :] ** 2)
    w_X = w[..., :, None] * w[..., None, :]
    sc_2 = np.sum(w_X * A_func(m_X, s_X), axis=(-1, -2))

    result = sc_1 - 0.5 * sc_2
    return (
        float(np.squeeze(result))
        if np.asarray(result).size == 1
        else np.squeeze(result)
    )


def crps_ensemble(obs, fct, estimator="pwm"):
    """Compute CRPS for ensemble forecasts."""
    obs = np.asarray(obs, dtype=float)
    fct = np.sort(np.asarray(fct, dtype=float), axis=-1)
    M = fct.shape[-1]

    if estimator == "nrg":
        e_1 = np.sum(np.abs(obs[..., None] - fct), axis=-1) / M
        e_2 = np.sum(
            np.abs(fct[..., :, None] - fct[..., None, :]), axis=(-1, -2)
        ) / M ** 2
        return e_1 - 0.5 * e_2

    elif estimator == "fair":
        e_1 = np.sum(np.abs(obs[..., None] - fct), axis=-1) / M
        e_2 = np.sum(
            np.abs(fct[..., :, None] - fct[..., None, :]), axis=(-1, -2)
        ) / (M * (M - 1))
        return e_1 - 0.5 * e_2

    elif estimator == "pwm":
        expected_diff = np.sum(np.abs(obs[..., None] - fct), axis=-1) / M
        beta_0 = np.sum(fct, axis=-1) / M
        beta_1 = np.sum(fct * np.arange(M), axis=-1) / (M * (M - 1.0))
        return expected_diff + beta_0 - 2.0 * beta_1

    elif estimator == "qd":
        alpha = np.arange(1, M + 1) - 0.5
        below = (fct <= obs[..., None]) * alpha * (obs[..., None] - fct)
        above = (fct > obs[..., None]) * (M - alpha) * (fct - obs[..., None])
        return 2.0 * np.sum(below + above, axis=-1) / M ** 2

    else:
        raise ValueError(
            f"Unknown estimator: {estimator}. Must be 'nrg', 'fair', 'pwm', or 'qd'."
        )


def owcrps_ensemble(obs, fct, w_func):
    """Compute outcome-weighted CRPS (owCRPS) for ensemble forecasts."""
    obs = np.asarray(obs, dtype=float)
    fct = np.asarray(fct, dtype=float)
    M = fct.shape[-1]

    ow = w_func(obs)
    fw = w_func(fct)
    wbar = np.mean(fw, axis=-1)

    e_1 = np.sum(np.abs(obs[..., None] - fct) * fw, axis=-1) * ow / (M * wbar)
    e_2 = (
        np.sum(
            np.abs(fct[..., :, None] - fct[..., None, :])
            * fw[..., :, None]
            * fw[..., None, :],
            axis=(-1, -2),
        )
        * ow
        / (M ** 2 * wbar ** 2)
    )

    return e_1 - 0.5 * e_2


def twcrps_ensemble(obs, fct, v_func):
    """Compute threshold-weighted CRPS (twCRPS) for ensemble forecasts.

    Applies the chaining function v to transform both observations and
    forecast members, then computes the standard CRPS on transformed values.
    """
    obs = np.asarray(obs, dtype=float)
    fct = np.asarray(fct, dtype=float)

    obs_v = v_func(obs)
    fct_v = v_func(fct)

    return crps_ensemble(obs_v, fct_v, estimator="nrg")
