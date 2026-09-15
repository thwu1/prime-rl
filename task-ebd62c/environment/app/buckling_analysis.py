"""
3D Frame Eigenvalue Buckling Analysis

Mixed C/Python implementation. Core matrix operations (elastic stiffness,
coordinate transformation) are in C (/app/libfem_core.so). The stability
analysis pipeline (geometric stiffness, eigenvalue solve) is in Python.

The elastic analysis framework is complete:
  - local_elastic_stiffness_3D  (C library)
  - transformation_matrix_3D    (C library)
  - assemble_elastic_stiffness
  - assemble_load_vector
  - partition_dofs
  - linear_solve

Five functions remain as stubs (NotImplementedError):
  - compute_element_forces
  - local_geometric_stiffness_3D
  - assemble_geometric_stiffness
  - eigenvalue_buckling_solve
  - elastic_critical_load_analysis
"""

import ctypes
import os
import numpy as np
import scipy.linalg
from ctypes import c_double, POINTER
from typing import Sequence


# ---------------------------------------------------------------------------
#  C Library Interface
# ---------------------------------------------------------------------------

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libfem_core.so')
_lib = ctypes.CDLL(_lib_path)

_lib.local_elastic_stiffness_3D_c.argtypes = [
    c_double, c_double, c_double, c_double,
    c_double, c_double, c_double,
    POINTER(c_double),
]
_lib.local_elastic_stiffness_3D_c.restype = None

_lib.transformation_matrix_3D_c.argtypes = [
    c_double, c_double, c_double,
    c_double, c_double, c_double,
    POINTER(c_double),
    POINTER(c_double),
]
_lib.transformation_matrix_3D_c.restype = None


# ---------------------------------------------------------------------------
#  Utility
# ---------------------------------------------------------------------------

def _node_dofs(n: int) -> list[int]:
    """Return the 6 global DOF indices for node n (0-based)."""
    base = 6 * n
    return [base + i for i in range(6)]


# ---------------------------------------------------------------------------
#  Elastic stiffness (via C library)
# ---------------------------------------------------------------------------

def local_elastic_stiffness_3D(E, nu, A, L, Iy, Iz, J):
    """
    12x12 local elastic stiffness matrix for a 3D Euler-Bernoulli beam element.

    DOF order: [u1, v1, w1, thx1, thy1, thz1, u2, v2, w2, thx2, thy2, thz2]
    Local x-axis is along the beam axis from node i to node j.
    """
    k = np.zeros((12, 12), dtype=np.float64, order='C')
    _lib.local_elastic_stiffness_3D_c(
        c_double(E), c_double(nu), c_double(A), c_double(L),
        c_double(Iy), c_double(Iz), c_double(J),
        k.ctypes.data_as(POINTER(c_double)),
    )
    return k


# ---------------------------------------------------------------------------
#  Transformation matrix (via C library)
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
    Gamma = np.zeros((12, 12), dtype=np.float64, order='C')
    _lib.transformation_matrix_3D_c(
        c_double(x1), c_double(y1), c_double(z1),
        c_double(x2), c_double(y2), c_double(z2),
        None,
        Gamma.ctypes.data_as(POINTER(c_double)),
    )
    return Gamma


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


# ===========================================================================
#  STUB FUNCTIONS — implement these
# ===========================================================================

def compute_element_forces(ele, xi, yi, zi, xj, yj, zj, u_dofs_global):
    """
    Compute local element internal forces from global nodal displacements.

    Parameters
    ----------
    ele            : dict with element properties (E, nu, A, I_y, I_z, J, local_z)
    xi, yi, zi     : coordinates of node i
    xj, yj, zj     : coordinates of node j
    u_dofs_global  : (12,) array of global DOF values for this element's nodes

    Returns
    -------
    (12,) array of local internal forces:
        [Fx1, Fy1, Fz1, Mx1, My1, Mz1, Fx2, Fy2, Fz2, Mx2, My2, Mz2]
    """
    raise NotImplementedError(
        "Implement element force recovery. See SPECIFICATION.md sections 3-4."
    )


def local_geometric_stiffness_3D(L, A, I_rho, Fx2, Mx2, My1, Mz1, My2, Mz2):
    """
    Build the 12x12 local geometric stiffness matrix for a 3D Euler-Bernoulli
    beam element with full torsion-bending coupling.

    Parameters
    ----------
    L      : element length
    A      : cross-sectional area
    I_rho  : polar moment of inertia about the centroidal axis
    Fx2    : axial force at node 2 (positive = tension)
    Mx2    : torsional moment at node 2 about local x-axis
    My1    : bending moment at node 1 about local y-axis
    Mz1    : bending moment at node 1 about local z-axis
    My2    : bending moment at node 2 about local y-axis
    Mz2    : bending moment at node 2 about local z-axis

    Returns
    -------
    (12, 12) symmetric ndarray — geometric stiffness in local coordinates.

    Notes
    -----
    See /app/SPECIFICATION.md section 5 for the mathematical derivation.
    """
    raise NotImplementedError(
        "Implement the geometric stiffness matrix. See SPECIFICATION.md section 5."
    )


def assemble_geometric_stiffness(node_coords, elements, u_global):
    """
    Assemble the global geometric stiffness matrix from the displacement state.

    Parameters
    ----------
    node_coords : (N, 3) array of node coordinates
    elements    : list of element dicts (must include 'I_rho' in addition
                  to standard elastic properties)
    u_global    : (6N,) global displacement vector from linear solve

    Returns
    -------
    (6N, 6N) global geometric stiffness matrix
    """
    raise NotImplementedError(
        "Implement global geometric stiffness assembly. See SPECIFICATION.md section 7."
    )


def eigenvalue_buckling_solve(K_e_global, K_g_global, boundary_conditions, n_nodes):
    """
    Solve the generalized eigenproblem for buckling.

    Parameters
    ----------
    K_e_global          : (6N, 6N) global elastic stiffness matrix
    K_g_global          : (6N, 6N) global geometric stiffness matrix
    boundary_conditions : dict of node BC flags
    n_nodes             : total number of nodes

    Returns
    -------
    (critical_load_factor, mode_shape) — mode_shape has constrained DOFs = 0
    """
    raise NotImplementedError(
        "Implement eigenvalue buckling solve. See SPECIFICATION.md section 6."
    )


def elastic_critical_load_analysis(
    node_coords: np.ndarray,
    elements: Sequence[dict],
    boundary_conditions: dict,
    nodal_loads: dict,
):
    """
    Perform complete buckling analysis for a 3D beam-column frame.

    Parameters
    ----------
    node_coords         : (N, 3) array of node coordinates
    elements            : list of element dicts with keys:
                          node_i, node_j, E, nu, A, I_y, I_z, J, I_rho, local_z
    boundary_conditions : dict mapping node index to 6-element BC flags
    nodal_loads         : dict mapping node index to 6-element load vector

    Returns
    -------
    (critical_load_factor, mode_shape)
    """
    raise NotImplementedError(
        "Implement the complete analysis pipeline."
    )
