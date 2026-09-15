"""
Geometric stiffness and eigenvalue buckling analysis for 3D beam elements.

Complete implementation of the local geometric stiffness matrix with
torsion-bending coupling, global geometric stiffness assembly, and
eigenvalue buckling solver.
"""

import numpy as np
import scipy.linalg
from typing import Sequence
from .elastic import transformation_matrix_3d, local_elastic_stiffness_3d
from .solve import partition_dofs, element_internal_forces


def local_geometric_stiffness_3d(L, A, I_rho, Fx2, Mx2, My1, Mz1, My2, Mz2):
    """
    Construct the 12x12 local geometric stiffness matrix for a 3D
    Euler-Bernoulli beam element with full torsion-bending coupling.
    """
    k_g = np.zeros((12, 12))

    # ---- upper triangle off-diagonal terms ----
    k_g[0, 6] = -Fx2 / L

    k_g[1, 3] = My1 / L
    k_g[1, 4] = Mx2 / L
    k_g[1, 5] = Fx2 / 10.0
    k_g[1, 7] = -6.0 * Fx2 / (5.0 * L)
    k_g[1, 9] = My2 / L
    k_g[1, 10] = -Mx2 / L
    k_g[1, 11] = Fx2 / 10.0

    k_g[2, 3] = Mz1 / L
    k_g[2, 4] = -Fx2 / 10.0
    k_g[2, 5] = Mx2 / L
    k_g[2, 8] = -6.0 * Fx2 / (5.0 * L)
    k_g[2, 9] = Mz2 / L
    k_g[2, 10] = -Fx2 / 10.0
    k_g[2, 11] = -Mx2 / L

    k_g[3, 4] = -1.0 * (2.0 * Mz1 - Mz2) / 6.0
    k_g[3, 5] = (2.0 * My1 - My2) / 6.0
    k_g[3, 7] = -My1 / L
    k_g[3, 8] = -Mz1 / L
    k_g[3, 9] = -Fx2 * I_rho / (A * L)
    k_g[3, 10] = -1.0 * (Mz1 + Mz2) / 6.0
    k_g[3, 11] = (My1 + My2) / 6.0

    k_g[4, 7] = -Mx2 / L
    k_g[4, 8] = Fx2 / 10.0
    k_g[4, 9] = -1.0 * (Mz1 + Mz2) / 6.0
    k_g[4, 10] = -Fx2 * L / 30.0
    k_g[4, 11] = Mx2 / 2.0

    k_g[5, 7] = -Fx2 / 10.0
    k_g[5, 8] = -Mx2 / L
    k_g[5, 9] = (My1 + My2) / 6.0
    k_g[5, 10] = -Mx2 / 2.0
    k_g[5, 11] = -Fx2 * L / 30.0

    k_g[7, 9] = -My2 / L
    k_g[7, 10] = Mx2 / L
    k_g[7, 11] = -Fx2 / 10.0

    k_g[8, 9] = -Mz2 / L
    k_g[8, 10] = Fx2 / 10.0
    k_g[8, 11] = Mx2 / L

    k_g[9, 10] = (Mz1 - 2.0 * Mz2) / 6.0
    k_g[9, 11] = -1.0 * (My1 - 2.0 * My2) / 6.0

    # ---- symmetric lower triangle ----
    k_g = k_g + k_g.T

    # ---- diagonal terms ----
    k_g[0, 0] = Fx2 / L
    k_g[1, 1] = 6.0 * Fx2 / (5.0 * L)
    k_g[2, 2] = 6.0 * Fx2 / (5.0 * L)
    k_g[3, 3] = Fx2 * I_rho / (A * L)
    k_g[4, 4] = 2.0 * Fx2 * L / 15.0
    k_g[5, 5] = 2.0 * Fx2 * L / 15.0
    k_g[6, 6] = Fx2 / L
    k_g[7, 7] = 6.0 * Fx2 / (5.0 * L)
    k_g[8, 8] = 6.0 * Fx2 / (5.0 * L)
    k_g[9, 9] = Fx2 * I_rho / (A * L)
    k_g[10, 10] = 2.0 * Fx2 * L / 15.0
    k_g[11, 11] = 2.0 * Fx2 * L / 15.0

    return k_g


