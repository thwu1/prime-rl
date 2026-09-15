"""

Tests for the 1D compressible Euler solver validation task.
Verifies output files only -- does not import agent code.
"""

import pytest
import numpy as np
import csv
import json
import os


class TestSodShockTube:
    """Verify the Sod shock tube results against known analytical solution features."""

    @pytest.fixture(scope="class")
    def sod_data(self):
        path = "/app/results/sod.csv"
        assert os.path.isfile(path), f"Sod results file not found at {path}"
        data = []
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            assert set(reader.fieldnames) >= {"x", "rho", "v", "p"}, (
                f"CSV must have columns x, rho, v, p; got {reader.fieldnames}"
            )
            for row in reader:
                data.append({
                    "x": float(row["x"]),
                    "rho": float(row["rho"]),
                    "v": float(row["v"]),
                    "p": float(row["p"]),
                })
        return sorted(data, key=lambda r: r["x"])

    def test_sod_row_count(self, sod_data):
        """Must have exactly 64 rows (one per element)."""
        assert len(sod_data) == 64, f"Expected 64 rows, got {len(sod_data)}"

    def test_sod_x_range(self, sod_data):
        """Element centers should span [0, 1]."""
        xs = [r["x"] for r in sod_data]
        assert xs[0] > 0.0 and xs[0] < 0.02
        assert xs[-1] > 0.98 and xs[-1] < 1.0

    def test_sod_density_left_plateau(self, sod_data):
        """Density in undisturbed left region should be ~1.0."""
        left_points = [r for r in sod_data if 0.05 < r["x"] < 0.2]
        rhos = [r["rho"] for r in left_points]
        avg_rho = np.mean(rhos)
        assert abs(avg_rho - 1.0) < 0.02, (
            f"Left plateau density should be ~1.0, got {avg_rho}"
        )

    def test_sod_density_right_plateau(self, sod_data):
        """Density in undisturbed right region should be ~0.125."""
        right_points = [r for r in sod_data if 0.85 < r["x"] < 0.95]
        rhos = [r["rho"] for r in right_points]
        avg_rho = np.mean(rhos)
        assert abs(avg_rho - 0.125) < 0.02, (
            f"Right plateau density should be ~0.125, got {avg_rho}"
        )

    def test_sod_pressure_left_plateau(self, sod_data):
        """Pressure in undisturbed left region should be ~1.0."""
        left_points = [r for r in sod_data if 0.05 < r["x"] < 0.2]
        ps = [r["p"] for r in left_points]
        avg_p = np.mean(ps)
        assert abs(avg_p - 1.0) < 0.02, (
            f"Left plateau pressure should be ~1.0, got {avg_p}"
        )

    def test_sod_pressure_right_plateau(self, sod_data):
        """Pressure in undisturbed right region should be ~0.1."""
        right_points = [r for r in sod_data if 0.85 < r["x"] < 0.95]
        ps = [r["p"] for r in right_points]
        avg_p = np.mean(ps)
        assert abs(avg_p - 0.1) < 0.02, (
            f"Right plateau pressure should be ~0.1, got {avg_p}"
        )

    def test_sod_contact_discontinuity(self, sod_data):
        """Contact discontinuity near x~0.685: density should transition in [0.6, 0.8]."""
        mid_points = [r for r in sod_data if 0.6 < r["x"] < 0.8]
        rhos = [r["rho"] for r in mid_points]
        assert max(rhos) > 0.3, f"Should see density > 0.3 near contact, max={max(rhos)}"
        assert min(rhos) < 0.35, f"Should see density < 0.35 near contact, min={min(rhos)}"

    def test_sod_shock_location(self, sod_data):
        """Shock near x~0.85: density jumps from ~0.265 to ~0.125."""
        shock_region = [r for r in sod_data if 0.78 < r["x"] < 0.92]
        rhos = [r["rho"] for r in shock_region]
        assert min(rhos) < 0.2, f"Should see low density past shock, min={min(rhos)}"
        assert max(rhos) > 0.2, f"Should see higher density before shock, max={max(rhos)}"

    def test_sod_velocity_in_expansion(self, sod_data):
        """Velocity in the expansion fan (x~0.3-0.5) should be positive."""
        fan_points = [r for r in sod_data if 0.3 < r["x"] < 0.5]
        vs = [r["v"] for r in fan_points]
        assert all(v > 0 for v in vs), "Velocity should be positive in expansion fan"

    def test_sod_post_shock_density(self, sod_data):
        """Post-shock density (between contact and shock) should be ~0.265."""
        post_shock = [r for r in sod_data if 0.72 < r["x"] < 0.8]
        if len(post_shock) > 0:
            rhos = [r["rho"] for r in post_shock]
            avg_rho = np.mean(rhos)
            assert abs(avg_rho - 0.265) < 0.06, (
                f"Post-shock density should be ~0.265, got {avg_rho}"
            )


