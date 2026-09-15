#!/usr/bin/env python3

"""
P2-P1 Taylor-Hood finite element solver for 2D steady Stokes equations.

Solves: -Laplacian(u) + grad(p) = f, div(u) = 0 on [0,1]^2
with Dirichlet BCs from a manufactured solution.

Performs h-convergence analysis for n in {4, 8, 16, 32}.
"""

import json
import sys

import numpy as np
from scipy.sparse import bmat, csr_matrix, lil_matrix
from scipy.sparse.linalg import spsolve

sys.path.insert(0, "/app")
from problem_spec import f_body, p_exact, u_exact


# ==================================================================
# Quadrature: 7-point Dunavant rule on reference triangle
# [(0,0), (1,0), (0,1)], exact for degree <= 5.
# Weights sum to 1/2 (area of reference triangle).
# ==================================================================

def gauss_triangle_7pt():
    s15 = np.sqrt(15.0)
    a1 = (6.0 - s15) / 21.0
    a2 = (6.0 + s15) / 21.0
    w0 = 9.0 / 80.0
    w1 = (155.0 - s15) / 2400.0
    w2 = (155.0 + s15) / 2400.0
    points = np.array([
        [1.0 / 3.0, 1.0 / 3.0],
        [a1, a1],
        [1.0 - 2.0 * a1, a1],
        [a1, 1.0 - 2.0 * a1],
        [a2, a2],
        [1.0 - 2.0 * a2, a2],
        [a2, 1.0 - 2.0 * a2],
    ])
    weights = np.array([w0, w1, w1, w1, w2, w2, w2])
    return points, weights


# ==================================================================
# P2 basis functions on reference triangle.
#
# Nodes (local numbering):
#   0: (0,0)     1: (1,0)       2: (0,1)
#   3: (0.5,0)   4: (0.5,0.5)   5: (0,0.5)
#
# Barycentric coords: lam0 = 1-xi-eta, lam1 = xi, lam2 = eta
# ==================================================================

def p2_basis(xi, eta):
    lam0 = 1.0 - xi - eta
    lam1 = xi
    lam2 = eta

    phi = np.array([
        lam0 * (2.0 * lam0 - 1.0),
        lam1 * (2.0 * lam1 - 1.0),
        lam2 * (2.0 * lam2 - 1.0),
        4.0 * lam0 * lam1,
        4.0 * lam1 * lam2,
        4.0 * lam0 * lam2,
    ])

    dphi_dxi = np.array([
        4.0 * xi + 4.0 * eta - 3.0,
        4.0 * xi - 1.0,
        0.0,
        4.0 - 8.0 * xi - 4.0 * eta,
        4.0 * eta,
        -4.0 * eta,
    ])

    dphi_deta = np.array([
        4.0 * xi + 4.0 * eta - 3.0,
        0.0,
        4.0 * eta - 1.0,
        -4.0 * xi,
        4.0 * xi,
        4.0 - 8.0 * xi - 4.0 * eta,
    ])

    return phi, dphi_dxi, dphi_deta


# ==================================================================
# P1 basis functions on reference triangle.
# ==================================================================

def p1_basis(xi, eta):
    psi = np.array([1.0 - xi - eta, xi, eta])
    dpsi_dxi = np.array([-1.0, 1.0, 0.0])
    dpsi_deta = np.array([-1.0, 0.0, 1.0])
    return psi, dpsi_dxi, dpsi_deta


# ==================================================================
# Mesh generation: structured triangular mesh on [0,1]^2.
#
# P2 nodes live on a (2n+1)x(2n+1) grid.
# P1 nodes live on a (n+1)x(n+1) grid.
# Each cell is split into 2 triangles by the (i,j)->(i+1,j+1) diagonal.
# ==================================================================

