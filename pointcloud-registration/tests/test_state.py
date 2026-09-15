"""
Tests for point cloud registration pipeline repair.

"""
import json
import os

import h5py
import numpy as np
import pytest


# Ground truth generation parameters (must match generate_data.py exactly)
TRANSFORM_PARAMS = [
    ([0, 0, 1],  0, [0.0,  0.0,  0.0]),
    ([0, 0, 1], 30, [0.5, -0.3,  0.2]),
    ([0, 1, 0], 45, [-0.4, 0.6, -0.1]),
    ([1, 0, 0], 55, [0.3,  0.2,  0.7]),
    ([1, 1, 1], 20, [-0.2, 0.1, -0.5]),
]

OUTPUT_PATH = "/app/output/transforms.json"
SCANS_PATH = "/app/data/scans.h5"


def axis_angle_to_rotation(axis, angle_deg):
    """Rodrigues rotation formula."""
    if angle_deg == 0:
        return np.eye(3)
    angle = np.radians(angle_deg)
    axis = np.array(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    return np.eye(3) + np.sin(angle) * K + (1.0 - np.cos(angle)) * (K @ K)


def ground_truth_align(axis, angle_deg, translation):
    """Compute 4x4 transform that maps scan_i coordinates back to scan_0 frame.

    Data was generated as: scan_i = R_gen @ ref + t_gen + noise.
    Aligning transform: T = [R_gen^T | -R_gen^T @ t_gen ; 0 0 0 1].
    """
    R_gen = axis_angle_to_rotation(axis, angle_deg)
    t_gen = np.array(translation, dtype=float)
    T = np.eye(4)
    T[:3, :3] = R_gen.T
    T[:3, 3] = -R_gen.T @ t_gen
    return T


def extract_rotation(M):
    """Extract the closest proper rotation from a 3x3 matrix via SVD."""
    U, _, Vt = np.linalg.svd(M)
    det = np.linalg.det(U @ Vt)
    C = np.diag([1.0, 1.0, det])
    return U @ C @ Vt


def angular_error_deg(R1, R2):
    """Angular distance between two rotation matrices, in degrees."""
    R_diff = R1 @ R2.T
    cos_theta = np.clip((np.trace(R_diff) - 1.0) / 2.0, -1.0, 1.0)
    return np.degrees(np.arccos(cos_theta))


@pytest.fixture
def transforms():
    with open(OUTPUT_PATH) as f:
        return json.load(f)


class TestOutputFormat:

    def test_output_exists(self):
        assert os.path.exists(OUTPUT_PATH), (
            f"Output file {OUTPUT_PATH} does not exist"
        )

    def test_valid_json_with_keys(self, transforms):
        for i in range(1, 5):
            key = f"T_{i}"
            assert key in transforms, f"Missing key '{key}' in output"

    def test_matrix_shapes(self, transforms):
        for i in range(1, 5):
            T = np.array(transforms[f"T_{i}"])
            assert T.shape == (4, 4), (
                f"T_{i} should be 4x4, got {T.shape}"
            )

    def test_bottom_row(self, transforms):
        for i in range(1, 5):
            T = np.array(transforms[f"T_{i}"])
            np.testing.assert_allclose(
                T[3, :], [0, 0, 0, 1], atol=1e-4,
                err_msg=f"T_{i} bottom row must be [0,0,0,1]",
            )

    def test_near_rigid(self, transforms):
        """3x3 block should be close to a rotation (det approx 1)."""
        for i in range(1, 5):
            T = np.array(transforms[f"T_{i}"])
            scale = abs(np.linalg.det(T[:3, :3])) ** (1.0 / 3.0)
            assert 0.7 < scale < 1.3, (
                f"T_{i} scale factor {scale:.4f} too far from 1.0"
            )


class TestRegistrationAccuracy:

    def test_rotation_error(self, transforms):
        """Recovered rotations must be within 5 degrees of ground truth."""
        for i in range(1, 5):
            axis, angle, trans = TRANSFORM_PARAMS[i]
            T_gt = ground_truth_align(axis, angle, trans)
            R_gt = T_gt[:3, :3]

            T_pred = np.array(transforms[f"T_{i}"])
            R_pred = extract_rotation(T_pred[:3, :3])

            err = angular_error_deg(R_pred, R_gt)
            assert err < 5.0, (
                f"T_{i} angular error {err:.2f} deg exceeds 5 deg threshold"
            )

    def test_translation_error(self, transforms):
        """Recovered translations must be within 0.3 units of ground truth."""
        for i in range(1, 5):
            axis, angle, trans = TRANSFORM_PARAMS[i]
            T_gt = ground_truth_align(axis, angle, trans)
            t_gt = T_gt[:3, 3]

            T_pred = np.array(transforms[f"T_{i}"])
            t_pred = T_pred[:3, 3]

            err = np.linalg.norm(t_pred - t_gt)
            assert err < 0.3, (
                f"T_{i} translation error {err:.4f} exceeds 0.3 threshold"
            )


class TestAlignmentQuality:

    def test_median_nn_distance(self, transforms):
        """After alignment, median nearest-neighbour distance must be < 0.5."""
        with h5py.File(SCANS_PATH, "r") as f:
            ref = f["scan_0/points"][:]

            for i in range(1, 5):
                scan = f[f"scan_{i}/points"][:]
                T = np.array(transforms[f"T_{i}"])

                # Apply transform
                aligned = scan @ T[:3, :3].T + T[:3, 3]

                # Brute-force nearest-neighbour distances
                dists_sq = (
                    np.sum(aligned ** 2, axis=1, keepdims=True)
                    - 2.0 * aligned @ ref.T
                    + np.sum(ref ** 2, axis=1, keepdims=True).T
                )
                nn_dists = np.sqrt(np.clip(dists_sq.min(axis=1), 0.0, None))
                median_d = np.median(nn_dists)

                assert median_d < 0.5, (
                    f"T_{i}: median NN distance {median_d:.4f} exceeds 0.5"
                )
