#!/usr/bin/env python3

"""
P2-P1 Taylor-Hood finite element solver for 2D steady Stokes equations.

Solves: -Laplacian(u) + grad(p) = f, div(u) = 0 on [0,1]^2
with Dirichlet BCs from a manufactured solution.

Body force is derived via symbolic differentiation using sympy.
Performs h-convergence analysis for n in {4, 8, 16, 32}.
"""

import json
import sys

import numpy as np
from scipy.sparse import bmat, csr_matrix, lil_matrix
from scipy.sparse.linalg import spsolve

sys.path.insert(0, "/app")
from problem_spec import u_exact, p_exact
from fem_framework import gauss_triangle_7pt, p2_basis, p1_basis, generate_mesh


# ==================================================================
# Body force derivation via sympy
# ==================================================================

def derive_body_force():
    """Derive the body force f = -Lap(u) + grad(p) using sympy.

    Uses the stream function and pressure defined in problem_spec.py
    to compute the body force symbolically, then returns numpy-callable
    functions.

    Returns:
        f1_func, f2_func: callables (x, y) -> scalar
    """
    import sympy as sp

    x, y = sp.symbols('x y')
    pi = sp.pi

    # Stream function (must match problem_spec.py exactly)
    psi = sp.sin(pi * x) * sp.sin(pi * y) / pi**2 + \
          x**2 * (1 - x)**2 * y**2 * (1 - y)**2

    # Velocity from stream function: u = curl(psi)
    u1_sym = sp.diff(psi, y)
    u2_sym = -sp.diff(psi, x)

    # Verify divergence-free
    div_u = sp.simplify(sp.diff(u1_sym, x) + sp.diff(u2_sym, y))
    assert div_u == 0, f"Velocity is not divergence-free: div(u) = {div_u}"

    # Pressure
    p_sym = sp.sin(pi * x) * sp.sin(pi * y)

    # Laplacian of velocity components
    lap_u1 = sp.diff(u1_sym, x, 2) + sp.diff(u1_sym, y, 2)
    lap_u2 = sp.diff(u2_sym, x, 2) + sp.diff(u2_sym, y, 2)

    # Body force: f = -Lap(u) + grad(p)
    f1_sym = -lap_u1 + sp.diff(p_sym, x)
    f2_sym = -lap_u2 + sp.diff(p_sym, y)

    # Convert to numpy-callable functions
    f1_func = sp.lambdify((x, y), f1_sym, modules=['numpy'])
    f2_func = sp.lambdify((x, y), f2_sym, modules=['numpy'])

    return f1_func, f2_func


# ==================================================================
# Assembly of the Stokes system.
#
# System structure (saddle-point):
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

def assemble_stokes(coords_p2, elems_p2, coords_p1, elems_p1, f_body):
    """Assemble the Stokes system matrices and forcing vectors.

    Args:
        coords_p2: P2 node coordinates
        elems_p2: P2 element connectivity
        coords_p1: P1 node coordinates
        elems_p1: P1 element connectivity
        f_body: callable (x, y) -> (f1, f2)

    Returns:
        K, Bx, By: sparse matrices
        F1, F2: forcing vectors
    """
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

            # Physical coordinates at quadrature point
            xp = x0 + dxdxi * xi + dxdeta * eta
            yp = y0 + dydxi * xi + dydeta * eta

            # P2 basis and reference gradients
            phi, dphi_dxi, dphi_deta = p2_basis(xi, eta)

            # Transform gradients to physical coordinates via inverse Jacobian
            dphi_dx = inv_detJ * (dydeta * dphi_dxi - dydxi * dphi_deta)
            dphi_dy = inv_detJ * (-dxdeta * dphi_dxi + dxdxi * dphi_deta)

            # P1 basis
            psi, _, _ = p1_basis(xi, eta)

            # Integration weight (quadrature weight times Jacobian determinant)
            wJ = w * abs(detJ)

            # Body force at this quadrature point
            f1v, f2v = f_body(xp, yp)

            # Stiffness matrix K (Laplacian operator)
            for a in range(6):
                for b in range(6):
                    K[p2n[a], p2n[b]] += wJ * (
                        dphi_dx[a] * dphi_dx[b] + dphi_dy[a] * dphi_dy[b]
                    )

            # Divergence matrices Bx, By (pressure-velocity coupling)
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
# Boundary condition handling
# ==================================================================

