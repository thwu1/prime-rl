"""
1D Brusselator reaction-diffusion system.
Spatial discretization via centered finite differences on a uniform grid.
Dirichlet boundary conditions set to the homogeneous steady-state values.
Interleaved state vector: [u_1, v_1, u_2, v_2, ..., u_N, v_N].
"""
import numpy as np
from scipy import sparse


def make_initial_condition(N, A=1.0, B=3.0):
    """Create initial condition vector for the Brusselator."""
    dx = 1.0 / (N + 1)
    x_grid = np.linspace(dx, 1.0 - dx, N)
    y0 = np.zeros(2 * N)
    y0[0::2] = 1.0 + np.sin(2.0 * np.pi * x_grid)
    y0[1::2] = 3.0
    return y0


def brusselator_rhs(y, N, Du=0.02, Dv=0.02, A=1.0, B=3.0):
    """Evaluate the RHS of the semi-discretized Brusselator PDE system."""
    dx = 1.0 / (N + 1)
    dx2 = dx * dx

    u = y[0::2]
    v = y[1::2]

    u_left = A
    u_right = A
    v_left = A / B
    v_right = A / B

    u_pad = np.concatenate(([u_left], u, [u_right]))
    v_pad = np.concatenate(([v_left], v, [v_right]))

    dydt = np.zeros_like(y)
    dydt[0::2] = (Du * (u_pad[:-2] - 2.0 * u_pad[1:-1] + u_pad[2:]) / dx2
                  + A - (B + 1.0) * u + u * u * v)
    dydt[1::2] = (Dv * (v_pad[:-2] - 2.0 * v_pad[1:-1] + v_pad[2:]) / dx2
                  + B * u - u * u * v)
    return dydt


def build_sparsity_pattern(N):
    """Build binary CSC sparsity pattern for the interleaved Brusselator Jacobian."""
    n = 2 * N
    rows, cols = [], []

    for i in range(N):
        ui = 2 * i
        vi = 2 * i + 1

        # du_i/dt depends on: u_{i-1}, u_i, u_{i+1}, v_i
        if i > 0:
            rows.append(ui); cols.append(2 * (i - 1))
        rows.append(ui); cols.append(ui)
        if i < N - 1:
            rows.append(ui); cols.append(2 * (i + 1))
        rows.append(ui); cols.append(vi)

        # dv_i/dt depends on: v_{i-1}, u_i, v_i, v_{i+1}
        if i > 0:
            rows.append(vi); cols.append(2 * (i - 1) + 1)
        rows.append(vi); cols.append(ui)
        rows.append(vi); cols.append(vi)
        if i < N - 1:
            rows.append(vi); cols.append(2 * (i + 1) + 1)

    data = np.ones(len(rows), dtype=np.float64)
    return sparse.csc_matrix((data, (rows, cols)), shape=(n, n))
