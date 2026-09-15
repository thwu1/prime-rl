
"""
Generalized Bicycle Code analyzer.
Constructs CSS parity check matrices, computes [[n,k,d]] parameters,
and identifies the code with best kd^2/n figure of merit.
"""

import json
import numpy as np
from numpy.linalg import matrix_power as m_power


def cyclic_shift(m):
    """m x m cyclic downward shift matrix: row j -> row (j+1) mod m."""
    M = np.zeros((m, m), dtype=int)
    for j in range(m):
        M[j, (j + 1) % m] = 1
    return M


def identity(m):
    return np.eye(m, dtype=int)


def rank_gf2(mat):
    """Compute rank of a binary matrix over GF(2) via row reduction."""
    M = mat.copy().astype(int) % 2
    nrows, ncols = M.shape
    pivots = {}
    for row in range(nrows):
        pos = -1
        for col in range(ncols):
            if M[row, col] != 0:
                pos = col
                break
        if pos == -1:
            continue
        for row2 in range(nrows):
            if row2 != row and M[row2, pos] == 1:
                M[row2] = (M[row2] + M[row]) % 2
        pivots[row] = pos
    return len(pivots)


def kernel_gf2(mat):
    """Find basis for kernel of mat over GF(2)."""
    M = mat.copy().astype(int) % 2
    nrows, ncols = M.shape
    Mt = M.copy()
    pivot_cols = []
    pivot_rows = []
    cur = 0
    for col in range(ncols):
        found = -1
        for row in range(cur, nrows):
            if Mt[row, col] == 1:
                found = row
                break
        if found == -1:
            continue
        Mt[[cur, found]] = Mt[[found, cur]]
        pivot_cols.append(col)
        pivot_rows.append(cur)
        for row in range(nrows):
            if row != cur and Mt[row, col] == 1:
                Mt[row] = (Mt[row] + Mt[cur]) % 2
        cur += 1

    free_cols = [c for c in range(ncols) if c not in pivot_cols]
    basis = []
    for fc in free_cols:
        v = np.zeros(ncols, dtype=int)
        v[fc] = 1
        for i, pc in enumerate(pivot_cols):
            v[pc] = Mt[pivot_rows[i], fc]
        basis.append(v)
    return np.array(basis, dtype=int) if basis else np.zeros((0, ncols), dtype=int)


def is_in_rowspace(v, M):
    """Check if binary vector v is in the GF(2) row space of M."""
    if M.shape[0] == 0:
        return np.all(v == 0)
    augmented = np.vstack([M % 2, (v.reshape(1, -1)) % 2])
    return rank_gf2(augmented) == rank_gf2(M % 2)


def min_weight_outside_rowspace(ker_basis, rowsp_matrix):
    """
    Find minimum Hamming weight of a non-zero vector in span(ker_basis)
    that is NOT in the row space of rowsp_matrix, all over GF(2).
    """
    if len(ker_basis) == 0:
        return float("inf")
    dim = len(ker_basis)
    min_w = float("inf")
    for i in range(1, 2**dim):
        v = np.zeros(ker_basis.shape[1], dtype=int)
        tmp = i
        for j in range(dim):
            if tmp & 1:
                v = (v + ker_basis[j]) % 2
            tmp >>= 1
        w = int(np.sum(v))
        if 0 < w < min_w:
            if not is_in_rowspace(v, rowsp_matrix):
                min_w = w
    return min_w


def build_matrix(l, m, terms):
    """
    Build a binary matrix from polynomial terms in shift operators.
    terms: list of [y_exp, x_exp] pairs.
    Returns l*m x l*m binary matrix.
    """
    x = np.kron(cyclic_shift(l), identity(m))
    y = np.kron(identity(l), cyclic_shift(m))
    N = l * m
    M = np.zeros((N, N), dtype=int)
    for yp, xp in terms:
        term = np.matmul(m_power(y, int(yp)), m_power(x, int(xp)))
        M = (M + np.round(term).astype(int)) % 2
    return M


def analyze_code(code_spec):
    """Analyze a single GB code and return its [[n,k,d]] parameters."""
    l = code_spec["l"]
    m = code_spec["m"]

    A = build_matrix(l, m, code_spec["A_terms"])
    B = build_matrix(l, m, code_spec["B_terms"])

    HX = np.hstack((A, B)).astype(int)
    HZ = np.hstack((B.T, A.T)).astype(int)

    n = 2 * l * m
    rx = rank_gf2(HX)
    rz = rank_gf2(HZ)
    k = n - rx - rz

    # Compute distance
    ker_HX = kernel_gf2(HX)
    ker_HZ = kernel_gf2(HZ)

    d_X = min_weight_outside_rowspace(ker_HX, HZ)
    d_Z = min_weight_outside_rowspace(ker_HZ, HX)
    d = min(d_X, d_Z)

    fom = round(k * d * d / n, 4)

    return {"n": n, "k": k, "d": d, "kd2_over_n": fom}


def main():
    with open("/app/codes.json", "r") as f:
        config = json.load(f)

    results = {"codes": {}}
    best_name = None
    best_fom = -1.0

    for code_spec in config["codes"]:
        name = code_spec["name"]
        print(f"Analyzing code '{name}'...")
        params = analyze_code(code_spec)
        results["codes"][name] = params
        print(f"  [[{params['n']},{params['k']},{params['d']}]], kd^2/n={params['kd2_over_n']}")

        if params["kd2_over_n"] > best_fom:
            best_fom = params["kd2_over_n"]
            best_name = name

    results["best_code"] = best_name

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nBest code: {best_name} (kd^2/n = {best_fom})")
    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
