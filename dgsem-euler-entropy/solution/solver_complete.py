"""

DGSEM solver: element-level operations and spatial semi-discretization
using flux-differencing (split-form) volume integrals.
"""

import numpy as np
from .basis import lgl_nodes_weights, derivative_matrix
from .euler import (euler_flux, lax_friedrichs_flux, chandrashekar_flux,
                    max_wave_speed, GAMMA)


class DGSolver:
    """1D DGSEM solver with precomputed LGL nodes, weights, and derivative matrix."""

    def __init__(self, N):
        self.N = N
        self.n_nodes = N + 1
        self.nodes, self.weights = lgl_nodes_weights(N)
        self.D = derivative_matrix(self.nodes)


class Mesh1D:
    """Simple 1D mesh of uniform elements."""

    def __init__(self, x_min, x_max, n_elements, periodic=False):
        self.x_min = x_min
        self.x_max = x_max
        self.n_elements = n_elements
        self.dx = (x_max - x_min) / n_elements
        self.periodic = periodic

    def element_bounds(self, e):
        x_left = self.x_min + e * self.dx
        return x_left, x_left + self.dx

    def physical_nodes(self, e, ref_nodes):
        x_l, x_r = self.element_bounds(e)
        return 0.5 * (x_l + x_r) + 0.5 * self.dx * ref_nodes


def compute_rhs_flux_differencing(U_all, solver, mesh, surface_flux_func, volume_flux_func):
    """Compute dU/dt using strong-form flux-differencing DG.

    The strong-form DG with SBP-SAT for du/dt + df/dx = 0:

        w_i * du/dt_i = -(1/J) * [2*sum_j Q_{ij}*f_vol(U_i,U_j)
                                   + delta_{i,N}*(f*_R - f(U_N))
                                   - delta_{i,0}*(f*_L - f(U_0))]

    Dividing by w_i and with Jacobian factor 2/dx:

        du/dt_i = -(2/dx) * [2*sum_j D_{ij}*f_vol(U_i,U_j)
                              + delta_{i,N}*(f*_R - f(U_N))/w_N
                              - delta_{i,0}*(f*_L - f(U_0))/w_0]

    Rearranging:

        du/dt_i = (2/dx) * [-2*sum_j D_{ij}*f_vol
                            + delta_{i,0}*(f*_L - f(U_0))/w_0
                            - delta_{i,N}*(f*_R - f(U_N))/w_N]
    """
    n_elem = mesh.n_elements
    n_nodes = solver.n_nodes
    N = solver.N
    D = solver.D
    w = solver.weights
    jac_factor = 2.0 / mesh.dx

    dUdt = np.zeros_like(U_all)

    for e in range(n_elem):
        # Volume integral using flux differencing
        for i in range(n_nodes):
            vol_sum = np.zeros(3)
            for j in range(n_nodes):
                if i != j:
                    fvol = volume_flux_func(U_all[e, :, i], U_all[e, :, j])
                else:
                    # Consistency: f_vol(U, U) = f(U)
                    fvol = euler_flux(U_all[e, :, i])
                vol_sum += D[i, j] * fvol
            dUdt[e, :, i] = -2.0 * vol_sum

        # Neighbor states for surface fluxes
        if mesh.periodic:
            e_left = (e - 1) % n_elem
            e_right = (e + 1) % n_elem
            U_left_ext = U_all[e_left, :, N]
            U_right_ext = U_all[e_right, :, 0]
        else:
            if e > 0:
                U_left_ext = U_all[e - 1, :, N]
            else:
                U_left_ext = U_all[e, :, 0].copy()
            if e < n_elem - 1:
                U_right_ext = U_all[e + 1, :, 0]
            else:
                U_right_ext = U_all[e, :, N].copy()

        # Surface numerical fluxes
        f_surf_left = surface_flux_func(U_left_ext, U_all[e, :, 0])
        f_surf_right = surface_flux_func(U_all[e, :, N], U_right_ext)

        # Physical fluxes at boundaries
        f_phys_left = euler_flux(U_all[e, :, 0])
        f_phys_right = euler_flux(U_all[e, :, N])

        # SAT surface corrections (strong form):
        # At left boundary (outward normal = -1): ADD correction
        # At right boundary (outward normal = +1): SUBTRACT correction
        dUdt[e, :, 0] += (f_surf_left - f_phys_left) / w[0]
        dUdt[e, :, N] -= (f_surf_right - f_phys_right) / w[N]

        # Apply Jacobian (reference to physical)
        dUdt[e] *= jac_factor

    return dUdt


def compute_max_dt(U_all, solver, mesh, cfl):
    """Compute maximum stable time step based on CFL condition."""
    max_speed = 0.0
    for e in range(mesh.n_elements):
        for i in range(solver.n_nodes):
            speed = max_wave_speed(U_all[e, :, i])
            if speed > max_speed:
                max_speed = speed
    return cfl * mesh.dx / (max_speed * (2 * solver.N + 1))
