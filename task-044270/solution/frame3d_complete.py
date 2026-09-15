"""
3D Beam Frame Analysis Pipeline — Complete Implementation
"""

import numpy as np
import scipy
from typing import Optional, Sequence


# ---------------------------------------------------------------------------
#  WORKING FUNCTIONS
# ---------------------------------------------------------------------------

def beam_transformation_matrix_3d(x1, y1, z1, x2, y2, z2, ref_vec=None):
    dx, dy, dz = x2 - x1, y2 - y1, z2 - z1
    L = np.sqrt(dx * dx + dy * dy + dz * dz)
    if np.isclose(L, 0.0):
        raise ValueError("Beam length is zero.")
    ex = np.array([dx, dy, dz]) / L
    if ref_vec is None:
        ref_vec = (
            np.array([0.0, 0.0, 1.0])
            if not (np.isclose(ex[0], 0) and np.isclose(ex[1], 0))
            else np.array([0.0, 1.0, 0.0])
        )
    else:
        ref_vec = np.asarray(ref_vec, dtype=float)
        if ref_vec.shape != (3,):
            raise ValueError("ref_vec must be length-3.")
        if not np.isclose(np.linalg.norm(ref_vec), 1.0):
            raise ValueError("ref_vec must be unit length.")
        if np.isclose(np.linalg.norm(np.cross(ref_vec, ex)), 0.0):
            raise ValueError("ref_vec parallel to beam axis.")

    ey = np.cross(ref_vec, ex)
    ey /= np.linalg.norm(ey)
    ez = np.cross(ex, ey)
    gamma = np.vstack((ex, ey, ez))
    return np.kron(np.eye(4), gamma)


def local_elastic_stiffness_3d_beam(E, nu, A, L, Iy, Iz, J):
    k = np.zeros((12, 12))
    EA_L = E * A / L
    GJ_L = E * J / (2.0 * (1.0 + nu) * L)
    EIz = E * Iz
    EIy = E * Iy
    k[0, 0] = k[6, 6] = EA_L
    k[0, 6] = k[6, 0] = -EA_L
    k[3, 3] = k[9, 9] = GJ_L
    k[3, 9] = k[9, 3] = -GJ_L
    k[1, 1] = k[7, 7] = 12.0 * EIz / L ** 3
    k[1, 7] = k[7, 1] = -12.0 * EIz / L ** 3
    k[1, 5] = k[5, 1] = k[1, 11] = k[11, 1] = 6.0 * EIz / L ** 2
    k[5, 7] = k[7, 5] = k[7, 11] = k[11, 7] = -6.0 * EIz / L ** 2
    k[5, 5] = k[11, 11] = 4.0 * EIz / L
    k[5, 11] = k[11, 5] = 2.0 * EIz / L
    k[2, 2] = k[8, 8] = 12.0 * EIy / L ** 3
    k[2, 8] = k[8, 2] = -12.0 * EIy / L ** 3
    k[2, 4] = k[4, 2] = k[2, 10] = k[10, 2] = -6.0 * EIy / L ** 2
    k[4, 8] = k[8, 4] = k[8, 10] = k[10, 8] = 6.0 * EIy / L ** 2
    k[4, 4] = k[10, 10] = 4.0 * EIy / L
    k[4, 10] = k[10, 4] = 2.0 * EIy / L
    return k


def assemble_global_elastic_stiffness(node_coords, elements):
    n_nodes = node_coords.shape[0]
    n_dof = 6 * n_nodes
    K = np.zeros((n_dof, n_dof))
    for ele in elements:
        ni, nj = int(ele["node_i"]), int(ele["node_j"])
        xi, yi, zi = node_coords[ni]
        xj, yj, zj = node_coords[nj]
        L = np.linalg.norm([xj - xi, yj - yi, zj - zi])
        Gamma = beam_transformation_matrix_3d(
            xi, yi, zi, xj, yj, zj, ele.get("local_z")
        )
        k_loc = local_elastic_stiffness_3d_beam(
            ele["E"], ele["nu"], ele["A"], L, ele["I_y"], ele["I_z"], ele["J"]
        )
        k_glb = Gamma.T @ k_loc @ Gamma
        dofs = list(range(6 * ni, 6 * ni + 6)) + list(range(6 * nj, 6 * nj + 6))
        K[np.ix_(dofs, dofs)] += k_glb
    return K


