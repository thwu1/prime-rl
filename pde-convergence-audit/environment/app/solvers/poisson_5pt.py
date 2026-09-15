"""
Solver for the 2D Poisson equation: -nabla^2 u = f on (0,1)^2 with u=0 on boundary.

Manufactured solution: u*(x,y) = sin(pi*x)*sin(pi*y)
Source term: f(x,y) = 2*pi^2*sin(pi*x)*sin(pi*y)

Uses N interior grid points per direction with the standard 5-point finite
difference stencil for the Laplacian: (4*u_ij - u_{i+-1,j} - u_{i,j+-1}) / h^2.
"""
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve


def solve(N):
    """Solve at resolution N and return the L2 (RMS) error."""
    h = 1.0 / N  # grid spacing for N interior points
    x = np.linspace(h, 1.0 - h, N)
    y = np.linspace(h, 1.0 - h, N)
    X, Y = np.meshgrid(x, y, indexing="ij")

    u_exact = np.sin(np.pi * X) * np.sin(np.pi * Y)
    f_vals = 2.0 * np.pi**2 * np.sin(np.pi * X) * np.sin(np.pi * Y)

    # Build 2D Laplacian via Kronecker products: A = (T x I + I x T) / h^2
    ones = np.ones(N)
    T = sparse.diags([-ones[:-1], 2.0 * ones, -ones[:-1]], [-1, 0, 1], format="csr")
    I_N = sparse.eye(N, format="csr")
    A = (sparse.kron(T, I_N) + sparse.kron(I_N, T)) / h**2

    u_num = spsolve(A, f_vals.ravel()).reshape((N, N))
    return float(np.sqrt(np.mean((u_num - u_exact) ** 2)))
