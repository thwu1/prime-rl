"""
Triangular mesh utilities for the unit square [0,1]^2.
"""
import numpy as np


def unit_square_mesh(n):
    """Generate a structured triangular mesh of [0,1]^2.

    Divides the unit square into n x n squares, each split into 2 triangles.

    Args:
        n: number of subdivisions per side.

    Returns:
        coords: (N_vertices, 2) float array of vertex coordinates.
        cells: (N_cells, 3) int array of triangle vertex indices.
            Each row [v0, v1, v2] defines a triangle with positive orientation.
    """
    coords = []
    for j in range(n + 1):
        for i in range(n + 1):
            coords.append([float(i) / n, float(j) / n])
    coords = np.array(coords)

    cells = []
    for j in range(n):
        for i in range(n):
            bl = j * (n + 1) + i
            br = bl + 1
            tl = bl + (n + 1)
            tr = tl + 1
            cells.append([bl, br, tr])
            cells.append([bl, tr, tl])
    cells = np.array(cells, dtype=int)

    return coords, cells


def boundary_nodes(coords):
    """Return sorted array of indices of nodes on the boundary of [0,1]^2.

    A node is on the boundary if any coordinate equals 0 or 1 (within tolerance).
    """
    x, y = coords[:, 0], coords[:, 1]
    tol = 1e-10
    return np.sort(
        np.where((x < tol) | (x > 1 - tol) | (y < tol) | (y > 1 - tol))[0]
    )
