#!/usr/bin/env python3
"""Tests for multi-scan point cloud alignment with HDF5 I/O."""
import numpy as np
import h5py
import os
import pytest


def generate_ground_truth_poses():
    """Regenerate deterministic ground truth poses.

    This function uses no random numbers -- positions and headings are
    hard-coded.  It must match the logic in generate_data.py exactly.
    """
    positions = np.array([
        [-5.0, -4.0, 1.5],
        [-1.0, -4.0, 1.5],
        [ 3.0, -4.0, 1.5],
        [ 6.0, -1.0, 1.5],
        [ 6.0,  3.0, 1.5],
        [ 2.0,  5.0, 1.5],
        [-3.0,  4.0, 1.5],
        [-6.0,  0.0, 1.5],
    ])

    gt_world_poses = []
    for i in range(8):
        next_i = (i + 1) % 8
        dx = positions[next_i, 0] - positions[i, 0]
        dy = positions[next_i, 1] - positions[i, 1]
        heading = np.arctan2(dy, dx)

        c, s = np.cos(heading), np.sin(heading)
        T = np.eye(4)
        T[0, 0] = c
        T[0, 1] = -s
        T[1, 0] = s
        T[1, 1] = c
        T[:3, 3] = positions[i]
        gt_world_poses.append(T)

    gt_world_poses = np.array(gt_world_poses)
    T_ref_inv = np.linalg.inv(gt_world_poses[0])
    gt_poses = np.array([T_ref_inv @ gt_world_poses[i] for i in range(8)])
    return gt_poses


def rotation_error_rad(R_est, R_gt):
    """Geodesic rotation error in radians."""
    R_err = R_est.T @ R_gt
    cos_angle = np.clip((np.trace(R_err) - 1.0) / 2.0, -1.0, 1.0)
    return np.arccos(cos_angle)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

OUTPUT_PATH = "/app/output/result.h5"


@pytest.fixture(scope="module")
def gt_poses():
    return generate_ground_truth_poses()


@pytest.fixture(scope="module")
def result_file():
    if not os.path.exists(OUTPUT_PATH):
        pytest.fail("Output file {} not found".format(OUTPUT_PATH))
    f = h5py.File(OUTPUT_PATH, 'r')
    yield f
    f.close()


@pytest.fixture(scope="module")
def est_poses(result_file):
    if 'poses' not in result_file:
        pytest.fail("Dataset 'poses' not found in result.h5")
    return result_file['poses'][:]


# ---------------------------------------------------------------------------
# HDF5 structure tests
# ---------------------------------------------------------------------------

def test_output_file_exists():
    assert os.path.exists(OUTPUT_PATH), \
        "Expected output file {} not found".format(OUTPUT_PATH)


def test_poses_dataset_exists(result_file):
    assert 'poses' in result_file, \
        "Dataset 'poses' not found in result.h5"


def test_poses_shape(est_poses):
    assert est_poses.shape == (8, 4, 4), \
        "Expected shape (8, 4, 4), got {}".format(est_poses.shape)


def test_poses_dtype(est_poses):
    assert np.issubdtype(est_poses.dtype, np.floating), \
        "Expected floating-point dtype, got {}".format(est_poses.dtype)


def test_reference_scan_attribute(result_file):
    ds = result_file['poses']
    assert 'reference_scan' in ds.attrs, \
        "Attribute 'reference_scan' not found on poses dataset"
    assert int(ds.attrs['reference_scan']) == 0, \
        "reference_scan attribute must be 0, got {}".format(
            ds.attrs['reference_scan'])


# ---------------------------------------------------------------------------
# Geometric validity tests
# ---------------------------------------------------------------------------

def test_pose_zero_is_identity(est_poses):
    assert np.allclose(est_poses[0], np.eye(4), atol=1e-6), \
        "Pose 0 must be the identity matrix"


def test_poses_are_valid_rigid_transforms(est_poses):
    for i in range(8):
        R = est_poses[i, :3, :3]
        det = np.linalg.det(R)
        assert abs(det - 1.0) < 1e-3, \
            "Pose {}: det(R) = {:.6f}, expected 1.0".format(i, det)
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-3), \
            "Pose {}: rotation is not orthogonal".format(i)
        assert np.allclose(est_poses[i, 3, :], [0, 0, 0, 1], atol=1e-6), \
            "Pose {}: bottom row must be [0,0,0,1]".format(i)


# ---------------------------------------------------------------------------
# Accuracy tests
# ---------------------------------------------------------------------------

def test_per_pose_translation_error(est_poses, gt_poses):
    for i in range(8):
        err = np.linalg.norm(est_poses[i, :3, 3] - gt_poses[i, :3, 3])
        assert err < 0.5, \
            "Pose {}: translation error {:.4f} m exceeds 0.5 m".format(i, err)


def test_per_pose_rotation_error(est_poses, gt_poses):
    for i in range(8):
        err = rotation_error_rad(est_poses[i, :3, :3], gt_poses[i, :3, :3])
        assert err < 0.15, \
            "Pose {}: rotation error {:.4f} rad exceeds 0.15 rad".format(i, err)


def test_absolute_trajectory_error(est_poses, gt_poses):
    """Root-mean-square translation error across all poses."""
    errors = [np.linalg.norm(est_poses[i, :3, 3] - gt_poses[i, :3, 3])
              for i in range(8)]
    ate = np.sqrt(np.mean(np.array(errors) ** 2))
    assert ate < 0.3, \
        "ATE = {:.4f} m exceeds 0.3 m threshold".format(ate)


def test_relative_pose_consistency(est_poses, gt_poses):
    """Check that consecutive relative poses are accurate."""
    for i in range(7):
        T_rel_est = np.linalg.inv(est_poses[i]) @ est_poses[i + 1]
        T_rel_gt = np.linalg.inv(gt_poses[i]) @ gt_poses[i + 1]
        trans_err = np.linalg.norm(T_rel_est[:3, 3] - T_rel_gt[:3, 3])
        rot_err = rotation_error_rad(T_rel_est[:3, :3], T_rel_gt[:3, :3])
        assert trans_err < 0.6, \
            "Pair ({},{}): relative translation error {:.4f} m".format(
                i, i + 1, trans_err)
        assert rot_err < 0.2, \
            "Pair ({},{}): relative rotation error {:.4f} rad".format(
                i, i + 1, rot_err)
