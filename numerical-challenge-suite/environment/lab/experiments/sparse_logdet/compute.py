"""Compute ln|det(M)| for the symmetric banded matrix M defined by:
    M_{ii} = sqrt(i)   for i = 1, ..., 1500
    M_{ij} = 0.05      for |i-j| in {1, 3, 9, 27, 81, 243, 729}
    M_{ij} = 0         otherwise

Uses sparse LU factorization to compute the log-determinant
via the product of diagonal entries of U.
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu


def compute():
    N = 1500
    rows, cols, data = [], [], []

    # Diagonal entries: sqrt(i) for i = 1,...,N
    for i in range(N):
        rows.append(i)
        cols.append(i)
        data.append(np.sqrt(float(i + 1)))

    # Off-diagonal bands at positions {1, 3, 9, 27, 81, 243, 729}
    bands = [3**k for k in range(7)]
    for i in range(N):
        for b in bands:
            j = i + b
            if 0 <= j < N:
                rows.append(i)
                cols.append(j)
                data.append(0.05)

    M_raw = sp.coo_matrix((data, (rows, cols)), shape=(N, N))

    # Enforce symmetry for numerical stability
    M = (M_raw.tocsc() + M_raw.tocsc().T) / 2.0

    lu = splu(M.tocsc())
    diag_u = lu.U.diagonal()
    log_det = float(np.sum(np.log(np.abs(diag_u))))
    return log_det


if __name__ == "__main__":
    result = compute()
    print(f"log|det(M)| = {result:.15e}")
    print(f"RESULT: {result:.15e}")
