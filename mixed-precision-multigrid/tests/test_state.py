
import json
import os
import numpy as np
from scipy import sparse
import pytest


def build_2d_laplacian(n):
    """Build the unscaled 2D 5-point Laplacian for n x n interior grid."""
    e = np.ones(n)
    T = sparse.diags([-e[:-1], 2 * e, -e[:-1]], [-1, 0, 1], format='csr')
    I_n = sparse.eye(n, format='csr')
    A = sparse.kron(I_n, T, format='csr') + sparse.kron(T, I_n, format='csr')
    return A


def build_rhs(n):
    """Build RHS b = h^2 * f(x,y) where f = 2*pi^2*sin(pi*x)*sin(pi*y)."""
    h = 1.0 / (n + 1)
    pts = np.linspace(h, 1.0 - h, n)
    X, Y = np.meshgrid(pts, pts)
    f_vals = 2.0 * np.pi ** 2 * np.sin(np.pi * X) * np.sin(np.pi * Y)
    return (h ** 2 * f_vals).flatten()


def exact_solution_vec(n):
    """Exact solution u(x,y) = sin(pi*x)*sin(pi*y) at interior grid points."""
    h = 1.0 / (n + 1)
    pts = np.linspace(h, 1.0 - h, n)
    X, Y = np.meshgrid(pts, pts)
    return (np.sin(np.pi * X) * np.sin(np.pi * Y)).flatten()


N = 63


class TestMatrixGeneration:
    """Verify the C matrix generator was built and executed."""

    def test_matrix_file_exists(self):
        assert os.path.isfile('/app/A.mtx'), (
            "Matrix file /app/A.mtx not found — the matrix generator "
            "at /app/matrix_gen/ must be built with cmake and executed"
        )

    def test_rhs_file_exists(self):
        assert os.path.isfile('/app/b.mtx'), (
            "RHS file /app/b.mtx not found — the matrix generator "
            "at /app/matrix_gen/ must be built with cmake and executed"
        )


class TestSolutionFile:
    def test_solution_exists_and_shape(self):
        u = np.load('/app/solution.npy')
        assert u.shape == (N * N,), (
            f"Solution shape should be ({N * N},), got {u.shape}"
        )

    def test_solution_dtype(self):
        u = np.load('/app/solution.npy')
        assert u.dtype == np.float64, (
            f"Solution dtype should be float64, got {u.dtype}"
        )

    def test_solution_not_trivial(self):
        u = np.load('/app/solution.npy')
        assert np.max(np.abs(u)) > 0.1, (
            "Solution appears to be near-zero; expected nontrivial values"
        )


class TestSolutionAccuracy:
    def test_algebraic_residual(self):
        """Verify the solution satisfies Au = b to high accuracy."""
        u = np.load('/app/solution.npy')
        A = build_2d_laplacian(N)
        b = build_rhs(N)
        residual_norm = np.linalg.norm(A @ u - b)
        b_norm = np.linalg.norm(b)
        rel_residual = residual_norm / b_norm
        assert rel_residual < 1e-8, (
            f"Relative algebraic residual {rel_residual:.2e} exceeds 1e-8"
        )

    def test_discretization_error(self):
        """Verify the solution is close to the exact PDE solution."""
        u = np.load('/app/solution.npy')
        u_exact = exact_solution_vec(N)
        error_linf = np.max(np.abs(u - u_exact))
        assert error_linf < 1e-2, (
            f"Solution error ||u - u_exact||_inf = {error_linf:.2e} exceeds 1e-2"
        )


class TestResultsJson:
    def test_results_fields(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        required = [
            'grid_size', 'total_iterations', 'final_relative_residual',
            'solution_error_linf', 'convergence_history',
        ]
        for key in required:
            assert key in results, f"Missing required key '{key}' in results.json"

    def test_grid_size(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert results['grid_size'] == N, (
            f"grid_size should be {N}, got {results['grid_size']}"
        )

    def test_convergence_within_budget(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert results['total_iterations'] <= 50, (
            f"Used {results['total_iterations']} iterations, budget is 50"
        )

    def test_final_residual(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert results['final_relative_residual'] < 1e-10, (
            f"Final relative residual {results['final_relative_residual']:.2e} "
            f"should be < 1e-10"
        )

    def test_convergence_history_nonempty(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        history = results['convergence_history']
        assert isinstance(history, list) and len(history) >= 1, (
            "convergence_history must be a non-empty list of residuals"
        )
        assert history[-1] < 1e-10, (
            f"Last residual in convergence_history ({history[-1]:.2e}) "
            f"should be < 1e-10"
        )


class TestConvergencePlot:
    def test_plot_exists(self):
        assert os.path.isfile('/app/convergence.png'), (
            "Convergence plot /app/convergence.png not found"
        )

    def test_plot_is_valid_png(self):
        with open('/app/convergence.png', 'rb') as f:
            header = f.read(8)
        # PNG files start with the 8-byte signature: 89 50 4E 47 0D 0A 1A 0A
        assert header[:4] == b'\x89PNG', (
            "convergence.png does not have a valid PNG header"
        )
        assert len(header) == 8, "convergence.png is too small to be a valid PNG"
