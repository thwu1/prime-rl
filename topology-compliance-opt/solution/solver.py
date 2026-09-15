#!/usr/bin/env python3
"""SIMP topology optimization for 2D cantilever beam compliance minimization.

Implements:
  - Q4 bilinear element stiffness via 2x2 Gauss quadrature (plane stress)
  - Sparse global assembly (COO -> CSC)
  - Dirichlet BCs by DOF elimination
  - Density filter (distance-weighted spatial convolution)
  - Adjoint-based compliance sensitivity
  - Optimality Criteria (OC) update with bisection on filtered volume
"""

import csv
import json
import os

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve


# -----------------------------------------------------------------------
# Element stiffness
# -----------------------------------------------------------------------

def compute_ke(nu):
    """8x8 element stiffness for unit-square Q4 plane-stress element.

    Node order: BL(0,0)  BR(1,0)  TR(1,1)  TL(0,1).
    DOFs per node: (ux, uy).
    Young's modulus factored out (E = 1); caller scales by material Ee.
    """
    factor = 1.0 / (1.0 - nu ** 2)
    D = factor * np.array([
        [1.0, nu, 0.0],
        [nu, 1.0, 0.0],
        [0.0, 0.0, (1.0 - nu) / 2.0],
    ])
    KE = np.zeros((8, 8))
    gp = 1.0 / np.sqrt(3.0)
    coords = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float)
    for xi in (-gp, gp):
        for eta in (-gp, gp):
            dNdxi = np.array([
                [-(1 - eta), (1 - eta), (1 + eta), -(1 + eta)],
                [-(1 - xi), -(1 + xi), (1 + xi), (1 - xi)],
            ]) / 4.0
            J = dNdxi @ coords
            detJ = np.linalg.det(J)
            dNdx = np.linalg.solve(J, dNdxi)
            B = np.zeros((3, 8))
            for i in range(4):
                B[0, 2 * i] = dNdx[0, i]
                B[1, 2 * i + 1] = dNdx[1, i]
                B[2, 2 * i] = dNdx[1, i]
                B[2, 2 * i + 1] = dNdx[0, i]
            KE += B.T @ D @ B * detJ
    return KE


# -----------------------------------------------------------------------
# Density filter
# -----------------------------------------------------------------------

def prepare_filter(nelx, nely, rmin):
    """Build sparse filter matrix H and row-sum vector Hs."""
    nele = nelx * nely
    iH, jH, sH = [], [], []
    rng = int(np.ceil(rmin))
    for ey1 in range(nely):
        for ex1 in range(nelx):
            e1 = ey1 * nelx + ex1
            for ey2 in range(max(0, ey1 - rng + 1), min(nely, ey1 + rng)):
                for ex2 in range(max(0, ex1 - rng + 1), min(nelx, ex1 + rng)):
                    dist = np.sqrt((ex1 - ex2) ** 2 + (ey1 - ey2) ** 2)
                    if dist < rmin:
                        e2 = ey2 * nelx + ex2
                        iH.append(e1)
                        jH.append(e2)
                        sH.append(rmin - dist)
    H = coo_matrix((sH, (iH, jH)), shape=(nele, nele)).tocsc()
    Hs = np.asarray(H.sum(axis=1)).flatten()
    return H, Hs


# -----------------------------------------------------------------------
# Main optimisation loop
# -----------------------------------------------------------------------

