"""Exact Riemann solver for the 1D Euler equations.

"""
import numpy as np


def solve(rhoL, uL, pL, rhoR, uR, pR, gamma):
    """
    Solve the exact Riemann problem for the 1D Euler equations.

    Returns dict with keys: p_star, u_star, rho_star_L, rho_star_R
    """
    aL = np.sqrt(gamma * pL / rhoL)
    aR = np.sqrt(gamma * pR / rhoR)

    gm1 = gamma - 1.0
    gp1 = gamma + 1.0
    g1 = gm1 / (2.0 * gamma)
    g3 = gm1 / gp1

    def fk(p, rho_k, p_k, a_k):
        if p > p_k:
            A = 2.0 / (gp1 * rho_k)
            B = g3 * p_k
            return (p - p_k) * np.sqrt(A / (p + B))
        else:
            return (2.0 * a_k / gm1) * ((p / p_k) ** g1 - 1.0)

    def dfk(p, rho_k, p_k, a_k):
        if p > p_k:
            A = 2.0 / (gp1 * rho_k)
            B = g3 * p_k
            return np.sqrt(A / (p + B)) * (1.0 - (p - p_k) / (2.0 * (p + B)))
        else:
            return (1.0 / (rho_k * a_k)) * (p / p_k) ** (-(gp1) / (2.0 * gamma))

    # PVRS initial guess
    p_star = max(1e-15, 0.5 * (pL + pR) -
                 0.125 * (uR - uL) * (rhoL + rhoR) * (aL + aR))

    # Newton-Raphson iteration
    for _ in range(300):
        f = fk(p_star, rhoL, pL, aL) + fk(p_star, rhoR, pR, aR) + (uR - uL)
        df = dfk(p_star, rhoL, pL, aL) + dfk(p_star, rhoR, pR, aR)
        if abs(df) < 1e-30:
            break
        dp = -f / df
        p_star = max(1e-15, p_star + dp)
        if abs(dp) < 1e-14 * max(1.0, p_star):
            break

    u_star = 0.5 * (uL + uR) + 0.5 * (
        fk(p_star, rhoR, pR, aR) - fk(p_star, rhoL, pL, aL))

    # Star-region densities
    if p_star > pL:
        rho_star_L = rhoL * ((p_star / pL + g3) / (g3 * p_star / pL + 1.0))
    else:
        rho_star_L = rhoL * (p_star / pL) ** (1.0 / gamma)

    if p_star > pR:
        rho_star_R = rhoR * ((p_star / pR + g3) / (g3 * p_star / pR + 1.0))
    else:
        rho_star_R = rhoR * (p_star / pR) ** (1.0 / gamma)

    return {
        "p_star": float(p_star),
        "u_star": float(u_star),
        "rho_star_L": float(rho_star_L),
        "rho_star_R": float(rho_star_R),
    }


def sample(x, t, x0, rhoL, uL, pL, rhoR, uR, pR, gamma):
    """
    Sample the exact Riemann solution at position x and time t.

    Returns tuple (rho, u, p).
    """
    sol = solve(rhoL, uL, pL, rhoR, uR, pR, gamma)
    ps = sol["p_star"]
    us = sol["u_star"]
    rsL = sol["rho_star_L"]
    rsR = sol["rho_star_R"]

    gm1 = gamma - 1.0
    gp1 = gamma + 1.0
    g1 = gm1 / (2.0 * gamma)
    g2 = gp1 / (2.0 * gamma)

    aL = np.sqrt(gamma * pL / rhoL)
    aR = np.sqrt(gamma * pR / rhoR)

    xi = (x - x0) / t

    # --- Left wave ---
    if ps <= pL:
        # Left rarefaction
        asL = aL * (ps / pL) ** g1
        head_L = uL - aL
        tail_L = us - asL
        if xi <= head_L:
            return (rhoL, uL, pL)
        elif xi <= tail_L:
            u = (2.0 / gp1) * (aL + gm1 / 2.0 * uL + xi)
            a = (2.0 / gp1) * (aL + gm1 / 2.0 * (uL - xi))
            rho = rhoL * (a / aL) ** (2.0 / gm1)
            p = pL * (a / aL) ** (2.0 * gamma / gm1)
            return (float(rho), float(u), float(p))
        elif xi <= us:
            return (rsL, us, ps)
    else:
        # Left shock
        SL = uL - aL * np.sqrt(g2 * ps / pL + g1)
        if xi <= SL:
            return (rhoL, uL, pL)
        elif xi <= us:
            return (rsL, us, ps)

    # --- Right wave ---
    if ps <= pR:
        # Right rarefaction
        asR = aR * (ps / pR) ** g1
        head_R = uR + aR
        tail_R = us + asR
        if xi >= head_R:
            return (rhoR, uR, pR)
        elif xi >= tail_R:
            u = (2.0 / gp1) * (-aR + gm1 / 2.0 * uR + xi)
            a = (2.0 / gp1) * (aR - gm1 / 2.0 * (uR - xi))
            rho = rhoR * (a / aR) ** (2.0 / gm1)
            p = pR * (a / aR) ** (2.0 * gamma / gm1)
            return (float(rho), float(u), float(p))
        else:
            return (rsR, us, ps)
    else:
        # Right shock
        SR = uR + aR * np.sqrt(g2 * ps / pR + g1)
        if xi >= SR:
            return (rhoR, uR, pR)
        else:
            return (rsR, us, ps)
