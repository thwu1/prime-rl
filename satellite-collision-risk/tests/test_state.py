"""
Verification tests for the conjunction risk analysis tool.
Tests collision probability computation against validated reference values
and verifies CDM parsing, risk classification, and batch processing.

"""

import json
import os
import subprocess
import math
import pytest
import tempfile


JAR_PATH = "/app/target/conjanalysis-1.0.jar"


def run_direct(xm, ym, sigma_x, sigma_y, radius):
    """Run tool in direct mode and return parsed JSON."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out_path = f.name
    try:
        result = subprocess.run(
            ["java", "-jar", JAR_PATH,
             "direct", str(xm), str(ym), str(sigma_x), str(sigma_y),
             str(radius), out_path],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"Direct mode failed (rc={result.returncode}):\n{result.stderr}"
        with open(out_path) as f:
            return json.load(f)
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


def run_cdm(cdm_file, combined_hbr):
    """Run tool in CDM mode and return parsed JSON."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out_path = f.name
    try:
        result = subprocess.run(
            ["java", "-jar", JAR_PATH,
             "cdm", cdm_file, str(combined_hbr), out_path],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"CDM mode failed (rc={result.returncode}):\n{result.stderr}"
        with open(out_path) as f:
            return json.load(f)
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


def assert_pc(actual, expected, rel_tol=1e-3):
    """Assert collision probability matches within relative tolerance."""
    abs_tol = max(abs(expected) * rel_tol, abs(expected) * 1e-3)
    assert abs(actual - expected) < abs_tol, \
        f"Pc={actual:.6e} expected {expected:.3e} (rel_err={abs(actual - expected) / max(abs(expected), 1e-300):.2e})"


# ======================================================================
# Build verification
# ======================================================================

class TestBuild:
    """Verify Maven build produced a working JAR."""

    def test_jar_exists(self):
        assert os.path.exists(JAR_PATH), f"JAR not found at {JAR_PATH}"

    def test_jar_runs_with_usage(self):
        result = subprocess.run(
            ["java", "-jar", JAR_PATH],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 1
        assert "usage" in result.stderr.lower() or "Usage" in result.stderr


# ======================================================================
# Reference test cases — validated collision probability values
# ======================================================================

class TestReferenceDirect01:
    """Reference cases with moderate miss distance and covariance."""

    def test_ref_01(self):
        data = run_direct(0, 10, 25, 50, 5)
        assert_pc(data["collision_probability"], 9.741e-3)

    def test_ref_02(self):
        data = run_direct(10, 0, 25, 50, 5)
        assert_pc(data["collision_probability"], 9.181e-3)

    def test_ref_03(self):
        data = run_direct(0, 10, 25, 75, 5)
        assert_pc(data["collision_probability"], 6.571e-3)

    def test_ref_04(self):
        data = run_direct(10, 0, 25, 75, 5)
        assert_pc(data["collision_probability"], 6.125e-3)


class TestReferenceDirect02:
    """Reference cases with larger separations."""

    def test_ref_05(self):
        data = run_direct(0, 1000, 1000, 3000, 10)
        assert_pc(data["collision_probability"], 1.577e-5)

    def test_ref_06(self):
        data = run_direct(1000, 0, 1000, 3000, 10)
        assert_pc(data["collision_probability"], 1.011e-5)

    def test_ref_07(self):
        data = run_direct(0, 10000, 1000, 3000, 10)
        assert_pc(data["collision_probability"], 6.443e-8, rel_tol=5e-3)

    def test_ref_08(self):
        """Extreme: very small probability ~1e-27."""
        data = run_direct(10000, 0, 1000, 3000, 10)
        assert_pc(data["collision_probability"], 3.219e-27, rel_tol=5e-3)

    def test_ref_09(self):
        data = run_direct(0, 10000, 1000, 10000, 10)
        assert_pc(data["collision_probability"], 3.033e-6)

    def test_ref_10(self):
        """Extreme: very small probability ~1e-28."""
        data = run_direct(10000, 0, 1000, 10000, 10)
        assert_pc(data["collision_probability"], 9.656e-28, rel_tol=5e-3)

    def test_ref_11(self):
        data = run_direct(0, 5000, 1000, 3000, 50)
        assert_pc(data["collision_probability"], 1.039e-4)

    def test_ref_12(self):
        data = run_direct(5000, 0, 1000, 3000, 50)
        assert_pc(data["collision_probability"], 1.564e-9)


class TestReferenceDirect03:
    """Reference cases with non-axis-aligned miss vectors."""

    def test_ref_13(self):
        data = run_direct(84.875546, 60.583685, 57.918666, 152.8814468, 10.3)
        assert_pc(data["collision_probability"], 1.9002e-3)

    def test_ref_14(self):
        data = run_direct(-81.618369, 115.055899, 15.988242, 5756.840725, 1.3)
        assert_pc(data["collision_probability"], 2.0553e-11)

    def test_ref_15(self):
        data = run_direct(102.177247, 693.405893, 94.230921, 643.409272, 5.3)
        assert_pc(data["collision_probability"], 7.2003e-5)


class TestReferenceDirect04:
    """Reference cases from real-world conjunction parameters."""

    def test_ref_16(self):
        data = run_direct(-752.672701, 644.939441, 445.859950, 6095.858688, 3.5)
        assert_pc(data["collision_probability"], 5.3904e-7)

    def test_ref_17(self):
        data = run_direct(-692.362272, 4475.456261, 193.454603, 562.027293, 13.2)
        assert_pc(data["collision_probability"], 2.2795e-20)


class TestReferenceDirect05:
    """Extreme covariance aspect ratio (~81:1)."""

    def test_ref_18(self):
        data = run_direct(-3.8872073, 0.1591646, 1.4101830, 114.2585190, 15)
        assert_pc(data["collision_probability"], 1.0038e-1)


# ======================================================================
# Risk level classification
# ======================================================================

class TestRiskLevel:
    """Verify correct risk level classification."""

    def test_high_risk(self):
        data = run_direct(0, 10, 25, 50, 5)
        assert data["risk_level"] == "HIGH"

    def test_medium_risk(self):
        data = run_direct(0, 1000, 1000, 3000, 10)
        assert data["risk_level"] == "MEDIUM"

    def test_low_risk(self):
        data = run_direct(0, 10000, 1000, 3000, 10)
        assert data["risk_level"] == "LOW"


# ======================================================================
# JSON schema validation
# ======================================================================

class TestDirectJsonSchema:
    """Verify direct-mode JSON output structure."""

    def test_json_has_required_fields(self):
        data = run_direct(0, 10, 25, 50, 5)
        required = {"xm", "ym", "sigma_x", "sigma_y", "radius",
                     "collision_probability", "risk_level"}
        assert required.issubset(set(data.keys())), \
            f"Missing fields: {required - set(data.keys())}"

    def test_json_numeric_types(self):
        data = run_direct(0, 10, 25, 50, 5)
        assert isinstance(data["collision_probability"], float)
        assert isinstance(data["xm"], (int, float))
        assert isinstance(data["risk_level"], str)


# ======================================================================
# CDM file parsing and end-to-end pipeline
# ======================================================================

class TestCDMParsing:
    """Test CDM file parsing and end-to-end conjunction analysis."""

    def test_cdm_example1_parses(self):
        data = run_cdm("/app/data/CDMExample1.txt", 10.0)
        assert "collision_probability" in data
        assert "tca" in data
        assert "miss_distance_m" in data
        assert "object1_name" in data
        assert "object2_name" in data
        assert "relative_velocity_km_s" in data
        assert "risk_level" in data

    def test_cdm_example1_metadata(self):
        data = run_cdm("/app/data/CDMExample1.txt", 10.0)
        assert data["object1_name"] == "SATELLITE A"
        assert data["object2_name"] == "FENGYUN 1C DEB"
        assert abs(data["miss_distance_m"] - 715.0) < 0.1

    def test_cdm_example1_tca(self):
        data = run_cdm("/app/data/CDMExample1.txt", 10.0)
        assert "2010-03-13" in data["tca"]
        assert "22:37:52" in data["tca"]

    def test_cdm_example1_relative_velocity(self):
        """Verify relative velocity from CDM state vectors."""
        data = run_cdm("/app/data/CDMExample1.txt", 10.0)
        assert abs(data["relative_velocity_km_s"] - 14.762) < 0.05

    def test_cdm_example1_probability_physical(self):
        data = run_cdm("/app/data/CDMExample1.txt", 10.0)
        assert data["collision_probability"] > 0
        assert math.isfinite(data["collision_probability"])
        assert data["collision_probability"] < 1.0

    def test_cdm_example1_risk_level_valid(self):
        data = run_cdm("/app/data/CDMExample1.txt", 10.0)
        assert data["risk_level"] in ("HIGH", "MEDIUM", "LOW")

    def test_cdm_encounter_leo_parses(self):
        data = run_cdm("/app/data/encounter_leo.txt", 15.0)
        assert "collision_probability" in data
        assert data["collision_probability"] > 0
        assert math.isfinite(data["collision_probability"])

    def test_cdm_encounter_leo_metadata(self):
        data = run_cdm("/app/data/encounter_leo.txt", 15.0)
        assert data["object1_name"] == "ASTRA 1A"
        assert data["object2_name"] == "DEBRIS 1422"

    def test_cdm_hbr_sensitivity(self):
        """Larger hard-body radius must produce higher collision probability."""
        data_small = run_cdm("/app/data/encounter_leo.txt", 5.0)
        data_large = run_cdm("/app/data/encounter_leo.txt", 50.0)
        assert data_large["collision_probability"] > data_small["collision_probability"]


# ======================================================================
# Numerical edge cases and robustness
# ======================================================================

class TestNumericalEdgeCases:
    """Test numerical robustness across extreme parameter ranges."""

    def test_anisotropic_miss_direction(self):
        """Different miss axes with anisotropic covariance give different Pc."""
        data_x = run_direct(10, 0, 25, 50, 5)
        data_y = run_direct(0, 10, 25, 50, 5)
        assert data_x["collision_probability"] != data_y["collision_probability"]

    def test_zero_miss_distance(self):
        """Head-on: Pc at origin > Pc with offset."""
        data = run_direct(0, 0, 25, 50, 5)
        data_offset = run_direct(0, 10, 25, 50, 5)
        assert data["collision_probability"] > data_offset["collision_probability"]

    def test_very_large_miss(self):
        """Very large miss distance gives near-zero probability."""
        data = run_direct(100000, 0, 100, 100, 5)
        assert data["collision_probability"] < 1e-50

    def test_extreme_covariance_ratio(self):
        """Covariance ratio > 1000:1."""
        data = run_direct(-3.8872073, 0.1591646, 1.4101830, 114.2585190, 15)
        assert 0.09 < data["collision_probability"] < 0.12


# ======================================================================
# Batch processing
# ======================================================================

class TestBatchProcessing:
    """Test batch CDM processing via run.sh."""

    def test_batch_script_exists(self):
        assert os.path.isfile("/app/run.sh")
        assert os.access("/app/run.sh", os.X_OK)

    def test_batch_single_file(self):
        result = subprocess.run(
            ["bash", "/app/run.sh", "/app/data/CDMExample1.txt"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0
        assert "collision_probability" in result.stdout

    def test_batch_multiple_files(self):
        result = subprocess.run(
            ["bash", "/app/run.sh",
             "/app/data/CDMExample1.txt", "/app/data/encounter_leo.txt"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0
        assert result.stdout.count("collision_probability") == 2
