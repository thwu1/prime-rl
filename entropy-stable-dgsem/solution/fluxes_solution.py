"""
Complete implementation of numerical flux functions for the DGSEM solver.
"""
import numpy as np
from core import GAMMA, cons2prim, euler_flux, max_wavespeed


def ln_mean(a, b):
    """Numerically stable weighted mean for entropy-conservative fluxes."""
    xi = a / b
    f = (xi - 1.0) / (xi + 1.0)
    u = f * f
    if u < 1.0e-2:
        return (a + b) / (2.0 * (1.0 + u * (1.0 / 3.0 + u * (1.0 / 5.0 + u / 7.0))))
    return (a - b) / (np.log(a) - np.log(b))


def ec_flux(u_L, u_R):
    """Entropy-conservative two-point flux for 1D Euler equations."""
    rho_L, v_L, p_L = cons2prim(u_L)
    rho_R, v_R, p_R = cons2prim(u_R)

    beta_L = rho_L / (2.0 * p_L)
    beta_R = rho_R / (2.0 * p_R)

    rho_ln = ln_mean(rho_L, rho_R)
    beta_ln = ln_mean(beta_L, beta_R)

    rho_avg = 0.5 * (rho_L + rho_R)
    v_avg = 0.5 * (v_L + v_R)
    beta_avg = 0.5 * (beta_L + beta_R)
    p_avg = rho_avg / (2.0 * beta_avg)
    v2_avg = 0.5 * (v_L**2 + v_R**2)

    f1 = rho_ln * v_avg
    f2 = f1 * v_avg + p_avg
    f3 = f1 * 0.5 * (1.0 / ((GAMMA - 1.0) * beta_ln) - v2_avg) + f2 * v_avg

    return np.array([f1, f2, f3])


def rs_flux(u_L, u_R):
    """Approximate Riemann solver for 1D Euler equations."""
    rho_L, v_L, p_L = cons2prim(u_L)
    rho_R, v_R, p_R = cons2prim(u_R)

    a_L = np.sqrt(GAMMA * p_L / rho_L)
    a_R = np.sqrt(GAMMA * p_R / rho_R)

    S_L = min(v_L - a_L, v_R - a_R)
    S_R = max(v_L + a_L, v_R + a_R)

    denom = rho_L * (S_L - v_L) - rho_R * (S_R - v_R)
    S_M = (p_R - p_L + rho_L * v_L * (S_L - v_L) - rho_R * v_R * (S_R - v_R)) / denom

    if S_L >= 0.0:
        return euler_flux(u_L)
    elif S_R <= 0.0:
        return euler_flux(u_R)
    elif S_M >= 0.0:
        coeff = rho_L * (S_L - v_L) / (S_L - S_M)
        E_L = u_L[2]
        u_star = coeff * np.array([
            1.0,
            S_M,
            E_L / rho_L + (S_M - v_L) * (S_M + p_L / (rho_L * (S_L - v_L)))
        ])
        return euler_flux(u_L) + S_L * (u_star - u_L)
    else:
        coeff = rho_R * (S_R - v_R) / (S_R - S_M)
        E_R = u_R[2]
        u_star = coeff * np.array([
            1.0,
            S_M,
            E_R / rho_R + (S_M - v_R) * (S_M + p_R / (rho_R * (S_R - v_R)))
        ])
        return euler_flux(u_R) + S_R * (u_star - u_R)


def lax_friedrichs_flux(u_L, u_R):
    """Local Lax-Friedrichs (Rusanov) flux -- provided for reference."""
    lam = max(max_wavespeed(u_L), max_wavespeed(u_R))
    return 0.5 * (euler_flux(u_L) + euler_flux(u_R)) - 0.5 * lam * (u_R - u_L)


def central_flux(u_L, u_R):
    """Central (average) flux -- provided for reference."""
    return 0.5 * (euler_flux(u_L) + euler_flux(u_R))
