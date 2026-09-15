"""
Fixed divergence-conforming DG Navier-Stokes solver for Kovasznay flow.

This is the corrected version with all four bugs fixed:
1. SIP sign error corrected (symmetry term uses minus sign)
2. MUMPS icntl_24 set to 1 (null pivot detection enabled)
3. (1/RE) factor restored on RHS boundary terms
4. u_prev update restored in time-stepping loop
"""


from mpi4py import MPI
from petsc4py import PETSc

import json
import numpy as np

import ufl
from dolfinx import default_real_type, fem, mesh
from dolfinx.fem.petsc import LinearProblem

if np.issubdtype(PETSc.ScalarType, np.complexfloating):
    print("This solver requires DOLFINx real mode.")
    exit(0)


# ========================================================================
# Physical and discretization parameters
# ========================================================================
MESH_N = 16
NUM_STEPS = 25
T_FINAL = 10.0
RE = 25.0
K = 1


# ========================================================================
# Kovasznay exact solution
# ========================================================================
def velocity_exact(x):
    lam = RE / 2 - np.sqrt(RE**2 / 4 + 4 * np.pi**2)
    return np.vstack((
        1 - np.exp(lam * x[0]) * np.cos(2 * np.pi * x[1]),
        (lam / (2 * np.pi)) * np.exp(lam * x[0]) * np.sin(2 * np.pi * x[1]),
    ))


def pressure_exact(x):
    lam = RE / 2 - np.sqrt(RE**2 / 4 + 4 * np.pi**2)
    return 0.5 * (1 - np.exp(2 * lam * x[0]))


def forcing(x):
    return np.vstack((np.zeros_like(x[0]), np.zeros_like(x[0])))


# ========================================================================
# Utility functions
# ========================================================================
def l2_norm(comm, v):
    return np.sqrt(
        comm.allreduce(
            fem.assemble_scalar(fem.form(ufl.inner(v, v) * ufl.dx)),
            op=MPI.SUM,
        )
    )


def domain_avg(msh, v):
    vol = msh.comm.allreduce(
        fem.assemble_scalar(
            fem.form(fem.Constant(msh, default_real_type(1.0)) * ufl.dx)
        ),
        op=MPI.SUM,
    )
    return (1.0 / vol) * msh.comm.allreduce(
        fem.assemble_scalar(fem.form(v * ufl.dx)), op=MPI.SUM
    )


def dg_jump(phi, n):
    return ufl.outer(phi("+"), n("+")) + ufl.outer(phi("-"), n("-"))


