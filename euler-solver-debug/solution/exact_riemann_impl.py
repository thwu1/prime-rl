#!/usr/bin/env python3
"""
Exact Riemann Solver for the 1D Euler Equations (Complete Implementation)

Reference: E.F. Toro, "Riemann Solvers and Numerical Methods for Fluid
Dynamics", 3rd edition, Springer, 2009, Chapter 4.
"""

import numpy as np


def exact_riemann(rho_L, u_L, p_L, rho_R, u_R, p_R, gamma, x, t, x0=0.0):
    """Compute the exact solution to a Riemann problem."""
    a_L = np.sqrt(gamma * p_L / rho_L)
    a_R = np.sqrt(gamma * p_R / rho_R)

    g1 = (gamma - 1.0) / (2.0 * gamma)
    g2 = (gamma + 1.0) / (2.0 * gamma)
    g3 = 2.0 * gamma / (gamma - 1.0)
    g4 = 2.0 / (gamma - 1.0)
    g5 = 2.0 / (gamma + 1.0)
    g6 = (gamma - 1.0) / (gamma + 1.0)
    g7 = (gamma - 1.0) / 2.0

    # Newton-Raphson for star-region pressure
    p_star = 0.5 * (p_L + p_R) - 0.125 * (u_R - u_L) * (rho_L + rho_R) * (a_L + a_R)
    p_star = max(p_star, 1e-10)

    for _ in range(300):
        if p_star <= p_L:
            ratio = p_star / p_L
            f_L = g4 * a_L * (ratio ** g1 - 1.0)
            fp_L = (1.0 / (rho_L * a_L)) * ratio ** (-g2)
        else:
            A_L = g5 / rho_L
            B_L = g6 * p_L
            sqr = np.sqrt(A_L / (p_star + B_L))
            f_L = (p_star - p_L) * sqr
            fp_L = sqr * (1.0 - (p_star - p_L) / (2.0 * (p_star + B_L)))

        if p_star <= p_R:
            ratio = p_star / p_R
            f_R = g4 * a_R * (ratio ** g1 - 1.0)
            fp_R = (1.0 / (rho_R * a_R)) * ratio ** (-g2)
        else:
            A_R = g5 / rho_R
            B_R = g6 * p_R
            sqr = np.sqrt(A_R / (p_star + B_R))
            f_R = (p_star - p_R) * sqr
            fp_R = sqr * (1.0 - (p_star - p_R) / (2.0 * (p_star + B_R)))

        f_val = f_L + f_R + (u_R - u_L)
        fp_val = fp_L + fp_R

        if abs(fp_val) < 1e-30:
            break

        dp = -f_val / fp_val
        p_new = max(p_star + dp, 1e-10)

        if 2.0 * abs(p_new - p_star) / (p_new + p_star + 1e-30) < 1e-12:
            p_star = p_new
            break
        p_star = p_new

    # Star-region velocity
    if p_star <= p_L:
        f_L = g4 * a_L * ((p_star / p_L) ** g1 - 1.0)
    else:
        A_L = g5 / rho_L
        B_L = g6 * p_L
        f_L = (p_star - p_L) * np.sqrt(A_L / (p_star + B_L))

    if p_star <= p_R:
        f_R = g4 * a_R * ((p_star / p_R) ** g1 - 1.0)
    else:
        A_R = g5 / rho_R
        B_R = g6 * p_R
        f_R = (p_star - p_R) * np.sqrt(A_R / (p_star + B_R))

    u_star = 0.5 * (u_L + u_R) + 0.5 * (f_R - f_L)

    # Sample exact solution
    rho = np.zeros_like(x, dtype=float)
    u_out = np.zeros_like(x, dtype=float)
    p_out = np.zeros_like(x, dtype=float)

    for i in range(len(x)):
        s = (x[i] - x0) / t

        if s < u_star:
            if p_star <= p_L:
                S_HL = u_L - a_L
                a_star_L = a_L * (p_star / p_L) ** g1
                S_TL = u_star - a_star_L

                if s <= S_HL:
                    rho[i] = rho_L
                    u_out[i] = u_L
                    p_out[i] = p_L
                elif s <= S_TL:
                    u_out[i] = g5 * (a_L + g7 * u_L + s)
                    a_fan = g5 * (a_L + g7 * (u_L - s))
                    rho[i] = rho_L * (a_fan / a_L) ** g4
                    p_out[i] = p_L * (a_fan / a_L) ** g3
                else:
                    rho[i] = rho_L * (p_star / p_L) ** (1.0 / gamma)
                    u_out[i] = u_star
                    p_out[i] = p_star
            else:
                S_L = u_L - a_L * np.sqrt(g2 * p_star / p_L + g1)
                if s <= S_L:
                    rho[i] = rho_L
                    u_out[i] = u_L
                    p_out[i] = p_L
                else:
                    rho[i] = rho_L * (p_star / p_L + g6) / (g6 * p_star / p_L + 1.0)
                    u_out[i] = u_star
                    p_out[i] = p_star
        else:
            if p_star <= p_R:
                S_HR = u_R + a_R
                a_star_R = a_R * (p_star / p_R) ** g1
                S_TR = u_star + a_star_R

                if s >= S_HR:
                    rho[i] = rho_R
                    u_out[i] = u_R
                    p_out[i] = p_R
                elif s >= S_TR:
                    u_out[i] = g5 * (-a_R + g7 * u_R + s)
                    a_fan = g5 * (a_R - g7 * (u_R - s))
                    rho[i] = rho_R * (a_fan / a_R) ** g4
                    p_out[i] = p_R * (a_fan / a_R) ** g3
                else:
                    rho[i] = rho_R * (p_star / p_R) ** (1.0 / gamma)
                    u_out[i] = u_star
                    p_out[i] = p_star
            else:
                S_R = u_R + a_R * np.sqrt(g2 * p_star / p_R + g1)
                if s >= S_R:
                    rho[i] = rho_R
                    u_out[i] = u_R
                    p_out[i] = p_R
                else:
                    rho[i] = rho_R * (p_star / p_R + g6) / (g6 * p_star / p_R + 1.0)
                    u_out[i] = u_star
                    p_out[i] = p_star

    return rho, u_out, p_out, p_star, u_star
