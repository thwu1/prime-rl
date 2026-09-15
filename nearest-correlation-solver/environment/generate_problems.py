#!/usr/bin/env python3
"""Generate problem matrices for the nearest correlation matrix task."""
import numpy as np
import json
import os


def construct_invalid_correlation(n, eigenvalues, seed):
    """Construct n x n symmetric matrix with unit diagonal from specified eigenvalues.

    Uses a random orthogonal matrix Q (determined by seed) to create Q diag(lam) Q^T,
    then normalizes to have unit diagonal. By Sylvester's law of inertia, the
    normalization preserves the inertia (count of positive/negative eigenvalues).
    """
    rng = np.random.RandomState(seed)
    H = rng.randn(n, n)
    Q, _ = np.linalg.qr(H)
    A = Q @ np.diag(np.array(eigenvalues, dtype=np.float64)) @ Q.T
    A = (A + A.T) / 2
    d = np.sqrt(np.abs(np.diag(A)))
    d = np.where(d < 1e-10, 1.0, d)
    A = A / np.outer(d, d)
    np.fill_diagonal(A, 1.0)
    return A


def main():
    os.makedirs("/app/problems", exist_ok=True)
    os.makedirs("/app/solutions", exist_ok=True)

    # Problem 1: Basic 6x6 NCM
    # Two small negative eigenvalues simulate a corrupted correlation matrix
    A1 = construct_invalid_correlation(
        6, [3.2, 2.1, 1.4, 0.6, -0.08, -0.22], seed=42
    )
    p1 = {
        "matrix": A1.tolist(),
        "weights": None,
        "fixed_entries": None,
        "tol": 1e-10,
        "compute_modified_cholesky": False,
        "solve_system_rhs": None,
    }

    # Problem 2: Weighted 10x10 NCM
    # Diagonal weight matrix emphasizes certain correlations
    A2 = construct_invalid_correlation(
        10, [4.0, 3.0, 2.5, 2.0, 1.5, 1.0, 0.5, 0.1, -0.15, -0.35], seed=123
    )
    p2 = {
        "matrix": A2.tolist(),
        "weights": [1.5, 2.0, 1.0, 0.8, 1.2, 3.0, 0.5, 1.8, 2.5, 1.0],
        "fixed_entries": None,
        "tol": 1e-10,
        "compute_modified_cholesky": False,
        "solve_system_rhs": None,
    }

    # Problem 3: Constrained 8x8 NCM
    # Trailing 3x3 block must be preserved (e.g., known reliable sub-correlations)
    rng3 = np.random.RandomState(456)
    Q3, _ = np.linalg.qr(rng3.randn(8, 8))
    C3 = Q3 @ np.diag([3.5, 2.8, 2.0, 1.2, 0.8, 0.3, 0.05, 0.01]) @ Q3.T
    C3 = (C3 + C3.T) / 2
    d3 = np.sqrt(np.diag(C3))
    C3 = C3 / np.outer(d3, d3)
    np.fill_diagonal(C3, 1.0)
    # Perturb off-diagonal entries outside the trailing 3x3 block
    E3 = rng3.randn(8, 8) * 0.3
    E3 = (E3 + E3.T) / 2
    np.fill_diagonal(E3, 0.0)
    E3[5:, 5:] = 0.0  # Preserve trailing 3x3 block
    A3 = C3 + E3
    np.fill_diagonal(A3, 1.0)
    fixed = [[i, j] for i in range(5, 8) for j in range(5, 8)]
    p3 = {
        "matrix": A3.tolist(),
        "weights": None,
        "fixed_entries": fixed,
        "tol": 1e-10,
        "compute_modified_cholesky": False,
        "solve_system_rhs": None,
    }

    # Problem 4: 15x15 NCM with modified Cholesky analysis
    # Several significant negative eigenvalues
    A4 = construct_invalid_correlation(
        15,
        [2.5, 2.2, 1.9, 1.7, 1.5, 1.3, 1.1, 0.9, 0.7, 0.5, 0.3, 0.15, -0.1, -0.3, -0.5],
        seed=789,
    )
    p4 = {
        "matrix": A4.tolist(),
        "weights": None,
        "fixed_entries": None,
        "tol": 1e-10,
        "compute_modified_cholesky": True,
        "solve_system_rhs": None,
    }

    # Problem 5: 12x12 NCM with linear system solve and backward error analysis
    A5 = construct_invalid_correlation(
        12,
        [5.0, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5, 1.0, 0.5, 0.2, -0.08, -0.15],
        seed=101,
    )
    rng5 = np.random.RandomState(202)
    rhs = rng5.randn(12).tolist()
    p5 = {
        "matrix": A5.tolist(),
        "weights": None,
        "fixed_entries": None,
        "tol": 1e-10,
        "compute_modified_cholesky": True,
        "solve_system_rhs": rhs,
    }

    problems = [p1, p2, p3, p4, p5]
    for i, p in enumerate(problems, 1):
        path = f"/app/problems/problem_{i}.json"
        with open(path, "w") as f:
            json.dump(p, f, indent=2)
        n = len(p["matrix"])
        eigs = sorted(np.linalg.eigvalsh(np.array(p["matrix"])))
        neg_count = sum(1 for e in eigs if e < 0)
        print(
            f"Problem {i}: {n}x{n}, {neg_count} negative eigenvalue(s), "
            f"range [{eigs[0]:.6f}, {eigs[-1]:.6f}]"
        )


if __name__ == "__main__":
    main()
