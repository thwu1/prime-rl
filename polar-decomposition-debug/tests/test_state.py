
import numpy as np
import pytest
import json
import sqlite3
import os
from itertools import combinations


class TestStandardNS:
    """Verify the reference standard Newton-Schulz implementation."""

    def test_produces_polar_factor(self):
        """Standard NS should produce a matrix with singular values close to 1."""
        from polar_decomp.standard_ns import standard_newton_schulz
        from polar_decomp.coefficients import CLASSICAL_COEFFICIENTS

        rng = np.random.RandomState(42)
        X = rng.randn(8, 16)

        result = standard_newton_schulz(X, CLASSICAL_COEFFICIENTS)
        S = np.linalg.svd(result, compute_uv=False)

        np.testing.assert_allclose(S, 1.0, atol=1e-3,
            err_msg="Standard NS should produce near-unit singular values")


class TestGramNS:
    """Verify that Gram Newton-Schulz matches the standard implementation."""

    def test_matches_standard_no_restart(self):
        """Gram NS without restart should match standard NS."""
        from polar_decomp.standard_ns import standard_newton_schulz
        from polar_decomp.gram_ns import gram_newton_schulz
        from polar_decomp.coefficients import CLASSICAL_COEFFICIENTS

        rng = np.random.RandomState(42)
        X = rng.randn(8, 16)

        result_std = standard_newton_schulz(X, CLASSICAL_COEFFICIENTS)
        result_gram = gram_newton_schulz(X, CLASSICAL_COEFFICIENTS)

        np.testing.assert_allclose(result_std, result_gram, atol=1e-6,
            err_msg="Gram NS should match standard NS without restart")

    def test_matches_standard_with_restart(self):
        """Gram NS with restarts should still match standard NS."""
        from polar_decomp.standard_ns import standard_newton_schulz
        from polar_decomp.gram_ns import gram_newton_schulz
        from polar_decomp.coefficients import CLASSICAL_COEFFICIENTS

        rng = np.random.RandomState(123)
        X = rng.randn(6, 24)

        result_std = standard_newton_schulz(X, CLASSICAL_COEFFICIENTS)
        result_gram = gram_newton_schulz(X, CLASSICAL_COEFFICIENTS,
                                         restart_iterations=[2, 4])

        np.testing.assert_allclose(result_std, result_gram, atol=1e-6,
            err_msg="Gram NS with restarts should match standard NS")

    def test_square_matrix(self):
        """Gram NS should work correctly on square matrices."""
        from polar_decomp.standard_ns import standard_newton_schulz
        from polar_decomp.gram_ns import gram_newton_schulz
        from polar_decomp.coefficients import CLASSICAL_COEFFICIENTS

        rng = np.random.RandomState(999)
        X = rng.randn(10, 10)

        result_std = standard_newton_schulz(X, CLASSICAL_COEFFICIENTS)
        result_gram = gram_newton_schulz(X, CLASSICAL_COEFFICIENTS)

        np.testing.assert_allclose(result_std, result_gram, atol=1e-6,
            err_msg="Gram NS should handle square matrices correctly")

    def test_tall_matrix(self):
        """Gram NS should work on tall-skinny matrices (internal transpose)."""
        from polar_decomp.standard_ns import standard_newton_schulz
        from polar_decomp.gram_ns import gram_newton_schulz
        from polar_decomp.coefficients import CLASSICAL_COEFFICIENTS

        rng = np.random.RandomState(77)
        X = rng.randn(20, 8)

        result_std = standard_newton_schulz(X, CLASSICAL_COEFFICIENTS)
        result_gram = gram_newton_schulz(X, CLASSICAL_COEFFICIENTS,
                                         restart_iterations=[3])

        np.testing.assert_allclose(result_std, result_gram, atol=1e-6,
            err_msg="Gram NS should handle tall matrices via internal transpose")

    def test_batch(self):
        """Gram NS should handle batched input correctly."""
        from polar_decomp.standard_ns import standard_newton_schulz
        from polar_decomp.gram_ns import gram_newton_schulz
        from polar_decomp.coefficients import CLASSICAL_COEFFICIENTS

        rng = np.random.RandomState(42)
        X = rng.randn(3, 6, 12)

        result_std = standard_newton_schulz(X, CLASSICAL_COEFFICIENTS)
        result_gram = gram_newton_schulz(X, CLASSICAL_COEFFICIENTS,
                                         restart_iterations=[3])

        np.testing.assert_allclose(result_std, result_gram, atol=1e-6,
            err_msg="Gram NS should handle batched input")

    def test_you_coefficients(self):
        """Gram NS with optimized You coefficients should match standard NS."""
        from polar_decomp.standard_ns import standard_newton_schulz
        from polar_decomp.gram_ns import gram_newton_schulz
        from polar_decomp.coefficients import YOU_COEFFICIENTS

        rng = np.random.RandomState(55)
        X = rng.randn(4, 32)

        result_std = standard_newton_schulz(X, YOU_COEFFICIENTS)
        result_gram = gram_newton_schulz(X, YOU_COEFFICIENTS,
                                         restart_iterations=[2])

        np.testing.assert_allclose(result_std, result_gram, atol=1e-6,
            err_msg="Gram NS with You coefficients should match standard NS")


