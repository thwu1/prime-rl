"""Kurganov-Tadmor central scheme for 1D Euler equations.

"""
import numpy as np


def solve(rhoL, uL, pL, rhoR, uR, pR, gamma, x_left, x_right, x0, t_end, N, cfl=0.5):
    """
    Solve 1D Euler equations using Kurganov-Tadmor central scheme
    with MUSCL reconstruction and van Albada limiter.

    Returns (x_centers, rho, u, p) as numpy arrays.
    """
    gm1 = gamma - 1.0
    dx = (x_right - x_left) / N
    xc = np.linspace(x_left + 0.5 * dx, x_right - 0.5 * dx, N)

    # Conservative variables: U = [rho, rho*u, E]
    U = np.zeros((3, N))
    for j in range(N):
        if xc[j] < x0:
            r, v, p_loc = rhoL, uL, pL
        else:
            r, v, p_loc = rhoR, uR, pR
        U[0, j] = r
        U[1, j] = r * v
        U[2, j] = p_loc / gm1 + 0.5 * r * v * v

    t = 0.0
    while t < t_end - 1e-15:
        # Time step from CFL
        smax = 0.0
        for j in range(N):
            r = U[0, j]
            v = U[1, j] / r
            p_loc = gm1 * (U[2, j] - 0.5 * r * v * v)
            if p_loc < 1e-15:
                p_loc = 1e-15
            a = np.sqrt(gamma * p_loc / r)
            smax = max(smax, abs(v) + a)
        dt = cfl * dx / smax
        if t + dt > t_end:
            dt = t_end - t

        # SSP-RK2
        L1 = _rhs(U, dx, N, gamma)
        U1 = U + dt * L1
        _fix_positivity(U1, U, N, gm1)

        L2 = _rhs(U1, dx, N, gamma)
        U = 0.5 * U + 0.5 * (U1 + dt * L2)
        _fix_positivity(U, U, N, gm1)

        t += dt

    rho_out = U[0, :]
    u_out = U[1, :] / U[0, :]
    p_out = gm1 * (U[2, :] - 0.5 * U[0, :] * u_out ** 2)
    return xc, rho_out, u_out, p_out


def _fix_positivity(U, U_fallback, N, gm1):
    for j in range(N):
        if U[0, j] <= 0:
            U[:, j] = U_fallback[:, j]
            continue
        v = U[1, j] / U[0, j]
        p_loc = gm1 * (U[2, j] - 0.5 * U[0, j] * v * v)
        if p_loc <= 0:
            U[:, j] = U_fallback[:, j]


def _van_albada(dL, dR):
    """Component-wise van Albada limiter."""
    result = np.zeros(3)
    for i in range(3):
        if dL[i] * dR[i] > 0:
            result[i] = (dL[i] * dR[i] ** 2 + dR[i] * dL[i] ** 2) / (
                dL[i] ** 2 + dR[i] ** 2 + 1e-30
            )
    return result


def _rhs(U, dx, N, gamma):
    gm1 = gamma - 1.0

    # Ghost cells (transmissive BC)
    Ug = np.zeros((3, N + 4))
    Ug[:, 2 : N + 2] = U
    Ug[:, 0] = Ug[:, 1] = U[:, 0]
    Ug[:, N + 2] = Ug[:, N + 3] = U[:, N - 1]

    # Limited slopes at each ghost cell
    slopes = np.zeros((3, N + 4))
    for j in range(1, N + 3):
        dL = Ug[:, j] - Ug[:, j - 1]
        dR = Ug[:, j + 1] - Ug[:, j]
        slopes[:, j] = _van_albada(dL, dR)

    # KT numerical flux at N+1 faces
    H = np.zeros((3, N + 1))
    for k in range(N + 1):
        jL = k + 1
        jR = k + 2

        # MUSCL reconstruction
        UL = Ug[:, jL] + 0.5 * slopes[:, jL]
        UR = Ug[:, jR] - 0.5 * slopes[:, jR]

        # Positivity guards
        if UL[0] <= 0:
            UL = Ug[:, jL].copy()
        pL_chk = gm1 * (UL[2] - 0.5 * UL[1] ** 2 / UL[0])
        if pL_chk <= 0:
            UL = Ug[:, jL].copy()

        if UR[0] <= 0:
            UR = Ug[:, jR].copy()
        pR_chk = gm1 * (UR[2] - 0.5 * UR[1] ** 2 / UR[0])
        if pR_chk <= 0:
            UR = Ug[:, jR].copy()

        # Fluxes and wave speeds
        rL = UL[0]
        vL = UL[1] / rL
        pL_loc = gm1 * (UL[2] - 0.5 * rL * vL * vL)
        if pL_loc < 1e-15:
            pL_loc = 1e-15
        aL = np.sqrt(gamma * pL_loc / rL)

        rR = UR[0]
        vR = UR[1] / rR
        pR_loc = gm1 * (UR[2] - 0.5 * rR * vR * vR)
        if pR_loc < 1e-15:
            pR_loc = 1e-15
        aR_loc = np.sqrt(gamma * pR_loc / rR)

        a_max = max(abs(vL) + aL, abs(vR) + aR_loc)

        FL = np.array([rL * vL, rL * vL * vL + pL_loc, vL * (UL[2] + pL_loc)])
        FR = np.array([rR * vR, rR * vR * vR + pR_loc, vR * (UR[2] + pR_loc)])

        H[:, k] = 0.5 * (FL + FR) - 0.5 * a_max * (UR - UL)

    # Divergence
    L = np.zeros((3, N))
    for j in range(N):
        L[:, j] = -(H[:, j + 1] - H[:, j]) / dx
    return L
