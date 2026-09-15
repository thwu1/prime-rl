
"""
Tests for the 3D Rotation Toolkit.

Verifies correctness of all rotation conversion, distance, interpolation,
mean, and projection functions using deterministic inputs. Also verifies
that evaluation.json contains correct candidate selections.
"""

import hashlib
import json
import sys
sys.path.insert(0, '/app')

import numpy as np
import pytest
from rotation_toolkit import (
    quaternion_to_matrix, matrix_to_quaternion,
    axis_angle_to_matrix, matrix_to_axis_angle,
    geodesic_distance, matrix_to_rotation_6d,
    rotation_6d_to_matrix, slerp_rotations,
    karcher_mean, project_to_so3,
)


# ---------------------------------------------------------------------------
# Deterministic helper functions (independent of the module under test)
# ---------------------------------------------------------------------------

def _rotation_about_axis(axis, angle):
    """Reference rotation matrix via Rodrigues formula (self-contained)."""
    axis = np.array(axis, dtype=np.float64)
    n = np.linalg.norm(axis)
    if n < 1e-15:
        return np.eye(3, dtype=np.float64)
    axis = axis / n
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ], dtype=np.float64)
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def _random_rotation(rng):
    """Generate a random rotation via random axis-angle."""
    v = rng.randn(3)
    angle = np.linalg.norm(v)
    if angle < 1e-12:
        return np.eye(3, dtype=np.float64)
    axis = v / angle
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ], dtype=np.float64)
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def _ref_geodesic_distance(R1, R2):
    """Reference geodesic distance (self-contained, correct formula)."""
    R_rel = R1.T @ R2
    cos_a = np.clip((np.trace(R_rel) - 1.0) / 2.0, -1.0, 1.0)
    return np.arccos(cos_a)


# ===================================================================
# TestQuaternionToMatrix
# ===================================================================

class TestQuaternionToMatrix:
    def test_identity(self):
        q = np.array([1.0, 0.0, 0.0, 0.0])
        R = quaternion_to_matrix(q)
        np.testing.assert_allclose(R, np.eye(3), atol=1e-12)

    def test_90_around_x(self):
        """90-degree rotation about x-axis: (0,1,0) -> (0,0,1)."""
        angle = np.pi / 2
        q = np.array([np.cos(angle / 2), np.sin(angle / 2), 0.0, 0.0])
        R = quaternion_to_matrix(q)
        expected = np.array([
            [1, 0, 0],
            [0, 0, -1],
            [0, 1, 0],
        ], dtype=np.float64)
        np.testing.assert_allclose(R, expected, atol=1e-12)

    def test_90_around_z(self):
        """90-degree rotation about z-axis: (1,0,0) -> (0,1,0)."""
        angle = np.pi / 2
        q = np.array([np.cos(angle / 2), 0.0, 0.0, np.sin(angle / 2)])
        R = quaternion_to_matrix(q)
        expected = np.array([
            [0, -1, 0],
            [1, 0, 0],
            [0, 0, 1],
        ], dtype=np.float64)
        np.testing.assert_allclose(R, expected, atol=1e-12)

    def test_orthogonality(self):
        rng = np.random.RandomState(42)
        for _ in range(20):
            q = rng.randn(4)
            q /= np.linalg.norm(q)
            R = quaternion_to_matrix(q)
            np.testing.assert_allclose(
                R @ R.T, np.eye(3), atol=1e-10,
                err_msg="quaternion_to_matrix produced non-orthogonal matrix",
            )

    def test_determinant(self):
        rng = np.random.RandomState(42)
        for _ in range(20):
            q = rng.randn(4)
            q /= np.linalg.norm(q)
            R = quaternion_to_matrix(q)
            det = np.linalg.det(R)
            assert np.isclose(det, 1.0, atol=1e-10), (
                f"det(R) = {det}, expected 1.0"
            )

    def test_batch(self):
        rng = np.random.RandomState(123)
        qs = rng.randn(5, 4)
        qs /= np.linalg.norm(qs, axis=1, keepdims=True)
        Rs = quaternion_to_matrix(qs)
        assert Rs.shape == (5, 3, 3)
        for i in range(5):
            np.testing.assert_allclose(Rs[i] @ Rs[i].T, np.eye(3), atol=1e-10)
            np.testing.assert_allclose(np.linalg.det(Rs[i]), 1.0, atol=1e-10)

    def test_roundtrip_with_matrix_to_quaternion(self):
        """q -> R -> q' -> R' should satisfy R == R'."""
        rng = np.random.RandomState(99)
        for _ in range(10):
            q = rng.randn(4)
            q /= np.linalg.norm(q)
            if q[0] < 0:
                q = -q
            R = quaternion_to_matrix(q)
            q2 = matrix_to_quaternion(R)
            R2 = quaternion_to_matrix(q2)
            np.testing.assert_allclose(R, R2, atol=1e-10)


