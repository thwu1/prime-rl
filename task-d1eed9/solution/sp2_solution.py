"""
Solution: SP2 Density Matrix Purification Solver

"""
import numpy as np
from scipy.sparse import csr_matrix, eye as speye
from scipy.sparse.linalg import norm as spnorm


def gershgorin_bounds(H):
    """Compute Gershgorin circle theorem bounds on eigenvalue range."""
    diag = np.array(H.diagonal())
    H_abs = abs(H)
    row_sums = np.array(H_abs.sum(axis=1)).flatten() - np.abs(diag)
    emin = float(np.min(diag - row_sums))
    emax = float(np.max(diag + row_sums))
    return emin, emax


def sparse_sp2(H, n_occ, tol=1e-10, trunc_thresh=1e-6, max_iter=200):
    """Sparse SP2 density matrix purification with adaptive truncation."""
    n = H.shape[0]

    emin, emax = gershgorin_bounds(H)
    gap = emax - emin

    # X0 = (emax*I - H) / (emax - emin)
    X = (speye(n, format='csr') * emax - H.tocsr()) / gap

    n_iter = 0
    idem_err = float('inf')

    for i in range(max_iter):
        X2 = X @ X

        # Adaptive truncation: reduce threshold as we approach convergence
        # to allow final refinement
        trace_err = abs(X.diagonal().sum() - n_occ)
        if trace_err > 1.0:
            cur_thresh = trunc_thresh
        elif trace_err > 0.01:
            cur_thresh = trunc_thresh * 0.1
        else:
            cur_thresh = 0.0  # No truncation near convergence

        if cur_thresh > 0:
            X2.data[np.abs(X2.data) < cur_thresh] = 0.0
            X2.eliminate_zeros()

        # Trace-based branching
        tr_X2 = X2.diagonal().sum()
        tr_alt = 2.0 * X.diagonal().sum() - tr_X2

        if abs(tr_alt - n_occ) < abs(tr_X2 - n_occ):
            X = 2.0 * X - X2
        else:
            X = X2

        if cur_thresh > 0:
            X.data[np.abs(X.data) < cur_thresh] = 0.0
            X.eliminate_zeros()

        # Enforce symmetry
        X = (X + X.T) / 2.0
        if cur_thresh > 0:
            X.data[np.abs(X.data) < cur_thresh] = 0.0
            X.eliminate_zeros()

        # Check idempotency periodically
        if i % 5 == 4 or cur_thresh == 0:
            X2_check = X @ X
            idem_err = spnorm(X2_check - X, 'fro')
            n_iter = i + 1
            if idem_err < tol:
                break

    # Recompute final idempotency error on the converged matrix
    X2_final = X @ X
    idem_err = spnorm(X2_final - X, 'fro')

    return X, n_iter, idem_err


def compute_comm_volume(H, partition):
    """Compute communication volume for block-row distributed SpMM."""
    n_blocks = len(partition) - 1
    total_volume = 0

    H_csr = H.tocsr()

    for k in range(n_blocks):
        start = partition[k]
        end = partition[k + 1]

        # Collect unique non-local column indices for this block's rows
        nonlocal_cols = set()
        for row in range(start, end):
            row_start = H_csr.indptr[row]
            row_end = H_csr.indptr[row + 1]
            for idx in range(row_start, row_end):
                col = H_csr.indices[idx]
                if col < start or col >= end:
                    nonlocal_cols.add(col)

        total_volume += len(nonlocal_cols)

    return int(total_volume)


def optimal_partition(H, n_blocks):
    """Find row partition minimizing communication volume with load balance.

    Uses DP with incremental comm volume computation: for each candidate
    block [i, j), sweeps i backward from j-1, maintaining a running set of
    columns and a count of how many fall inside [i, j).
    """
    n = H.shape[0]
    H_csr = H.tocsr()

    row_nnz = np.diff(H_csr.indptr)
    cum_nnz = np.concatenate([[0], np.cumsum(row_nnz)])
    total_nnz = int(cum_nnz[-1])
    max_block_nnz = 1.5 * total_nnz / n_blocks

    INF = 10 ** 9

    # Level 1: single block [0, j), forward incremental
    dp_prev = [INF] * (n + 1)
    fwd_cols = set()
    fwd_local = 0
    for j in range(1, n + 1):
        # Column j-1 enters the local range [0, j)
        if (j - 1) in fwd_cols:
            fwd_local += 1
        # Add row j-1
        for idx in range(H_csr.indptr[j - 1], H_csr.indptr[j]):
            c = H_csr.indices[idx]
            if c not in fwd_cols:
                fwd_cols.add(c)
                if c < j:
                    fwd_local += 1
        if cum_nnz[j] <= max_block_nnz:
            dp_prev[j] = len(fwd_cols) - fwd_local

    all_parents = []

    for b in range(2, n_blocks + 1):
        dp_curr = [INF] * (n + 1)
        parent = [0] * (n + 1)

        for j in range(b, n + 1):
            # Sweep i backward; incrementally track block [i, j) columns
            blk_cols = set()
            blk_local = 0

            for i in range(j - 1, -1, -1):
                block_nnz = cum_nnz[j] - cum_nnz[i]
                if block_nnz > max_block_nnz:
                    break

                # Column i now enters the local range [i, j)
                if i in blk_cols:
                    blk_local += 1

                # Add row i's columns
                for idx in range(H_csr.indptr[i], H_csr.indptr[i + 1]):
                    c = H_csr.indices[idx]
                    if c not in blk_cols:
                        blk_cols.add(c)
                        if i <= c < j:
                            blk_local += 1

                if block_nnz <= 0:
                    continue

                comm = len(blk_cols) - blk_local

                if dp_prev[i] < INF:
                    cost = dp_prev[i] + comm
                    if cost < dp_curr[j]:
                        dp_curr[j] = cost
                        parent[j] = i

        all_parents.append(parent)
        dp_prev = dp_curr

    if dp_prev[n] >= INF:
        return [i * n // n_blocks for i in range(n_blocks + 1)]

    partition = [n]
    j = n
    for lvl in range(len(all_parents) - 1, -1, -1):
        j = all_parents[lvl][j]
        partition.append(j)
    partition.append(0)
    partition.reverse()

    return partition
