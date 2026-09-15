"""
3D Frame Eigenvalue Buckling Analysis — Complete Implementation

Implements linear (eigenvalue) buckling analysis for 3D Euler-Bernoulli
beam-column frames. The pipeline:
  1) Assembles the global elastic stiffness matrix K
  2) Assembles the global load vector P
  3) Solves K u = P for the reference displacement state
  4) Recovers element internal forces from u
  5) Assembles the global geometric stiffness matrix K_g
  6) Solves the generalized eigenproblem K phi = -lambda K_g phi
  7) Returns the smallest positive eigenvalue lambda (critical load factor)
     and the corresponding buckling mode shape phi

The geometric stiffness matrix includes full torsion-bending coupling:
  - P-delta/P-theta terms from axial force (Hermite shape function integrals)
  - Torsion-bending coupling from Mx2
  - Moment-displacement and moment-rotation coupling from My1, Mz1, My2, Mz2
"""

import numpy as np
import scipy.linalg
from typing import Optional, Sequence


# ---------------------------------------------------------------------------
#  Utility
# ---------------------------------------------------------------------------

def _node_dofs(n: int) -> list[int]:
    """Return the 6 global DOF indices for node n (0-based)."""
    base = 6 * n
    return [base + i for i in range(6)]


# ---------------------------------------------------------------------------
#  Elastic stiffness
# ---------------------------------------------------------------------------

def local_elastic_stiffness_3D(E, nu, A, L, Iy, Iz, J):
    """
    12x12 local elastic stiffness matrix for a 3D Euler-Bernoulli beam element.

    DOF order: [u1, v1, w1, thx1, thy1, thz1, u2, v2, w2, thx2, thy2, thz2]
    Local x-axis is along the beam axis from node i to node j.
    """
    k = np.zeros((12, 12))
    EA_L = E * A / L
    GJ_L = E * J / (2.0 * (1.0 + nu) * L)
    EIz = E * Iz
    EIy = E * Iy

    # Axial (local x)
    k[0, 0] = k[6, 6] = EA_L
    k[0, 6] = k[6, 0] = -EA_L

    # Torsion (about local x)
    k[3, 3] = k[9, 9] = GJ_L
    k[3, 9] = k[9, 3] = -GJ_L

    # Bending about z-axis (v-displacement, thz-rotation)
    k[1, 1] = k[7, 7] = 12.0 * EIz / L**3
    k[1, 7] = k[7, 1] = -12.0 * EIz / L**3
    k[1, 5] = k[5, 1] = k[1, 11] = k[11, 1] = 6.0 * EIz / L**2
    k[5, 7] = k[7, 5] = k[7, 11] = k[11, 7] = -6.0 * EIz / L**2
    k[5, 5] = k[11, 11] = 4.0 * EIz / L
    k[5, 11] = k[11, 5] = 2.0 * EIz / L

    # Bending about y-axis (w-displacement, thy-rotation)
    k[2, 2] = k[8, 8] = 12.0 * EIy / L**3
    k[2, 8] = k[8, 2] = -12.0 * EIy / L**3
    k[2, 4] = k[4, 2] = k[2, 10] = k[10, 2] = -6.0 * EIy / L**2
    k[4, 8] = k[8, 4] = k[8, 10] = k[10, 8] = 6.0 * EIy / L**2
    k[4, 4] = k[10, 10] = 4.0 * EIy / L
    k[4, 10] = k[10, 4] = 2.0 * EIy / L

    return k


# ---------------------------------------------------------------------------
#  Transformation matrix
# ---------------------------------------------------------------------------

