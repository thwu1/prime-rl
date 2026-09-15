"""
Steady Kovasznay flow solver using Taylor-Hood (P2-P1) finite elements
with Picard (fixed-point) linearization.

Solves the steady incompressible Navier-Stokes equations:
    -nu * laplacian(u) + (u . nabla)u + grad(p) = 0   in Omega
    div(u) = 0                                          in Omega
with exact Kovasznay boundary conditions on all of dOmega.

The Picard iteration linearizes the convective term by replacing the
convecting velocity with the previous iteration's solution:
    (u_n . nabla) u

Output: /app/results.json with L2 error norms vs exact solution.
"""
from mpi4py import MPI
from petsc4py import PETSc

import numpy as np
import json

import ufl
from basix.ufl import element, mixed_element
from dolfinx import default_real_type, fem, mesh
from dolfinx.fem.petsc import (
    assemble_matrix,
    assemble_vector,
    apply_lifting,
)

if np.issubdtype(PETSc.ScalarType, np.complexfloating):
    print("This solver requires DOLFINx real mode, not complex mode.")
    exit(0)

# =====================================================
# Physical and numerical parameters
# =====================================================
Re = 25.0                 # Reynolds number (nu = 1/Re)
n_cells = 24              # Mesh divisions per direction
k = 2                     # Velocity polynomial degree (pressure is k-1)
max_picard_iter = 50      # Maximum Picard iterations
picard_atol = 1e-8        # Picard absolute tolerance on increment norm

# =====================================================
# Exact Kovasznay solution
# =====================================================
lmbda = Re / 2.0 - np.sqrt(Re**2 / 4.0 + 4.0 * np.pi**2)


def u_exact(x):
    """Exact velocity field for Kovasznay flow."""
    return np.vstack((
        1.0 - np.exp(lmbda * x[0]) * np.cos(2.0 * np.pi * x[1]),
        (lmbda / (2.0 * np.pi)) * np.exp(lmbda * x[0]) * np.sin(2.0 * np.pi * x[1]),
    ))


def p_exact(x):
    """Exact pressure field for Kovasznay flow."""
    return -0.5 * np.exp(2.0 * lmbda * x[0])


# =====================================================
# Mesh: [-0.5, 1.5] x [-0.5, 1.5]
# =====================================================
domain = mesh.create_rectangle(
    MPI.COMM_WORLD,
    [np.array([-0.5, -0.5]), np.array([1.5, 1.5])],
    [n_cells, n_cells],
    mesh.CellType.triangle,
)
gdim = domain.geometry.dim

# =====================================================
# Taylor-Hood function space P2-P1
# =====================================================
vel_elem = element("Lagrange", domain.basix_cell(), k, shape=(gdim,), dtype=default_real_type)
pres_elem = element("Lagrange", domain.basix_cell(), k - 1, dtype=default_real_type)
TH = mixed_element([vel_elem, pres_elem])
W = fem.functionspace(domain, TH)

# Velocity sub-space (collapsed) for BCs and Picard convecting field
W0 = W.sub(0)
V_collapsed, _ = W0.collapse()

# =====================================================
# Dirichlet boundary conditions
# =====================================================
u_D = fem.Function(V_collapsed)
u_D.interpolate(u_exact)

fdim = domain.topology.dim - 1

# Locate boundary facets
facets_left = mesh.locate_entities_boundary(domain, fdim, lambda x: np.isclose(x[0], -0.5))
facets_bottom = mesh.locate_entities_boundary(domain, fdim, lambda x: np.isclose(x[1], -0.5))
facets_top = mesh.locate_entities_boundary(domain, fdim, lambda x: np.isclose(x[1], 1.5))

# Locate DOFs on boundary facets
dofs_left = fem.locate_dofs_topological((W0, V_collapsed), fdim, facets_left)
dofs_bottom = fem.locate_dofs_topological((W0, V_collapsed), fdim, facets_bottom)
dofs_top = fem.locate_dofs_topological((W0, V_collapsed), fdim, facets_top)

bcs = [
    fem.dirichletbc(u_D, dofs_left, W0),
    fem.dirichletbc(u_D, dofs_bottom, W0),
    fem.dirichletbc(u_D, dofs_top, W0),
]

# =====================================================
# Solution functions
# =====================================================
w_h = fem.Function(W)            # Current solution (u_h, p_h)
w_prev = fem.Function(W)         # Previous Picard iterate
u_n = fem.Function(V_collapsed)  # Convecting velocity for Picard

# =====================================================
# Variational formulation (Picard-linearized NS)
# =====================================================
(u, p) = ufl.TrialFunctions(W)
(v, q) = ufl.TestFunctions(W)

a_form = (
    Re * ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx
    + ufl.inner(ufl.dot(ufl.grad(u), u_n), v) * ufl.dx
    + ufl.inner(p, ufl.div(v)) * ufl.dx
    - ufl.inner(ufl.div(u), q) * ufl.dx
)

zero_vec = fem.Constant(domain, (PETSc.ScalarType(0.0), PETSc.ScalarType(0.0)))
zero_scalar = fem.Constant(domain, PETSc.ScalarType(0.0))
L_form = ufl.inner(zero_vec, v) * ufl.dx + ufl.inner(zero_scalar, q) * ufl.dx

