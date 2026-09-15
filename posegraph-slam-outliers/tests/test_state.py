
"""Tests for pose graph SLAM optimization with outlier rejection."""

import json
import math

import numpy as np
import pytest

NUM_POSES = 100
RADIUS = 5.0


def normalize_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def ground_truth_poses():
    """Regenerate deterministic ground truth (circular trajectory)."""
    gt = []
    for i in range(NUM_POSES):
        angle = 2 * math.pi * i / NUM_POSES
        x = RADIUS * math.cos(angle)
        y = RADIUS * math.sin(angle)
        theta = normalize_angle(angle + math.pi / 2)
        gt.append([x, y, theta])
    return np.array(gt)


def load_dataset():
    with open("/app/pose_graph.json") as f:
        return json.load(f)


def load_result():
    with open("/app/optimized_poses.json") as f:
        return json.load(f)


def ground_truth_outlier_indices():
    """Identify outlier loop closures by arc distance between connected poses."""
    dataset = load_dataset()
    outliers = []
    for idx, edge in enumerate(dataset["loop_closure_edges"]):
        i, j = edge["i"], edge["j"]
        arc = min(abs(i - j), NUM_POSES - abs(i - j))
        if arc > 25:
            outliers.append(idx)
    return outliers


class TestOutputFormat:
    def test_file_exists_and_parseable(self):
        result = load_result()
        assert isinstance(result, dict)

    def test_poses_field(self):
        result = load_result()
        assert "poses" in result, "Missing 'poses' key"
        assert len(result["poses"]) == NUM_POSES, (
            f"Expected {NUM_POSES} poses, got {len(result['poses'])}"
        )
        for i, p in enumerate(result["poses"]):
            assert len(p) == 3, f"Pose {i} should have 3 elements [x, y, theta]"
            assert all(isinstance(v, (int, float)) for v in p), (
                f"Pose {i} contains non-numeric values"
            )

    def test_rejected_field(self):
        result = load_result()
        assert "rejected_loop_closures" in result, (
            "Missing 'rejected_loop_closures' key"
        )
        rejected = result["rejected_loop_closures"]
        assert isinstance(rejected, list)
        dataset = load_dataset()
        n_lc = len(dataset["loop_closure_edges"])
        for idx in rejected:
            assert isinstance(idx, int), f"Outlier index {idx} is not an integer"
            assert 0 <= idx < n_lc, f"Outlier index {idx} out of range [0, {n_lc})"


class TestPoseAccuracy:
    def test_per_pose_position_error(self):
        gt = ground_truth_poses()
        result = load_result()
        poses = np.array(result["poses"])
        pos_err = np.sqrt(
            (poses[:, 0] - gt[:, 0]) ** 2 + (poses[:, 1] - gt[:, 1]) ** 2
        )
        worst = int(np.argmax(pos_err))
        assert np.all(pos_err < 0.5), (
            f"Pose {worst} position error {pos_err[worst]:.3f}m exceeds 0.5m"
        )

    def test_per_pose_angle_error(self):
        gt = ground_truth_poses()
        result = load_result()
        poses = np.array(result["poses"])
        ang_err = np.array([
            abs(normalize_angle(p - g))
            for p, g in zip(poses[:, 2], gt[:, 2])
        ])
        worst = int(np.argmax(ang_err))
        assert np.all(ang_err < 0.1), (
            f"Pose {worst} angle error {ang_err[worst]:.4f} rad exceeds 0.1 rad"
        )

    def test_mean_position_error(self):
        gt = ground_truth_poses()
        result = load_result()
        poses = np.array(result["poses"])
        pos_err = np.sqrt(
            (poses[:, 0] - gt[:, 0]) ** 2 + (poses[:, 1] - gt[:, 1]) ** 2
        )
        mean_err = float(np.mean(pos_err))
        assert mean_err < 0.2, (
            f"Mean position error {mean_err:.3f}m exceeds 0.2m"
        )

    def test_mean_angle_error(self):
        gt = ground_truth_poses()
        result = load_result()
        poses = np.array(result["poses"])
        ang_err = np.array([
            abs(normalize_angle(p - g))
            for p, g in zip(poses[:, 2], gt[:, 2])
        ])
        mean_err = float(np.mean(ang_err))
        assert mean_err < 0.05, (
            f"Mean angle error {mean_err:.4f} rad exceeds 0.05 rad"
        )


