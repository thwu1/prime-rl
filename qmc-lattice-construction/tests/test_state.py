
import json
import os
import sys
import sqlite3
import numpy as np
import pytest


RESULTS_PATH = "/app/results/benchmark.json"
DB_PATH = "/app/results/benchmark.db"
PLOT_PATH = "/app/results/convergence.png"
SCRIPT_PATH = "/app/results/convergence.gp"


@pytest.fixture
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.isfile(RESULTS_PATH), "benchmark.json not found"

    def test_results_structure(self, results):
        required_keys = [
            "dimension", "exact_integral", "qmc_estimate", "qmc_error",
            "mc_estimate", "qmc_convergence_rate", "mc_convergence_rate",
            "generating_vector", "n_points", "n_shifts", "convergence"
        ]
        for key in required_keys:
            assert key in results, f"Missing key: {key}"
        conv = results["convergence"]
        for key in ["n_values", "qmc_errors", "mc_errors"]:
            assert key in conv, f"Missing convergence key: {key}"


class TestExactIntegral:
    def test_exact_integral_matches_formula(self, results):
        d = results["dimension"]
        coeffs = np.array([1.0 / j for j in range(1, d + 1)])
        expected = float(np.prod((np.exp(coeffs) - 1.0) / coeffs))
        assert abs(results["exact_integral"] - expected) < 1e-10, (
            f"Exact integral mismatch: got {results['exact_integral']}, "
            f"expected {expected}"
        )


class TestQMCAccuracy:
    def test_qmc_error_below_threshold(self, results):
        assert results["qmc_error"] < 5e-4, (
            f"QMC error too large: {results['qmc_error']:.2e}"
        )

    def test_qmc_beats_mc_error(self, results):
        assert results["qmc_error"] < results.get("mc_error", 1.0), (
            f"QMC error ({results['qmc_error']:.2e}) not better than "
            f"MC error ({results.get('mc_error', 'N/A')})"
        )


class TestConvergenceRate:
    def test_qmc_rate_above_threshold(self, results):
        rate = results["qmc_convergence_rate"]
        assert rate > 0.65, (
            f"QMC convergence rate too low: {rate:.3f} (need > 0.65)"
        )

    def test_qmc_rate_exceeds_mc(self, results):
        qmc_rate = results["qmc_convergence_rate"]
        mc_rate = results["mc_convergence_rate"]
        assert qmc_rate > mc_rate + 0.1, (
            f"QMC rate ({qmc_rate:.3f}) not substantially better than "
            f"MC rate ({mc_rate:.3f})"
        )


class TestGeneratingVector:
    def test_vector_length(self, results):
        z = results["generating_vector"]
        d = results["dimension"]
        assert len(z) == d, f"Vector length {len(z)} != dimension {d}"

    def test_components_valid(self, results):
        z = results["generating_vector"]
        n = results["n_points"]
        for i, zi in enumerate(z):
            assert isinstance(zi, int), f"z[{i}] = {zi} is not int"
            assert 1 <= zi < n, f"z[{i}] = {zi} not in [1, {n-1}]"

    def test_first_component_is_one(self, results):
        z = results["generating_vector"]
        assert z[0] == 1, f"z[0] = {z[0]}, expected 1"


class TestConvergenceData:
    def test_enough_data_points(self, results):
        conv = results["convergence"]
        assert len(conv["n_values"]) >= 4, "Need at least 4 convergence points"

    def test_array_lengths_match(self, results):
        conv = results["convergence"]
        n_pts = len(conv["n_values"])
        assert len(conv["qmc_errors"]) == n_pts
        assert len(conv["mc_errors"]) == n_pts

    def test_qmc_errors_generally_decrease(self, results):
        conv = results["convergence"]
        qmc_errs = conv["qmc_errors"]
        assert qmc_errs[-1] < qmc_errs[0], (
            f"QMC errors not decreasing: first={qmc_errs[0]:.2e}, "
            f"last={qmc_errs[-1]:.2e}"
        )


