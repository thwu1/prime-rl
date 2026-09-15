
"""
Tests for the Newton-Schulz polar decomposition solver, custom coefficient
design, and evaluation pipeline.

Verifies correctness of standard NS, Gram NS, eigenvalue simulation,
stability metric, restart optimization, convergence analysis, custom
coefficient schedule properties, and the full benchmark evaluation
pipeline with SQLite database and JSON report.
"""

import json
import os
import sqlite3

import numpy as np
import pytest
import sys

sys.path.insert(0, "/app")
from polar_solver import (
    standard_newton_schulz,
    gram_newton_schulz,
    simulate_eigenvalue_evolution,
    stability_metric,
    find_optimal_restarts,
    compute_polar_error,
    analyze_convergence,
    load_coefficients,
)

# Reference coefficients for testing core solver functions
COEFFICIENTS = [
    [4.0848, -6.8946, 2.9270],
    [3.9505, -6.3029, 2.6377],
    [3.7418, -5.5913, 2.3037],
    [2.8769, -3.1427, 1.2046],
    [2.8366, -3.0525, 1.2012],
]

SCHULZ_CLASSIC = [[1.5, -0.5, 0.0]] * 5
SCHULZ_CONSERVATIVE = [[1.4, -0.4, 0.0]] * 5


class TestStandardNewtonSchulz:
    """Verify the reference implementation works correctly."""

    def test_orthogonality_wide(self):
        np.random.seed(42)
        X = np.random.randn(4, 8)
        result = standard_newton_schulz(X, COEFFICIENTS)
        error = compute_polar_error(result)
        assert error < 0.05, f"Orthogonality error too large: {error}"

    def test_orthogonality_tall(self):
        np.random.seed(42)
        X = np.random.randn(8, 4)
        result = standard_newton_schulz(X, COEFFICIENTS)
        error = compute_polar_error(result)
        assert error < 0.1, f"Orthogonality error too large: {error}"

    def test_orthogonality_square(self):
        np.random.seed(42)
        X = np.random.randn(6, 6)
        result = standard_newton_schulz(X, COEFFICIENTS)
        error = compute_polar_error(result)
        assert error < 0.1, f"Orthogonality error too large: {error}"

    def test_preserves_shape(self):
        np.random.seed(42)
        X = np.random.randn(5, 10)
        result = standard_newton_schulz(X, COEFFICIENTS)
        assert result.shape == X.shape, f"Shape mismatch: {result.shape} vs {X.shape}"


class TestGramNewtonSchulz:
    """Verify Gram NS matches standard NS and handles all shapes."""

    def test_equivalence_wide_no_restart(self):
        np.random.seed(42)
        X = np.random.randn(4, 8)
        standard_result = standard_newton_schulz(X, COEFFICIENTS)
        gram_result = gram_newton_schulz(X, COEFFICIENTS, reset_iterations=[])
        diff = np.linalg.norm(standard_result - gram_result) / np.linalg.norm(
            standard_result
        )
        assert diff < 1e-6, f"Relative difference too large: {diff}"

    def test_equivalence_tall_no_restart(self):
        np.random.seed(123)
        X = np.random.randn(10, 4)
        standard_result = standard_newton_schulz(X, COEFFICIENTS)
        gram_result = gram_newton_schulz(X, COEFFICIENTS, reset_iterations=[])
        diff = np.linalg.norm(standard_result - gram_result) / np.linalg.norm(
            standard_result
        )
        assert diff < 1e-6, f"Relative difference too large: {diff}"

    def test_equivalence_square_no_restart(self):
        np.random.seed(99)
        X = np.random.randn(6, 6)
        standard_result = standard_newton_schulz(X, COEFFICIENTS)
        gram_result = gram_newton_schulz(X, COEFFICIENTS, reset_iterations=[])
        diff = np.linalg.norm(standard_result - gram_result) / np.linalg.norm(
            standard_result
        )
        assert diff < 1e-6, f"Relative difference too large: {diff}"

    def test_equivalence_with_restart(self):
        np.random.seed(42)
        X = np.random.randn(6, 12)
        standard_result = standard_newton_schulz(X, COEFFICIENTS)
        gram_result = gram_newton_schulz(X, COEFFICIENTS, reset_iterations=[2])
        diff = np.linalg.norm(standard_result - gram_result) / np.linalg.norm(
            standard_result
        )
        assert diff < 1e-5, f"Relative difference too large: {diff}"

    def test_equivalence_with_multiple_restarts(self):
        np.random.seed(77)
        X = np.random.randn(5, 15)
        standard_result = standard_newton_schulz(X, COEFFICIENTS)
        gram_result = gram_newton_schulz(X, COEFFICIENTS, reset_iterations=[2, 4])
        diff = np.linalg.norm(standard_result - gram_result) / np.linalg.norm(
            standard_result
        )
        assert diff < 1e-5, f"Relative difference too large: {diff}"

    def test_orthogonality_with_restart(self):
        np.random.seed(42)
        X = np.random.randn(4, 8)
        result = gram_newton_schulz(X, COEFFICIENTS, reset_iterations=[2])
        error = compute_polar_error(result)
        assert error < 0.1, f"Orthogonality error too large: {error}"

    def test_batch_processing(self):
        np.random.seed(42)
        X = np.random.randn(3, 4, 8)
        result = gram_newton_schulz(X, COEFFICIENTS, reset_iterations=[2])
        assert result.shape == X.shape, f"Shape mismatch: {result.shape}"
        for i in range(3):
            error = compute_polar_error(result[i])
            assert error < 0.1, f"Batch {i} orthogonality error: {error}"

    def test_tall_with_restart(self):
        np.random.seed(55)
        X = np.random.randn(12, 5)
        standard_result = standard_newton_schulz(X, COEFFICIENTS)
        gram_result = gram_newton_schulz(X, COEFFICIENTS, reset_iterations=[2])
        diff = np.linalg.norm(standard_result - gram_result) / np.linalg.norm(
            standard_result
        )
        assert diff < 1e-5, f"Relative difference too large: {diff}"