class TestOptimizationQuality:
    def test_not_initial_estimates(self):
        """Verify the result differs from the raw initial estimates."""
        dataset = load_dataset()
        result = load_result()
        initial = np.array(dataset["initial_estimates"])
        optimized = np.array(result["poses"])
        diff = np.sqrt(np.sum((initial[50:] - optimized[50:]) ** 2, axis=1))
        assert np.max(diff) > 0.1, (
            "Optimized poses appear identical to initial estimates — "
            "optimization may not have run"
        )

    def test_pose_0_fixed(self):
        """Pose 0 must remain at its initial position (gauge reference)."""
        dataset = load_dataset()
        result = load_result()
        init_0 = dataset["initial_estimates"][0]
        opt_0 = result["poses"][0]
        pos_err = math.sqrt(
            (init_0[0] - opt_0[0]) ** 2 + (init_0[1] - opt_0[1]) ** 2
        )
        assert pos_err < 0.01, (
            f"Pose 0 moved {pos_err:.4f}m from initial position "
            "(should be fixed as gauge reference)"
        )

    def test_outlier_detection_recall(self):
        """At least 3 of 5 true outliers must be detected."""
        gt_outliers = set(ground_truth_outlier_indices())
        result = load_result()
        detected = set(result["rejected_loop_closures"])
        true_pos = len(gt_outliers & detected)
        assert true_pos >= 3, (
            f"Only detected {true_pos}/5 outlier loop closures (need >=3)"
        )

    def test_outlier_detection_precision(self):
        """At most 2 correct loop closures may be falsely rejected."""
        gt_outliers = set(ground_truth_outlier_indices())
        result = load_result()
        detected = set(result["rejected_loop_closures"])
        false_pos = len(detected - gt_outliers)
        assert false_pos <= 2, (
            f"Falsely rejected {false_pos} correct loop closures (max 2 allowed)"
        )


class TestResidualConsistency:
    def _chi_squared(self, poses, edge):
        i, j = edge["i"], edge["j"]
        xi, yi, ti = poses[i]
        xj, yj, tj = poses[j]
        c, s = math.cos(ti), math.sin(ti)
        dx_pred = c * (xj - xi) + s * (yj - yi)
        dy_pred = -s * (xj - xi) + c * (yj - yi)
        dt_pred = normalize_angle(tj - ti)
        ex = edge["dx"] - dx_pred
        ey = edge["dy"] - dy_pred
        et = normalize_angle(edge["dtheta"] - dt_pred)
        info = edge["information"]
        return (
            info[0] * ex * ex
            + 2 * info[1] * ex * ey
            + 2 * info[2] * ex * et
            + info[3] * ey * ey
            + 2 * info[4] * ey * et
            + info[5] * et * et
        )

    def test_odometry_residuals(self):
        dataset = load_dataset()
        result = load_result()
        poses = np.array(result["poses"])
        for edge in dataset["odometry_edges"]:
            chi2 = self._chi_squared(poses, edge)
            assert chi2 < 50.0, (
                f"Odometry edge {edge['i']}->{edge['j']} has "
                f"chi-squared={chi2:.1f} (threshold 50)"
            )

    def test_accepted_loop_closure_residuals(self):
        dataset = load_dataset()
        result = load_result()
        poses = np.array(result["poses"])
        rejected = set(result["rejected_loop_closures"])
        for idx, edge in enumerate(dataset["loop_closure_edges"]):
            if idx in rejected:
                continue
            chi2 = self._chi_squared(poses, edge)
            assert chi2 < 50.0, (
                f"Accepted loop closure {edge['i']}->{edge['j']} "
                f"(index {idx}) has chi-squared={chi2:.1f} (threshold 50)"
            )
