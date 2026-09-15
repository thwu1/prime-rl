
"""
Tests for the polar decomposition numerical library.
"""

import sys
import numpy as np
import pytest

sys.path.insert(0, "/app")

from newton_schulz import (
    polar_decomposition_svd,
    standard_newton_schulz,
    gram_newton_schulz_naive,
    gram_newton_schulz_stabilized,
    simulate_eigenvalue_evolution,
    stability_metric,
    find_optimal_restarts,
    compute_flop_ratio,
    load_config,
)


@pytest.fixture
def config():
    return load_config("/app/coefficients.db")


@pytest.fixture
def polar_express_coefs(config):
    return [tuple(c) for c in config["polar_express_coefficients"]]


@pytest.fixture
def uniform_coefs(config):
    return [tuple(c) for c in config["uniform_coefficients"]]


def _make_test_matrix(n, m, seed=42, condition_number=10.0):
    """Create a test matrix with controlled singular values."""
    rng = np.random.RandomState(seed)
    U, _ = np.linalg.qr(rng.randn(n, n))
    V, _ = np.linalg.qr(rng.randn(m, m))
    sigmas = np.linspace(1.0, 1.0 / condition_number, min(n, m))
    S = np.zeros((n, m))
    for i, s in enumerate(sigmas):
        S[i, i] = s
    return U @ S @ V


# ===================== Standard Newton-Schulz Tests =====================

class TestStandardNewtonSchulz:
    def test_basic_convergence(self, polar_express_coefs):
        """Should approximate polar decomposition."""
        X = _make_test_matrix(8, 16, seed=1, condition_number=5.0)
        result = standard_newton_schulz(X, polar_express_coefs)
        expected = polar_decomposition_svd(X)
        np.testing.assert_allclose(result, expected, atol=0.015)

    def test_square_matrix(self, polar_express_coefs):
        """Works on square matrices."""
        X = _make_test_matrix(8, 8, seed=2, condition_number=3.0)
        result = standard_newton_schulz(X, polar_express_coefs)
        expected = polar_decomposition_svd(X)
        np.testing.assert_allclose(result, expected, atol=0.02)

    def test_tall_matrix(self, polar_express_coefs):
        """Works on tall matrices (n > m)."""
        X = _make_test_matrix(16, 8, seed=3, condition_number=5.0)
        result = standard_newton_schulz(X, polar_express_coefs)
        expected = polar_decomposition_svd(X)
        np.testing.assert_allclose(result, expected, atol=0.015)

    def test_orthogonality(self, polar_express_coefs):
        """Result should have orthonormal rows (for n <= m)."""
        X = _make_test_matrix(6, 12, seed=4, condition_number=3.0)
        result = standard_newton_schulz(X, polar_express_coefs)
        gram = result @ result.T
        np.testing.assert_allclose(gram, np.eye(6), atol=0.03)

    def test_uniform_coefficients(self, uniform_coefs):
        """Works with uniform coefficients."""
        X = _make_test_matrix(6, 12, seed=5, condition_number=5.0)
        result = standard_newton_schulz(X, uniform_coefs)
        expected = polar_decomposition_svd(X)
        np.testing.assert_allclose(result, expected, atol=0.015)

    def test_preserves_shape(self, polar_express_coefs):
        """Output shape matches input shape."""
        X = _make_test_matrix(8, 16, seed=6)
        result = standard_newton_schulz(X, polar_express_coefs)
        assert result.shape == X.shape

    def test_well_conditioned_matrix(self, polar_express_coefs):
        """Near-orthogonal input should be preserved."""
        rng = np.random.RandomState(7)
        U, _ = np.linalg.qr(rng.randn(6, 6))
        V, _ = np.linalg.qr(rng.randn(10, 10))
        S = np.zeros((6, 10))
        for i in range(6):
            S[i, i] = 0.95 + 0.05 * rng.rand()
        X = U @ S @ V
        result = standard_newton_schulz(X, polar_express_coefs)
        expected = polar_decomposition_svd(X)
        np.testing.assert_allclose(result, expected, atol=0.015)


