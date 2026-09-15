#!/usr/bin/env python3
"""
Solver for nearest correlation matrix problems with numerical certification.

Implements:
  1. Higham alternating projections with Dykstra's correction (basic, weighted, constrained)
  2. Modified Cholesky factorization via block LDL^T decomposition
  3. Normwise and componentwise backward error analysis for linear systems
"""

import json
import os

import numpy as np
from scipy.linalg import ldl, cho_factor, cho_solve


# ────────────────────────────────────────────────────────────────────
# Nearest Correlation Matrix
# ────────────────────────────────────────────────────────────────────

def proj_psd(A):
    """Project a symmetric matrix onto the positive-semidefinite cone."""
    eigvals, eigvecs = np.linalg.eigh(A)
    eigvals = np.maximum(eigvals, 0.0)
    X = eigvecs @ np.diag(eigvals) @ eigvecs.T
    return (X + X.T) / 2.0


def nearcorr(A, tol=1e-10, maxits=100000, weights=None, fixed_entries=None):
    """Compute nearest correlation matrix using alternating projections
    with Dykstra's correction.

    Reference: N. J. Higham, "Computing the nearest correlation matrix —
    a problem from finance", IMA J. Numer. Anal. 22(3):329–343, 2002.

    Parameters
    ----------
    A : array_like, (n, n)
        Symmetric input matrix with unit diagonal.
    tol : float
        Convergence tolerance on relative differences.
    maxits : int
        Maximum number of iterations.
    weights : array_like of length n, optional
        Diagonal weight vector w.  When given the algorithm minimises
        ||diag(w)^{1/2} (X-A) diag(w)^{1/2}||_F.
    fixed_entries : list of [i, j] pairs, optional
        Entries that must be preserved exactly from the input.

    Returns
    -------
    Y : ndarray
        Nearest correlation matrix.
    iteration : int
        Number of iterations used.
    """
    A = np.array(A, dtype=np.float64)
    n = A.shape[0]

    if weights is not None:
        w = np.array(weights, dtype=np.float64)
        Whalf = np.sqrt(np.outer(w, w))
    else:
        Whalf = np.ones((n, n))

    X = A.copy()
    Y = A.copy()
    dS = np.zeros_like(A)

    for iteration in range(1, maxits + 1):
        Xold = X.copy()
        R = Y - dS

        # Project onto PSD cone in weighted space
        R_wtd = Whalf * R
        X = proj_psd(R_wtd)
        X = X / Whalf

        # Dykstra correction
        dS = X - R

        Yold = Y.copy()
        Y = X.copy()

        # Project onto unit-diagonal constraint
        np.fill_diagonal(Y, 1.0)

        # Restore fixed entries
        if fixed_entries is not None:
            for i, j in fixed_entries:
                Y[i, j] = A[i, j]

        # Convergence check
        rdX = np.linalg.norm(X - Xold, "fro") / max(np.linalg.norm(X, "fro"), 1e-30)
        rdY = np.linalg.norm(Y - Yold, "fro") / max(np.linalg.norm(Y, "fro"), 1e-30)
        rdXY = np.linalg.norm(Y - X, "fro") / max(np.linalg.norm(Y, "fro"), 1e-30)

        if max(rdX, rdY, rdXY) < tol:
            break

    return Y, iteration


# ────────────────────────────────────────────────────────────────────
# Modified Cholesky Factorization
# ────────────────────────────────────────────────────────────────────

def modified_cholesky(A, delta=None):
    """Compute modified Cholesky factorization using Cheng–Higham approach.

    Uses scipy's block LDL^T factorization (Bunch-Kaufman pivoting),
    then perturbs the block-diagonal factor D so that all eigenvalues
    are >= delta, yielding A + E with E = L F L^T.

    Parameters
    ----------
    A : ndarray, (n, n)
        Symmetric matrix.
    delta : float, optional
        Minimum eigenvalue target for perturbed D.
        Defaults to sqrt(eps) * ||A||_F.

    Returns
    -------
    dict with keys perturbation_frobenius_norm, perturbed_min_eigenvalue,
    condition_number.
    """
    A = np.array(A, dtype=np.float64)
    n = A.shape[0]

    if delta is None:
        delta = np.sqrt(np.finfo(np.float64).eps) * np.linalg.norm(A, "fro")

    # Block LDL^T factorization: A = L D L^T
    L, D, perm = ldl(A)

    # Perturb D so all eigenvalues >= delta
    F = np.zeros_like(D)
    i = 0
    while i < n:
        if i < n - 1 and abs(D[i, i + 1]) > 1e-30:
            # 2x2 block
            block = D[i : i + 2, i : i + 2]
            eigvals, eigvecs = np.linalg.eigh(block)
            new_eigvals = np.maximum(eigvals, delta)
            if not np.allclose(eigvals, new_eigvals):
                new_block = eigvecs @ np.diag(new_eigvals) @ eigvecs.T
                F[i : i + 2, i : i + 2] = new_block - block
            i += 2
        else:
            # 1x1 block
            if D[i, i] < delta:
                F[i, i] = delta - D[i, i]
            i += 1

    # Perturbation E = L F L^T
    E = L @ F @ L.T
    E = (E + E.T) / 2.0

    perturbation_norm = float(np.linalg.norm(E, "fro"))

    # Properties of A + E
    A_perturbed = A + E
    A_perturbed = (A_perturbed + A_perturbed.T) / 2.0
    perturbed_eigvals = np.linalg.eigvalsh(A_perturbed)
    perturbed_min_eig = float(perturbed_eigvals[0])

    # 2-norm condition number of A + E
    if perturbed_eigvals[0] > 1e-30:
        cond = float(perturbed_eigvals[-1] / perturbed_eigvals[0])
    else:
        cond = float(perturbed_eigvals[-1] / max(perturbed_eigvals[0], 1e-30))

    return {
        "perturbation_frobenius_norm": perturbation_norm,
        "perturbed_min_eigenvalue": perturbed_min_eig,
        "condition_number": cond,
    }


