#!/usr/bin/env python3
"""

Complete DGSEM solver for 1D compressible Euler equations with
entropy-stable flux differencing.
"""

import numpy as np
import csv
import json
import os

GAMMA = 1.4


# ======================================================================
# Polynomial basis functions (LGL nodes, derivative matrix)
# ======================================================================

def legendre_poly(n, x):
    """Evaluate Legendre polynomial P_n(x) and its derivative P_n'(x)."""
    if n == 0:
        return 1.0, 0.0
    elif n == 1:
        return x, 1.0
    L_prev, L_curr = 1.0, x
    dL_prev, dL_curr = 0.0, 1.0
    for k in range(2, n + 1):
        L_next = ((2 * k - 1) * x * L_curr - (k - 1) * L_prev) / k
        dL_next = dL_prev + (2 * k - 1) * L_curr
        L_prev, L_curr = L_curr, L_next
        dL_prev, dL_curr = dL_curr, dL_next
    return L_curr, dL_curr


def lgl_nodes_weights(N):
    """Compute N+1 Legendre-Gauss-Lobatto nodes and weights on [-1, 1].

    LGL nodes are roots of (1-x^2)*P_N'(x) = 0. Interior nodes found
    via Newton iteration starting from Chebyshev-Gauss-Lobatto initial guesses.
    """
    if N == 0:
        return np.array([0.0]), np.array([2.0])
    if N == 1:
        return np.array([-1.0, 1.0]), np.array([1.0, 1.0])

    nodes = np.zeros(N + 1)
    nodes[0] = -1.0
    nodes[N] = 1.0

    # Chebyshev-Gauss-Lobatto initial guesses for interior nodes
    for j in range(1, N):
        nodes[j] = -np.cos(np.pi * j / N)

    # Newton iteration: find roots of P_N'(x) for interior nodes
    for j in range(1, N):
        x = nodes[j]
        for _ in range(100):
            L, dL = legendre_poly(N, x)
            if abs(1 - x * x) < 1e-16:
                break
            # P_N''(x) via recurrence relation
            d2L = (2.0 * x * dL - N * (N + 1) * L) / (1.0 - x * x)
            dx = -dL / d2L
            x = x + dx
            if abs(dx) < 1e-15:
                break
        nodes[j] = x

    nodes.sort()

    # Weights: w_j = 2 / (N*(N+1)*[P_N(x_j)]^2)
    weights = np.zeros(N + 1)
    for j in range(N + 1):
        L, _ = legendre_poly(N, nodes[j])
        weights[j] = 2.0 / (N * (N + 1) * L * L)

    return nodes, weights


def barycentric_weights(nodes):
    """Compute barycentric interpolation weights."""
    n = len(nodes)
    w = np.ones(n)
    for j in range(n):
        for k in range(n):
            if k != j:
                w[j] /= (nodes[j] - nodes[k])
    return w


def derivative_matrix(nodes):
    """Build polynomial derivative matrix D on given nodes."""
    n = len(nodes)
    w = barycentric_weights(nodes)
    D = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i != j:
                D[i, j] = (w[j] / w[i]) / (nodes[i] - nodes[j])
        D[i, i] = -np.sum(D[i, :])
    return D


# ======================================================================
# Euler equations: fluxes and entropy
# ======================================================================

def conserved_to_primitive(U):
    """Convert [rho, rho*v, E] to [rho, v, p]."""
    rho = U[0]
    v = U[1] / rho
    p = (GAMMA - 1.0) * (U[2] - 0.5 * rho * v**2)
    return np.array([rho, v, p])


def primitive_to_conserved(W):
    """Convert [rho, v, p] to [rho, rho*v, E]."""
    rho, v, p = W[0], W[1], W[2]
    E = p / (GAMMA - 1.0) + 0.5 * rho * v**2
    return np.array([rho, rho * v, E])


def euler_flux(U):
    """Physical flux F(U) for 1D Euler."""
    rho, rho_v, E = U[0], U[1], U[2]
    v = rho_v / rho
    p = (GAMMA - 1.0) * (E - 0.5 * rho * v**2)
    return np.array([rho_v, rho_v * v + p, (E + p) * v])


def max_wave_speed(U):
    """Maximum wave speed |v| + c."""
    rho = U[0]
    v = U[1] / rho
    p = (GAMMA - 1.0) * (U[2] - 0.5 * rho * v**2)
    c = np.sqrt(GAMMA * np.abs(p) / rho)
    return np.abs(v) + c