def generate_mesh(n):
    m = 2 * n + 1  # P2 grid side length

    # P2 coordinates
    x2 = np.linspace(0.0, 1.0, m)
    y2 = np.linspace(0.0, 1.0, m)
    X2, Y2 = np.meshgrid(x2, y2)
    coords_p2 = np.column_stack([X2.ravel(), Y2.ravel()])

    # P1 coordinates
    x1 = np.linspace(0.0, 1.0, n + 1)
    y1 = np.linspace(0.0, 1.0, n + 1)
    X1, Y1 = np.meshgrid(x1, y1)
    coords_p1 = np.column_stack([X1.ravel(), Y1.ravel()])

    n_elem = 2 * n * n
    elems_p2 = np.empty((n_elem, 6), dtype=int)
    elems_p1 = np.empty((n_elem, 3), dtype=int)

    e = 0
    for j in range(n):
        for i in range(n):
            # P1 vertex indices
            v00 = j * (n + 1) + i
            v10 = j * (n + 1) + (i + 1)
            v01 = (j + 1) * (n + 1) + i
            v11 = (j + 1) * (n + 1) + (i + 1)

            # P2 node indices
            c00 = (2 * j) * m + (2 * i)
            c10 = (2 * j) * m + (2 * i + 2)
            c01 = (2 * j + 2) * m + (2 * i)
            c11 = (2 * j + 2) * m + (2 * i + 2)

            m_bot = (2 * j) * m + (2 * i + 1)
            m_right = (2 * j + 1) * m + (2 * i + 2)
            m_top = (2 * j + 2) * m + (2 * i + 1)
            m_left = (2 * j + 1) * m + (2 * i)
            m_diag = (2 * j + 1) * m + (2 * i + 1)

            # Triangle 1 (lower-right): (i,j) -> (i+1,j) -> (i+1,j+1)
            elems_p2[e] = [c00, c10, c11, m_bot, m_right, m_diag]
            elems_p1[e] = [v00, v10, v11]
            e += 1

            # Triangle 2 (upper-left): (i,j) -> (i+1,j+1) -> (i,j+1)
            elems_p2[e] = [c00, c11, c01, m_diag, m_left, m_top]
            elems_p1[e] = [v00, v11, v01]
            e += 1

    return coords_p2, elems_p2, coords_p1, elems_p1


# ==================================================================
# Assembly of the Stokes system.
#
# System structure:
#   [K    0    -Bx^T] [U1]   [F1]
#   [0    K    -By^T] [U2] = [F2]
#   [-Bx -By    0   ] [P ]   [0 ]
#
# K_ij   = integral( grad(phi_i) . grad(phi_j) )   (P2 stiffness)
# Bx_ki  = integral( psi_k * d(phi_i)/dx )         (divergence, x)
# By_ki  = integral( psi_k * d(phi_i)/dy )         (divergence, y)
# F1_i   = integral( f1 * phi_i )                  (forcing, x)
# F2_i   = integral( f2 * phi_i )                  (forcing, y)
# ==================================================================

def assemble_stokes(coords_p2, elems_p2, coords_p1, elems_p1):
    n_p2 = coords_p2.shape[0]
    n_p1 = coords_p1.shape[0]
    n_elem = elems_p2.shape[0]

    K = lil_matrix((n_p2, n_p2))
    Bx = lil_matrix((n_p1, n_p2))
    By = lil_matrix((n_p1, n_p2))
    F1 = np.zeros(n_p2)
    F2 = np.zeros(n_p2)

    qpts, qwts = gauss_triangle_7pt()

    for e in range(n_elem):
        p2n = elems_p2[e]
        p1n = elems_p1[e]

        # Vertices of the physical triangle (first 3 P2 nodes)
        x0, y0 = coords_p2[p2n[0]]
        x1, y1 = coords_p2[p2n[1]]
        x2, y2 = coords_p2[p2n[2]]

        # Jacobian of reference-to-physical mapping
        dxdxi = x1 - x0
        dxdeta = x2 - x0
        dydxi = y1 - y0
        dydeta = y2 - y0
        detJ = dxdxi * dydeta - dxdeta * dydxi
        inv_detJ = 1.0 / detJ

        for q in range(len(qwts)):
            xi, eta = qpts[q]
            w = qwts[q]

            # Physical coordinates
            xp = x0 + dxdxi * xi + dxdeta * eta
            yp = y0 + dydxi * xi + dydeta * eta

            # P2 basis and reference gradients
            phi, dphi_dxi, dphi_deta = p2_basis(xi, eta)

            # Transform gradients to physical coordinates
            dphi_dx = inv_detJ * (dydeta * dphi_dxi - dydxi * dphi_deta)
            dphi_dy = inv_detJ * (-dxdeta * dphi_dxi + dxdxi * dphi_deta)

            # P1 basis
            psi, _, _ = p1_basis(xi, eta)

            # Integration weight
            wJ = w * abs(detJ)

            # Body force
            f1v, f2v = f_body(xp, yp)

            # Stiffness matrix K
            for a in range(6):
                for b in range(6):
                    K[p2n[a], p2n[b]] += wJ * (
                        dphi_dx[a] * dphi_dx[b] + dphi_dy[a] * dphi_dy[b]
                    )

            # Divergence matrices Bx, By
            for k in range(3):
                for a in range(6):
                    Bx[p1n[k], p2n[a]] += wJ * psi[k] * dphi_dx[a]
                    By[p1n[k], p2n[a]] += wJ * psi[k] * dphi_dy[a]

            # Forcing vectors
            for a in range(6):
                F1[p2n[a]] += wJ * f1v * phi[a]
                F2[p2n[a]] += wJ * f2v * phi[a]

    return K.tocsr(), Bx.tocsr(), By.tocsr(), F1, F2


