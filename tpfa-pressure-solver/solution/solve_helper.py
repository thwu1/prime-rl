#!/usr/bin/env python3
"""Reference TPFA reservoir pressure solver.

Solves the steady-state single-phase pressure equation on a 2D structured
grid using the Two-Point Flux Approximation (TPFA) finite volume method.
"""

import csv
import json
import os
import sys

import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve


def load_json(path):
    with open(path) as fh:
        return json.load(fh)


def cell_id(i, j, ny):
    """Flat index for cell (i, j) in column-major order."""
    return i * ny + j


def build_system(grid, perm, wells, fluid, config):
    nx = grid["nx"]
    ny = grid["ny"]
    dx = grid["dx"]
    dy = grid["dy"]
    h = grid["thickness"]
    mu = fluid["viscosity"]
    kx = perm["kx"]
    ky = perm["ky"]

    N = nx * ny
    A = lil_matrix((N, N))
    rhs = np.zeros(N)

    # --- x-direction internal faces ---
    for i in range(nx - 1):
        for j in range(ny):
            c1 = cell_id(i, j, ny)
            c2 = cell_id(i + 1, j, ny)
            half_d1 = dx[i] / 2.0
            half_d2 = dx[i + 1] / 2.0
            face_area = dy[j] * h
            # Harmonic-mean transmissibility (series resistance)
            trans = face_area / (mu * (half_d1 / kx[i][j] + half_d2 / kx[i + 1][j]))
            A[c1, c1] -= trans
            A[c1, c2] += trans
            A[c2, c2] -= trans
            A[c2, c1] += trans

    # --- y-direction internal faces ---
    for i in range(nx):
        for j in range(ny - 1):
            c1 = cell_id(i, j, ny)
            c2 = cell_id(i, j + 1, ny)
            half_d1 = dy[j] / 2.0
            half_d2 = dy[j + 1] / 2.0
            face_area = dx[i] * h
            trans = face_area / (mu * (half_d1 / ky[i][j] + half_d2 / ky[i][j + 1]))
            A[c1, c1] -= trans
            A[c1, c2] += trans
            A[c2, c2] -= trans
            A[c2, c1] += trans

    # --- well source terms ---
    # Conservation equation per cell: sum T*(p_nb - p_cell) = -Q_well
    for w in wells["wells"]:
        c = cell_id(w["i"], w["j"], ny)
        rhs[c] -= w["value"]

    # --- reference pressure constraint ---
    ref = config["reference_pressure"]
    rc = cell_id(ref["i"], ref["j"], ny)
    A[rc, :] = 0
    A[rc, rc] = 1.0
    rhs[rc] = ref["value"]

    return A.tocsr(), rhs, nx, ny


def solve_and_write(input_dir, output_dir):
    grid = load_json(os.path.join(input_dir, "grid.json"))
    perm = load_json(os.path.join(input_dir, "permeability.json"))
    wells = load_json(os.path.join(input_dir, "wells.json"))
    fluid = load_json(os.path.join(input_dir, "fluid.json"))
    config = load_json(os.path.join(input_dir, "config.json"))

    A, rhs, nx, ny = build_system(grid, perm, wells, fluid, config)
    pressure = spsolve(A, rhs)

    # ---- write pressure.csv ----
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, "pressure.csv")
    with open(csv_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["i", "j", "pressure"])
        for i in range(nx):
            for j in range(ny):
                writer.writerow([i, j, f"{pressure[cell_id(i, j, ny)]:.10g}"])

    # ---- write diagnostics.json ----
    total_rate = sum(w["value"] for w in wells["wells"])
    diag = {
        "mass_balance_error": abs(total_rate),
        "well_rates": {w["name"]: w["value"] for w in wells["wells"]},
        "max_pressure": float(np.max(pressure)),
        "min_pressure": float(np.min(pressure)),
    }
    with open(os.path.join(output_dir, "diagnostics.json"), "w") as fh:
        json.dump(diag, indent=2, fp=fh)


if __name__ == "__main__":
    in_dir = sys.argv[1] if len(sys.argv) > 1 else "/app/input"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "/app/output"
    solve_and_write(in_dir, out_dir)
