#!/usr/bin/env python3
"""
Solver for BBOB Landscape Parameter Recovery task.

Recovers hidden instance parameters (xopt, fopt, rotation matrices) of BBOB
benchmark functions using black-box evaluations via cocoex, then generates
predictions using standalone implementations.
"""

import json
import sys
import numpy as np
from scipy.optimize import minimize
import cocoex

# Import the standalone implementation for predictions
sys.path.insert(0, "/app")
import bbob_impl


def numerical_hessian(func, x, h=1e-5):
    """Compute numerical Hessian via central finite differences.

    Uses the formula:
    H[i,j] = (f(x+h*ei+h*ej) - f(x+h*ei-h*ej) - f(x-h*ei+h*ej) + f(x-h*ei-h*ej)) / (4h^2)
    """
    D = len(x)
    x = np.asarray(x, dtype=float)
    H = np.zeros((D, D))
    for i in range(D):
        for j in range(i, D):
            xpp = x.copy()
            xpp[i] += h
            xpp[j] += h
            xpm = x.copy()
            xpm[i] += h
            xpm[j] -= h
            xmp = x.copy()
            xmp[i] -= h
            xmp[j] += h
            xmm = x.copy()
            xmm[i] -= h
            xmm[j] -= h
            H[i, j] = (func(xpp) - func(xpm) - func(xmp) + func(xmm)) / (4 * h * h)
            H[j, i] = H[i, j]
    return H


def find_optimum(problem, D, n_restarts=50):
    """Find the global optimum using multi-start L-BFGS-B.

    For unimodal functions (f1, f2, f10), a single start usually suffices.
    Multiple restarts provide robustness, especially for f8 (Rosenbrock).
    """
    best_x = None
    best_f = float("inf")
    bounds = [(-5, 5)] * D
    opts = {"ftol": 1e-15, "gtol": 1e-12, "maxiter": 50000}

    # Start from the problem's initial solution
    x0 = problem.initial_solution.copy()
    res = minimize(problem, x0, method="L-BFGS-B", bounds=bounds, options=opts)
    if res.fun < best_f:
        best_f = res.fun
        best_x = res.x.copy()

    # Additional random restarts
    rng = np.random.RandomState(12345)
    for _ in range(n_restarts):
        x0 = rng.uniform(-4, 4, D)
        res = minimize(problem, x0, method="L-BFGS-B", bounds=bounds, options=opts)
        if res.fun < best_f:
            best_f = res.fun
            best_x = res.x.copy()

    # Polish: re-evaluate to ensure consistency
    best_f = float(problem(best_x))
    return best_x, best_f