# ===================== Gram Newton-Schulz Tests =====================

class TestGramNewtonSchulzNaive:
    def test_matches_standard(self, polar_express_coefs):
        """Should produce same result as standard variant."""
        X = _make_test_matrix(8, 16, seed=10)
        std_result = standard_newton_schulz(X, polar_express_coefs)
        gram_result = gram_newton_schulz_naive(X, polar_express_coefs)
        np.testing.assert_allclose(gram_result, std_result, atol=1e-6)

    def test_matches_standard_square(self, polar_express_coefs):
        """Equivalence on square matrices."""
        X = _make_test_matrix(8, 8, seed=11)
        std_result = standard_newton_schulz(X, polar_express_coefs)
        gram_result = gram_newton_schulz_naive(X, polar_express_coefs)
        np.testing.assert_allclose(gram_result, std_result, atol=1e-6)

    def test_matches_standard_tall(self, polar_express_coefs):
        """Equivalence on tall matrices."""
        X = _make_test_matrix(16, 8, seed=12)
        std_result = standard_newton_schulz(X, polar_express_coefs)
        gram_result = gram_newton_schulz_naive(X, polar_express_coefs)
        np.testing.assert_allclose(gram_result, std_result, atol=1e-6)

    def test_matches_standard_uniform(self, uniform_coefs):
        """Equivalence with uniform coefficients."""
        X = _make_test_matrix(6, 12, seed=13, condition_number=5.0)
        std_result = standard_newton_schulz(X, uniform_coefs)
        gram_result = gram_newton_schulz_naive(X, uniform_coefs)
        np.testing.assert_allclose(gram_result, std_result, atol=1e-6)

    def test_convergence_to_polar(self, polar_express_coefs):
        """Converges to polar decomposition."""
        X = _make_test_matrix(8, 16, seed=14, condition_number=5.0)
        result = gram_newton_schulz_naive(X, polar_express_coefs)
        expected = polar_decomposition_svd(X)
        np.testing.assert_allclose(result, expected, atol=0.015)

    def test_rectangular_high_aspect(self, polar_express_coefs):
        """Works with highly rectangular matrices (m >> n)."""
        X = _make_test_matrix(4, 32, seed=15, condition_number=5.0)
        result = gram_newton_schulz_naive(X, polar_express_coefs)
        expected = polar_decomposition_svd(X)
        np.testing.assert_allclose(result, expected, atol=0.015)


# ===================== Stabilized Gram Newton-Schulz Tests =====================

class TestGramNewtonSchulzStabilized:
    def test_matches_naive_no_restart(self, polar_express_coefs):
        """With no restart iterations, stabilized == naive."""
        X = _make_test_matrix(8, 16, seed=20)
        naive_result = gram_newton_schulz_naive(X, polar_express_coefs)
        stab_result = gram_newton_schulz_stabilized(X, polar_express_coefs, [])
        np.testing.assert_allclose(stab_result, naive_result, atol=1e-10)

    def test_restart_at_2_converges(self, polar_express_coefs):
        """Stabilized with restart at iteration 2 converges to polar."""
        X = _make_test_matrix(8, 16, seed=21, condition_number=5.0)
        result = gram_newton_schulz_stabilized(X, polar_express_coefs, [2])
        expected = polar_decomposition_svd(X)
        np.testing.assert_allclose(result, expected, atol=0.015)

    def test_restart_at_2_preserves_shape(self, polar_express_coefs):
        """Shape is preserved with restarts."""
        X = _make_test_matrix(10, 20, seed=22)
        result = gram_newton_schulz_stabilized(X, polar_express_coefs, [2])
        assert result.shape == X.shape

    def test_multiple_restarts(self, polar_express_coefs):
        """Multiple restarts still converge."""
        X = _make_test_matrix(8, 16, seed=23, condition_number=5.0)
        result = gram_newton_schulz_stabilized(X, polar_express_coefs, [1, 3])
        expected = polar_decomposition_svd(X)
        np.testing.assert_allclose(result, expected, atol=0.015)

    def test_tall_matrix_with_restart(self, polar_express_coefs):
        """Stabilized works on tall matrices."""
        X = _make_test_matrix(16, 8, seed=24, condition_number=5.0)
        result = gram_newton_schulz_stabilized(X, polar_express_coefs, [2])
        expected = polar_decomposition_svd(X)
        np.testing.assert_allclose(result, expected, atol=0.015)

    def test_restart_every_iteration(self, polar_express_coefs):
        """Restarting every iteration is equivalent to standard variant."""
        X = _make_test_matrix(8, 16, seed=25)
        stab_result = gram_newton_schulz_stabilized(X, polar_express_coefs, [1, 2, 3, 4])
        std_result = standard_newton_schulz(X, polar_express_coefs)
        np.testing.assert_allclose(stab_result, std_result, atol=1e-6)