class TestStabilityMetric:
    """Verify stability metric computes max(|q|)/min(|q|)."""

    def test_uniform_gives_one(self):
        q_values = {
            "Q_0": np.array([2.0, 2.0, 2.0]),
            "Q_1": np.array([3.0, 3.0, 3.0]),
        }
        metric = stability_metric(q_values)
        assert abs(metric - 1.0) < 1e-10, f"Expected 1.0, got {metric}"

    def test_known_ratio(self):
        q_values = {"Q_0": np.array([1.0, 10.0])}
        metric = stability_metric(q_values)
        assert abs(metric - 10.0) < 1e-10, f"Expected 10.0, got {metric}"

    def test_max_over_min_not_mean(self):
        q_values = {"Q_0": np.array([1.0, 1.0, 100.0])}
        metric = stability_metric(q_values)
        assert abs(metric - 100.0) < 1e-10, f"Expected 100.0, got {metric}"

    def test_takes_max_across_iterations(self):
        q_values = {
            "Q_0": np.array([1.0, 2.0]),
            "Q_1": np.array([1.0, 50.0]),
            "Q_2": np.array([1.0, 5.0]),
        }
        metric = stability_metric(q_values)
        assert abs(metric - 50.0) < 1e-10, f"Expected 50.0, got {metric}"

    def test_uses_absolute_values(self):
        q_values = {"Q_0": np.array([-10.0, 5.0])}
        metric = stability_metric(q_values)
        assert abs(metric - 2.0) < 1e-10, f"Expected 2.0, got {metric}"


class TestEigenvalueSimulation:
    """Verify eigenvalue tracking through Newton-Schulz iterations."""

    def test_no_perturbation_convergence(self):
        eigenvalues = np.array([0.3, 0.5, 0.7, 0.9])
        q_values = simulate_eigenvalue_evolution(
            eigenvalues, COEFFICIENTS, perturbation=0.0
        )
        final_q = q_values[f"Q_{len(COEFFICIENTS)-1}"]
        products = final_q * eigenvalues
        for i, p in enumerate(products):
            assert abs(p - 1.0) < 0.05, (
                f"Eigenvalue {eigenvalues[i]}: q*sigma={p}, expected ~1.0"
            )

    def test_perturbation_causes_instability(self):
        eigenvalues = np.linspace(0.1, 1.0, 20)
        q_values = simulate_eigenvalue_evolution(
            eigenvalues, COEFFICIENTS, perturbation=-0.01, reset_indices=[]
        )
        metric = stability_metric(q_values)
        assert metric > 50, f"Expected large instability metric, got {metric}"

    def test_restart_reduces_instability(self):
        eigenvalues = np.array([0.03, 0.08, 0.15, 0.3, 0.5, 0.7, 0.85, 1.0])
        q_no_restart = simulate_eigenvalue_evolution(
            eigenvalues, COEFFICIENTS, perturbation=-2 ** (-10), reset_indices=[]
        )
        q_with_restart = simulate_eigenvalue_evolution(
            eigenvalues, COEFFICIENTS, perturbation=-2 ** (-10), reset_indices=[1]
        )
        metric_no_restart = stability_metric(q_no_restart)
        metric_with_restart = stability_metric(q_with_restart)
        assert metric_with_restart < metric_no_restart, (
            f"Restart should improve stability: "
            f"{metric_with_restart} vs {metric_no_restart}"
        )

    def test_returns_correct_number_of_iterations(self):
        eigenvalues = np.array([0.5, 0.8])
        q_values = simulate_eigenvalue_evolution(
            eigenvalues, COEFFICIENTS, perturbation=0.0
        )
        assert len(q_values) == len(COEFFICIENTS)
        for i in range(len(COEFFICIENTS)):
            assert f"Q_{i}" in q_values


