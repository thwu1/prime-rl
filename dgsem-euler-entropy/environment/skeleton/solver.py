"""
DGSEM solver: element-level operations and spatial semi-discretization.

The solver uses nodal DG with Legendre-Gauss-Lobatto nodes and supports
flux-differencing (split-form) volume integrals for entropy stability.
"""

import numpy as np
from .basis import lgl_nodes_weights, derivative_matrix
from .euler import (euler_flux, lax_friedrichs_flux, chandrashekar_flux,
                    max_wave_speed, GAMMA)


class DGSolver:
    """1D DGSEM solver for systems of conservation laws.

    Attributes
    ----------
    N : int
        Polynomial degree.
    n_nodes : int
        Number of nodes per element (N+1).
    nodes : np.ndarray
        Reference LGL nodes on [-1, 1].
    weights : np.ndarray
        LGL quadrature weights.
    D : np.ndarray
        Derivative matrix on reference element.
    """

    def __init__(self, N):
        self.N = N
        self.n_nodes = N + 1
        self.nodes, self.weights = lgl_nodes_weights(N)
        self.D = derivative_matrix(self.nodes)


class Mesh1D:
    """Simple 1D mesh of uniform elements.

    Attributes
    ----------
    x_min, x_max : float
        Domain bounds.
    n_elements : int
        Number of elements.
    dx : float
        Element width (uniform).
    periodic : bool
        Whether boundary conditions are periodic.
    """

    def __init__(self, x_min, x_max, n_elements, periodic=False):
        self.x_min = x_min
        self.x_max = x_max
        self.n_elements = n_elements
        self.dx = (x_max - x_min) / n_elements
        self.periodic = periodic

    def element_bounds(self, e):
        """Return (x_left, x_right) for element e."""
        x_left = self.x_min + e * self.dx
        return x_left, x_left + self.dx

    def physical_nodes(self, e, ref_nodes):
        """Map reference nodes [-1,1] to physical coordinates in element e."""
        x_l, x_r = self.element_bounds(e)
        return 0.5 * (x_l + x_r) + 0.5 * self.dx * ref_nodes


def compute_rhs_flux_differencing(U_all, solver, mesh, surface_flux_func, volume_flux_func):
    """Compute the spatial semi-discretization dU/dt using flux-differencing DG.

    This implements the split-form DG operator where the volume integral uses
    a two-point flux function instead of the standard divergence form.

    Parameters
    ----------
    U_all : np.ndarray, shape (n_elements, 3, n_nodes)
        Solution array. U_all[e, :, i] are the 3 conserved variables
        at node i of element e.
    solver : DGSolver
        The DG solver with precomputed basis data.
    mesh : Mesh1D
        The computational mesh.
    surface_flux_func : callable
        Numerical flux function for element interfaces: f(U_L, U_R) -> F.
    volume_flux_func : callable
        Two-point flux function for volume integral: f(U_L, U_R) -> F.

    Returns
    -------
    dUdt : np.ndarray, same shape as U_all
        Time derivative of the solution.

    TODO: Implement the flux-differencing volume integral and surface terms.

    The algorithm for each element e:
    1. Compute the volume integral contribution using the two-point flux:
       For each node i, compute:
         vol_i = (2/dx) * sum_j D[i,j] * volume_flux_func(U[:,i], U[:,j])
       Note: the factor 2/dx accounts for the Jacobian from reference to physical.

    2. Compute surface flux contributions:
       - Left boundary: F_L = surface_flux_func(U_neighbor_right, U_e_left)
       - Right boundary: F_R = surface_flux_func(U_e_right, U_neighbor_left)
       For non-periodic boundaries, use the element's own boundary state
       as the neighbor state (reflecting).

    3. Apply surface terms:
       dUdt[e, :, 0]  -= (1/w_0) * (2/dx) * (F_surf_left - euler_flux(U[:,0]))  ... wait
       Actually: The surface contribution in nodal DG with LGL nodes (where
       boundary nodes coincide with element interfaces) is:
         dUdt[:,0]  += -(2/dx) * (1/w_0) * (F_num_left - F_phys_left)  ... no

       Use the standard formulation:
         dUdt[:,i] = -(2/dx) * [ sum_j D[i,j]*F_vol(U_i,U_j)
                                 + (1/w_i)*(F_surf_right*delta_{i,N} - F_surf_left*delta_{i,0}) ]
       But with the split-form correction. The correct formulation is:

         dUdt[:,i] = -(2/dx) / w_i * [
             sum_j  2*D[i,j]*w_j * volume_flux_func(U_i, U_j)
             + (F_surf_left if i==0 else 0) * (-1)
             + (F_surf_right if i==N else 0) * (+1)
             - f(U_i) * (delta_{i,N} - delta_{i,0})
         ]

       Hmm, this is getting complicated. Here is the precise formulation:

       Let Q = M * D where M = diag(weights). The split-form volume operator is:
         (M * dUdt_vol)_i = -2 * sum_j Q[i,j] * f_vol(U_i, U_j)

       Then add surface terms using the numerical flux:
         (M * dUdt)_i = (M * dUdt_vol)_i
                        - [f_surf_R - f(U_N)] * delta_{i,N}
                        + [f_surf_L - f(U_0)] * delta_{i,0}

       Then dUdt_i = (M * dUdt)_i / w_i, and multiply by 2/dx for the Jacobian.

    This is the most challenging part of the implementation. You need to get
    the signs and scaling exactly right.
    """
    raise NotImplementedError("Flux-differencing RHS computation not implemented")


def compute_max_dt(U_all, solver, mesh, cfl):
    """Compute the maximum stable time step based on CFL condition.

    Parameters
    ----------
    U_all : np.ndarray, shape (n_elements, 3, n_nodes)
    solver : DGSolver
    mesh : Mesh1D
    cfl : float

    Returns
    -------
    dt : float
    """
    max_speed = 0.0
    for e in range(mesh.n_elements):
        for i in range(solver.n_nodes):
            speed = max_wave_speed(U_all[e, :, i])
            if speed > max_speed:
                max_speed = speed
    # DG CFL restriction includes factor of 1/(2N+1)
    return cfl * mesh.dx / (max_speed * (2 * solver.N + 1))
