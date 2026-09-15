
"""
Validation tests for the 3D phantom volume analysis pipeline.

Verifies that /app/report.json contains correct physical-space measurements
for the synthetic phantom structures, including proper handling of anisotropic
spacing, non-zero origin, and rotated direction cosine matrix.
"""

import json
import os

import numpy as np
import pytest

# ── Ground truth phantom parameters ──────────────────────────────────────────
# These match generate_phantom.py exactly.

SPACING = (0.5, 0.5, 1.2)       # (sx, sy, sz) in mm
ORIGIN = (10.0, -5.0, 20.0)     # (ox, oy, oz) in mm
THETA = np.radians(20)           # 20-degree rotation about z

# Direction cosine matrix as used by SimpleITK.
# GetDirection() returns (cos, sin, 0, -sin, cos, 0, 0, 0, 1) in row-major.
# Physical coords: world = origin + DIRECTION @ diag(spacing) @ voxel_index
DIRECTION = np.array([
    [np.cos(THETA),  np.sin(THETA), 0.0],
    [-np.sin(THETA), np.cos(THETA), 0.0],
    [0.0,            0.0,           1.0],
])

# Structure definitions: (cx, cy, cz, rx, ry, rz, intensity) in voxel coords
STRUCTURES = [
    (30, 30, 20, 12, 10, 6, 180),
    (95, 30, 55, 10,  8, 5, 200),
    (30, 95, 50,  8,  7, 5, 190),
    (95, 95, 25,  9,  8, 4, 210),
    (60, 60, 65,  7,  7, 4, 215),
    (60, 30, 40,  8,  6, 5, 195),
]

NUM_STRUCTURES = len(STRUCTURES)


def _world_centroid(cx, cy, cz):
    """Convert voxel center to world coordinates using full affine transform.

    world = origin + direction_matrix @ (diag(spacing) @ index)
    This matches SimpleITK's TransformIndexToPhysicalPoint.
    """
    scaled = np.array([cx * SPACING[0], cy * SPACING[1], cz * SPACING[2]])
    return (np.array(ORIGIN) + DIRECTION @ scaled).tolist()


def _ellipsoid_volume(rx, ry, rz):
    """Theoretical volume of an ellipsoid with given voxel radii, in mm³."""
    return (4.0 / 3.0) * np.pi * (rx * SPACING[0]) * (ry * SPACING[1]) * (rz * SPACING[2])


# Pre-compute expected values sorted by descending volume
EXPECTED = sorted(
    [
        {
            "centroid": _world_centroid(cx, cy, cz),
            "volume": _ellipsoid_volume(rx, ry, rz),
            "intensity": intensity,
        }
        for cx, cy, cz, rx, ry, rz, intensity in STRUCTURES
    ],
    key=lambda e: -e["volume"],
)

# ── Tolerances ───────────────────────────────────────────────────────────────
VOL_REL_TOL = 0.25       # 25 % relative tolerance on volume
CENTROID_TOL_MM = 3.0     # 3 mm absolute tolerance on centroid position
INTENSITY_ABS_TOL = 25.0  # absolute tolerance on mean intensity
SPHERICITY_LO = 0.2
SPHERICITY_HI = 1.25      # discretized ellipsoids commonly yield sphericity slightly >1
MATCH_MAX_MM = 12.0       # max distance to consider a centroid match


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_report():
    path = "/app/report.json"
    assert os.path.isfile(path), f"Report file not found at {path}"
    with open(path, "r") as f:
        return json.load(f)


def match_structures(detected, expected):
    """Greedily match detected structures to expected by centroid proximity.

    Returns list of (detected_dict, expected_dict) pairs.
    Asserts every detected structure matches within MATCH_MAX_MM.
    """
    matched = []
    used = set()

    for det in detected:
        best_idx = None
        best_dist = float("inf")
        for i, exp in enumerate(expected):
            if i in used:
                continue
            dist = float(np.linalg.norm(
                np.array(det["centroid_mm"]) - np.array(exp["centroid"])
            ))
            if dist < best_dist:
                best_dist = dist
                best_idx = i

        assert best_idx is not None and best_dist < MATCH_MAX_MM, (
            f"No expected structure within {MATCH_MAX_MM} mm of detected centroid "
            f"{det['centroid_mm']} (nearest: {best_dist:.1f} mm). "
            f"Verify direction-cosine / origin handling."
        )
        matched.append((det, expected[best_idx]))
        used.add(best_idx)

    return matched


