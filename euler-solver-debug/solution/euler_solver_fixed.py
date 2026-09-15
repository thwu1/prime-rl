#!/usr/bin/env python3
"""
1D Euler Equation Solver using Kurganov-Tadmor Central Scheme (FIXED)

All three bugs from the original version have been corrected:
  1. Energy formula: p/(gamma-1) not p/gamma
  2. KT flux diffusion: minus sign not plus
  3. CFL condition: |u|+a not |u|

Uses SSP-RK2 (Heun's method) for second-order time integration.
"""

import numpy as np
import json
import sys


def load_config(config_path):
    with open(config_path, 'r') as f:
        return json.load(f)


def parse_msh(msh_path):
    """Parse gmsh .msh v2.2 file to extract 1D node coordinates."""
    nodes = {}
    elements = []
    with open(msh_path) as f:
        line = f.readline()
        while line:
            if line.strip() == '$Nodes':
                n = int(f.readline().strip())
                for _ in range(n):
                    parts = f.readline().split()
                    nid = int(parts[0])
                    x = float(parts[1])
                    nodes[nid] = x
            elif line.strip() == '$Elements':
                n = int(f.readline().strip())
                for _ in range(n):
                    parts = f.readline().split()
                    etype = int(parts[1])
                    if etype == 1:  # 2-node line element
                        ntags = int(parts[2])
                        n1 = int(parts[3 + ntags])
                        n2 = int(parts[4 + ntags])
                        elements.append((n1, n2))
            line = f.readline()

    node_ids = set()
    for n1, n2 in elements:
        node_ids.add(n1)
        node_ids.add(n2)

    coords = sorted([nodes[nid] for nid in node_ids])
    centers = [(coords[i] + coords[i + 1]) / 2.0 for i in range(len(coords) - 1)]
    return np.array(centers), np.array(coords)


def primitive_to_conservative(rho, u, p, gamma):
    rho_u = rho * u
    # FIX 1: correct energy formula
    E = p / (gamma - 1.0) + 0.5 * rho * u**2
    return np.array([rho, rho_u, E])


def conservative_to_primitive(U, gamma):
    rho = U[0]
    u = U[1] / rho
    p = (gamma - 1.0) * (U[2] - 0.5 * rho * u**2)
    return rho, u, p


def euler_flux(U, gamma):
    rho, u, p = conservative_to_primitive(U, gamma)
    E = U[2]
    return np.array([rho * u, rho * u**2 + p, u * (E + p)])


def max_wave_speed(U, gamma):
    rho, u, p = conservative_to_primitive(U, gamma)
    if rho <= 0 or p <= 0:
        return abs(u) + 1.0
    a = np.sqrt(gamma * p / rho)
    return abs(u) + a


def minmod(a, b):
    result = np.zeros_like(a)
    mask = (a * b > 0)
    result[mask] = np.where(np.abs(a[mask]) < np.abs(b[mask]), a[mask], b[mask])
    return result


def reconstruct(U_cells, dx):
    ncells = U_cells.shape[1]
    nvars = U_cells.shape[0]
    slopes = np.zeros_like(U_cells)
    for i in range(1, ncells - 1):
        dU_left = (U_cells[:, i] - U_cells[:, i - 1]) / dx
        dU_right = (U_cells[:, i + 1] - U_cells[:, i]) / dx
        slopes[:, i] = minmod(dU_left, dU_right)

    U_L = np.zeros((nvars, ncells - 1))
    U_R = np.zeros((nvars, ncells - 1))
    for i in range(ncells - 1):
        U_L[:, i] = U_cells[:, i] + 0.5 * dx * slopes[:, i]
        U_R[:, i] = U_cells[:, i + 1] - 0.5 * dx * slopes[:, i + 1]
    return U_L, U_R


def kt_numerical_flux(U_L, U_R, gamma):
    F_L = euler_flux(U_L, gamma)
    F_R = euler_flux(U_R, gamma)
    a_L = max_wave_speed(U_L, gamma)
    a_R = max_wave_speed(U_R, gamma)
    a_max = max(a_L, a_R)
    # FIX 2: correct diffusion sign (minus, not plus)
    flux = 0.5 * (F_L + F_R) - 0.5 * a_max * (U_R - U_L)
    return flux


def compute_timestep(U_cells, dx, gamma, cfl):
    ncells = U_cells.shape[1]
    max_speed = 0.0
    for i in range(ncells):
        rho = U_cells[0, i]
        u = U_cells[1, i] / rho if rho > 0 else 0.0
        p = (gamma - 1.0) * (U_cells[2, i] - 0.5 * rho * u**2) if rho > 0 else 1.0
        a = np.sqrt(gamma * max(p, 1e-10) / max(rho, 1e-10))
        # FIX 3: correct wave speed (|u| + a, not just |u|)
        speed = abs(u) + a
        max_speed = max(max_speed, speed)
    if max_speed < 1e-10:
        max_speed = 1.0
    return cfl * dx / max_speed


def compute_rhs(U, dx, gamma):
    """Compute spatial right-hand side dU/dt = L(U)."""
    N = U.shape[1]
    U_L, U_R = reconstruct(U, dx)
    n_interfaces = N - 1
    fluxes = np.zeros((3, n_interfaces))
    for j in range(n_interfaces):
        fluxes[:, j] = kt_numerical_flux(U_L[:, j], U_R[:, j], gamma)

    rhs = np.zeros_like(U)
    for i in range(1, N - 1):
        rhs[:, i] = -(1.0 / dx) * (fluxes[:, i] - fluxes[:, i - 1])
    return rhs


def apply_bc(U):
    """Apply transmissive boundary conditions."""
    U[:, 0] = U[:, 1]
    U[:, -1] = U[:, -2]


def solve(config, msh_path):
    gamma = config['gamma']
    x0 = config['domain']['x_diaphragm']
    t_end = config['t_end']
    cfl = config.get('cfl', 0.45)

    x, node_coords = parse_msh(msh_path)
    N = len(x)
    dx = (node_coords[-1] - node_coords[0]) / N

    rho_L = config['left_state']['rho']
    u_L = config['left_state']['u']
    p_L = config['left_state']['p']
    rho_R = config['right_state']['rho']
    u_R = config['right_state']['u']
    p_R = config['right_state']['p']

    U = np.zeros((3, N))
    for i in range(N):
        if x[i] < x0:
            U[:, i] = primitive_to_conservative(rho_L, u_L, p_L, gamma)
        else:
            U[:, i] = primitive_to_conservative(rho_R, u_R, p_R, gamma)

    t = 0.0
    while t < t_end - 1e-14:
        dt = compute_timestep(U, dx, gamma, cfl)
        if t + dt > t_end:
            dt = t_end - t

        # SSP-RK2 (Heun's method) for second-order time accuracy
        # Stage 1: U* = U + dt * L(U)
        rhs1 = compute_rhs(U, dx, gamma)
        U_star = U + dt * rhs1
        apply_bc(U_star)

        # Stage 2: U^{n+1} = 0.5*U + 0.5*(U* + dt*L(U*))
        rhs2 = compute_rhs(U_star, dx, gamma)
        U = 0.5 * U + 0.5 * (U_star + dt * rhs2)
        apply_bc(U)

        t += dt

    rho_out = np.zeros(N)
    u_out = np.zeros(N)
    p_out = np.zeros(N)
    for i in range(N):
        rho_out[i], u_out[i], p_out[i] = conservative_to_primitive(U[:, i], gamma)

    return x, rho_out, u_out, p_out