# ===================================================================
# TestAxisAngleToMatrix
# ===================================================================

class TestAxisAngleToMatrix:
    def test_identity(self):
        """Zero axis-angle should produce the identity matrix."""
        aa = np.array([0.0, 0.0, 0.0])
        R = axis_angle_to_matrix(aa)
        assert np.all(np.isfinite(R)), (
            "axis_angle_to_matrix produced NaN/Inf for zero input"
        )
        np.testing.assert_allclose(R, np.eye(3), atol=1e-12)

    def test_small_angle(self):
        """Very small axis-angle should give near-identity without NaN."""
        aa = np.array([1e-9, 0.0, 0.0])
        R = axis_angle_to_matrix(aa)
        assert np.all(np.isfinite(R)), (
            "axis_angle_to_matrix produced NaN/Inf for small angle"
        )
        np.testing.assert_allclose(R, np.eye(3), atol=1e-6)

    def test_90_around_z(self):
        aa = np.array([0.0, 0.0, np.pi / 2])
        R = axis_angle_to_matrix(aa)
        expected = _rotation_about_axis([0, 0, 1], np.pi / 2)
        np.testing.assert_allclose(R, expected, atol=1e-12)

    def test_180_around_x(self):
        aa = np.array([np.pi, 0.0, 0.0])
        R = axis_angle_to_matrix(aa)
        expected = _rotation_about_axis([1, 0, 0], np.pi)
        np.testing.assert_allclose(R, expected, atol=1e-10)

    def test_roundtrip(self):
        """axis_angle -> matrix -> axis_angle -> matrix roundtrip."""
        rng = np.random.RandomState(42)
        for _ in range(10):
            axis = rng.randn(3)
            axis /= np.linalg.norm(axis)
            angle = rng.uniform(0.1, 2.8)
            aa = angle * axis
            R = axis_angle_to_matrix(aa)
            aa2 = matrix_to_axis_angle(R)
            R2 = axis_angle_to_matrix(aa2)
            np.testing.assert_allclose(R, R2, atol=1e-8)

    def test_batch(self):
        aas = np.array([
            [0.0, 0.0, np.pi / 2],
            [np.pi / 2, 0.0, 0.0],
            [0.0, np.pi / 4, 0.0],
        ])
        Rs = axis_angle_to_matrix(aas)
        assert Rs.shape == (3, 3, 3)
        for i in range(3):
            np.testing.assert_allclose(
                Rs[i] @ Rs[i].T, np.eye(3), atol=1e-10,
            )


# ===================================================================
# TestGeodesicDistance
# ===================================================================

class TestGeodesicDistance:
    def test_zero_distance(self):
        """d(R, R) must be 0 for any rotation R."""
        rng = np.random.RandomState(42)
        R = _random_rotation(rng)
        d = geodesic_distance(R, R)
        np.testing.assert_allclose(d, 0.0, atol=1e-12,
            err_msg="geodesic_distance(R, R) should be 0")

    def test_known_angle(self):
        """Same-axis rotations: distance = angle difference."""
        R1 = _rotation_about_axis([0, 0, 1], 0.3)
        R2 = _rotation_about_axis([0, 0, 1], 0.8)
        d = geodesic_distance(R1, R2)
        np.testing.assert_allclose(d, 0.5, atol=1e-10)

    def test_known_90(self):
        """Distance from identity to 90-degree rotation is pi/2."""
        R1 = np.eye(3)
        R2 = _rotation_about_axis([0, 0, 1], np.pi / 2)
        d = geodesic_distance(R1, R2)
        np.testing.assert_allclose(d, np.pi / 2, atol=1e-10)

    def test_known_180(self):
        """Distance from identity to 180-degree rotation is pi."""
        R1 = np.eye(3)
        R2 = _rotation_about_axis([1, 0, 0], np.pi)
        d = geodesic_distance(R1, R2)
        np.testing.assert_allclose(d, np.pi, atol=1e-10)

    def test_symmetry(self):
        rng = np.random.RandomState(42)
        for _ in range(10):
            R1 = _random_rotation(rng)
            R2 = _random_rotation(rng)
            np.testing.assert_allclose(
                geodesic_distance(R1, R2),
                geodesic_distance(R2, R1),
                atol=1e-10,
            )

    def test_left_invariance(self):
        """Geodesic distance is invariant under left multiplication."""
        rng = np.random.RandomState(42)
        for _ in range(5):
            R1 = _random_rotation(rng)
            R2 = _random_rotation(rng)
            Q = _random_rotation(rng)
            d_orig = geodesic_distance(R1, R2)
            d_rot = geodesic_distance(Q @ R1, Q @ R2)
            np.testing.assert_allclose(d_orig, d_rot, atol=1e-10)

    def test_triangle_inequality(self):
        rng = np.random.RandomState(42)
        for _ in range(10):
            R1 = _random_rotation(rng)
            R2 = _random_rotation(rng)
            R3 = _random_rotation(rng)
            d12 = geodesic_distance(R1, R2)
            d23 = geodesic_distance(R2, R3)
            d13 = geodesic_distance(R1, R3)
            assert d13 <= d12 + d23 + 1e-10, (
                f"Triangle inequality violated: {d13} > {d12} + {d23}"
            )


