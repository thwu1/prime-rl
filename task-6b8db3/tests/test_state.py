"""
Tests for the rotation synchronization pipeline.

Verifies that recovered rotations, outlier detection, and comparison report
meet quality thresholds against known ground truth.

"""

import json
import math
import os

import numpy as np
import pytest

# ============================================================
# Ground truth (NOT present in the task environment)
# ============================================================

GROUND_TRUTH_ROTATIONS = {
    "0": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    "1": [
        [1.0, 0.0, 0.0],
        [0.0, 0.7071067812, -0.7071067812],
        [0.0, 0.7071067812, 0.7071067812],
    ],
    "2": [
        [0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0],
        [-1.0, 0.0, 0.0],
    ],
    "3": [
        [0.8660254038, -0.5, 0.0],
        [0.5, 0.8660254038, 0.0],
        [0.0, 0.0, 1.0],
    ],
    "4": [
        [0.75, 0.25, 0.6123724357],
        [0.25, 0.75, -0.6123724357],
        [-0.6123724357, 0.6123724357, 0.5],
    ],
    "5": [
        [-0.5, -0.6123724357, 0.6123724357],
        [0.6123724357, 0.25, 0.75],
        [-0.6123724357, 0.75, 0.25],
    ],
    "6": [
        [0.906307787, 0.0, 0.4226182617],
        [0.1093816549, 0.9659258263, -0.234569716],
        [-0.4082178937, 0.2588190451, 0.8754260981],
    ],
    "7": [
        [0.5613467622, -0.3232051687, 0.7618584065],
        [0.7618584065, 0.5613467622, -0.3232051687],
        [-0.3232051687, 0.7618584065, 0.5613467622],
    ],
    "8": [
        [1.0, 0.0, 0.0],
        [0.0, -0.8660254038, -0.5],
        [0.0, 0.5, -0.8660254038],
    ],
    "9": [
        [0.8830222216, -0.4545194777, 0.1169777784],
        [0.4545194777, 0.7660444431, -0.4545194777],
        [0.1169777784, 0.4545194777, 0.8830222216],
    ],
    "10": [
        [0.0616284167, -0.0616284167, 0.9961946981],
        [0.7071067812, 0.7071067812, 0.0],
        [-0.7044160264, 0.7044160264, 0.0871557427],
    ],
    "11": [
        [-0.1183501194, -0.9909258359, 0.0637121418],
        [0.5435857881, -0.1183501194, -0.8309679538],
        [0.8309679538, -0.0637121418, 0.5526599522],
    ],
}

GROUND_TRUTH_OUTLIERS = [[1, 9], [2, 5], [7, 8]]

MAX_GEODESIC_ERROR_DEG = 10.0
ANCHOR_NODES = ["0", "3"]


def _geodesic_angle_deg(R1, R2):
    """Compute geodesic angle in degrees between two 3x3 rotation matrices."""
    R1 = np.array(R1, dtype=np.float64)
    R2 = np.array(R2, dtype=np.float64)
    R12 = R1 @ R2.T
    trace = R12[0, 0] + R12[1, 1] + R12[2, 2]
    cos_angle = np.clip((trace - 1.0) / 2.0, -1.0, 1.0)
    return math.degrees(math.acos(cos_angle))


def _is_valid_so3(R, tol=1e-4):
    """Check if R is a valid SO(3) matrix (orthogonal, det=+1)."""
    R = np.array(R, dtype=np.float64)
    if R.shape != (3, 3):
        return False
    RtR = R.T @ R
    I = np.eye(3)
    if np.max(np.abs(RtR - I)) > tol:
        return False
    if abs(np.linalg.det(R) - 1.0) > tol:
        return False
    return True


# ============================================================
# Tests
# ============================================================


class TestOutputFilesExist:
    def test_rotations_file_exists(self):
        assert os.path.isfile("/app/output/rotations.json"), (
            "Missing /app/output/rotations.json"
        )

    def test_outliers_file_exists(self):
        assert os.path.isfile("/app/output/outliers.json"), (
            "Missing /app/output/outliers.json"
        )

    def test_report_file_exists(self):
        assert os.path.isfile("/app/output/report.json"), (
            "Missing /app/output/report.json"
        )


class TestRotationsValid:
    @pytest.fixture(autouse=True)
    def load_rotations(self):
        with open("/app/output/rotations.json") as f:
            self.rotations = json.load(f)

    def test_all_nodes_present(self):
        for i in range(12):
            assert str(i) in self.rotations, (
                f"Node {i} missing from rotations.json"
            )

    def test_all_valid_so3(self):
        for i in range(12):
            key = str(i)
            R = self.rotations[key]
            assert _is_valid_so3(R), (
                f"Node {i} rotation is not a valid SO(3) matrix. "
                f"det={np.linalg.det(np.array(R)):.6f}, "
                f"max(R^T R - I)={np.max(np.abs(np.array(R).T @ np.array(R) - np.eye(3))):.6f}"
            )

    def test_anchor_nodes_exact(self):
        for key in ANCHOR_NODES:
            R_out = np.array(self.rotations[key], dtype=np.float64)
            R_gt = np.array(GROUND_TRUTH_ROTATIONS[key], dtype=np.float64)
            assert np.allclose(R_out, R_gt, atol=1e-4), (
                f"Anchor node {key} does not match ground truth.\n"
                f"Got:\n{R_out}\nExpected:\n{R_gt}"
            )