# ===================== Eigenvalue Evolution Tests =====================

class TestEigenvalueEvolution:
    def test_no_perturbation_r_converges_to_one(self, uniform_coefs):
        """With zero perturbation, R eigenvalues should converge toward 1."""
        eigenvalues = np.array([0.9, 0.5, 0.2])
        result = simulate_eigenvalue_evolution(eigenvalues, uniform_coefs, 0.0, [])
        final_r = result["R"][4]
        for r in final_r:
            assert abs(r) < 2.0, f"R eigenvalue {r} diverged"

    def test_returns_correct_structure(self, polar_express_coefs):
        """Returns dict with R and Q, each with per-iteration snapshots."""
        eigenvalues = np.array([0.8, 0.5, 0.1])
        result = simulate_eigenvalue_evolution(
            eigenvalues, polar_express_coefs, -1e-4, []
        )
        assert "R" in result and "Q" in result
        assert set(result["R"].keys()) == {0, 1, 2, 3, 4}
        assert set(result["Q"].keys()) == {0, 1, 2, 3, 4}
        for i in range(5):
            assert len(result["R"][i]) == 3
            assert len(result["Q"][i]) == 3

    def test_single_iteration_values(self):
        """Single-iteration eigenvalue evolution produces deterministic values."""
        coefs = [(1.875, -1.25, 0.375)]
        eigenvalues = np.array([0.8])
        perturbation = -1e-3
        result = simulate_eigenvalue_evolution(eigenvalues, coefs, perturbation, [])

        r0 = 0.8**2 + perturbation
        z0 = (-1.25) * r0 + 0.375 * r0**2
        q0 = z0 + 1.875
        np.testing.assert_allclose(result["Q"][0][0], q0, rtol=1e-10)

    def test_two_iteration_consistency(self):
        """Two-iteration eigenvalue evolution is self-consistent."""
        coefs = [(1.875, -1.25, 0.375), (1.875, -1.25, 0.375)]
        eigenvalues = np.array([0.7])
        perturbation = -1e-3
        result = simulate_eigenvalue_evolution(eigenvalues, coefs, perturbation, [])

        r0 = 0.7**2 + perturbation
        z0 = (-1.25) * r0 + 0.375 * r0**2
        q0 = z0 + 1.875
        r1 = r0 * q0**2
        z1 = (-1.25) * r1 + 0.375 * r1**2
        q1 = q0 * (z1 + 1.875)

        np.testing.assert_allclose(result["Q"][0][0], q0, rtol=1e-10)
        np.testing.assert_allclose(result["Q"][1][0], q1, rtol=1e-10)

    def test_negative_perturbation_causes_blowup(self, uniform_coefs):
        """Large negative perturbation causes instability without restarts."""
        eigenvalues = np.array([0.9, 0.5, 0.01])
        result = simulate_eigenvalue_evolution(eigenvalues, uniform_coefs, -0.01, [])
        final_q = result["Q"][4]
        abs_q = np.abs(final_q)
        cond = abs_q.max() / abs_q.min()
        assert cond > 100, f"Expected instability with large perturbation, got cond={cond}"

    def test_restart_prevents_blowup(self, uniform_coefs):
        """Restart should improve stability."""
        eigenvalues = np.array([0.9, 0.5, 0.01])
        no_restart = simulate_eigenvalue_evolution(eigenvalues, uniform_coefs, -0.01, [])
        no_restart_cond = stability_metric(no_restart["Q"])
        with_restart = simulate_eigenvalue_evolution(eigenvalues, uniform_coefs, -0.01, [2])
        with_restart_cond = stability_metric(with_restart["Q"])
        assert with_restart_cond < no_restart_cond, \
            f"Restart should improve stability: {with_restart_cond} >= {no_restart_cond}"

    def test_eigenvalue_count_preserved(self, polar_express_coefs):
        """Number of eigenvalues should remain constant."""
        eigenvalues = np.array([0.95, 0.8, 0.6, 0.4, 0.2])
        result = simulate_eigenvalue_evolution(eigenvalues, polar_express_coefs, -1e-4, [2])
        for i in range(5):
            assert len(result["R"][i]) == 5
            assert len(result["Q"][i]) == 5


