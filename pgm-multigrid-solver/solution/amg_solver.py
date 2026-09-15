#!/usr/bin/env python3
"""
Algebraic Multigrid (AMG) preconditioned Conjugate Gradient solver
using Parallel Graph Matching (PGM) coarsening.

Inspired by the Ginkgo HPC library's multigrid framework.
"""

import argparse
import json
import sys

import numpy as np
from scipy import sparse
from scipy.io import mmread
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import spsolve


def pgm_coarsen(A):
    """
    Parallel Graph Matching (PGM) aggregation-based coarsening.

    Builds a strength-of-connection graph from |a_ij| (off-diagonal entries),
    then performs greedy maximal matching: each unmatched vertex is paired with
    its strongest unmatched neighbor.  Unmatched vertices become singleton
    aggregates.  Returns injection prolongation P and coarse-grid size.
    """
    n = A.shape[0]
    A_csr = A.tocsr()
    indptr = A_csr.indptr
    indices = A_csr.indices
    data = A_csr.data

    agg = np.full(n, -1, dtype=np.int64)
    matched = np.zeros(n, dtype=bool)

    # Greedy matching: process vertices in order, match with strongest
    # unmatched neighbor
    for i in range(n):
        if matched[i]:
            continue

        start, end = indptr[i], indptr[i + 1]
        best_j = -1
        best_s = 0.0

        for idx in range(start, end):
            j = indices[idx]
            if j == i or matched[j]:
                continue
            s = abs(data[idx])
            if s > best_s:
                best_s = s
                best_j = j

        if best_j >= 0:
            matched[i] = True
            matched[best_j] = True
            agg[i] = i
            agg[best_j] = i
        else:
            # No unmatched neighbor: singleton
            agg[i] = i

    # Assign remaining unmatched vertices (shouldn't happen, but safety)
    for i in range(n):
        if agg[i] < 0:
            agg[i] = i

    # Renumber aggregates contiguously
    unique_ids = np.unique(agg)
    id_map = np.empty(n, dtype=np.int64)
    for new_id, old_id in enumerate(unique_ids):
        id_map[old_id] = new_id
    agg_contiguous = id_map[agg]
    n_coarse = len(unique_ids)

    # Build prolongation P (n x n_coarse): P[i, agg[i]] = 1
    rows_p = np.arange(n)
    cols_p = agg_contiguous
    vals_p = np.ones(n)
    P = csr_matrix((vals_p, (rows_p, cols_p)), shape=(n, n_coarse))

    return P, n_coarse


class AMGHierarchy:
    """Algebraic multigrid hierarchy with PGM coarsening."""

    def __init__(self, A, max_levels=15, min_coarse=50):
        self.As = [A.tocsr()]
        self.Ps = []
        self.Rs = []
        self._D_invs = []

        current_A = self.As[0]

        for _ in range(max_levels - 1):
            if current_A.shape[0] <= min_coarse:
                break

            P, n_coarse = pgm_coarsen(current_A)

            if n_coarse >= current_A.shape[0]:
                # Coarsening stalled
                break

            R = P.T.tocsr()
            coarse_A = (R @ current_A @ P).tocsr()

            self.Ps.append(P)
            self.Rs.append(R)
            self.As.append(coarse_A)

            current_A = coarse_A

        # Cache diagonal inverses for weighted Jacobi
        for A_level in self.As:
            diag = A_level.diagonal().copy()
            diag[diag == 0] = 1.0
            self._D_invs.append(1.0 / diag)

    @property
    def n_levels(self):
        return len(self.As)

    @property
    def level_sizes(self):
        return [A.shape[0] for A in self.As]

    @property
    def grid_complexity(self):
        return sum(A.shape[0] for A in self.As) / self.As[0].shape[0]

    @property
    def operator_complexity(self):
        return sum(A.nnz for A in self.As) / self.As[0].nnz

    def v_cycle(self, b, x=None, level=0, omega=0.67,
                pre_sweeps=2, post_sweeps=2):
        """Apply one V-cycle starting from the given level."""
        A = self.As[level]
        D_inv = self._D_invs[level]

        if x is None:
            x = np.zeros(A.shape[0])
        else:
            x = x.copy()

        # Coarsest level: direct solve
        if level == self.n_levels - 1:
            return spsolve(A, b)

        # Pre-smoothing: weighted Jacobi
        for _ in range(pre_sweeps):
            r = b - A @ x
            x += omega * D_inv * r

        # Restrict residual to coarse grid
        r = b - A @ x
        r_coarse = self.Rs[level] @ r

        # Solve on coarse grid (recursive V-cycle)
        e_coarse = self.v_cycle(r_coarse, level=level + 1, omega=omega,
                                pre_sweeps=pre_sweeps, post_sweeps=post_sweeps)

        # Prolongate correction
        x += self.Ps[level] @ e_coarse

        # Post-smoothing: weighted Jacobi
        for _ in range(post_sweeps):
            r = b - A @ x
            x += omega * D_inv * r

        return x


