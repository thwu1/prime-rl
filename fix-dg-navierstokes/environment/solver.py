#!/usr/bin/env python3
"""
Divergence-conforming DG discretization of the incompressible
Navier-Stokes equations on a unit-square mesh, validated against
the Kovasznay analytical flow at Re = 25.

Run:    python3 /app/solver.py
Output: /app/results.json  with keys  e_u, e_div_u, e_p, converged

"""

import json
import sys

import numpy as np
from mpi4py import MPI
from petsc4py import PETSc

import ufl
from dolfinx import default_real_type, fem, mesh
from dolfinx.fem.petsc import LinearProblem

if np.issubdtype(PETSc.ScalarType, np.complexfloating):
    print("ERROR: Solver requires real-valued PETSc. Exiting.")
    sys.exit(1)


# ===================================================================
# Helper functions
# ===================================================================

def norm_L2(comm, v):
    """Compute the L2(Omega)-norm of a UFL expression v."""
    return np.sqrt(
        comm.allreduce(
            fem.assemble_scalar(fem.form(ufl.inner(v, v) * ufl.dx)),
            op=MPI.SUM,
        )
    )


def domain_average(msh, v):
    """Compute the average of a scalar function v over the domain."""
    vol = msh.comm.allreduce(
        fem.assemble_scalar(
            fem.form(fem.Constant(msh, default_real_type(1.0)) * ufl.dx)
        ),
        op=MPI.SUM,
    )
    return (1.0 / vol) * msh.comm.allreduce(
        fem.assemble_scalar(fem.form(v * ufl.dx)), op=MPI.SUM
    )


# ===================================================================
# Physical and discretization parameters
# ===================================================================

Re = 25.0           # Reynolds number
n_cells = 16        # Mesh cells per direction
k = 1               # Polynomial degree for the pressure space
num_time_steps = 25  # Number of implicit Euler steps
t_end = 10.0        # Final time (long enough to reach steady state)


# ===================================================================
# Kovasznay analytical solution
# ===================================================================

def u_exact_expr(x):
    """Exact velocity for Kovasznay flow."""
    lam = Re / 2.0 - np.sqrt(Re**2 / 4.0 + 4.0 * np.pi**2)
    return np.vstack(
        (
            1.0 - np.exp(lam * x[0]) * np.cos(2.0 * np.pi * x[1]),
            lam / (2.0 * np.pi)
            * np.exp(lam * x[0])
            * np.sin(2.0 * np.pi * x[1]),
        )
    )


def p_exact_expr(x):
    """Exact pressure for Kovasznay flow."""
    lam = Re / 2.0 - np.sqrt(Re**2 / 4.0 + 4.0 * np.pi**2)
    return 0.5 * (1.0 - np.exp(2.0 * lam * x[0]))


def forcing_expr(x):
    """Body force (zero -- Kovasznay is an exact NS solution)."""
    return np.vstack((np.zeros_like(x[0]), np.zeros_like(x[0])))


# ===================================================================
# Mesh
# ===================================================================

msh = mesh.create_unit_square(MPI.COMM_WORLD, n_cells, n_cells)
gdim = msh.geometry.dim


# ===================================================================
# Function spaces
# ===================================================================

# RT_{k+1} for velocity (H(div)-conforming)
V = fem.functionspace(msh, ("Raviart-Thomas", k + 1))

# Pressure space  (must satisfy  div(V_h) = Q_h)
Q = fem.functionspace(msh, ("Lagrange", k))

VQ = ufl.MixedFunctionSpace(V, Q)

# Auxiliary DG space for body force interpolation
W = fem.functionspace(msh, ("Discontinuous Lagrange", k + 1, (gdim,)))

# Trial / test functions
u, p = ufl.TrialFunctions(VQ)
v, q = ufl.TestFunctions(VQ)

# Time step
delta_t = fem.Constant(msh, default_real_type(t_end / num_time_steps))

# SIP penalty parameter
alpha = fem.Constant(msh, default_real_type(1.0))

h = ufl.CellDiameter(msh)
n_facet = ufl.FacetNormal(msh)


def jump(phi, n):
    """Jump of a vector-valued function across an interior facet."""
    return ufl.outer(phi("+"), n("+")) + ufl.outer(phi("-"), n("-"))


# ===================================================================
# SIP viscous bilinear form
# ===================================================================

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

# ===================================================================
# Right-hand side
# ===================================================================

f_func = fem.Function(W)          # zero body force
u_D = fem.Function(V)             # Dirichlet data = exact velocity
u_D.interpolate(u_exact_expr)

