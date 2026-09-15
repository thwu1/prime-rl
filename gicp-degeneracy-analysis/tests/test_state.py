"""Tests for point cloud registration with degeneracy and observability analysis."""

import json
import os

import numpy as np
import pytest

SCANS_DIR = "/app/scans"
RESULTS_DIR = "/app/results"
SCANS = [f"scan_{i}" for i in range(1, 6)]


# ── Ground-truth computation (same parameters as data generator) ────────────


def _skew(v):
    return np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])


def _rot_aa(axis, angle):
    a = np.asarray(axis, dtype=np.float64)
    a = a / np.linalg.norm(a)
    K = _skew(a)
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * K @ K


def _make_T(R, t):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def _ground_truth():
    return {
        "scan_1": _make_T(_rot_aa([0, 0, 1], np.radians(10)), [0.30, 0.12, 0.08]),
        "scan_2": _make_T(_rot_aa([0.4, 0.6, 0.7], np.radians(5)), [0.15, -0.10, 0.12]),
        "scan_3": _make_T(_rot_aa([0, 0, 1], np.radians(4)), [0.12, 0.08, 0.25]),
        "scan_4": _make_T(_rot_aa([1, 0, 0], np.radians(4)), [0.70, 0.12, 0.08]),
        "scan_5": _make_T(_rot_aa([1, 1, 1], np.radians(8)), [0.18, 0.22, 0.12]),
    }


_GT = _ground_truth()
_DEGENERATE = {"scan_3", "scan_4"}
_NON_DEGENERATE = {"scan_1", "scan_2", "scan_5"}


# ── Helpers ─────────────────────────────────────────────────────────────────


def rotation_error_rad(T_est, T_gt):
    R_err = T_est[:3, :3].T @ T_gt[:3, :3]
    trace = np.clip(np.trace(R_err), -1.0, 3.0)
    return np.arccos(np.clip((trace - 1.0) / 2.0, -1.0, 1.0))


def translation_error(T_est, T_gt):
    return np.linalg.norm(T_est[:3, 3] - T_gt[:3, 3])


def load_transform(scan):
    with open(os.path.join(RESULTS_DIR, scan, "transform.json")) as f:
        data = json.load(f)
    return np.array(data["matrix"])


def load_eigenvalues(scan):
    with open(os.path.join(RESULTS_DIR, scan, "hessian_eigenvalues.json")) as f:
        data = json.load(f)
    return np.array(data["eigenvalues"])


def load_classification(scan):
    with open(os.path.join(RESULTS_DIR, scan, "classification.json")) as f:
        return json.load(f)


def load_diagnosis(scan):
    with open(os.path.join(RESULTS_DIR, scan, "diagnosis.json")) as f:
        return json.load(f)


# ── Structural tests ───────────────────────────────────────────────────────


class TestStructure:
    @pytest.mark.parametrize("sc", SCANS)
    def test_result_files_exist(self, sc):
        res_dir = os.path.join(RESULTS_DIR, sc)
        for fname in (
            "transform.json",
            "hessian_eigenvalues.json",
            "classification.json",
            "diagnosis.json",
        ):
            path = os.path.join(res_dir, fname)
            assert os.path.isfile(path), f"Missing {path}"

    @pytest.mark.parametrize("sc", SCANS)
    def test_transform_shape(self, sc):
        T = load_transform(sc)
        assert T.shape == (4, 4), f"Transform shape is {T.shape}, expected (4, 4)"
        np.testing.assert_allclose(
            T[3, :], [0, 0, 0, 1], atol=1e-6,
            err_msg=f"{sc}: bottom row of T must be [0,0,0,1]",
        )

    @pytest.mark.parametrize("sc", SCANS)
    def test_rotation_valid(self, sc):
        T = load_transform(sc)
        R = T[:3, :3]
        np.testing.assert_allclose(
            R.T @ R, np.eye(3), atol=1e-3,
            err_msg=f"{sc}: R is not orthogonal",
        )
        assert abs(np.linalg.det(R) - 1.0) < 1e-3, \
            f"{sc}: det(R)={np.linalg.det(R):.6f}"

    @pytest.mark.parametrize("sc", SCANS)
    def test_eigenvalues_format(self, sc):
        eigvals = load_eigenvalues(sc)
        assert eigvals.shape == (6,), \
            f"{sc}: expected 6 eigenvalues, got {eigvals.shape}"
        assert np.all(np.diff(eigvals) >= -1e-8), \
            f"{sc}: eigenvalues not sorted ascending"
        assert np.all(eigvals >= -1e-6), \
            f"{sc}: negative eigenvalues found"

    @pytest.mark.parametrize("sc", SCANS)
    def test_classification_format(self, sc):
        cls = load_classification(sc)
        assert "is_degenerate" in cls, f"{sc}: missing is_degenerate"
        assert "condition_number" in cls, f"{sc}: missing condition_number"
        assert "degenerate_dof_count" in cls, f"{sc}: missing degenerate_dof_count"
        assert isinstance(cls["is_degenerate"], bool), \
            f"{sc}: is_degenerate must be bool"
        assert isinstance(cls["condition_number"], (int, float)), \
            f"{sc}: condition_number must be numeric"
        assert isinstance(cls["degenerate_dof_count"], int), \
            f"{sc}: degenerate_dof_count must be int"

    @pytest.mark.parametrize("sc", SCANS)
    def test_diagnosis_format(self, sc):
        diag = load_diagnosis(sc)
        assert "scene_type" in diag, f"{sc}: missing scene_type"
        assert "registration_reliable" in diag, f"{sc}: missing registration_reliable"
        assert "num_well_constrained_dofs" in diag, f"{sc}: missing num_well_constrained_dofs"
        assert "corrective_strategy" in diag, f"{sc}: missing corrective_strategy"
        assert isinstance(diag["scene_type"], str) and len(diag["scene_type"]) > 0, \
            f"{sc}: scene_type must be a non-empty string"
        assert isinstance(diag["registration_reliable"], bool), \
            f"{sc}: registration_reliable must be bool"
        assert isinstance(diag["num_well_constrained_dofs"], int), \
            f"{sc}: num_well_constrained_dofs must be int"
        assert 0 <= diag["num_well_constrained_dofs"] <= 6, \
            f"{sc}: num_well_constrained_dofs must be in [0, 6]"


