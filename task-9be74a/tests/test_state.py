"""
Tests for rough Heston calibration and pricing pipeline.
"""

import json
import os
import numpy as np
import pytest


# ============================================================
# Fixture: load all output files
# ============================================================

@pytest.fixture
def calibrated_params():
    with open("/app/calibrated_params.json") as f:
        return json.load(f)


@pytest.fixture
def normalized_leverage():
    with open("/app/normalized_leverage.json") as f:
        return json.load(f)


@pytest.fixture
def model_impvols():
    with open("/app/model_impvols.json") as f:
        return json.load(f)


# ============================================================
# Test 1: Output files exist and have valid structure
# ============================================================

class TestOutputStructure:
    def test_calibrated_params_exists(self):
        assert os.path.exists("/app/calibrated_params.json")

    def test_normalized_leverage_exists(self):
        assert os.path.exists("/app/normalized_leverage.json")

    def test_model_impvols_exists(self):
        assert os.path.exists("/app/model_impvols.json")

    def test_calibrated_params_keys(self, calibrated_params):
        for key in ["H", "nu", "rho", "lbd"]:
            assert key in calibrated_params, f"Missing key '{key}'"
            assert isinstance(calibrated_params[key], (int, float))

    def test_normalized_leverage_keys(self, normalized_leverage):
        for key in ["expiries", "empirical", "model"]:
            assert key in normalized_leverage, f"Missing key '{key}'"
            assert isinstance(normalized_leverage[key], list)

    def test_normalized_leverage_lengths(self, normalized_leverage):
        n = len(normalized_leverage["expiries"])
        assert n == 48, f"Expected 48 expiries, got {n}"
        assert len(normalized_leverage["empirical"]) == n
        assert len(normalized_leverage["model"]) == n

    def test_model_impvols_keys(self, model_impvols):
        for key in ["maturities", "log_strikes", "impvols"]:
            assert key in model_impvols, f"Missing key '{key}'"

    def test_model_impvols_shape(self, model_impvols):
        assert len(model_impvols["maturities"]) == 3
        assert len(model_impvols["log_strikes"]) == 5
        assert len(model_impvols["impvols"]) == 3
        for row in model_impvols["impvols"]:
            assert len(row) == 5


# ============================================================
# Test 2: Calibrated parameters are physically reasonable
# ============================================================

class TestCalibratedParams:
    def test_H_range(self, calibrated_params):
        H = calibrated_params["H"]
        assert 1e-4 <= H <= 1.0, f"H={H} out of range"

    def test_nu_positive(self, calibrated_params):
        nu = calibrated_params["nu"]
        assert 0.01 <= nu <= 10, f"nu={nu} out of range"

    def test_rho_negative(self, calibrated_params):
        rho = calibrated_params["rho"]
        assert -1.0 < rho < 0, f"rho={rho} not in (-1, 0)"

    def test_lambda_nonnegative(self, calibrated_params):
        lbd = calibrated_params["lbd"]
        assert 0 <= lbd <= 10, f"lbd={lbd} out of range"


# ============================================================
# Test 3: Normalized leverage contract values
# ============================================================