def transformation_matrix_3D(x1, y1, z1, x2, y2, z2, ref_vec=None):
    """
    12x12 transformation matrix Gamma for a 3D beam element.

    Maps local DOFs to global DOFs:  u_global = Gamma^T u_local
    Stiffness transformation:        K_global = Gamma^T K_local Gamma
    Inverse (global to local):       u_local  = Gamma  u_global

    The local x-axis points from node 1 to node 2.
    The local y-axis is defined by cross(ref_vec, local_x).
    The local z-axis completes the right-hand triad.
    """
    dx, dy, dz = x2 - x1, y2 - y1, z2 - z1
    L = np.sqrt(dx * dx + dy * dy + dz * dz)
    if np.isclose(L, 0.0):
        raise ValueError("Zero-length beam element.")

    ex = np.array([dx, dy, dz]) / L

    if ref_vec is None:
        if not (np.isclose(ex[0], 0) and np.isclose(ex[1], 0)):
            ref_vec = np.array([0.0, 0.0, 1.0])
        else:
            ref_vec = np.array([0.0, 1.0, 0.0])
    else:
        ref_vec = np.asarray(ref_vec, dtype=float)
        if not np.isclose(np.linalg.norm(ref_vec), 1.0):
            raise ValueError("Reference vector must be unit length.")
        if np.isclose(np.linalg.norm(np.cross(ref_vec, ex)), 0.0):
            raise ValueError("Reference vector parallel to beam axis.")

    ey = np.cross(ref_vec, ex)
    ey /= np.linalg.norm(ey)
    ez = np.cross(ex, ey)

    gamma = np.vstack((ex, ey, ez))
    return np.kron(np.eye(4), gamma)


# ---------------------------------------------------------------------------
#  Global elastic assembly
# ---------------------------------------------------------------------------

def assemble_elastic_stiffness(node_coords, elements):
    """Assemble global elastic stiffness matrix from element contributions."""
    n_nodes = node_coords.shape[0]
    n_dof = 6 * n_nodes
    K = np.zeros((n_dof, n_dof))

    for ele in elements:
        ni, nj = int(ele['node_i']), int(ele['node_j'])
        xi, yi, zi = node_coords[ni]
        xj, yj, zj = node_coords[nj]
        L = np.linalg.norm([xj - xi, yj - yi, zj - zi])

        Gamma = transformation_matrix_3D(
            xi, yi, zi, xj, yj, zj, ele.get('local_z')
        )
        k_loc = local_elastic_stiffness_3D(
            ele['E'], ele['nu'], ele['A'], L,
            ele['I_y'], ele['I_z'], ele['J']
        )
        k_glb = Gamma.T @ k_loc @ Gamma

        dofs = _node_dofs(ni) + _node_dofs(nj)
        K[np.ix_(dofs, dofs)] += k_glb

    return K


def assemble_load_vector(nodal_loads, n_nodes):
    """Assemble global load vector from nodal loads."""
    n_dof = 6 * n_nodes
    P = np.zeros(n_dof)
    for n, load in nodal_loads.items():
        P[_node_dofs(n)] += np.asarray(load, dtype=float)
    return P


# ---------------------------------------------------------------------------
#  DOF partitioning and linear solve
# ---------------------------------------------------------------------------

def partition_dofs(boundary_conditions, n_nodes):
    """Partition DOFs into fixed and free sets based on boundary conditions."""
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
    """Solve the linear system K u = P with imposed boundary conditions."""
    n_dof = len(fixed) + len(free)
    K_ff = K_global[np.ix_(free, free)]
    K_sf = K_global[np.ix_(fixed, free)]

    cond = np.linalg.cond(K_ff)
    if cond > 1e16:
        raise ValueError(
            f"Stiffness matrix is ill-conditioned (cond={cond:.2e})"
        )

    u_f = np.linalg.solve(K_ff, P_global[free])
    u = np.zeros(n_dof)
    u[free] = u_f

    reactions = np.zeros(P_global.shape)
    reactions[fixed] = K_sf @ u_f - P_global[fixed]

    return u, reactions


# ---------------------------------------------------------------------------
#  Force recovery
# ---------------------------------------------------------------------------

