#!/usr/bin/env python3
"""Orchestrator for two-phase Poiseuille flow pipeline solution.


Uses gmsh for mesh generation, GNU Octave for the numerical FVM solver,
and Python for the analytical solution and results assembly.
"""

import json
import math
import os
import subprocess
import sys

sys.path.insert(0, "/app")
from config import (
    H, G, MU1,
    VISCOSITY_RATIOS, SATURATIONS,
    CONV_MESH_SIZES, CONV_SW, CONV_MU_RATIO,
)


# ============================================================================
# Analytical solution (pure Python)
# ============================================================================

def analytical_constants(Sw, mu_ratio):
    """Integration constants for two-phase velocity profile."""
    mu1 = MU1
    mu2 = MU1 * mu_ratio
    h1 = Sw * H
    h2 = H - h1
    C1 = G * (mu2 * h1**2 + mu1 * h2 * (2 * h1 + h2)) / (
        2 * mu1 * (mu2 * h1 + mu1 * h2)
    )
    C3 = (mu1 / mu2) * C1
    C4 = (G / (2 * mu2)) * H**2 - C3 * H
    return C1, C3, C4


def analytical_velocity(y, Sw, mu_ratio):
    """Analytical velocity at position y."""
    mu1 = MU1
    mu2 = MU1 * mu_ratio
    h1 = Sw * H
    C1, C3, C4 = analytical_constants(Sw, mu_ratio)
    if y <= h1:
        return -(G / (2 * mu1)) * y**2 + C1 * y
    else:
        return -(G / (2 * mu2)) * y**2 + C3 * y + C4


def analytical_flow_rates(Sw, mu_ratio):
    """Analytical volumetric flow rates Q1, Q2."""
    mu1 = MU1
    mu2 = MU1 * mu_ratio
    h1 = Sw * H
    C1, C3, C4 = analytical_constants(Sw, mu_ratio)
    Q1 = -(G / (6 * mu1)) * h1**3 + C1 * h1**2 / 2
    Q2 = (-(G / (6 * mu2)) * (H**3 - h1**3)
          + C3 * (H**2 - h1**2) / 2
          + C4 * (H - h1))
    return Q1, Q2


def analytical_kr(Sw, mu_ratio):
    """Analytical relative permeabilities (kr1, kr2)."""
    mu1 = MU1
    mu2 = MU1 * mu_ratio
    Q1, Q2 = analytical_flow_rates(Sw, mu_ratio)
    kr1 = 12 * Q1 * mu1 / (H**3 * G)
    kr2 = 12 * Q2 * mu2 / (H**3 * G)
    return kr1, kr2


# ============================================================================
# Mesh generation via gmsh
# ============================================================================

