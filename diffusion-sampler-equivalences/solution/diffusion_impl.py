"""
Unified diffusion sampler framework: DDPM, DDIM, EDM schedule/sampling library.
"""

import numpy as np


# ── Schedules ───────────────────────────────────────────────────────────────

def linear_beta_schedule(T, beta_start=1e-4, beta_end=0.02):
    beta = np.linspace(beta_start, beta_end, T)
    alpha = 1.0 - beta
    alpha_bar = np.cumprod(alpha)
    return {"beta": beta, "alpha": alpha, "alpha_bar": alpha_bar}


def cosine_alpha_bar_schedule(T, s=0.008):
    steps = T + 1
    t = np.linspace(0, T, steps)
    f = np.cos(((t / T) + s) / (1.0 + s) * np.pi * 0.5) ** 2
    alpha_bar_full = f / f[0]
    beta = 1.0 - alpha_bar_full[1:] / alpha_bar_full[:-1]
    beta = np.clip(beta, 0.0, 0.999)
    alpha = 1.0 - beta
    alpha_bar = np.cumprod(alpha)
    return {"beta": beta, "alpha": alpha, "alpha_bar": alpha_bar}


# ── Helpers ─────────────────────────────────────────────────────────────────

def _alpha_bar_prev(schedule, t):
    """Return alpha_bar at t-1, with alpha_bar[-1] = 1.0 by convention."""
    if t == 0:
        return 1.0
    return float(schedule["alpha_bar"][t - 1])


# ── Posteriors ──────────────────────────────────────────────────────────────

def posterior_mean_coefficients(t, schedule):
    ab_t = schedule["alpha_bar"][t]
    ab_prev = _alpha_bar_prev(schedule, t)
    beta_t = schedule["beta"][t]
    coeff_x0 = np.sqrt(ab_prev) * beta_t / (1.0 - ab_t)
    coeff_xt = np.sqrt(schedule["alpha"][t]) * (1.0 - ab_prev) / (1.0 - ab_t)
    return coeff_x0, coeff_xt


def posterior_variance(t, schedule):
    ab_t = schedule["alpha_bar"][t]
    ab_prev = _alpha_bar_prev(schedule, t)
    beta_t = schedule["beta"][t]
    return (1.0 - ab_prev) / (1.0 - ab_t) * beta_t


# ── Sampling steps ──────────────────────────────────────────────────────────

def ddpm_ancestral_step(x_t, eps_pred, t, schedule, z=None):
    alpha_t = schedule["alpha"][t]
    ab_t = schedule["alpha_bar"][t]
    beta_t = schedule["beta"][t]

    mean = (1.0 / np.sqrt(alpha_t)) * (
        x_t - beta_t / np.sqrt(1.0 - ab_t) * eps_pred
    )

    if t == 0:
        return mean

    var = posterior_variance(t, schedule)
    if z is None:
        z = np.random.randn(*x_t.shape)
    return mean + np.sqrt(var) * z


def ddim_step(x_t, eps_pred, t, t_prev, schedule, eta=0.0, z=None):
    ab_t = schedule["alpha_bar"][t]
    ab_prev = 1.0 if t_prev < 0 else schedule["alpha_bar"][t_prev]

    # Predicted clean data
    pred_x0 = (x_t - np.sqrt(1.0 - ab_t) * eps_pred) / np.sqrt(ab_t)

    # Noise magnitude
    if eta > 0.0 and ab_prev < 1.0:
        variance = (1.0 - ab_prev) / (1.0 - ab_t) * (1.0 - ab_t / ab_prev)
        sigma = eta * np.sqrt(variance)
    else:
        sigma = 0.0

    # Direction pointing toward x_t
    dir_coeff = np.sqrt(max(1.0 - ab_prev - sigma ** 2, 0.0))

    # Noise
    if z is None:
        if sigma > 0:
            z = np.random.randn(*x_t.shape)
        else:
            z = np.zeros_like(x_t)

    return np.sqrt(ab_prev) * pred_x0 + dir_coeff * eps_pred + sigma * z


# ── Conversions ─────────────────────────────────────────────────────────────

def vp_to_edm_sigma(alpha_bar_t):
    return np.sqrt((1.0 - alpha_bar_t) / alpha_bar_t)


def noise_to_score(eps, sigma):
    return -eps / sigma


def signal_to_noise_ratio(alpha_bar_t):
    return alpha_bar_t / (1.0 - alpha_bar_t)


def predicted_x0(x_t, eps_pred, t, schedule):
    ab_t = schedule["alpha_bar"][t]
    return (x_t - np.sqrt(1.0 - ab_t) * eps_pred) / np.sqrt(ab_t)