def assemble_load_vector(nodal_loads, n_nodes):
    n_dof = 6 * n_nodes
    P = np.zeros(n_dof)
    for n, load in nodal_loads.items():
        base = 6 * n
        P[base : base + 6] += np.asarray(load, dtype=float)
    return P


def partition_dofs(boundary_conditions, n_nodes):
    n_dof = n_nodes * 6
    fixed = []
    for n in range(n_nodes):
        flags = boundary_conditions.get(n)
        if flags is not None:
            fixed.extend([6 * n + i for i, f in enumerate(flags) if f])
    fixed = np.asarray(fixed, dtype=int)
    free = np.setdiff1d(np.arange(n_dof), fixed, assume_unique=True)
    return fixed, free


def linear_solve(P_global, K_global, fixed, free):
    n_dof = len(fixed) + len(free)
    K_ff = K_global[np.ix_(free, free)]
    K_sf = K_global[np.ix_(fixed, free)]
    cond = np.linalg.cond(K_ff)
    if cond >= 1e16:
        raise ValueError(
            f"Stiffness matrix ill-conditioned (cond={cond:.2e})"
        )
    u_f = np.linalg.solve(K_ff, P_global[free])
    u = np.zeros(n_dof)
    u[free] = u_f
    reactions = np.zeros(P_global.shape)
    reactions[fixed] = K_sf @ u_f - P_global[fixed]
    return u, reactions


# ---------------------------------------------------------------------------
#  GEOMETRIC STIFFNESS AND BUCKLING FUNCTIONS
# ---------------------------------------------------------------------------

def local_geometric_stiffness_3d_beam(L, A, I_rho, Fx2, Mx2, My1, Mz1, My2, Mz2):
    """12x12 local geometric stiffness with torsion-bending coupling."""
    k_g = np.zeros((12, 12))
    # upper triangle off-diagonal terms
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
    # symmetric lower triangle
    k_g = k_g + k_g.transpose()
    # diagonal terms
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


def compute_element_internal_forces(ele_info, xi, yi, zi, xj, yj, zj, u_dofs_global):
    """Recover local element internal forces from global displacements."""
    v = np.array([xj - xi, yj - yi, zj - zi], dtype=float)
    L = np.linalg.norm(v)
    Gamma = beam_transformation_matrix_3d(
        xi, yi, zi, xj, yj, zj, ele_info.get("local_z")
    )
    k_e_local = local_elastic_stiffness_3d_beam(
        ele_info["E"], ele_info["nu"], ele_info["A"], L,
        ele_info["I_y"], ele_info["I_z"], ele_info["J"]
    )
    u_dofs_local = Gamma @ u_dofs_global
    return k_e_local @ u_dofs_local


def assemble_global_geometric_stiffness(node_coords, elements, u_global):
    """Assemble the global geometric stiffness matrix."""
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
        dx, dy, dz = (xj - xi), (yj - yi), (zj - zi)
        L = float(np.linalg.norm([dx, dy, dz]))
        A = float(ele["A"])
        I_rho = float(ele["I_rho"])
        local_z = ele.get("local_z")
        Gamma = beam_transformation_matrix_3d(xi, yi, zi, xj, yj, zj, local_z)
        dofs = list(range(6 * ni, 6 * ni + 6)) + list(range(6 * nj, 6 * nj + 6))
        u_e_global = u_global[dofs]
        load_local = compute_element_internal_forces(
            ele, xi, yi, zi, xj, yj, zj, u_e_global
        )
        Fx2 = float(load_local[6])
        Mx2 = float(load_local[9])
        My1 = float(load_local[4])
        Mz1 = float(load_local[5])
        My2 = float(load_local[10])
        Mz2 = float(load_local[11])
        k_g_local = local_geometric_stiffness_3d_beam(
            L, A, I_rho, Fx2, Mx2, My1, Mz1, My2, Mz2
        )
        k_g_global = Gamma.T @ k_g_local @ Gamma
        K[np.ix_(dofs, dofs)] += k_g_global

    return K


