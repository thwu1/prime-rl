"""
Finite difference assembly for 2D elliptic PDEs.
"""

from sparse_matrix import SparseMatrix


def build_laplacian_2d(nx, ny, dx=1.0):
    """
    Assemble the 2D negative-Laplacian using a 5-point stencil.

    Discretizes -nabla^2 u on an nx x ny grid. Unknowns are ordered
    in row-major fashion: index = j * nx + i for grid point (i, j).

    At interior points the stencil is:
        (-u_{i-1,j} - u_{i+1,j} - u_{i,j-1} - u_{i,j+1} + 4*u_{i,j}) / dx^2

    Points on the grid boundary use a truncated stencil (missing
    neighbours correspond to Dirichlet u = 0 outside the domain),
    so the diagonal is always 4/dx^2 and each valid in-grid neighbour
    contributes -1/dx^2.

    Args:
        nx: int, grid points in x
        ny: int, grid points in y
        dx: float, grid spacing

    Returns:
        SparseMatrix of dimension (nx * ny)
    """
    raise NotImplementedError("Implement 2D Laplacian assembly")
