"""
Naive unpreconditioned CG solver — reads Matrix Market files, attempts
to solve the system, and reports convergence diagnostics.

Requires: numpy, scipy  (pip3 install numpy scipy)

"""
import numpy as np
from scipy.io import mmread
import sys


def cg_solve(A, b, max_iter=50, tol=1e-10):
    """Conjugate Gradient without preconditioning."""
    x = np.zeros_like(b)
    r = b - A @ x
    p = r.copy()
    r0_norm = np.linalg.norm(r)

    for k in range(1, max_iter + 1):
        Ap = A @ p
        alpha = np.dot(r, r) / np.dot(p, Ap)
        x = x + alpha * p
        r_new = r - alpha * Ap
        rel_res = np.linalg.norm(r_new) / r0_norm
        print(f"  Iteration {k:3d}: relative residual = {rel_res:.6e}")
        if rel_res < tol:
            return x, k, float(rel_res)
        beta = np.dot(r_new, r_new) / np.dot(r, r)
        p = r_new + beta * p
        r = r_new

    return x, max_iter, float(np.linalg.norm(r) / r0_norm)


if __name__ == "__main__":
    try:
        A = mmread("/app/A.mtx").tocsr()
        b_dense = mmread("/app/b.mtx")
        b = np.asarray(b_dense).flatten()
    except FileNotFoundError:
        print("Error: A.mtx and/or b.mtx not found in /app/.")
        print("Build and run the matrix generator at /app/matrix_gen/ first.")
        sys.exit(1)

    N = int(round(np.sqrt(A.shape[0])))
    print(f"System size: {N}x{N} grid, {N*N} unknowns")
    print(f"Matrix: {A.shape[0]}x{A.shape[1]}, {A.nnz} nonzeros")
    print(f"Running CG solver (max 50 iterations, tol 1e-10)...\n")

    x, iters, final_res = cg_solve(A, b)

    print(f"\n--- Results ---")
    print(f"Iterations: {iters}")
    print(f"Final relative residual: {final_res:.6e}")

    if final_res > 1e-10:
        print(f"\nFAILED: solver did not converge to target tolerance.")