def lax_friedrichs_flux(U_L, U_R):
    """Local Lax-Friedrichs (Rusanov) numerical flux."""
    F_L = euler_flux(U_L)
    F_R = euler_flux(U_R)
    lambda_max = max(max_wave_speed(U_L), max_wave_speed(U_R))
    return 0.5 * (F_L + F_R) - 0.5 * lambda_max * (U_R - U_L)


def ln_mean(a, b):
    """Logarithmic mean with numerically stable implementation.

    ln_mean(a, b) = (a - b) / (ln(a) - ln(b))
    Uses Taylor expansion when a ~ b to avoid cancellation.
    """
    xi = a / b
    f = (xi - 1.0) / (xi + 1.0)
    u = f * f
    if u < 1e-4:
        F = 1.0 + u / 3.0 + u * u / 5.0 + u * u * u / 7.0
        return (a + b) / (2.0 * F)
    else:
        return (a - b) / (np.log(a) - np.log(b))


def chandrashekar_flux(U_L, U_R):
    """Entropy-conservative two-point flux (Chandrashekar 2013)."""
    rho_L = U_L[0]
    v_L = U_L[1] / rho_L
    p_L = (GAMMA - 1.0) * (U_L[2] - 0.5 * rho_L * v_L**2)

    rho_R = U_R[0]
    v_R = U_R[1] / rho_R
    p_R = (GAMMA - 1.0) * (U_R[2] - 0.5 * rho_R * v_R**2)

    # Inverse temperature
    beta_L = rho_L / (2.0 * p_L)
    beta_R = rho_R / (2.0 * p_R)

    # Logarithmic means
    rho_ln = ln_mean(rho_L, rho_R)
    beta_ln = ln_mean(beta_L, beta_R)

    # Arithmetic means
    rho_avg = 0.5 * (rho_L + rho_R)
    v_avg = 0.5 * (v_L + v_R)
    v2_avg = 0.5 * (v_L**2 + v_R**2)
    p_avg = rho_avg / (2.0 * beta_ln)

    # Flux components
    f1 = rho_ln * v_avg
    f2 = f1 * v_avg + p_avg
    f3 = f1 * (1.0 / (2.0 * (GAMMA - 1.0) * beta_ln)
               + v_avg**2 - 0.5 * v2_avg) + p_avg * v_avg

    return np.array([f1, f2, f3])


def mathematical_entropy(U):
    """S = -rho * s / (gamma - 1) where s = ln(p) - gamma * ln(rho)."""
    rho = U[0]
    v = U[1] / rho
    p = (GAMMA - 1.0) * (U[2] - 0.5 * rho * v**2)
    s = np.log(p) - GAMMA * np.log(rho)
    return -rho * s / (GAMMA - 1.0)


# ======================================================================
# DG solver classes and spatial discretization
# ======================================================================

class DGSolver:
    """1D DGSEM solver with precomputed LGL nodes, weights, and D matrix."""

    def __init__(self, N):
        self.N = N
        self.n_nodes = N + 1
        self.nodes, self.weights = lgl_nodes_weights(N)
        self.D = derivative_matrix(self.nodes)


class Mesh1D:
    """Simple uniform 1D mesh."""

    def __init__(self, x_min, x_max, n_elements, periodic=False):
        self.x_min = x_min
        self.x_max = x_max
        self.n_elements = n_elements
        self.dx = (x_max - x_min) / n_elements
        self.periodic = periodic

    def element_bounds(self, e):
        x_left = self.x_min + e * self.dx
        return x_left, x_left + self.dx

    def physical_nodes(self, e, ref_nodes):
        x_l, x_r = self.element_bounds(e)
        return 0.5 * (x_l + x_r) + 0.5 * self.dx * ref_nodes