class TestNormalizedLeverage:
    def test_empirical_leverage_negative(self, normalized_leverage):
        """Leverage should be negative (negative spot-vol correlation in equity)."""
        emp = np.array(normalized_leverage["empirical"])
        assert np.mean(emp < 0) > 0.9, "Expected most leverage values to be negative"

    def test_empirical_leverage_magnitude(self, normalized_leverage):
        """Leverage magnitude should be in realistic range."""
        emp = np.array(normalized_leverage["empirical"])
        assert np.all(np.abs(emp) < 1.0), "Leverage magnitudes unrealistically large"

    def test_model_fit_rmse(self, normalized_leverage):
        """Model should fit empirical leverage with RMSE < 0.015."""
        emp = np.array(normalized_leverage["empirical"])
        mod = np.array(normalized_leverage["model"])
        rmse = np.sqrt(np.mean((emp - mod) ** 2))
        assert rmse < 0.015, f"Leverage fit RMSE={rmse:.6f} too large (expected < 0.015)"

    def test_leverage_monotonically_more_negative(self, normalized_leverage):
        """Empirical leverage should generally become more negative with maturity."""
        emp = np.array(normalized_leverage["empirical"])
        n = len(emp)
        q1_avg = np.mean(emp[: n // 4])
        q4_avg = np.mean(emp[3 * n // 4:])
        assert q4_avg < q1_avg, "Long-dated leverage should be more negative than short-dated"

    def test_expiries_sorted(self, normalized_leverage):
        expiries = np.array(normalized_leverage["expiries"])
        assert np.all(np.diff(expiries) > 0), "Expiries must be sorted ascending"


# ============================================================
# Test 4: Model implied volatilities
# ============================================================

class TestModelImpliedVols:
    def test_impvols_are_finite(self, model_impvols):
        for i, row in enumerate(model_impvols["impvols"]):
            for j, v in enumerate(row):
                assert np.isfinite(v), f"impvol[{i}][{j}]={v} is not finite"

    def test_impvols_in_realistic_range(self, model_impvols):
        """All implied vols should be between 5% and 100%."""
        for i, row in enumerate(model_impvols["impvols"]):
            for j, v in enumerate(row):
                assert 0.05 < v < 1.0, f"impvol[{i}][{j}]={v} outside (0.05, 1.0)"

    def test_negative_skew(self, model_impvols):
        """Equity smiles should have negative skew: vol at k=-0.1 > vol at k=+0.1."""
        for i, row in enumerate(model_impvols["impvols"]):
            assert row[0] > row[-1], (
                f"Maturity {model_impvols['maturities'][i]}: "
                f"vol(k=-0.1)={row[0]:.4f} should exceed vol(k=+0.1)={row[-1]:.4f}"
            )

    def test_atm_vol_level(self, model_impvols):
        """ATM implied vol (k=0) should be in the range 10%-35% for SPX-like data."""
        for i, row in enumerate(model_impvols["impvols"]):
            atm = row[2]
            assert 0.10 < atm < 0.35, (
                f"ATM vol at tau={model_impvols['maturities'][i]} is {atm:.4f}, "
                "expected (0.10, 0.35)"
            )

    def test_atm_vol_reference_values(self, model_impvols):
        """ATM vols should be close to reference values computed with fixed rough params."""
        ref_atm = [0.1895, 0.1993, 0.2030]
        for i, row in enumerate(model_impvols["impvols"]):
            atm = row[2]
            assert abs(atm - ref_atm[i]) < 0.02, (
                f"ATM vol at tau={model_impvols['maturities'][i]}: "
                f"got {atm:.4f}, expected ~{ref_atm[i]:.4f} (tol=0.02)"
            )

    def test_smile_curvature(self, model_impvols):
        """The smile should have convexity: vol(k=-0.1) + vol(k=+0.1) > 2*vol(k=0)."""
        for i, row in enumerate(model_impvols["impvols"]):
            wings = row[0] + row[-1]
            center = 2 * row[2]
            assert wings > center, (
                f"Maturity {model_impvols['maturities'][i]}: "
                f"no smile convexity ({wings:.4f} <= {center:.4f})"
            )

    def test_term_structure_of_skew(self, model_impvols):
        """Skew (vol(k=-0.1) - vol(k=+0.1)) should decrease with maturity."""
        skews = []
        for row in model_impvols["impvols"]:
            skews.append(row[0] - row[-1])
        assert skews[0] > skews[-1], (
            f"Short-term skew {skews[0]:.4f} should exceed long-term skew {skews[-1]:.4f}"
        )


# ============================================================
# Test 5: Cross-consistency checks
# ============================================================

class TestConsistency:
    def test_maturities_match_spec(self, model_impvols):
        assert model_impvols["maturities"] == [0.25, 0.5, 1.0]

    def test_log_strikes_match_spec(self, model_impvols):
        assert model_impvols["log_strikes"] == [-0.1, -0.05, 0.0, 0.05, 0.1]

    def test_impvol_symmetry_broken(self, model_impvols):
        """With rho < 0, vol(k<0) - vol_atm should exceed vol_atm - vol(k>0)."""
        for row in model_impvols["impvols"]:
            left_excess = row[0] - row[2]
            right_deficit = row[2] - row[-1]
            assert left_excess > right_deficit, "Skew asymmetry expected with rho < 0"
