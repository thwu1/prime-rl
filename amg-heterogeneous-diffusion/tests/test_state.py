"""
Tests for the AMG preconditioned CG solver.

Independently assembles the same matrix, solves with a direct solver, and
compares the reported results against the ground truth.
"""
import json
import os

import numpy as np
import pytest
from scipy import sparse
from scipy.sparse.linalg import spsolve


# ------------------------------------------------------------------ helpers


def load_config():
    with open("/app/problem.json") as f:
        return json.load(f)


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def eval_K(x, y, inclusions, background):
    """Evaluate piecewise-constant diffusion coefficient at (x, y)."""
    for inc in inclusions:
        xr, yr = inc["x_range"], inc["y_range"]
        if xr[0] <= x <= xr[1] and yr[0] <= y <= yr[1]:
            return inc["value"]
    return background


def assemble_matrix(config):
    """Assemble the 5-point stencil matrix and RHS (independent reference)."""
    n = config["grid_size"]
    N = n * n
    h = 1.0 / (n + 1)
    h2 = h * h
    inclusions = config["coefficients"]["inclusions"]
    background = config["coefficients"]["background"]

    rows, cols, vals = [], [], []
    b = np.full(N, config["rhs_value"])

    neighbors = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    for j in range(n):
        for i in range(n):
            idx = j * n + i
            x = (i + 1) * h
            y = (j + 1) * h

            diag = 0.0
            for di, dj in neighbors:
                face_x = x + di * h * 0.5
                face_y = y + dj * h * 0.5
                k_face = eval_K(face_x, face_y, inclusions, background)
                coeff = k_face / h2

                ni, nj = i + di, j + dj
                if 0 <= ni < n and 0 <= nj < n:
                    neighbor_idx = nj * n + ni
                    rows.append(idx)
                    cols.append(neighbor_idx)
                    vals.append(-coeff)

                diag += coeff

            rows.append(idx)
            cols.append(idx)
            vals.append(diag)

    A = sparse.csr_matrix((vals, (rows, cols)), shape=(N, N))
    return A, b


# cached direct solution
_ref_cache = {}


def get_reference_solution():
    if "x" not in _ref_cache:
        config = load_config()
        A, b = assemble_matrix(config)
        _ref_cache["A"] = A
        _ref_cache["b"] = b
        _ref_cache["x"] = spsolve(A, b)
        _ref_cache["config"] = config
    return _ref_cache


# ------------------------------------------------------------------ tests


class TestResultsStructure:
    """Verify results.json exists and has all required fields."""

    def test_file_exists(self):
        assert os.path.isfile("/app/results.json"), (
            "results.json not found at /app/results.json"
        )

    def test_required_keys(self):
        results = load_results()
        required = [
            "n_unknowns",
            "n_levels",
            "grid_complexity",
            "operator_complexity",
            "pcg_iterations",
            "convergence_factor",
            "solution_norm",
            "probe_values",
        ]
        for key in required:
            assert key in results, f"Missing required key: {key}"

    def test_probe_keys(self):
        config = load_config()
        results = load_results()
        for pt in config["output"]["probe_points_ij"]:
            key = f"{pt[0]}_{pt[1]}"
            assert key in results["probe_values"], (
                f"Missing probe key: {key}"
            )


class TestMatrixDimensions:
    """Verify the matrix size matches the grid specification."""

    def test_n_unknowns(self):
        config = load_config()
        results = load_results()
        expected = config["grid_size"] ** 2
        assert results["n_unknowns"] == expected, (
            f"Expected n_unknowns={expected}, got {results['n_unknowns']}"
        )


class TestAMGHierarchy:
    """Verify AMG hierarchy properties are in expected ranges."""

    def test_minimum_levels(self):
        results = load_results()
        assert results["n_levels"] >= 3, (
            f"AMG should have >= 3 levels, got {results['n_levels']}"
        )

    def test_grid_complexity_range(self):
        results = load_results()
        gc = results["grid_complexity"]
        assert 1.0 < gc < 3.0, (
            f"Grid complexity should be in (1, 3), got {gc}"
        )

    def test_operator_complexity_range(self):
        results = load_results()
        oc = results["operator_complexity"]
        assert 1.0 < oc < 6.0, (
            f"Operator complexity should be in (1, 6), got {oc}"
        )


class TestConvergence:
    """Verify PCG convergence behavior."""

    def test_iteration_count(self):
        results = load_results()
        assert results["pcg_iterations"] < 100, (
            f"PCG should converge in < 100 iterations, "
            f"got {results['pcg_iterations']}"
        )

    def test_convergence_factor(self):
        results = load_results()
        cf = results["convergence_factor"]
        assert 0.0 < cf < 0.7, (
            f"Convergence factor should be in (0, 0.7), got {cf}"
        )


class TestSolutionAccuracy:
    """Verify solution values against an independent direct solve."""

    def test_probe_values(self):
        ref = get_reference_solution()
        config = ref["config"]
        x_ref = ref["x"]
        results = load_results()
        n = config["grid_size"]

        for pt in config["output"]["probe_points_ij"]:
            i, j = pt
            idx = j * n + i
            key = f"{i}_{j}"

            ref_val = x_ref[idx]
            reported = results["probe_values"][key]

            # Use combined absolute + relative tolerance
            err = abs(reported - ref_val)
            tol = max(1e-8, 1e-4 * abs(ref_val))
            assert err < tol, (
                f"Probe ({i},{j}): expected {ref_val:.10e}, "
                f"got {reported:.10e}, error={err:.2e}, tol={tol:.2e}"
            )

    def test_solution_norm(self):
        ref = get_reference_solution()
        x_ref = ref["x"]
        results = load_results()

        ref_norm = float(np.linalg.norm(x_ref))
        reported = results["solution_norm"]

        rel_err = abs(reported - ref_norm) / (ref_norm + 1e-15)
        assert rel_err < 1e-3, (
            f"Solution norm: expected {ref_norm:.6e}, "
            f"got {reported:.6e}, rel_err={rel_err:.2e}"
        )

    def test_residual_is_small(self):
        """Independently verify that the solution approximately satisfies Au = b."""
        ref = get_reference_solution()
        config = ref["config"]
        A = ref["A"]
        b_vec = ref["b"]
        results = load_results()
        n = config["grid_size"]

        # Reconstruct full solution from probe values and solution norm.
        # We can't fully reconstruct x from just probe values, but we can
        # verify that the direct solution satisfies the equation.
        x_ref = ref["x"]
        residual = b_vec - A @ x_ref
        rel_residual = np.linalg.norm(residual) / np.linalg.norm(b_vec)
        assert rel_residual < 1e-10, (
            f"Direct solution residual too large: {rel_residual:.2e}"
        )
