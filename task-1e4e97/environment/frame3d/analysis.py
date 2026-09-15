"""
Complete elastic critical load analysis pipeline for 3D frames.
"""
import numpy as np
from typing import Sequence
from .elastic import assemble_global_elastic_stiffness, assemble_load_vector
from .solve import partition_dofs, linear_solve
from .buckling import (
    assemble_global_geometric_stiffness,
    eigenvalue_buckling_solve,
)


def elastic_critical_load(node_coords, elements, boundary_conditions, nodal_loads):
    """
    Perform complete eigenvalue buckling analysis for a 3D frame.

    Parameters
    ----------
    node_coords : (N, 3) ndarray
        Global coordinates of N nodes.
    elements : sequence of dict
        Element definitions with keys: node_i, node_j, E, nu, A, I_y,
        I_z, J, I_rho, and optionally local_z.
    boundary_conditions : dict[int, Sequence]
        Maps node index to 6-element fixity flags.
    nodal_loads : dict[int, Sequence[float]]
        Maps node index to [Fx, Fy, Fz, Mx, My, Mz].

    Returns
    -------
    critical_load_factor : float
        Smallest positive eigenvalue lambda.
    mode_shape : (6*N,) ndarray
        Buckling mode shape vector.
    """
    n_nodes = node_coords.shape[0]

    # Step 1: Elastic stiffness
    K = assemble_global_elastic_stiffness(node_coords, elements)

    # Step 2: Load vector
    P = assemble_load_vector(nodal_loads, n_nodes)

    # Step 3: Linear static solve
    fixed, free = partition_dofs(boundary_conditions, n_nodes)
    u_global, _ = linear_solve(K, P, fixed, free)

    # Step 4: Geometric stiffness from displacement state
    K_g = assemble_global_geometric_stiffness(node_coords, elements, u_global)

    # Step 5: Eigenvalue buckling analysis
    lam, mode = eigenvalue_buckling_solve(K, K_g, boundary_conditions, n_nodes)

    return lam, mode