def compute_element_forces(ele, xi, yi, zi, xj, yj, zj, u_dofs_global):
    """
    Compute local element internal forces from global nodal displacements.

    Key: u_local = Gamma @ u_global (Gamma maps global -> local because
    gamma rows are local axes expressed in global coordinates).

    Returns [Fx1, Fy1, Fz1, Mx1, My1, Mz1, Fx2, Fy2, Fz2, Mx2, My2, Mz2]
    """
    L = np.linalg.norm([xj - xi, yj - yi, zj - zi])

    Gamma = transformation_matrix_3D(
        xi, yi, zi, xj, yj, zj, ele.get('local_z')
    )
    k_local = local_elastic_stiffness_3D(
        ele['E'], ele['nu'], ele['A'], L,
        ele['I_y'], ele['I_z'], ele['J']
    )

    # Global to local transformation (Gamma, NOT Gamma.T)
    u_local = Gamma @ u_dofs_global
    return k_local @ u_local


# ---------------------------------------------------------------------------
#  Geometric stiffness matrix
# ---------------------------------------------------------------------------

def local_geometric_stiffness_3D(L, A, I_rho, Fx2, Mx2, My1, Mz1, My2, Mz2):
    """
    12x12 local geometric stiffness matrix for a 3D Euler-Bernoulli beam
    with full torsion-bending coupling.

    Derived from consistent formulation using Hermite cubic shape functions.
    The P-delta terms arise from integrals of shape function derivatives:
        k_g[i,j] = Fx2 * integral_0^L (dPhi_i/dx)(dPhi_j/dx) dx
    where Phi_i are the bending shape functions with sign conventions:
        v(xi) = v1*N1 + thz1*N2 + v2*N3 + thz2*N4     (z-bending)
        w(xi) = w1*N1 - thy1*N2 + w2*N3 - thy2*N4      (y-bending)

    Evaluated shape function derivative integrals yield coefficients:
        6/(5L) for displacement-displacement diagonal
        1/10   for displacement-rotation coupling
        2L/15  for rotation-rotation diagonal
        -L/30  for rotation-rotation off-diagonal
    """
    k_g = np.zeros((12, 12))

    # ---- Upper triangle off-diagonal terms ----

    # Axial coupling
    k_g[0, 6] = -Fx2 / L

    # v-plane P-delta + torsion-bending + moment coupling (row 1: v1)
    k_g[1, 3] = My1 / L
    k_g[1, 4] = Mx2 / L
    k_g[1, 5] = Fx2 / 10.0
    k_g[1, 7] = -6.0 * Fx2 / (5.0 * L)
    k_g[1, 9] = My2 / L
    k_g[1, 10] = -Mx2 / L
    k_g[1, 11] = Fx2 / 10.0

    # w-plane P-delta + torsion-bending + moment coupling (row 2: w1)
    k_g[2, 3] = Mz1 / L
    k_g[2, 4] = -Fx2 / 10.0
    k_g[2, 5] = Mx2 / L
    k_g[2, 8] = -6.0 * Fx2 / (5.0 * L)
    k_g[2, 9] = Mz2 / L
    k_g[2, 10] = -Fx2 / 10.0
    k_g[2, 11] = -Mx2 / L

    # Torsion-moment coupling (row 3: thx1)
    k_g[3, 4] = -(2.0 * Mz1 - Mz2) / 6.0
    k_g[3, 5] = (2.0 * My1 - My2) / 6.0
    k_g[3, 7] = -My1 / L
    k_g[3, 8] = -Mz1 / L
    k_g[3, 9] = -Fx2 * I_rho / (A * L)
    k_g[3, 10] = -(Mz1 + Mz2) / 6.0
    k_g[3, 11] = (My1 + My2) / 6.0

    # w-plane rotation coupling (row 4: thy1)
    k_g[4, 7] = -Mx2 / L
    k_g[4, 8] = Fx2 / 10.0
    k_g[4, 9] = -(Mz1 + Mz2) / 6.0
    k_g[4, 10] = -Fx2 * L / 30.0
    k_g[4, 11] = Mx2 / 2.0

    # v-plane rotation coupling (row 5: thz1)
    k_g[5, 7] = -Fx2 / 10.0
    k_g[5, 8] = -Mx2 / L
    k_g[5, 9] = (My1 + My2) / 6.0
    k_g[5, 10] = -Mx2 / 2.0
    k_g[5, 11] = -Fx2 * L / 30.0

    # v-plane node 2 coupling (row 7: v2)
    k_g[7, 9] = -My2 / L
    k_g[7, 10] = Mx2 / L
    k_g[7, 11] = -Fx2 / 10.0

    # w-plane node 2 coupling (row 8: w2)
    k_g[8, 9] = -Mz2 / L
    k_g[8, 10] = Fx2 / 10.0
    k_g[8, 11] = Mx2 / L

    # Torsion-moment coupling at node 2 (row 9: thx2)
    k_g[9, 10] = (Mz1 - 2.0 * Mz2) / 6.0
    k_g[9, 11] = -(My1 - 2.0 * My2) / 6.0

    # ---- Symmetrize ----
    k_g = k_g + k_g.T

    # ---- Diagonal terms ----
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


