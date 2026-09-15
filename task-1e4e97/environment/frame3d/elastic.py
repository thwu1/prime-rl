"""
Elastic stiffness and coordinate transformation for 3D Euler-Bernoulli beam elements.

DOF order per node: [ux, uy, uz, theta_x, theta_y, theta_z]
Local x-axis runs along the beam from node i to node j.
"""
import numpy as np
from typing import Optional, Sequence
from .config import NDOF_PER_NODE


def local_elastic_stiffness_3d(E, nu, A, L, Iy, Iz, J):
    """Build the 12x12 local elastic stiffness matrix for a 3D beam element."""
    k = np.zeros((12, 12))
    EA_L = E * A / L
    GJ_L = E * J / (2.0 * (1.0 + nu) * L)
    EIz = E * Iz
    EIy = E * Iy

    # Axial (ux)
    k[0, 0] = k[6, 6] = EA_L
    k[0, 6] = k[6, 0] = -EA_L

    # Torsion (theta_x)
    k[3, 3] = k[9, 9] = GJ_L
    k[3, 9] = k[9, 3] = -GJ_L

    # Bending about z-axis (uy displacements, theta_z rotations)
    k[1, 1] = k[7, 7] = 12.0 * EIz / L**3
    k[1, 7] = k[7, 1] = -12.0 * EIz / L**3
    k[1, 5] = k[5, 1] = k[1, 11] = k[11, 1] = 6.0 * EIz / L**2
    k[5, 7] = k[7, 5] = k[7, 11] = k[11, 7] = -6.0 * EIz / L**2
    k[5, 5] = k[11, 11] = 4.0 * EIz / L
    k[5, 11] = k[11, 5] = 2.0 * EIz / L

    # Bending about y-axis (uz displacements, theta_y rotations)
    k[2, 2] = k[8, 8] = 12.0 * EIy / L**3
    k[2, 8] = k[8, 2] = -12.0 * EIy / L**3
    k[2, 4] = k[4, 2] = k[2, 10] = k[10, 2] = -6.0 * EIy / L**2
    k[4, 8] = k[8, 4] = k[8, 10] = k[10, 8] = 6.0 * EIy / L**2
    k[4, 4] = k[10, 10] = 4.0 * EIy / L
    k[4, 10] = k[10, 4] = 2.0 * EIy / L

    return k


def transformation_matrix_3d(x1, y1, z1, x2, y2, z2, ref_vec=None):
    """Compute the 12x12 local-to-global transformation matrix for a 3D beam.

    Parameters
    ----------
    x1, y1, z1 : float
        Start node coordinates.
    x2, y2, z2 : float
        End node coordinates.
    ref_vec : (3,) array-like or None
        Unit vector defining local z-axis orientation. If None, defaults to
        global z unless beam is along global z, then uses global y.

    Returns
    -------
    Gamma : (12, 12) ndarray
        Transformation matrix composed of four 3x3 direction cosine blocks.
    """
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

    gamma = np.vstack((ex, ey, ez))
    return np.kron(np.eye(4), gamma)


def assemble_global_elastic_stiffness(node_coords, elements):
    """Assemble the global elastic stiffness matrix for the frame."""
    n_nodes = node_coords.shape[0]
    n_dof = NDOF_PER_NODE * n_nodes
    K = np.zeros((n_dof, n_dof))

    for ele in elements:
        ni, nj = int(ele['node_i']), int(ele['node_j'])
        xi, yi, zi = node_coords[ni]
        xj, yj, zj = node_coords[nj]
        L = np.linalg.norm([xj - xi, yj - yi, zj - zi])

        Gamma = transformation_matrix_3d(xi, yi, zi, xj, yj, zj,
                                         ele.get('local_z'))
        k_loc = local_elastic_stiffness_3d(ele['E'], ele['nu'], ele['A'], L,
                                           ele['I_y'], ele['I_z'], ele['J'])
        k_glb = Gamma.T @ k_loc @ Gamma

        dofs = list(range(6 * ni, 6 * ni + 6)) + list(range(6 * nj, 6 * nj + 6))
        K[np.ix_(dofs, dofs)] += k_glb

    return K


def assemble_load_vector(nodal_loads, n_nodes):
    """Assemble the global load vector from nodal loads."""
    n_dof = NDOF_PER_NODE * n_nodes
    P = np.zeros(n_dof)
    for n, load in nodal_loads.items():
        dofs = list(range(6 * n, 6 * n + 6))
        P[dofs] += np.asarray(load, dtype=float)
    return P