class TestEntropyConservation:
    """Verify entropy conservation properties from JSON output."""

    @pytest.fixture(scope="class")
    def entropy_data(self):
        path = "/app/results/entropy.json"
        assert os.path.isfile(path), f"Entropy results file not found at {path}"
        with open(path, "r") as f:
            data = json.load(f)
        assert "S_initial" in data, "entropy.json must contain S_initial"
        assert "S_final" in data, "entropy.json must contain S_final"
        assert "S_change" in data, "entropy.json must contain S_change"
        return data

    def test_entropy_file_valid(self, entropy_data):
        """Entropy JSON must exist and have required keys."""
        assert entropy_data is not None

    def test_entropy_initial_finite(self, entropy_data):
        """Initial entropy should be a finite number."""
        assert np.isfinite(entropy_data["S_initial"]), (
            f"S_initial is not finite: {entropy_data['S_initial']}"
        )

    def test_entropy_final_finite(self, entropy_data):
        """Final entropy should be a finite number."""
        assert np.isfinite(entropy_data["S_final"]), (
            f"S_final is not finite: {entropy_data['S_final']}"
        )

    def test_entropy_conservation(self, entropy_data):
        """Entropy change must be below 1e-4 (semi-discrete conservation + time error)."""
        S_change = entropy_data["S_change"]
        assert abs(S_change) < 1e-4, (
            f"Entropy change should be < 1e-4, got {S_change}. "
            f"The spatial scheme is not entropy-conservative."
        )

    def test_entropy_change_consistency(self, entropy_data):
        """S_change should equal S_final - S_initial."""
        S0 = entropy_data["S_initial"]
        Sf = entropy_data["S_final"]
        S_change = entropy_data["S_change"]
        expected = Sf - S0
        assert abs(S_change - expected) < 1e-14, (
            f"S_change={S_change} != S_final-S_initial={expected}"
        )

    def test_entropy_initial_plausible(self, entropy_data):
        """Initial entropy should be in a plausible range."""
        S0 = entropy_data["S_initial"]
        assert abs(S0) < 10.0, f"S_initial={S0} seems implausibly large"