class TestFindOptimalRestarts:
    """Verify restart optimization finds the best positions."""

    def test_returns_correct_format(self):
        eigenvalues = np.linspace(0.1, 1.0, 10)
        result = find_optimal_restarts(
            eigenvalues, COEFFICIENTS, perturbation=-2 ** (-10), num_restarts=1
        )
        assert isinstance(result, tuple) and len(result) == 2
        best_restarts, best_metric = result
        assert isinstance(best_restarts, list)
        assert isinstance(best_metric, (float, np.floating))

    def test_one_restart_is_optimal(self):
        eigenvalues = np.linspace(0.1, 1.0, 20)
        perturbation = -(2 ** (-10))
        best_restarts, best_metric = find_optimal_restarts(
            eigenvalues, COEFFICIENTS, perturbation, num_restarts=1
        )
        assert len(best_restarts) == 1
        assert 1 <= best_restarts[0] <= len(COEFFICIENTS) - 1

        for pos in range(1, len(COEFFICIENTS)):
            q_vals = simulate_eigenvalue_evolution(
                eigenvalues, COEFFICIENTS, perturbation, reset_indices=[pos]
            )
            other_metric = stability_metric(q_vals)
            assert best_metric <= other_metric + 1e-10, (
                f"Position [{pos}] has metric {other_metric} < "
                f"reported best {best_metric}"
            )

    def test_zero_restarts(self):
        eigenvalues = np.linspace(0.1, 1.0, 10)
        best_restarts, best_metric = find_optimal_restarts(
            eigenvalues, COEFFICIENTS, perturbation=-2 ** (-10), num_restarts=0
        )
        assert best_restarts == []
        assert np.isfinite(best_metric)
        assert best_metric > 0

    def test_two_restarts(self):
        eigenvalues = np.linspace(0.1, 1.0, 15)
        perturbation = -(2 ** (-10))
        best_restarts, best_metric = find_optimal_restarts(
            eigenvalues, COEFFICIENTS, perturbation, num_restarts=2
        )
        assert len(best_restarts) == 2
        assert all(1 <= r <= len(COEFFICIENTS) - 1 for r in best_restarts)
        assert best_restarts == sorted(best_restarts)
        assert np.isfinite(best_metric)

    def test_metric_is_finite(self):
        eigenvalues = np.linspace(0.2, 0.9, 15)
        best_restarts, best_metric = find_optimal_restarts(
            eigenvalues, COEFFICIENTS, perturbation=-2 ** (-10), num_restarts=1
        )
        assert best_metric > 0
        assert np.isfinite(best_metric)


class TestConvergenceAnalysis:
    """Verify per-iteration convergence metrics."""

    def test_error_decreases_overall(self):
        np.random.seed(42)
        X = np.random.randn(4, 8)
        errors = analyze_convergence(X, COEFFICIENTS)
        assert len(errors) == len(COEFFICIENTS)
        assert errors[-1] < errors[0], (
            f"Final error {errors[-1]} should be less than first {errors[0]}"
        )

    def test_final_error_small(self):
        np.random.seed(42)
        X = np.random.randn(4, 8)
        errors = analyze_convergence(X, COEFFICIENTS)
        assert errors[-1] < 0.1, f"Final error too large: {errors[-1]}"

    def test_tall_matrix(self):
        np.random.seed(42)
        X = np.random.randn(8, 4)
        errors = analyze_convergence(X, COEFFICIENTS)
        assert len(errors) == len(COEFFICIENTS)
        assert errors[-1] < 0.1, f"Final error too large: {errors[-1]}"


class TestComputePolarError:
    """Verify orthogonality error computation."""

    def test_identity_zero_error(self):
        I = np.eye(4)
        error = compute_polar_error(I)
        assert abs(error) < 1e-10

    def test_orthogonal_zero_error(self):
        np.random.seed(42)
        Q, _ = np.linalg.qr(np.random.randn(4, 4))
        error = compute_polar_error(Q)
        assert abs(error) < 1e-10

    def test_semi_orthogonal_zero_error(self):
        np.random.seed(42)
        Q, _ = np.linalg.qr(np.random.randn(6, 4))
        error = compute_polar_error(Q.T)
        assert abs(error) < 1e-10

    def test_random_nonzero_error(self):
        np.random.seed(42)
        X = np.random.randn(4, 6)
        error = compute_polar_error(X)
        assert error > 0.1