# ===================================================================
# TestRotation6D
# ===================================================================

class TestRotation6D:
    def test_roundtrip(self):
        """R -> 6D -> R roundtrip."""
        rng = np.random.RandomState(42)
        for _ in range(10):
            R = _random_rotation(rng)
            d6 = matrix_to_rotation_6d(R)
            R_rec = rotation_6d_to_matrix(d6)
            np.testing.assert_allclose(R, R_rec, atol=1e-10)

    def test_identity(self):
        d6 = matrix_to_rotation_6d(np.eye(3))
        R = rotation_6d_to_matrix(d6)
        np.testing.assert_allclose(R, np.eye(3), atol=1e-12)

    def test_orthogonality_from_arbitrary_input(self):
        """rotation_6d_to_matrix should always produce a valid rotation."""
        rng = np.random.RandomState(42)
        for _ in range(10):
            d6 = rng.randn(6)
            R = rotation_6d_to_matrix(d6)
            np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-10)
            np.testing.assert_allclose(np.linalg.det(R), 1.0, atol=1e-10)


# ===================================================================
# TestKarcherMean
# ===================================================================

class TestKarcherMean:
    def test_single_rotation(self):
        R = _rotation_about_axis([0, 0, 1], np.pi / 4)
        mean = karcher_mean(np.array([R]))
        np.testing.assert_allclose(mean, R, atol=1e-8)

    def test_two_symmetric_rotations(self):
        """Mean of R(+theta) and R(-theta) about same axis is identity."""
        R1 = _rotation_about_axis([0, 0, 1], np.pi / 4)
        R2 = _rotation_about_axis([0, 0, 1], -np.pi / 4)
        mean = karcher_mean(np.array([R1, R2]))
        np.testing.assert_allclose(mean, np.eye(3), atol=1e-6)

    def test_weighted_mean(self):
        """Heavy weight toward R1 should pull mean closer to R1."""
        R1 = np.eye(3)
        R2 = _rotation_about_axis([0, 0, 1], np.pi / 2)
        mean = karcher_mean(
            np.array([R1, R2]),
            weights=np.array([10.0, 1.0]),
        )
        d1 = _ref_geodesic_distance(mean, R1)
        d2 = _ref_geodesic_distance(mean, R2)
        assert d1 < d2, f"Expected mean closer to R1: d1={d1}, d2={d2}"

    def test_is_rotation(self):
        """Result must be a valid rotation matrix."""
        rng = np.random.RandomState(42)
        Rs = np.array([_random_rotation(rng) for _ in range(5)])
        mean = karcher_mean(Rs)
        np.testing.assert_allclose(mean @ mean.T, np.eye(3), atol=1e-8)
        np.testing.assert_allclose(np.linalg.det(mean), 1.0, atol=1e-8)


# ===================================================================
# TestProjectToSO3
# ===================================================================

class TestProjectToSO3:
    def test_already_rotation(self):
        R = _rotation_about_axis([1, 1, 1], np.pi / 3)
        R_proj = project_to_so3(R)
        np.testing.assert_allclose(R_proj, R, atol=1e-10)

    def test_perturbed_rotation(self):
        rng = np.random.RandomState(42)
        R = _random_rotation(rng)
        M = R + 0.1 * rng.randn(3, 3)
        R_proj = project_to_so3(M)
        np.testing.assert_allclose(R_proj @ R_proj.T, np.eye(3), atol=1e-10)
        np.testing.assert_allclose(np.linalg.det(R_proj), 1.0, atol=1e-10)

    def test_negative_det(self):
        """Even if SVD gives det=-1, result should have det=+1."""
        M = np.diag([1.0, 1.0, -1.0])  # reflection
        R_proj = project_to_so3(M)
        np.testing.assert_allclose(R_proj @ R_proj.T, np.eye(3), atol=1e-10)
        np.testing.assert_allclose(np.linalg.det(R_proj), 1.0, atol=1e-10)

    def test_frobenius_close(self):
        """Projected rotation should be close to the perturbed input."""
        rng = np.random.RandomState(42)
        R = _random_rotation(rng)
        M = R + 0.01 * rng.randn(3, 3)
        R_proj = project_to_so3(M)
        dist = np.linalg.norm(R_proj - M, 'fro')
        assert dist < 0.1, f"Projected rotation too far from input: {dist}"