def get_boundary_dofs(coords, tol=1e-12):
    """Return indices of nodes on the boundary of [0,1]^2."""
    x, y = coords[:, 0], coords[:, 1]
    return np.where(
        (x < tol) | (x > 1.0 - tol) | (y < tol) | (y > 1.0 - tol)
    )[0]


def apply_dirichlet_bc(A, rhs, bc_dofs, bc_vals):
    """Apply Dirichlet BCs by row/column elimination.

    For each constrained DOF j with value g_j:
    1. Subtract A[:,j]*g_j from RHS (lift known values)
    2. Zero out row j and column j of A
    3. Set A[j,j] = 1, rhs[j] = g_j

    Returns modified (A_csr, rhs).
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

    # Step 3: set BC values in RHS
    rhs[bc_dofs] = bc_vals

    return A.tocsr(), rhs


# ==================================================================
# Solver: assemble, apply BCs, solve saddle-point system
# ==================================================================

def solve_stokes(n, f_body):
    """Solve the Stokes problem on a mesh with n divisions per side.

    Args:
        n: mesh divisions
        f_body: callable (x, y) -> (f1, f2)

    Returns:
        u1_vals, u2_vals, p_vals: solution arrays
        coords_p2, coords_p1, elems_p2, elems_p1: mesh data
    """
    print(f"  n={n}: generating mesh...", flush=True)
    coords_p2, elems_p2, coords_p1, elems_p1 = generate_mesh(n)
    n_p2 = coords_p2.shape[0]
    n_p1 = coords_p1.shape[0]
    print(f"         P2 nodes={n_p2}, P1 nodes={n_p1}, "
          f"elements={elems_p2.shape[0]}")

    print(f"         assembling...", flush=True)
    K, Bx, By, F1, F2 = assemble_stokes(
        coords_p2, elems_p2, coords_p1, elems_p1, f_body
    )

    # Build the full saddle-point system as a block matrix
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
        # u1 component
        all_bc_dofs.append(dof)
        all_bc_vals.append(u1v)
        # u2 component (offset by n_p2)
        all_bc_dofs.append(n_p2 + dof)
        all_bc_vals.append(u2v)

    # Pin pressure at first P1 node to remove the hydrostatic mode
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
# L2 error computation via numerical quadrature
# ==================================================================

def compute_errors(u1_vals, u2_vals, p_vals,
                   coords_p2, coords_p1, elems_p2, elems_p1):
    """Compute L2 error norms for velocity and pressure.

    Integrates ||u_h - u_exact||^2 and ||p_h - p_exact||^2 over
    each element using 7-point quadrature.
    """
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

            # FEM solution at quadrature point
            u1_h = np.dot(phi, u1_vals[p2n])
            u2_h = np.dot(phi, u2_vals[p2n])
            p_h = np.dot(psi, p_vals[p1n])

            # Exact solution at quadrature point
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
    print("Deriving body force via symbolic differentiation...", flush=True)
    f1_func, f2_func = derive_body_force()

    def f_body(x, y):
        return float(f1_func(x, y)), float(f2_func(x, y))

    mesh_sizes = [4, 8, 16, 32]
    velocity_errors = []
    pressure_errors = []

    print("\nP2-P1 Taylor-Hood Stokes solver -- convergence study")
    print("=" * 55)

    for n in mesh_sizes:
        u1, u2, p, c_p2, c_p1, e_p2, e_p1 = solve_stokes(n, f_body)
        err_u, err_p = compute_errors(u1, u2, p, c_p2, c_p1, e_p2, e_p1)
        velocity_errors.append(float(err_u))
        pressure_errors.append(float(err_p))
        print(f"         e_u = {err_u:.6e},  e_p = {err_p:.6e}")

    # Compute convergence rates: r_i = log(e_i/e_{i+1}) / log(2)
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
