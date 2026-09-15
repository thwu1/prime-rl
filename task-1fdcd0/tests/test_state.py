
import pytest
import json
import numpy as np
import os
import subprocess
import shutil


# ---------------------------------------------------------------------------
# Ground truth generation helpers (mirrors generate_data.py exactly)
# ---------------------------------------------------------------------------

def _rotation_z(angle):
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _make_pose(R, t):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def _skew(v):
    return np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])


def _exp_so3(omega):
    theta = np.linalg.norm(omega)
    if theta < 1e-10:
        return np.eye(3) + _skew(omega)
    K = _skew(omega / theta)
    return np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * K @ K


def _add_noise_to_pose(T, trans_std, rot_std, rng):
    noise_trans = rng.normal(0, trans_std, 3)
    noise_rot = rng.normal(0, rot_std, 3)
    T_noisy = T.copy()
    T_noisy[:3, :3] = _exp_so3(noise_rot) @ T[:3, :3]
    T_noisy[:3, 3] = T[:3, 3] + noise_trans
    return T_noisy


def _inv_pose(T):
    T_inv = np.eye(4)
    T_inv[:3, :3] = T[:3, :3].T
    T_inv[:3, 3] = -T[:3, :3].T @ T[:3, 3]
    return T_inv


def _rot_to_quat(R):
    """3x3 rotation matrix to quaternion (qx, qy, qz, qw) scalar-last."""
    tr = R[0, 0] + R[1, 1] + R[2, 2]
    if tr > 0:
        s = 2.0 * np.sqrt(tr + 1.0)
        qw = 0.25 * s
        qx = (R[2, 1] - R[1, 2]) / s
        qy = (R[0, 2] - R[2, 0]) / s
        qz = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        qw = (R[2, 1] - R[1, 2]) / s
        qx = 0.25 * s
        qy = (R[0, 1] + R[1, 0]) / s
        qz = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        qw = (R[0, 2] - R[2, 0]) / s
        qx = (R[0, 1] + R[1, 0]) / s
        qy = 0.25 * s
        qz = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        qw = (R[1, 0] - R[0, 1]) / s
        qx = (R[0, 2] + R[2, 0]) / s
        qy = (R[1, 2] + R[2, 1]) / s
        qz = 0.25 * s
    return qx, qy, qz, qw


def _rotation_error(R1, R2):
    R_err = R1.T @ R2
    cos_angle = np.clip((np.trace(R_err) - 1) / 2, -1, 1)
    return np.arccos(cos_angle)


def generate_pose_graph_and_gt(seed=42):
    """Generate pose graph and return (gt_poses, outlier_edge_indices).
    Also writes g2o file to /app/data/trajectory.g2o when called for generalization test."""
    rng = np.random.RandomState(seed)

    gt_poses = []
    for i in range(5):
        gt_poses.append(_make_pose(_rotation_z(0), np.array([i * 3.0, 0.0, 0.0])))
    for i in range(4):
        gt_poses.append(_make_pose(_rotation_z(np.pi / 2), np.array([12.0, (i + 1) * 3.0, 0.0])))
    for i in range(4):
        gt_poses.append(_make_pose(_rotation_z(np.pi), np.array([12.0 - (i + 1) * 3.0, 12.0, 0.0])))
    for i in range(3):
        gt_poses.append(_make_pose(_rotation_z(3 * np.pi / 2), np.array([0.0, 12.0 - (i + 1) * 3.0, 0.0])))

    info_odom_rt = np.diag([2500.0, 2500.0, 2500.0, 400.0, 400.0, 400.0])
    info_lc_rt = np.diag([4000.0, 4000.0, 4000.0, 600.0, 600.0, 600.0])

    edges = []
    for i in range(15):
        T_rel = _inv_pose(gt_poses[i]) @ gt_poses[i + 1]
        T_meas = _add_noise_to_pose(T_rel, 0.05, 0.015, rng)
        edges.append({"from": i, "to": i + 1, "measurement": T_meas, "information": info_odom_rt})

    T_rel = _inv_pose(gt_poses[15]) @ gt_poses[0]
    T_meas = _add_noise_to_pose(T_rel, 0.03, 0.01, rng)
    edges.append({"from": 15, "to": 0, "measurement": T_meas, "information": info_lc_rt})

    T_rel = _inv_pose(gt_poses[14]) @ gt_poses[1]
    T_meas = _add_noise_to_pose(T_rel, 0.03, 0.01, rng)
    edges.append({"from": 14, "to": 1, "measurement": T_meas, "information": info_lc_rt})

    T_wrong = _make_pose(_exp_so3(rng.normal(0, 0.5, 3)), rng.normal(0, 2.0, 3))
    edges.append({"from": 3, "to": 10, "measurement": T_wrong, "information": info_lc_rt})

    T_wrong = _make_pose(_exp_so3(rng.normal(0, 0.5, 3)), rng.normal(0, 2.0, 3))
    edges.append({"from": 6, "to": 13, "measurement": T_wrong, "information": info_lc_rt})

    return gt_poses, [17, 18], edges


