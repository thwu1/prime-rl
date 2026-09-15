"""
Solver for the 1D linear advection equation: u_t + c*u_x = 0 on [0,1)
with periodic boundary conditions, c = 1.0, T_final = 0.5.
Initial condition: u(x,0) = sin(2*pi*x).
Exact solution: u(x,t) = sin(2*pi*(x - c*t)).

Uses N grid points with CFL number 0.8.
Time stepping via the C kernel.
"""
import numpy as np


def solve(N):
    """Solve at resolution N and return the L2 (RMS) error at T_final."""
    from bindings import lax_wendroff_step

    T_final = 0.5
    c = 1.0
    h = 1.0 / N
    CFL_target = 0.8
    dt = CFL_target * h / c
    N_t = int(round(T_final / dt))
    dt = T_final / N_t  # adjust to hit T_final exactly
    nu = c * dt / h

    x = np.linspace(0.0, 1.0 - h, N)
    u = np.sin(2.0 * np.pi * x)

    for _ in range(N_t):
        u = lax_wendroff_step(u, nu)

    u_exact = np.sin(2.0 * np.pi * (x - c * T_final))
    return float(np.sqrt(np.mean((u - u_exact) ** 2)))
