
"""Tests for kinematic calibration task output."""

import json
import math
import os
import xml.etree.ElementTree as ET

import numpy as np
import pytest


# --------------- FK implementation for verification ---------------

def _rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return [[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]]

def _rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]]

def _rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]

def _mat4_mult(A, B):
    C = [[0]*4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            s = 0.0
            for k in range(4):
                s += A[i][k] * B[k][j]
            C[i][j] = s
    return C

def _eye4():
    return [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]

def _trans4(x, y, z):
    T = _eye4()
    T[0][3] = x; T[1][3] = y; T[2][3] = z
    return T

def _rpy_mat(r, p, y):
    return _mat4_mult(_rot_z(y), _mat4_mult(_rot_y(p), _rot_x(r)))

def _axis_rot(axis, angle):
    ax, ay, az = axis
    n = math.sqrt(ax*ax + ay*ay + az*az)
    if n < 1e-12:
        return _eye4()
    ax /= n; ay /= n; az /= n
    c = math.cos(angle); s = math.sin(angle); t = 1 - c
    R = _eye4()
    R[0][0] = t*ax*ax+c;    R[0][1] = t*ax*ay-s*az; R[0][2] = t*ax*az+s*ay
    R[1][0] = t*ay*ax+s*az; R[1][1] = t*ay*ay+c;    R[1][2] = t*ay*az-s*ax
    R[2][0] = t*az*ax-s*ay; R[2][1] = t*az*ay+s*ax; R[2][2] = t*az*az+c
    return R

def _parse_joints(urdf_path):
    tree = ET.parse(urdf_path)
    root = tree.getroot()
    jp = {}
    for j in root.findall("joint"):
        parent = j.find("parent").get("link")
        jp.setdefault(parent, []).append(j)
    joints = []
    cur = "base_link"
    while cur in jp and jp[cur]:
        je = jp[cur][0]
        org = je.find("origin")
        xyz = [float(v) for v in org.get("xyz", "0 0 0").split()]
        rpy = [float(v) for v in org.get("rpy", "0 0 0").split()]
        ax = [float(v) for v in je.find("axis").get("xyz", "0 0 1").split()]
        joints.append({"name": je.get("name"), "xyz": xyz, "rpy": rpy, "axis": ax})
        cur = je.find("child").get("link")
    return joints

def _fk(angles, joints, corrections, tool_tip):
    T = _eye4()
    for ang, j in zip(angles, joints):
        ox, oy, oz = j["xyz"]
        if j["name"] in corrections:
            dx, dy, dz = corrections[j["name"]]
            ox += dx; oy += dy; oz += dz
        T_o = _mat4_mult(_trans4(ox, oy, oz), _rpy_mat(*j["rpy"]))
        T_j = _axis_rot(j["axis"], ang)
        T = _mat4_mult(T, _mat4_mult(T_o, T_j))
    T = _mat4_mult(T, _trans4(*tool_tip))
    return [T[0][3], T[1][3], T[2][3]]


# --------------- Fixtures ---------------

@pytest.fixture
def result():
    path = "/app/calibration_result.json"
    assert os.path.isfile(path), f"Missing output file: {path}"
    with open(path) as f:
        return json.load(f)

@pytest.fixture
def measurements():
    with open("/app/measurements.json") as f:
        return json.load(f)

@pytest.fixture
def joints():
    return _parse_joints("/app/robot.urdf")

@pytest.fixture
def validation_gt():
    with open("/tests/validation_ground_truth.json") as f:
        return json.load(f)

@pytest.fixture
def validation_configs():
    with open("/app/validation_configs.json") as f:
        return json.load(f)


# --------------- Tests ---------------

class TestOutputStructure:
    def test_file_exists(self):
        assert os.path.isfile("/app/calibration_result.json")

    def test_required_keys(self, result):
        required = ["nominal_rms_error_m", "calibrated_rms_error_m",
                     "parameter_corrections", "validation_predictions"]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_corrections_structure(self, result):
        pc = result["parameter_corrections"]
        expected_joints = ["joint1", "joint2", "joint3", "joint4", "joint5", "joint6"]
        for jname in expected_joints:
            assert jname in pc, f"Missing corrections for {jname}"
            for axis in ["dx", "dy", "dz"]:
                assert axis in pc[jname], f"Missing {axis} in {jname}"
                assert isinstance(pc[jname][axis], (int, float)), \
                    f"{jname}.{axis} must be numeric"

    def test_validation_predictions_count(self, result, validation_configs):
        n_expected = len(validation_configs["validation_configs"])
        assert len(result["validation_predictions"]) == n_expected, \
            f"Expected {n_expected} predictions, got {len(result['validation_predictions'])}"

    def test_predictions_are_3d(self, result):
        for i, pred in enumerate(result["validation_predictions"]):
            assert len(pred) == 3, f"Prediction {i} should have 3 components"
            for v in pred:
                assert isinstance(v, (int, float)), \
                    f"Prediction {i} component not numeric"


class TestNominalError:
    def test_nominal_rms_approximately_correct(self, result, measurements, joints):
        """Verify agent computed nominal RMS error correctly."""
        tool_tip = measurements["tool_tip_offset"]
        errors_sq = []
        for m in measurements["measurements"]:
            pos = _fk(m["joint_angles"], joints, {}, tool_tip)
            diff = [a - b for a, b in zip(pos, m["measured_position"])]
            errors_sq.append(sum(d*d for d in diff))
        expected_rms = math.sqrt(sum(errors_sq) / len(errors_sq))

        reported = result["nominal_rms_error_m"]
        assert abs(reported - expected_rms) < 0.001, \
            f"Nominal RMS {reported:.4f} differs from expected {expected_rms:.4f}"


class TestCalibrationQuality:
    def test_calibrated_rms_below_threshold(self, result):
        """Calibrated model must achieve < 2mm RMS position error."""
        assert result["calibrated_rms_error_m"] < 0.002, \
            f"Calibrated RMS {result['calibrated_rms_error_m']*1000:.2f}mm >= 2mm"

    def test_improvement_ratio(self, result):
        """Calibrated error must be at least 3x better than nominal."""
        nom = result["nominal_rms_error_m"]
        cal = result["calibrated_rms_error_m"]
        assert nom / cal >= 3.0, \
            f"Improvement ratio {nom/cal:.1f}x < 3x required"

    def test_calibrated_rms_independently_verified(self, result, measurements, joints):
        """Independently verify the calibrated RMS using agent's corrections."""
        pc = result["parameter_corrections"]
        corrections = {}
        for jname, c in pc.items():
            corrections[jname] = (c["dx"], c["dy"], c["dz"])

        tool_tip = measurements["tool_tip_offset"]
        errors_sq = []
        for m in measurements["measurements"]:
            pos = _fk(m["joint_angles"], joints, corrections, tool_tip)
            diff = [a - b for a, b in zip(pos, m["measured_position"])]
            errors_sq.append(sum(d*d for d in diff))
        actual_rms = math.sqrt(sum(errors_sq) / len(errors_sq))

        assert actual_rms < 0.002, \
            f"Independently computed calibrated RMS {actual_rms*1000:.2f}mm >= 2mm"

    def test_corrections_physically_reasonable(self, result):
        """Corrections should be on the order of millimeters, not meters."""
        for jname, c in result["parameter_corrections"].items():
            for axis in ["dx", "dy", "dz"]:
                val = abs(c[axis])
                assert val < 0.02, \
                    f"{jname}.{axis}={c[axis]:.6f} exceeds 20mm — not physically plausible"


class TestValidationPredictions:
    def test_predictions_match_ground_truth(self, result, validation_gt):
        """Each validation prediction must be within 2mm of ground truth."""
        preds = result["validation_predictions"]
        gt_configs = validation_gt["validation_configs"]
        max_err = 0.0
        for i, (pred, gt) in enumerate(zip(preds, gt_configs)):
            tp = gt["true_position"]
            err = math.sqrt(sum((a - b) ** 2 for a, b in zip(pred, tp)))
            max_err = max(max_err, err)
            assert err < 0.002, \
                f"Validation point {i}: error {err*1000:.2f}mm >= 2mm"
        print(f"Max validation error: {max_err*1000:.2f}mm")

    def test_validation_rms(self, result, validation_gt):
        """RMS of validation prediction errors must be below 1mm."""
        preds = result["validation_predictions"]
        gt_configs = validation_gt["validation_configs"]
        errors_sq = []
        for pred, gt in zip(preds, gt_configs):
            tp = gt["true_position"]
            err_sq = sum((a - b) ** 2 for a, b in zip(pred, tp))
            errors_sq.append(err_sq)
        rms = math.sqrt(sum(errors_sq) / len(errors_sq))
        assert rms < 0.001, \
            f"Validation RMS {rms*1000:.2f}mm >= 1mm"

    def test_predictions_from_calibrated_model(self, result, validation_configs, joints,
                                                measurements, validation_gt):
        """
        Verify that the validation predictions are consistent with
        applying the reported corrections to FK, not just copied from somewhere.
        """
        pc = result["parameter_corrections"]
        corrections = {}
        for jname, c in pc.items():
            corrections[jname] = (c["dx"], c["dy"], c["dz"])

        tool_tip = measurements["tool_tip_offset"]
        preds = result["validation_predictions"]
        configs = validation_configs["validation_configs"]

        for i, (pred, vc) in enumerate(zip(preds, configs)):
            pos = _fk(vc["joint_angles"], joints, corrections, tool_tip)
            diff = math.sqrt(sum((a - b)**2 for a, b in zip(pred, pos)))
            assert diff < 1e-6, \
                f"Prediction {i} doesn't match FK with reported corrections (diff={diff:.2e})"
