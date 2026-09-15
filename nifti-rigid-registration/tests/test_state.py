"""Verify rigid-body registration results.

"""

import json
import os

import numpy as np
import nibabel as nib
from scipy.spatial.transform import Rotation

# ---------------------------------------------------------------------------
# Ground-truth transforms (must match setup_data.py exactly)
# ---------------------------------------------------------------------------
GROUND_TRUTH = {
    "patient_1": {
        "euler_zyx_deg": [12.0, -8.0, 5.0],
        "translation_mm": [4.0, -3.0, 6.0],
    },
    "patient_2": {
        "euler_zyx_deg": [-5.0, 15.0, -10.0],
        "translation_mm": [-7.0, 2.0, -4.0],
    },
    "patient_3": {
        "euler_zyx_deg": [8.0, 3.0, -20.0],
        "translation_mm": [10.0, 5.0, -8.0],
    },
}


def _gt_matrix(name: str) -> np.ndarray:
    """Build the ground-truth 4x4 transform for *name*."""
    p = GROUND_TRUTH[name]
    R = Rotation.from_euler("ZYX", p["euler_zyx_deg"], degrees=True)
    T = np.eye(4)
    T[:3, :3] = R.as_matrix()
    T[:3, 3] = p["translation_mm"]
    return T


def _rotation_angle_error_deg(R1: np.ndarray, R2: np.ndarray) -> float:
    """Geodesic distance (degrees) between two 3x3 rotation matrices."""
    R_diff = R1.T @ R2
    cos_angle = (np.trace(R_diff) - 1.0) / 2.0
    cos_angle = float(np.clip(cos_angle, -1.0, 1.0))
    return float(np.degrees(np.arccos(cos_angle)))


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation (= normalised cross-correlation for zero-mean)."""
    a64 = a.ravel().astype(np.float64)
    b64 = b.ravel().astype(np.float64)
    a_c = a64 - a64.mean()
    b_c = b64 - b64.mean()
    denom = np.sqrt(np.sum(a_c ** 2) * np.sum(b_c ** 2))
    if denom < 1e-12:
        return 0.0
    return float(np.sum(a_c * b_c) / denom)


def _best_match(T_recovered: np.ndarray, T_gt: np.ndarray):
    """Check T and T^{-1} against ground truth; return the better match.

    Handles the common convention ambiguity (ref->patient vs patient->ref).
    Returns (rot_error_deg, trans_error_mm).
    """
    best_rot = float("inf")
    best_trans = float("inf")
    for T_cand in [T_recovered, np.linalg.inv(T_recovered)]:
        rot_err = _rotation_angle_error_deg(T_cand[:3, :3], T_gt[:3, :3])
        trans_err = float(np.linalg.norm(T_cand[:3, 3] - T_gt[:3, 3]))
        if rot_err + trans_err < best_rot + best_trans:
            best_rot = rot_err
            best_trans = trans_err
    return best_rot, best_trans


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestOutputFilesExist:
    def test_json_exists(self):
        assert os.path.isfile("/app/output/registration_results.json")

    def test_resampled_1_exists(self):
        assert os.path.isfile("/app/output/resampled_1.nii.gz")

    def test_resampled_2_exists(self):
        assert os.path.isfile("/app/output/resampled_2.nii.gz")

    def test_resampled_3_exists(self):
        assert os.path.isfile("/app/output/resampled_3.nii.gz")


class TestJSONStructure:
    def test_keys_present(self):
        with open("/app/output/registration_results.json") as f:
            data = json.load(f)
        for key in ("patient_1", "patient_2", "patient_3"):
            assert key in data, f"Missing key: {key}"
            assert "transform_4x4" in data[key], f"Missing transform_4x4 in {key}"

    def test_matrices_are_4x4(self):
        with open("/app/output/registration_results.json") as f:
            data = json.load(f)
        for key in ("patient_1", "patient_2", "patient_3"):
            T = np.array(data[key]["transform_4x4"])
            assert T.shape == (4, 4), f"{key}: shape {T.shape} != (4, 4)"


class TestTransformAccuracy:
    """Check recovered transforms against ground truth."""

    def _load_results(self):
        with open("/app/output/registration_results.json") as f:
            return json.load(f)

    def test_patient_1_rotation(self):
        T_rec = np.array(self._load_results()["patient_1"]["transform_4x4"])
        rot_err, _ = _best_match(T_rec, _gt_matrix("patient_1"))
        assert rot_err < 2.0, f"patient_1 rotation error {rot_err:.2f}° >= 2.0°"

    def test_patient_1_translation(self):
        T_rec = np.array(self._load_results()["patient_1"]["transform_4x4"])
        _, trans_err = _best_match(T_rec, _gt_matrix("patient_1"))
        assert trans_err < 2.5, f"patient_1 translation error {trans_err:.2f} mm >= 2.5 mm"

    def test_patient_2_rotation(self):
        T_rec = np.array(self._load_results()["patient_2"]["transform_4x4"])
        rot_err, _ = _best_match(T_rec, _gt_matrix("patient_2"))
        assert rot_err < 2.0, f"patient_2 rotation error {rot_err:.2f}° >= 2.0°"

    def test_patient_2_translation(self):
        T_rec = np.array(self._load_results()["patient_2"]["transform_4x4"])
        _, trans_err = _best_match(T_rec, _gt_matrix("patient_2"))
        assert trans_err < 2.5, f"patient_2 translation error {trans_err:.2f} mm >= 2.5 mm"

    def test_patient_3_rotation(self):
        T_rec = np.array(self._load_results()["patient_3"]["transform_4x4"])
        rot_err, _ = _best_match(T_rec, _gt_matrix("patient_3"))
        assert rot_err < 2.0, f"patient_3 rotation error {rot_err:.2f}° >= 2.0°"

    def test_patient_3_translation(self):
        T_rec = np.array(self._load_results()["patient_3"]["transform_4x4"])
        _, trans_err = _best_match(T_rec, _gt_matrix("patient_3"))
        assert trans_err < 2.5, f"patient_3 translation error {trans_err:.2f} mm >= 2.5 mm"


class TestResamplingQuality:
    """Check that resampled volumes closely match the reference."""

    def _ref(self):
        return nib.load("/app/data/reference.nii.gz").get_fdata(dtype=np.float32)

    def _ref_affine(self):
        return nib.load("/app/data/reference.nii.gz").affine

    def test_resampled_1_ncc(self):
        ref = self._ref()
        res = nib.load("/app/output/resampled_1.nii.gz").get_fdata(dtype=np.float32)
        assert res.shape == ref.shape, f"Shape mismatch: {res.shape} vs {ref.shape}"
        ncc = _ncc(ref, res)
        assert ncc > 0.93, f"patient_1 NCC {ncc:.4f} < 0.93"

    def test_resampled_2_ncc(self):
        ref = self._ref()
        res = nib.load("/app/output/resampled_2.nii.gz").get_fdata(dtype=np.float32)
        assert res.shape == ref.shape, f"Shape mismatch: {res.shape} vs {ref.shape}"
        ncc = _ncc(ref, res)
        assert ncc > 0.93, f"patient_2 NCC {ncc:.4f} < 0.93"

    def test_resampled_3_ncc(self):
        ref = self._ref()
        res = nib.load("/app/output/resampled_3.nii.gz").get_fdata(dtype=np.float32)
        assert res.shape == ref.shape, f"Shape mismatch: {res.shape} vs {ref.shape}"
        ncc = _ncc(ref, res)
        assert ncc > 0.93, f"patient_3 NCC {ncc:.4f} < 0.93"

    def test_resampled_affines_match_reference(self):
        ref_aff = self._ref_affine()
        for i in range(1, 4):
            res_aff = nib.load(f"/app/output/resampled_{i}.nii.gz").affine
            np.testing.assert_array_almost_equal(
                res_aff, ref_aff, decimal=2,
                err_msg=f"patient_{i}: resampled affine != reference affine",
            )