def write_g2o_for_test(filepath, gt_poses, edges):
    """Write pose graph in g2o format for the generalization test."""
    # Compute dead-reckoning initial estimates
    initial_estimates = [gt_poses[0].copy()]
    current_pose = gt_poses[0].copy()
    for i in range(15):
        current_pose = current_pose @ edges[i]["measurement"]
        initial_estimates.append(current_pose.copy())

    perm = [3, 4, 5, 0, 1, 2]
    with open(filepath, "w") as f:
        for idx, pose in enumerate(initial_estimates):
            x, y, z = pose[0, 3], pose[1, 3], pose[2, 3]
            qx, qy, qz, qw = _rot_to_quat(pose[:3, :3])
            f.write(f"VERTEX_SE3:QUAT {idx} {x:.10f} {y:.10f} {z:.10f} "
                    f"{qx:.10f} {qy:.10f} {qz:.10f} {qw:.10f}\n")
        f.write("FIX 0\n")
        for edge in edges:
            meas = edge["measurement"]
            x, y, z = meas[0, 3], meas[1, 3], meas[2, 3]
            qx, qy, qz, qw = _rot_to_quat(meas[:3, :3])
            info_rt = edge["information"]
            info_tr = info_rt[np.ix_(perm, perm)]
            vals = []
            for i in range(6):
                for j in range(i, 6):
                    vals.append(info_tr[i, j])
            info_str = " ".join(f"{v:.6f}" for v in vals)
            f.write(f"EDGE_SE3:QUAT {edge['from']} {edge['to']} "
                    f"{x:.10f} {y:.10f} {z:.10f} "
                    f"{qx:.10f} {qy:.10f} {qz:.10f} {qw:.10f} "
                    f"{info_str}\n")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPoseGraphOptimization:

    def test_output_files_exist(self):
        assert os.path.isfile("/app/output/poses.json"), \
            "/app/output/poses.json not found"
        assert os.path.isfile("/app/output/outliers.json"), \
            "/app/output/outliers.json not found"
        assert os.path.isfile("/app/output/optimized.g2o"), \
            "/app/output/optimized.g2o not found"
        assert os.path.isfile("/app/output/trajectory.png"), \
            "/app/output/trajectory.png not found"

    def test_output_format_poses(self):
        with open("/app/output/poses.json") as f:
            poses = json.load(f)
        assert isinstance(poses, list), "poses.json must be a JSON list"
        assert len(poses) == 16, f"Expected 16 poses, got {len(poses)}"
        for p in poses:
            assert "id" in p and "pose" in p, "Each entry needs 'id' and 'pose'"
            pose = np.array(p["pose"])
            assert pose.shape == (4, 4), f"Pose {p['id']}: shape {pose.shape}, expected (4,4)"
            R = pose[:3, :3]
            det = np.linalg.det(R)
            assert abs(det - 1.0) < 0.05, \
                f"Pose {p['id']}: det(R)={det:.4f}, must be ~1.0"
            assert np.allclose(R @ R.T, np.eye(3), atol=0.05), \
                f"Pose {p['id']}: R is not orthogonal"

    def test_output_format_outliers(self):
        with open("/app/output/outliers.json") as f:
            outliers = json.load(f)
        assert isinstance(outliers, list), "outliers.json must be a JSON list"
        for o in outliers:
            assert "edge_index" in o, "Each outlier must have 'edge_index'"
            assert "from" in o, "Each outlier must have 'from'"
            assert "to" in o, "Each outlier must have 'to'"

    def test_g2o_output(self):
        assert os.path.isfile("/app/output/optimized.g2o"), \
            "/app/output/optimized.g2o not found"

        vertex_count = 0
        edge_count = 0
        fix_count = 0

        with open("/app/output/optimized.g2o") as f:
            for line in f:
                parts = line.strip().split()
                if not parts:
                    continue
                if parts[0] == 'VERTEX_SE3:QUAT':
                    vertex_count += 1
                    assert len(parts) == 9, \
                        f"VERTEX_SE3:QUAT line should have 9 fields, got {len(parts)}"
                    qx = float(parts[5])
                    qy = float(parts[6])
                    qz = float(parts[7])
                    qw = float(parts[8])
                    qnorm = (qx**2 + qy**2 + qz**2 + qw**2) ** 0.5
                    assert abs(qnorm - 1.0) < 0.01, \
                        f"Vertex {parts[1]}: quaternion norm {qnorm:.4f}, expected ~1.0"
                elif parts[0] == 'EDGE_SE3:QUAT':
                    edge_count += 1
                    assert len(parts) == 31, \
                        f"EDGE_SE3:QUAT line should have 31 fields, got {len(parts)}"
                elif parts[0] == 'FIX':
                    fix_count += 1

        assert vertex_count == 16, f"Expected 16 vertices, got {vertex_count}"
        assert edge_count == 19, f"Expected 19 edges, got {edge_count}"
        assert fix_count >= 1, "No FIX line found in optimized.g2o"

    def test_trajectory_plot(self):
        assert os.path.isfile("/app/output/trajectory.png"), \
            "/app/output/trajectory.png not found"
        fsize = os.path.getsize("/app/output/trajectory.png")
        assert fsize >= 1000, \
            f"trajectory.png too small ({fsize} bytes), expected >= 1000"
        with open("/app/output/trajectory.png", "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', \
            "trajectory.png does not have valid PNG header"

    def test_fixed_pose(self):
        gt_poses, _, _ = generate_pose_graph_and_gt(seed=42)
        with open("/app/output/poses.json") as f:
            est_poses = json.load(f)
        pose_0 = None
        for ep in est_poses:
            if ep["id"] == 0:
                pose_0 = np.array(ep["pose"])
                break
        assert pose_0 is not None, "Pose 0 not found in output"
        assert np.allclose(pose_0, gt_poses[0], atol=1e-4), \
            "Pose 0 (anchor) must remain fixed"

    def test_pose_accuracy(self):
        gt_poses, _, _ = generate_pose_graph_and_gt(seed=42)
        with open("/app/output/poses.json") as f:
            est_poses = json.load(f)

        trans_errors = []
        rot_errors = []
        for ep in est_poses:
            i = ep["id"]
            T_est = np.array(ep["pose"])
            T_gt = gt_poses[i]
            trans_errors.append(np.linalg.norm(T_est[:3, 3] - T_gt[:3, 3]))
            rot_errors.append(_rotation_error(T_est[:3, :3], T_gt[:3, :3]))

        avg_trans = np.mean(trans_errors)
        max_trans = np.max(trans_errors)
        avg_rot = np.mean(rot_errors)
        max_rot = np.max(rot_errors)

        assert max_trans < 0.5, \
            f"Max translation error {max_trans:.3f}m exceeds 0.5m"
        assert avg_trans < 0.2, \
            f"Avg translation error {avg_trans:.3f}m exceeds 0.2m"
        assert max_rot < np.radians(5), \
            f"Max rotation error {np.degrees(max_rot):.1f} deg exceeds 5 deg"
        assert avg_rot < np.radians(2), \
            f"Avg rotation error {np.degrees(avg_rot):.1f} deg exceeds 2 deg"

    def test_outlier_detection(self):
        _, true_outlier_indices, _ = generate_pose_graph_and_gt(seed=42)
        with open("/app/output/outliers.json") as f:
            detected = json.load(f)

        detected_indices = set(o["edge_index"] for o in detected)
        true_indices = set(true_outlier_indices)

        missed = true_indices - detected_indices
        assert len(missed) == 0, f"Failed to detect outlier edges: {missed}"

        false_pos = detected_indices - true_indices
        assert len(false_pos) <= 1, \
            f"Too many false-positive outliers ({len(false_pos)}): {false_pos}"

    def test_loop_closure_consistency(self):
        gt_poses, _, _ = generate_pose_graph_and_gt(seed=42)
        with open("/app/output/poses.json") as f:
            est_poses = json.load(f)

        pose_map = {ep["id"]: np.array(ep["pose"]) for ep in est_poses}
        expected_dist = np.linalg.norm(gt_poses[15][:3, 3] - gt_poses[0][:3, 3])
        actual_dist = np.linalg.norm(pose_map[15][:3, 3] - pose_map[0][:3, 3])

        assert abs(actual_dist - expected_dist) < 0.5, \
            f"Loop closure inconsistency: expected ~{expected_dist:.1f}m gap, got {actual_dist:.1f}m"

    def test_generalization(self):
        """Run optimizer on a second dataset to verify it is not hardcoded."""
        gt2, outlier_indices2, edges2 = generate_pose_graph_and_gt(seed=123)

        # Overwrite dataset with new g2o file
        write_g2o_for_test("/app/data/trajectory.g2o", gt2, edges2)

        # Clean output
        if os.path.exists("/app/output"):
            shutil.rmtree("/app/output")
        os.makedirs("/app/output")

        # Run optimizer
        result = subprocess.run(
            ["python3", "/app/optimize.py"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, \
            f"Optimizer failed on second dataset:\nstdout: {result.stdout[-500:]}\nstderr: {result.stderr[-500:]}"

        assert os.path.isfile("/app/output/poses.json"), \
            "poses.json missing for second dataset"
        assert os.path.isfile("/app/output/outliers.json"), \
            "outliers.json missing for second dataset"

        with open("/app/output/poses.json") as f:
            est_poses = json.load(f)

        # Accuracy check (relaxed thresholds)
        trans_errors = []
        for ep in est_poses:
            i = ep["id"]
            T_est = np.array(ep["pose"])
            T_gt = gt2[i]
            trans_errors.append(np.linalg.norm(T_est[:3, 3] - T_gt[:3, 3]))

        avg_trans = np.mean(trans_errors)
        max_trans = np.max(trans_errors)
        assert max_trans < 0.7, \
            f"Second dataset: max translation error {max_trans:.3f}m exceeds 0.7m"
        assert avg_trans < 0.3, \
            f"Second dataset: avg translation error {avg_trans:.3f}m exceeds 0.3m"

        # Outlier detection check
        with open("/app/output/outliers.json") as f:
            detected = json.load(f)
        detected_indices = set(o["edge_index"] for o in detected)
        true_indices = set(outlier_indices2)
        missed = true_indices - detected_indices
        assert len(missed) == 0, \
            f"Second dataset: missed outlier edges {missed}"
