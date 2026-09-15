#!/usr/bin/env python3
"""
Cell-centred finite volume solver for  div(kappa * grad(T)) = S
on 2D unstructured triangular meshes with non-orthogonal correction.

Usage
-----
Single mesh:     python3 solver.py <mesh.json> <output.json>
Convergence:     python3 solver.py --study
"""


import json
import math
import os
import subprocess
import sys

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve

# ---- import problem definition from /app/ -----------------------------------
sys.path.insert(0, "/app")
from problem_spec import kappa, source, T_exact, neumann_flux, ANALYTICAL_INNER_FLUX


# ===========================================================================
# Geometry helpers
# ===========================================================================

def compute_geometry(nodes, cells, faces, face_cells):
    """Return centroids, areas, face_mids, face_normals, face_lens."""
    nc = len(cells)
    nf = len(faces)

    centroids = np.zeros((nc, 2))
    areas = np.zeros(nc)
    for ci in range(nc):
        v = nodes[cells[ci]]
        centroids[ci] = v.mean(axis=0)
        d1 = v[1] - v[0]
        d2 = v[2] - v[0]
        areas[ci] = 0.5 * abs(d1[0] * d2[1] - d1[1] * d2[0])

    face_mids = np.zeros((nf, 2))
    face_normals = np.zeros((nf, 2))
    face_lens = np.zeros(nf)

    for fi in range(nf):
        p1 = nodes[faces[fi][0]]
        p2 = nodes[faces[fi][1]]
        face_mids[fi] = 0.5 * (p1 + p2)
        edge = p2 - p1
        L = math.sqrt(edge[0] ** 2 + edge[1] ** 2)
        face_lens[fi] = L
        # rotate edge 90 deg CCW to get a candidate normal
        n = np.array([-edge[1], edge[0]])
        # ensure it points outward from the owner cell
        owner = face_cells[fi][0]
        vec = face_mids[fi] - centroids[owner]
        if n[0] * vec[0] + n[1] * vec[1] < 0:
            n = -n
        face_normals[fi] = n  # magnitude == face length

    return centroids, areas, face_mids, face_normals, face_lens


# ===========================================================================
# Green-Gauss gradient
# ===========================================================================

def least_squares_gradient(T, faces, face_cells, centroids, face_mids,
                           inner_set, outer_set):
    """Least-squares gradient reconstruction (second-order on arbitrary meshes).

    For each cell P, minimise  sum_N w * |grad_P . (x_N - x_P) - (T_N - T_P)|^2
    which yields a 2x2 system per cell.
    """
    nc = len(centroids)
    # accumulate A = [[a11,a12],[a12,a22]] and rhs = [r1,r2] per cell
    a11 = np.zeros(nc)
    a12 = np.zeros(nc)
    a22 = np.zeros(nc)
    r1 = np.zeros(nc)
    r2 = np.zeros(nc)

    nf = len(faces)
    for fi in range(nf):
        ow = face_cells[fi][0]
        nb = face_cells[fi][1]
        if nb >= 0:
            # internal face: use neighbour centroid
            dx = centroids[nb, 0] - centroids[ow, 0]
            dy = centroids[nb, 1] - centroids[ow, 1]
            dT = T[nb] - T[ow]
            # owner cell
            a11[ow] += dx * dx;  a12[ow] += dx * dy;  a22[ow] += dy * dy
            r1[ow] += dx * dT;   r2[ow] += dy * dT
            # neighbour cell (reverse direction)
            a11[nb] += dx * dx;  a12[nb] += dx * dy;  a22[nb] += dy * dy
            r1[nb] += (-dx) * (-dT);  r2[nb] += (-dy) * (-dT)
        elif fi in inner_set:
            xf, yf = face_mids[fi]
            T_bc = T_exact(xf, yf)
            dx = xf - centroids[ow, 0]
            dy = yf - centroids[ow, 1]
            dT = T_bc - T[ow]
            a11[ow] += dx * dx;  a12[ow] += dx * dy;  a22[ow] += dy * dy
            r1[ow] += dx * dT;   r2[ow] += dy * dT
        else:  # outer (Neumann) – use face midpoint with extrapolated T
            xf, yf = face_mids[fi]
            dx = xf - centroids[ow, 0]
            dy = yf - centroids[ow, 1]
            # approximate dT using current gradient (iterative)
            # on first call grads are zero → skip this face (avoids singular system)
            # these faces still contribute geometry through internal neighbours

    # solve 2x2 systems
    grads = np.zeros((nc, 2))
    for ci in range(nc):
        det = a11[ci] * a22[ci] - a12[ci] * a12[ci]
        if abs(det) < 1e-30:
            continue
        grads[ci, 0] = (a22[ci] * r1[ci] - a12[ci] * r2[ci]) / det
        grads[ci, 1] = (a11[ci] * r2[ci] - a12[ci] * r1[ci]) / det
    return grads


