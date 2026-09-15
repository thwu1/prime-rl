#!/usr/bin/env python3
"""
Build the complete DG Navier-Stokes solver by replacing the
NotImplementedError section in the skeleton with a working
implementation.

"""

SOLVER_PATH = "/app/solver.py"

# ------------------------------------------------------------------
# Read the skeleton and locate the boundaries of the TODO section
# ------------------------------------------------------------------

with open(SOLVER_PATH) as f:
    lines = f.readlines()

# Find the line with NotImplementedError and the error computation header
impl_line = None
error_section_line = None
for i, line in enumerate(lines):
    if "raise NotImplementedError" in line:
        impl_line = i
    if "ERROR COMPUTATION" in line and "===" in line:
        error_section_line = i
        break

assert impl_line is not None, "Could not find NotImplementedError in skeleton"
assert error_section_line is not None, "Could not find ERROR COMPUTATION section"

# Find start of the IMPLEMENT block (the comment header)
impl_block_start = impl_line
for i in range(impl_line, -1, -1):
    if "IMPLEMENT YOUR SOLVER BELOW" in lines[i]:
        impl_block_start = i
        break

# ------------------------------------------------------------------
# The implementation code
# ------------------------------------------------------------------

implementation = '''\
# --- Function spaces ---
# RT_{k+1} for velocity (H(div)-conforming) and DG_k for pressure
# so that div(V_h) = Q_h, ensuring pointwise mass conservation.
V = fem.functionspace(msh, ("Raviart-Thomas", k + 1))
Q = fem.functionspace(msh, ("Discontinuous Lagrange", k))
VQ = ufl.MixedFunctionSpace(V, Q)

# Auxiliary DG space for body force interpolation
W = fem.functionspace(msh, ("Discontinuous Lagrange", k + 1, (gdim,)))

# Trial / test functions
u, p = ufl.TrialFunctions(VQ)
v, q = ufl.TestFunctions(VQ)

# Time step
delta_t = fem.Constant(msh, default_real_type(t_end / num_time_steps))

# SIP penalty parameter — must scale as O(k^2) for coercivity
alpha = fem.Constant(msh, default_real_type(6.0 * k**2))

h = ufl.CellDiameter(msh)
n_facet = ufl.FacetNormal(msh)


def jump(phi, n):
    """Jump of a vector-valued function across an interior facet."""
    return ufl.outer(phi("+"), n("+")) + ufl.outer(phi("-"), n("-"))


# --- SIP viscous bilinear form ---
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

# --- Pressure-velocity coupling (saddle-point structure) ---
a_form -= ufl.inner(p, ufl.div(v)) * ufl.dx
a_form -= ufl.inner(ufl.div(u), q) * ufl.dx

# --- Right-hand side ---
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

# --- Boundary conditions (strong Dirichlet on normal velocity DOFs) ---
msh.topology.create_connectivity(msh.topology.dim - 1, msh.topology.dim)
boundary_facets = mesh.exterior_facet_indices(msh.topology)
boundary_vel_dofs = fem.locate_dofs_topological(
    V, msh.topology.dim - 1, boundary_facets
)
bc_u = fem.dirichletbc(u_D, boundary_vel_dofs)
bcs = [bc_u]

# --- Solver configuration (direct LU via MUMPS) ---
# ICNTL(24)=1 and ICNTL(25)=0 enable null-pivot detection for
# the singular saddle-point system (pressure determined up to constant).
solver_options = {
    "ksp_type": "preonly",
    "pc_type": "lu",
    "pc_factor_mat_solver_type": "mumps",
    "mat_mumps_icntl_14": 80,
    "mat_mumps_icntl_24": 1,
    "mat_mumps_icntl_25": 0,
    "ksp_error_if_not_converged": 1,
}

# --- Initial Stokes solve ---
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

# --- Convective terms + time stepping ---
# Upwind indicator: lmbda = 1 where u_n . n > 0 (outflow), else 0
lmbda = ufl.conditional(ufl.gt(ufl.dot(u_n, n_facet), 0), 1, 0)

# Upwind flux: sample trial function from the upwind side
u_uw = lmbda("+") * u("+") + lmbda("-") * u("-")

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

# --- Time-stepping loop ---
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

'''

# ------------------------------------------------------------------
# Assemble the complete file
# ------------------------------------------------------------------

with open(SOLVER_PATH, "w") as f:
    # Write everything before the IMPLEMENT block
    for i in range(impl_block_start):
        f.write(lines[i])

    # Write a blank line separator, then the implementation
    f.write("\n")
    f.write(implementation)
    f.write("\n")

    # Write everything from the ERROR COMPUTATION section onward
    for i in range(error_section_line, len(lines)):
        f.write(lines[i])

print(f"Solver implementation written to {SOLVER_PATH}")
