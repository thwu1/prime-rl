"""
Test suite for the multi-view 3D reconstruction pipeline and evaluator.

Tests verify correctness of:
1. Quaternion <-> rotation matrix conversion
2. SE3 inverse computation
3. Depth map unprojection to camera coordinates
4. Camera pose encoding/decoding roundtrip
5. COLMAP text format I/O (quaternion conventions, intrinsics)
6. Similarity alignment (Procrustes/Umeyama via SVD)
7. End-to-end reconstruction pipeline
8. RANSAC-based robust alignment with outlier rejection
9. SQLite evaluation database correctness
10. PLY point cloud export (binary format, vertex properties)
11. jq-extracted JSON outputs (outlier IDs, metrics summary)
12. sqlite3 CLI outputs (database view, CSV export)
"""


import numpy as np
import sqlite3
import json
import os
import sys

sys.path.insert(0, "/app")

from rotation_utils import quat_to_mat, mat_to_quat
from geometry_utils import (
    depth_to_cam_coords_points,
    closed_form_inverse_se3,
    depth_to_world_coords_points,
    project_points_to_camera,
)
from pose_encoding import extri_intri_to_pose_encoding, pose_encoding_to_extri_intri
from colmap_io import (
    read_cameras_text,
    read_images_text,
    read_points3d_text,
    load_scene,
    build_extrinsic_from_quat_trans,
)
from alignment import (
    estimate_similarity_transform,
    apply_similarity_transform,
    compute_alignment_error,
    robust_estimate_similarity_transform,
)


def _random_rotation_matrix(rng):
    """Generate a random valid rotation matrix via QR decomposition."""
    A = rng.standard_normal((3, 3))
    Q, _ = np.linalg.qr(A)
    if np.linalg.det(Q) < 0:
        Q[:, 0] *= -1
    return Q


# ---------------------------------------------------------------------------
# 1. Quaternion conversion tests
# ---------------------------------------------------------------------------

class TestQuaternionConversion:

    def test_identity_rotation(self):
        """Identity matrix should produce quaternion [0, 0, 0, 1] (XYZW)."""
        R = np.eye(3)
        q = mat_to_quat(R[np.newaxis])[0]
        expected = np.array([0.0, 0.0, 0.0, 1.0])
        diff = min(np.linalg.norm(q - expected), np.linalg.norm(q + expected))
        assert diff < 1e-10, f"Identity quaternion: expected {expected}, got {q}"

    def test_90deg_z_rotation(self):
        """90-deg rotation about z-axis: q = [0, 0, sin(pi/4), cos(pi/4)]."""
        R = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=np.float64)
        q = mat_to_quat(R[np.newaxis])[0]
        s45 = np.sin(np.pi / 4)
        c45 = np.cos(np.pi / 4)
        expected = np.array([0.0, 0.0, s45, c45])
        diff = min(np.linalg.norm(q - expected), np.linalg.norm(q + expected))
        assert diff < 1e-10, f"90-deg z-rotation: expected {expected}, got {q}"

    def test_180deg_x_rotation(self):
        """180-deg rotation about x-axis: q = [1, 0, 0, 0]."""
        R = np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]], dtype=np.float64)
        q = mat_to_quat(R[np.newaxis])[0]
        expected = np.array([1.0, 0.0, 0.0, 0.0])
        diff = min(np.linalg.norm(q - expected), np.linalg.norm(q + expected))
        assert diff < 1e-10, f"180-deg x-rotation: expected {expected}, got {q}"

    def test_roundtrip_random(self):
        """mat_to_quat(quat_to_mat(q)) should recover q for random quaternions."""
        rng = np.random.default_rng(42)
        for trial in range(20):
            q = rng.standard_normal(4)
            q = q / np.linalg.norm(q)
            if q[3] < 0:
                q = -q

            R = quat_to_mat(q[np.newaxis])[0]
            q_recovered = mat_to_quat(R[np.newaxis])[0]

            diff = min(
                np.linalg.norm(q - q_recovered),
                np.linalg.norm(q + q_recovered),
            )
            assert diff < 1e-8, (
                f"Quaternion roundtrip failed (trial {trial}): "
                f"original {q}, recovered {q_recovered}, diff {diff}"
            )


# ---------------------------------------------------------------------------
# 2. SE3 inverse tests
# ---------------------------------------------------------------------------

