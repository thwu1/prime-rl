"""
2D Brusselator Reaction-Diffusion System
=========================================

PDE system on the unit square [0, 1] x [0, 1]:

    dU/dt = alpha * laplacian(U) + B + U^2 * V - (A + 1) * U + f(x, y, t)
    dV/dt = alpha * laplacian(V) + A * U - U^2 * V

Parameters:
    A = 3.4,  B = 1.0,  alpha = 10.0
    Grid: N = 32 points per dimension,  dx = 1 / (N - 1)

Boundary conditions:
    Zero-flux (Neumann / clamped) -- at grid boundaries the neighbor
    index is clamped to [0, N-1], which gives a zero discrete normal
    derivative.

Time span: [0, 11.5]

Forcing:
    f(x, y, t) = 5.0   if t >= 1.1 and (x - 0.3)^2 + (y - 0.6)^2 <= 0.01
               = 0.0   otherwise

Initial conditions:
    U(x, y, 0) = 22 * (y * (1 - y))^{3/2}
    V(x, y, 0) = 27 * (x * (1 - x))^{3/2}

State vector layout (row-major / C-order):
    u[0      : N*N  ]  =  U.ravel()
    u[N*N    : 2*N*N]  =  V.ravel()
    Index of U(i, j)   =  i * N + j
    Index of V(i, j)   =  N * N + i * N + j
"""

import numpy as np
from scipy.integrate import solve_ivp

# ---------------------------------------------------------------------------
# Grid and physical parameters
# ---------------------------------------------------------------------------
N = 32
dx = 1.0 / (N - 1)
A_PARAM = 3.4
B_PARAM = 1.0
ALPHA = 10.0
ALPHA_DX2 = ALPHA / (dx ** 2)
TSPAN = (0.0, 11.5)
OUTPUT_TIMES = [0.0, 1.0, 2.0, 5.0, 11.5]

xyd = np.linspace(0, 1, N)


# ---------------------------------------------------------------------------
# Forcing
# ---------------------------------------------------------------------------
def brusselator_forcing(x, y, t):
    """Localized bump forcing active for t >= 1.1."""
    if t >= 1.1 and (x - 0.3) ** 2 + (y - 0.6) ** 2 <= 0.01:
        return 5.0
    return 0.0


# ---------------------------------------------------------------------------
# Initial conditions
# ---------------------------------------------------------------------------
def initial_conditions():
    """Return initial state vector u0 of length 2 * N * N."""
    U = np.zeros((N, N))
    V = np.zeros((N, N))
    for i in range(N):
        for j in range(N):
            x, y = xyd[i], xyd[j]
            U[i, j] = 22.0 * (y * (1.0 - y)) ** 1.5
            V[i, j] = 27.0 * (x * (1.0 - x)) ** 1.5
    return np.concatenate([U.ravel(), V.ravel()])


# ---------------------------------------------------------------------------
# Right-hand side (naive reference implementation)
# ---------------------------------------------------------------------------
def brusselator_rhs(t, u):
    """Right-hand side for the Brusselator PDE system."""
    nn = N * N
    U = u[:nn].reshape(N, N)
    V = u[nn:].reshape(N, N)
    dU = np.zeros_like(U)
    dV = np.zeros_like(V)

    for i in range(N):
        for j in range(N):
            ip1 = (i + 1) % N
            im1 = (i - 1) % N
            jp1 = (j + 1) % N
            jm1 = (j - 1) % N

            lap_U = ALPHA_DX2 * (
                U[im1, j] + U[ip1, j] + U[i, jp1] + U[i, jm1] - 4 * U[i, j]
            )
            lap_V = ALPHA_DX2 * (
                V[im1, j] + V[ip1, j] + V[i, jp1] + V[i, jm1] - 4 * V[i, j]
            )

            x_val, y_val = xyd[i], xyd[j]
            f_val = brusselator_forcing(x_val, y_val, t)

            dU[i, j] = (
                lap_U
                + B_PARAM
                + U[i, j] ** 2 * V[i, j]
                - (A_PARAM + 1) * U[i, j]
                + f_val
            )
            dV[i, j] = (
                lap_V + A_PARAM * U[i, j] - U[i, j] ** 2 * V[i, j]
            )

    return np.concatenate([dU.ravel(), dV.ravel()])


# ---------------------------------------------------------------------------
# Naive solver (for reference -- will be extremely slow or fail)
# ---------------------------------------------------------------------------
def naive_solve():
    """
    Attempt to solve with an explicit method (RK45).

    This will be extremely slow or fail outright because the Brusselator
    with diffusion is a stiff system.
    """
    u0 = initial_conditions()
    sol = solve_ivp(
        brusselator_rhs,
        TSPAN,
        u0,
        method="RK45",
        t_eval=OUTPUT_TIMES,
        rtol=1e-6,
        atol=1e-8,
    )
    return sol