# ── Non-degenerate scenario accuracy ───────────────────────────────────────


class TestNonDegenerateAccuracy:
    @pytest.mark.parametrize("sc", ["scan_1", "scan_2", "scan_5"])
    def test_registration_accuracy(self, sc):
        T_est = load_transform(sc)
        T_gt = _GT[sc]
        rot_err = rotation_error_rad(T_est, T_gt)
        trans_err = translation_error(T_est, T_gt)
        assert rot_err < np.radians(5), \
            f"{sc} rotation error {np.degrees(rot_err):.2f}deg > 5deg"
        assert trans_err < 0.35, \
            f"{sc} translation error {trans_err:.4f} > 0.35"

    @pytest.mark.parametrize("sc", ["scan_1", "scan_2", "scan_5"])
    def test_non_degenerate_classification(self, sc):
        cls = load_classification(sc)
        assert cls["is_degenerate"] is False, \
            f"{sc} should not be classified as degenerate"

    @pytest.mark.parametrize("sc", ["scan_1", "scan_2", "scan_5"])
    def test_non_degenerate_diagnosis(self, sc):
        diag = load_diagnosis(sc)
        assert diag["registration_reliable"] is True, \
            f"{sc} should be marked as reliable"
        assert diag["num_well_constrained_dofs"] == 6, \
            f"{sc} should have 6 well-constrained DOFs"
        assert diag["corrective_strategy"] is None, \
            f"{sc} should have null corrective_strategy"


# ── Degenerate scenario checks ─────────────────────────────────────────────


class TestDegenerateScenarios:
    def test_scan_3_detected(self):
        cls = load_classification("scan_3")
        assert cls["is_degenerate"] is True, \
            "scan_3 should be classified as degenerate"
        assert cls["condition_number"] < 0.01, \
            f"scan_3 condition_number {cls['condition_number']:.6e} should be < 0.01"

    def test_scan_3_well_constrained(self):
        T_est = load_transform("scan_3")
        T_gt = _GT["scan_3"]
        z_err = abs(T_est[2, 3] - T_gt[2, 3])
        assert z_err < 0.30, \
            f"scan_3 z-translation error {z_err:.4f} > 0.30 (constrained DOF)"

    def test_scan_4_detected(self):
        cls = load_classification("scan_4")
        assert cls["is_degenerate"] is True, \
            "scan_4 should be classified as degenerate"
        assert cls["condition_number"] < 0.01, \
            f"scan_4 condition_number {cls['condition_number']:.6e} should be < 0.01"

    def test_scan_4_well_constrained(self):
        T_est = load_transform("scan_4")
        T_gt = _GT["scan_4"]
        yz_err = np.linalg.norm(T_est[1:3, 3] - T_gt[1:3, 3])
        assert yz_err < 0.30, \
            f"scan_4 yz-translation error {yz_err:.4f} > 0.30 (constrained DOFs)"

    @pytest.mark.parametrize("sc", ["scan_3", "scan_4"])
    def test_degenerate_diagnosis(self, sc):
        diag = load_diagnosis(sc)
        assert diag["registration_reliable"] is False, \
            f"{sc} should not be marked as reliable"
        assert diag["num_well_constrained_dofs"] < 6, \
            f"{sc} should have fewer than 6 well-constrained DOFs"
        assert diag["corrective_strategy"] is not None, \
            f"{sc} should have a corrective_strategy"


# ── Eigenvalue spectrum consistency ────────────────────────────────────────


class TestEigenvalueSpectrum:
    def test_nondeg_ratio_exceeds_deg(self):
        eig1 = load_eigenvalues("scan_1")
        eig3 = load_eigenvalues("scan_3")
        r1 = eig1[0] / max(eig1[-1], 1e-10)
        r3 = eig3[0] / max(eig3[-1], 1e-10)
        assert r1 > r3, \
            f"Non-degenerate ratio ({r1:.6e}) should exceed degenerate ratio ({r3:.6e})"

    @pytest.mark.parametrize("sc", ["scan_1", "scan_2", "scan_5"])
    def test_nondeg_eigenvalue_ratio(self, sc):
        eigvals = load_eigenvalues(sc)
        ratio = eigvals[0] / max(eigvals[-1], 1e-10)
        assert ratio > 0.005, \
            f"{sc} eigenvalue ratio {ratio:.6e} too small for non-degenerate"