# ---------------------------------------------------------------------------
#  Global geometric stiffness assembly
# ---------------------------------------------------------------------------

def assemble_geometric_stiffness(node_coords, elements, u_global):
    """
    Assemble global geometric stiffness matrix from the displacement state.

    For each element: recover local internal forces, build the local geometric
    stiffness matrix, transform to global coordinates, and assemble.
    """
    node_coords = np.asarray(node_coords, dtype=float)
    u_global = np.asarray(u_global, dtype=float)
    n_nodes = node_coords.shape[0]
    n_dof = 6 * n_nodes
    K_g = np.zeros((n_dof, n_dof), dtype=float)

    for ele in elements:
        ni = int(ele['node_i'])
        nj = int(ele['node_j'])
        xi, yi, zi = node_coords[ni]
        xj, yj, zj = node_coords[nj]
        L = float(np.linalg.norm([xj - xi, yj - yi, zj - zi]))
        A = float(ele['A'])
        I_rho = float(ele['I_rho'])

        Gamma = transformation_matrix_3D(
            xi, yi, zi, xj, yj, zj, ele.get('local_z')
        )

        dofs = _node_dofs(ni) + _node_dofs(nj)
        u_e_global = u_global[dofs]

        # Recover local internal forces
        load_local = compute_element_forces(
            ele, xi, yi, zi, xj, yj, zj, u_e_global
        )

        # Extract the six internal force components used by K_g
        Fx2 = float(load_local[6])
        Mx2 = float(load_local[9])
        My1 = float(load_local[4])
        Mz1 = float(load_local[5])
        My2 = float(load_local[10])
        Mz2 = float(load_local[11])

        # Build local geometric stiffness and transform to global
        k_g_local = local_geometric_stiffness_3D(
            L, A, I_rho, Fx2, Mx2, My1, Mz1, My2, Mz2
        )
        k_g_global = Gamma.T @ k_g_local @ Gamma
        K_g[np.ix_(dofs, dofs)] += k_g_global

    return K_g


# ---------------------------------------------------------------------------
#  Eigenvalue buckling solve
# ---------------------------------------------------------------------------