class TestStabilitySimulation:
    """Verify the eigenvalue evolution simulation."""

    def test_convergence(self):
        """Simulation should predict convergence to unit singular values."""
        from polar_decomp.stability import simulate_eigenvalue_evolution
        from polar_decomp.coefficients import CLASSICAL_COEFFICIENTS

        eigenvalues = np.array([0.1, 0.3, 0.5, 0.7, 0.9])

        q_values = simulate_eigenvalue_evolution(
            eigenvalues, CLASSICAL_COEFFICIENTS, perturbation=0.0)

        final_q = q_values[f'Q_{len(CLASSICAL_COEFFICIENTS) - 1}']
        final_sigma = final_q * eigenvalues

        np.testing.assert_allclose(final_sigma, 1.0, atol=1e-3,
            err_msg="Simulation should predict convergence to 1")

    def test_restart_invariance(self):
        """With zero perturbation, restart should not change final singular values.

        The restart is a mathematical identity in exact arithmetic: it just
        reformulates the same computation. So the final singular values
        (q_accumulated * eigenvalues) should be the same regardless of
        restart schedule when perturbation is zero.
        """
        from polar_decomp.stability import simulate_eigenvalue_evolution

        eigenvalues = np.array([0.2, 0.4, 0.6, 0.8])
        coefs = [(1.875, -1.25, 0.375)] * 5
        num_iters = len(coefs)
        restart_pos = 2

        # Without restart
        q_no = simulate_eigenvalue_evolution(
            eigenvalues, coefs, perturbation=0.0)
        final_sv_no = q_no[f'Q_{num_iters - 1}'] * eigenvalues

        # With restart at position 2
        q_yes = simulate_eigenvalue_evolution(
            eigenvalues, coefs, perturbation=0.0,
            restart_indices=[restart_pos])

        # Pre-restart Q values are identical in both simulations.
        # After restart, eigenvalues were multiplied by q_pre_restart.
        # So: final_sv = q_post_restart * eigenvalues * q_pre_restart
        q_pre_restart = q_no[f'Q_{restart_pos - 1}']
        final_sv_yes = q_yes[f'Q_{num_iters - 1}'] * eigenvalues * q_pre_restart

        np.testing.assert_allclose(final_sv_no, final_sv_yes, atol=1e-10,
            err_msg="With zero perturbation, restart should not change "
                    "final singular values")