class TestSE3Inverse:

    def test_product_is_identity(self):
        """M @ inverse(M) should equal the 4x4 identity matrix."""
        rng = np.random.default_rng(123)
        for trial in range(10):
            R = _random_rotation_matrix(rng)
            t = rng.standard_normal((3, 1))

            M = np.eye(4)
            M[:3, :3] = R
            M[:3, 3:] = t

            M_inv = closed_form_inverse_se3(M[np.newaxis])[0]
            product = M @ M_inv

            np.testing.assert_allclose(
                product, np.eye(4), atol=1e-10,
                err_msg=f"M @ inverse(M) != I (trial {trial})",
            )

    def test_known_translation_inverse(self):
        """Pure translation: inverse should negate the translation vector."""
        t = np.array([[2.0], [-3.0], [7.0]])
        M = np.eye(4)
        M[:3, 3:] = t

        M_inv = closed_form_inverse_se3(M[np.newaxis])[0]

        np.testing.assert_allclose(
            M_inv[:3, 3], -t.flatten(), atol=1e-12,
            err_msg=f"Pure-translation inverse: expected {-t.flatten()}, "
                    f"got {M_inv[:3, 3]}",
        )

    def test_rotation_preserved(self):
        """Inverse should transpose the rotation block."""
        rng = np.random.default_rng(789)
        R = _random_rotation_matrix(rng)
        t = rng.standard_normal((3, 1))

        M = np.eye(4)
        M[:3, :3] = R
        M[:3, 3:] = t

        M_inv = closed_form_inverse_se3(M[np.newaxis])[0]

        np.testing.assert_allclose(
            M_inv[:3, :3], R.T, atol=1e-12,
            err_msg="Rotation block of inverse should be R^T",
        )


# ---------------------------------------------------------------------------
# 3. Depth unprojection tests
# ---------------------------------------------------------------------------