# ===========================================================================
# Main solver
# ===========================================================================

def solve_mesh(mesh, max_noc_iters=40, noc_tol=1e-12):
    """Solve the diffusion equation on *mesh*.  Returns (T, centroids, areas)."""
    nodes_raw = mesh["nodes"]
    cells_raw = mesh["cells"]
    faces_raw = mesh["faces"]
    fc_raw = mesh["face_cells"]

    nodes = np.array(nodes_raw)
    cells = [np.array(c, dtype=int) for c in cells_raw]
    faces = [np.array(f, dtype=int) for f in faces_raw]
    face_cells = [list(fc) for fc in fc_raw]

    inner_set = set(mesh["inner_boundary_faces"])
    outer_set = set(mesh["outer_boundary_faces"])

    nc = len(cells)
    nf = len(faces)

    centroids, areas, face_mids, face_normals, face_lens = \
        compute_geometry(nodes, cells, faces, face_cells)

    # initial guess: exact solution
    T = np.array([T_exact(centroids[ci, 0], centroids[ci, 1])
                  for ci in range(nc)])

    for noc_iter in range(max_noc_iters):
        # 1. gradients (least-squares reconstruction)
        grads = least_squares_gradient(
            T, faces, face_cells,
            centroids, face_mids,
            inner_set, outer_set,
        )

        # 2. assemble linear system  A T = b   (positive-diagonal convention)
        #    original eqn:  sum_f Phi_f = S_P V_P
        #    multiply by -1 for positive diagonal
        rows, cols, vals = [], [], []
        b = np.zeros(nc)

        # source  (after sign flip:  b_P = -S_P V_P)
        for ci in range(nc):
            b[ci] = -source(centroids[ci, 0], centroids[ci, 1]) * areas[ci]

        # --- internal faces ---
        for fi in range(nf):
            ow = face_cells[fi][0]
            nb = face_cells[fi][1]
            if nb < 0:
                continue

            Sf = face_normals[fi]
            Sf2 = Sf[0] ** 2 + Sf[1] ** 2
            xf, yf = face_mids[fi]
            kf = kappa(xf, yf)

            d = centroids[nb] - centroids[ow]
            Sd = Sf[0] * d[0] + Sf[1] * d[1]
            if abs(Sd) < 1e-30:
                continue

            coeff = kf * Sf2 / Sd   # over-relaxed diffusion coeff

            # non-orthogonal correction vector  k = S - |S|^2/(S.d) * d
            k0 = Sf[0] - (Sf2 / Sd) * d[0]
            k1 = Sf[1] - (Sf2 / Sd) * d[1]
            grad_f0 = 0.5 * (grads[ow, 0] + grads[nb, 0])
            grad_f1 = 0.5 * (grads[ow, 1] + grads[nb, 1])
            noc = kf * (k0 * grad_f0 + k1 * grad_f1)

            # owner row
            rows.append(ow); cols.append(ow); vals.append(coeff)
            rows.append(ow); cols.append(nb);  vals.append(-coeff)
            # neighbour row
            rows.append(nb); cols.append(nb); vals.append(coeff)
            rows.append(nb); cols.append(ow); vals.append(-coeff)

            # RHS correction  (sign-flipped eqn: b_ow += noc, b_nb -= noc)
            b[ow] += noc
            b[nb] -= noc

        # --- Dirichlet faces (inner boundary) ---
        for fi in inner_set:
            ow = face_cells[fi][0]
            Sf = face_normals[fi]
            Sf2 = Sf[0] ** 2 + Sf[1] ** 2
            xf, yf = face_mids[fi]
            kf = kappa(xf, yf)
            T_bc = T_exact(xf, yf)

            d_Pf = face_mids[fi] - centroids[ow]
            Sd = Sf[0] * d_Pf[0] + Sf[1] * d_Pf[1]
            if abs(Sd) < 1e-30:
                continue

            coeff = kf * Sf2 / Sd

            # non-orthogonal correction
            k0 = Sf[0] - (Sf2 / Sd) * d_Pf[0]
            k1 = Sf[1] - (Sf2 / Sd) * d_Pf[1]
            noc = kf * (k0 * grads[ow, 0] + k1 * grads[ow, 1])

            rows.append(ow); cols.append(ow); vals.append(coeff)
            b[ow] += coeff * T_bc + noc

        # --- Neumann faces (outer boundary) ---
        for fi in outer_set:
            ow = face_cells[fi][0]
            Sf = face_normals[fi]
            L = face_lens[fi]
            nx, ny = Sf[0] / L, Sf[1] / L
            xf, yf = face_mids[fi]
            q = neumann_flux(xf, yf, nx, ny)
            # sign-flipped eqn moves known Neumann flux to RHS with + sign
            b[ow] += q * L

        # 3. solve
        A = coo_matrix((vals, (rows, cols)), shape=(nc, nc)).tocsr()
        T_new = spsolve(A, b)

        # convergence check
        if noc_iter > 0:
            change = np.max(np.abs(T_new - T))
            if change < noc_tol:
                T = T_new
                break
        T = T_new

    # recompute final gradients for flux evaluation
    grads = least_squares_gradient(
        T, faces, face_cells,
        centroids, face_mids,
        inner_set, outer_set,
    )

    return T, centroids, areas, grads, face_mids, face_normals, face_cells, inner_set


