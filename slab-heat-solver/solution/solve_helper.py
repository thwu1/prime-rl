"""
Reference solution for 2D steady-state ground-coupled slab heat transfer
with heterogeneous (layered) soil and embedded perimeter insulation.

Solves div(k(x,z) * grad(theta)) = 0 using a cell-face harmonic-mean
finite-difference scheme on a uniform grid. Richardson extrapolation
between two resolutions yields high-accuracy results. For each case,
computes the total heat loss Q, average flux density, and the linear
thermal transmittance (psi-value).

"""
import json
import sys

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve


# ---------------------------------------------------------------------------
# Material property helpers
# ---------------------------------------------------------------------------

def build_k_field(x_coords, z_coords, soil_layers, insulation=None):
    """Build 2D conductivity field k(x,z) from layer and insulation specs."""
    Nz = len(z_coords)
    Nx = len(x_coords)
    k = np.empty((Nz, Nx), dtype=np.float64)

    for j in range(Nz):
        z = z_coords[j]
        k_val = soil_layers[-1]["conductivity"]
        for layer in soil_layers:
            if z <= layer["depth_to"] + 1e-10:
                k_val = layer["conductivity"]
                break
        k[j, :] = k_val

    if insulation is not None:
        ins = insulation
        for j in range(Nz):
            z = z_coords[j]
            if ins["z_start"] - 1e-10 <= z <= ins["z_end"] + 1e-10:
                for i in range(Nx):
                    x = x_coords[i]
                    if ins["x_start"] - 1e-10 <= x <= ins["x_end"] + 1e-10:
                        k[j, i] = ins["conductivity"]

    return k


def harmonic_mean(k1, k2):
    """Harmonic mean of two conductivities (correct for cell-face averaging)."""
    s = k1 + k2
    if s < 1e-30:
        return 0.0
    return 2.0 * k1 * k2 / s


def compute_U_1d(soil_layers, D):
    """1D thermal transmittance through soil column (series resistance)."""
    R = 0.0
    prev_depth = 0.0
    for layer in soil_layers:
        d = min(layer["depth_to"], D) - prev_depth
        if d > 0:
            R += d / layer["conductivity"]
        prev_depth = layer["depth_to"]
        if prev_depth >= D:
            break
    return 1.0 / R if R > 0 else float("inf")


# ---------------------------------------------------------------------------
# Variable-coefficient finite-difference solver
# ---------------------------------------------------------------------------

def solve_fd(B, w, W, D, soil_layers, insulation, delta_T, target_dx):
    """
    Solve div(k * grad(theta)) = 0 on [0,W] x [0,D].

    BCs: top piecewise-linear Dirichlet, bottom/right Dirichlet (theta=0),
    left Neumann (symmetry). Uses harmonic-mean face conductivities.

    Returns total heat loss Q in W/m (full slab, both halves by symmetry).
    """
    Nx = int(round(W / target_dx)) + 1
    Nz = int(round(D / target_dx)) + 1
    dx = W / (Nx - 1)
    dz = D / (Nz - 1)
    N = Nx * Nz

    x_coords = np.linspace(0, W, Nx)
    z_coords = np.linspace(0, D, Nz)
    k_field = build_k_field(x_coords, z_coords, soil_layers, insulation)

    rx = 1.0 / (dx * dx)
    rz = 1.0 / (dz * dz)
    Bpw = B + w

    rows = []
    cols = []
    vals = []
    b = np.zeros(N, dtype=np.float64)

    for j in range(Nz):
        for i in range(Nx):
            n = j * Nx + i
            x = x_coords[i]

            if j == 0:
                rows.append(n)
                cols.append(n)
                vals.append(1.0)
                if x <= B + 1e-10:
                    b[n] = 1.0
                elif x <= Bpw + 1e-10:
                    b[n] = max(0.0, (Bpw - x) / w)
            elif j == Nz - 1 or i == Nx - 1:
                rows.append(n)
                cols.append(n)
                vals.append(1.0)
            elif i == 0:
                k_e = harmonic_mean(k_field[j, 0], k_field[j, 1])
                k_s = harmonic_mean(k_field[j, 0], k_field[j + 1, 0])
                k_n = harmonic_mean(k_field[j - 1, 0], k_field[j, 0])
                diag = -(2.0 * k_e * rx + k_s * rz + k_n * rz)
                rows.extend([n, n, n, n])
                cols.extend([n, n + 1, n - Nx, n + Nx])
                vals.extend([diag, 2.0 * k_e * rx, k_n * rz, k_s * rz])
            else:
                k_e = harmonic_mean(k_field[j, i], k_field[j, i + 1])
                k_w = harmonic_mean(k_field[j, i - 1], k_field[j, i])
                k_s = harmonic_mean(k_field[j, i], k_field[j + 1, i])
                k_n = harmonic_mean(k_field[j - 1, i], k_field[j, i])
                diag = -(k_e * rx + k_w * rx + k_s * rz + k_n * rz)
                rows.extend([n, n, n, n, n])
                cols.extend([n, n + 1, n - 1, n + Nx, n - Nx])
                vals.extend([diag, k_e * rx, k_w * rx, k_s * rz, k_n * rz])

    A = coo_matrix(
        (np.array(vals, dtype=np.float64),
         (np.array(rows, dtype=np.int64), np.array(cols, dtype=np.int64))),
        shape=(N, N),
    ).tocsr()

    theta = spsolve(A, b).reshape((Nz, Nx))

    i_max = min(int(round(Bpw / dx)), Nx - 1)
    Q_half = 0.0
    for i in range(i_max + 1):
        if Nz >= 3:
            dt_dz = (
                -3.0 * theta[0, i] + 4.0 * theta[1, i] - theta[2, i]
            ) / (2.0 * dz)
        else:
            dt_dz = (theta[1, i] - theta[0, i]) / dz
        flux = -k_field[0, i] * delta_T * dt_dz
        wgt = dx / 2.0 if (i == 0 or i == i_max) else dx
        Q_half += flux * wgt

    return 2.0 * Q_half


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open("/app/cases.json") as f:
        CASES = json.load(f)

    print("Loaded /app/cases.json", flush=True)

    results = {}

    for name, cfg in CASES.items():
        B = cfg["slab_half_width"]
        w = cfg["wall_thickness"]
        W = cfg["domain_width"]
        D = cfg["domain_depth"]
        soil_layers = cfg["soil_layers"]
        insulation = cfg.get("insulation", None)
        dT = cfg["T_indoor"] - cfg["T_outdoor"]

        print(f"Solving {name} (B={B}, W={W}, D={D})...", flush=True)

        dx_c = 0.20
        dx_f = 0.10

        Q_c = solve_fd(B, w, W, D, soil_layers, insulation, dT, dx_c)
        Q_f = solve_fd(B, w, W, D, soil_layers, insulation, dT, dx_f)

        # Richardson extrapolation: O(h^2) => extrapolated = (4*Q_f - Q_c) / 3
        Q = (4.0 * Q_f - Q_c) / 3.0

        U_1d = compute_U_1d(soil_layers, D)
        psi_value = Q / dT - U_1d * 2.0 * B
        q_avg = Q / (2.0 * B)

        results[name] = {
            "heat_loss_per_meter": round(Q, 6),
            "flux_density_avg": round(q_avg, 6),
            "psi_value": round(psi_value, 6),
        }

        print(
            f"  Q_c={Q_c:.4f}  Q_f={Q_f:.4f}  Q={Q:.4f}  "
            f"q_avg={q_avg:.4f}  psi={psi_value:.4f}",
            flush=True,
        )

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json", flush=True)


if __name__ == "__main__":
    main()
