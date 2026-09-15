"""
DOF partitioning, linear solve, and internal force recovery for 3D frames.
"""
import numpy as np
from typing import Sequence
from .config import NDOF_PER_NODE
from .elastic import transformation_matrix_3d, local_elastic_stiffness_3d


def partition_dofs(boundary_conditions, n_nodes):
    """Partition global DOFs into fixed and free index arrays.

    Parameters
    ----------
    boundary_conditions : dict[int, Sequence[int]]
        Maps node index to 6-element iterable of 0/False (free) or 1/True (fixed).
    n_nodes : int
        Total number of nodes.

    Returns
    -------
    fixed : (n_fixed,) int ndarray
    free  : (n_free,) int ndarray
    """
    n_dof = n_nodes * NDOF_PER_NODE
    fixed = []
    for n in range(n_nodes):
        flags = boundary_conditions.get(n)
        if flags is not None:
            fixed.extend([6 * n + i for i, f in enumerate(flags) if f])
    fixed = np.asarray(fixed, dtype=int)
    free = np.setdiff1d(np.arange(n_dof), fixed, assume_unique=True)
    return fixed, free


def linear_solve(K, P, fixed, free):
    """Solve K*u = P with fixed-DOF constraints.

    Returns
    -------
    u : (n_dof,) ndarray
        Full displacement vector (fixed DOFs are zero).
    reactions : (n_dof,) ndarray
        Reaction forces (non-zero only at fixed DOFs).
    """
    K_ff = K[np.ix_(free, free)]
    K_sf = K[np.ix_(fixed, free)]

    cond = np.linalg.cond(K_ff)
    if cond > 1e16:
        raise ValueError(
            f"Ill-conditioned stiffness matrix (cond={cond:.2e})"
        )

    u_f = np.linalg.solve(K_ff, P[free])
    u = np.zeros(len(fixed) + len(free))
    u[free] = u_f

    reactions = np.zeros(P.shape)
    reactions[fixed] = K_sf @ u_f - P[fixed]
    return u, reactions


def element_internal_forces(ele, node_coords, u_global):
    """Compute internal forces in local coordinates for a single element.

    Parameters
    ----------
    ele : dict
        Element definition with node_i, node_j, E, nu, A, I_y, I_z, J,
        and optionally local_z.
    node_coords : (N, 3) ndarray
        Global node coordinates.
    u_global : (6*N,) ndarray
        Global displacement vector.

    Returns
    -------
    f_local : (12,) ndarray
        Internal forces in local coordinates:
        [Fx1, Fy1, Fz1, Mx1, My1, Mz1, Fx2, Fy2, Fz2, Mx2, My2, Mz2]
    """
    ni, nj = int(ele['node_i']), int(ele['node_j'])
    xi, yi, zi = node_coords[ni]
    xj, yj, zj = node_coords[nj]
    L = np.linalg.norm([xj - xi, yj - yi, zj - zi])

    Gamma = transformation_matrix_3d(xi, yi, zi, xj, yj, zj,
                                     ele.get('local_z'))
    k_loc = local_elastic_stiffness_3d(ele['E'], ele['nu'], ele['A'], L,
                                       ele['I_y'], ele['I_z'], ele['J'])

    dofs = list(range(6 * ni, 6 * ni + 6)) + list(range(6 * nj, 6 * nj + 6))
    u_e_global = u_global[dofs]
    u_e_local = Gamma @ u_e_global
    f_local = k_loc @ u_e_local
    return f_local