# ==================================================================
# Boundary condition handling.
# ==================================================================

def get_boundary_dofs(coords, tol=1e-12):
    """Return indices of nodes on the boundary of [0,1]^2."""
    x, y = coords[:, 0], coords[:, 1]
    return np.where(
        (x < tol) | (x > 1.0 - tol) | (y < tol) | (y > 1.0 - tol)
    )[0]


def apply_dirichlet_bc(A, rhs, bc_dofs, bc_vals):
    """Apply Dirichlet BCs by row/column elimination.

    Modifies rhs in-place. Returns modified (A_csr, rhs).
    """
    A = A.tolil()

    # Step 1: modify RHS to account for known BC values
    for j, val in zip(bc_dofs, bc_vals):
        col = np.asarray(A[:, j].todense()).ravel()
        rhs -= col * val

    # Step 2: zero out BC rows and columns, set diagonal to 1
    for dof in bc_dofs:
        A[dof, :] = 0
        A[:, dof] = 0
        A[dof, dof] = 1.0

    # Step 3: set BC values in RHS (overrides any accumulated changes)
    rhs[bc_dofs] = bc_vals

    return A.tocsr(), rhs


# ==================================================================
# Solver
# ==================================================================

def solve_stokes(n):
    """Solve the Stokes problem on a mesh with n divisions per side."""
    print(f"  n={n}: generating mesh...", flush=True)
    coords_p2, elems_p2, coords_p1, elems_p1 = generate_mesh(n)
    n_p2 = coords_p2.shape[0]
    n_p1 = coords_p1.shape[0]
    print(f"         P2 nodes={n_p2}, P1 nodes={n_p1}, "
          f"elements={elems_p2.shape[0]}")

    print(f"         assembling...", flush=True)
    K, Bx, By, F1, F2 = assemble_stokes(
        coords_p2, elems_p2, coords_p1, elems_p1
    )

    # Build the full saddle-point system
    Z_pp = csr_matrix((n_p1, n_p1))
    A = bmat([
        [K, None, -Bx.T],
        [None, K, -By.T],
        [-Bx, -By, Z_pp],
    ], format="csr")
    rhs = np.concatenate([F1, F2, np.zeros(n_p1)])

    # Collect Dirichlet BCs for velocity (all boundary P2 nodes)
    bdy_p2 = get_boundary_dofs(coords_p2)
    all_bc_dofs = []
    all_bc_vals = []
    for dof in bdy_p2:
        xc, yc = coords_p2[dof]
        u1v, u2v = u_exact(xc, yc)
        all_bc_dofs.append(dof)
        all_bc_vals.append(u1v)
        all_bc_dofs.append(n_p2 + dof)
        all_bc_vals.append(u2v)

    # Pin pressure at first P1 node
    p_pin_dof = 2 * n_p2
    p_pin_val = p_exact(coords_p1[0, 0], coords_p1[0, 1])
    all_bc_dofs.append(p_pin_dof)
    all_bc_vals.append(float(p_pin_val))

    all_bc_dofs = np.array(all_bc_dofs, dtype=int)
    all_bc_vals = np.array(all_bc_vals, dtype=float)

    print(f"         applying BCs ({len(all_bc_dofs)} constrained)...",
          flush=True)
    A_bc, rhs_bc = apply_dirichlet_bc(A, rhs, all_bc_dofs, all_bc_vals)

    print(f"         solving {A_bc.shape[0]}x{A_bc.shape[1]} system...",
          flush=True)
    sol = spsolve(A_bc, rhs_bc)

    u1_vals = sol[:n_p2]
    u2_vals = sol[n_p2:2 * n_p2]
    p_vals = sol[2 * n_p2:]

    return (u1_vals, u2_vals, p_vals,
            coords_p2, coords_p1, elems_p2, elems_p1)