class TestLoadCoefficients:
    """Verify coefficient loading."""

    def test_loads_reference(self):
        data = load_coefficients("/app/coefficients.json")
        assert "schulz_classic" in data
        coefs = data["schulz_classic"]
        assert len(coefs) == 5
        for triple in coefs:
            assert len(triple) == 3


class TestCustomCoefficientDesign:
    """Verify the custom-designed coefficient schedule meets all requirements."""

    @pytest.fixture(autouse=True)
    def load_custom_config(self):
        config_path = "/app/configs/custom_optimized.json"
        assert os.path.exists(config_path), (
            "custom_optimized.json not found — run coefficient designer first"
        )
        with open(config_path) as f:
            config = json.load(f)
        iterations = config["parameters"]["iterations"]
        self.coefficients = [
            [it["coefficients"]["a"], it["coefficients"]["b"], it["coefficients"]["c"]]
            for it in sorted(iterations, key=lambda x: x["step"])
        ]
        assert config["metadata"]["name"] == "custom_optimized"

    def test_has_5_iterations(self):
        assert len(self.coefficients) == 5, (
            f"Expected 5 iterations, got {len(self.coefficients)}"
        )

    def test_positive_leading_coefficients(self):
        for i, (a, b, c) in enumerate(self.coefficients):
            assert a > 0, f"Iteration {i}: a={a} must be positive"

    def test_has_quadratic_terms(self):
        has_nonzero_c = any(abs(c) > 1e-10 for _, _, c in self.coefficients)
        assert has_nonzero_c, (
            "At least one iteration must use a quadratic term (c != 0)"
        )

    def test_coefficients_are_novel(self):
        """Custom coefficients must differ from all known baselines."""
        for known_name, known in [
            ("schulz_classic", SCHULZ_CLASSIC),
            ("schulz_conservative", SCHULZ_CONSERVATIVE),
            ("reference_coefficients", COEFFICIENTS),
        ]:
            diff = sum(
                sum((a - b) ** 2 for a, b in zip(t1, t2))
                for t1, t2 in zip(self.coefficients, known)
            )
            assert diff > 0.01, (
                f"Custom coefficients too similar to {known_name} (diff={diff:.6f})"
            )

    def test_beats_conservative_on_convergence(self):
        """Custom schedule must achieve lower avg error than schulz_conservative."""
        with open("/app/matrix_specs.json") as f:
            specs = json.load(f)

        custom_errors = []
        conservative_errors = []
        for mat_spec in specs["matrices"]:
            np.random.seed(mat_spec["seed"])
            X = np.random.randn(mat_spec["rows"], mat_spec["cols"])

            custom_result = standard_newton_schulz(X, self.coefficients)
            conservative_result = standard_newton_schulz(X, SCHULZ_CONSERVATIVE)

            custom_errors.append(compute_polar_error(custom_result))
            conservative_errors.append(compute_polar_error(conservative_result))

        custom_avg = np.mean(custom_errors)
        conservative_avg = np.mean(conservative_errors)
        assert custom_avg < conservative_avg, (
            f"Custom avg error ({custom_avg:.6f}) must be less than "
            f"conservative ({conservative_avg:.6f})"
        )