def compute_rhs_flux_differencing(U_all, solver, mesh, surface_flux_func,
                                  volume_flux_func):
    """Compute dU/dt using strong-form flux-differencing DG with SBP-SAT."""
    n_elem = mesh.n_elements
    n_nodes = solver.n_nodes
    N = solver.N
    D = solver.D
    w = solver.weights
    jac_factor = 2.0 / mesh.dx

    dUdt = np.zeros_like(U_all)

    for e in range(n_elem):
        # Volume integral: -2 * sum_j D_{ij} * f_vol(U_i, U_j)
        for i in range(n_nodes):
            vol_sum = np.zeros(3)
            for j in range(n_nodes):
                if i != j:
                    fvol = volume_flux_func(U_all[e, :, i], U_all[e, :, j])
                else:
                    fvol = euler_flux(U_all[e, :, i])
                vol_sum += D[i, j] * fvol
            dUdt[e, :, i] = -2.0 * vol_sum

        # Neighbor states for surface fluxes
        if mesh.periodic:
            e_left = (e - 1) % n_elem
            e_right = (e + 1) % n_elem
            U_left_ext = U_all[e_left, :, N]
            U_right_ext = U_all[e_right, :, 0]
        else:
            if e > 0:
                U_left_ext = U_all[e - 1, :, N]
            else:
                U_left_ext = U_all[e, :, 0].copy()
            if e < n_elem - 1:
                U_right_ext = U_all[e + 1, :, 0]
            else:
                U_right_ext = U_all[e, :, N].copy()

        # Numerical surface fluxes
        f_surf_left = surface_flux_func(U_left_ext, U_all[e, :, 0])
        f_surf_right = surface_flux_func(U_all[e, :, N], U_right_ext)

        # Physical fluxes at boundaries
        f_phys_left = euler_flux(U_all[e, :, 0])
        f_phys_right = euler_flux(U_all[e, :, N])

        # SAT surface corrections (strong form)
        dUdt[e, :, 0] += (f_surf_left - f_phys_left) / w[0]
        dUdt[e, :, N] -= (f_surf_right - f_phys_right) / w[N]

        # Jacobian (reference to physical)
        dUdt[e] *= jac_factor

    return dUdt


def compute_max_dt(U_all, solver, mesh, cfl):
    """CFL-based maximum stable time step."""
    max_speed = 0.0
    for e in range(mesh.n_elements):
        for i in range(solver.n_nodes):
            speed = max_wave_speed(U_all[e, :, i])
            if speed > max_speed:
                max_speed = speed
    return cfl * mesh.dx / (max_speed * (2 * solver.N + 1))


# ======================================================================
# Time integration: SSP-RK3 (Shu-Osher)
# ======================================================================

def ssp_rk3_step(U, dt, rhs_func):
    """One step of the 3rd-order strong stability preserving Runge-Kutta."""
    k1 = rhs_func(U)
    U1 = U + dt * k1

    k2 = rhs_func(U1)
    U2 = 0.75 * U + 0.25 * (U1 + dt * k2)

    k3 = rhs_func(U2)
    U3 = (1.0 / 3.0) * U + (2.0 / 3.0) * (U2 + dt * k3)

    return U3


# ======================================================================
# Problem 1: Sod Shock Tube
# ======================================================================

