"""
Utility functions for the Kovasznay flow problem using FEniCSx/DOLFINx.

Provides mesh creation, exact analytical solutions for Kovasznay flow
at Re=25, error computation against exact solutions, and helper norms.

"""

import numpy as np
from mpi4py import MPI

import ufl
from dolfinx import default_real_type, fem, mesh


# ===================================================================
# Physical and discretization parameters
# ===================================================================

Re = 25.0   # Reynolds number
k = 1       # Polynomial degree for the pressure space


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
# Kovasznay analytical solution
# ===================================================================

def u_exact_expr(x):
    """Exact velocity for Kovasznay flow at Re=25.

    Returns a (2, N) array of velocity components.
    """
    lam = Re / 2.0 - np.sqrt(Re**2 / 4.0 + 4.0 * np.pi**2)
    return np.vstack((
        1.0 - np.exp(lam * x[0]) * np.cos(2.0 * np.pi * x[1]),
        lam / (2.0 * np.pi)
        * np.exp(lam * x[0])
        * np.sin(2.0 * np.pi * x[1]),
    ))


def p_exact_expr(x):
    """Exact pressure for Kovasznay flow at Re=25."""
    lam = Re / 2.0 - np.sqrt(Re**2 / 4.0 + 4.0 * np.pi**2)
    return 0.5 * (1.0 - np.exp(2.0 * lam * x[0]))


# ===================================================================
# Mesh creation
# ===================================================================

def create_mesh(n_cells):
    """Create an n_cells x n_cells unit-square mesh."""
    return mesh.create_unit_square(MPI.COMM_WORLD, n_cells, n_cells)


# ===================================================================
# Error computation
# ===================================================================

def compute_errors(msh, u_h, p_h):
    """Compute L2 errors and divergence norm against exact Kovasznay solution.

    Args:
        msh: DOLFINx mesh
        u_h: computed velocity (fem.Function in H(div) space)
        p_h: computed pressure (fem.Function)

    Returns:
        dict with keys:
            e_u     — velocity L2 error
            e_div_u — divergence L2 norm (should be ~eps for div-conforming)
            e_p     — pressure L2 error (zero-mean normalized)
    """
    gdim = msh.geometry.dim
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

    return {
        "e_u": float(e_u),
        "e_div_u": float(e_div_u),
        "e_p": float(e_p),
    }
