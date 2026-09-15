"""Tests for multi-view SfM reconstruction output.

"""

import json
import os
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_reconstruction():
    with open("/app/output/reconstruction.json") as f:
        return json.load(f)


def load_observations():
    with open("/app/data/observations.json") as f:
        return json.load(f)


def load_intrinsics():
    with open("/app/data/intrinsics.json") as f:
        return json.load(f)


def load_ground_truth():
    with open("/tests/ground_truth.json") as f:
        return json.load(f)


def umeyama_align(X, Y):
    """Umeyama (1991) similarity alignment: find s, R, t minimising
    ||Y - (s * R @ X + t)||^2.  X, Y are N x 3 arrays.
    Returns (s, R, t).
    """
    assert X.shape == Y.shape
    n, d = X.shape

    mu_x = X.mean(axis=0)
    mu_y = Y.mean(axis=0)
    X_c = X - mu_x
    Y_c = Y - mu_y

    var_x = np.sum(X_c ** 2) / n
    if var_x < 1e-12:
        return 1.0, np.eye(d), mu_y - mu_x

    cov = Y_c.T @ X_c / n
    U, D, Vt = np.linalg.svd(cov)

    S = np.eye(d)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[d - 1, d - 1] = -1

    R = U @ S @ Vt
    s = np.trace(np.diag(D) @ S) / var_x
    t = mu_y - s * R @ mu_x

    return s, R, t


def rotation_angle_deg(R1, R2):
    """Geodesic angle between two 3x3 rotation matrices, in degrees."""
    R_rel = R1.T @ R2
    cos_angle = np.clip((np.trace(R_rel) - 1.0) / 2.0, -1.0, 1.0)
    return float(np.degrees(np.arccos(cos_angle)))


def build_K(cam):
    return np.array([
        [cam["fx"], 0, cam["cx"]],
        [0, cam["fy"], cam["cy"]],
        [0, 0, 1],
    ])


def compute_reprojection_errors(rec, obs_data, intr_data):
    """Return per-observation reprojection error array."""
    K = {}
    for c in intr_data["cameras"]:
        K[c["camera_id"]] = build_K(c)

    rec_cams = {c["camera_id"]: c for c in rec["cameras"]}
    rec_pts = {p["point_id"]: np.array(p["xyz"]) for p in rec["points_3d"]}

    errors = []
    for o in obs_data["observations"]:
        ci, pi = o["camera_id"], o["point_id"]
        if ci not in rec_cams or pi not in rec_pts:
            continue
        R = np.array(rec_cams[ci]["R"])
        t = np.array(rec_cams[ci]["t"])
        K_ci = K[ci]
        P3d = rec_pts[pi]

        P_cam = R @ P3d + t
        if P_cam[2] < 1e-6:
            errors.append(1e4)
            continue

        u_proj = K_ci[0, 0] * P_cam[0] / P_cam[2] + K_ci[0, 2]
        v_proj = K_ci[1, 1] * P_cam[1] / P_cam[2] + K_ci[1, 2]
        err = np.sqrt((u_proj - o["u"]) ** 2 + (v_proj - o["v"]) ** 2)
        errors.append(err)

    return np.array(errors)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rec():
    return load_reconstruction()


@pytest.fixture(scope="module")
def obs_data():
    return load_observations()


@pytest.fixture(scope="module")
def intr_data():
    return load_intrinsics()


@pytest.fixture(scope="module")
def gt():
    return load_ground_truth()


@pytest.fixture(scope="module")
def alignment(rec, gt):
    """Procrustes alignment of reconstructed points to ground truth."""
    gt_pts_map = {i: np.array(p) for i, p in enumerate(gt["points_3d"])}
    rec_pts_map = {p["point_id"]: np.array(p["xyz"]) for p in rec["points_3d"]}

    common_ids = sorted(set(gt_pts_map.keys()) & set(rec_pts_map.keys()))
    assert len(common_ids) >= 20, "Too few common points for alignment"

    X = np.array([rec_pts_map[pi] for pi in common_ids])
    Y = np.array([gt_pts_map[pi] for pi in common_ids])

    s, R_align, t_align = umeyama_align(X, Y)

    X_aligned = s * (R_align @ X.T).T + t_align
    return {
        "s": s,
        "R_align": R_align,
        "t_align": t_align,
        "common_ids": common_ids,
        "X_aligned": X_aligned,
        "Y": Y,
    }


# ---------------------------------------------------------------------------
# Tests — output structure
# ---------------------------------------------------------------------------

class TestOutputStructure:
    def test_output_file_exists(self):
        assert os.path.exists("/app/output/reconstruction.json"), \
            "Output file /app/output/reconstruction.json not found"

    def test_output_valid_structure(self, rec):
        assert "cameras" in rec, "Missing 'cameras' key"
        assert "points_3d" in rec, "Missing 'points_3d' key"
        assert isinstance(rec["cameras"], list)
        assert isinstance(rec["points_3d"], list)

        for cam in rec["cameras"]:
            assert "camera_id" in cam
            assert "R" in cam
            assert "t" in cam
            R = np.array(cam["R"])
            t = np.array(cam["t"])
            assert R.shape == (3, 3), \
                f"Camera {cam['camera_id']}: R shape {R.shape} != (3,3)"
            assert t.shape == (3,), \
                f"Camera {cam['camera_id']}: t shape {t.shape} != (3,)"

        for pt in rec["points_3d"]:
            assert "point_id" in pt
            assert "xyz" in pt
            xyz = np.array(pt["xyz"])
            assert xyz.shape == (3,), \
                f"Point {pt['point_id']}: xyz shape {xyz.shape} != (3,)"

    def test_all_cameras_present(self, rec):
        cam_ids = {c["camera_id"] for c in rec["cameras"]}
        assert cam_ids == {0, 1, 2, 3, 4}, \
            f"Expected cameras {{0,1,2,3,4}}, got {cam_ids}"

    def test_sufficient_points(self, rec):
        assert len(rec["points_3d"]) >= 50, \
            f"Only {len(rec['points_3d'])} points reconstructed (need >= 50)"


