"""
Divergence-conforming DG Navier-Stokes solver for Kovasznay flow.

Uses monolithic mixed element approach (RT_{k+1} x DG_k) with manual
PETSc assembly. Compatible with DOLFINx 0.9.0.

Implements symmetric interior penalty DG viscous terms, upwind convective
treatment, and semi-implicit time-stepping to steady state.
"""

import sys
sys.path.insert(0, "/app")

from mpi4py import MPI
from petsc4py import PETSc

import json
import numpy as np

import ufl
from basix.ufl import element as basix_element, mixed_element
from dolfinx import default_real_type, fem, mesh
from dolfinx.fem.petsc import (
    assemble_matrix, assemble_vector,
    apply_lifting, set_bc,
)

from problem_spec import (
    MESH_N, POLY_DEGREE, RE, NUM_STEPS, T_FINAL,
    velocity_exact, pressure_exact, forcing,
)

if np.issubdtype(PETSc.ScalarType, np.complexfloating):
    print("This solver requires DOLFINx real mode.")
    exit(0)

K = POLY_DEGREE


def l2_norm(comm, v):
    """Compute the L2 norm of v over the domain."""
    return np.sqrt(
        comm.allreduce(
            fem.assemble_scalar(fem.form(ufl.inner(v, v) * ufl.dx)),
            op=MPI.SUM,
        )
    )


def domain_avg(msh, v):
    """Compute the domain average of a scalar function."""
    vol = msh.comm.allreduce(
        fem.assemble_scalar(
            fem.form(fem.Constant(msh, default_real_type(1.0)) * ufl.dx)
        ),
        op=MPI.SUM,
    )
    return (1.0 / vol) * msh.comm.allreduce(
        fem.assemble_scalar(fem.form(v * ufl.dx)), op=MPI.SUM
    )


def tensor_jump(phi, n):
    """Compute the tensor jump [[phi (x) n]] across facets."""
    return ufl.outer(phi("+"), n("+")) + ufl.outer(phi("-"), n("-"))


def create_ksp(comm, solver_opts, prefix):
    """Create and configure a PETSc KSP solver with MUMPS."""
    ksp = PETSc.KSP().create(comm)
    ksp.setOptionsPrefix(prefix)
    opts = PETSc.Options()
    opts.prefixPush(prefix)
    for k, v in solver_opts.items():
        opts[k] = v
    opts.prefixPop()
    ksp.setFromOptions()
    return ksp


def assemble_rhs(L_compiled, a_compiled, bcs):
    """Assemble RHS vector with BC lifting and enforcement."""
    b = assemble_vector(L_compiled)
    apply_lifting(b, [a_compiled], bcs=[bcs])
    b.ghostUpdate(addv=PETSc.InsertMode.ADD, mode=PETSc.ScatterMode.REVERSE)
    set_bc(b, bcs)
    return b