L_form = (
    ufl.inner(f_func, v) * ufl.dx
    + (1.0 / Re)
    * (
        -ufl.inner(ufl.outer(u_D, n_facet), ufl.grad(v)) * ufl.ds
        + (alpha / h)
        * ufl.inner(ufl.outer(u_D, n_facet), ufl.outer(v, n_facet))
        * ufl.ds
    )
)
# Zero contribution to the continuity row
L_form += ufl.inner(fem.Constant(msh, default_real_type(0.0)), q) * ufl.dx

# ===================================================================
# Boundary conditions
# ===================================================================

msh.topology.create_connectivity(msh.topology.dim - 1, msh.topology.dim)
boundary_facets = mesh.exterior_facet_indices(msh.topology)
boundary_vel_dofs = fem.locate_dofs_topological(
    V, msh.topology.dim - 1, boundary_facets
)
bc_u = fem.dirichletbc(u_D, boundary_vel_dofs)
bcs = [bc_u]

# ===================================================================
# Solver configuration  (direct LU via MUMPS)
# ===================================================================

solver_options = {
    "ksp_type": "preonly",
    "pc_type": "lu",
    "pc_factor_mat_solver_type": "mumps",
    "mat_mumps_icntl_14": 80,       # Increase MUMPS working memory
    "ksp_error_if_not_converged": 1,
}

# ===================================================================
# Initial Stokes solve
# ===================================================================

u_h = fem.Function(V)
p_h = fem.Function(Q)

print("Solving initial Stokes problem ...")
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
        print("PETSc solver failed:", e)
        sys.exit(1)
    raise

# Normalise pressure (determined only up to a constant)
p_h.x.array[:] -= domain_average(msh, p_h)

# Store solution at previous time level
u_n = fem.Function(V)
u_n.x.array[:] = u_h.x.array

# ===================================================================
# Convective terms + time stepping
# ===================================================================

# Upwind indicator: lmbda = 1 where u_n . n > 0 (outflow), else 0
lmbda = ufl.conditional(ufl.gt(ufl.dot(u_n, n_facet), 0), 1, 0)

# Upwind flux: sample trial function from the upwind side
u_uw = lmbda("+") * u("-") + lmbda("-") * u("+")

a_form += (
    ufl.inner(u / delta_t, v) * ufl.dx
    - ufl.inner(u, ufl.div(ufl.outer(v, u_n))) * ufl.dx
    + ufl.inner((ufl.dot(u_n, n_facet))("+") * u_uw, v("+")) * ufl.dS
    + ufl.inner((ufl.dot(u_n, n_facet))("-") * u_uw, v("-")) * ufl.dS
    + ufl.inner(ufl.dot(u_n, n_facet) * lmbda * u, v) * ufl.ds
)

L_form += (
    ufl.inner(u_n / delta_t, v) * ufl.dx
    - ufl.inner(ufl.dot(u_n, n_facet) * (1.0 - lmbda) * u_D, v) * ufl.ds
)

# ===================================================================
# Time-stepping loop
# ===================================================================

print(f"Time stepping ({num_time_steps} steps, "
      f"dt={float(delta_t.value):.4f}) ...")
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

    if (step + 1) % 10 == 0:
        print(f"  Step {step + 1}/{num_time_steps}")


# ===================================================================
# Error computation
# ===================================================================

print("Computing errors ...")
V_exact = fem.functionspace(msh, ("Lagrange", k + 3, (gdim,)))
Q_exact = fem.functionspace(msh, ("Lagrange", k + 2))

u_e = fem.Function(V_exact)
u_e.interpolate(u_exact_expr)

p_e = fem.Function(Q_exact)
p_e.interpolate(p_exact_expr)

e_u = norm_L2(msh.comm, u_h - u_e)
e_div_u = norm_L2(msh.comm, ufl.div(u_h))
p_e_avg = domain_average(msh, p_e)
e_p = norm_L2(msh.comm, p_h - (p_e - p_e_avg))

results = {
    "e_u": float(e_u),
    "e_div_u": float(e_div_u),
    "e_p": float(e_p),
    "converged": True,
}

with open("/app/results.json", "w") as fout:
    json.dump(results, fout, indent=2)

print(f"\nResults:")
print(f"  e_u     = {e_u:.5e}")
print(f"  e_div_u = {e_div_u:.5e}")
print(f"  e_p     = {e_p:.5e}")
print("Results written to /app/results.json")