def assemble_global_geometric_stiffness(node_coords, elements, u_global):
    """
    Assemble the global geometric stiffness matrix from element
    contributions using internal forces from the linear static solution.
    """
    node_coords = np.asarray(node_coords, dtype=float)
    u_global = np.asarray(u_global, dtype=float)
    n_nodes = node_coords.shape[0]
    n_dof = 6 * n_nodes
    K = np.zeros((n_dof, n_dof), dtype=float)

    for ele in elements:
        ni = int(ele["node_i"])
        nj = int(ele["node_j"])
        xi, yi, zi = node_coords[ni]
        xj, yj, zj = node_coords[nj]
        L = float(np.linalg.norm([xj - xi, yj - yi, zj - zi]))
        A = float(ele["A"])
        I_rho = float(ele["I_rho"])

        Gamma = transformation_matrix_3d(
            xi, yi, zi, xj, yj, zj, ele.get("local_z")
        )

        # Recover internal forces in local coordinates
        f_local = element_internal_forces(ele, node_coords, u_global)

        Fx2 = float(f_local[6])
        Mx2 = float(f_local[9])
        My1 = float(f_local[4])
        Mz1 = float(f_local[5])
        My2 = float(f_local[10])
        Mz2 = float(f_local[11])

        k_g_local = local_geometric_stiffness_3d(
            L, A, I_rho, Fx2, Mx2, My1, Mz1, My2, Mz2
        )
        k_g_global = Gamma.T @ k_g_local @ Gamma

        dofs = list(range(6 * ni, 6 * ni + 6)) + \
               list(range(6 * nj, 6 * nj + 6))
        K[np.ix_(dofs, dofs)] += k_g_global

    return K


def eigenvalue_buckling_solve(K_e, K_g, boundary_conditions, n_nodes):
    """
    Solve the generalized eigenvalue buckling problem:
        K_e * phi = -lambda * K_g * phi
    """
    c_eps = 1e3 * np.finfo(float).eps

    # DOF partitioning
    _, free = partition_dofs(boundary_conditions, n_nodes)
    free = np.asarray(free, dtype=int)

    # Extract free-free blocks
    K_e_ff = K_e[np.ix_(free, free)]
    K_g_ff = K_g[np.ix_(free, free)]

    # Enforce exact symmetry
    K_e_ff = 0.5 * (K_e_ff + K_e_ff.T)
    K_g_ff = 0.5 * (K_g_ff + K_g_ff.T)

    # Generalized eigenvalue solve
    eig_vals, eig_vecs = scipy.linalg.eig(
        K_e_ff, -1.0 * K_g_ff, check_finite=False
    )

    if eig_vals.size == 0:
        raise ValueError("Eigen-solution returned no eigenvalues.")

    # Realness check
    lam_max = float(np.max(np.abs(eig_vals)))
    rel_imag = np.max(np.abs(np.imag(eig_vals))) / max(lam_max, 1.0)

    if rel_imag <= c_eps:
        # De-phase eigenvectors and take real parts
        V = eig_vecs.copy()
        for j in range(V.shape[1]):
            col = V[:, j]
            k = int(np.argmax(np.abs(col)))
            phase = np.conj(col[k]) / (abs(col[k]) + 1e-300)
            V[:, j] = phase * col
        eig_vals = np.real(eig_vals)
        eig_vecs = np.real(V)
    else:
        raise ValueError(
            f"Significantly complex eigenpairs (rel_imag={rel_imag:.3e})"
        )

    # Select smallest positive eigenvalue
    vals = eig_vals.astype(float, copy=False)
    finite = np.isfinite(vals)
    lam_scale = np.max(np.abs(vals[finite])) if np.any(finite) else 1.0
    pos_cut = max(1e-12, c_eps * lam_scale)

    cand = np.flatnonzero(finite & (vals > pos_cut))
    if cand.size == 0:
        raise ValueError("No positive buckling factors found.")

    ix = cand[np.argmin(vals[cand])]
    eig_value = float(vals[ix])
    eig_vector_free = eig_vecs[:, ix].astype(float, copy=False)

    # Embed into full DOF vector
    n_dof = 6 * n_nodes
    mode = np.zeros(n_dof, dtype=float)
    mode[free] = eig_vector_free

    return eig_value, mode
