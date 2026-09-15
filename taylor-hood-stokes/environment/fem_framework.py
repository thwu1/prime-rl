
"""
Finite element framework utilities for P2-P1 Taylor-Hood elements.

Provides mesh generation, quadrature rules, and basis function
evaluation on a structured triangular mesh of [0,1]^2.
"""

import numpy as np


# ==================================================================
# Quadrature: 7-point Dunavant rule on reference triangle
# [(0,0), (1,0), (0,1)], exact for degree <= 5.
# Weights sum to 1/2 (area of reference triangle).
# ==================================================================

def gauss_triangle_7pt():
    """Return (points, weights) for 7-point quadrature on reference triangle."""
    s15 = np.sqrt(15.0)
    a1 = (6.0 - s15) / 21.0
    a2 = (6.0 + s15) / 21.0
    w0 = 9.0 / 80.0
    w1 = (155.0 - s15) / 2400.0
    w2 = (155.0 + s15) / 2400.0
    points = np.array([
        [1.0 / 3.0, 1.0 / 3.0],
        [a1, a1],
        [1.0 - 2.0 * a1, a1],
        [a1, 1.0 - 2.0 * a1],
        [a2, a2],
        [1.0 - 2.0 * a2, a2],
        [a2, 1.0 - 2.0 * a2],
    ])
    weights = np.array([w0, w1, w1, w1, w2, w2, w2])
    return points, weights


# ==================================================================
# P2 basis functions on reference triangle.
#
# Nodes (local numbering):
#   0: (0,0)     1: (1,0)       2: (0,1)
#   3: (0.5,0)   4: (0.5,0.5)   5: (0,0.5)
#
# Barycentric coords: lam0 = 1-xi-eta, lam1 = xi, lam2 = eta
#
# phi_0 = lam0*(2*lam0 - 1)
# phi_1 = lam1*(2*lam1 - 1)
# phi_2 = lam2*(2*lam2 - 1)
# phi_3 = 4*lam0*lam1       (midpoint of edge 0-1)
# phi_4 = 4*lam1*lam2       (midpoint of edge 1-2)
# phi_5 = 4*lam0*lam2       (midpoint of edge 0-2)
# ==================================================================

def p2_basis(xi, eta):
    """Evaluate P2 basis functions and their reference-space gradients.

    Args:
        xi, eta: reference coordinates

    Returns:
        phi: shape function values (6,)
        dphi_dxi: xi-derivatives (6,)
        dphi_deta: eta-derivatives (6,)
    """
    lam0 = 1.0 - xi - eta
    lam1 = xi
    lam2 = eta

    phi = np.array([
        lam0 * (2.0 * lam0 - 1.0),
        lam1 * (2.0 * lam1 - 1.0),
        lam2 * (2.0 * lam2 - 1.0),
        4.0 * lam0 * lam1,
        4.0 * lam1 * lam2,
        4.0 * lam0 * lam2,
    ])

    dphi_dxi = np.array([
        4.0 * xi + 4.0 * eta - 3.0,
        4.0 * xi - 1.0,
        0.0,
        4.0 - 8.0 * xi - 4.0 * eta,
        4.0 * eta,
        -4.0 * eta,
    ])

    dphi_deta = np.array([
        4.0 * xi + 4.0 * eta - 3.0,
        0.0,
        4.0 * eta - 1.0,
        -4.0 * xi,
        4.0 * xi,
        4.0 - 4.0 * xi - 8.0 * eta,
    ])

    return phi, dphi_dxi, dphi_deta


# ==================================================================
# P1 basis functions on reference triangle.
# ==================================================================

def p1_basis(xi, eta):
    """Evaluate P1 basis functions and their reference-space gradients.

    Args:
        xi, eta: reference coordinates

    Returns:
        psi: shape function values (3,)
        dpsi_dxi: xi-derivatives (3,)
        dpsi_deta: eta-derivatives (3,)
    """
    psi = np.array([1.0 - xi - eta, xi, eta])
    dpsi_dxi = np.array([-1.0, 1.0, 0.0])
    dpsi_deta = np.array([-1.0, 0.0, 1.0])
    return psi, dpsi_dxi, dpsi_deta


