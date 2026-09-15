#!/usr/bin/env python3
"""
Solver for advection-diffusion equation on non-uniform periodic grid.
Computes eigenvalue spectrum, stability limits, and time-stepping error.
"""

import json
import ctypes
import numpy as np
import os
import sys


def load_fdweights_lib():
    """Load the C shared library for FD weight computation."""
    lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'libfdweights.so')
    if not os.path.exists(lib_path):
        print(f"Error: {lib_path} not found. Run 'make' first.",
              file=sys.stderr)
        sys.exit(1)
    lib = ctypes.CDLL(lib_path)
    lib.compute_fd_weights.argtypes = [
        ctypes.c_double,
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.compute_fd_weights.restype = None
    return lib


def generate_grid(N, alpha, L=2 * np.pi):
    """Generate non-uniform periodic grid with sinusoidal stretching."""
    j = np.arange(N)
    return L * (j / N + alpha / (2 * np.pi) * np.sin(2 * np.pi * j / N))


def compute_weights(lib, x0, stencil_pts, deriv_order):
    """Call C library to compute FD weights."""
    n = len(stencil_pts)
    xs_c = (ctypes.c_double * n)(*stencil_pts)
    w_c = (ctypes.c_double * n)()
    lib.compute_fd_weights(x0, xs_c, n, deriv_order, w_c)
    return np.array([w_c[i] for i in range(n)])


def build_operator(lib, x, a, nu, hw=2):
    """Build spatial operator L = -a*D1 + nu*D2."""
    N = len(x)
    D1 = np.zeros((N, N))
    D2 = np.zeros((N, N))

    for i in range(N):
        indices = [(i + k) % N for k in range(-hw, hw + 1)]
        x_stencil = np.array([x[idx] for idx in indices])

        w1 = compute_weights(lib, x[i], x_stencil, 1)
        w2 = compute_weights(lib, x[i], x_stencil, 2)

        for k_idx, j in enumerate(indices):
            D1[i, j] += w1[k_idx]
            D2[i, j] += w2[k_idx]

    return -a * D1 + nu * D2


def forward_euler_max_dt(eigenvalues):
    """Compute maximum stable dt for Forward Euler."""
    dt_max = float('inf')
    for lam in eigenvalues:
        if abs(lam) < 1e-14:
            continue
        if lam.real >= 0:
            return 0.0
        dt_j = -2 * lam.real / (lam.real ** 2 + lam.imag ** 2)
        dt_max = min(dt_max, dt_j)
    return dt_max


def rk4_max_dt(eigenvalues):
    """Compute maximum stable dt for Classical RK4."""
    dt_max = float('inf')
    for lam in eigenvalues:
        if abs(lam) < 1e-14:
            continue
        if lam.real >= 0:
            return 0.0
        dt_j = -2 * lam.real / (lam.real ** 2 + lam.imag ** 2)
        dt_max = min(dt_max, dt_j)
    return dt_max


def rk4_step(L_op, u, dt):
    """Single Classical RK4 time step for u' = L_op @ u."""
    k1 = L_op @ u
    k2 = L_op @ (u + 0.5 * dt * k1)
    k3 = L_op @ (u + 0.5 * dt * k2)
    k4 = L_op @ (u + dt * k3)
    return u + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)


def exact_solution(x, t, a, nu):
    """Exact solution of u_t + a*u_x = nu*u_xx with periodic IC."""
    return (np.exp(-nu * t) * np.sin(x - a * t)
            + 0.5 * np.exp(-4 * nu * t) * np.sin(3 * (x - a * t)))


def main():
    with open('/app/config.json') as f:
        config = json.load(f)

    N = config['grid']['N']
    alpha = config['grid']['stretching_alpha']
    a = config['pde']['advection_speed']
    nu = config['pde']['diffusion_coeff']
    hw = config['discretization']['stencil_half_width']
    T_final = config['simulation']['final_time']
    dt_frac = config['simulation']['dt_fraction']

    lib = load_fdweights_lib()
    x = generate_grid(N, alpha)
    L_op = build_operator(lib, x, a, nu, hw)

    eigenvalues = np.linalg.eigvals(L_op)
    spectral_radius = float(np.max(np.abs(eigenvalues)))

    dt_fe = forward_euler_max_dt(eigenvalues)
    dt_rk4 = rk4_max_dt(eigenvalues)

    if dt_rk4 <= 1e-15:
        print("Warning: RK4 stability limit is zero or negative",
              file=sys.stderr)
        dt_sim = 1e-3
    else:
        dt_sim = dt_frac * dt_rk4
    nsteps = max(1, int(np.ceil(T_final / dt_sim)))
    dt_sim = T_final / nsteps

    u = np.sin(x) + 0.5 * np.sin(3 * x)
    for _ in range(nsteps):
        u = rk4_step(L_op, u, dt_sim)

    u_exact = exact_solution(x, T_final, a, nu)
    rms_error = float(np.sqrt(np.mean((u - u_exact) ** 2)))

    # FD weights at j=32
    i_test = 32
    indices_32 = [(i_test + k) % N for k in range(-hw, hw + 1)]
    x_stencil_32 = np.array([x[idx] for idx in indices_32])
    w1_32 = compute_weights(lib, x[i_test], x_stencil_32, 1)
    w2_32 = compute_weights(lib, x[i_test], x_stencil_32, 2)

    sort_idx = np.argsort(np.abs(eigenvalues))
    eig_sorted = eigenvalues[sort_idx]

    results = {
        'spectral_radius': spectral_radius,
        'dt_max_forward_euler': float(dt_fe),
        'dt_max_rk4': float(dt_rk4),
        'rk4_simulation_l2_error': rms_error,
        'eigenvalues_real': [float(e.real) for e in eig_sorted],
        'eigenvalues_imag': [float(e.imag) for e in eig_sorted],
        'fd_weights_d1_at_j32': [float(v) for v in w1_32],
        'fd_weights_d2_at_j32': [float(v) for v in w2_32],
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Spectral radius: {spectral_radius:.6f}")
    print(f"FE max dt: {dt_fe:.6e}")
    print(f"RK4 max dt: {dt_rk4:.6e}")
    print(f"Simulation dt: {dt_sim:.6e} ({nsteps} steps)")
    print(f"RMS error: {rms_error:.6e}")


if __name__ == '__main__':
    main()
