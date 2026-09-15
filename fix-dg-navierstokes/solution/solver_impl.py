#!/usr/bin/env python3
"""
Divergence-conforming DG solver for the incompressible Navier-Stokes
equations, validated against Kovasznay analytical flow at Re=25.

Uses RT_{k+1}/DG_k elements, SIP viscous stabilization, upwind
convective flux, Picard linearization via implicit Euler, and
MUMPS for the singular saddle-point system.

"""

import json
import sys

import numpy as np
from mpi4py import MPI
from petsc4py import PETSc

import ufl
from dolfinx import default_real_type, fem, mesh
from dolfinx.fem.petsc import LinearProblem

sys.path.insert(0, "/app")
from utils import (
    Re, k, create_mesh, u_exact_expr, p_exact_expr,
    compute_errors, norm_L2, domain_average,
)

if np.issubdtype(PETSc.ScalarType, np.complexfloating):
    print("ERROR: Solver requires real-valued PETSc. Exiting.")
    sys.exit(1)


def solve(n_cells=16, num_time_steps=25, t_end=10.0):
    """Solve Kovasznay flow on an n_cells x n_cells unit-square mesh.

    Args:
        n_cells: mesh cells per direction
        num_time_steps: number of implicit Euler time steps
        t_end: final time (must be large enough to reach steady state)

    Returns:
        dict with keys: e_u, e_div_u, e_p, converged
    """
    msh = create_mesh(n_cells)
    gdim = msh.geometry.dim

    # =================================================================
    # Function spaces
    # =================================================================

    # RT_{k+1} for velocity (H(div)-conforming)
    V = fem.functionspace(msh, ("Raviart-Thomas", k + 1))
    # DG_k for pressure: satisfies div(RT_{k+1}) = DG_k
    # This pairing guarantees exact mass conservation.
    Q = fem.functionspace(msh, ("Discontinuous Lagrange", k))
    VQ = ufl.MixedFunctionSpace(V, Q)

    # Auxiliary DG space for body force interpolation
    W = fem.functionspace(msh, ("Discontinuous Lagrange", k + 1, (gdim,)))

    # Trial / test functions
    u, p = ufl.TrialFunctions(VQ)
    v, q = ufl.TestFunctions(VQ)

    # Time step
    delta_t = fem.Constant(msh, default_real_type(t_end / num_time_steps))

    # SIP penalty parameter: must scale as O(k^2) for coercivity
    alpha = fem.Constant(msh, default_real_type(6.0 * k**2))

    h = ufl.CellDiameter(msh)
    n_facet = ufl.FacetNormal(msh)

    def jump(phi, n):
        """Jump of a vector-valued function across an interior facet."""
        return ufl.outer(phi("+"), n("+")) + ufl.outer(phi("-"), n("-"))

    # =================================================================
    # SIP viscous bilinear form
    # =================================================================

    a_form = (1.0 / Re) * (
        # Volume integral
        ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx
        # Interior facet terms (consistency + symmetry + penalty)
        - ufl.inner(ufl.avg(ufl.grad(u)), jump(v, n_facet)) * ufl.dS
        - ufl.inner(jump(u, n_facet), ufl.avg(ufl.grad(v))) * ufl.dS
        + (alpha / ufl.avg(h))
        * ufl.inner(jump(u, n_facet), jump(v, n_facet))
        * ufl.dS
        # Boundary facet Nitsche terms
        - ufl.inner(ufl.grad(u), ufl.outer(v, n_facet)) * ufl.ds
        - ufl.inner(ufl.outer(u, n_facet), ufl.grad(v)) * ufl.ds
        + (alpha / h)
        * ufl.inner(ufl.outer(u, n_facet), ufl.outer(v, n_facet))
        * ufl.ds
    )

    # Pressure-velocity coupling (saddle-point structure)
    a_form -= ufl.inner(p, ufl.div(v)) * ufl.dx
    a_form -= ufl.inner(ufl.div(u), q) * ufl.dx

    # =================================================================
    # Right-hand side
    # =================================================================

    f_func = fem.Function(W)          # zero body force (Kovasznay is exact NS solution)
    u_D = fem.Function(V)             # Dirichlet data = exact velocity
    u_D.interpolate(u_exact_expr)

    L_form = (
        ufl.inner(f_func, v) * ufl.dx
        + (1.0 / Re)
        * (
            -ufl.inner(ufl.outer(u_D, n_facet), ufl.grad(v)) * ufl.ds
            + (alpha / h)
            * ufl.inner(
                ufl.outer(u_D, n_facet), ufl.outer(v, n_facet)
            )
            * ufl.ds
        )
    )
    # Zero contribution to the continuity equation row
    L_form += ufl.inner(
        fem.Constant(msh, default_real_type(0.0)), q
    ) * ufl.dx

    # =================================================================
    # Boundary conditions
    # =================================================================

    msh.topology.create_connectivity(msh.topology.dim - 1, msh.topology.dim)
    boundary_facets = mesh.exterior_facet_indices(msh.topology)
    boundary_vel_dofs = fem.locate_dofs_topological(
        V, msh.topology.dim - 1, boundary_facets
    )
    bc_u = fem.dirichletbc(u_D, boundary_vel_dofs)
    bcs = [bc_u]

    # =================================================================
    # Solver configuration (MUMPS direct LU with null-pivot detection)
    # =================================================================

    solver_options = {
        "ksp_type": "preonly",
        "pc_type": "lu",
        "pc_factor_mat_solver_type": "mumps",
        "mat_mumps_icntl_14": 80,       # Increase MUMPS working memory
        "mat_mumps_icntl_24": 1,         # Detect null pivots
        "mat_mumps_icntl_25": 0,         # Handle null-pivot rows
        "ksp_error_if_not_converged": 1,
    }

    # =================================================================
    # Initial Stokes solve
    # =================================================================

    u_h = fem.Function(V)
    p_h = fem.Function(Q)

    stokes_problem = LinearProblem(
        ufl.extract_blocks(a_form),
        ufl.extract_blocks(L_form),
        u=[u_h, p_h],
        bcs=bcs,
        kind="mpi",
        petsc_options_prefix="stokes_",
        petsc_options=solver_options,
    )

    try:
        stokes_problem.solve()
    except PETSc.Error as e:
        if e.ierr == 92:
            print("PETSc solver failed (Stokes):", e)
            sys.exit(1)
        raise

    # Normalise pressure (determined only up to a constant)
    p_h.x.array[:] -= domain_average(msh, p_h)

    # Store solution at previous time level
    u_n = fem.Function(V)
    u_n.x.array[:] = u_h.x.array

    # =================================================================
    # Convective terms + time stepping
    # =================================================================

    # Upwind indicator: lmbda = 1 where u_n . n > 0 (outflow), else 0
    lmbda = ufl.conditional(
        ufl.gt(ufl.dot(u_n, n_facet), 0), 1, 0
    )

    # Upwind flux: sample trial function from the upwind side
    u_uw = lmbda("+") * u("+") + lmbda("-") * u("-")

    a_form += (
        ufl.inner(u / delta_t, v) * ufl.dx
        - ufl.inner(u, ufl.div(ufl.outer(v, u_n))) * ufl.dx
        + ufl.inner(
            (ufl.dot(u_n, n_facet))("+") * u_uw, v("+")
        ) * ufl.dS
        + ufl.inner(
            (ufl.dot(u_n, n_facet))("-") * u_uw, v("-")
        ) * ufl.dS
        + ufl.inner(
            ufl.dot(u_n, n_facet) * lmbda * u, v
        ) * ufl.ds
    )

    L_form += (
        ufl.inner(u_n / delta_t, v) * ufl.dx
        - ufl.inner(
            ufl.dot(u_n, n_facet) * (1.0 - lmbda) * u_D, v
        ) * ufl.ds
    )

    # =================================================================
    # Time-stepping loop (Picard iteration via implicit Euler)
    # =================================================================

    ns_problem = LinearProblem(
        ufl.extract_blocks(a_form),
        ufl.extract_blocks(L_form),
        u=[u_h, p_h],
        bcs=bcs,
        kind="mpi",
        petsc_options_prefix="ns_",
        petsc_options=solver_options,
    )

    for step in range(num_time_steps):
        try:
            ns_problem.solve()
        except PETSc.Error as e:
            if e.ierr == 92:
                print(f"PETSc solver failed at step {step}:", e)
                sys.exit(1)
            raise

        p_h.x.array[:] -= domain_average(msh, p_h)
        u_n.x.array[:] = u_h.x.array

    # =================================================================
    # Error computation
    # =================================================================

    errors = compute_errors(msh, u_h, p_h)
    errors["converged"] = True
    return errors


if __name__ == "__main__":
    errors = solve(n_cells=16, num_time_steps=25, t_end=10.0)

    with open("/app/results.json", "w") as fout:
        json.dump(errors, fout, indent=2)

    print(f"Results:")
    print(f"  e_u     = {errors['e_u']:.5e}")
    print(f"  e_div_u = {errors['e_div_u']:.5e}")
    print(f"  e_p     = {errors['e_p']:.5e}")
    print("Results written to /app/results.json")