# ===================== Stability Metric Tests =====================

class TestStabilityMetric:
    def test_identity_condition(self):
        """All-ones Q has metric 1."""
        q_snapshots = {0: np.array([1.0, 1.0, 1.0])}
        assert stability_metric(q_snapshots) == pytest.approx(1.0)

    def test_known_condition(self):
        """Known metric value."""
        q_snapshots = {
            0: np.array([10.0, 1.0, 5.0]),
            1: np.array([2.0, 1.0, 2.0]),
        }
        assert stability_metric(q_snapshots) == pytest.approx(10.0)

    def test_negative_values(self):
        """Negative eigenvalues should use absolute values."""
        q_snapshots = {0: np.array([-5.0, 1.0, 2.0])}
        assert stability_metric(q_snapshots) == pytest.approx(5.0)


# ===================== Optimal Restart Tests =====================

class TestFindOptimalRestarts:
    def test_optimal_restart_polar_express(self, polar_express_coefs, config):
        """Optimal single restart for polar express coefficients."""
        eigenvalues = np.array(config["test_eigenvalues"])
        perturbation = config["test_perturbation"]
        best_positions, best_cond = find_optimal_restarts(
            eigenvalues, polar_express_coefs, perturbation, num_restarts=1
        )
        assert best_positions == [2], \
            f"Expected optimal restart at [2], got {best_positions}"
        assert best_cond < 1e6, f"Stability metric too large: {best_cond}"

    def test_optimal_restart_uniform(self, uniform_coefs, config):
        """Find optimal single restart for uniform coefficients."""
        eigenvalues = np.array(config["test_eigenvalues"])
        perturbation = config["test_perturbation"]
        best_positions, best_cond = find_optimal_restarts(
            eigenvalues, uniform_coefs, perturbation, num_restarts=1
        )
        assert len(best_positions) == 1
        assert 1 <= best_positions[0] <= 4
        assert best_cond < 1e8

    def test_zero_restarts(self, polar_express_coefs, config):
        """Zero restarts should return empty list."""
        eigenvalues = np.array(config["test_eigenvalues"])
        perturbation = config["test_perturbation"]
        best_positions, best_cond = find_optimal_restarts(
            eigenvalues, polar_express_coefs, perturbation, num_restarts=0
        )
        assert best_positions == []

    def test_two_restarts(self, polar_express_coefs, config):
        """Two restarts should find valid positions."""
        eigenvalues = np.array(config["test_eigenvalues"])
        perturbation = config["test_perturbation"]
        best_positions, best_cond = find_optimal_restarts(
            eigenvalues, polar_express_coefs, perturbation, num_restarts=2
        )
        assert len(best_positions) == 2
        assert all(1 <= p <= 4 for p in best_positions)
        assert best_positions == sorted(best_positions)

    def test_more_restarts_improves_stability(self, polar_express_coefs, config):
        """More restarts should not worsen stability."""
        eigenvalues = np.array(config["test_eigenvalues"])
        perturbation = config["test_perturbation"]
        _, cond_1 = find_optimal_restarts(
            eigenvalues, polar_express_coefs, perturbation, num_restarts=1
        )
        _, cond_2 = find_optimal_restarts(
            eigenvalues, polar_express_coefs, perturbation, num_restarts=2
        )
        assert cond_2 <= cond_1 + 1e-6, \
            f"More restarts worsened stability: {cond_2} > {cond_1}"