# ────────────────────────────────────────────────────────────────────
# Linear System Solve with Backward Error
# ────────────────────────────────────────────────────────────────────

def solve_with_backward_error(C, b):
    """Solve C x = b and compute backward errors.

    Parameters
    ----------
    C : ndarray, (n, n)
        Symmetric positive (semi)definite correlation matrix.
    b : array_like, (n,)
        Right-hand side.

    Returns
    -------
    dict with keys solution, normwise_backward_error, componentwise_backward_error.
    """
    C = np.array(C, dtype=np.float64)
    b = np.array(b, dtype=np.float64)

    # Solve — use Cholesky if safely PSD, otherwise LU
    eigvals = np.linalg.eigvalsh(C)
    if eigvals[0] > 1e-12:
        cf = cho_factor(C)
        x = cho_solve(cf, b)
    else:
        x = np.linalg.solve(C, b)

    # Residual
    r = b - C @ x

    # Normwise backward error (Rigal–Gaches):
    #   eta = ||r||_inf / (||C||_inf ||x||_inf + ||b||_inf)
    denom_nw = np.linalg.norm(C, np.inf) * np.linalg.norm(x, np.inf) + np.linalg.norm(
        b, np.inf
    )
    eta = float(np.linalg.norm(r, np.inf) / max(denom_nw, 1e-30))

    # Componentwise backward error:
    #   omega = max_i |r_i| / (|C||x| + |b|)_i
    denom_cw = np.abs(C) @ np.abs(x) + np.abs(b)
    valid = denom_cw > 1e-30
    if np.any(valid):
        omega = float(np.max(np.abs(r[valid]) / denom_cw[valid]))
    else:
        omega = 0.0

    return {
        "solution": x.tolist(),
        "normwise_backward_error": eta,
        "componentwise_backward_error": omega,
    }


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────

def solve_problem(problem):
    """Solve a single NCM problem and return the solution dict."""
    A = np.array(problem["matrix"])
    tol = problem.get("tol", 1e-10)
    weights = problem.get("weights")
    fixed_entries = problem.get("fixed_entries")

    # Nearest correlation matrix
    X, iterations = nearcorr(A, tol=tol, weights=weights, fixed_entries=fixed_entries)

    # Frobenius distance (weighted or unweighted)
    if weights is not None:
        w = np.array(weights)
        Whalf = np.sqrt(np.outer(w, w))
        frob_dist = float(np.linalg.norm(Whalf * (A - X), "fro"))
    else:
        frob_dist = float(np.linalg.norm(A - X, "fro"))

    min_eig = float(np.min(np.linalg.eigvalsh(X)))

    result = {
        "nearest_correlation_matrix": X.tolist(),
        "frobenius_distance": frob_dist,
        "min_eigenvalue": min_eig,
        "iterations": iterations,
        "modified_cholesky": None,
        "linear_system": None,
    }

    if problem.get("compute_modified_cholesky"):
        result["modified_cholesky"] = modified_cholesky(A)

    if problem.get("solve_system_rhs") is not None:
        result["linear_system"] = solve_with_backward_error(X, problem["solve_system_rhs"])

    return result


def main():
    os.makedirs("/app/solutions", exist_ok=True)

    for i in range(1, 6):
        prob_path = f"/app/problems/problem_{i}.json"
        sol_path = f"/app/solutions/solution_{i}.json"

        with open(prob_path) as f:
            problem = json.load(f)

        result = solve_problem(problem)

        with open(sol_path, "w") as f:
            json.dump(result, f, indent=2)

        mc_info = ""
        if result["modified_cholesky"]:
            mc_info = f", perturbation={result['modified_cholesky']['perturbation_frobenius_norm']:.4e}"
        ls_info = ""
        if result["linear_system"]:
            ls_info = f", nbe={result['linear_system']['normwise_backward_error']:.2e}"

        print(
            f"Problem {i}: dist={result['frobenius_distance']:.6e}, "
            f"min_eig={result['min_eigenvalue']:.6e}, "
            f"iters={result['iterations']}{mc_info}{ls_info}"
        )


if __name__ == "__main__":
    main()
