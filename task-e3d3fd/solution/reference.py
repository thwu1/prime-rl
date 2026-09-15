"""
3D Frame Eigenvalue Buckling Analysis - Reference Implementation

Complete pipeline: elastic stiffness assembly, coordinate transformation,
load vector, DOF partitioning, linear solve, internal force recovery,
geometric stiffness with full torsion-bending coupling, and eigenvalue solve.
"""
import numpy as np
import scipy
from typing import Optional, Sequence


def elastic_critical_load_analysis(
    node_coords: np.ndarray,
    elements: Sequence[dict],
    boundary_conditions: dict,
    nodal_loads: dict,
):
    """
    Perform linear (eigenvalue) buckling analysis for a 3D frame.

    Returns (critical_load_factor, mode_shape).
    """

    # ------------------------------------------------------------------ #
    #  Local elastic stiffness matrix (12x12, Euler-Bernoulli beam)      #
    # ------------------------------------------------------------------ #
    def _local_elastic_stiffness(E, nu, A, L, Iy, Iz, J):
        k = np.zeros((12, 12))
        EA_L = E * A / L
        GJ_L = E * J / (2.0 * (1.0 + nu) * L)
        EIz = E * Iz
        EIy = E * Iy

        # Axial
        k[0, 0] = k[6, 6] = EA_L
        k[0, 6] = k[6, 0] = -EA_L

        # Torsion
        k[3, 3] = k[9, 9] = GJ_L
        k[3, 9] = k[9, 3] = -GJ_L

        # Bending about z-axis (local y-displacements, rotations about z)
        k[1, 1] = k[7, 7] = 12.0 * EIz / L ** 3
        k[1, 7] = k[7, 1] = -12.0 * EIz / L ** 3
        k[1, 5] = k[5, 1] = k[1, 11] = k[11, 1] = 6.0 * EIz / L ** 2
        k[5, 7] = k[7, 5] = k[7, 11] = k[11, 7] = -6.0 * EIz / L ** 2
        k[5, 5] = k[11, 11] = 4.0 * EIz / L
        k[5, 11] = k[11, 5] = 2.0 * EIz / L

        # Bending about y-axis (local z-displacements, rotations about y)
        k[2, 2] = k[8, 8] = 12.0 * EIy / L ** 3
        k[2, 8] = k[8, 2] = -12.0 * EIy / L ** 3
        k[2, 4] = k[4, 2] = k[2, 10] = k[10, 2] = -6.0 * EIy / L ** 2
        k[4, 8] = k[8, 4] = k[8, 10] = k[10, 8] = 6.0 * EIy / L ** 2
        k[4, 4] = k[10, 10] = 4.0 * EIy / L
        k[4, 10] = k[10, 4] = 2.0 * EIy / L

        return k

    # ------------------------------------------------------------------ #
    #  Coordinate transformation matrix (12x12)                          #
    # ------------------------------------------------------------------ #
    def _transformation_matrix(x1, y1, z1, x2, y2, z2, ref_vec):
        dx, dy, dz = x2 - x1, y2 - y1, z2 - z1
        L = np.sqrt(dx * dx + dy * dy + dz * dz)
        if np.isclose(L, 0.0):
            raise ValueError("Zero-length beam element.")
        ex = np.array([dx, dy, dz]) / L

        if ref_vec is None:
            if np.isclose(ex[0], 0) and np.isclose(ex[1], 0):
                ref_vec = np.array([0.0, 1.0, 0.0])
            else:
                ref_vec = np.array([0.0, 0.0, 1.0])
        else:
            ref_vec = np.asarray(ref_vec, dtype=float)

        ey = np.cross(ref_vec, ex)
        ey /= np.linalg.norm(ey)
        ez = np.cross(ex, ey)

        gamma = np.vstack((ex, ey, ez))  # 3x3
        return np.kron(np.eye(4), gamma)  # 12x12

    # ------------------------------------------------------------------ #
    #  Global elastic stiffness assembly                                 #
    # ------------------------------------------------------------------ #
    def _assemble_global_K(node_coords, elements):
        n_nodes = node_coords.shape[0]
        n_dof = 6 * n_nodes
        K = np.zeros((n_dof, n_dof))
        for ele in elements:
            ni, nj = int(ele["node_i"]), int(ele["node_j"])
            xi, yi, zi = node_coords[ni]
            xj, yj, zj = node_coords[nj]
            L = np.linalg.norm([xj - xi, yj - yi, zj - zi])
            Gamma = _transformation_matrix(
                xi, yi, zi, xj, yj, zj, ele.get("local_z")
            )
            k_loc = _local_elastic_stiffness(
                ele["E"], ele["nu"], ele["A"], L,
                ele["I_y"], ele["I_z"], ele["J"],
            )
            k_glb = Gamma.T @ k_loc @ Gamma
            dofs = list(range(6 * ni, 6 * ni + 6)) + list(
                range(6 * nj, 6 * nj + 6)
            )
            K[np.ix_(dofs, dofs)] += k_glb
        return K

    # ------------------------------------------------------------------ #
    #  Load vector assembly                                              #
    # ------------------------------------------------------------------ #
    def _assemble_load_vector(nodal_loads, n_nodes):
        P = np.zeros(6 * n_nodes)
        for n, load in nodal_loads.items():
            P[6 * n : 6 * n + 6] += np.asarray(load, dtype=float)
        return P

    # ------------------------------------------------------------------ #
    #  DOF partitioning                                                  #
    # ------------------------------------------------------------------ #
    def _partition_dofs(boundary_conditions, n_nodes):
        fixed = []
        for n in range(n_nodes):
            flags = boundary_conditions.get(n)
            if flags is not None:
                fixed.extend(
                    [6 * n + i for i, f in enumerate(flags) if f]
                )
        fixed = np.asarray(fixed, dtype=int)
        free = np.setdiff1d(np.arange(6 * n_nodes), fixed)
        return fixed, free

    # ------------------------------------------------------------------ #
    #  Linear solve                                                      #
    # ------------------------------------------------------------------ #
    def _linear_solve(P, K, fixed, free):
        n_dof = len(fixed) + len(free)
        K_ff = K[np.ix_(free, free)]
        cond = np.linalg.cond(K_ff)
        if cond > 1e16:
            raise ValueError(
                f"Stiffness matrix ill-conditioned (cond={cond:.2e})"
            )
        u_f = np.linalg.solve(K_ff, P[free])
        u = np.zeros(n_dof)
        u[free] = u_f
        return u

    # ------------------------------------------------------------------ #
    #  Per-element internal force recovery (in local coordinates)        #
    # ------------------------------------------------------------------ #
    def _element_local_forces(ele, xi, yi, zi, xj, yj, zj, u_dofs_global):
        L = np.linalg.norm([xj - xi, yj - yi, zj - zi])
        Gamma = _transformation_matrix(
            xi, yi, zi, xj, yj, zj, ele.get("local_z")
        )
        k_loc = _local_elastic_stiffness(
            ele["E"], ele["nu"], ele["A"], L,
            ele["I_y"], ele["I_z"], ele["J"],
        )
        u_local = Gamma @ u_dofs_global
        return k_loc @ u_local

    # ------------------------------------------------------------------ #
    #  Local geometric stiffness matrix (12x12, full torsion-bending)    #
    # ------------------------------------------------------------------ #
    def _local_geometric_stiffness(L, A, I_rho, Fx2, Mx2, My1, Mz1, My2, Mz2):
        k_g = np.zeros((12, 12))

        # Upper-triangle off-diagonal entries
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

        k_g[3, 4] = -(2.0 * Mz1 - Mz2) / 6.0
        k_g[3, 5] = (2.0 * My1 - My2) / 6.0
        k_g[3, 7] = -My1 / L
        k_g[3, 8] = -Mz1 / L
        k_g[3, 9] = -Fx2 * I_rho / (A * L)
        k_g[3, 10] = -(Mz1 + Mz2) / 6.0
        k_g[3, 11] = (My1 + My2) / 6.0

        k_g[4, 7] = -Mx2 / L
        k_g[4, 8] = Fx2 / 10.0
        k_g[4, 9] = -(Mz1 + Mz2) / 6.0
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
        k_g[9, 11] = -(My1 - 2.0 * My2) / 6.0

        # Symmetric lower triangle
        k_g = k_g + k_g.T

        # Diagonal entries
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

    # ------------------------------------------------------------------ #
    #  Global geometric stiffness assembly                               #
    # ------------------------------------------------------------------ #
    def _assemble_global_Kg(node_coords, elements, u_global):
        n_nodes = node_coords.shape[0]
        n_dof = 6 * n_nodes
        Kg = np.zeros((n_dof, n_dof))

        for ele in elements:
            ni = int(ele["node_i"])
            nj = int(ele["node_j"])
            xi, yi, zi = node_coords[ni]
            xj, yj, zj = node_coords[nj]
            dx, dy, dz = xj - xi, yj - yi, zj - zi
            L = float(np.linalg.norm([dx, dy, dz]))
            A = float(ele["A"])
            I_rho = float(ele["I_rho"])

            Gamma = _transformation_matrix(
                xi, yi, zi, xj, yj, zj, ele.get("local_z")
            )
            dofs = list(range(6 * ni, 6 * ni + 6)) + list(
                range(6 * nj, 6 * nj + 6)
            )
            u_e_global = u_global[dofs]

            # Recover local internal forces
            f_local = _element_local_forces(
                ele, xi, yi, zi, xj, yj, zj, u_e_global
            )

            # Extract internal force components for geometric stiffness
            Fx2 = float(f_local[6])
            Mx2 = float(f_local[9])
            My1 = float(f_local[4])
            Mz1 = float(f_local[5])
            My2 = float(f_local[10])
            Mz2 = float(f_local[11])

            k_g_local = _local_geometric_stiffness(
                L, A, I_rho, Fx2, Mx2, My1, Mz1, My2, Mz2
            )
            k_g_global = Gamma.T @ k_g_local @ Gamma

            Kg[np.ix_(dofs, dofs)] += k_g_global

        return Kg

    # ------------------------------------------------------------------ #
    #  Eigenvalue solve                                                  #
    # ------------------------------------------------------------------ #
    def _eigenvalue_solve(K_e, K_g, boundary_conditions, n_nodes):
        c_eps = 1e3 * np.finfo(float).eps

        _, free = _partition_dofs(boundary_conditions, n_nodes)
        free = np.asarray(free, dtype=int)

        K_e_ff = K_e[np.ix_(free, free)]
        K_g_ff = K_g[np.ix_(free, free)]

        # Enforce exact symmetry
        K_e_ff = 0.5 * (K_e_ff + K_e_ff.T)
        K_g_ff = 0.5 * (K_g_ff + K_g_ff.T)

        # Generalized eigenvalue problem: K_e v = lambda (-K_g) v
        eig_vals, eig_vecs = scipy.linalg.eig(
            K_e_ff, -1.0 * K_g_ff, check_finite=False
        )

        if eig_vals.size == 0:
            raise ValueError("Eigensolver returned no eigenvalues.")

        # Realness check
        lam_max = float(np.max(np.abs(eig_vals)))
        rel_imag = np.max(np.abs(np.imag(eig_vals))) / max(lam_max, 1.0)

        if rel_imag <= c_eps:
            # De-phase eigenvectors and discard imaginary parts
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
                f"Complex eigenpairs (rel_imag={rel_imag:.3e})"
            )

        # Select smallest positive eigenvalue
        vals = eig_vals.astype(float, copy=False)
        finite_mask = np.isfinite(vals)
        lam_scale = (
            np.max(np.abs(vals[finite_mask]))
            if np.any(finite_mask)
            else 1.0
        )
        pos_cut = max(1e-12, c_eps * lam_scale)

        cand = np.flatnonzero(finite_mask & (vals > pos_cut))
        if cand.size == 0:
            raise ValueError("No positive buckling eigenvalues found.")

        ix = cand[np.argmin(vals[cand])]
        eig_value = float(vals[ix])
        eig_vec_free = eig_vecs[:, ix].astype(float, copy=False)

        # Embed into full global DOF vector
        n_dof = 6 * n_nodes
        mode = np.zeros(n_dof, dtype=float)
        mode[free] = eig_vec_free

        return eig_value, mode

    # ================================================================== #
    #  Main pipeline                                                     #
    # ================================================================== #
    node_coords = np.asarray(node_coords, dtype=float)
    n_nodes = node_coords.shape[0]

    # 1. Assemble global elastic stiffness
    K = _assemble_global_K(node_coords, elements)

    # 2. Assemble global load vector
    P = _assemble_load_vector(nodal_loads, n_nodes)

    # 3. Partition DOFs
    fixed, free = _partition_dofs(boundary_conditions, n_nodes)

    # 4. Linear static solve
    u = _linear_solve(P, K, fixed, free)

    # 5. Assemble global geometric stiffness
    K_g = _assemble_global_Kg(node_coords, elements, u)

    # 6. Eigenvalue buckling analysis
    lam, mode = _eigenvalue_solve(K, K_g, boundary_conditions, n_nodes)

    return lam, mode