# ===================== FLOP Ratio Tests =====================

class TestFlopRatio:
    def test_highly_rectangular(self):
        """For m >> n, Gram variant should be much cheaper."""
        ratio = compute_flop_ratio(n=64, m=4096, num_restarts=1, num_iterations=5)
        assert 0.1 < ratio < 0.6, f"Unexpected FLOP ratio: {ratio}"

    def test_square_matrix_ratio(self):
        """For n == m, overhead changes the ratio."""
        ratio = compute_flop_ratio(n=64, m=64, num_restarts=1, num_iterations=5)
        assert 0.5 < ratio < 1.5, f"Unexpected FLOP ratio for square: {ratio}"

    def test_no_restarts_cheapest(self):
        """No restarts should be cheapest variant."""
        ratio_0 = compute_flop_ratio(n=64, m=1024, num_restarts=0, num_iterations=5)
        ratio_1 = compute_flop_ratio(n=64, m=1024, num_restarts=1, num_iterations=5)
        ratio_2 = compute_flop_ratio(n=64, m=1024, num_restarts=2, num_iterations=5)
        assert ratio_0 < ratio_1 < ratio_2

    def test_max_restarts_equals_standard(self):
        """T-1 restarts should give ratio exactly 1."""
        ratio = compute_flop_ratio(n=64, m=1024, num_restarts=4, num_iterations=5)
        np.testing.assert_allclose(ratio, 1.0, atol=1e-10)

    def test_known_values(self):
        """Verify FLOP ratio against known reference values."""
        ratio = compute_flop_ratio(n=10, m=100, num_restarts=1, num_iterations=5)
        np.testing.assert_allclose(ratio, 108000.0 / 210000.0, rtol=1e-10)

    def test_max_restarts_square(self):
        """T-1 restarts on square matrix also gives ratio 1."""
        ratio = compute_flop_ratio(n=32, m=32, num_restarts=4, num_iterations=5)
        np.testing.assert_allclose(ratio, 1.0, atol=1e-10)


# ===================== Integration Tests =====================

class TestIntegration:
    def test_all_three_match_on_well_conditioned(self, polar_express_coefs):
        """All three variants should match on well-conditioned input."""
        X = _make_test_matrix(8, 16, seed=50, condition_number=3.0)
        std = standard_newton_schulz(X, polar_express_coefs)
        naive = gram_newton_schulz_naive(X, polar_express_coefs)
        stab = gram_newton_schulz_stabilized(X, polar_express_coefs, [2])
        expected = polar_decomposition_svd(X)
        np.testing.assert_allclose(std, expected, atol=0.015)
        np.testing.assert_allclose(naive, expected, atol=0.015)
        np.testing.assert_allclose(stab, expected, atol=0.015)

    def test_eigenvalue_sim_consistent_with_matrix(self, polar_express_coefs, config):
        """Eigenvalue simulation should predict actual matrix behavior."""
        n, m = 6, 12
        rng = np.random.RandomState(51)
        U, _ = np.linalg.qr(rng.randn(n, n))
        V, _ = np.linalg.qr(rng.randn(m, m))
        sigmas = np.array([0.9, 0.7, 0.5, 0.3, 0.15, 0.05])
        S = np.zeros((n, m))
        for i, s in enumerate(sigmas):
            S[i, i] = s
        X = U @ S @ V

        norm = np.linalg.norm(X, 'fro') + 1e-7
        sigmas_normalized = sigmas / norm

        result = simulate_eigenvalue_evolution(
            sigmas_normalized, polar_express_coefs, 0.0, []
        )

        final_q = result["Q"][4]
        sorted_q = np.sort(np.abs(final_q))
        sorted_inv_sigma = np.sort(1.0 / sigmas_normalized)
        np.testing.assert_allclose(
            sorted_q[-3:], sorted_inv_sigma[-3:], rtol=0.1
        )