class TestIntegrationFunctionality:
    def test_independent_small_qmc(self):
        """Run an independent small-scale QMC integration to verify code works."""
        sys.path.insert(0, "/app")
        try:
            from cbc import construct_generating_vector
            from lattice import shifted_lattice_estimate
        except (ImportError, OSError):
            pytest.skip("Cannot import lattice/cbc modules")

        n = 127
        d = 3
        weights = [1.0, 0.25, 0.1111]
        coeffs = np.array([1.0, 0.5, 1.0 / 3.0])
        func = lambda x: np.exp(x @ coeffs)
        exact = float(np.prod((np.exp(coeffs) - 1.0) / coeffs))

        z = construct_generating_vector(n, d, weights)
        assert len(z) == d
        assert all(1 <= zi < n for zi in z)

        est = shifted_lattice_estimate(func, z, n, d, n_shifts=20, seed=999)
        err = abs(est - exact)
        assert err < 5e-3, (
            f"Small QMC test failed: estimate={est:.6f}, "
            f"exact={exact:.6f}, error={err:.2e}"
        )

    def test_lattice_points_in_unit_cube(self):
        """Verify that generated lattice points lie in [0, 1)."""
        sys.path.insert(0, "/app")
        try:
            from lattice import generate_lattice_points
        except (ImportError, OSError):
            pytest.skip("Cannot import lattice module")

        z = [1, 3, 5]
        n = 11
        d = 3
        pts = generate_lattice_points(z, n, d)
        assert pts.shape == (n, d), f"Wrong shape: {pts.shape}"
        assert np.all(pts >= 0.0), "Points below 0"
        assert np.all(pts < 1.0), f"Points >= 1: max={pts.max()}"

    def test_kernel_omega_at_zero(self):
        """Verify omega(0) = 2*pi^2 * B_2(0) = pi^2/3."""
        sys.path.insert(0, "/app")
        try:
            from kernels import omega
        except (ImportError, OSError):
            pytest.skip("Cannot import kernels module")

        expected = np.pi ** 2 / 3.0
        actual = float(omega(0.0))
        assert abs(actual - expected) < 1e-10, (
            f"omega(0) = {actual}, expected pi^2/3 = {expected}"
        )


class TestConvergencePlot:
    def test_gnuplot_script_exists(self):
        assert os.path.isfile(SCRIPT_PATH), "convergence.gp not found"

    def test_gnuplot_script_is_valid(self):
        with open(SCRIPT_PATH) as f:
            content = f.read().lower()
        assert "set terminal" in content, "gnuplot script missing 'set terminal' directive"
        assert "plot" in content, "gnuplot script missing 'plot' command"
        assert "log" in content, "gnuplot script missing log scale directive"

    def test_convergence_png_exists(self):
        assert os.path.isfile(PLOT_PATH), "convergence.png not found"

    def test_convergence_png_valid(self):
        with open(PLOT_PATH, "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', "convergence.png is not a valid PNG file"
        assert os.path.getsize(PLOT_PATH) > 1024, "convergence.png is suspiciously small"


class TestSQLiteDatabase:
    def test_database_exists(self):
        assert os.path.isfile(DB_PATH), "benchmark.db not found"

    def test_table_schema(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("PRAGMA table_info(convergence_results)")
        columns = {row[1]: row[2].upper() for row in cursor.fetchall()}
        conn.close()
        assert "n_points" in columns, "Missing column: n_points"
        assert "qmc_error" in columns, "Missing column: qmc_error"
        assert "mc_error" in columns, "Missing column: mc_error"

    def test_data_populated(self):
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT COUNT(*) FROM convergence_results").fetchone()[0]
        conn.close()
        assert rows >= 4, f"Expected >= 4 rows in convergence_results, got {rows}"

    def test_data_matches_json(self, results):
        conv = results["convergence"]
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT n_points, qmc_error, mc_error FROM convergence_results ORDER BY n_points"
        ).fetchall()
        conn.close()

        json_sorted = sorted(zip(conv["n_values"], conv["qmc_errors"], conv["mc_errors"]))
        assert len(rows) == len(json_sorted), (
            f"Row count mismatch: DB={len(rows)}, JSON={len(json_sorted)}"
        )
        for (jn, jq, jm), (dn, dq, dm) in zip(json_sorted, rows):
            assert jn == dn, f"n_points mismatch: JSON={jn}, DB={dn}"
            assert abs(jq - dq) < 1e-8, f"qmc_error mismatch at n={jn}"
            assert abs(jm - dm) < 1e-8, f"mc_error mismatch at n={jn}"