def recover_rotation_matrix(problem, xopt, fopt, D):
    """Recover the rotation matrix R from the Hessian eigenvectors.

    For f10 (Ellipsoidal rotated): H approx 2 R^T Lambda R where
    Lambda = diag(10^(6(i-1)/(D-1))).

    CRITICAL: The Hessian must be computed at a SHIFTED point (not at xopt)
    because the Tosz transformation has singular derivatives at z=0.
    At z=R*(x-xopt)=0, log(|z_i|) diverges, making finite differences
    unreliable. Shifting away from xopt ensures Tosz arguments are well-behaved.

    The eigenvectors of R^T * D * R are columns of R^T regardless of the
    diagonal matrix D (as long as entries are distinct), so the shifted
    Hessian yields the same rotation matrix.
    """
    # Multiple shift vectors to try (in case one gives z_k near zero for some row of R)
    shift_candidates = [
        np.array([1.0, -0.5, 0.7, -0.3, 0.9]),
        np.array([-0.8, 1.2, -0.6, 0.4, -1.1]),
        np.array([0.3, 0.9, -1.0, 0.6, -0.4]),
        np.array([1.5, 0.5, 0.5, -1.0, 0.5]),
    ]

    # Probe points for sign resolution and quality evaluation
    rng = np.random.RandomState(999)
    probe_points = rng.uniform(-3, 3, size=(15, D))
    true_vals = np.array([float(problem(pp)) for pp in probe_points])

    best_R = None
    best_error = float("inf")
    best_eigenvalues = None

    for shift in shift_candidates:
        x_shifted = xopt + shift
        H = numerical_hessian(problem, x_shifted, h=1e-4)
        eigenvalues, eigenvectors = np.linalg.eigh(H)

        # Check that all eigenvalues are positive (expected for sum-of-squares)
        if np.any(eigenvalues < 0):
            print(f"    Shift {shift}: skipping due to negative eigenvalue(s)")
            continue

        # Sort by eigenvalue ascending (smallest eig -> row 0 of R, largest -> row D-1)
        idx = np.argsort(eigenvalues)
        eigenvalues_sorted = eigenvalues[idx]
        eigenvectors_sorted = eigenvectors[:, idx]

        # Columns of eigenvectors are rows of R: R = eigenvectors^T
        R_initial = eigenvectors_sorted.T

        # Resolve sign ambiguity by testing all 2^D combinations
        n_combinations = 2 ** D
        for mask in range(n_combinations):
            signs = np.array(
                [1.0 if (mask >> i) & 1 == 0 else -1.0 for i in range(D)]
            )
            R_candidate = np.diag(signs) @ R_initial

            # Compute predictions with this R candidate
            preds = np.array(
                [bbob_impl.evaluate_f10(pp, xopt, fopt, R_candidate) for pp in probe_points]
            )
            error = np.sum((preds - true_vals) ** 2)

            if error < best_error:
                best_error = error
                best_R = R_candidate.copy()
                best_eigenvalues = eigenvalues_sorted.copy()

    if best_R is None:
        # Fallback: use shift with largest norm and ignore negative eigenvalues
        print("  WARNING: All shifts produced negative eigenvalues, using fallback")
        shift = np.array([2.0, -1.5, 1.7, -1.3, 1.9])
        x_shifted = xopt + shift
        H = numerical_hessian(problem, x_shifted, h=1e-3)
        eigenvalues, eigenvectors = np.linalg.eigh(H)
        idx = np.argsort(np.abs(eigenvalues))
        eigenvectors_sorted = eigenvectors[:, idx]
        R_initial = eigenvectors_sorted.T
        best_eigenvalues = np.abs(eigenvalues[idx])

        for mask in range(2 ** D):
            signs = np.array(
                [1.0 if (mask >> i) & 1 == 0 else -1.0 for i in range(D)]
            )
            R_candidate = np.diag(signs) @ R_initial
            preds = np.array(
                [bbob_impl.evaluate_f10(pp, xopt, fopt, R_candidate) for pp in probe_points]
            )
            error = np.sum((preds - true_vals) ** 2)
            if error < best_error:
                best_error = error
                best_R = R_candidate.copy()

    return best_R, best_eigenvalues


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    functions = config["functions"]
    D = config["dimension"]
    instance = config["instance"]
    n_test = config["n_test_points"]
    seed = config["test_point_seed"]

    # Generate deterministic test points (must match test expectations)
    rng = np.random.RandomState(seed)
    test_points = rng.uniform(-3, 3, size=(n_test, D))

    results = {}

    for fid in functions:
        print(f"\n{'='*50}")
        print(f"Processing f{fid}")
        print(f"{'='*50}")

        suite = cocoex.Suite(
            "bbob", "",
            f"function_indices: {fid} instance_indices: {instance} dimensions: {D}"
        )
        problem = None
        for p in suite:
            problem = p
            break

        if problem is None:
            print(f"ERROR: Could not create problem f{fid}")
            continue

        # Step 1: Find the global optimum
        print("  Finding optimum...")
        xopt, fopt = find_optimum(problem, D)
        print(f"  xopt = {xopt}")
        print(f"  fopt = {fopt:.10f}")

        entry = {
            "xopt": xopt.tolist(),
            "fopt": float(fopt),
        }

        R = None

        if fid == 10:
            # For f10: compute Hessian at a SHIFTED point to avoid Tosz singularity
            # The Tosz transformation has log(|x|) which diverges as x->0, making
            # the Hessian at the exact optimum unreliable via finite differences.
            print("  Recovering rotation matrix (shifted Hessian method)...")
            R, shifted_eigs = recover_rotation_matrix(problem, xopt, fopt, D)
            entry["rotation_matrix"] = R.tolist()

            # Condition number from the shifted Hessian eigenvalues
            # (same eigenvector structure as optimum Hessian, eigenvalue ratio is similar)
            condition_number = float(shifted_eigs[-1] / max(shifted_eigs[0], 1e-15))

            ortho_err = np.max(np.abs(R @ R.T - np.eye(D)))
            print(f"  R orthogonality error: {ortho_err:.2e}")
            print(f"  Shifted Hessian eigenvalues = {shifted_eigs}")
            print(f"  Condition number (from shifted H) = {condition_number:.2f}")
        else:
            # For other functions: compute Hessian at the optimum directly
            print("  Computing Hessian...")
            H = numerical_hessian(problem, xopt)
            eigenvalues = np.sort(np.linalg.eigvalsh(H))
            abs_eigs = np.abs(eigenvalues)
            condition_number = float(abs_eigs[-1] / max(abs_eigs[0], 1e-15))
            print(f"  Condition number = {condition_number:.2f}")
            print(f"  Eigenvalues = {eigenvalues}")

        entry["condition_number"] = condition_number

        # Step 4: Generate predictions using standalone implementation
        print("  Computing predictions...")
        predictions = []
        for tp in test_points:
            if fid == 1:
                pred = bbob_impl.evaluate_f1(tp, xopt, fopt)
            elif fid == 2:
                pred = bbob_impl.evaluate_f2(tp, xopt, fopt)
            elif fid == 8:
                pred = bbob_impl.evaluate_f8(tp, xopt, fopt)
            elif fid == 10:
                pred = bbob_impl.evaluate_f10(tp, xopt, fopt, R)
            else:
                pred = 0.0
            predictions.append(float(pred))

        entry["predictions"] = predictions

        # Spot-check: compare first prediction with cocoex
        true_val = float(problem(test_points[0]))
        rel_err = abs(predictions[0] - true_val) / max(abs(true_val), 1.0)
        print(f"  Prediction[0] = {predictions[0]:.6f}, cocoex = {true_val:.6f}, "
              f"rel_err = {rel_err:.2e}")

        # Check all predictions for this function
        max_err = 0.0
        for i, tp in enumerate(test_points):
            tv = float(problem(tp))
            err = abs(predictions[i] - tv) / max(abs(tv), 1.0)
            max_err = max(max_err, err)
        print(f"  Max relative error across all {n_test} test points: {max_err:.2e}")

        results[f"f{fid}"] = entry

    # Write results
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*50}")
    print("Results written to /app/results.json")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
