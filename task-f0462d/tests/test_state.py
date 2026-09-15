"""
Tests for the rectangular prism gravity forward model and density inversion.

"""
import json
import math
import os

import pytest

# Ground-truth density model (kg/m^3), 32 prisms indexed as iz*16 + iy*4 + ix
TRUE_DENSITIES = [
    # Bottom layer (iz=0), iy=0..3
    0, 0, 0, 0,
    0, 400, 0, 0,
    0, 0, 600, 0,
    0, 0, 0, 0,
    # Top layer (iz=1), iy=0..3
    0, 0, 0, 0,
    0, 250, 350, 0,
    0, 200, 500, 0,
    0, 0, 100, 0,
]

G = 6.674e-11  # gravitational constant


# ---------------------------------------------------------------------------
# Reference forward model (independent implementation for data-fit check)
# ---------------------------------------------------------------------------

def _safe_log(x, y, z, r):
    """Numerically safe ln(x + r)."""
    if r == 0.0:
        return 0.0
    if x < 0.0:
        if y == 0.0 and z == 0.0:
            return -math.log(-2.0 * x)
        return math.log((y * y + z * z) / (r - x))
    return math.log(x + r)


def _safe_atan2(y, x):
    """Principal-value arctan(y/x) with safe x=0 handling."""
    if x != 0.0:
        return math.atan(y / x)
    if y > 0.0:
        return math.pi / 2.0
    if y < 0.0:
        return -math.pi / 2.0
    return 0.0


def _kernel_u(e, n, u):
    r = math.sqrt(e * e + n * n + u * u)
    return (
        e * _safe_log(n, e, u, r)
        + n * _safe_log(e, n, u, r)
        - u * _safe_atan2(e * n, u * r)
    )


def _ref_gravity_u(obs_e, obs_n, obs_up, prism, density):
    """Reference implementation of vertical gravity for a rectangular prism."""
    w, ep, s, np_, bot, top = prism
    shifts_e = [w - obs_e, ep - obs_e]
    shifts_n = [s - obs_n, np_ - obs_n]
    shifts_up = [bot - obs_up, top - obs_up]
    result = 0.0
    for i in range(2):
        for j in range(2):
            for k in range(2):
                sign = (-1) ** (i + j + k)
                result += sign * _kernel_u(
                    shifts_e[i], shifts_n[j], shifts_up[k]
                )
    return -G * density * result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOutputFilesExist:
    def test_recovered_densities_exist(self):
        assert os.path.exists("/app/recovered_densities.json"), (
            "Output file /app/recovered_densities.json not found"
        )

    def test_laplace_verification_exist(self):
        assert os.path.exists("/app/laplace_verification.json"), (
            "Output file /app/laplace_verification.json not found"
        )

    def test_diagnostics_exist(self):
        assert os.path.exists("/app/inversion_diagnostics.json"), (
            "Output file /app/inversion_diagnostics.json not found"
        )

    def test_density_png_exist(self):
        assert os.path.exists("/app/density_model.png"), (
            "Output file /app/density_model.png not found"
        )


class TestRecoveredDensitiesFormat:
    @pytest.fixture(autouse=True)
    def load_densities(self):
        with open("/app/recovered_densities.json") as f:
            self.data = json.load(f)

    def test_has_densities_key(self):
        assert "densities" in self.data, "Output must contain 'densities' key"

    def test_correct_count(self):
        assert len(self.data["densities"]) == 32, (
            f"Expected 32 densities, got {len(self.data['densities'])}"
        )

    def test_all_numeric(self):
        for i, d in enumerate(self.data["densities"]):
            assert isinstance(d, (int, float)), (
                f"Density [{i}] must be a number, got {type(d)}"
            )


class TestDensityAccuracy:
    @pytest.fixture(autouse=True)
    def load_densities(self):
        with open("/app/recovered_densities.json") as f:
            self.recovered = json.load(f)["densities"]

    def test_rmse(self):
        """Overall RMSE of recovered densities vs true model."""
        mse = sum(
            (r - t) ** 2 for r, t in zip(self.recovered, TRUE_DENSITIES)
        ) / len(TRUE_DENSITIES)
        rmse = math.sqrt(mse)
        assert rmse < 30, (
            f"RMSE = {rmse:.1f} kg/m^3 (must be < 30)"
        )

    def test_zero_density_prisms(self):
        """Prisms with true density 0 must be recovered near zero."""
        for i, (r, t) in enumerate(zip(self.recovered, TRUE_DENSITIES)):
            if t == 0:
                assert abs(r) < 50, (
                    f"Prism {i}: true=0, recovered={r:.1f} kg/m^3 (|d| must be < 50)"
                )

    def test_nonzero_density_prisms(self):
        """Non-zero density prisms must be recovered within 10% relative error."""
        for i, (r, t) in enumerate(zip(self.recovered, TRUE_DENSITIES)):
            if t > 0:
                rel_err = abs(r - t) / t
                assert rel_err < 0.1, (
                    f"Prism {i}: true={t}, recovered={r:.1f}, "
                    f"rel_error={rel_err:.3f} (must be < 0.1)"
                )