class TestRestartFinder:
    """Verify the restart position optimizer."""

    def test_single_restart(self):
        """find_optimal_restarts should return the globally optimal position."""
        from polar_decomp.restart_finder import find_optimal_restarts
        from polar_decomp.stability import simulate_eigenvalue_evolution
        from polar_decomp.stability import stability_metric
        from polar_decomp.coefficients import YOU_COEFFICIENTS

        eigenvalues = np.array([0.04, 0.06, 0.10, 0.15, 0.20])
        perturbation = -1e-4

        best_positions, best_metric = find_optimal_restarts(
            eigenvalues, YOU_COEFFICIENTS, perturbation, num_restarts=1)

        # Verify it is actually optimal by exhaustive comparison
        for pos in range(1, len(YOU_COEFFICIENTS)):
            q_vals = simulate_eigenvalue_evolution(
                eigenvalues, YOU_COEFFICIENTS, perturbation,
                restart_indices=[pos])
            metric = stability_metric(q_vals)
            assert best_metric <= metric + 1e-10, (
                f"Position {pos} has metric {metric:.6f} which is better "
                f"than 'optimal' {best_metric:.6f} at {best_positions}")

        assert isinstance(best_positions, list)
        assert len(best_positions) == 1
        assert all(1 <= p < len(YOU_COEFFICIENTS) for p in best_positions)

    def test_multi_restart(self):
        """find_optimal_restarts should work with multiple restart positions."""
        from polar_decomp.restart_finder import find_optimal_restarts
        from polar_decomp.stability import simulate_eigenvalue_evolution
        from polar_decomp.stability import stability_metric
        from polar_decomp.coefficients import YOU_COEFFICIENTS

        eigenvalues = np.array([0.03, 0.05, 0.08, 0.12, 0.18])
        perturbation = -5e-5

        best_positions, best_metric = find_optimal_restarts(
            eigenvalues, YOU_COEFFICIENTS, perturbation, num_restarts=2)

        assert isinstance(best_positions, list)
        assert len(best_positions) == 2
        assert best_positions[0] < best_positions[1], "Positions should be sorted"

        # Verify optimality by exhaustive comparison
        for combo in combinations(range(1, len(YOU_COEFFICIENTS)), 2):
            q_vals = simulate_eigenvalue_evolution(
                eigenvalues, YOU_COEFFICIENTS, perturbation,
                restart_indices=list(combo))
            metric = stability_metric(q_vals)
            assert best_metric <= metric + 1e-10, (
                f"Combo {combo} has metric {metric:.6f} which is better "
                f"than 'optimal' {best_metric:.6f} at {best_positions}")


