
"""
Verification tests for the gyroid module construction task.

Tests check the output result.json against the target specification:
topological invariants, geometric ranges, and internal consistency.
"""

import json
import os
import pytest


RESULT_PATH = "/app/result.json"
TARGET_PATH = "/app/target.json"


@pytest.fixture
def result():
    """Load and return the result JSON produced by the agent's script."""
    assert os.path.isfile(RESULT_PATH), (
        f"Expected output file {RESULT_PATH} does not exist. "
        "Did build.py run successfully?"
    )
    with open(RESULT_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture
def target():
    """Load and return the target specification."""
    with open(TARGET_PATH) as f:
        data = json.load(f)
    return data


REQUIRED_KEYS = [
    "genus", "volume", "surface_area",
    "num_vert", "num_tri", "num_components", "is_valid",
]


class TestResultSchema:
    """Verify the output JSON has the correct structure."""

    def test_all_keys_present(self, result):
        for key in REQUIRED_KEYS:
            assert key in result, f"Missing key: {key}"

    def test_numeric_types(self, result):
        for key in ["genus", "volume", "surface_area", "num_vert", "num_tri",
                     "num_components"]:
            assert isinstance(result[key], (int, float)), (
                f"{key} must be numeric, got {type(result[key])}"
            )

    def test_is_valid_boolean(self, result):
        assert isinstance(result["is_valid"], bool), (
            f"is_valid must be boolean, got {type(result['is_valid'])}"
        )


class TestTopology:
    """Verify topological invariants of the constructed solid."""

    def test_genus(self, result, target):
        """The gyroid module must have the correct genus."""
        expected = target["genus"]
        assert result["genus"] == expected, (
            f"Expected genus {expected}, got {result['genus']}"
        )

    def test_single_component(self, result, target):
        """The solid must be a single connected component."""
        expected = target["num_components"]
        assert result["num_components"] == expected, (
            f"Expected {expected} component(s), got {result['num_components']}"
        )

    def test_manifold_valid(self, result):
        """The constructed solid must be a valid manifold."""
        assert result["is_valid"] is True, (
            "Manifold status indicates an error"
        )


class TestGeometry:
    """Verify geometric measurements are in expected ranges."""

    def test_volume_range(self, result, target):
        vol = result["volume"]
        lo, hi = target["volume_range"]
        assert lo < vol < hi, (
            f"Volume {vol} is outside expected range ({lo}, {hi})"
        )

    def test_surface_area_range(self, result, target):
        sa = result["surface_area"]
        lo, hi = target["surface_area_range"]
        assert lo < sa < hi, (
            f"Surface area {sa} is outside expected range ({lo}, {hi})"
        )

    def test_vertex_count(self, result, target):
        nv = result["num_vert"]
        nv_min = target["num_vert_min"]
        assert nv >= nv_min, (
            f"num_vert {nv} is below minimum {nv_min}"
        )

    def test_triangle_count(self, result, target):
        nt = result["num_tri"]
        nt_min = target["num_tri_min"]
        assert nt >= nt_min, (
            f"num_tri {nt} is below minimum {nt_min}"
        )


class TestConsistency:
    """Verify internal consistency of reported mesh properties."""

    def test_euler_characteristic(self, result):
        """
        For a closed orientable 2-manifold triangle mesh:
          chi = V - E + F, with E = 3F/2 (each triangle has 3 edges, shared by 2 faces)
          => chi = V - F/2 => 2V - F = 4 - 4g

        This catches hardcoded/inconsistent values.
        """
        V = result["num_vert"]
        F = result["num_tri"]
        g = result["genus"]
        euler_mesh = 2 * V - F
        euler_expected = 4 - 4 * g
        assert abs(euler_mesh - euler_expected) <= 8, (
            f"Euler characteristic inconsistency: 2*{V} - {F} = {euler_mesh}, "
            f"expected 4 - 4*{g} = {euler_expected} (tolerance 8 for degenerate tris)"
        )