def eigenvalue_buckling_solve(K_e_global, K_g_global, boundary_conditions, n_nodes):
    """
    Solve the generalized eigenproblem K_e phi = -lambda K_g phi for buckling.

    Returns the smallest positive eigenvalue (critical load factor) and
    the corresponding global mode shape vector with constrained DOFs = 0.
    """
    c_eps = 1e3 * np.finfo(float).eps  # ~2e-13 in double precision

    # Partition DOFs
    _, free = partition_dofs(boundary_conditions, n_nodes)
    free = np.asarray(free, dtype=int)

    # Extract free-free blocks
    K_e_ff = K_e_global[np.ix_(free, free)]
    K_g_ff = K_g_global[np.ix_(free, free)]

    # Enforce symmetry (numerical round-off correction)
    K_e_ff = 0.5 * (K_e_ff + K_e_ff.T)
    K_g_ff = 0.5 * (K_g_ff + K_g_ff.T)

    # Conditioning checks
    cond_e = np.linalg.cond(K_e_ff)
    if not np.isfinite(cond_e) or cond_e > 1e16:
        raise ValueError(
            f"Elastic stiffness ill-conditioned (cond={cond_e:.3e})"
        )

    cond_g = np.linalg.cond(K_g_ff)
    if not np.isfinite(cond_g) or cond_g > 1e16:
        raise ValueError(
            f"Geometric stiffness ill-conditioned (cond={cond_g:.3e})"
        )

    # Generalized eigenvalue problem: K_e phi = -lambda K_g phi
    eig_vals, eig_vecs = scipy.linalg.eig(
        K_e_ff, -1.0 * K_g_ff, check_finite=False
    )

    if eig_vals.size == 0:
        raise ValueError("Eigenvalue solver returned no eigenvalues.")

    # Robust realness check: compare imaginary magnitude to overall scale
    lam_max = float(np.max(np.abs(eig_vals)))
    rel_imag = np.max(np.abs(np.imag(eig_vals))) / max(lam_max, 1.0)

    if rel_imag <= c_eps:
        # De-phase eigenvectors and take real parts
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
            f"Complex eigenpairs detected (rel_imag={rel_imag:.3e})"
        )

    # Select smallest positive eigenvalue (scale-aware threshold)
    vals = eig_vals.astype(float, copy=False)
    finite_mask = np.isfinite(vals)
    lam_scale = np.max(np.abs(vals[finite_mask])) if np.any(finite_mask) else 1.0
    pos_cut = max(1e-12, c_eps * lam_scale)

    candidates = np.flatnonzero(finite_mask & (vals > pos_cut))
    if candidates.size == 0:
        raise ValueError("No positive buckling load factors found.")

    ix = candidates[np.argmin(vals[candidates])]
    critical_load_factor = float(vals[ix])
    mode_free = eig_vecs[:, ix].astype(float, copy=False)

    # Embed into full global DOF vector
    num_dofs = 6 * n_nodes
    mode = np.zeros(num_dofs, dtype=float)
    mode[free] = mode_free

    return critical_load_factor, mode


# ---------------------------------------------------------------------------
#  Main pipeline
# ---------------------------------------------------------------------------

def elastic_critical_load_analysis(
    node_coords: np.ndarray,
    elements: Sequence[dict],
    boundary_conditions: dict,
    nodal_loads: dict,
):
    """
    Perform complete eigenvalue buckling analysis for a 3D beam-column frame.

    Parameters:
        node_coords         : (N, 3) array of node coordinates
        elements            : list of element dicts with keys:
                              node_i, node_j, E, nu, A, I_y, I_z, J, I_rho, local_z
        boundary_conditions : dict mapping node index to 6-element BC flags
        nodal_loads         : dict mapping node index to 6-element load vector

    Returns:
        (critical_load_factor, mode_shape)
    """
    n_nodes = node_coords.shape[0]

    # Step 1: Assemble global elastic stiffness
    K = assemble_elastic_stiffness(node_coords, elements)

    # Step 2: Assemble global load vector
    P = assemble_load_vector(nodal_loads, n_nodes)

    # Step 3: Solve linear static problem
    fixed, free = partition_dofs(boundary_conditions, n_nodes)
    u_global, _ = linear_solve(P, K, fixed, free)

    # Step 4: Assemble geometric stiffness from displacement state
    K_g = assemble_geometric_stiffness(node_coords, elements, u_global)

    # Step 5: Solve eigenvalue buckling problem
    lam, mode = eigenvalue_buckling_solve(K, K_g, boundary_conditions, n_nodes)

    return lam, mode