class TestDatabaseStructure:
    """Verify the SQLite database has been populated correctly."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect('/app/workloads.db')
        conn.row_factory = sqlite3.Row
        yield conn
        conn.close()

    def test_evaluations_count(self, db):
        """Should have the correct number of evaluation rows.

        4 workloads with max_restarts [2, 2, 1, 2].
        Each workload has (max_restarts + 1) configs x 2 coefficient sets.
        Total: (3 + 3 + 2 + 3) x 2 = 22.
        """
        cursor = db.cursor()
        cursor.execute('SELECT COUNT(*) FROM evaluations')
        count = cursor.fetchone()[0]
        assert count == 22, f"Expected 22 evaluations, got {count}"

    def test_evaluations_cover_all_workloads(self, db):
        """Every workload should have evaluations."""
        cursor = db.cursor()
        cursor.execute('SELECT DISTINCT workload_id FROM evaluations')
        workload_ids = {row[0] for row in cursor.fetchall()}
        cursor.execute('SELECT id FROM workloads')
        expected_ids = {row[0] for row in cursor.fetchall()}
        assert workload_ids == expected_ids, (
            f"Missing workload evaluations: {expected_ids - workload_ids}")

    def test_evaluations_cover_both_coef_sets(self, db):
        """Each workload should have evaluations for both CLASSICAL and YOU."""
        cursor = db.cursor()
        cursor.execute(
            'SELECT workload_id, GROUP_CONCAT(DISTINCT coefficient_set) as coefs '
            'FROM evaluations GROUP BY workload_id')
        for row in cursor.fetchall():
            coefs = set(row['coefs'].split(','))
            assert coefs == {'CLASSICAL', 'YOU'}, (
                f"Workload {row['workload_id']} has coefficient sets {coefs}, "
                f"expected both CLASSICAL and YOU")

    def test_recommendations_populated(self, db):
        """Should have a recommendation for each workload."""
        cursor = db.cursor()
        cursor.execute('SELECT COUNT(*) FROM recommendations')
        count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM workloads')
        num_workloads = cursor.fetchone()[0]
        assert count == num_workloads, (
            f"Expected {num_workloads} recommendations, got {count}")


class TestEvaluationCorrectness:
    """Verify the stored evaluation results are numerically correct."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect('/app/workloads.db')
        conn.row_factory = sqlite3.Row
        yield conn
        conn.close()

    def test_stability_metrics_match_recomputation(self, db):
        """Re-compute stability metrics and verify they match stored values."""
        from polar_decomp.stability import simulate_eigenvalue_evolution
        from polar_decomp.stability import stability_metric
        from polar_decomp.coefficients import CLASSICAL_COEFFICIENTS, YOU_COEFFICIENTS

        coef_map = {
            'CLASSICAL': CLASSICAL_COEFFICIENTS,
            'YOU': YOU_COEFFICIENTS,
        }

        cursor = db.cursor()
        cursor.execute(
            'SELECT e.coefficient_set, e.restart_positions, '
            'e.stability_metric, w.eigenvalues, w.perturbation '
            'FROM evaluations e JOIN workloads w ON e.workload_id = w.id')

        checked = 0
        for row in cursor.fetchall():
            coef_set = row['coefficient_set']
            positions = json.loads(row['restart_positions'])
            stored_metric = row['stability_metric']
            eigenvalues = np.array(json.loads(row['eigenvalues']))
            perturbation = row['perturbation']

            coefs = coef_map[coef_set]
            q_values = simulate_eigenvalue_evolution(
                eigenvalues, coefs, perturbation, restart_indices=positions)
            recomputed = stability_metric(q_values)

            np.testing.assert_allclose(
                stored_metric, recomputed, rtol=1e-10,
                err_msg=f"Metric mismatch for {coef_set} restarts={positions}")
            checked += 1

        assert checked == 22, f"Only checked {checked} evaluations"

    def test_restart_positions_are_optimal(self, db):
        """Verify stored restart positions are optimal via exhaustive search."""
        from polar_decomp.stability import simulate_eigenvalue_evolution
        from polar_decomp.stability import stability_metric
        from polar_decomp.coefficients import CLASSICAL_COEFFICIENTS, YOU_COEFFICIENTS

        coef_map = {
            'CLASSICAL': CLASSICAL_COEFFICIENTS,
            'YOU': YOU_COEFFICIENTS,
        }

        cursor = db.cursor()
        cursor.execute(
            'SELECT e.coefficient_set, e.num_restarts, e.restart_positions, '
            'e.stability_metric, w.eigenvalues, w.perturbation '
            'FROM evaluations e JOIN workloads w ON e.workload_id = w.id '
            'WHERE e.num_restarts > 0')

        checked = 0
        for row in cursor.fetchall():
            coef_set = row['coefficient_set']
            num_r = row['num_restarts']
            stored_positions = json.loads(row['restart_positions'])
            stored_metric = row['stability_metric']
            eigenvalues = np.array(json.loads(row['eigenvalues']))
            perturbation = row['perturbation']

            coefs = coef_map[coef_set]
            possible = list(range(1, len(coefs)))

            for combo in combinations(possible, num_r):
                q_vals = simulate_eigenvalue_evolution(
                    eigenvalues, coefs, perturbation,
                    restart_indices=list(combo))
                metric = stability_metric(q_vals)
                assert stored_metric <= metric + 1e-10, (
                    f"{coef_set} restarts={stored_positions}: "
                    f"combo {combo} has better metric {metric:.10f} "
                    f"than stored {stored_metric:.10f}")
            checked += 1

        assert checked > 0, "No evaluations with restarts found"