def generate_mesh_and_extract_nodes(N):
    """Generate 1D mesh with gmsh, parse MSH 2.2, return sorted node coords."""
    geo_content = (
        f"Mesh.MshFileVersion = 2.2;\n"
        f"Point(1) = {{0, 0, 0}};\n"
        f"Point(2) = {{{H}, 0, 0}};\n"
        f"Line(1) = {{1, 2}};\n"
        f"Transfinite Curve {{1}} = {N + 1} Using Progression 1.0;\n"
    )
    geo_path = f"/tmp/mesh_{N}.geo"
    msh_path = f"/tmp/mesh_{N}.msh"

    with open(geo_path, 'w') as f:
        f.write(geo_content)

    result = subprocess.run(
        ['gmsh', '-1', geo_path, '-o', msh_path, '-format', 'msh2'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"gmsh error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Extract nodes using the pipeline's reader
    result = subprocess.run(
        ['python3', '/app/pipeline/read_mesh.py', msh_path],
        capture_output=True, text=True, check=True
    )
    nodes = [float(x) for x in result.stdout.strip().split('\n')]
    return sorted(nodes)


def write_nodes_file(nodes, path):
    """Write node coordinates to a text file for Octave."""
    with open(path, 'w') as f:
        for c in nodes:
            f.write(f"{c:.15e}\n")


# ============================================================================
# Numerical solver via Octave
# ============================================================================

def run_two_phase_solver(N, Sw, mu_ratio):
    """Run the Octave two-phase solver, return (y_centers, u_values)."""
    nodes_path = f"/tmp/nodes_{N}.txt"
    output_path = f"/tmp/vel_{N}_{Sw}_{mu_ratio}.dat"

    # Generate mesh
    nodes = generate_mesh_and_extract_nodes(N)
    write_nodes_file(nodes, nodes_path)

    # Run Octave solver
    result = subprocess.run(
        ['octave', '--no-gui', '--silent',
         '/solution/two_phase_solver.m',
         nodes_path, str(Sw), str(mu_ratio), str(G), str(H), output_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Octave error (N={N}): {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Read velocity output
    y_vals, u_vals = [], []
    with open(output_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                y_vals.append(float(parts[0]))
                u_vals.append(float(parts[1]))
    return y_vals, u_vals


# ============================================================================
# Flow rate computation from numerical velocity
# ============================================================================

def compute_numerical_flow_rates(y_vals, u_vals, Sw):
    """Split velocity profile at interface and integrate for Q1, Q2."""
    h1 = Sw * H
    dy = y_vals[1] - y_vals[0]
    Q1, Q2 = 0.0, 0.0

    for i in range(len(y_vals)):
        y_lo = y_vals[i] - dy / 2
        y_hi = y_vals[i] + dy / 2
        if y_hi <= h1 + 1e-15:
            Q1 += u_vals[i] * dy
        elif y_lo >= h1 - 1e-15:
            Q2 += u_vals[i] * dy
        else:
            frac1 = (h1 - y_lo) / dy
            Q1 += u_vals[i] * frac1 * dy
            Q2 += u_vals[i] * (1.0 - frac1) * dy
    return Q1, Q2


# ============================================================================
# Main
# ============================================================================

def main():
    results = {}

    # --- 1. Analytical relative permeability curves ---
    print("Computing analytical kr curves...")
    analytical_kr_data = {}
    for mu_ratio in VISCOSITY_RATIOS:
        key = f"mu_ratio_{mu_ratio}"
        kr1_list, kr2_list = [], []
        for Sw in SATURATIONS:
            kr1, kr2 = analytical_kr(Sw, mu_ratio)
            kr1_list.append(float(kr1))
            kr2_list.append(float(kr2))
        analytical_kr_data[key] = {
            "Sw": list(SATURATIONS),
            "kr1": kr1_list,
            "kr2": kr2_list,
        }
    results["analytical_kr"] = analytical_kr_data

    # --- 2. Mesh convergence study (gmsh + Octave) ---
    print("Running mesh convergence study...")
    l2_errors = []
    for N in CONV_MESH_SIZES:
        print(f"  N={N}...")
        y_num, u_num = run_two_phase_solver(N, CONV_SW, CONV_MU_RATIO)
        err_sq_sum = 0.0
        for i in range(len(y_num)):
            u_exact = analytical_velocity(y_num[i], CONV_SW, CONV_MU_RATIO)
            err_sq_sum += (u_num[i] - u_exact) ** 2
        l2 = math.sqrt(err_sq_sum / len(y_num))
        l2_errors.append(l2)

    # Convergence order from least-squares log-log fit
    log_h = [math.log(H / N) for N in CONV_MESH_SIZES]
    log_e = [math.log(e) for e in l2_errors]
    n_pts = len(log_h)
    sum_x = sum(log_h)
    sum_y = sum(log_e)
    sum_xx = sum(x * x for x in log_h)
    sum_xy = sum(x * y for x, y in zip(log_h, log_e))
    convergence_order = (n_pts * sum_xy - sum_x * sum_y) / (n_pts * sum_xx - sum_x ** 2)

    results["convergence"] = {
        "mesh_sizes": list(CONV_MESH_SIZES),
        "l2_errors": l2_errors,
        "convergence_order": convergence_order,
    }

    # --- 3. Validation at finest mesh ---
    print("Computing validation data...")
    N_finest = CONV_MESH_SIZES[-1]
    y_fine, u_fine = run_two_phase_solver(N_finest, CONV_SW, CONV_MU_RATIO)

    max_err = max(
        abs(u_fine[i] - analytical_velocity(y_fine[i], CONV_SW, CONV_MU_RATIO))
        for i in range(len(y_fine))
    )

    Q1_num, Q2_num = compute_numerical_flow_rates(y_fine, u_fine, CONV_SW)
    mu2 = MU1 * CONV_MU_RATIO
    kr1_num = 12 * Q1_num * MU1 / (H**3 * G)
    kr2_num = 12 * Q2_num * mu2 / (H**3 * G)
    kr1_ana, kr2_ana = analytical_kr(CONV_SW, CONV_MU_RATIO)

    results["validation"] = {
        "finest_mesh_max_error": max_err,
        "kr1_numerical": kr1_num,
        "kr2_numerical": kr2_num,
        "kr1_analytical": float(kr1_ana),
        "kr2_analytical": float(kr2_ana),
    }

    # --- Write output ---
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
