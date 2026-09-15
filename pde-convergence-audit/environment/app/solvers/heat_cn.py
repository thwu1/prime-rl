"""
Solver for the 1D heat equation: u_t = u_xx on (0,1), T_final = 0.1.
Boundary conditions: u(0,t) = u(1,t) = 0 (Dirichlet).
Initial condition: u(x,0) = sin(pi*x).
Exact solution: exp(-pi^2 * t) * sin(pi*x).

Uses N interior spatial grid points and N time steps with an implicit
scheme, solved via the Thomas algorithm (C kernel).
"""
import numpy as np


def solve(N):
    """Solve at resolution N and return the L2 (RMS) error at T_final."""
    from bindings import thomas_solve

    T_final = 0.1
    N_t = N
    h = 1.0 / (N + 1)
    dt = T_final / N_t
    r = dt / h**2

    x = np.linspace(h, 1.0 - h, N)
    u = np.sin(np.pi * x)

    # Implicit time-stepping: backward Euler
    # Tridiagonal system: (-r) * u_{i-1} + (1+2r) * u_i + (-r) * u_{i+1} = u_old
    a_diag = -r * np.ones(N)
    b_diag = (1.0 + 2.0 * r) * np.ones(N)
    c_diag = -r * np.ones(N)

    for _ in range(N_t):
        u = thomas_solve(a_diag, b_diag, c_diag, u.copy())

    u_exact = np.exp(-np.pi**2 * T_final) * np.sin(np.pi * x)
    return float(np.sqrt(np.mean((u - u_exact) ** 2)))