# ==================================================================
# Mesh generation: structured triangular mesh on [0,1]^2.
#
# P2 nodes live on a (2n+1)x(2n+1) grid.
# P1 nodes live on a (n+1)x(n+1) grid.
# Each square cell is split into 2 triangles by the diagonal
# from corner (i,j) to corner (i+1,j+1).
#
# Triangle 1 (lower-right): vertices (i,j)-(i+1,j)-(i+1,j+1)
# Triangle 2 (upper-left):  vertices (i,j)-(i+1,j+1)-(i,j+1)
#
# For each triangle, P2 element connectivity lists 6 nodes:
#   [vertex0, vertex1, vertex2, mid01, mid12, mid02]
# where mid_ab is the midpoint of edge from local node a to local node b.
# ==================================================================

def generate_mesh(n):
    """Generate a structured triangular mesh on [0,1]^2.

    Args:
        n: number of divisions per side

    Returns:
        coords_p2: P2 node coordinates, shape (n_p2, 2)
        elems_p2: P2 element connectivity, shape (n_elem, 6)
        coords_p1: P1 node coordinates, shape (n_p1, 2)
        elems_p1: P1 element connectivity, shape (n_elem, 3)
    """
    m = 2 * n + 1  # P2 grid side length

    # P2 coordinates
    x2 = np.linspace(0.0, 1.0, m)
    y2 = np.linspace(0.0, 1.0, m)
    X2, Y2 = np.meshgrid(x2, y2)
    coords_p2 = np.column_stack([X2.ravel(), Y2.ravel()])

    # P1 coordinates
    x1 = np.linspace(0.0, 1.0, n + 1)
    y1 = np.linspace(0.0, 1.0, n + 1)
    X1, Y1 = np.meshgrid(x1, y1)
    coords_p1 = np.column_stack([X1.ravel(), Y1.ravel()])

    n_elem = 2 * n * n
    elems_p2 = np.empty((n_elem, 6), dtype=int)
    elems_p1 = np.empty((n_elem, 3), dtype=int)

    e = 0
    for j in range(n):
        for i in range(n):
            # P1 vertex indices
            v00 = j * (n + 1) + i
            v10 = j * (n + 1) + (i + 1)
            v01 = (j + 1) * (n + 1) + i
            v11 = (j + 1) * (n + 1) + (i + 1)

            # P2 node indices
            c00 = (2 * j) * m + (2 * i)
            c10 = (2 * j) * m + (2 * i + 2)
            c01 = (2 * j + 2) * m + (2 * i)
            c11 = (2 * j + 2) * m + (2 * i + 2)

            m_bot = (2 * j) * m + (2 * i + 1)
            m_right = (2 * j + 1) * m + (2 * i + 2)
            m_top = (2 * j + 2) * m + (2 * i + 1)
            m_left = (2 * j + 1) * m + (2 * i)
            m_diag = (2 * j + 1) * m + (2 * i + 1)

            # Triangle 1 (lower-right): (i,j) -> (i+1,j) -> (i+1,j+1)
            # Local nodes: 0=c00, 1=c10, 2=c11
            # mid01=m_bot, mid12=m_right, mid02=m_diag
            elems_p2[e] = [c00, c10, c11, m_bot, m_right, m_diag]
            elems_p1[e] = [v00, v10, v11]
            e += 1

            # Triangle 2 (upper-left): (i,j) -> (i+1,j+1) -> (i,j+1)
            # Local nodes: 0=c00, 1=c11, 2=c01
            # mid01=m_diag, mid12=m_top, mid02=m_left
            elems_p2[e] = [c00, c11, c01, m_diag, m_top, m_left]
            elems_p1[e] = [v00, v11, v01]
            e += 1

    return coords_p2, elems_p2, coords_p1, elems_p1