def eigenvalue_buckling_solve(K_e_global, K_g_global, boundary_conditions, n_nodes):
    """Solve the buckling eigenvalue problem."""
    c_eps = 1e3 * np.finfo(float).eps

    _, free = partition_dofs(boundary_conditions, n_nodes)
    free = np.asarray(free, dtype=int)

    K_e_ff = K_e_global[np.ix_(free, free)]
    K_g_ff = K_g_global[np.ix_(free, free)]

    # enforce symmetry
    K_e_ff = 0.5 * (K_e_ff + K_e_ff.T)
    K_g_ff = 0.5 * (K_g_ff + K_g_ff.T)

    # conditioning checks
    cond_e = np.linalg.cond(K_e_ff)
    if not np.isfinite(cond_e) or cond_e > 1e16:
        raise ValueError(
            f"Elastic stiffness ill-conditioned (cond={cond_e:.3e})."
        )
    cond_g = np.linalg.cond(K_g_ff)
    if not np.isfinite(cond_g) or cond_g > 1e16:
        raise ValueError(
            f"Geometric stiffness ill-conditioned (cond={cond_g:.3e})."
        )

    # generalized eigenvalue solve
    eig_vals, eig_vecs = scipy.linalg.eig(
        K_e_ff, -1.0 * K_g_ff, check_finite=False
    )

    if eig_vals.size == 0:
        raise ValueError("Eigen-solution returned no eigenvalues.")

    # realness check
    lam_max = float(np.max(np.abs(eig_vals)))
    rel_imag = np.max(np.abs(np.imag(eig_vals))) / max(lam_max, 1.0)

    if rel_imag <= c_eps:
        V = eig_vecs.copy()
        for j in range(V.shape[1]):
            col = V[:, j]
            k_idx = int(np.argmax(np.abs(col)))
            phase = np.conj(col[k_idx]) / (abs(col[k_idx]) + 1e-300)
            V[:, j] = phase * col
        eig_vals = np.real(eig_vals)
        eig_vecs = np.real(V)
    else:
        raise ValueError(
            f"Complex eigenpairs (relative imag={rel_imag:.3e})."
        )

    # select smallest positive eigenvalue
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

    # embed into full DOF vector
    n_dof = 6 * n_nodes
    mode = np.zeros(n_dof, dtype=float)
    mode[free] = eig_vector_free

    return eig_value, mode


def elastic_critical_load_analysis(node_coords, elements, boundary_conditions, nodal_loads):
    """Full eigenvalue buckling analysis pipeline."""
    n_nodes = node_coords.shape[0]

    # 1. Assemble elastic stiffness
    K = assemble_global_elastic_stiffness(node_coords, elements)

    # 2. Assemble load vector
    P = assemble_load_vector(nodal_loads, n_nodes)

    # 3. Partition DOFs and solve linear system
    fixed, free = partition_dofs(boundary_conditions, n_nodes)
    u_global, _ = linear_solve(P, K, fixed, free)

    # 4. Assemble geometric stiffness
    K_g = assemble_global_geometric_stiffness(node_coords, elements, u_global)

    # 5. Solve eigenvalue problem
    lam, mode = eigenvalue_buckling_solve(K, K_g, boundary_conditions, n_nodes)

    return lam, mode