class TestEvaluationPipeline:
    """Verify the evaluation pipeline produces correct outputs."""

    def test_database_exists(self):
        assert os.path.exists("/app/benchmark.db"), "benchmark.db not found"

    def test_database_tables(self):
        conn = sqlite3.connect("/app/benchmark.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "benchmark_results" in tables, "Missing benchmark_results table"
        assert "configurations" in tables, "Missing configurations table"
        assert "matrices" in tables, "Missing matrices table"
        assert "stability_results" in tables, "Missing stability_results table"

    def test_database_configuration_count(self):
        conn = sqlite3.connect("/app/benchmark.db")
        count = conn.execute("SELECT COUNT(*) FROM configurations").fetchone()[0]
        conn.close()
        assert count == 3, f"Expected 3 configurations, got {count}"

    def test_database_matrix_count(self):
        conn = sqlite3.connect("/app/benchmark.db")
        count = conn.execute("SELECT COUNT(*) FROM matrices").fetchone()[0]
        conn.close()
        assert count == 6, f"Expected 6 matrices, got {count}"

    def test_database_benchmark_results_count(self):
        conn = sqlite3.connect("/app/benchmark.db")
        count = conn.execute("SELECT COUNT(*) FROM benchmark_results").fetchone()[0]
        conn.close()
        assert count == 18, f"Expected 18 benchmark results (3x6), got {count}"

    def test_database_stability_results_count(self):
        conn = sqlite3.connect("/app/benchmark.db")
        count = conn.execute("SELECT COUNT(*) FROM stability_results").fetchone()[0]
        conn.close()
        assert count == 9, f"Expected 9 stability results (3x3), got {count}"

    def test_report_exists(self):
        assert os.path.exists("/app/evaluation_report.json"), (
            "evaluation_report.json not found"
        )

    def test_report_structure(self):
        with open("/app/evaluation_report.json") as f:
            report = json.load(f)
        assert "configurations" in report
        configs = report["configurations"]
        assert len(configs) == 3, f"Expected 3 configs, got {len(configs)}"
        names = {c["name"] for c in configs}
        assert names == {"schulz_classic", "schulz_conservative", "custom_optimized"}
        for cfg in configs:
            assert "avg_orthogonality_error" in cfg, (
                f"Missing avg_orthogonality_error in {cfg['name']}"
            )
            assert "stability_metric" in cfg, (
                f"Missing stability_metric in {cfg['name']}"
            )
            assert "optimal_restarts_1" in cfg, (
                f"Missing optimal_restarts_1 in {cfg['name']}"
            )
            assert "rank" in cfg, f"Missing rank in {cfg['name']}"

    def test_report_rankings_consistent(self):
        with open("/app/evaluation_report.json") as f:
            report = json.load(f)
        configs = sorted(report["configurations"], key=lambda c: c["rank"])
        ranks = [c["rank"] for c in configs]
        assert ranks == [1, 2, 3], f"Ranks should be [1, 2, 3], got {ranks}"
        for i in range(len(configs) - 1):
            assert configs[i]["avg_orthogonality_error"] <= configs[i + 1]["avg_orthogonality_error"] + 1e-10, (
                f"Rank {configs[i]['rank']} error {configs[i]['avg_orthogonality_error']} "
                f"> rank {configs[i+1]['rank']} error {configs[i+1]['avg_orthogonality_error']}"
            )

    def test_conservative_ranks_worst(self):
        """The conservative config with slower convergence should rank worst."""
        with open("/app/evaluation_report.json") as f:
            report = json.load(f)
        sc = [c for c in report["configurations"] if c["name"] == "schulz_conservative"][0]
        assert sc["rank"] == 3, f"schulz_conservative should rank 3, got {sc['rank']}"

    def test_report_metrics_valid(self):
        with open("/app/evaluation_report.json") as f:
            report = json.load(f)
        for cfg in report["configurations"]:
            assert cfg["avg_orthogonality_error"] > 0, (
                f"{cfg['name']}: error should be positive"
            )
            assert cfg["avg_orthogonality_error"] < 2.0, (
                f"{cfg['name']}: error too large ({cfg['avg_orthogonality_error']})"
            )
            assert cfg["stability_metric"] > 0, (
                f"{cfg['name']}: stability metric should be positive"
            )
            assert np.isfinite(cfg["stability_metric"]), (
                f"{cfg['name']}: stability metric not finite"
            )
            restarts = cfg["optimal_restarts_1"]
            assert isinstance(restarts, list), (
                f"{cfg['name']}: optimal_restarts_1 should be list"
            )
            assert len(restarts) == 1, (
                f"{cfg['name']}: expected 1 restart position, got {len(restarts)}"
            )
            assert 1 <= restarts[0] <= 4, (
                f"{cfg['name']}: restart position {restarts[0]} out of range [1,4]"
            )

    def test_report_stability_matches_database(self):
        """Report stability metric should match database no-restart entry."""
        with open("/app/evaluation_report.json") as f:
            report = json.load(f)
        conn = sqlite3.connect("/app/benchmark.db")
        for cfg in report["configurations"]:
            name = cfg["name"]
            reported_metric = cfg["stability_metric"]
            config_id = conn.execute(
                "SELECT id FROM configurations WHERE name=?", (name,)
            ).fetchone()[0]
            db_metric = conn.execute(
                "SELECT stability_metric FROM stability_results WHERE config_id=? AND num_restarts=0",
                (config_id,),
            ).fetchone()[0]
            assert abs(reported_metric - db_metric) < 1e-10, (
                f"{name}: report metric {reported_metric} != db metric {db_metric}"
            )
        conn.close()
