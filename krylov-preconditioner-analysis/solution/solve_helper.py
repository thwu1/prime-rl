#!/usr/bin/env python3

"""
Solve the sparse system analysis pipeline.

Steps:
1. Load problem data and understand block structure
2. Compute Q1 and Q2, their eigenvalues
3. Compute generalized eigenvalues with block-diagonal matrices
4. Solve the linear system using an appropriate iterative method
5. Write results
"""

import json
import numpy as np
from scipy import sparse
from scipy.linalg import cho_factor, cho_solve, eigvalsh as dense_eigvalsh
from scipy.sparse.linalg import factorized, gmres, LinearOperator

# -----------------------------------------------------------------------
# Load problem
# -----------------------------------------------------------------------
A = sparse.load_npz("/app/problem/A.npz")
B = sparse.load_npz("/app/problem/B.npz")
C = sparse.load_npz("/app/problem/C.npz")
K = sparse.load_npz("/app/problem/M.npz")
rhs = np.load("/app/problem/rhs.npy")

n1 = A.shape[0]
n2 = B.shape[0]
n_total = n1 + n2
print(f"System size: {n_total} (n1={n1}, n2={n2})")

# -----------------------------------------------------------------------
# Discover block structure: K = [A, B'; B, -C]
# -----------------------------------------------------------------------
print("Verifying block assembly...")
assert np.allclose(K[:n1, :n1].toarray(), A.toarray())
assert np.allclose(K[n1:, :n1].toarray(), B.toarray())
assert np.allclose(K[n1:, n1:].toarray(), -C.toarray())

# -----------------------------------------------------------------------
# 1. Q1 = B A^{-1} B^T + C  (exact Schur complement variant)
# -----------------------------------------------------------------------
print("Computing Q1 ...")
solve_A = factorized(A.tocsc())
BT_dense = B.T.toarray()
AinvBT = np.column_stack([solve_A(BT_dense[:, i]) for i in range(n2)])
Q1 = B.toarray() @ AinvBT + C.toarray()

eigs_Q1 = np.sort(np.linalg.eigvalsh(Q1))
print(f"  eigenvalue range: [{eigs_Q1[0]:.6e}, {eigs_Q1[-1]:.6e}]")

# -----------------------------------------------------------------------
# 2. Q2 = B diag(A)^{-1} B^T + C  (diagonal approximation)
# -----------------------------------------------------------------------
print("Computing Q2 ...")
d_inv = 1.0 / A.diagonal()
D_inv = sparse.diags(d_inv)
Q2 = (B @ D_inv @ B.T).toarray() + C.toarray()

eigs_Q2 = np.sort(np.linalg.eigvalsh(Q2))
print(f"  eigenvalue range: [{eigs_Q2[0]:.6e}, {eigs_Q2[-1]:.6e}]")

# -----------------------------------------------------------------------
# 3. Generalized eigenvalues  M v = lam P v
# -----------------------------------------------------------------------
K_dense = K.toarray()

# --- P1 = blkdiag(A, Q1) ---
print("Computing generalized eigenvalues (P1) ...")
P1 = np.zeros((n_total, n_total))
P1[:n1, :n1] = A.toarray()
P1[n1:, n1:] = Q1
eigs_ge1 = np.sort(dense_eigvalsh(K_dense, P1))

# --- P2 = blkdiag(A, Q2) ---
print("Computing generalized eigenvalues (P2) ...")
P2 = np.zeros((n_total, n_total))
P2[:n1, :n1] = A.toarray()
P2[n1:, n1:] = Q2
eigs_ge2 = np.sort(dense_eigvalsh(K_dense, P2))

# -----------------------------------------------------------------------
# 4. Solve M x = rhs using GMRES with block-diagonal preconditioner
# -----------------------------------------------------------------------
print("Solving system with GMRES + block-diagonal preconditioner ...")
Q1_chol = cho_factor(Q1)

def _apply_P1_inv(v):
    out = np.empty(n_total)
    out[:n1] = solve_A(v[:n1])
    out[n1:] = cho_solve(Q1_chol, v[n1:])
    return out

P1_op = LinearOperator((n_total, n_total), matvec=_apply_P1_inv)
x_sol, info = gmres(K, rhs, M=P1_op, rtol=1e-10, restart=100, maxiter=20)
assert info == 0, f"GMRES did not converge, info={info}"

rel_resid = float(np.linalg.norm(K @ x_sol - rhs) / np.linalg.norm(rhs))
print(f"Final relative residual: {rel_resid:.2e}")

# -----------------------------------------------------------------------
# 5. Write results
# -----------------------------------------------------------------------
results = {
    "Q1": {
        "largest_5": eigs_Q1[-5:][::-1].tolist(),
        "smallest_5": eigs_Q1[:5].tolist(),
    },
    "Q2": {
        "largest_5": eigs_Q2[-5:][::-1].tolist(),
        "smallest_5": eigs_Q2[:5].tolist(),
    },
    "gen_eig_1": {
        "largest_real_3": eigs_ge1[-3:][::-1].tolist(),
        "smallest_real_3": eigs_ge1[:3].tolist(),
    },
    "gen_eig_2": {
        "largest_real_3": eigs_ge2[-3:][::-1].tolist(),
        "smallest_real_3": eigs_ge2[:3].tolist(),
    },
    "solution": x_sol.tolist(),
    "relative_residual": rel_resid,
}

with open("/app/results.json", "w") as fh:
    json.dump(results, fh)

print("Results written to /app/results.json")