class TestDepthUnprojection:

    def test_principal_point_unprojection(self):
        """Depth at the principal point should unproject to (0, 0, d)."""
        fx, fy, cx, cy = 400.0, 200.0, 320.0, 240.0
        intrinsic = np.array(
            [[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64
        )
        H, W = 480, 640

        depth = np.zeros((H, W), dtype=np.float64)
        depth[int(cy), int(cx)] = 5.0

        cam_coords = depth_to_cam_coords_points(depth, intrinsic)

        np.testing.assert_allclose(cam_coords[int(cy), int(cx), 0], 0.0, atol=1e-10)
        np.testing.assert_allclose(cam_coords[int(cy), int(cx), 1], 0.0, atol=1e-10)
        np.testing.assert_allclose(cam_coords[int(cy), int(cx), 2], 5.0, atol=1e-10)

    def test_known_point_unprojection(self):
        """Project a 3D camera-frame point to a pixel, then unproject back."""
        fx, fy, cx, cy = 400.0, 200.0, 320.0, 240.0
        intrinsic = np.array(
            [[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64
        )
        H, W = 480, 640

        P = np.array([1.0, -2.0, 5.0])

        u = fx * P[0] / P[2] + cx
        v = fy * P[1] / P[2] + cy

        u_px, v_px = int(round(u)), int(round(v))
        depth = np.zeros((H, W), dtype=np.float64)
        depth[v_px, u_px] = P[2]

        cam_coords = depth_to_cam_coords_points(depth, intrinsic)

        np.testing.assert_allclose(
            cam_coords[v_px, u_px, 0], P[0], atol=1e-6,
            err_msg=f"x_cam: expected {P[0]}, got {cam_coords[v_px, u_px, 0]}",
        )
        np.testing.assert_allclose(
            cam_coords[v_px, u_px, 1], P[1], atol=1e-6,
            err_msg=f"y_cam: expected {P[1]}, got {cam_coords[v_px, u_px, 1]}",
        )

    def test_asymmetric_focal_lengths(self):
        """With fx != fy, horizontal and vertical unprojection scales must differ."""
        fx, fy = 500.0, 250.0
        cx, cy = 100.0, 100.0
        intrinsic = np.array(
            [[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64
        )

        depth = np.zeros((200, 200), dtype=np.float64)
        depth[150, 150] = 1.0

        cam_coords = depth_to_cam_coords_points(depth, intrinsic)

        np.testing.assert_allclose(
            cam_coords[150, 150, 0], 0.1, atol=1e-10,
            err_msg=f"x_cam should be 50/fx=0.1, got {cam_coords[150, 150, 0]}",
        )
        np.testing.assert_allclose(
            cam_coords[150, 150, 1], 0.2, atol=1e-10,
            err_msg=f"y_cam should be 50/fy=0.2, got {cam_coords[150, 150, 1]}",
        )


# ---------------------------------------------------------------------------
# 4. Pose encoding roundtrip tests
# ---------------------------------------------------------------------------

class TestPoseEncoding:

    def test_roundtrip_square_image(self):
        """Roundtrip with fx == fy should preserve rotation and focal length."""
        rng = np.random.default_rng(789)
        S = 3

        extrinsics = np.zeros((S, 3, 4), dtype=np.float64)
        for i in range(S):
            extrinsics[i, :3, :3] = _random_rotation_matrix(rng)
            extrinsics[i, :3, 3] = rng.standard_normal(3)

        f = 500.0
        intrinsics = np.zeros((S, 3, 3), dtype=np.float64)
        for i in range(S):
            intrinsics[i] = np.array([[f, 0, 256], [0, f, 256], [0, 0, 1]])

        image_hw = (512, 512)
        encoding = extri_intri_to_pose_encoding(extrinsics, intrinsics, image_hw)
        ext_dec, int_dec = pose_encoding_to_extri_intri(encoding, image_hw)

        for i in range(S):
            np.testing.assert_allclose(
                ext_dec[i, :3, :3], extrinsics[i, :3, :3], atol=1e-6,
                err_msg=f"Rotation mismatch at frame {i}",
            )
            np.testing.assert_allclose(
                ext_dec[i, :3, 3], extrinsics[i, :3, 3], atol=1e-6,
                err_msg=f"Translation mismatch at frame {i}",
            )
            np.testing.assert_allclose(
                int_dec[i, 0, 0], f, atol=1e-3,
                err_msg=f"fx mismatch at frame {i}: {int_dec[i, 0, 0]} vs {f}",
            )
            np.testing.assert_allclose(
                int_dec[i, 1, 1], f, atol=1e-3,
                err_msg=f"fy mismatch at frame {i}: {int_dec[i, 1, 1]} vs {f}",
            )

    def test_roundtrip_nonsquare_image(self):
        """Roundtrip with fx != fy must preserve both focal lengths independently."""
        rng = np.random.default_rng(101)
        S = 2

        extrinsics = np.zeros((S, 3, 4), dtype=np.float64)
        for i in range(S):
            extrinsics[i, :3, :3] = _random_rotation_matrix(rng)
            extrinsics[i, :3, 3] = rng.standard_normal(3)

        fx, fy = 600.0, 400.0
        intrinsics = np.zeros((S, 3, 3), dtype=np.float64)
        for i in range(S):
            intrinsics[i] = np.array([[fx, 0, 320], [0, fy, 240], [0, 0, 1]])

        image_hw = (480, 640)
        encoding = extri_intri_to_pose_encoding(extrinsics, intrinsics, image_hw)
        ext_dec, int_dec = pose_encoding_to_extri_intri(encoding, image_hw)

        for i in range(S):
            np.testing.assert_allclose(
                int_dec[i, 0, 0], fx, atol=1e-3,
                err_msg=f"fx: expected {fx}, got {int_dec[i, 0, 0]}",
            )
            np.testing.assert_allclose(
                int_dec[i, 1, 1], fy, atol=1e-3,
                err_msg=f"fy: expected {fy}, got {int_dec[i, 1, 1]}",
            )


# ---------------------------------------------------------------------------
# 5. COLMAP I/O tests
# ---------------------------------------------------------------------------

class TestColmapIO:

    def test_camera_intrinsics(self):
        """COLMAP camera reader should produce correct intrinsic matrix."""
        cameras = read_cameras_text('/app/data/cameras.txt')
        K = cameras[1]['intrinsic']
        np.testing.assert_allclose(K[0, 0], 400.0, atol=1e-10, err_msg="fx wrong")
        np.testing.assert_allclose(K[1, 1], 200.0, atol=1e-10, err_msg="fy wrong")
        np.testing.assert_allclose(K[0, 2], 320.0, atol=1e-10, err_msg="cx wrong")
        np.testing.assert_allclose(K[1, 2], 240.0, atol=1e-10, err_msg="cy wrong")

    def test_identity_quaternion_convention(self):
        """Identity camera quaternion should be [0,0,0,1] in XYZW (scalar-last)."""
        images = read_images_text('/app/data/images.txt')
        q = images[1]['quat_xyzw']
        expected = np.array([0.0, 0.0, 0.0, 1.0])
        diff = min(np.linalg.norm(q - expected), np.linalg.norm(q + expected))
        assert diff < 1e-10, (
            f"Identity quaternion should be [0,0,0,1] (XYZW), got {q}"
        )

    def test_rotation_from_colmap(self):
        """Rotation matrix reconstructed from COLMAP quaternion should match known value."""
        images = read_images_text('/app/data/images.txt')
        img2 = images[2]
        ext = build_extrinsic_from_quat_trans(img2['quat_xyzw'], img2['translation'])
        R = ext[:3, :3]

        # Image 2 is a 15-degree rotation about the x-axis
        angle = np.radians(15)
        R_expected = np.array([
            [1, 0, 0],
            [0, np.cos(angle), -np.sin(angle)],
            [0, np.sin(angle),  np.cos(angle)]
        ], dtype=np.float64)

        np.testing.assert_allclose(
            R, R_expected, atol=1e-10,
            err_msg=f"Expected 15-deg x-rotation, got:\n{R}",
        )


# ---------------------------------------------------------------------------
# 6. Similarity alignment tests
# ---------------------------------------------------------------------------

class TestSimilarityAlignment:

    def test_identity_alignment(self):
        """Identical point clouds should produce identity transform."""
        rng = np.random.default_rng(42)
        pts = rng.standard_normal((15, 3))
        s, R, t = estimate_similarity_transform(pts, pts)
        assert abs(s - 1.0) < 1e-8, f"Scale should be 1.0, got {s}"
        np.testing.assert_allclose(R, np.eye(3), atol=1e-8,
            err_msg="Rotation should be identity")
        np.testing.assert_allclose(t, np.zeros(3), atol=1e-8,
            err_msg="Translation should be zero")

    def test_known_transform_recovery(self):
        """Should recover known scale, rotation, and translation exactly."""
        rng = np.random.default_rng(42)
        source = rng.standard_normal((20, 3))

        angle = np.radians(30)
        R_true = np.array([
            [np.cos(angle), -np.sin(angle), 0],
            [np.sin(angle),  np.cos(angle), 0],
            [0, 0, 1]
        ], dtype=np.float64)
        s_true = 2.5
        t_true = np.array([1.0, -2.0, 3.0])

        target = s_true * (R_true @ source.T).T + t_true

        s, R, t = estimate_similarity_transform(source, target)
        assert abs(s - s_true) < 1e-8, f"Scale: expected {s_true}, got {s}"
        np.testing.assert_allclose(R, R_true, atol=1e-8,
            err_msg="Rotation mismatch")
        np.testing.assert_allclose(t, t_true, atol=1e-8,
            err_msg="Translation mismatch")

    def test_arbitrary_rotation_and_scale(self):
        """Should handle arbitrary rotations and varying scale factors."""
        rng = np.random.default_rng(99)
        source = rng.standard_normal((30, 3))

        A = rng.standard_normal((3, 3))
        Q, _ = np.linalg.qr(A)
        if np.linalg.det(Q) < 0:
            Q[:, 0] *= -1
        R_true = Q

        s_true = 0.75
        t_true = np.array([-3.0, 2.0, 1.5])

        target = s_true * (R_true @ source.T).T + t_true

        s, R, t = estimate_similarity_transform(source, target)
        assert abs(s - s_true) < 1e-8, f"Scale: expected {s_true}, got {s}"
        np.testing.assert_allclose(R, R_true, atol=1e-8,
            err_msg="Rotation mismatch")
        np.testing.assert_allclose(t, t_true, atol=1e-8,
            err_msg="Translation mismatch")


# ---------------------------------------------------------------------------
# 7. Full pipeline tests
# ---------------------------------------------------------------------------

class TestFullPipeline:

    def _load_scene(self):
        """Load scene data from COLMAP files."""
        cameras, images, points_dict = load_scene('/app/data')
        gt_points = np.array([
            points_dict[pid]['xyz']
            for pid in sorted(points_dict.keys())
        ])
        return cameras, images, gt_points

    def test_reconstruction_via_depth(self):
        """Project 3D points to depth, unproject back, align, verify accuracy."""
        cameras, images, gt_points = self._load_scene()

        # Use camera 1 (identity rotation, zero translation)
        img = images[1]
        cam = cameras[img['camera_id']]
        intrinsic = cam['intrinsic']
        H, W = cam['height'], cam['width']

        ext = build_extrinsic_from_quat_trans(img['quat_xyzw'], img['translation'])

        # Forward: project 3D points to pixel coordinates + depths
        pixels, depths = project_points_to_camera(gt_points, ext, intrinsic)

        # Build depth map from projected points
        depth_map = np.zeros((H, W), dtype=np.float64)
        valid = []
        for i in range(len(gt_points)):
            u_px = int(round(pixels[i, 0]))
            v_px = int(round(pixels[i, 1]))
            if 0 <= u_px < W and 0 <= v_px < H and depths[i] > 0:
                depth_map[v_px, u_px] = depths[i]
                valid.append((i, u_px, v_px))

        assert len(valid) >= 5, f"Too few visible points: {len(valid)}"

        # Inverse: unproject depth map to world coordinates
        world_recovered, _, _ = depth_to_world_coords_points(depth_map, ext, intrinsic)

        # Extract recovered 3D points at the projected pixel locations
        rec_pts = np.array([world_recovered[v, u] for _, u, v in valid])
        gt_valid = np.array([gt_points[i] for i, _, _ in valid])

        # Align reconstructed points to ground truth and measure error
        rmse, s, R, t = compute_alignment_error(rec_pts, gt_valid)

        assert rmse < 0.01, (
            f"Reconstruction RMSE {rmse:.6f} exceeds threshold 0.01. "
            f"Scale={s:.4f}, det(R)={np.linalg.det(R):.4f}"
        )

    def test_cross_view_reprojection(self):
        """Unproject from cam1, reproject to cam2 — should match direct projection."""
        cameras, images, gt_points = self._load_scene()

        # Camera 1 (identity)
        img1 = images[1]
        cam1 = cameras[img1['camera_id']]
        intr1 = cam1['intrinsic']
        H, W = cam1['height'], cam1['width']
        ext1 = build_extrinsic_from_quat_trans(img1['quat_xyzw'], img1['translation'])

        # Camera 2 (15-degree x-rotation)
        img2 = images[2]
        intr2 = cameras[img2['camera_id']]['intrinsic']
        ext2 = build_extrinsic_from_quat_trans(img2['quat_xyzw'], img2['translation'])

        # Project ground truth to camera 1
        pixels1, depths1 = project_points_to_camera(gt_points, ext1, intr1)

        # Build depth map for camera 1
        depth_map = np.zeros((H, W), dtype=np.float64)
        valid = []
        for i in range(len(gt_points)):
            u = int(round(pixels1[i, 0]))
            v = int(round(pixels1[i, 1]))
            if 0 <= u < W and 0 <= v < H and depths1[i] > 0:
                depth_map[v, u] = depths1[i]
                valid.append((i, u, v))

        # Unproject to world coordinates using camera 1 parameters
        world_rec, _, _ = depth_to_world_coords_points(depth_map, ext1, intr1)

        # Direct projection to camera 2 (ground truth reference)
        pixels2_direct, _ = project_points_to_camera(gt_points, ext2, intr2)

        # Reproject recovered world points to camera 2
        for pt_idx, u, v in valid:
            rec_pt = world_rec[v, u]
            pixels2_reproj, _ = project_points_to_camera(
                rec_pt[np.newaxis], ext2, intr2
            )

            np.testing.assert_allclose(
                pixels2_reproj[0], pixels2_direct[pt_idx], atol=1.0,
                err_msg=(
                    f"Cross-view reprojection mismatch for point {pt_idx}: "
                    f"direct={pixels2_direct[pt_idx]}, reproj={pixels2_reproj[0]}"
                ),
            )


# ---------------------------------------------------------------------------
# 8. Robust alignment tests
# ---------------------------------------------------------------------------

class TestRobustAlignment:

    def test_known_transform_with_outliers(self):
        """RANSAC should recover the correct transform despite 25% outlier contamination."""
        rng = np.random.default_rng(42)
        n_clean = 30

        source_clean = rng.standard_normal((n_clean, 3))

        angle = np.radians(30)
        R_true = np.array([
            [np.cos(angle), -np.sin(angle), 0],
            [np.sin(angle),  np.cos(angle), 0],
            [0, 0, 1]
        ], dtype=np.float64)
        s_true = 2.5
        t_true = np.array([1.0, -2.0, 3.0])

        target_clean = s_true * (R_true @ source_clean.T).T + t_true

        # Add 10 outlier correspondences (random, non-matching)
        n_outlier = 10
        source_outliers = rng.uniform(-50, 50, (n_outlier, 3))
        target_outliers = rng.uniform(-50, 50, (n_outlier, 3))

        source = np.vstack([source_clean, source_outliers])
        target = np.vstack([target_clean, target_outliers])

        # Shuffle to mix inliers and outliers
        perm = rng.permutation(n_clean + n_outlier)
        source = source[perm]
        target = target[perm]

        s, R, t, inlier_mask = robust_estimate_similarity_transform(
            source, target, inlier_threshold=0.1
        )

        # Transform should be close to ground truth
        assert abs(s - s_true) < 0.3, f"Scale: expected {s_true}, got {s}"

        # RMSE on identified inliers should be low
        aligned = s * (R @ source[inlier_mask].T).T + t
        residuals = np.linalg.norm(aligned - target[inlier_mask], axis=1)
        rmse = np.sqrt(np.mean(residuals ** 2))
        assert rmse < 0.5, f"Inlier RMSE should be < 0.5, got {rmse}"

    def test_inlier_identification(self):
        """RANSAC should correctly distinguish inlier from outlier correspondences."""
        rng = np.random.default_rng(42)
        n_clean = 30
        n_outlier = 10

        source_clean = rng.standard_normal((n_clean, 3))
        R_true = _random_rotation_matrix(np.random.default_rng(99))
        s_true = 1.5
        t_true = np.array([2.0, -1.0, 0.5])
        target_clean = s_true * (R_true @ source_clean.T).T + t_true

        source_outliers = rng.uniform(-50, 50, (n_outlier, 3))
        target_outliers = rng.uniform(-50, 50, (n_outlier, 3))

        source = np.vstack([source_clean, source_outliers])
        target = np.vstack([target_clean, target_outliers])

        perm = rng.permutation(n_clean + n_outlier)
        source = source[perm]
        target = target[perm]

        # Track ground truth inlier status
        is_inlier_gt = np.zeros(n_clean + n_outlier, dtype=bool)
        is_inlier_gt[:n_clean] = True
        is_inlier_gt = is_inlier_gt[perm]

        _, _, _, inlier_mask = robust_estimate_similarity_transform(
            source, target, inlier_threshold=0.1
        )

        # Most true inliers should be identified
        true_positives = np.sum(inlier_mask & is_inlier_gt)
        assert true_positives >= 20, (
            f"At least 20 of {n_clean} true inliers should be found, got {true_positives}"
        )

        # Most outliers should be rejected
        false_positives = np.sum(inlier_mask & ~is_inlier_gt)
        assert false_positives <= 3, (
            f"At most 3 outliers should be misclassified as inliers, got {false_positives}"
        )

    def test_improvement_over_naive(self):
        """Robust alignment should dramatically outperform naive Umeyama on contaminated data."""
        rng = np.random.default_rng(42)
        source_clean = rng.standard_normal((20, 3))

        angle = np.radians(45)
        R_true = np.array([
            [np.cos(angle), -np.sin(angle), 0],
            [np.sin(angle),  np.cos(angle), 0],
            [0, 0, 1]
        ], dtype=np.float64)
        s_true = 2.0
        t_true = np.array([5.0, -3.0, 1.0])
        target_clean = s_true * (R_true @ source_clean.T).T + t_true

        source_outliers = rng.uniform(-100, 100, (8, 3))
        target_outliers = rng.uniform(-100, 100, (8, 3))

        source = np.vstack([source_clean, source_outliers])
        target = np.vstack([target_clean, target_outliers])

        # Naive alignment on contaminated data
        s_naive, R_naive, t_naive = estimate_similarity_transform(source, target)
        aligned_naive = s_naive * (R_naive @ source[:20].T).T + t_naive
        rmse_naive = np.sqrt(np.mean(np.linalg.norm(
            aligned_naive - target[:20], axis=1
        ) ** 2))

        # Robust alignment on contaminated data
        s_robust, R_robust, t_robust, _ = robust_estimate_similarity_transform(
            source, target, inlier_threshold=0.1
        )
        aligned_robust = s_robust * (R_robust @ source[:20].T).T + t_robust
        rmse_robust = np.sqrt(np.mean(np.linalg.norm(
            aligned_robust - target[:20], axis=1
        ) ** 2))

        assert rmse_robust < rmse_naive, (
            f"Robust RMSE ({rmse_robust:.4f}) should be less than naive ({rmse_naive:.4f})"
        )
        assert rmse_robust < 0.5, f"Robust RMSE should be < 0.5, got {rmse_robust}"


# ---------------------------------------------------------------------------
# 9. Results database tests
# ---------------------------------------------------------------------------

class TestResultsDatabase:

    def test_database_exists(self):
        """SQLite results database should exist at /app/results.db."""
        assert os.path.exists('/app/results.db'), "Database /app/results.db not found"

    def test_clean_scene_metrics(self):
        """Clean scene should have near-perfect reconstruction quality."""
        conn = sqlite3.connect('/app/results.db')
        cursor = conn.execute(
            "SELECT num_points, num_inliers, inlier_ratio, rmse, scale "
            "FROM quality_metrics WHERE scene_name='clean'"
        )
        row = cursor.fetchone()
        conn.close()

        assert row is not None, "No 'clean' row in quality_metrics"
        num_points, num_inliers, inlier_ratio, rmse, scale = row

        assert num_points >= 8, f"Expected >= 8 points, got {num_points}"
        assert inlier_ratio > 0.9, f"Clean inlier ratio should be > 0.9, got {inlier_ratio}"
        assert rmse < 0.05, f"Clean RMSE should be < 0.05, got {rmse}"
        assert abs(scale - 1.0) < 0.1, f"Clean scale should be ~1.0, got {scale}"

    def test_noisy_scene_metrics(self):
        """Noisy scene should show outlier rejection with reasonable metrics."""
        conn = sqlite3.connect('/app/results.db')
        cursor = conn.execute(
            "SELECT num_points, num_inliers, inlier_ratio, rmse, scale "
            "FROM quality_metrics WHERE scene_name='noisy'"
        )
        row = cursor.fetchone()
        conn.close()

        assert row is not None, "No 'noisy' row in quality_metrics"
        num_points, num_inliers, inlier_ratio, rmse, scale = row

        assert num_points >= 8, f"Expected >= 8 points, got {num_points}"
        assert 0.5 < inlier_ratio < 0.85, (
            f"Noisy inlier ratio should be 0.5-0.85 (expect ~0.7), got {inlier_ratio}"
        )
        assert rmse < 0.1, f"Noisy inlier RMSE should be < 0.1, got {rmse}"
        assert abs(scale - 1.0) < 0.2, f"Noisy scale should be ~1.0, got {scale}"

    def test_clean_point_classifications(self):
        """All clean scene points should be classified as inliers with low residuals."""
        conn = sqlite3.connect('/app/results.db')
        cursor = conn.execute(
            "SELECT COUNT(*) FROM point_classifications "
            "WHERE scene_name='clean' AND is_inlier=1"
        )
        inlier_count = cursor.fetchone()[0]

        cursor = conn.execute(
            "SELECT MAX(residual) FROM point_classifications "
            "WHERE scene_name='clean'"
        )
        max_residual = cursor.fetchone()[0]
        conn.close()

        assert inlier_count >= 8, (
            f"Most clean points should be inliers, got {inlier_count}"
        )
        assert max_residual is not None and max_residual < 0.1, (
            f"Clean scene max residual should be < 0.1, got {max_residual}"
        )

    def test_noisy_point_classifications(self):
        """Corrupted points (IDs 8, 9, 10) should be identified as outliers."""
        conn = sqlite3.connect('/app/results.db')

        for point_id in [8, 9, 10]:
            cursor = conn.execute(
                "SELECT is_inlier, residual FROM point_classifications "
                "WHERE scene_name='noisy' AND point_id=?",
                (point_id,)
            )
            row = cursor.fetchone()
            assert row is not None, (
                f"Point {point_id} missing from noisy scene classifications"
            )
            is_inlier, residual = row
            assert is_inlier == 0, (
                f"Point {point_id} should be outlier (is_inlier=0), got {is_inlier}"
            )
            assert residual > 50.0, (
                f"Point {point_id} residual should be > 50, got {residual}"
            )

        # At least 5 of points 1-7 should be inliers
        cursor = conn.execute(
            "SELECT COUNT(*) FROM point_classifications "
            "WHERE scene_name='noisy' AND point_id <= 7 AND is_inlier=1"
        )
        inlier_count = cursor.fetchone()[0]
        conn.close()

        assert inlier_count >= 5, (
            f"At least 5 of points 1-7 should be inliers, got {inlier_count}"
        )


# ---------------------------------------------------------------------------
# 10. PLY point cloud export tests
# ---------------------------------------------------------------------------

def _parse_ply_header(filepath):
    """Parse a PLY file header and return metadata."""
    with open(filepath, 'rb') as f:
        lines = []
        while True:
            line = f.readline()
            if not line:
                raise ValueError("Unexpected end of file before end_header")
            line_str = line.decode('ascii').strip()
            lines.append(line_str)
            if line_str == 'end_header':
                break
        data_offset = f.tell()

    fmt = None
    vertex_count = 0
    properties = []

    for line in lines:
        if line.startswith('format '):
            fmt = line.split()[1]
        elif line.startswith('element vertex '):
            vertex_count = int(line.split()[-1])
        elif line.startswith('property '):
            parts = line.split()
            properties.append(parts[-1])  # property name is last token

    return {
        'format': fmt,
        'vertex_count': vertex_count,
        'properties': properties,
        'data_offset': data_offset,
    }


class TestPlyExport:

    def test_clean_ply_valid(self):
        """Clean reconstruction PLY should be valid binary little-endian with correct properties."""
        path = '/app/output/clean.ply'
        assert os.path.exists(path), f"{path} not found"
        meta = _parse_ply_header(path)
        assert meta['format'] == 'binary_little_endian', (
            f"Expected binary_little_endian format, got {meta['format']}"
        )
        required_props = {'x', 'y', 'z', 'red', 'green', 'blue', 'residual', 'is_inlier'}
        actual_props = set(meta['properties'])
        assert required_props.issubset(actual_props), (
            f"Missing vertex properties: {required_props - actual_props}"
        )
        assert meta['vertex_count'] >= 8, (
            f"Expected >= 8 vertices in clean PLY, got {meta['vertex_count']}"
        )
        # Verify file has binary data after header
        file_size = os.path.getsize(path)
        assert file_size > meta['data_offset'], (
            f"PLY file has no binary data after header"
        )

    def test_noisy_ply_inliers_only(self):
        """Noisy inliers PLY should have fewer vertices than total points (outliers excluded)."""
        path = '/app/output/noisy_inliers.ply'
        assert os.path.exists(path), f"{path} not found"
        meta = _parse_ply_header(path)
        assert meta['format'] == 'binary_little_endian', (
            f"Expected binary_little_endian format, got {meta['format']}"
        )
        assert meta['vertex_count'] < 10, (
            f"Expected < 10 vertices (outliers excluded), got {meta['vertex_count']}"
        )
        assert meta['vertex_count'] >= 5, (
            f"Expected >= 5 inlier vertices, got {meta['vertex_count']}"
        )


# ---------------------------------------------------------------------------
# 11. jq-extracted JSON output tests
# ---------------------------------------------------------------------------

class TestJqOutput:

    def test_outlier_ids(self):
        """jq-extracted outlier IDs should identify corrupted points 8, 9, 10."""
        path = '/app/output/outlier_ids.json'
        assert os.path.exists(path), f"{path} not found"
        with open(path) as f:
            outlier_ids = json.load(f)
        assert isinstance(outlier_ids, list), (
            f"outlier_ids.json should be a JSON array, got {type(outlier_ids).__name__}"
        )
        for pid in [8, 9, 10]:
            assert pid in outlier_ids, (
                f"Point {pid} should be in outlier list, got {outlier_ids}"
            )

    def test_metrics_summary(self):
        """jq-extracted metrics summary should have correct structure and reasonable values."""
        path = '/app/output/metrics_summary.json'
        assert os.path.exists(path), f"{path} not found"
        with open(path) as f:
            summary = json.load(f)
        assert isinstance(summary, dict), (
            f"metrics_summary.json should be a JSON object, got {type(summary).__name__}"
        )
        for key in ['clean_rmse', 'noisy_rmse', 'noisy_inlier_ratio']:
            assert key in summary, f"Missing key '{key}' in metrics_summary.json"
        assert summary['clean_rmse'] < 0.05, (
            f"clean_rmse should be < 0.05, got {summary['clean_rmse']}"
        )
        assert 0.5 < summary['noisy_inlier_ratio'] < 0.85, (
            f"noisy_inlier_ratio should be 0.5-0.85, got {summary['noisy_inlier_ratio']}"
        )


# ---------------------------------------------------------------------------
# 12. sqlite3 CLI output tests
# ---------------------------------------------------------------------------

class TestSqliteCliOutput:

    def test_outlier_analysis_view(self):
        """Database should have outlier_analysis view with correct schema and data."""
        conn = sqlite3.connect('/app/results.db')
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name='outlier_analysis'"
        )
        row = cursor.fetchone()
        assert row is not None, "View 'outlier_analysis' not found in database"

        cursor = conn.execute("SELECT * FROM outlier_analysis ORDER BY scene_name")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 2, (
            f"outlier_analysis view should have 2 rows (clean, noisy), got {len(rows)}"
        )

    def test_csv_export(self):
        """Outlier report CSV should exist with headers and data rows."""
        path = '/app/output/outlier_report.csv'
        assert os.path.exists(path), f"{path} not found"
        with open(path) as f:
            content = f.read().strip()
        lines = content.split('\n')
        assert len(lines) >= 3, (
            f"CSV should have header + 2 data rows, got {len(lines)} lines"
        )
        # Header should contain expected column names
        header = lines[0].lower()
        assert 'scene_name' in header, (
            f"CSV header should contain 'scene_name', got: {lines[0]}"
        )
