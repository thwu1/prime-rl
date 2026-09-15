"""
Second-order MUSCL-Hancock Godunov finite volume solver for the
1D Euler equations, using the exact Riemann solver for intercell fluxes.

"""

import numpy as np
from solver.exact_riemann import solve_riemann_star, sample_riemann


def solve_euler_1d(left, right, gamma, xmin, xmax, x0, ncells, t_end, cfl):
    """
    Solve the 1D Euler equations with a piecewise-constant initial
    discontinuity at *x0*.

    Parameters
    ----------
    left, right : dict   -- {'rho': float, 'u': float, 'p': float}
    gamma       : float  -- ratio of specific heats
    xmin, xmax  : float  -- domain bounds
    x0          : float  -- initial discontinuity position
    ncells      : int    -- number of finite-volume cells
    t_end       : float  -- final time
    cfl         : float  -- CFL number (< 1)

    Returns
    -------
    (x, rho, u, p) : tuple of 1-D numpy arrays
    """
    dx = (xmax - xmin) / ncells
    x = np.linspace(xmin + 0.5 * dx, xmax - 0.5 * dx, ncells)
    gm1 = gamma - 1.0
    N = ncells

    # ---- helpers -----------------------------------------------------------

    def to_cons(rho, u, p):
        return np.array([rho, rho * u, p / gm1 + 0.5 * rho * u * u])

    def to_prim(U):
        r = U[0].copy()
        r = np.maximum(r, 1e-15)
        v = U[1] / r
        pr = gm1 * (U[2] - 0.5 * r * v * v)
        pr = np.maximum(pr, 1e-15)
        return r, v, pr

    def flux_phys(r, v, pr):
        E = pr / gm1 + 0.5 * r * v * v
        return np.array([r * v, r * v * v + pr, v * (E + pr)])

    def minmod(a, b):
        return np.where(a * b > 0,
                        np.where(np.abs(a) < np.abs(b), a, b),
                        0.0)

    # ---- initialise --------------------------------------------------------

    rho = np.where(x < x0, left['rho'], right['rho'])
    u   = np.where(x < x0, left['u'],   right['u'])
    p   = np.where(x < x0, left['p'],   right['p'])

    U = to_cons(rho, u, p)
    t = 0.0

    # ---- main loop ---------------------------------------------------------

    while t < t_end - 1e-14:
        rho, u, p = to_prim(U)

        # adaptive time step
        a = np.sqrt(gamma * p / rho)
        smax = np.max(np.abs(u) + a)
        dt = cfl * dx / smax
        if t + dt > t_end:
            dt = t_end - t

        # ghost cells (transmissive / zero-gradient BC)
        rho_e = np.concatenate([[rho[0]], rho, [rho[-1]]])
        u_e   = np.concatenate([[u[0]],   u,   [u[-1]]])
        p_e   = np.concatenate([[p[0]],   p,   [p[-1]]])

        # MUSCL slopes with minmod limiter
        drho = minmod(rho_e[1:-1] - rho_e[:-2], rho_e[2:] - rho_e[1:-1])
        du   = minmod(u_e[1:-1]   - u_e[:-2],   u_e[2:]   - u_e[1:-1])
        dp   = minmod(p_e[1:-1]   - p_e[:-2],   p_e[2:]   - p_e[1:-1])

        # boundary-extrapolated values within each cell
        rho_L = np.maximum(rho - 0.5 * drho, 1e-15)
        rho_R = np.maximum(rho + 0.5 * drho, 1e-15)
        u_L   = u - 0.5 * du
        u_R   = u + 0.5 * du
        p_L   = np.maximum(p - 0.5 * dp, 1e-15)
        p_R   = np.maximum(p + 0.5 * dp, 1e-15)

        # Hancock predictor: evolve boundary values by dt/2
        FL = flux_phys(rho_L, u_L, p_L)
        FR = flux_phys(rho_R, u_R, p_R)
        UL = to_cons(rho_L, u_L, p_L)
        UR = to_cons(rho_R, u_R, p_R)

        dFdx = (FR - FL) / dx
        UL_ev = UL - 0.5 * dt * dFdx
        UR_ev = UR - 0.5 * dt * dFdx

        rho_Le, u_Le, p_Le = to_prim(UL_ev)
        rho_Re, u_Re, p_Re = to_prim(UR_ev)

        # ---- intercell fluxes via exact Riemann solver --------------------

        nfaces = N + 1
        F_face = np.zeros((3, nfaces))

        for i in range(1, nfaces - 1):
            # left state = right boundary of cell i-1 (evolved)
            rl, vl, pl = float(rho_Re[i-1]), float(u_Re[i-1]), float(p_Re[i-1])
            # right state = left boundary of cell i (evolved)
            rr, vr, pr = float(rho_Le[i]),   float(u_Le[i]),   float(p_Le[i])

            ps, vs = solve_riemann_star(rl, vl, pl, rr, vr, pr, gamma)
            rf, uf, pf = sample_riemann(rl, vl, pl, rr, vr, pr,
                                        gamma, ps, vs, 0.0)

            Ef = pf / gm1 + 0.5 * rf * uf * uf
            F_face[0, i] = rf * uf
            F_face[1, i] = rf * uf * uf + pf
            F_face[2, i] = uf * (Ef + pf)

        # boundary fluxes: copy adjacent interior face (transmissive)
        F_face[:, 0]  = F_face[:, 1]
        F_face[:, -1] = F_face[:, -2]

        # conservative update
        U = U - (dt / dx) * (F_face[:, 1:] - F_face[:, :-1])
        t += dt

    rho, u, p = to_prim(U)
    return x, rho, u, p
