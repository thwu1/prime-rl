"""
Sparse differentiation via graph coloring and compressed finite differences.

Computes the Jacobian of a vector-valued function exploiting a known
sparsity pattern: columns that do not share any nonzero row can be
perturbed simultaneously in a single finite-difference probe.
"""
import numpy as np
from scipy import sparse


def column_connectivity_graph(S):
    """Build column-conflict adjacency graph from a sparsity pattern.

    Two columns conflict (are adjacent) if they both have a nonzero entry
    in at least one common row.

    Returns dict mapping each column index to the set of conflicting columns.
    """
    n_cols = S.shape[1]
    adj = {i: set() for i in range(n_cols)}
    S_csr = S.tocsr()

    for row in range(S.shape[0]):
        start, end = S_csr.indptr[row], S_csr.indptr[row + 1]
        nz_cols = S_csr.indices[start:end]
        for ii in range(len(nz_cols)):
            for jj in range(ii + 1, min(ii + 2, len(nz_cols))):
                ci, cj = int(nz_cols[ii]), int(nz_cols[jj])
                adj[ci].add(cj)
                adj[cj].add(ci)

    return adj


def greedy_coloring(adj, n_cols):
    """Greedy sequential distance-1 graph coloring.

    Returns np.array of 0-indexed color assignments (length n_cols).
    """
    colors = np.full(n_cols, -1, dtype=int)

    for node in range(n_cols):
        used = set()
        for nb in adj.get(node, set()):
            if colors[nb] >= 0:
                used.add(colors[nb])
        c = 0
        while c in used:
            c += 1
        colors[node] = c

    return colors


def compressed_jacobian(f, x, sparsity, coloring, eps=1e-7):
    """Compute sparse Jacobian via compressed (grouped) finite differences.

    Columns sharing the same color are perturbed simultaneously, and
    individual entries are recovered using the known sparsity pattern.

    Returns scipy.sparse.csc_matrix.
    """
    n = len(x)
    n_colors = int(np.max(coloring)) + 1
    f0 = f(x)

    S_csc = sparsity.tocsc()
    jac_rows, jac_cols, jac_data = [], [], []

    for c in range(n_colors):
        seed = np.zeros(n)
        col_indices = np.where(coloring == c)[0]
        seed[col_indices] = 1.0

        compressed = (f(x + eps * seed) - f0) / eps

        for j in col_indices:
            start, end = S_csc.indptr[j], S_csc.indptr[j + 1]
            for row in S_csc.indices[start:end]:
                jac_rows.append(int(row))
                jac_cols.append(int(j))
                jac_data.append(compressed[int(row)])

    return sparse.csc_matrix((jac_data, (jac_rows, jac_cols)), shape=(n, n))