# ===================================================================
# TestSlerpRotations
# ===================================================================

class TestSlerpRotations:
    def test_endpoints(self):
        R1 = np.eye(3)
        R2 = _rotation_about_axis([0, 0, 1], np.pi / 2)
        np.testing.assert_allclose(slerp_rotations(R1, R2, 0.0), R1, atol=1e-10)
        np.testing.assert_allclose(slerp_rotations(R1, R2, 1.0), R2, atol=1e-10)

    def test_midpoint(self):
        R1 = np.eye(3)
        R2 = _rotation_about_axis([0, 0, 1], np.pi / 2)
        R_mid = slerp_rotations(R1, R2, 0.5)
        expected = _rotation_about_axis([0, 0, 1], np.pi / 4)
        np.testing.assert_allclose(R_mid, expected, atol=1e-8)

    def test_quarter(self):
        R1 = np.eye(3)
        R2 = _rotation_about_axis([0, 0, 1], np.pi / 2)
        R_q = slerp_rotations(R1, R2, 0.25)
        expected = _rotation_about_axis([0, 0, 1], np.pi / 8)
        np.testing.assert_allclose(R_q, expected, atol=1e-8)

    def test_is_rotation(self):
        rng = np.random.RandomState(42)
        R1 = _random_rotation(rng)
        R2 = _random_rotation(rng)
        for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
            R = slerp_rotations(R1, R2, t)
            np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-10)
            np.testing.assert_allclose(np.linalg.det(R), 1.0, atol=1e-10)

    def test_constant_angular_velocity(self):
        """SLERP produces constant angular velocity interpolation."""
        R1 = np.eye(3)
        R2 = _rotation_about_axis([1, 1, 0], np.pi * 0.8)
        ts = np.linspace(0, 1, 11)
        Rs = [slerp_rotations(R1, R2, t) for t in ts]

        # Compute consecutive geodesic distances using reference formula
        dists = []
        for i in range(len(Rs) - 1):
            dists.append(_ref_geodesic_distance(Rs[i], Rs[i + 1]))

        np.testing.assert_allclose(dists, dists[0], atol=1e-6,
            err_msg="SLERP should maintain constant angular velocity")


# ===================================================================
# TestEvaluationJson
# ===================================================================

class TestEvaluationJson:
    """Verify the evaluation.json report exists with correct structure and selections."""

    def test_file_exists(self):
        """evaluation.json must exist at /app/evaluation.json."""
        import os
        assert os.path.isfile('/app/evaluation.json'), (
            "Missing /app/evaluation.json — must document candidate selections"
        )

    def test_structure(self):
        """evaluation.json must have the correct schema."""
        with open('/app/evaluation.json') as f:
            data = json.load(f)

        required_funcs = [
            'rotation_6d_to_matrix',
            'slerp_rotations',
            'karcher_mean',
            'project_to_so3',
        ]
        for func in required_funcs:
            assert func in data, f"Missing evaluation entry for '{func}'"
            entry = data[func]
            assert 'selected' in entry, f"Missing 'selected' key for '{func}'"
            assert entry['selected'] in ('alpha', 'beta'), (
                f"Invalid selection '{entry['selected']}' for '{func}' — must be 'alpha' or 'beta'"
            )
            assert 'reason' in entry, f"Missing 'reason' key for '{func}'"
            assert len(str(entry['reason'])) >= 15, (
                f"Reason for '{func}' is too short — provide a meaningful justification"
            )

    def test_correct_selections(self):
        """Verify that the evaluation selections are mathematically correct."""
        with open('/app/evaluation.json') as f:
            data = json.load(f)

        ordered_funcs = [
            'rotation_6d_to_matrix',
            'slerp_rotations',
            'karcher_mean',
            'project_to_so3',
        ]
        sel_string = ':'.join(data[f]['selected'] for f in ordered_funcs)
        digest = hashlib.sha256(sel_string.encode()).hexdigest()[:16]
        assert digest == '209a91e99d2e40f3', (
            "One or more candidate selections in evaluation.json are incorrect"
        )