# ---------------------------------------------------------------------------
# Tests — camera validity
# ---------------------------------------------------------------------------

class TestCameraValidity:
    def test_camera_zero_is_reference(self, rec):
        cam0 = next(c for c in rec["cameras"] if c["camera_id"] == 0)
        R = np.array(cam0["R"])
        t = np.array(cam0["t"])
        assert np.allclose(R, np.eye(3), atol=0.01), \
            f"Camera 0 R should be identity, got\n{R}"
        assert np.allclose(t, np.zeros(3), atol=0.01), \
            f"Camera 0 t should be zero, got {t}"

    def test_valid_rotation_matrices(self, rec):
        for cam in rec["cameras"]:
            ci = cam["camera_id"]
            R = np.array(cam["R"])
            assert np.allclose(R @ R.T, np.eye(3), atol=0.02), \
                f"Camera {ci}: R is not orthogonal"
            det = np.linalg.det(R)
            assert abs(det - 1.0) < 0.02, \
                f"Camera {ci}: det(R) = {det:.4f} != 1"


# ---------------------------------------------------------------------------
# Tests — reprojection quality
# ---------------------------------------------------------------------------

class TestReprojection:
    def test_median_reprojection_error(self, rec, obs_data, intr_data):
        errors = compute_reprojection_errors(rec, obs_data, intr_data)
        median_err = float(np.median(errors))
        assert median_err < 1.5, \
            f"Median reprojection error {median_err:.2f} px exceeds 1.5 px"

    def test_inlier_ratio(self, rec, obs_data, intr_data):
        errors = compute_reprojection_errors(rec, obs_data, intr_data)
        inlier_count = int(np.sum(errors < 5.0))
        ratio = inlier_count / len(errors) if len(errors) > 0 else 0.0
        assert ratio > 0.80, \
            f"Inlier ratio {ratio:.2f} < 0.80 (need >80% observations " \
            f"with reproj error < 5 px)"


# ---------------------------------------------------------------------------
# Tests — ground-truth accuracy (after Procrustes alignment)
# ---------------------------------------------------------------------------

class TestGroundTruthAccuracy:
    def test_point_accuracy(self, alignment):
        X_al = alignment["X_aligned"]
        Y = alignment["Y"]

        point_errors = np.linalg.norm(X_al - Y, axis=1)
        rmse = float(np.sqrt(np.mean(point_errors ** 2)))
        scene_extent = float(np.max(np.ptp(Y, axis=0)))

        norm_rmse = rmse / scene_extent
        assert norm_rmse < 0.05, \
            f"Point RMSE {rmse:.3f} / scene extent {scene_extent:.1f} " \
            f"= {norm_rmse:.4f} exceeds 0.05"

    def test_camera_rotation_accuracy(self, rec, gt, alignment):
        R_align = alignment["R_align"]

        gt_cams = {c["camera_id"]: c for c in gt["cameras"]}
        rec_cams = {c["camera_id"]: c for c in rec["cameras"]}

        rot_errors = []
        for ci in range(5):
            R_gt = np.array(gt_cams[ci]["R"])
            R_rec = np.array(rec_cams[ci]["R"])
            R_rec_aligned = R_rec @ R_align.T
            err = rotation_angle_deg(R_gt, R_rec_aligned)
            rot_errors.append(err)

        mean_err = float(np.mean(rot_errors))
        assert mean_err < 5.0, \
            f"Mean camera rotation error {mean_err:.2f} deg exceeds 5.0 deg. " \
            f"Per-camera: {[f'{e:.2f}' for e in rot_errors]}"

    def test_camera_translation_accuracy(self, rec, gt, alignment):
        s = alignment["s"]
        R_align = alignment["R_align"]
        t_align = alignment["t_align"]

        gt_cams = {c["camera_id"]: c for c in gt["cameras"]}
        rec_cams = {c["camera_id"]: c for c in rec["cameras"]}

        trans_errors = []
        baselines = []
        for ci in range(5):
            R_gt = np.array(gt_cams[ci]["R"])
            t_gt = np.array(gt_cams[ci]["t"])
            R_rec = np.array(rec_cams[ci]["R"])
            t_rec = np.array(rec_cams[ci]["t"])

            C_gt = -R_gt.T @ t_gt
            C_rec = -R_rec.T @ t_rec
            C_rec_al = s * R_align @ C_rec + t_align

            trans_errors.append(float(np.linalg.norm(C_rec_al - C_gt)))
            baselines.append(float(np.linalg.norm(C_gt)))

        nonzero_baselines = [b for b in baselines if b > 0.01]
        mean_baseline = float(np.mean(nonzero_baselines)) if nonzero_baselines else 1.0
        mean_err = float(np.mean(trans_errors))
        norm_err = mean_err / max(mean_baseline, 0.01)

        assert norm_err < 0.15, \
            f"Normalized camera position error {norm_err:.3f} exceeds 0.15. " \
            f"Mean error {mean_err:.3f}, mean baseline {mean_baseline:.3f}"
