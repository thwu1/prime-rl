"""Tests for terrain cast shadow and illumination analysis.

Verifies output files, array metadata, shadow mask correctness at known
locations, illumination physical consistency, and analysis statistics.
"""

import json
import os

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def shadow_arr():
    return np.load("/app/output/cast_shadow.npy")


@pytest.fixture(scope="module")
def illum_arr():
    return np.load("/app/output/illumination.npy")


@pytest.fixture(scope="module")
def analysis():
    with open("/app/output/analysis.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Output existence
# ---------------------------------------------------------------------------

class TestOutputExistence:
    def test_cast_shadow_file(self):
        assert os.path.isfile("/app/output/cast_shadow.npy")

    def test_illumination_file(self):
        assert os.path.isfile("/app/output/illumination.npy")

    def test_analysis_file(self):
        assert os.path.isfile("/app/output/analysis.json")


# ---------------------------------------------------------------------------
# Cast shadow array format
# ---------------------------------------------------------------------------

class TestCastShadowFormat:
    def test_shape(self, shadow_arr):
        assert shadow_arr.shape == (200, 200)

    def test_dtype(self, shadow_arr):
        assert shadow_arr.dtype == np.uint8

    def test_valid_values(self, shadow_arr):
        """Only 0, 1, and 255 are valid pixel values."""
        unique = set(np.unique(shadow_arr))
        assert unique.issubset({0, 1, 255})


# ---------------------------------------------------------------------------
# Illumination array format
# ---------------------------------------------------------------------------

class TestIlluminationFormat:
    def test_shape(self, illum_arr):
        assert illum_arr.shape == (200, 200)

    def test_dtype(self, illum_arr):
        assert illum_arr.dtype in (np.float32, np.float64)


# ---------------------------------------------------------------------------
# Cast shadow pixel accuracy
# ---------------------------------------------------------------------------

class TestCastShadowPixels:
    """Check shadow mask at geometrically unambiguous locations."""

    # --- Pixels that MUST be in cast shadow (value == 1) ---

    def test_shadow_north_of_escarpment(self, shadow_arr):
        """Row 76, col 80: flat terrain north of escarpment, within shadow zone."""
        assert shadow_arr[76, 80] == 1

    def test_shadow_on_ramp_mid(self, shadow_arr):
        """Row 85, col 80: mid-ramp pixel cast-shadowed by higher ramp."""
        assert shadow_arr[85, 80] == 1

    def test_shadow_on_ramp_lower(self, shadow_arr):
        """Row 90, col 60: lower-ramp pixel cast-shadowed by upper ramp."""
        assert shadow_arr[90, 60] == 1

    def test_shadow_north_of_hill(self, shadow_arr):
        """Row 132, col 140: in cast shadow from Gaussian hill shoulder."""
        assert shadow_arr[132, 140] == 1

    # --- Pixels that MUST NOT be in cast shadow (value == 0) ---

    def test_lit_far_north(self, shadow_arr):
        """Row 50, col 80: well north, ray clears the escarpment."""
        assert shadow_arr[50, 80] == 0

    def test_lit_outside_shadow_zone(self, shadow_arr):
        """Row 65, col 80: north of escarpment but outside shadow reach."""
        assert shadow_arr[65, 80] == 0

    def test_lit_plateau(self, shadow_arr):
        """Row 120, col 80: flat plateau south of escarpment."""
        assert shadow_arr[120, 80] == 0

    def test_lit_hill_summit(self, shadow_arr):
        """Row 150, col 140: summit of Gaussian hill — nothing blocks."""
        assert shadow_arr[150, 140] == 0

    def test_lit_far_south(self, shadow_arr):
        """Row 180, col 100: flat plateau, no obstructions to SSW."""
        assert shadow_arr[180, 100] == 0

    # --- Nodata ---

    def test_nodata_preserved(self, shadow_arr):
        """Nodata pixel (row 42, col 110) must be marked 255."""
        assert shadow_arr[42, 110] == 255


# ---------------------------------------------------------------------------
# Illumination pixel accuracy
# ---------------------------------------------------------------------------

class TestIlluminationValues:
    def test_flat_plateau(self, illum_arr):
        """Flat terrain illumination should be ~ sin(18deg) ~ 0.309."""
        val = float(illum_arr[120, 80])
        assert abs(val - 0.309) < 0.05, f"Got {val}, expected ~0.309"

    def test_hill_summit(self, illum_arr):
        """Hill summit is essentially flat -> illumination ~ 0.309."""
        val = float(illum_arr[150, 140])
        assert abs(val - 0.309) < 0.05, f"Got {val}, expected ~0.309"

    def test_shadowed_zero(self, illum_arr):
        """Cast-shadowed pixel must have illumination = 0."""
        assert abs(float(illum_arr[76, 80])) < 0.01

    def test_ramp_shadowed_zero(self, illum_arr):
        """Ramp pixel in cast shadow -> illumination = 0."""
        assert abs(float(illum_arr[90, 60])) < 0.01

    def test_south_facing_slope(self, illum_arr):
        """South-facing hill slope gets higher illumination than flat."""
        val = float(illum_arr[155, 140])
        assert val > 0.35, f"South-facing slope illumination {val} too low"

    def test_valid_range(self, illum_arr):
        """All valid (non-NaN) illumination values must be in [0, 1]."""
        valid = illum_arr[~np.isnan(illum_arr)]
        assert np.all(valid >= -0.001) and np.all(valid <= 1.001)

    def test_nodata_illumination(self, illum_arr):
        """Nodata pixel should carry NaN, not an illumination value."""
        assert np.isnan(illum_arr[42, 110]), (
            f"Nodata pixel has illumination {illum_arr[42, 110]}; expected NaN"
        )


# ---------------------------------------------------------------------------
# analysis.json
# ---------------------------------------------------------------------------

class TestAnalysisJSON:
    def test_required_keys(self, analysis):
        for key in ("cast_shadow_fraction", "mean_illumination",
                     "shadow_area_sq_m", "max_slope_degrees"):
            assert key in analysis, f"Missing key: {key}"

    def test_cast_shadow_fraction(self, analysis):
        v = analysis["cast_shadow_fraction"]
        assert 0.08 < v < 0.25, f"cast_shadow_fraction={v} outside (0.08, 0.25)"

    def test_mean_illumination(self, analysis):
        v = analysis["mean_illumination"]
        assert 0.15 < v < 0.32, f"mean_illumination={v} outside (0.15, 0.32)"

    def test_shadow_area(self, analysis):
        v = analysis["shadow_area_sq_m"]
        assert 2_500_000 < v < 8_000_000, (
            f"shadow_area_sq_m={v} outside (2.5M, 8M)"
        )

    def test_max_slope(self, analysis):
        v = analysis["max_slope_degrees"]
        assert 24 < v < 32, f"max_slope_degrees={v} outside (24, 32)"