# ========================================================================
# Main solver routine
# ========================================================================
def solve():
    domain = mesh.create_unit_square(MPI.COMM_WORLD, MESH_N, MESH_N)

    V = fem.functionspace(domain, ("Raviart-Thomas", K + 1))
    Q = fem.functionspace(domain, ("Discontinuous Lagrange", K))
    VQ = ufl.MixedFunctionSpace(V, Q)

    gdim = domain.geometry.dim
    W = fem.functionspace(domain, ("Discontinuous Lagrange", K + 1, (gdim,)))

    u, p = ufl.TrialFunctions(VQ)
    v, q = ufl.TestFunctions(VQ)

    delta_t = fem.Constant(domain, default_real_type(T_FINAL / NUM_STEPS))
    alpha = fem.Constant(domain, default_real_type(6.0 * K**2))

    h = ufl.CellDiameter(domain)
    n = ufl.FacetNormal(domain)

    # FIX 1: Correct SIP-DG viscous bilinear form
    # Both consistency terms must have NEGATIVE signs for symmetric penalty
    a_form = (1.0 / RE) * (
        ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx
        - ufl.inner(ufl.avg(ufl.grad(u)), dg_jump(v, n)) * ufl.dS
        - ufl.inner(dg_jump(u, n), ufl.avg(ufl.grad(v))) * ufl.dS  # FIX: minus sign
        + (alpha / ufl.avg(h))
        * ufl.inner(dg_jump(u, n), dg_jump(v, n))
        * ufl.dS
        - ufl.inner(ufl.grad(u), ufl.outer(v, n)) * ufl.ds
        - ufl.inner(ufl.outer(u, n), ufl.grad(v)) * ufl.ds
        + (alpha / h)
        * ufl.inner(ufl.outer(u, n), ufl.outer(v, n))
        * ufl.ds
    )

    a_form -= ufl.inner(p, ufl.div(v)) * ufl.dx
    a_form -= ufl.inner(ufl.div(u), q) * ufl.dx

    f_ext = fem.Function(W)
    f_ext.interpolate(forcing)

    u_D = fem.Function(V)
    u_D.interpolate(velocity_exact)

    # FIX 3: Include (1/RE) factor on boundary terms to match bilinear form
    L_form = ufl.inner(f_ext, v) * ufl.dx + (1.0 / RE) * (
        -ufl.inner(ufl.outer(u_D, n), ufl.grad(v)) * ufl.ds
        + (alpha / h)
        * ufl.inner(ufl.outer(u_D, n), ufl.outer(v, n))
        * ufl.ds
    )
    L_form += ufl.inner(
        fem.Constant(domain, default_real_type(0.0)), q
    ) * ufl.dx

    domain.topology.create_connectivity(
        domain.topology.dim - 1, domain.topology.dim
    )
    bdry_facets = mesh.exterior_facet_indices(domain.topology)
    bdry_dofs = fem.locate_dofs_topological(
        V, domain.topology.dim - 1, bdry_facets
    )
    bcs = [fem.dirichletbc(u_D, bdry_dofs)]

    # FIX 2: Set icntl_24 to 1 for null pivot detection
    solver_opts = {
        "ksp_type": "preonly",
        "pc_type": "lu",
        "pc_factor_mat_solver_type": "mumps",
        "mat_mumps_icntl_14": 80,
        "mat_mumps_icntl_24": 1,  # FIX: enable null pivot detection
        "mat_mumps_icntl_25": 0,
        "ksp_error_if_not_converged": 1,
    }

    u_h = fem.Function(V)
    p_h = fem.Function(Q)
    p_h.name = "p"

    print("Solving Stokes for initial condition...")
    stokes_problem = LinearProblem(
        ufl.extract_blocks(a_form),
        ufl.extract_blocks(L_form),
        u=[u_h, p_h],
        bcs=bcs,
        kind="mpi",
        petsc_options_prefix="stokes_",
        petsc_options=solver_opts,
    )

    try:
        stokes_problem.solve()
    except PETSc.Error as e:
        if e.ierr == 92:
            print(f"Solver failed during Stokes solve: {e}")
            exit(1)
        raise

    p_h.x.array[:] -= domain_avg(domain, p_h)

    u_prev = fem.Function(V, name="u_prev")
    u_prev.x.array[:] = u_h.x.array

    lmbda = ufl.conditional(ufl.gt(ufl.dot(u_prev, n), 0), 1, 0)
    u_upwind = lmbda("+") * u("+") + lmbda("-") * u("-")

    a_form += (
        ufl.inner(u / delta_t, v) * ufl.dx
        - ufl.inner(u, ufl.div(ufl.outer(v, u_prev))) * ufl.dx
        + ufl.inner(
            (ufl.dot(u_prev, n))("+") * u_upwind, v("+")
        ) * ufl.dS
        + ufl.inner(
            (ufl.dot(u_prev, n))("-") * u_upwind, v("-")
        ) * ufl.dS
        + ufl.inner(ufl.dot(u_prev, n) * lmbda * u, v) * ufl.ds
    )

    L_form += (
        ufl.inner(u_prev / delta_t, v) * ufl.dx
        - ufl.inner(
            ufl.dot(u_prev, n) * (1 - lmbda) * u_D, v
        ) * ufl.ds
    )

    ns_problem = LinearProblem(
        ufl.extract_blocks(a_form),
        ufl.extract_blocks(L_form),
        u=[u_h, p_h],
        bcs=bcs,
        kind="mpi",
        petsc_options_prefix="ns_",
        petsc_options=solver_opts,
    )

    print("Starting time stepping...")
    t = 0.0
    for step in range(NUM_STEPS):
        t += delta_t.value

        try:
            ns_problem.solve()
        except PETSc.Error as e:
            if e.ierr == 92:
                print(f"Solver failed at step {step + 1}: {e}")
                exit(1)
            raise

        p_h.x.array[:] -= domain_avg(domain, p_h)

        # FIX 4: Update u_prev with current solution for next time step
        u_prev.x.array[:] = u_h.x.array

        print(f"  Step {step + 1}/{NUM_STEPS}, t = {t:.4f}")

    print("\nComputing errors...")

    V_exact = fem.functionspace(domain, ("Lagrange", K + 3, (gdim,)))
    Q_exact = fem.functionspace(domain, ("Lagrange", K + 2))

    u_e = fem.Function(V_exact)
    u_e.interpolate(velocity_exact)

    p_e = fem.Function(Q_exact)
    p_e.interpolate(pressure_exact)

    e_vel = l2_norm(domain.comm, u_h - u_e)
    e_div = l2_norm(domain.comm, ufl.div(u_h))

    p_e_avg = domain_avg(domain, p_e)
    e_prs = l2_norm(domain.comm, p_h - (p_e - p_e_avg))

    assert np.isclose(
        e_div, 0.0, atol=float(1.0e5 * np.finfo(default_real_type).eps)
    ), f"Mass conservation violated: e_div = {e_div}"

    print(f"\n{'='*40}")
    print(f"Velocity L2 error:    {e_vel:.6e}")
    print(f"Divergence L2 error:  {e_div:.6e}")
    print(f"Pressure L2 error:    {e_prs:.6e}")
    print(f"{'='*40}")

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
    solve()
