#!/usr/bin/env python3

"""
Stability analysis of finite difference discretization on a non-uniform
periodic grid for the advection-diffusion equation.

Implements:
  1. Fornberg's algorithm for FD weights on non-uniform grids
  2. Periodic operator matrix construction
  3. Eigenvalue stability analysis (Forward Euler + RK4)
  4. RK4 time-stepping simulation with exact-solution error
"""

import json
import numpy as np


def fornberg_weights(x0, x, m):
    """
    Fornberg's algorithm for finite difference weights.

    Parameters
    ----------
    x0 : float
        Point at which the derivative is approximated.
    x : array-like
        Stencil points (length n+1).
    m : int
        Maximum derivative order to compute.

    Returns
    -------
    c : ndarray, shape (n+1, m+1)
        c[j, k] = weight for point x[j], derivative order k.
    """
    n = len(x) - 1
    c = np.zeros((n + 1, m + 1))
    c1 = 1.0
    c4 = x[0] - x0
    c[0, 0] = 1.0

    for i in range(1, n + 1):
        mn = min(i, m)
        c2 = 1.0
        c5 = c4
        c4 = x[i] - x0
        for j in range(i):
            c3 = x[i] - x[j]
            c2 *= c3
            if j == i - 1:
                for k in range(mn, 0, -1):
                    c[i, k] = c1 * (k * c[i - 1, k - 1] - c5 * c[i - 1, k]) / c2
                c[i, 0] = -c1 * c5 * c[i - 1, 0] / c2
            for k in range(mn, 0, -1):
                c[j, k] = (c4 * c[j, k] - k * c[j, k - 1]) / c3
            c[j, 0] = c4 * c[j, 0] / c3
        c1 = c2

    return c


def generate_grid(N, alpha, L=2 * np.pi):
    """Generate non-uniform periodic grid with sinusoidal stretching."""
    j = np.arange(N)
    return L * (j / N + alpha / (2 * np.pi) * np.sin(2 * np.pi * j / N))


def build_operator(x, a, nu, hw=2):
    """
    Build spatial operator matrix L = -a*D1 + nu*D2 on periodic non-uniform grid.

    Uses Fornberg FD weights with centered stencils of half-width hw.
    Handles periodic coordinate unwrapping at domain boundaries.
    """
    N = len(x)
    L_period = 2 * np.pi
    D1 = np.zeros((N, N))
    D2 = np.zeros((N, N))

    for i in range(N):
        # Centered stencil indices with periodic wrapping
        indices = [(i + k) % N for k in range(-hw, hw + 1)]

        # Stencil coordinates, unwrapped so they are contiguous near x[i]
        x_stencil = np.array([x[idx] for idx in indices])
        for k in range(len(x_stencil)):
            diff = x_stencil[k] - x[i]
            if diff > L_period / 2:
                x_stencil[k] -= L_period
            elif diff < -L_period / 2:
                x_stencil[k] += L_period

        # Compute weights for 1st and 2nd derivatives
        c = fornberg_weights(x[i], x_stencil, 2)

        for k_idx, j_col in enumerate(indices):
            D1[i, j_col] += c[k_idx, 1]
            D2[i, j_col] += c[k_idx, 2]

    return -a * D1 + nu * D2, D1, D2


def rk4_stability_function(z):
    """RK4 stability polynomial R(z)."""
    return 1 + z + z ** 2 / 2 + z ** 3 / 6 + z ** 4 / 24


def forward_euler_max_dt(eigenvalues):
    """
    Maximum stable dt for Forward Euler.

    For each eigenvalue lambda, the stability constraint |1 + lambda*dt| <= 1
    gives dt <= -2*Re(lambda) / |lambda|^2.
    """
    dt_max = float('inf')
    for lam in eigenvalues:
        re = lam.real
        if abs(lam) < 1e-14:
            continue
        if re >= 0:
            return 0.0
        dt_j = -2 * re / (re ** 2 + lam.imag ** 2)
        dt_max = min(dt_max, dt_j)
    return dt_max


def rk4_max_dt(eigenvalues, tol=1e-12):
    """
    Maximum stable dt for Classical RK4 via binary search.

    Finds the largest dt such that |R(lambda_j * dt)| <= 1 for all eigenvalues.
    """
    dt_low = 0.0
    dt_high = 0.1

    # Find an upper bound where at least one eigenvalue is unstable
    for _ in range(100):
        z = eigenvalues * dt_high
        if np.max(np.abs(rk4_stability_function(z))) > 1.0:
            break
        dt_high *= 2

    # Binary search
    for _ in range(200):
        dt_mid = (dt_low + dt_high) / 2
        z = eigenvalues * dt_mid
        if np.max(np.abs(rk4_stability_function(z))) <= 1.0:
            dt_low = dt_mid
        else:
            dt_high = dt_mid
        if dt_high - dt_low < tol:
            break

    return dt_low


