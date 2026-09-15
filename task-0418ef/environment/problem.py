"""
1D Brusselator reaction-diffusion system (method of lines).

The Brusselator models an autocatalytic chemical reaction with diffusion:

  du_i/dt = A + u_i^2 * v_i - (B+1)*u_i + alpha * (u_{i-1} - 2*u_i + u_{i+1}) / dx^2
  dv_i/dt = B*u_i - u_i^2 * v_i + alpha * (v_{i-1} - 2*v_i + v_{i+1}) / dx^2

State vector layout: y = [u_0, u_1, ..., u_{N-1}, v_0, v_1, ..., v_{N-1}]
Periodic boundary conditions on the spatial domain [0, 1).

Parameters:
  A = 1.0, B = 3.0, alpha = 0.02
  N = 40 grid points per species (80 total ODEs)
  dx = 1/N = 0.025

Integration interval: t in [0, 2]
"""

import numpy as np

A_PARAM = 1.0
B_PARAM = 3.0
ALPHA = 0.02
N_GRID = 40
N_TOTAL = 2 * N_GRID  # 80
DX = 1.0 / N_GRID
T_START = 0.0
T_END = 2.0


def initial_condition():
    """Return initial state vector y0 of length N_TOTAL."""
    x = np.arange(N_GRID) * DX
    u = A_PARAM + 0.5 * np.sin(2.0 * np.pi * x)
    v = B_PARAM / A_PARAM + 0.1 * np.cos(2.0 * np.pi * x)
    return np.concatenate([u, v])


def rhs(y, t):
    """
    Compute the right-hand side f(y, t) of the ODE system dy/dt = f(y, t).

    Parameters
    ----------
    y : ndarray of shape (N_TOTAL,)
        Current state vector.
    t : float
        Current time (autonomous system, but included for interface consistency).

    Returns
    -------
    dydt : ndarray of shape (N_TOTAL,)
    """
    N = N_GRID
    u = y[:N]
    v = y[N:]

    # Diffusion (periodic BCs via np.roll)
    laplacian_u = (np.roll(u, 1) - 2.0 * u + np.roll(u, -1)) / (DX * DX)
    laplacian_v = (np.roll(v, 1) - 2.0 * v + np.roll(v, -1)) / (DX * DX)

    # Reaction + diffusion
    du = A_PARAM + u * u * v - (B_PARAM + 1.0) * u + ALPHA * laplacian_u
    dv = B_PARAM * u - u * u * v + ALPHA * laplacian_v

    return np.concatenate([du, dv])


def sparsity_pattern():
    """
    Return the sparsity pattern of the Jacobian df/dy.

    Returns
    -------
    pattern : set of (int, int)
        Set of (row, col) tuples indicating positions where the Jacobian
        may have nonzero entries.
    """
    pattern = set()
    N = N_GRID

    for i in range(N):
        # Row i: equation for u_i
        # Depends on u_{i-1}, u_i, u_{i+1} (diffusion) and v_i (reaction)
        pattern.add((i, (i - 1) % N))       # u_{i-1}
        pattern.add((i, i))                  # u_i
        pattern.add((i, (i + 1) % N))       # u_{i+1}
        pattern.add((i, N + i))              # v_i

        # Row N+i: equation for v_i
        # Depends on u_i (reaction) and v_{i-1}, v_i, v_{i+1} (diffusion)
        pattern.add((N + i, i))              # u_i
        pattern.add((N + i, N + (i - 1) % N))  # v_{i-1}
        pattern.add((N + i, N + i))          # v_i
        pattern.add((N + i, N + (i + 1) % N))  # v_{i+1}

    return pattern