class TestRotationsAccuracy:
    @pytest.fixture(autouse=True)
    def load_rotations(self):
        with open("/app/output/rotations.json") as f:
            self.rotations = json.load(f)

    def test_each_node_within_threshold(self):
        errors = {}
        for i in range(12):
            key = str(i)
            R_out = self.rotations[key]
            R_gt = GROUND_TRUTH_ROTATIONS[key]
            err = _geodesic_angle_deg(R_out, R_gt)
            errors[i] = err
            assert err < MAX_GEODESIC_ERROR_DEG, (
                f"Node {i} geodesic error = {err:.2f}° exceeds {MAX_GEODESIC_ERROR_DEG}° threshold. "
                f"All errors: {json.dumps({k: round(v, 2) for k, v in errors.items()})}"
            )

    def test_mean_error_reasonable(self):
        total = 0.0
        for i in range(12):
            key = str(i)
            total += _geodesic_angle_deg(self.rotations[key], GROUND_TRUTH_ROTATIONS[key])
        mean_err = total / 12
        assert mean_err < 5.0, (
            f"Mean geodesic error = {mean_err:.2f}° is too high (expected < 5°)"
        )


class TestOutlierDetection:
    @pytest.fixture(autouse=True)
    def load_outliers(self):
        with open("/app/output/outliers.json") as f:
            self.outliers = json.load(f)

    def test_outliers_is_list(self):
        assert isinstance(self.outliers, list), "outliers.json must be a JSON list"

    def test_outlier_format(self):
        for entry in self.outliers:
            assert isinstance(entry, list) and len(entry) == 2, (
                f"Each outlier must be [i, j], got {entry}"
            )

    def test_true_outliers_detected(self):
        detected = set()
        for entry in self.outliers:
            pair = tuple(sorted(entry))
            detected.add(pair)
        gt_set = set(tuple(sorted(e)) for e in GROUND_TRUTH_OUTLIERS)
        hits = detected & gt_set
        assert len(hits) >= 2, (
            f"Must detect at least 2 of 3 true outliers. "
            f"True outliers: {GROUND_TRUTH_OUTLIERS}. "
            f"Detected: {[list(p) for p in detected]}. "
            f"Hits: {len(hits)}"
        )

    def test_few_false_positives(self):
        detected = set()
        for entry in self.outliers:
            pair = tuple(sorted(entry))
            detected.add(pair)
        gt_set = set(tuple(sorted(e)) for e in GROUND_TRUTH_OUTLIERS)
        false_positives = detected - gt_set
        assert len(false_positives) <= 2, (
            f"Too many false positive outliers ({len(false_positives)}). "
            f"Detected: {[list(p) for p in detected]}. "
            f"True: {GROUND_TRUTH_OUTLIERS}. "
            f"FPs: {[list(p) for p in false_positives]}"
        )


class TestReport:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/output/report.json") as f:
            self.report = json.load(f)

    def test_required_fields_present(self):
        required = [
            "strategy_a_name",
            "strategy_b_name",
            "strategy_a_mean_residual_deg",
            "strategy_b_mean_residual_deg",
            "chosen_strategy",
            "outlier_threshold_deg",
        ]
        for field in required:
            assert field in self.report, (
                f"report.json missing required field '{field}'"
            )

    def test_strategy_names_are_strings(self):
        assert isinstance(self.report["strategy_a_name"], str)
        assert isinstance(self.report["strategy_b_name"], str)
        assert isinstance(self.report["chosen_strategy"], str)
        assert len(self.report["strategy_a_name"]) > 0
        assert len(self.report["strategy_b_name"]) > 0

    def test_strategies_are_different(self):
        assert self.report["strategy_a_name"] != self.report["strategy_b_name"], (
            "strategy_a_name and strategy_b_name must be different strategies"
        )

    def test_residuals_are_numeric(self):
        a = self.report["strategy_a_mean_residual_deg"]
        b = self.report["strategy_b_mean_residual_deg"]
        t = self.report["outlier_threshold_deg"]
        assert isinstance(a, (int, float)) and a >= 0, (
            f"strategy_a_mean_residual_deg must be non-negative number, got {a}"
        )
        assert isinstance(b, (int, float)) and b >= 0, (
            f"strategy_b_mean_residual_deg must be non-negative number, got {b}"
        )
        assert isinstance(t, (int, float)) and t > 0, (
            f"outlier_threshold_deg must be positive number, got {t}"
        )

    def test_chosen_strategy_matches(self):
        chosen = self.report["chosen_strategy"]
        assert chosen in (
            self.report["strategy_a_name"],
            self.report["strategy_b_name"],
        ), (
            f"chosen_strategy '{chosen}' must match one of the strategy names: "
            f"'{self.report['strategy_a_name']}' or '{self.report['strategy_b_name']}'"
        )

    def test_chosen_has_lower_residual(self):
        chosen = self.report["chosen_strategy"]
        a_res = self.report["strategy_a_mean_residual_deg"]
        b_res = self.report["strategy_b_mean_residual_deg"]
        if chosen == self.report["strategy_a_name"]:
            assert a_res <= b_res + 0.1, (
                f"Chosen strategy '{chosen}' has residual {a_res:.2f}° but "
                f"other has {b_res:.2f}° — chosen should have equal or lower residual"
            )
        else:
            assert b_res <= a_res + 0.1, (
                f"Chosen strategy '{chosen}' has residual {b_res:.2f}° but "
                f"other has {a_res:.2f}° — chosen should have equal or lower residual"
            )
