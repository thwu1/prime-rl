"""
Exact Riemann solver for the 1D Euler equations of gas dynamics.

Reference: E.F. Toro, "Riemann Solvers and Numerical Methods for
Fluid Dynamics", 3rd edition, Springer, 2009, Chapter 4.
"""

import math


def solve_riemann_star(rhoL, uL, pL, rhoR, uR, pR, gamma):
    """
    Compute the star-region pressure and velocity for the Riemann problem.

    Uses Newton-Raphson iteration on the pressure function
    f(p) = fL(p) + fR(p) + (uR - uL) = 0
    with an adaptive initial guess.

    Parameters
    ----------
    rhoL, uL, pL : float  -- left state
    rhoR, uR, pR : float  -- right state
    gamma         : float  -- ratio of specific heats

    Returns
    -------
    (pstar, ustar) : tuple of float
    """
    aL = math.sqrt(gamma * pL / rhoL)
    aR = math.sqrt(gamma * pR / rhoR)

    gm1 = gamma - 1.0
    gp1 = gamma + 1.0
    g1 = gm1 / (2.0 * gamma)      # (gamma-1)/(2*gamma)
    g2 = gp1 / (2.0 * gamma)      # (gamma+1)/(2*gamma)
    g3 = 2.0 * gamma / gm1        # 2*gamma/(gamma-1)
    g4 = 2.0 / gp1                # 2/(gamma+1)
    g5 = gm1 / gp1                # (gamma-1)/(gamma+1)
    g6 = gm1 / 2.0                # (gamma-1)/2

    # ---- pressure functions ------------------------------------------------

    def fK(p, rhoK, pK, aK):
        if p > pK:
            AK = g5 / rhoK
            BK = g5 * pK
            return (p - pK) * math.sqrt(AK / (p + BK))
        else:
            return (2.0 * aK / gm1) * ((p / pK) ** g1 - 1.0)

    def fK_deriv(p, rhoK, pK, aK):
        if p > pK:
            AK = g5 / rhoK
            BK = g5 * pK
            qrt = math.sqrt(AK / (p + BK))
            return qrt * (1.0 - (p - pK) / (2.0 * (p + BK)))
        else:
            return (1.0 / (rhoK * aK)) * (p / pK) ** (-g2)

    def f(p):
        return fK(p, rhoL, pL, aL) + fK(p, rhoR, pR, aR) + (uR - uL)

    def f_prime(p):
        return fK_deriv(p, rhoL, pL, aL) + fK_deriv(p, rhoR, pR, aR)

    # ---- adaptive initial guess -------------------------------------------

    ppv = 0.5 * (pL + pR) - 0.125 * (uR - uL) * (rhoL + rhoR) * (aL + aR)
    ppv = max(ppv, 1e-15)

    pmin = min(pL, pR)
    pmax = max(pL, pR)
    qrat = pmax / max(pmin, 1e-30)

    if qrat <= 2.0 and pmin <= ppv <= pmax:
        p0 = ppv
    elif ppv < pmin:
        # two-rarefaction approximation
        num = aL + aR - g6 * (uR - uL)
        den = aL / (pL ** g1) + aR / (pR ** g1)
        p0 = (num / den) ** g3
    else:
        # two-shock approximation
        gL = math.sqrt(g4 / rhoL / (g5 * pL + ppv))
        gR = math.sqrt(g4 / rhoR / (g5 * pR + ppv))
        p0 = (gL * pL + gR * pR - (uR - uL)) / (gL + gR)

    p0 = max(p0, 1e-15)

    # ---- Newton-Raphson iteration ------------------------------------------

    pstar = p0
    for _ in range(200):
        fval = f(pstar)
        fpval = f_prime(pstar)
        if abs(fpval) < 1e-30:
            break
        dp = fval / fpval
        pnew = pstar - dp
        if pnew <= 0.0:
            pstar *= 0.5
            continue
        pstar = pnew
        if 2.0 * abs(dp) / (abs(pstar) + abs(pstar + dp) + 1e-30) < 1e-12:
            break

    # ---- star velocity -----------------------------------------------------

    ustar = 0.5 * (uL + uR) + 0.5 * (
        fK(pstar, rhoR, pR, aR) - fK(pstar, rhoL, pL, aL)
    )

    return pstar, ustar


def sample_riemann(rhoL, uL, pL, rhoR, uR, pR, gamma, pstar, ustar, S):
    """
    Sample the exact Riemann solution at similarity variable S = (x-x0)/t.

    Parameters
    ----------
    rhoL, uL, pL : float  -- left state
    rhoR, uR, pR : float  -- right state
    gamma         : float  -- ratio of specific heats
    pstar, ustar  : float  -- star state from solve_riemann_star
    S             : float  -- similarity variable  (x - x0) / t

    Returns
    -------
    (rho, u, p) : tuple of float
    """
    gm1 = gamma - 1.0
    gp1 = gamma + 1.0
    g1 = gm1 / (2.0 * gamma)
    g2 = gp1 / (2.0 * gamma)
    g4 = 2.0 / gp1
    g5 = gm1 / gp1
    g6 = gm1 / 2.0

    aL = math.sqrt(gamma * pL / rhoL)
    aR = math.sqrt(gamma * pR / rhoR)

    if S <= ustar:
        # ---- left of contact discontinuity ----
        if pstar <= pL:
            # left rarefaction
            SHL = uL - aL                              # head speed
            astarL = aL * (pstar / pL) ** g1
            STL = ustar - astarL                        # tail speed

            if S <= SHL:
                rho, u, p = rhoL, uL, pL
            elif S <= STL:
                # inside rarefaction fan
                u = g4 * (aL + g6 * uL + S)
                a = g4 * (aL - g6 * (S - uL))
                rho = rhoL * (a / aL) ** (2.0 / gm1)
                p = pL * (a / aL) ** (2.0 * gamma / gm1)
            else:
                rho = rhoL * (pstar / pL) ** (1.0 / gamma)
                u = ustar
                p = pstar
        else:
            # left shock
            SL = uL - aL * math.sqrt(g2 * pstar / pL + g1)
            if S <= SL:
                rho, u, p = rhoL, uL, pL
            else:
                rho = rhoL * (pstar / pL + g5) / (g5 * pstar / pL + 1.0)
                u = ustar
                p = pstar
    else:
        # ---- right of contact discontinuity ----
        if pstar <= pR:
            # right rarefaction
            SHR = uR + aR                              # head speed
            astarR = aR * (pstar / pR) ** g1
            STR = ustar + astarR                        # tail speed

            if S >= SHR:
                rho, u, p = rhoR, uR, pR
            elif S >= STR:
                # inside rarefaction fan
                u = g4 * (-aR + g6 * uR + S)
                a = g4 * (aR + g6 * (uR - S))
                rho = rhoR * (a / aR) ** (2.0 / gm1)
                p = pR * (a / aR) ** (2.0 * gamma / gm1)
            else:
                rho = rhoR * (pstar / pR) ** (1.0 / gamma)
                u = ustar
                p = pstar
        else:
            # right shock
            SR = uR + aR * math.sqrt(g2 * pstar / pR + g1)
            if S >= SR:
                rho, u, p = rhoR, uR, pR
            else:
                rho = rhoR * (pstar / pR + g5) / (g5 * pstar / pR + 1.0)
                u = ustar
                p = pstar

    return rho, u, p