# ── Tests ────────────────────────────────────────────────────────────────────

class TestReportFormat:
    """Validate report structure and formatting."""

    def test_report_exists_and_valid_json(self):
        report = load_report()
        assert isinstance(report, dict)

    def test_has_required_top_level_keys(self):
        report = load_report()
        assert "num_structures" in report, "Missing 'num_structures' key"
        assert "structures" in report, "Missing 'structures' key"
        assert isinstance(report["structures"], list)

    def test_required_fields_present(self):
        report = load_report()
        required = {"label", "volume_mm3", "centroid_mm", "mean_intensity", "sphericity"}
        for i, s in enumerate(report["structures"]):
            missing = required - set(s.keys())
            assert not missing, f"Structure {i} missing fields: {missing}"
            assert isinstance(s["centroid_mm"], list) and len(s["centroid_mm"]) == 3, (
                f"Structure {i}: centroid_mm must be a list of 3 floats"
            )


class TestStructureCount:
    """Validate that all structures are detected."""

    def test_num_structures_field(self):
        report = load_report()
        assert report["num_structures"] == NUM_STRUCTURES, (
            f"Expected {NUM_STRUCTURES} structures, got {report['num_structures']}"
        )

    def test_structures_list_length(self):
        report = load_report()
        assert len(report["structures"]) == NUM_STRUCTURES, (
            f"Expected {NUM_STRUCTURES} entries in structures list, "
            f"got {len(report['structures'])}"
        )


class TestSortOrder:
    """Validate descending volume sort."""

    def test_sorted_by_descending_volume(self):
        report = load_report()
        volumes = [s["volume_mm3"] for s in report["structures"]]
        for i in range(len(volumes) - 1):
            assert volumes[i] >= volumes[i + 1], (
                f"Structures not sorted by descending volume: "
                f"index {i} ({volumes[i]:.1f}) < index {i+1} ({volumes[i+1]:.1f})"
            )


class TestPhysicalMeasurements:
    """Validate physical-space measurements against ground truth."""

    def test_volume_accuracy(self):
        """Physical volumes must be within 25% of theoretical ellipsoid volumes."""
        report = load_report()
        matched = match_structures(report["structures"], EXPECTED)
        for det, exp in matched:
            rel_err = abs(det["volume_mm3"] - exp["volume"]) / exp["volume"]
            assert rel_err < VOL_REL_TOL, (
                f"Volume {det['volume_mm3']:.1f} mm³ vs expected {exp['volume']:.1f} mm³ "
                f"(relative error {rel_err:.1%} exceeds {VOL_REL_TOL:.0%})"
            )

    def test_centroid_world_coordinates(self):
        """Centroids must be correct in world coordinates (direction cosines!)."""
        report = load_report()
        matched = match_structures(report["structures"], EXPECTED)
        for det, exp in matched:
            dist = float(np.linalg.norm(
                np.array(det["centroid_mm"]) - np.array(exp["centroid"])
            ))
            assert dist < CENTROID_TOL_MM, (
                f"Centroid {det['centroid_mm']} is {dist:.2f} mm from expected "
                f"{[round(c, 2) for c in exp['centroid']]} "
                f"(tolerance: {CENTROID_TOL_MM} mm). "
                f"Check direction cosine matrix handling."
            )

    def test_mean_intensity(self):
        """Mean intensity must be close to the structure's nominal intensity."""
        report = load_report()
        matched = match_structures(report["structures"], EXPECTED)
        for det, exp in matched:
            assert abs(det["mean_intensity"] - exp["intensity"]) < INTENSITY_ABS_TOL, (
                f"Mean intensity {det['mean_intensity']:.1f} too far from "
                f"expected ~{exp['intensity']} (tolerance: ±{INTENSITY_ABS_TOL})"
            )

    def test_sphericity_range(self):
        """Sphericity must be in valid range for convex ellipsoidal structures."""
        report = load_report()
        for s in report["structures"]:
            assert SPHERICITY_LO < s["sphericity"] <= SPHERICITY_HI, (
                f"Sphericity {s['sphericity']:.3f} outside expected range "
                f"({SPHERICITY_LO}, {SPHERICITY_HI}]"
            )