class TestLaplaceEquation:
    @pytest.fixture(autouse=True)
    def load_laplace(self):
        with open("/app/laplace_verification.json") as f:
            self.data = json.load(f)

    def test_has_results(self):
        assert "results" in self.data, "Must contain 'results' key"
        assert len(self.data["results"]) > 0, "Must have at least one test point"

    def test_laplace_residual(self):
        """g_ee + g_nn + g_uu must be approximately zero at exterior points."""
        for i, point in enumerate(self.data["results"]):
            g_ee = point["g_ee"]
            g_nn = point["g_nn"]
            g_uu = point["g_uu"]
            laplace = g_ee + g_nn + g_uu
            max_comp = max(abs(g_ee), abs(g_nn), abs(g_uu))
            if max_comp > 0:
                rel_residual = abs(laplace) / max_comp
                assert rel_residual < 1e-6, (
                    f"Laplace not satisfied at point {i}: "
                    f"g_ee={g_ee:.6e}, g_nn={g_nn:.6e}, g_uu={g_uu:.6e}, "
                    f"sum={laplace:.6e}, relative={rel_residual:.2e}"
                )


class TestDataFit:
    """Forward prediction from recovered densities must fit observed data."""

    @pytest.fixture(autouse=True)
    def load_all(self):
        with open("/app/problem_config.json") as f:
            self.config = json.load(f)
        with open("/app/observed_gravity.json") as f:
            self.obs_data = json.load(f)
        with open("/app/recovered_densities.json") as f:
            self.rec_data = json.load(f)

    def test_data_residual(self):
        prisms = self.config["prisms"]
        observations = self.obs_data["observations"]
        densities = self.rec_data["densities"]

        residuals = []
        for obs in observations:
            predicted = 0.0
            for p_idx, prism in enumerate(prisms):
                if abs(densities[p_idx]) > 1e-10:
                    predicted += _ref_gravity_u(
                        obs["easting"], obs["northing"], obs["upward"],
                        prism, densities[p_idx],
                    )
            residuals.append(predicted - obs["g_u"])

        rms = math.sqrt(sum(r ** 2 for r in residuals) / len(residuals))
        max_data = max(abs(o["g_u"]) for o in observations)

        if max_data > 0:
            normalized_rms = rms / max_data
            assert normalized_rms < 0.01, (
                f"Data fit too poor: normalized RMS = {normalized_rms:.6f} (must be < 0.01)"
            )


class TestInversionDiagnostics:
    @pytest.fixture(autouse=True)
    def load_diagnostics(self):
        with open("/app/inversion_diagnostics.json") as f:
            self.data = json.load(f)

    def test_has_required_keys(self):
        required = ["condition_number", "data_rms_misfit", "n_observations", "n_parameters"]
        for key in required:
            assert key in self.data, f"Missing required key: '{key}'"

    def test_condition_number_positive(self):
        cn = self.data["condition_number"]
        assert isinstance(cn, (int, float)), (
            f"condition_number must be numeric, got {type(cn)}"
        )
        assert cn > 0, f"condition_number must be positive, got {cn}"

    def test_data_rms_nonnegative(self):
        rms = self.data["data_rms_misfit"]
        assert isinstance(rms, (int, float)), (
            f"data_rms_misfit must be numeric, got {type(rms)}"
        )
        assert rms >= 0, f"data_rms_misfit must be non-negative, got {rms}"

    def test_n_observations(self):
        assert self.data["n_observations"] == 64, (
            f"n_observations must be 64, got {self.data['n_observations']}"
        )

    def test_n_parameters(self):
        assert self.data["n_parameters"] == 32, (
            f"n_parameters must be 32, got {self.data['n_parameters']}"
        )


class TestDensityVisualization:
    def test_png_exists(self):
        assert os.path.exists("/app/density_model.png"), (
            "density_model.png not found at /app/"
        )

    def test_valid_png_header(self):
        with open("/app/density_model.png", "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', (
            f"File does not have valid PNG magic bytes, got {header[:4]!r}"
        )

    def test_reasonable_file_size(self):
        size = os.path.getsize("/app/density_model.png")
        assert size > 1000, (
            f"PNG file too small ({size} bytes), likely empty or corrupted"
        )