# ===================== Tuned V2 Coefficient Integration Tests =====================

class TestTunedV2Integration:
    """Tests for tuned_v2 coefficient set extracted from .mat file."""

    def test_tuned_v2_exists_in_database(self):
        """tuned_v2 coefficient set exists in database."""
        import sqlite3 as sql3
        conn = sql3.connect("/app/coefficients.db")
        c = conn.cursor()
        c.execute("SELECT id FROM coefficient_sets WHERE name = 'tuned_v2'")
        row = c.fetchone()
        conn.close()
        assert row is not None, "tuned_v2 not found in coefficient_sets table"

    def test_tuned_v2_has_five_iterations(self):
        """tuned_v2 has exactly 5 iterations of coefficients."""
        import sqlite3 as sql3
        conn = sql3.connect("/app/coefficients.db")
        c = conn.cursor()
        c.execute("""SELECT COUNT(*) FROM coefficients co
                     JOIN coefficient_sets cs ON co.set_id = cs.id
                     WHERE cs.name = 'tuned_v2'""")
        count = c.fetchone()[0]
        conn.close()
        assert count == 5, f"Expected 5 iterations, got {count}"

    def test_tuned_v2_coefficients_sum_to_one(self):
        """Each iteration's coefficients satisfy a + b + c = 1."""
        import sqlite3 as sql3
        conn = sql3.connect("/app/coefficients.db")
        c = conn.cursor()
        c.execute("""SELECT co.iteration, co.a, co.b, co.c
                     FROM coefficients co
                     JOIN coefficient_sets cs ON co.set_id = cs.id
                     WHERE cs.name = 'tuned_v2'
                     ORDER BY co.iteration""")
        rows = c.fetchall()
        conn.close()
        assert len(rows) == 5
        for iteration, a, b, cc in rows:
            np.testing.assert_allclose(a + b + cc, 1.0, atol=1e-6,
                err_msg=f"Iteration {iteration}: a+b+c != 1")

    def test_tuned_v2_first_iteration_values(self):
        """First iteration coefficients match expected values."""
        import sqlite3 as sql3
        conn = sql3.connect("/app/coefficients.db")
        c = conn.cursor()
        c.execute("""SELECT co.a, co.b, co.c FROM coefficients co
                     JOIN coefficient_sets cs ON co.set_id = cs.id
                     WHERE cs.name = 'tuned_v2'
                     ORDER BY co.iteration LIMIT 1""")
        row = c.fetchone()
        conn.close()
        np.testing.assert_allclose(row[0], 2.0, atol=1e-6)
        np.testing.assert_allclose(row[1], -1.5, atol=1e-6)
        np.testing.assert_allclose(row[2], 0.5, atol=1e-6)

    def test_tuned_v2_last_iteration_values(self):
        """Last iteration coefficients match expected values."""
        import sqlite3 as sql3
        conn = sql3.connect("/app/coefficients.db")
        c = conn.cursor()
        c.execute("""SELECT co.a, co.b, co.c FROM coefficients co
                     JOIN coefficient_sets cs ON co.set_id = cs.id
                     WHERE cs.name = 'tuned_v2'
                     ORDER BY co.iteration DESC LIMIT 1""")
        row = c.fetchone()
        conn.close()
        np.testing.assert_allclose(row[0], 1.85, atol=1e-6)
        np.testing.assert_allclose(row[1], -1.2, atol=1e-6)
        np.testing.assert_allclose(row[2], 0.35, atol=1e-6)

    def test_tuned_v2_standard_ns_convergence(self):
        """Standard NS converges with tuned_v2 coefficients."""
        import sqlite3 as sql3
        conn = sql3.connect("/app/coefficients.db")
        c = conn.cursor()
        c.execute("""SELECT co.a, co.b, co.c FROM coefficients co
                     JOIN coefficient_sets cs ON co.set_id = cs.id
                     WHERE cs.name = 'tuned_v2'
                     ORDER BY co.iteration""")
        tuned_coefs = [tuple(row) for row in c.fetchall()]
        conn.close()

        X = _make_test_matrix(8, 16, seed=100, condition_number=3.0)
        result = standard_newton_schulz(X, tuned_coefs)
        expected = polar_decomposition_svd(X)
        np.testing.assert_allclose(result, expected, atol=0.05)

    def test_tuned_v2_gram_matches_standard(self):
        """Gram NS matches standard NS with tuned_v2 coefficients."""
        import sqlite3 as sql3
        conn = sql3.connect("/app/coefficients.db")
        c = conn.cursor()
        c.execute("""SELECT co.a, co.b, co.c FROM coefficients co
                     JOIN coefficient_sets cs ON co.set_id = cs.id
                     WHERE cs.name = 'tuned_v2'
                     ORDER BY co.iteration""")
        tuned_coefs = [tuple(row) for row in c.fetchall()]
        conn.close()

        X = _make_test_matrix(8, 16, seed=101, condition_number=3.0)
        std_result = standard_newton_schulz(X, tuned_coefs)
        gram_result = gram_newton_schulz_naive(X, tuned_coefs)
        np.testing.assert_allclose(gram_result, std_result, atol=1e-6)

    def test_tuned_v2_stabilized_convergence(self):
        """Stabilized Gram NS converges with tuned_v2 and restart."""
        import sqlite3 as sql3
        conn = sql3.connect("/app/coefficients.db")
        c = conn.cursor()
        c.execute("""SELECT co.a, co.b, co.c FROM coefficients co
                     JOIN coefficient_sets cs ON co.set_id = cs.id
                     WHERE cs.name = 'tuned_v2'
                     ORDER BY co.iteration""")
        tuned_coefs = [tuple(row) for row in c.fetchall()]
        conn.close()

        X = _make_test_matrix(8, 16, seed=102, condition_number=3.0)
        result = gram_newton_schulz_stabilized(X, tuned_coefs, [2])
        expected = polar_decomposition_svd(X)
        np.testing.assert_allclose(result, expected, atol=0.05)


