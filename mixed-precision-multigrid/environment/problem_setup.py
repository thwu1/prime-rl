"""2D Poisson equation discretization: -Laplacian(u) = f on [0,1]^2, u=0 on boundary."""
import numpy as np
from scipy import sparse

GRID_SIZE = 63  # interior points per direction


def build_system():
    """Build the sparse linear system Au = b for the 2D Poisson equation.

    Uses the standard 5-point finite difference stencil (unscaled):
      diagonal = 4, off-diagonal = -1
    RHS is h^2 * f(x,y) where f(x,y) = 2*pi^2*sin(pi*x)*sin(pi*y).

    Returns (A, b, n) where A is n^2 x n^2 sparse matrix, b is n^2 vector.
    """
    n = GRID_SIZE
    h = 1.0 / (n + 1)

    e = np.ones(n)
    T = sparse.diags([-e[:-1], 2 * e, -e[:-1]], [-1, 0, 1], format='csr')
    I_n = sparse.eye(n, format='csr')
    A = sparse.kron(I_n, T, format='csr') + sparse.kron(T, I_n, format='csr')

    pts = np.linspace(h, 1.0 - h, n)
    X, Y = np.meshgrid(pts, pts)
    f_vals = 2.0 * np.pi ** 2 * np.sin(np.pi * X) * np.sin(np.pi * Y)
    b = (h ** 2 * f_vals).flatten()

    return A, b, n


def exact_solution(n):
    """Analytical solution u(x,y) = sin(pi*x)*sin(pi*y) at interior grid points."""
    h = 1.0 / (n + 1)
    pts = np.linspace(h, 1.0 - h, n)
    X, Y = np.meshgrid(pts, pts)
    return (np.sin(np.pi * X) * np.sin(np.pi * Y)).flatten()