# =====================================================
# Compile forms (coefficients are read at assembly time)
# =====================================================
a_compiled = fem.form(a_form)
L_compiled = fem.form(L_form)

# =====================================================
# Picard iteration loop
# =====================================================
print("Starting Picard iteration...")
n_iters = 0

for iteration in range(max_picard_iter):
    # Assemble system matrix and RHS vector
    A = assemble_matrix(a_compiled, bcs=bcs)
    A.assemble()

    b = assemble_vector(L_compiled)
    apply_lifting(b, [a_compiled], bcs=[bcs])
    b.ghostUpdate(addv=PETSc.InsertMode.ADD, mode=PETSc.ScatterMode.REVERSE)
    for bc in bcs:
        bc.set(b.array_w)

    # Configure direct solver (MUMPS LU)
    ksp = PETSc.KSP().create(domain.comm)
    ksp.setOperators(A)
    ksp.setType("preonly")
    pc = ksp.getPC()
    pc.setType("lu")
    use_superlu = PETSc.IntType == np.int64
    if PETSc.Sys().hasExternalPackage("mumps") and not use_superlu:
        pc.setFactorSolverType("mumps")
        pc.setFactorSetUpSolverType()
        pc.getFactorMatrix().setMumpsIcntl(icntl=14, ival=80)
        pc.getFactorMatrix().setMumpsIcntl(icntl=24, ival=1)
        pc.getFactorMatrix().setMumpsIcntl(icntl=25, ival=0)
    else:
        pc.setFactorSolverType("superlu_dist")

    try:
        ksp.solve(b, w_h.x.petsc_vec)
    except PETSc.Error as e:
        if e.ierr == 92:
            print(f"MUMPS solver failed at Picard iteration {iteration}: {e}")
            break
        raise
    w_h.x.scatter_forward()

    # Compute increment norm for convergence check
    increment_norm = np.linalg.norm(w_h.x.array - w_prev.x.array)
    print(f"  Iteration {iteration}: ||delta w|| = {increment_norm:.6e}")

    # Store current solution as previous
    w_prev.x.array[:] = w_h.x.array
    n_iters = iteration + 1

    # Clean up PETSc objects
    ksp.destroy()
    A.destroy()
    b.destroy()

    if increment_norm < picard_atol:
        print(f"Picard converged after {n_iters} iterations.")
        break
else:
    print(f"WARNING: Picard did not converge within {max_picard_iter} iterations.")

# =====================================================
# Post-processing: compute L2 errors vs exact solution
# =====================================================
u_h = w_h.sub(0).collapse()
p_h = w_h.sub(1).collapse()

# Higher-order space for accurate exact-solution representation
V_exact = fem.functionspace(domain, ("Lagrange", k + 3, (gdim,)))
Q_exact = fem.functionspace(domain, ("Lagrange", k + 3))

u_ex = fem.Function(V_exact)
u_ex.interpolate(u_exact)

p_ex = fem.Function(Q_exact)
p_ex.interpolate(p_exact)

# L2 velocity error
e_u = np.sqrt(domain.comm.allreduce(
    fem.assemble_scalar(fem.form(ufl.inner(u_h - u_ex, u_h - u_ex) * ufl.dx)),
    op=MPI.SUM,
))

# Pressure: subtract domain mean (pressure determined only up to constant)
vol = domain.comm.allreduce(
    fem.assemble_scalar(fem.form(fem.Constant(domain, default_real_type(1.0)) * ufl.dx)),
    op=MPI.SUM,
)
p_h_mean = domain.comm.allreduce(
    fem.assemble_scalar(fem.form(p_h * ufl.dx)), op=MPI.SUM
) / vol
p_ex_mean = domain.comm.allreduce(
    fem.assemble_scalar(fem.form(p_ex * ufl.dx)), op=MPI.SUM
) / vol

e_p = np.sqrt(domain.comm.allreduce(
    fem.assemble_scalar(fem.form(
        ufl.inner((p_h - p_h_mean) - (p_ex - p_ex_mean),
                   (p_h - p_h_mean) - (p_ex - p_ex_mean)) * ufl.dx
    )),
    op=MPI.SUM,
))

# Divergence of computed velocity
e_div = np.sqrt(domain.comm.allreduce(
    fem.assemble_scalar(fem.form(ufl.inner(ufl.div(u_h), ufl.div(u_h)) * ufl.dx)),
    op=MPI.SUM,
))

# =====================================================
# Output results
# =====================================================
print(f"\n{'=' * 50}")
print(f"Results:")
print(f"  L2 velocity error:  {e_u:.6e}")
print(f"  L2 pressure error:  {e_p:.6e}")
print(f"  Divergence (L2):    {e_div:.6e}")
print(f"  Picard iterations:  {n_iters}")
print(f"{'=' * 50}")

results = {
    "e_u": float(e_u),
    "e_p": float(e_p),
    "e_div": float(e_div),
    "iterations": int(n_iters),
}

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Results written to /app/results.json")