class TestSBPVerification:
    """Verify the SBP matrix verification results and independently validate matrices."""

    @pytest.fixture(scope="class")
    def spectral_data(self):
        path = "/app/results/spectral.json"
        assert os.path.isfile(path), f"spectral.json not found at {path}"
        with open(path, "r") as f:
            data = json.load(f)
        assert "sbp_error" in data, "spectral.json must contain sbp_error"
        assert "mass_cond" in data, "spectral.json must contain mass_cond"
        assert "D_spectral_radius" in data, "spectral.json must contain D_spectral_radius"
        return data

    def test_spectral_json_valid(self, spectral_data):
        """spectral.json must exist and have required keys."""
        assert spectral_data is not None

    def test_sbp_error_threshold(self, spectral_data):
        """SBP deviation must be below 1e-10."""
        assert spectral_data["sbp_error"] < 1e-10, (
            f"SBP error {spectral_data['sbp_error']} >= 1e-10"
        )

    def test_mass_cond_finite(self, spectral_data):
        """Mass matrix condition number must be finite and > 1."""
        assert np.isfinite(spectral_data["mass_cond"])
        assert spectral_data["mass_cond"] > 1.0

    def test_spectral_radius_finite(self, spectral_data):
        """Spectral radius of D must be finite and positive."""
        assert np.isfinite(spectral_data["D_spectral_radius"])
        assert spectral_data["D_spectral_radius"] > 0.0

    def test_mass_matrix_csv_exists(self):
        """Mass matrix CSV must exist."""
        assert os.path.isfile("/app/results/mass_matrix.csv"), (
            "mass_matrix.csv not found"
        )

    def test_deriv_matrix_csv_exists(self):
        """Derivative matrix CSV must exist."""
        assert os.path.isfile("/app/results/deriv_matrix.csv"), (
            "deriv_matrix.csv not found"
        )

    def test_matrices_correct_size(self):
        """Both matrices must be 6x6 (N=5 -> N+1=6 nodes)."""
        M = np.loadtxt("/app/results/mass_matrix.csv", delimiter=",")
        D = np.loadtxt("/app/results/deriv_matrix.csv", delimiter=",")
        assert M.shape == (6, 6), f"M shape should be (6,6), got {M.shape}"
        assert D.shape == (6, 6), f"D shape should be (6,6), got {D.shape}"

    def test_mass_matrix_diagonal(self):
        """Mass matrix must be diagonal."""
        M = np.loadtxt("/app/results/mass_matrix.csv", delimiter=",")
        off_diag = M - np.diag(np.diag(M))
        assert np.linalg.norm(off_diag) < 1e-14, "Mass matrix M must be diagonal"

    def test_mass_weights_positive(self):
        """All diagonal entries of M must be positive."""
        M = np.loadtxt("/app/results/mass_matrix.csv", delimiter=",")
        diag = np.diag(M)
        assert np.all(diag > 0), "All diagonal entries of M must be positive"

    def test_mass_weights_sum_to_two(self):
        """Diagonal entries of M must sum to 2 (integral of 1 over [-1,1])."""
        M = np.loadtxt("/app/results/mass_matrix.csv", delimiter=",")
        assert abs(np.trace(M) - 2.0) < 1e-13, (
            f"trace(M) = {np.trace(M)}, expected 2.0"
        )

    def test_mass_weight_symmetry(self):
        """Quadrature weights must be symmetric: w_i = w_{N-i}."""
        M = np.loadtxt("/app/results/mass_matrix.csv", delimiter=",")
        d = np.diag(M)
        n = len(d)
        for i in range(n // 2):
            assert abs(d[i] - d[n - 1 - i]) < 1e-14, (
                f"Weight {i} ({d[i]}) != weight {n-1-i} ({d[n-1-i]})"
            )

    def test_derivative_of_constant_is_zero(self):
        """D applied to constant function must give zero."""
        D = np.loadtxt("/app/results/deriv_matrix.csv", delimiter=",")
        f_const = np.ones(D.shape[0])
        df = D @ f_const
        np.testing.assert_allclose(df, 0.0, atol=1e-13,
                                   err_msg="D @ [1,...,1] should be zero")

    def test_independent_sbp_verification(self):
        """Independently verify the SBP property from CSV matrices."""
        M = np.loadtxt("/app/results/mass_matrix.csv", delimiter=",")
        D = np.loadtxt("/app/results/deriv_matrix.csv", delimiter=",")
        n = M.shape[0]
        Q = M @ D
        B = np.zeros((n, n))
        B[0, 0] = -1.0
        B[-1, -1] = 1.0
        sbp_deviation = np.linalg.norm(Q + Q.T - B, 'fro')
        assert sbp_deviation < 1e-10, (
            f"Independent SBP deviation {sbp_deviation} >= 1e-10"
        )