def pcg(A, b, preconditioner, tol=1e-8, maxiter=200):
    """
    Preconditioned Conjugate Gradient method.

    Parameters
    ----------
    A : sparse matrix
    b : right-hand side vector
    preconditioner : callable, returns M^{-1} r
    tol : relative residual tolerance
    maxiter : maximum iterations

    Returns
    -------
    x, iterations, residual_norm, converged
    """
    n = A.shape[0]
    x = np.zeros(n)
    r = b.copy()

    b_norm = np.linalg.norm(b)
    if b_norm == 0:
        return x, 0, 0.0, True

    z = preconditioner(r)
    p = z.copy()
    rz = np.dot(r, z)

    for k in range(1, maxiter + 1):
        Ap = A @ p
        pAp = np.dot(p, Ap)

        if pAp <= 0:
            # Preconditioner or matrix issue; break
            break

        alpha = rz / pAp
        x = x + alpha * p
        r = r - alpha * Ap

        r_norm = np.linalg.norm(r)
        if r_norm / b_norm < tol:
            return x, k, r_norm, True

        z = preconditioner(r)
        rz_new = np.dot(r, z)
        beta = rz_new / rz
        p = z + beta * p
        rz = rz_new

    # Compute true residual at exit
    true_res = np.linalg.norm(b - A @ x)
    return x, k if 'k' in dir() else maxiter, true_res, (true_res / b_norm < tol)


def main():
    parser = argparse.ArgumentParser(
        description="AMG-preconditioned CG solver with PGM coarsening"
    )
    parser.add_argument("--matrix", required=True,
                        help="Path to Matrix Market file")
    parser.add_argument("--tol", type=float, default=1e-8,
                        help="Relative residual tolerance")
    parser.add_argument("--maxiter", type=int, default=200,
                        help="Maximum CG iterations")
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")
    args = parser.parse_args()

    # Read matrix
    A = mmread(args.matrix)
    if not sparse.issparse(A):
        A = csr_matrix(A)
    else:
        A = A.tocsr()
    A = A.astype(np.float64)
    n = A.shape[0]

    # RHS: b = [1, 1, ..., 1]^T
    b = np.ones(n)

    # Build AMG hierarchy
    mg = AMGHierarchy(A, max_levels=15, min_coarse=50)

    # Preconditioner: one V-cycle
    def precond(r):
        return mg.v_cycle(r.copy())

    # Solve
    x, iters, res_norm, converged = pcg(
        A, b, precond, tol=args.tol, maxiter=args.maxiter
    )

    # True residual
    true_res = np.linalg.norm(b - A @ x)
    b_norm = np.linalg.norm(b)
    rel_res = true_res / b_norm if b_norm > 0 else 0.0

    results = {
        "iterations": int(iters),
        "residual_norm": float(true_res),
        "relative_residual": float(rel_res),
        "converged": bool(converged),
        "grid_complexity": float(mg.grid_complexity),
        "operator_complexity": float(mg.operator_complexity),
        "n_levels": int(mg.n_levels),
        "level_sizes": [int(s) for s in mg.level_sizes],
    }

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    print(f"{'Converged' if converged else 'FAILED'} in {iters} iterations")
    print(f"Residual: {true_res:.2e}  Relative: {rel_res:.2e}")
    print(f"Levels: {mg.n_levels}  Sizes: {mg.level_sizes}")
    print(f"Grid complexity: {mg.grid_complexity:.3f}  "
          f"Operator complexity: {mg.operator_complexity:.3f}")


if __name__ == "__main__":
    main()
