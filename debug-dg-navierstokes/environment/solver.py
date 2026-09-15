"""
Divergence-conforming DG Navier-Stokes solver for Kovasznay flow.

Implements a divergence-conforming discontinuous Galerkin method for
the incompressible Navier-Stokes equations on a unit square mesh,
validated against the Kovasznay exact solution at Reynolds number 25.

The method uses Raviart-Thomas elements for velocity (H(div)-conforming)
and discontinuous Lagrange elements for pressure, with a symmetric
interior penalty formulation for the viscous term.

This solver contains bugs that prevent correct results.
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
MESH_N = 16           # cells per side
NUM_STEPS = 25        # time steps
T_FINAL = 10.0        # final time (relaxation to steady state)
RE = 25.0             # Reynolds number
K = 1                 # polynomial degree


# ========================================================================
# Kovasznay exact solution
# ========================================================================
def velocity_exact(x):
    """Exact velocity field for Kovasznay flow at given Reynolds number."""
    lam = RE / 2 - np.sqrt(RE**2 / 4 + 4 * np.pi**2)
    return np.vstack((
        1 - np.exp(lam * x[0]) * np.cos(2 * np.pi * x[1]),
        (lam / (2 * np.pi)) * np.exp(lam * x[0]) * np.sin(2 * np.pi * x[1]),
    ))


def pressure_exact(x):
    """Exact pressure field for Kovasznay flow at given Reynolds number."""
    lam = RE / 2 - np.sqrt(RE**2 / 4 + 4 * np.pi**2)
    return 0.5 * (1 - np.exp(2 * lam * x[0]))


def forcing(x):
    """External forcing (zero for Kovasznay flow)."""
    return np.vstack((np.zeros_like(x[0]), np.zeros_like(x[0])))


# ========================================================================
# Utility functions
# ========================================================================
def l2_norm(comm, v):
    """Compute the L2 norm of a function over the domain."""
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


def dg_jump(phi, n):
    """Compute the tensor jump of vector field phi across facets."""
    return ufl.outer(phi("+"), n("+")) + ufl.outer(phi("-"), n("-"))


# ========================================================================
# Main solver routine
# ========================================================================
def solve():
    """Solve the Navier-Stokes equations using DG and return error metrics."""

    # ------------------------------------------------------------------
    # Mesh and function spaces
    # ------------------------------------------------------------------
    domain = mesh.create_unit_square(MPI.COMM_WORLD, MESH_N, MESH_N)

    # Velocity: H(div)-conforming Raviart-Thomas of order k+1
    V = fem.functionspace(domain, ("Raviart-Thomas", K + 1))
    # Pressure: Discontinuous Lagrange of order k
    Q = fem.functionspace(domain, ("Discontinuous Lagrange", K))
    # Mixed space
    VQ = ufl.MixedFunctionSpace(V, Q)

    gdim = domain.geometry.dim
    # DG space for forcing and visualization
    W = fem.functionspace(domain, ("Discontinuous Lagrange", K + 1, (gdim,)))

    # Trial and test functions
    u, p = ufl.TrialFunctions(VQ)
    v, q = ufl.TestFunctions(VQ)

    # Constants
    delta_t = fem.Constant(domain, default_real_type(T_FINAL / NUM_STEPS))
    alpha = fem.Constant(domain, default_real_type(6.0 * K**2))

    h = ufl.CellDiameter(domain)
    n = ufl.FacetNormal(domain)

    # ------------------------------------------------------------------
    # Stokes bilinear form: symmetric interior penalty DG viscous term
    # ------------------------------------------------------------------
    # The SIP form for the viscous term has three parts on interior facets:
    #   (1) consistency:   -<avg(grad u), jump(v)>
    #   (2) symmetry:      -<jump(u), avg(grad v)>
    #   (3) penalty:       alpha/h <jump(u), jump(v)>
    # Plus analogous boundary terms.
    a_form = (1.0 / RE) * (
        ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx
        # Interior facet terms
        - ufl.inner(ufl.avg(ufl.grad(u)), dg_jump(v, n)) * ufl.dS
        + ufl.inner(dg_jump(u, n), ufl.avg(ufl.grad(v))) * ufl.dS
        + (alpha / ufl.avg(h))
        * ufl.inner(dg_jump(u, n), dg_jump(v, n))
        * ufl.dS
        # Boundary facet terms
        - ufl.inner(ufl.grad(u), ufl.outer(v, n)) * ufl.ds
        - ufl.inner(ufl.outer(u, n), ufl.grad(v)) * ufl.ds
        + (alpha / h)
        * ufl.inner(ufl.outer(u, n), ufl.outer(v, n))
        * ufl.ds
    )

    # Pressure-velocity coupling
    a_form -= ufl.inner(p, ufl.div(v)) * ufl.dx
    a_form -= ufl.inner(ufl.div(u), q) * ufl.dx

    # ------------------------------------------------------------------
    # Right-hand side: forcing + boundary data
    # ------------------------------------------------------------------
    f_ext = fem.Function(W)
    f_ext.interpolate(forcing)

    u_D = fem.Function(V)
    u_D.interpolate(velocity_exact)

    # Boundary forcing terms from Nitsche/DG treatment of Dirichlet BCs
    L_form = ufl.inner(f_ext, v) * ufl.dx + (
        -ufl.inner(ufl.outer(u_D, n), ufl.grad(v)) * ufl.ds
        + (alpha / h)
        * ufl.inner(ufl.outer(u_D, n), ufl.outer(v, n))
        * ufl.ds
    )
    # Zero contribution to pressure equation
    L_form += ufl.inner(
        fem.Constant(domain, default_real_type(0.0)), q
    ) * ufl.dx

    # ------------------------------------------------------------------
    # Dirichlet boundary conditions (normal component of velocity)
    # ------------------------------------------------------------------
    domain.topology.create_connectivity(
        domain.topology.dim - 1, domain.topology.dim
    )
    bdry_facets = mesh.exterior_facet_indices(domain.topology)
    bdry_dofs = fem.locate_dofs_topological(
        V, domain.topology.dim - 1, bdry_facets
    )
    bcs = [fem.dirichletbc(u_D, bdry_dofs)]

    # ------------------------------------------------------------------
    # Solver configuration (MUMPS direct solver)
    # ------------------------------------------------------------------
    solver_opts = {
        "ksp_type": "preonly",
        "pc_type": "lu",
        "pc_factor_mat_solver_type": "mumps",
        "mat_mumps_icntl_14": 80,       # Increase MUMPS working memory
        "mat_mumps_icntl_24": 0,        # Null pivot detection
        "mat_mumps_icntl_25": 0,        # Solution for singular systems
        "ksp_error_if_not_converged": 1,
    }

    # ------------------------------------------------------------------
    # Solve Stokes problem for initial condition
    # ------------------------------------------------------------------
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

    # Normalize pressure (determined up to a constant)
    p_h.x.array[:] -= domain_avg(domain, p_h)

    # Store previous time step velocity
    u_prev = fem.Function(V, name="u_prev")
    u_prev.x.array[:] = u_h.x.array

    # ------------------------------------------------------------------
    # Add time-stepping and convective terms for Navier-Stokes
    # ------------------------------------------------------------------
    # Upwind indicator: 1 if u_prev.n > 0 (outflow), 0 otherwise
    lmbda = ufl.conditional(ufl.gt(ufl.dot(u_prev, n), 0), 1, 0)
    u_upwind = lmbda("+") * u("+") + lmbda("-") * u("-")

    # Time derivative and convective terms added to bilinear form
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

    # Previous time step and inflow boundary terms added to RHS
    L_form += (
        ufl.inner(u_prev / delta_t, v) * ufl.dx
        - ufl.inner(
            ufl.dot(u_prev, n) * (1 - lmbda) * u_D, v
        ) * ufl.ds
    )

    # Create Navier-Stokes solver
    ns_problem = LinearProblem(
        ufl.extract_blocks(a_form),
        ufl.extract_blocks(L_form),
        u=[u_h, p_h],
        bcs=bcs,
        kind="mpi",
        petsc_options_prefix="ns_",
        petsc_options=solver_opts,
    )

    # ------------------------------------------------------------------
    # Time-stepping loop (semi-implicit, relaxing to steady state)
    # ------------------------------------------------------------------
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

        print(f"  Step {step + 1}/{NUM_STEPS}, t = {t:.4f}")

    # ------------------------------------------------------------------
    # Compute errors against exact solution
    # ------------------------------------------------------------------
    print("\nComputing errors...")

    V_exact = fem.functionspace(domain, ("Lagrange", K + 3, (gdim,)))
    Q_exact = fem.functionspace(domain, ("Lagrange", K + 2))

    u_e = fem.Function(V_exact)
    u_e.interpolate(velocity_exact)

    p_e = fem.Function(Q_exact)
    p_e.interpolate(pressure_exact)

    e_vel = l2_norm(domain.comm, u_h - u_e)
    e_div = l2_norm(domain.comm, ufl.div(u_h))

    # Normalize exact pressure before comparing
    p_e_avg = domain_avg(domain, p_e)
    e_prs = l2_norm(domain.comm, p_h - (p_e - p_e_avg))

    # Verify mass conservation (should be exact for div-conforming elements)
    assert np.isclose(
        e_div, 0.0, atol=float(1.0e5 * np.finfo(default_real_type).eps)
    ), f"Mass conservation violated: e_div = {e_div}"

    print(f"\n{'='*40}")
    print(f"Velocity L2 error:    {e_vel:.6e}")
    print(f"Divergence L2 error:  {e_div:.6e}")
    print(f"Pressure L2 error:    {e_prs:.6e}")
    print(f"{'='*40}")

    # Write results
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