def main():
    domain = mesh.create_unit_square(MPI.COMM_WORLD, MESH_N, MESH_N)
    gdim = domain.geometry.dim

    # ================================================================
    # Monolithic mixed function space: RT_{k+1} x DG_k
    # This avoids the block LinearProblem API (kind="mpi") which is
    # not available in dolfinx 0.9.0.
    # ================================================================
    cell = domain.basix_cell()
    mel = mixed_element([
        basix_element("Raviart-Thomas", cell, K + 1),
        basix_element("Discontinuous Lagrange", cell, K),
    ])
    W = fem.functionspace(domain, mel)

    # Separate RT space for the previous-velocity coefficient
    V_rt = fem.functionspace(domain, ("Raviart-Thomas", K + 1))
    # DG vector space for forcing interpolation
    W_vis = fem.functionspace(
        domain, ("Discontinuous Lagrange", K + 1, (gdim,))
    )

    # Collapsed velocity sub-space (for Dirichlet BCs)
    W_V = W.sub(0)
    V_collapsed, _ = W_V.collapse()

    # Mixed trial / test functions
    up_trial = ufl.TrialFunction(W)
    vq_test = ufl.TestFunction(W)
    u, p = ufl.split(up_trial)
    v, q = ufl.split(vq_test)

    # Constants
    delta_t = fem.Constant(domain, default_real_type(T_FINAL / NUM_STEPS))
    alpha = fem.Constant(domain, default_real_type(6.0 * K**2))
    h = ufl.CellDiameter(domain)
    n = ufl.FacetNormal(domain)

    # Previous velocity (coefficient in a separate RT space)
    u_prev = fem.Function(V_rt, name="u_prev")

    # ================================================================
    # SIP-DG viscous bilinear form
    # ================================================================
    a_visc = (1.0 / RE) * (
        # Volume gradient term
        ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx
        # Interior facet: consistency
        - ufl.inner(ufl.avg(ufl.grad(u)), tensor_jump(v, n)) * ufl.dS
        # Interior facet: symmetry (negative for SIP)
        - ufl.inner(tensor_jump(u, n), ufl.avg(ufl.grad(v))) * ufl.dS
        # Interior facet: penalty
        + (alpha / ufl.avg(h))
        * ufl.inner(tensor_jump(u, n), tensor_jump(v, n))
        * ufl.dS
        # Boundary: Nitsche consistency
        - ufl.inner(ufl.grad(u), ufl.outer(v, n)) * ufl.ds
        # Boundary: Nitsche symmetry
        - ufl.inner(ufl.outer(u, n), ufl.grad(v)) * ufl.ds
        # Boundary: Nitsche penalty
        + (alpha / h)
        * ufl.inner(ufl.outer(u, n), ufl.outer(v, n))
        * ufl.ds
    )

    # Pressure-velocity coupling (saddle-point)
    a_stokes = a_visc
    a_stokes -= ufl.inner(p, ufl.div(v)) * ufl.dx
    a_stokes -= ufl.inner(ufl.div(u), q) * ufl.dx

    # ================================================================
    # RHS: body force + DG boundary terms for Dirichlet data
    # ================================================================
    f_ext = fem.Function(W_vis)
    f_ext.interpolate(forcing)

    u_D = fem.Function(V_rt)
    u_D.interpolate(velocity_exact)

    L_stokes = ufl.inner(f_ext, v) * ufl.dx + (1.0 / RE) * (
        -ufl.inner(ufl.outer(u_D, n), ufl.grad(v)) * ufl.ds
        + (alpha / h)
        * ufl.inner(ufl.outer(u_D, n), ufl.outer(v, n))
        * ufl.ds
    )
    L_stokes += ufl.inner(
        fem.Constant(domain, default_real_type(0.0)), q
    ) * ufl.dx

    # ================================================================
    # Dirichlet BCs on velocity normal component (all boundaries)
    # ================================================================
    domain.topology.create_connectivity(
        domain.topology.dim - 1, domain.topology.dim
    )
    bdry_facets = mesh.exterior_facet_indices(domain.topology)
    u_D_bc = fem.Function(V_collapsed)
    u_D_bc.interpolate(velocity_exact)
    bdry_dofs = fem.locate_dofs_topological(
        (W_V, V_collapsed), domain.topology.dim - 1, bdry_facets
    )
    bcs = [fem.dirichletbc(u_D_bc, bdry_dofs, W_V)]

    # ================================================================
    # MUMPS direct solver options
    # ================================================================
    solver_opts = {
        "ksp_type": "preonly",
        "pc_type": "lu",
        "pc_factor_mat_solver_type": "mumps",
        "mat_mumps_icntl_14": 80,
        "mat_mumps_icntl_24": 1,   # null pivot detection
        "mat_mumps_icntl_25": 0,
        "ksp_error_if_not_converged": 1,
    }

    # Solution function in the mixed space
    w_h = fem.Function(W)

    # ================================================================
    # Solve Stokes problem for initial condition
    # ================================================================
    print("Solving Stokes for initial condition...")
    a_stokes_compiled = fem.form(a_stokes)
    L_stokes_compiled = fem.form(L_stokes)

    A_stokes = assemble_matrix(a_stokes_compiled, bcs=bcs)
    A_stokes.assemble()
    b_stokes = assemble_rhs(L_stokes_compiled, a_stokes_compiled, bcs)

    ksp_stokes = create_ksp(domain.comm, solver_opts, "stokes_")
    ksp_stokes.setOperators(A_stokes)

    try:
        ksp_stokes.solve(b_stokes, w_h.x.petsc_vec)
    except PETSc.Error as e:
        if e.ierr == 92:
            print(f"Solver failed during Stokes solve: {e}")
            exit(1)
        raise
    w_h.x.scatter_forward()
    ksp_stokes.destroy()

    # Extract initial velocity into u_prev
    u_init = w_h.sub(0).collapse()
    u_prev.x.array[:] = u_init.x.array[:]

    # ================================================================
    # Navier-Stokes form: Stokes + time derivative + convection
    # ================================================================
    # Upwind indicator based on u_prev . n
    lmbda = ufl.conditional(ufl.gt(ufl.dot(u_prev, n), 0), 1, 0)
    u_uw = lmbda("+") * u("+") + lmbda("-") * u("-")

    a_ns = a_stokes + (
        ufl.inner(u / delta_t, v) * ufl.dx
        - ufl.inner(u, ufl.div(ufl.outer(v, u_prev))) * ufl.dx
        + ufl.inner(
            (ufl.dot(u_prev, n))("+") * u_uw, v("+")
        ) * ufl.dS
        + ufl.inner(
            (ufl.dot(u_prev, n))("-") * u_uw, v("-")
        ) * ufl.dS
        + ufl.inner(ufl.dot(u_prev, n) * lmbda * u, v) * ufl.ds
    )

    L_ns = L_stokes + (
        ufl.inner(u_prev / delta_t, v) * ufl.dx
        - ufl.inner(
            ufl.dot(u_prev, n) * (1 - lmbda) * u_D, v
        ) * ufl.ds
    )

    a_ns_compiled = fem.form(a_ns)
    L_ns_compiled = fem.form(L_ns)

    ksp_ns = create_ksp(domain.comm, solver_opts, "ns_")

    # ================================================================
    # Time-stepping loop
    # ================================================================
    print("Starting time stepping...")
    t = 0.0
    for step in range(NUM_STEPS):
        t += delta_t.value

        # Reassemble NS system (coefficients u_prev changed)
        A_ns = assemble_matrix(a_ns_compiled, bcs=bcs)
        A_ns.assemble()
        b_ns = assemble_rhs(L_ns_compiled, a_ns_compiled, bcs)

        ksp_ns.setOperators(A_ns)

        try:
            ksp_ns.solve(b_ns, w_h.x.petsc_vec)
        except PETSc.Error as e:
            if e.ierr == 92:
                print(f"Solver failed at step {step + 1}: {e}")
                exit(1)
            raise
        w_h.x.scatter_forward()

        # Update u_prev with current velocity
        u_step = w_h.sub(0).collapse()
        u_prev.x.array[:] = u_step.x.array[:]

        print(f"  Step {step + 1}/{NUM_STEPS}, t = {t:.4f}")

    ksp_ns.destroy()

    # ================================================================
    # Compute error norms against exact Kovasznay solution
    # ================================================================
    print("\nComputing errors...")

    u_final = w_h.sub(0).collapse()
    p_final = w_h.sub(1).collapse()

    # Normalize pressure (determined up to a constant)
    p_avg = domain_avg(domain, p_final)
    p_final.x.array[:] -= p_avg

    # Higher-order spaces for exact solution interpolation
    V_exact = fem.functionspace(domain, ("Lagrange", K + 3, (gdim,)))
    Q_exact = fem.functionspace(domain, ("Lagrange", K + 2))

    u_e = fem.Function(V_exact)
    u_e.interpolate(velocity_exact)

    p_e = fem.Function(Q_exact)
    p_e.interpolate(pressure_exact)

    e_vel = l2_norm(domain.comm, u_final - u_e)
    e_div = l2_norm(domain.comm, ufl.div(u_final))

    p_e_avg = domain_avg(domain, p_e)
    e_prs = l2_norm(domain.comm, p_final - (p_e - p_e_avg))

    assert np.isclose(
        e_div, 0.0, atol=float(1.0e5 * np.finfo(default_real_type).eps)
    ), f"Mass conservation violated: e_div = {e_div}"

    print(f"\nVelocity L2 error:    {e_vel:.6e}")
    print(f"Divergence L2 error:  {e_div:.6e}")
    print(f"Pressure L2 error:    {e_prs:.6e}")

    results = {
        "velocity_l2_error": float(e_vel),
        "divergence_l2_error": float(e_div),
        "pressure_l2_error": float(e_prs),
    }
    with open("/app/results.json", "w") as fh:
        json.dump(results, fh, indent=2)

    print(f"\nResults written to /app/results.json")
    return results


if __name__ == "__main__":
    main()