def run_sod():
    """Run the Sod shock tube and write /app/results/sod.csv."""
    N = 3
    n_elements = 64
    cfl = 0.5
    t_final = 0.2

    solver = DGSolver(N)
    mesh = Mesh1D(0.0, 1.0, n_elements, periodic=False)

    # Initialize: per-element based on element center
    U_all = np.zeros((n_elements, 3, solver.n_nodes))
    for e in range(n_elements):
        x_l, x_r = mesh.element_bounds(e)
        x_center = 0.5 * (x_l + x_r)
        if x_center < 0.5:
            W = np.array([1.0, 0.0, 1.0])
        else:
            W = np.array([0.125, 0.0, 0.1])
        for i in range(solver.n_nodes):
            U_all[e, :, i] = primitive_to_conserved(W)

    # Fixed boundary states
    U_bc_left = U_all[0, :, 0].copy()
    U_bc_right = U_all[-1, :, -1].copy()

    def rhs(U):
        U_copy = U.copy()
        U_copy[0, :, 0] = U_bc_left
        U_copy[-1, :, -1] = U_bc_right
        return compute_rhs_flux_differencing(U_copy, solver, mesh,
                                             lax_friedrichs_flux,
                                             chandrashekar_flux)

    # Time integration loop
    t = 0.0
    step = 0
    while t < t_final - 1e-14:
        dt = compute_max_dt(U_all, solver, mesh, cfl)
        if t + dt > t_final:
            dt = t_final - t
        U_all = ssp_rk3_step(U_all, dt, rhs)
        t += dt
        step += 1

    print(f"  Sod: completed at t={t:.6f}, steps={step}")

    # Write cell-averaged results
    rows = []
    for e in range(n_elements):
        x_phys = mesh.physical_nodes(e, solver.nodes)
        x_center = 0.5 * (x_phys[0] + x_phys[-1])
        rho_avg = np.sum(solver.weights * U_all[e, 0, :]) / 2.0
        rho_v_avg = np.sum(solver.weights * U_all[e, 1, :]) / 2.0
        E_avg = np.sum(solver.weights * U_all[e, 2, :]) / 2.0
        U_avg = np.array([rho_avg, rho_v_avg, E_avg])
        W_avg = conserved_to_primitive(U_avg)
        rows.append({"x": x_center, "rho": W_avg[0], "v": W_avg[1], "p": W_avg[2]})

    rows.sort(key=lambda r: r["x"])
    with open("/app/results/sod.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["x", "rho", "v", "p"])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: f"{v:.10e}" for k, v in row.items()})

    print("  Sod: wrote /app/results/sod.csv")


# ======================================================================
# Problem 2: Entropy Conservation Test
# ======================================================================

def run_entropy_conservation():
    """Run entropy test and write /app/results/entropy.json."""
    N = 4
    n_elements = 16
    cfl = 0.3
    t_final = 2.0

    solver = DGSolver(N)
    mesh = Mesh1D(0.0, 1.0, n_elements, periodic=True)

    # Smooth initial condition
    U_all = np.zeros((n_elements, 3, solver.n_nodes))
    for e in range(n_elements):
        x_phys = mesh.physical_nodes(e, solver.nodes)
        for i in range(solver.n_nodes):
            rho = 1.0 + 0.5 * np.sin(2.0 * np.pi * x_phys[i])
            v = 1.0
            p = 1.0
            W = np.array([rho, v, p])
            U_all[e, :, i] = primitive_to_conserved(W)

    # Initial total entropy via quadrature
    S_initial = 0.0
    for e in range(n_elements):
        for i in range(solver.n_nodes):
            S_initial += (solver.weights[i]
                          * mathematical_entropy(U_all[e, :, i])
                          * (mesh.dx / 2.0))

    print(f"  Entropy: S_initial = {S_initial:.15e}")

    # Entropy-conservative flux for both volume and surface (no dissipation)
    def rhs(U):
        return compute_rhs_flux_differencing(U, solver, mesh,
                                             chandrashekar_flux,
                                             chandrashekar_flux)

    # Time integration
    t = 0.0
    step = 0
    while t < t_final - 1e-14:
        dt = compute_max_dt(U_all, solver, mesh, cfl)
        if t + dt > t_final:
            dt = t_final - t
        U_all = ssp_rk3_step(U_all, dt, rhs)
        t += dt
        step += 1

    print(f"  Entropy: completed at t={t:.6f}, steps={step}")

    # Final total entropy
    S_final = 0.0
    for e in range(n_elements):
        for i in range(solver.n_nodes):
            S_final += (solver.weights[i]
                        * mathematical_entropy(U_all[e, :, i])
                        * (mesh.dx / 2.0))

    S_change = S_final - S_initial
    print(f"  Entropy: S_final = {S_final:.15e}")
    print(f"  Entropy: S_change = {S_change:.15e}")

    result = {
        "S_initial": S_initial,
        "S_final": S_final,
        "S_change": S_change
    }
    with open("/app/results/entropy.json", "w") as f:
        json.dump(result, f, indent=2)

    print("  Entropy: wrote /app/results/entropy.json")


# ======================================================================
# Matrix export for Octave SBP verification
# ======================================================================

def export_matrices(N=5):
    """Export mass and derivative matrices for degree N as CSV."""
    nodes, weights = lgl_nodes_weights(N)
    D = derivative_matrix(nodes)
    M = np.diag(weights)
    np.savetxt("/app/results/mass_matrix.csv", M, delimiter=",",
               fmt="%.15e")
    np.savetxt("/app/results/deriv_matrix.csv", D, delimiter=",",
               fmt="%.15e")
    print(f"  Exported {N+1}x{N+1} matrices to CSV")


# ======================================================================
# Main
# ======================================================================

if __name__ == "__main__":
    os.makedirs("/app/results", exist_ok=True)

    print("Running Sod shock tube...")
    run_sod()
    print()

    print("Running entropy conservation test...")
    run_entropy_conservation()
    print()

    print("Exporting N=5 matrices for SBP verification...")
    export_matrices(5)
    print()

    print("All simulations complete.")
