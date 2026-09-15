#!/usr/bin/env python3
"""Generate problem data and output schema for the task."""
import numpy as np
from scipy import sparse
import os
import json

np.random.seed(42)
os.makedirs('/app/problem', exist_ok=True)

n1 = 500   # primary block size
n2 = 200   # secondary block size

# === Block A: 500x500 SPD from variable-coefficient 1D diffusion ===
h = 1.0 / (n1 + 1)
x_pts = np.linspace(h, 1.0 - h, n1)
kappa = 1.0 + 5.0 * np.sin(np.pi * x_pts) ** 2
k_half = (kappa[:-1] + kappa[1:]) / 2.0

main_diag = np.zeros(n1)
main_diag[0] = (kappa[0] + k_half[0]) / h ** 2
main_diag[-1] = (k_half[-1] + kappa[-1]) / h ** 2
main_diag[1:-1] = (k_half[:-1] + k_half[1:]) / h ** 2
off_diag = -k_half / h ** 2

A = sparse.diags([off_diag, main_diag, off_diag], [-1, 0, 1], format='csr')
A = A + 10.0 * sparse.eye(n1)

# === Block B: 200x500 sparse constraint operator ===
rng = np.random.RandomState(17)
nnz_per_row = 12
rows_b, cols_b, vals_b = [], [], []
for i in range(n2):
    cols = np.sort(rng.choice(n1, size=nnz_per_row, replace=False))
    for j in cols:
        rows_b.append(i)
        cols_b.append(int(j))
        vals_b.append(rng.randn() * 0.5)
B = sparse.csr_matrix((vals_b, (rows_b, cols_b)), shape=(n2, n1))

# === Block C: 200x200 small SPD diagonal regularization ===
rng2 = np.random.RandomState(31)
c_diag = 0.01 * (rng2.rand(n2) + 0.1)
C = sparse.diags([c_diag], [0], format='csr')

# === Full system: [A, B^T; B, -C] ===
M = sparse.bmat([[A, B.T], [B, -C]], format='csr')
n_total = n1 + n2

# === RHS from a structured true solution ===
rng3 = np.random.RandomState(53)
x_true = np.zeros(n_total)
x_true[:n1] = np.sin(np.linspace(0, 4 * np.pi, n1))
x_true[n1:] = np.cos(np.linspace(0, 2 * np.pi, n2)) * 5.0
rhs = M @ x_true

# === Save matrices ===
sparse.save_npz('/app/problem/A.npz', A)
sparse.save_npz('/app/problem/B.npz', B)
sparse.save_npz('/app/problem/C.npz', C)
sparse.save_npz('/app/problem/M.npz', M)
np.save('/app/problem/rhs.npy', rhs)

# === Minimal info.json ===
with open('/app/problem/info.json', 'w') as f:
    json.dump({
        'n_total': n_total,
        'block_partition': [n1, n2],
        'files': {
            'M.npz': 'system matrix (%dx%d, scipy CSR)' % (n_total, n_total),
            'A.npz': '%dx%d sparse matrix' % (n1, n1),
            'B.npz': '%dx%d sparse matrix' % (n2, n1),
            'C.npz': '%dx%d sparse matrix' % (n2, n2),
            'rhs.npy': 'right-hand side vector (length %d)' % n_total
        },
        'origin': 'Mixed finite element discretization.'
    }, f, indent=2)

# === Required output schema ===
schema = {
    "_description": (
        "Write /app/results.json matching this schema exactly. "
        "The system matrix M has a natural 2x2 block partition with sizes "
        "given by block_partition in info.json. Denote the blocks "
        "M11 (500x500), M12 (500x200), M21 (200x500), M22 (200x200). "
        "Files A.npz, B.npz, C.npz are related to these blocks but their "
        "exact relationship must be determined by inspection."
    ),
    "Q1": {
        "_def": "Q1 = M21 M11^{-1} M12 - M22, a 200x200 dense matrix",
        "largest_5": "5 largest eigenvalues as a list (descending order)",
        "smallest_5": "5 smallest eigenvalues as a list (ascending order)"
    },
    "Q2": {
        "_def": (
            "Q2 = M21 diag(M11)^{-1} M12 - M22, "
            "where diag(M11) is the diagonal matrix formed from the "
            "diagonal entries of M11"
        ),
        "largest_5": "5 largest eigenvalues as a list (descending order)",
        "smallest_5": "5 smallest eigenvalues as a list (ascending order)"
    },
    "gen_eig_1": {
        "_def": (
            "Generalized eigenvalues of the matrix pencil (M, P1), "
            "where P1 = blkdiag(M11, Q1)"
        ),
        "largest_real_3": "3 with largest real part (descending, as list)",
        "smallest_real_3": "3 with smallest real part (ascending, as list)"
    },
    "gen_eig_2": {
        "_def": (
            "Generalized eigenvalues of the matrix pencil (M, P2), "
            "where P2 = blkdiag(M11, Q2)"
        ),
        "largest_real_3": "3 with largest real part (descending, as list)",
        "smallest_real_3": "3 with smallest real part (ascending, as list)"
    },
    "solution": "Solution vector x (list of 700 floats) satisfying M x = rhs",
    "relative_residual": "float: ||M x - rhs|| / ||rhs||, must be < 1e-7"
}
with open('/app/problem/required_output.json', 'w') as f:
    json.dump(schema, f, indent=2)

print("Problem generated: %dx%d system" % (n_total, n_total))
print("  A: %dx%d, nnz=%d" % (n1, n1, A.nnz))
print("  B: %dx%d, nnz=%d" % (n2, n1, B.nnz))
print("  C: %dx%d, nnz=%d" % (n2, n2, C.nnz))
print("  M: %dx%d, nnz=%d" % (n_total, n_total, M.nnz))
