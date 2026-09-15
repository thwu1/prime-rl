
"""
Verification tests for calibration phantom quality assessment.

Independently recomputes expected marker positions from known distortion
coefficients and verifies the agent's calibration report matches.
"""

import json
import math
import os
import struct

import numpy as np
import pytest


# --------------------------------------------------------------------------
# True distortion coefficients (same as used during phantom generation).
# Terms in order: [x^2, y^2, z^2, xy, xz, yz]
# --------------------------------------------------------------------------
TRUE_COEFFS = {
    "x": [1.5e-3, -0.75e-3, 1.0e-3, -1.25e-3, 0.5e-3, -0.25e-3],
    "y": [-0.5e-3, 1.0e-3, -0.75e-3, 0.75e-3, -0.5e-3, 1.0e-3],
    "z": [0.25e-3, -0.5e-3, 1.5e-3, 0.5e-3, -0.75e-3, 0.25e-3],
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def compute_ideal_positions(spec):
    """Generate ideal grid positions and grid IDs from spec."""
    grid = spec["grid"]
    positions = []
    ids = []
    for i in range(grid["layout"][0]):
        for j in range(grid["layout"][1]):
            for k in range(grid["layout"][2]):
                positions.append([
                    grid["origin_mm"][0] + i * grid["spacing_mm"][0],
                    grid["origin_mm"][1] + j * grid["spacing_mm"][1],
                    grid["origin_mm"][2] + k * grid["spacing_mm"][2],
                ])
                ids.append([i, j, k])
    return np.array(positions), ids


def apply_distortion(positions, coeffs):
    """Apply 2nd-order polynomial distortion to positions."""
    x, y, z = positions[:, 0], positions[:, 1], positions[:, 2]
    quad = np.column_stack([x**2, y**2, z**2, x * y, x * z, y * z])
    result = positions.copy()
    for axis, key in enumerate(["x", "y", "z"]):
        result[:, axis] += quad @ np.array(coeffs[key])
    return result


def read_mha_voxels(filepath):
    """Read a MetaImage (.mha) file and return (array, header_dict).

    Parses the text header and reads the raw float32 binary payload.
    Does NOT require ITK.
    """
    header = {}
    with open(filepath, "rb") as f:
        while True:
            line = f.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            if "=" in text:
                k, v = text.split("=", 1)
                header[k.strip()] = v.strip()
            if "ElementDataFile" in text:
                break
        raw = f.read()

    size = list(map(int, header["DimSize"].split()))
    arr = np.frombuffer(raw, dtype=np.float32).reshape(size[2], size[1], size[0])
    return arr, header


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def spec():
    with open("/app/calibration_spec.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def report():
    path = "/app/calibration_report.json"
    assert os.path.isfile(path), "calibration_report.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ground_truth(spec):
    ideal, ids = compute_ideal_positions(spec)
    distorted = apply_distortion(ideal, TRUE_COEFFS)
    displacements = distorted - ideal
    magnitudes = np.linalg.norm(displacements, axis=1)
    return {
        "ideal": ideal,
        "ids": ids,
        "distorted": distorted,
        "displacements": displacements,
        "magnitudes": magnitudes,
        "max_mm": float(magnitudes.max()),
        "mean_mm": float(magnitudes.mean()),
        "rms_mm": float(np.sqrt((magnitudes**2).mean())),
    }


# --------------------------------------------------------------------------
# Test: report structure
# --------------------------------------------------------------------------

class TestReportStructure:
    def test_report_exists(self):
        assert os.path.isfile("/app/calibration_report.json")

    def test_required_top_level_fields(self, report):
        for key in ("detected_markers", "num_detected", "geometric_errors",
                     "distortion_model", "snr_db", "quality_assessment"):
            assert key in report, f"Missing top-level field: {key}"

    def test_marker_fields(self, report):
        for m in report["detected_markers"]:
            for key in ("grid_id", "ideal_position_mm", "detected_position_mm",
                        "displacement_mm", "displacement_magnitude_mm"):
                assert key in m, f"Missing marker field: {key}"

    def test_distortion_model_fields(self, report):
        dm = report["distortion_model"]
        for key in ("coefficients_x", "coefficients_y", "coefficients_z",
                     "fit_residual_rms_mm"):
            assert key in dm, f"Missing distortion_model field: {key}"

    def test_quality_assessment_fields(self, report):
        qa = report["quality_assessment"]
        for key in ("detection_pass", "geometric_pass", "snr_pass", "overall"):
            assert key in qa, f"Missing quality_assessment field: {key}"


# --------------------------------------------------------------------------
# Test: marker detection
# --------------------------------------------------------------------------

class TestDetection:
    def test_all_markers_detected(self, report):
        assert report["num_detected"] == 48, (
            f"Expected 48 markers, got {report['num_detected']}"
        )

    def test_marker_count_matches_list(self, report):
        assert len(report["detected_markers"]) == report["num_detected"]

    def test_unique_grid_ids(self, report):
        ids = [tuple(m["grid_id"]) for m in report["detected_markers"]]
        assert len(set(ids)) == len(ids), f"Duplicate grid IDs detected: {ids}"

    def test_all_grid_ids_present(self, report, spec):
        grid = spec["grid"]
        expected_ids = set()
        for i in range(grid["layout"][0]):
            for j in range(grid["layout"][1]):
                for k in range(grid["layout"][2]):
                    expected_ids.add((i, j, k))
        actual_ids = {tuple(m["grid_id"]) for m in report["detected_markers"]}
        missing = expected_ids - actual_ids
        assert not missing, f"Missing grid IDs: {missing}"


# --------------------------------------------------------------------------
# Test: detected position accuracy (also anti-cheat)
# --------------------------------------------------------------------------

class TestPositionAccuracy:
    def test_detected_positions_close_to_truth(self, report, ground_truth):
        """Each detected position must be within 1mm of true distorted position."""
        det_map = {
            tuple(m["grid_id"]): np.array(m["detected_position_mm"])
            for m in report["detected_markers"]
        }
        for idx, gid in enumerate(ground_truth["ids"]):
            key = tuple(gid)
            if key not in det_map:
                pytest.fail(f"Grid position {gid} not found in report")
            actual = det_map[key]
            expected = ground_truth["distorted"][idx]
            dist = np.linalg.norm(actual - expected)
            assert dist < 1.0, (
                f"Marker {gid}: detected at {actual.tolist()}, "
                f"expected near {expected.tolist()}, error {dist:.3f}mm > 1.0mm"
            )

    def test_displacements_consistent(self, report):
        """displacement_mm should equal detected minus ideal."""
        for m in report["detected_markers"]:
            detected = np.array(m["detected_position_mm"])
            ideal = np.array(m["ideal_position_mm"])
            displacement = np.array(m["displacement_mm"])
            np.testing.assert_allclose(
                displacement, detected - ideal, atol=1e-6,
                err_msg=f"Marker {m['grid_id']}: displacement inconsistent"
            )

    def test_magnitude_consistent(self, report):
        """displacement_magnitude_mm should be L2 norm of displacement_mm."""
        for m in report["detected_markers"]:
            displacement = np.array(m["displacement_mm"])
            expected_mag = float(np.linalg.norm(displacement))
            assert abs(m["displacement_magnitude_mm"] - expected_mag) < 1e-6, (
                f"Marker {m['grid_id']}: magnitude inconsistent"
            )


# --------------------------------------------------------------------------
# Test: image consistency (anti-cheat — centroids must be at bright voxels)
# --------------------------------------------------------------------------

class TestImageConsistency:
    def test_centroids_at_bright_voxels(self, report, spec):
        """Verify reported centroids correspond to bright regions in the
        actual phantom image. Cannot be faked without reading the image."""
        arr, header = read_mha_voxels("/app/phantom.mha")
        spacing = list(map(float, header["ElementSpacing"].split()))
        origin = list(map(float, header["Offset"].split()))
        size = list(map(int, header["DimSize"].split()))

        bg = spec["grid"]["background_intensity"]
        marker = spec["grid"]["marker_intensity"]
        threshold = (bg + marker) / 2.0

        for m in report["detected_markers"]:
            pos = m["detected_position_mm"]
            vi = int(round((pos[0] - origin[0]) / spacing[0]))
            vj = int(round((pos[1] - origin[1]) / spacing[1]))
            vk = int(round((pos[2] - origin[2]) / spacing[2]))

            assert 0 <= vi < size[0] and 0 <= vj < size[1] and 0 <= vk < size[2], (
                f"Marker {m['grid_id']} centroid at {pos} is outside image bounds"
            )

            # Check 3x3x3 neighbourhood mean intensity
            k0, k1 = max(0, vk - 1), min(size[2], vk + 2)
            j0, j1 = max(0, vj - 1), min(size[1], vj + 2)
            i0, i1 = max(0, vi - 1), min(size[0], vi + 2)
            region = arr[k0:k1, j0:j1, i0:i1]
            assert region.mean() > threshold, (
                f"Marker {m['grid_id']} centroid at {pos} has neighbourhood mean "
                f"{region.mean():.1f}, expected > {threshold}"
            )


# --------------------------------------------------------------------------
# Test: geometric error statistics
# --------------------------------------------------------------------------

class TestGeometricErrors:
    def test_max_error(self, report, ground_truth):
        assert abs(report["geometric_errors"]["max_mm"] - ground_truth["max_mm"]) < 0.3, (
            f"max_mm: got {report['geometric_errors']['max_mm']:.3f}, "
            f"expected ~{ground_truth['max_mm']:.3f}"
        )

    def test_mean_error(self, report, ground_truth):
        assert abs(report["geometric_errors"]["mean_mm"] - ground_truth["mean_mm"]) < 0.2, (
            f"mean_mm: got {report['geometric_errors']['mean_mm']:.3f}, "
            f"expected ~{ground_truth['mean_mm']:.3f}"
        )

    def test_rms_error(self, report, ground_truth):
        assert abs(report["geometric_errors"]["rms_mm"] - ground_truth["rms_mm"]) < 0.2, (
            f"rms_mm: got {report['geometric_errors']['rms_mm']:.3f}, "
            f"expected ~{ground_truth['rms_mm']:.3f}"
        )


# --------------------------------------------------------------------------
# Test: polynomial distortion model
# --------------------------------------------------------------------------

class TestDistortionModel:
    def test_coefficients_x(self, report):
        actual = report["distortion_model"]["coefficients_x"]
        assert len(actual) == 6, f"Expected 6 x-coefficients, got {len(actual)}"
        np.testing.assert_allclose(
            actual, TRUE_COEFFS["x"], atol=5e-4,
            err_msg="X distortion coefficients do not match",
        )

    def test_coefficients_y(self, report):
        actual = report["distortion_model"]["coefficients_y"]
        assert len(actual) == 6, f"Expected 6 y-coefficients, got {len(actual)}"
        np.testing.assert_allclose(
            actual, TRUE_COEFFS["y"], atol=5e-4,
            err_msg="Y distortion coefficients do not match",
        )

    def test_coefficients_z(self, report):
        actual = report["distortion_model"]["coefficients_z"]
        assert len(actual) == 6, f"Expected 6 z-coefficients, got {len(actual)}"
        np.testing.assert_allclose(
            actual, TRUE_COEFFS["z"], atol=5e-4,
            err_msg="Z distortion coefficients do not match",
        )

    def test_fit_residual_small(self, report):
        rms = report["distortion_model"]["fit_residual_rms_mm"]
        assert rms < 0.5, f"Fit residual RMS {rms:.4f}mm exceeds 0.5mm"

    def test_no_nan_in_coefficients(self, report):
        dm = report["distortion_model"]
        for key in ("coefficients_x", "coefficients_y", "coefficients_z"):
            for val in dm[key]:
                assert not math.isnan(val) and not math.isinf(val), (
                    f"NaN/Inf in {key}: {dm[key]}"
                )


# --------------------------------------------------------------------------
# Test: SNR
# --------------------------------------------------------------------------

class TestSNR:
    def test_snr_in_expected_range(self, report):
        """SNR should be ~27 dB given marker=250, bg=30, noise_sigma=10."""
        snr = report["snr_db"]
        assert 20.0 < snr < 35.0, f"SNR {snr:.1f} dB outside expected 20-35 range"

    def test_snr_above_threshold(self, report, spec):
        threshold = spec["quality_criteria"]["min_snr_db"]
        assert report["snr_db"] >= threshold, (
            f"SNR {report['snr_db']:.1f} dB below threshold {threshold}"
        )

    def test_snr_not_nan(self, report):
        assert not math.isnan(report["snr_db"]) and not math.isinf(report["snr_db"])


# --------------------------------------------------------------------------
# Test: quality assessment
# --------------------------------------------------------------------------

class TestQualityAssessment:
    def test_overall_pass(self, report):
        assert report["quality_assessment"]["overall"] == "PASS", (
            f"Expected PASS, got {report['quality_assessment']['overall']}"
        )

    def test_detection_pass(self, report):
        assert report["quality_assessment"]["detection_pass"] is True

    def test_geometric_pass(self, report):
        assert report["quality_assessment"]["geometric_pass"] is True

    def test_snr_pass(self, report):
        assert report["quality_assessment"]["snr_pass"] is True

    def test_overall_consistent(self, report):
        """Overall should be PASS iff all sub-criteria pass."""
        qa = report["quality_assessment"]
        all_pass = qa["detection_pass"] and qa["geometric_pass"] and qa["snr_pass"]
        expected = "PASS" if all_pass else "FAIL"
        assert qa["overall"] == expected, (
            f"overall='{qa['overall']}' inconsistent with sub-criteria "
            f"(detection={qa['detection_pass']}, geometric={qa['geometric_pass']}, "
            f"snr={qa['snr_pass']})"
        )