class TestRecommendationsOptimal:
    """Verify recommendations are the best configurations per workload."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect('/app/workloads.db')
        conn.row_factory = sqlite3.Row
        yield conn
        conn.close()

    def test_recommendation_is_global_best(self, db):
        """Each recommendation should have the lowest metric for its workload."""
        cursor = db.cursor()
        cursor.execute(
            'SELECT r.workload_id, r.best_stability_metric '
            'FROM recommendations r')

        for row in cursor.fetchall():
            wl_id = row['workload_id']
            best_metric = row['best_stability_metric']

            cursor2 = db.cursor()
            cursor2.execute(
                'SELECT MIN(stability_metric) as min_metric '
                'FROM evaluations WHERE workload_id = ?',
                (wl_id,))
            min_metric = cursor2.fetchone()['min_metric']

            np.testing.assert_allclose(
                best_metric, min_metric, rtol=1e-10,
                err_msg=f"Workload {wl_id}: recommendation metric "
                        f"{best_metric} != min evaluation {min_metric}")


class TestReport:
    """Verify the JSON report is correct and consistent with the database."""

    def test_report_exists_and_valid(self):
        """report.json should exist and be valid JSON."""
        assert os.path.exists('/app/report.json'), "report.json not found"
        with open('/app/report.json') as f:
            report = json.load(f)
        assert isinstance(report, dict), "report.json should be a JSON object"

    def test_report_has_all_workloads(self):
        """report.json should have entries for all workloads."""
        with open('/app/report.json') as f:
            report = json.load(f)

        conn = sqlite3.connect('/app/workloads.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM workloads')
        workload_names = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert set(report.keys()) == workload_names, (
            f"Report keys {set(report.keys())} don't match "
            f"workloads {workload_names}")

    def test_report_entry_structure(self):
        """Each report entry should have the required fields."""
        with open('/app/report.json') as f:
            report = json.load(f)

        required_keys = {'coefficient_set', 'num_restarts',
                        'restart_positions', 'stability_metric'}
        for name, entry in report.items():
            assert required_keys <= set(entry.keys()), (
                f"Entry '{name}' missing keys: "
                f"{required_keys - set(entry.keys())}")
            assert isinstance(entry['restart_positions'], list)
            assert isinstance(entry['stability_metric'], float)

    def test_report_matches_database(self):
        """report.json entries should match the recommendations table."""
        with open('/app/report.json') as f:
            report = json.load(f)

        conn = sqlite3.connect('/app/workloads.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            'SELECT w.name, r.best_coefficient_set, r.best_num_restarts, '
            'r.best_restart_positions, r.best_stability_metric '
            'FROM recommendations r JOIN workloads w ON r.workload_id = w.id')

        for row in cursor.fetchall():
            name = row['name']
            assert name in report, f"Workload '{name}' not in report"
            entry = report[name]
            assert entry['coefficient_set'] == row['best_coefficient_set'], (
                f"'{name}': coefficient_set mismatch")
            assert entry['num_restarts'] == row['best_num_restarts'], (
                f"'{name}': num_restarts mismatch")
            assert entry['restart_positions'] == json.loads(
                row['best_restart_positions']), (
                f"'{name}': restart_positions mismatch")
            np.testing.assert_allclose(
                entry['stability_metric'], row['best_stability_metric'],
                rtol=1e-10,
                err_msg=f"'{name}': stability_metric mismatch")

        conn.close()


def _better_by_stability(conn, workload_id, max_restarts):
    """Helper: determine which coefficient set has lower stability metric."""
    cursor = conn.cursor()
    cursor.execute(
        'SELECT coefficient_set FROM evaluations '
        'WHERE workload_id = ? AND num_restarts = ? '
        'ORDER BY stability_metric ASC LIMIT 1',
        (workload_id, max_restarts))
    row = cursor.fetchone()
    return row['coefficient_set']


class TestConvergenceAnalysis:
    """Verify the convergence analysis JSON is correct and consistent."""

    def test_file_exists_and_valid(self):
        """convergence_analysis.json should exist and be valid JSON."""
        assert os.path.exists('/app/convergence_analysis.json'), \
            "convergence_analysis.json not found"
        with open('/app/convergence_analysis.json') as f:
            analysis = json.load(f)
        assert isinstance(analysis, dict)

    def test_has_all_workloads(self):
        """convergence_analysis.json should cover all workloads."""
        with open('/app/convergence_analysis.json') as f:
            analysis = json.load(f)
        conn = sqlite3.connect('/app/workloads.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM workloads')
        workload_names = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert set(analysis.keys()) == workload_names, (
            f"Analysis keys {set(analysis.keys())} don't match "
            f"workloads {workload_names}")

    def test_entry_structure(self):
        """Each entry must have the required fields with correct types."""
        with open('/app/convergence_analysis.json') as f:
            analysis = json.load(f)
        required_keys = {'CLASSICAL_converge_iter', 'YOU_converge_iter',
                        'recommended_set'}
        for name, entry in analysis.items():
            assert required_keys <= set(entry.keys()), (
                f"Entry '{name}' missing keys: "
                f"{required_keys - set(entry.keys())}")
            for key in ['CLASSICAL_converge_iter', 'YOU_converge_iter']:
                assert entry[key] is None or isinstance(entry[key], int), (
                    f"'{name}'.{key} must be int or null, got {type(entry[key])}")
            assert entry['recommended_set'] in ('CLASSICAL', 'YOU'), (
                f"'{name}'.recommended_set must be CLASSICAL or YOU, "
                f"got {entry['recommended_set']}")

    def test_convergence_iterations_correct(self):
        """Recompute convergence iterations and verify they match."""
        from polar_decomp.stability import simulate_eigenvalue_evolution
        from polar_decomp.coefficients import CLASSICAL_COEFFICIENTS, YOU_COEFFICIENTS

        with open('/app/convergence_analysis.json') as f:
            analysis = json.load(f)

        conn = sqlite3.connect('/app/workloads.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT name, eigenvalues FROM workloads')

        coef_map = {
            'CLASSICAL': CLASSICAL_COEFFICIENTS,
            'YOU': YOU_COEFFICIENTS,
        }

        for row in cursor.fetchall():
            name = row['name']
            eigenvalues = np.array(json.loads(row['eigenvalues']))
            entry = analysis[name]

            for set_name, coefs in coef_map.items():
                q_values = simulate_eigenvalue_evolution(
                    eigenvalues, coefs, perturbation=0.0, restart_indices=[])

                expected_iter = None
                for i in range(len(coefs)):
                    q = q_values[f'Q_{i}']
                    sv = q * eigenvalues
                    if np.all(np.abs(sv - 1.0) < 1e-3):
                        expected_iter = i
                        break

                key = f'{set_name}_converge_iter'
                assert entry[key] == expected_iter, (
                    f"{name}.{key}: expected {expected_iter}, "
                    f"got {entry[key]}")
        conn.close()

    def test_recommended_set_correct(self):
        """Verify recommended_set follows the tiebreaking rules."""
        with open('/app/convergence_analysis.json') as f:
            analysis = json.load(f)

        conn = sqlite3.connect('/app/workloads.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, max_restarts FROM workloads')

        for row in cursor.fetchall():
            name = row['name']
            entry = analysis[name]
            c_iter = entry['CLASSICAL_converge_iter']
            y_iter = entry['YOU_converge_iter']

            if c_iter is not None and y_iter is not None:
                if c_iter < y_iter:
                    expected = 'CLASSICAL'
                elif y_iter < c_iter:
                    expected = 'YOU'
                else:
                    expected = _better_by_stability(
                        conn, row['id'], row['max_restarts'])
            elif c_iter is not None:
                expected = 'CLASSICAL'
            elif y_iter is not None:
                expected = 'YOU'
            else:
                expected = _better_by_stability(
                    conn, row['id'], row['max_restarts'])

            assert entry['recommended_set'] == expected, (
                f"{name}: expected recommended_set={expected}, "
                f"got {entry['recommended_set']}")
        conn.close()