# ==================================================================
# L2 error computation via numerical quadrature.
# ==================================================================

def compute_errors(u1_vals, u2_vals, p_vals,
                   coords_p2, coords_p1, elems_p2, elems_p1):
    qpts, qwts = gauss_triangle_7pt()
    n_elem = elems_p2.shape[0]

    err_u_sq = 0.0
    err_p_sq = 0.0

    for e in range(n_elem):
        p2n = elems_p2[e]
        p1n = elems_p1[e]

        x0, y0 = coords_p2[p2n[0]]
        x1, y1 = coords_p2[p2n[1]]
        x2, y2 = coords_p2[p2n[2]]

        dxdxi = x1 - x0
        dxdeta = x2 - x0
        dydxi = y1 - y0
        dydeta = y2 - y0
        detJ = dxdxi * dydeta - dxdeta * dydxi

        for q in range(len(qwts)):
            xi, eta = qpts[q]
            w = qwts[q]

            xp = x0 + dxdxi * xi + dxdeta * eta
            yp = y0 + dydxi * xi + dydeta * eta

            phi, _, _ = p2_basis(xi, eta)
            psi, _, _ = p1_basis(xi, eta)

            u1_h = np.dot(phi, u1_vals[p2n])
            u2_h = np.dot(phi, u2_vals[p2n])
            p_h = np.dot(psi, p_vals[p1n])

            u1_ex, u2_ex = u_exact(xp, yp)
            p_ex = p_exact(xp, yp)

            wJ = w * abs(detJ)
            err_u_sq += wJ * ((u1_h - u1_ex) ** 2 + (u2_h - u2_ex) ** 2)
            err_p_sq += wJ * (p_h - p_ex) ** 2

    return np.sqrt(err_u_sq), np.sqrt(err_p_sq)


# ==================================================================
# Main: convergence analysis
# ==================================================================

def main():
    mesh_sizes = [4, 8, 16, 32]
    velocity_errors = []
    pressure_errors = []

    print("P2-P1 Taylor-Hood Stokes solver — convergence study")
    print("=" * 55)

    for n in mesh_sizes:
        u1, u2, p, c_p2, c_p1, e_p2, e_p1 = solve_stokes(n)
        err_u, err_p = compute_errors(u1, u2, p, c_p2, c_p1, e_p2, e_p1)
        velocity_errors.append(float(err_u))
        pressure_errors.append(float(err_p))
        print(f"         e_u = {err_u:.6e},  e_p = {err_p:.6e}")

    # Compute convergence rates
    vel_rates = []
    pres_rates = []
    for i in range(len(mesh_sizes) - 1):
        vr = np.log(velocity_errors[i] / velocity_errors[i + 1]) / np.log(2.0)
        pr = np.log(pressure_errors[i] / pressure_errors[i + 1]) / np.log(2.0)
        vel_rates.append(float(vr))
        pres_rates.append(float(pr))

    avg_vel = float(np.mean(vel_rates))
    avg_pres = float(np.mean(pres_rates))

    results = {
        "mesh_sizes": mesh_sizes,
        "velocity_l2_errors": velocity_errors,
        "pressure_l2_errors": pressure_errors,
        "velocity_convergence_rates": vel_rates,
        "pressure_convergence_rates": pres_rates,
        "velocity_avg_convergence_rate": avg_vel,
        "pressure_avg_convergence_rate": avg_pres,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print()
    print(f"Velocity rates: {[f'{r:.3f}' for r in vel_rates]}, "
          f"avg = {avg_vel:.3f}")
    print(f"Pressure rates: {[f'{r:.3f}' for r in pres_rates]}, "
          f"avg = {avg_pres:.3f}")
    print(f"\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
