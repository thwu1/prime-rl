"""Graph construction and Laplacian computation for SGWT."""
import numpy as np


def build_laplacian(n_nodes, edges):
    """Build the combinatorial graph Laplacian L = D - W from an edge list.

    Parameters
    ----------
    n_nodes : int
        Number of vertices.
    edges : list of [src, dst, weight]
        Undirected edge triples. Each edge is stored once; the adjacency
        matrix is symmetrised internally.

    Returns
    -------
    L : ndarray, shape (n_nodes, n_nodes)
        Combinatorial graph Laplacian.
    """
    W = np.zeros((n_nodes, n_nodes))
    for edge in edges:
        i, j, w = int(edge[0]), int(edge[1]), float(edge[2])
        W[i, j] = w
        W[j, i] = w

    # Degree matrix — diagonal entries equal the vertex degree
    D = np.diag(np.sum(W > 0, axis=1).astype(float))
    L = D - W
    return L


def compute_fourier_basis(L):
    """Eigendecompose the graph Laplacian.

    Returns eigenvalues (ascending) and the corresponding eigenvectors.
    Tiny negative eigenvalues caused by floating-point noise are clamped
    to zero.
    """
    eigenvalues, eigenvectors = np.linalg.eigh(L)
    idx = np.argsort(eigenvalues)
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]
    eigenvalues = np.maximum(eigenvalues, 0.0)
    # Clamp to valid spectral range
    eigenvalues = np.clip(eigenvalues, 0, 2.0)
    return eigenvalues, eigenvectors