def rk4_step(L_op, u, dt):
    """Single Classical RK4 time step for u' = L_op @ u."""
    k1 = L_op @ u
    k2 = L_op @ (u + 0.5 * dt * k1)
    k3 = L_op @ (u + 0.5 * dt * k2)
    k4 = L_op @ (u + dt * k3)
    return u + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)


def exact_solution(x, t, a, nu):
    """
    Exact solution of u_t + a*u_x = nu*u_xx with periodic BC.

    For initial condition u(x,0) = sin(x) + 0.5*sin(3x), each Fourier mode
    k decays as exp(-nu*k^2*t) and advects at speed a.
    """
    return (np.exp(-nu * t) * np.sin(x - a * t)
            + 0.5 * np.exp(-9 * nu * t) * np.sin(3 * (x - a * t)))


def main():
    # Load configuration
    with open('/opt/task/config.json', 'r') as f:
        config = json.load(f)

    N = config['grid']['N']
    alpha = config['grid']['stretching_alpha']
    a = config['pde']['advection_speed']
    nu = config['pde']['diffusion_coeff']
    hw = config['discretization']['stencil_half_width']
    T_final = config['simulation']['final_time']
    dt_frac = config['simulation']['dt_fraction']

    # Generate non-uniform grid
    x = generate_grid(N, alpha)

    # Build operator matrix
    L_op, D1, D2 = build_operator(x, a, nu, hw)

    # Eigenvalue analysis
    eigenvalues = np.linalg.eigvals(L_op)
    spectral_radius = float(np.max(np.abs(eigenvalues)))

    # Stability limits
    dt_fe = forward_euler_max_dt(eigenvalues)
    dt_rk4 = rk4_max_dt(eigenvalues)

    # RK4 simulation at fraction of stability limit
    dt_sim = dt_frac * dt_rk4
    nsteps = int(np.ceil(T_final / dt_sim))
    dt_sim = T_final / nsteps  # adjust to hit T_final exactly

    u = np.sin(x) + 0.5 * np.sin(3 * x)
    for _ in range(nsteps):
        u = rk4_step(L_op, u, dt_sim)

    # RMS error against exact solution
    u_exact = exact_solution(x, T_final, a, nu)
    rms_error = float(np.sqrt(np.mean((u - u_exact) ** 2)))

    # Fornberg weights at j=32
    i_test = 32
    indices_32 = [(i_test + k) % N for k in range(-hw, hw + 1)]
    x_stencil_32 = np.array([x[idx] for idx in indices_32])
    L_period = 2 * np.pi
    for k in range(len(x_stencil_32)):
        diff = x_stencil_32[k] - x[i_test]
        if diff > L_period / 2:
            x_stencil_32[k] -= L_period
        elif diff < -L_period / 2:
            x_stencil_32[k] += L_period
    c_32 = fornberg_weights(x[i_test], x_stencil_32, 2)

    # Sort eigenvalues by magnitude (ascending)
    sort_idx = np.argsort(np.abs(eigenvalues))
    eig_sorted = eigenvalues[sort_idx]

    # Assemble results
    results = {
        'spectral_radius': spectral_radius,
        'dt_max_forward_euler': float(dt_fe),
        'dt_max_rk4': float(dt_rk4),
        'rk4_simulation_l2_error': rms_error,
        'rk4_simulation_dt': float(dt_sim),
        'rk4_simulation_nsteps': int(nsteps),
        'eigenvalues_real': [float(e.real) for e in eig_sorted],
        'eigenvalues_imag': [float(e.imag) for e in eig_sorted],
        'fornberg_weights_d1_at_j32': [float(v) for v in c_32[:, 1]],
        'fornberg_weights_d2_at_j32': [float(v) for v in c_32[:, 2]],
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Grid points: {N}")
    print(f"Spectral radius: {spectral_radius:.6f}")
    print(f"Forward Euler max dt: {dt_fe:.6e}")
    print(f"RK4 max dt: {dt_rk4:.6e}")
    print(f"Simulation dt: {dt_sim:.6e} ({nsteps} steps)")
    print(f"RMS error at T={T_final}: {rms_error:.6e}")
    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