def main():
    # ---- Load problem definition ----
    with open("/app/problem.json") as f:
        prob = json.load(f)

    nelx = prob["mesh"]["nelx"]
    nely = prob["mesh"]["nely"]
    E0 = prob["material"]["E0"]
    Emin = prob["material"]["Emin"]
    nu = prob["material"]["nu"]
    volfrac = prob["optimization"]["volfrac"]
    penal = prob["optimization"]["penal"]
    rmin = prob["optimization"]["rmin"]
    max_iter = prob["optimization"]["max_iter"]
    tol = prob["optimization"]["tol"]

    nele = nelx * nely
    ndof = 2 * (nelx + 1) * (nely + 1)

    # ---- Element stiffness (unit modulus) ----
    KE = compute_ke(nu)
    KE_flat = KE.flatten()  # cache for assembly

    # ---- Density filter ----
    H, Hs = prepare_filter(nelx, nely, rmin)

    # ---- Element DOF table (vectorised) ----
    ey_arr, ex_arr = np.meshgrid(np.arange(nely), np.arange(nelx), indexing="ij")
    ey_f = ey_arr.flatten()
    ex_f = ex_arr.flatten()
    n_bl = ey_f * (nelx + 1) + ex_f
    n_br = n_bl + 1
    n_tl = (ey_f + 1) * (nelx + 1) + ex_f
    n_tr = n_tl + 1
    edofMat = np.column_stack([
        2 * n_bl, 2 * n_bl + 1,
        2 * n_br, 2 * n_br + 1,
        2 * n_tr, 2 * n_tr + 1,
        2 * n_tl, 2 * n_tl + 1,
    ])

    # Assembly index arrays (constant across iterations)
    iK = np.repeat(edofMat, 8, axis=1).flatten()
    jK = np.tile(edofMat, (1, 8)).flatten()

    # ---- Boundary conditions ----
    # Left edge (ix = 0) fully clamped
    fixed = []
    for iy in range(nely + 1):
        n = iy * (nelx + 1)
        fixed.extend([2 * n, 2 * n + 1])
    fixed = np.array(fixed, dtype=int)
    free = np.setdiff1d(np.arange(ndof), fixed)

    # Unit downward load at mid-right edge
    F = np.zeros(ndof)
    load_node = (nely // 2) * (nelx + 1) + nelx
    F[2 * load_node + 1] = -1.0

    # ---- Initialise design variables ----
    x = volfrac * np.ones(nele)
    history = []

    print(f"Topology optimisation: {nelx}x{nely} mesh, volfrac={volfrac}, "
          f"p={penal}, rmin={rmin}")

    for loop in range(1, max_iter + 1):
        # -- Filter: design vars -> physical densities --
        xPhys = np.asarray(H @ x).flatten() / Hs

        # -- Assemble global K --
        Ee = Emin + xPhys ** penal * (E0 - Emin)
        sK = (KE_flat[np.newaxis, :] * Ee[:, np.newaxis]).flatten()
        K = coo_matrix((sK, (iK, jK)), shape=(ndof, ndof)).tocsc()

        # -- Solve KU = F --
        U = np.zeros(ndof)
        U[free] = spsolve(K[np.ix_(free, free)], F[free])

        # -- Element compliances & sensitivities --
        Ue = U[edofMat]                       # (nele, 8)
        ce = np.sum((Ue @ KE) * Ue, axis=1)   # element compliance
        c = float(np.sum(Ee * ce))             # total compliance

        dc = -penal * xPhys ** (penal - 1) * (E0 - Emin) * ce   # dc/dxPhys
        dv = np.ones(nele)

        # -- Filter sensitivities (H is symmetric) --
        dc = np.asarray(H @ (dc / Hs)).flatten()
        dv = np.asarray(H @ (dv / Hs)).flatten()

        # -- OC update (bisection on Lagrange multiplier) --
        xold = x.copy()
        l1, l2 = 0.0, 1e9
        move = 0.2
        while (l2 - l1) / (l1 + l2) > 1e-3:
            lmid = 0.5 * (l1 + l2)
            Be = x * np.sqrt(np.maximum(-dc / dv / lmid, 1e-20))
            xnew = np.maximum(0.001,
                       np.maximum(x - move,
                           np.minimum(1.0,
                               np.minimum(x + move, Be))))
            xPhys_new = np.asarray(H @ xnew).flatten() / Hs
            if np.sum(xPhys_new) > volfrac * nele:
                l1 = lmid
            else:
                l2 = lmid

        x = xnew
        change = float(np.max(np.abs(x - xold)))
        vol = float(np.mean(xPhys_new))

        history.append({
            "iter": loop,
            "compliance": c,
            "volume": vol,
            "change": change,
        })
        print(f"It.: {loop:4d}  Obj.: {c:11.4f}  Vol.: {vol:.4f}  ch.: {change:.4f}")

        if change < tol:
            break

    # ---- Final evaluation with converged densities ----
    xPhys = np.asarray(H @ x).flatten() / Hs
    Ee = Emin + xPhys ** penal * (E0 - Emin)
    sK = (KE_flat[np.newaxis, :] * Ee[:, np.newaxis]).flatten()
    K = coo_matrix((sK, (iK, jK)), shape=(ndof, ndof)).tocsc()
    U = np.zeros(ndof)
    U[free] = spsolve(K[np.ix_(free, free)], F[free])
    Ue = U[edofMat]
    ce = np.sum((Ue @ KE) * Ue, axis=1)
    c_final = float(np.sum(Ee * ce))

    # ---- Save results ----
    os.makedirs("/app/results", exist_ok=True)

    np.save("/app/results/density.npy", xPhys.reshape(nely, nelx))

    with open("/app/results/compliance.txt", "w") as f:
        f.write(f"{c_final:.6f}\n")

    with open("/app/results/history.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["iter", "compliance", "volume", "change"])
        writer.writeheader()
        for row in history:
            writer.writerow(row)

    print(f"\nDone. Final compliance: {c_final:.6f}, volume: {np.mean(xPhys):.4f}")


if __name__ == "__main__":
    main()