# ===========================================================================
# Post-processing
# ===========================================================================

def compute_metrics(T, centroids, areas, grads, face_mids, face_normals,
                    face_cells, inner_set):
    """Return L2 error and inner-boundary flux."""
    nc = len(T)
    T_ex = np.array([T_exact(centroids[ci, 0], centroids[ci, 1])
                     for ci in range(nc)])
    total_area = areas.sum()
    l2_err = math.sqrt(np.sum((T - T_ex) ** 2 * areas) / total_area)

    # inner boundary flux
    inner_flux = 0.0
    for fi in inner_set:
        ow = face_cells[fi][0]
        Sf = face_normals[fi]
        Sf2 = Sf[0] ** 2 + Sf[1] ** 2
        xf, yf = face_mids[fi]
        kf = kappa(xf, yf)
        T_bc = T_exact(xf, yf)
        d_Pf = face_mids[fi] - centroids[ow]
        Sd = Sf[0] * d_Pf[0] + Sf[1] * d_Pf[1]
        if abs(Sd) < 1e-30:
            continue
        coeff = kf * Sf2 / Sd
        k0 = Sf[0] - (Sf2 / Sd) * d_Pf[0]
        k1 = Sf[1] - (Sf2 / Sd) * d_Pf[1]
        noc = kf * (k0 * grads[ow, 0] + k1 * grads[ow, 1])
        flux = coeff * (T_bc - T[ow]) + noc
        inner_flux += flux

    return l2_err, inner_flux


# ===========================================================================
# Entry points
# ===========================================================================

def solve_single(mesh_file, output_file):
    with open(mesh_file) as f:
        mesh = json.load(f)
    T, centroids, areas, grads, fmids, fnorms, fcells, inner_set = solve_mesh(mesh)
    l2, flux = compute_metrics(T, centroids, areas, grads, fmids, fnorms,
                               fcells, inner_set)
    result = {
        "cell_temperatures": T.tolist(),
        "l2_error": float(l2),
        "inner_boundary_flux": float(flux),
    }
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"L2 error: {l2:.6e}   inner flux: {flux:.6f}  "
          f"(analytical: {ANALYTICAL_INNER_FLUX:.6f})")


def run_convergence_study():
    domain_area = math.pi * (2.0 ** 2 - 0.5 ** 2)  # pi*(R^2 - r^2)
    l2_errors = []
    mesh_sizes = []

    for level in (1, 2, 3):
        # generate mesh
        subprocess.run(
            ["python3", "/app/mesh_generator.py", str(level)],
            cwd="/app", check=True,
        )
        mesh_file = f"/app/mesh_level_{level}.json"
        out_file = f"/app/solve_level_{level}.json"

        with open(mesh_file) as f:
            mesh = json.load(f)

        T, centroids, areas, grads, fmids, fnorms, fcells, iset = solve_mesh(mesh)
        l2, flux = compute_metrics(T, centroids, areas, grads, fmids, fnorms,
                                   fcells, iset)

        nc = len(mesh["cells"])
        h = math.sqrt(domain_area / nc)
        l2_errors.append(l2)
        mesh_sizes.append(h)

        # write individual result
        res = {
            "cell_temperatures": T.tolist(),
            "l2_error": float(l2),
            "inner_boundary_flux": float(flux),
        }
        with open(out_file, "w") as f:
            json.dump(res, f)

        print(f"Level {level}: h={h:.4f}  L2={l2:.6e}  flux={flux:.6f}")

    # convergence order from two finest levels
    p = math.log(l2_errors[1] / l2_errors[2]) / math.log(mesh_sizes[1] / mesh_sizes[2])

    results = {
        "l2_errors": l2_errors,
        "mesh_sizes": mesh_sizes,
        "convergence_order": float(p),
        "inner_boundary_flux_finest": float(flux),
    }
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nConvergence order (levels 2->3): {p:.3f}")
    print(f"Inner flux finest: {flux:.6f}  (analytical: {ANALYTICAL_INNER_FLUX:.6f})")
    print("Wrote /app/results.json")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--study":
        run_convergence_study()
    elif len(sys.argv) == 3:
        solve_single(sys.argv[1], sys.argv[2])
    else:
        print("Usage:")
        print("  python3 solver.py <mesh.json> <output.json>")
        print("  python3 solver.py --study")
        sys.exit(1)