# ===================== Verification Report Tests =====================

class TestVerificationReport:
    """Tests for the CSV verification report generated via sqlite3 CLI."""

    def test_report_exists(self):
        """Verification report CSV exists at expected path."""
        import os
        assert os.path.exists("/app/verification_report.csv"), \
            "Report not found at /app/verification_report.csv"

    def test_report_has_header(self):
        """Report has expected column headers."""
        with open("/app/verification_report.csv") as f:
            header = f.readline().strip()
        expected_cols = ["name", "num_iterations", "mean_a", "mean_b", "mean_c"]
        for col in expected_cols:
            assert col in header, f"Missing column '{col}' in header: {header}"

    def test_report_has_three_sets(self):
        """Report contains all three coefficient sets."""
        import csv
        with open("/app/verification_report.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"
        names = {row['name'] for row in rows}
        assert 'polar_express' in names, "Missing polar_express"
        assert 'uniform' in names, "Missing uniform"
        assert 'tuned_v2' in names, "Missing tuned_v2"

    def test_report_uniform_values(self):
        """Uniform coefficient means are exact."""
        import csv
        with open("/app/verification_report.csv") as f:
            reader = csv.DictReader(f)
            rows = {row['name']: row for row in reader}
        uniform = rows['uniform']
        assert int(uniform['num_iterations']) == 5
        np.testing.assert_allclose(float(uniform['mean_a']), 1.875, atol=1e-6)
        np.testing.assert_allclose(float(uniform['mean_b']), -1.25, atol=1e-6)
        np.testing.assert_allclose(float(uniform['mean_c']), 0.375, atol=1e-6)

    def test_report_all_have_five_iterations(self):
        """All coefficient sets have 5 iterations."""
        import csv
        with open("/app/verification_report.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                assert int(row['num_iterations']) == 5, \
                    f"{row['name']} has {row['num_iterations']} iterations"
