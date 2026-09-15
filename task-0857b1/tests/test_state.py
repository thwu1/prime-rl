"""
Verification tests for geometric multigrid V-cycle implementation.
Tests operator correctness, smoother effectiveness, and convergence properties.
"""

import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, '/app')

RESULTS_FILE = '/app/results.json'


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_FILE), \
        'results.json not found. Run: python3 /app/run_solver.py'
    with open(RESULTS_FILE) as f:
        return json.load(f)


class TestTransferOperators:
    """Verify multigrid prolongation and restriction operators."""

    def test_prolongation_shape_small(self):
        from multigrid import build_prolongation
        P = build_prolongation(3, 7)
        assert P.shape == (49, 9), f'Expected (49, 9), got {P.shape}'

    def test_prolongation_shape_medium(self):
        from multigrid import build_prolongation
        P = build_prolongation(7, 15)
        assert P.shape == (225, 49), f'Expected (225, 49), got {P.shape}'

    def test_restriction_shape(self):
        from multigrid import build_restriction
        R = build_restriction(3, 7)
        assert R.shape == (9, 49), f'Expected (9, 49), got {R.shape}'

    def test_restriction_is_scaled_transpose_of_prolongation(self):
        """R must equal (1/4)*P^T for full-weighting in 2D."""
        from multigrid import build_prolongation, build_restriction
        for nc, nf in [(3, 7), (7, 15), (15, 31)]:
            P = build_prolongation(nc, nf)
            R = build_restriction(nc, nf)
            diff = np.abs((R - 0.25 * P.T).toarray())
            assert np.max(diff) < 1e-12, \
                f'nc={nc},nf={nf}: R != (1/4)*P^T, max diff={np.max(diff):.2e}'

    def test_prolongation_entries_nonnegative(self):
        from multigrid import build_prolongation
        P = build_prolongation(3, 7)
        assert np.all(P.toarray() >= -1e-15), 'Prolongation has negative entries'

    def test_prolongation_of_constant(self):
        """Prolongating a constant vector must produce all-positive entries."""
        from multigrid import build_prolongation
        P = build_prolongation(3, 7)
        Pc = P @ np.ones(9)
        assert np.all(Pc >= 0.25 - 1e-12), \
            f'Prolongation of ones has entries < 0.25: min={np.min(Pc):.4f}'
        assert np.max(Pc) > 0.99, \
            'Prolongation of ones should have at least one entry near 1.0'

    def test_restriction_of_constant(self):
        """Full-weighting restriction of a constant function yields a constant."""
        from multigrid import build_restriction
        R = build_restriction(3, 7)
        Rc = R @ np.ones(49)
        assert np.allclose(Rc, 1.0, atol=1e-12), \
            f'Restriction of all-ones should be all-ones, got min={np.min(Rc):.4f}'


class TestSmoother:
    """Verify weighted Jacobi smoother effectiveness."""

    def test_smoother_reduces_high_frequency_error(self):
        """Checkerboard mode (highest frequency) must be damped rapidly."""
        from multigrid import smooth
        from poisson import assemble_poisson_matrix
        n = 15
        A = assemble_poisson_matrix(n)
        b = np.zeros(n * n)
        x = np.array([(-1.0) ** (i + j) for j in range(n) for i in range(n)])
        x_smooth = smooth(A, b, x.copy(), 5, 2.0 / 3.0)
        ratio = np.linalg.norm(x_smooth) / np.linalg.norm(x)
        assert ratio < 0.3, \
            f'High-freq damping ratio {ratio:.4f} after 5 Jacobi steps (expected < 0.3)'

    def test_smoother_preserves_low_frequency(self):
        """Low-frequency error should not be amplified significantly."""
        from multigrid import smooth
        from poisson import assemble_poisson_matrix
        n = 15
        A = assemble_poisson_matrix(n)
        h = 1.0 / (n + 1)
        # Lowest frequency eigenmode: sin(pi*x)*sin(pi*y)
        x = np.array([
            np.sin(np.pi * (i + 1) * h) * np.sin(np.pi * (j + 1) * h)
            for j in range(n) for i in range(n)
        ])
        b = np.zeros(n * n)
        x_smooth = smooth(A, b, x.copy(), 5, 2.0 / 3.0)
        ratio = np.linalg.norm(x_smooth) / np.linalg.norm(x)
        # Low-frequency should not be amplified (ratio <= 1)
        assert ratio < 1.05, \
            f'Low-freq amplification ratio {ratio:.4f} (expected <= ~1.0)'


class TestConvergence:
    """Verify V-cycle convergence on the Poisson problem."""

    def test_results_complete(self, results):
        """Results must exist for all tested grid sizes."""
        for n in ['15', '31', '63', '127', '255']:
            assert n in results, f'Missing results for grid size {n}'
            assert 'error' not in results[n], \
                f'Solver failed on grid {n}: {results[n].get("error")}'

    def test_convergence_factor_optimal(self, results):
        """Per-iteration convergence factor must be < 0.2."""
        for n_str, r in results.items():
            if 'error' in r:
                pytest.fail(f'Grid {n_str} failed: {r["error"]}')
            assert r['convergence_factor'] < 0.2, \
                f'Grid {n_str}: conv. factor {r["convergence_factor"]:.4f} >= 0.2'

    def test_mesh_independence(self, results):
        """Convergence factor must not depend on mesh size."""
        factors = []
        for n_str in ['31', '63', '127', '255']:
            if n_str in results and 'error' not in results[n_str]:
                factors.append(results[n_str]['convergence_factor'])
        assert len(factors) >= 3, 'Need >= 3 grid sizes for mesh independence test'
        variation = max(factors) - min(factors)
        assert variation < 0.07, \
            f'Conv. factor varies by {variation:.4f} across grids ' \
            f'(factors: {[round(f, 4) for f in factors]})'

    def test_discretization_error_second_order(self, results):
        """L2 error must decrease as O(h^2) under mesh refinement."""
        sizes = [15, 31, 63, 127, 255]
        errors = []
        for n in sizes:
            r = results.get(str(n))
            if r and 'error' not in r:
                errors.append((n, r['l2_error']))
        assert len(errors) >= 3, 'Need >= 3 grid sizes for convergence rate test'
        rates = []
        for i in range(1, len(errors)):
            n_prev, e_prev = errors[i - 1]
            n_curr, e_curr = errors[i]
            h_ratio = (n_prev + 1) / (n_curr + 1)
            rate = np.log(e_prev / e_curr) / np.log(1.0 / h_ratio)
            rates.append(rate)
        avg_rate = np.mean(rates)
        assert 1.7 < avg_rate < 2.5, \
            f'Avg convergence rate {avg_rate:.2f}, expected ~2.0 (rates: ' \
            f'{[round(r, 2) for r in rates]})'

    def test_solution_accuracy_finest_grid(self, results):
        """L2 error on the finest grid must be sufficiently small."""
        r = results.get('255')
        assert r and 'error' not in r, 'Finest grid (255) result missing'
        assert r['l2_error'] < 1e-3, \
            f'L2 error on 255x255 grid: {r["l2_error"]:.2e} (expected < 1e-3)'

    def test_iteration_count_bounded(self, results):
        """Must converge within a reasonable number of V-cycles."""
        for n_str, r in results.items():
            if 'error' in r:
                continue
            assert r['num_iterations'] < 50, \
                f'Grid {n_str}: {r["num_iterations"]} iterations (expected < 50)'
