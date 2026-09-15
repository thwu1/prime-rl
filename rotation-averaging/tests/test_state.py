"""Tests for the rotation averaging solver."""

import json
import os
import shutil
import subprocess

import numpy as np
import pytest
from scipy.spatial.transform import Rotation


# ---------------------------------------------------------------------------
# Ground-truth generation (embedded; NOT available to solver at /app/)
# ---------------------------------------------------------------------------

def _generate_pose_graph(seed):
    """Deterministically generate a pose graph with inlier/outlier edges."""
    rng = np.random.default_rng(seed)
    num_cameras = 25

    gt_rotations = [Rotation.random(random_state=rng).as_matrix()
                    for _ in range(num_cameras)]

    def _gdist(R1, R2):
        cos_a = np.clip((np.trace(R1.T @ R2) - 1) / 2, -1.0, 1.0)
        return float(np.arccos(cos_a))

    k = 6
    edge_set = set()
    for i in range(num_cameras):
        dists = sorted((_gdist(gt_rotations[i], gt_rotations[j]), j)
                       for j in range(num_cameras) if j != i)
        for _, j in dists[:k]:
            edge_set.add((min(i, j), max(i, j)))

    for _ in range(20):
        i, j = int(rng.integers(0, num_cameras)), int(rng.integers(0, num_cameras))
        if i != j:
            edge_set.add((min(i, j), max(i, j)))

    noise_std = 0.008
    edges, edge_is_outlier = [], []
    for i, j in sorted(edge_set):
        R_ij_gt = gt_rotations[j] @ gt_rotations[i].T
        R_noise = Rotation.from_rotvec(rng.normal(0, noise_std, size=3)).as_matrix()
        R_ij = R_noise @ R_ij_gt
        dist = _gdist(gt_rotations[i], gt_rotations[j])
        weight = float(np.clip(1.0 - 0.3 * dist, 0.3, 1.0))
        edges.append({"i": int(i), "j": int(j),
                       "R_ij": R_ij.tolist(), "weight": round(weight, 4)})
        edge_is_outlier.append(False)

    for _ in range(15):
        i = int(rng.integers(0, num_cameras))
        j = int(rng.integers(0, num_cameras))
        while i == j:
            j = int(rng.integers(0, num_cameras))
        i, j = min(i, j), max(i, j)
        R_random = Rotation.random(random_state=rng).as_matrix()
        weight = float(round(rng.uniform(0.15, 0.45), 4))
        edges.append({"i": i, "j": j,
                       "R_ij": R_random.tolist(), "weight": weight})
        edge_is_outlier.append(True)

    pose_graph = {"num_cameras": num_cameras, "edges": edges}
    ground_truth = {"rotations": [R.tolist() for R in gt_rotations],
                    "edge_is_outlier": edge_is_outlier}
    return pose_graph, ground_truth


# ---------------------------------------------------------------------------
# Geometric helpers
# ---------------------------------------------------------------------------

def align_rotations_right_procrustes(R_est_list, R_gt_list):
    """Find G minimizing sum ||R_gt[i] - R_est[i] @ G||_F^2."""
    M = np.zeros((3, 3))
    for R_e, R_g in zip(R_est_list, R_gt_list):
        M += R_e.T @ R_g
    U, _, Vt = np.linalg.svd(M)
    d = np.linalg.det(U @ Vt)
    return U @ np.diag([1.0, 1.0, d]) @ Vt


def geodesic_distance(R1, R2):
    """Geodesic distance between two SO(3) elements in radians."""
    cos_a = np.clip((np.trace(R1.T @ R2) - 1) / 2, -1.0, 1.0)
    return float(np.arccos(cos_a))


# ---------------------------------------------------------------------------
# Fixtures for the PRIMARY graph (seed=42, the one shipped in the image)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ground_truth():
    _, gt = _generate_pose_graph(seed=42)
    return gt


@pytest.fixture(scope="module")
def pose_graph_data():
    pg, _ = _generate_pose_graph(seed=42)
    return pg


@pytest.fixture(scope="module")
def solver_output():
    solver_path = "/app/solver.py"
    assert os.path.exists(solver_path), (
        f"Solver not found at {solver_path}. "
        "Create /app/solver.py that reads /app/pose_graph.json "
        "and writes /app/output/results.json."
    )

    result = subprocess.run(
        ["python3", solver_path],
        capture_output=True,
        text=True,
        timeout=180,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Solver exited with code {result.returncode}.\n"
        f"stderr (last 800 chars): {result.stderr[-800:]}"
    )

    output_path = "/app/output/results.json"
    assert os.path.exists(output_path), (
        f"Output file {output_path} not found after running solver."
    )

    with open(output_path) as f:
        data = json.load(f)
    return data


# ---------------------------------------------------------------------------
# Output format checks
# ---------------------------------------------------------------------------
class TestOutputFormat:
    def test_has_rotations_key(self, solver_output):
        assert "rotations" in solver_output, "Missing 'rotations' key in output"

    def test_has_outlier_edges_key(self, solver_output):
        assert "outlier_edges" in solver_output, "Missing 'outlier_edges' key"

    def test_all_cameras_present(self, solver_output, ground_truth):
        n = len(ground_truth["rotations"])
        for i in range(n):
            assert str(i) in solver_output["rotations"], (
                f"Camera {i} missing from rotations output"
            )

    def test_rotation_shapes(self, solver_output, ground_truth):
        for key, R_list in solver_output["rotations"].items():
            R = np.array(R_list)
            assert R.shape == (3, 3), (
                f"Camera {key}: rotation shape {R.shape} != (3, 3)"
            )

    def test_outlier_edges_format(self, solver_output):
        for pair in solver_output["outlier_edges"]:
            assert len(pair) == 2, f"Outlier edge {pair} should have 2 elements"
            assert isinstance(pair[0], (int, float))
            assert isinstance(pair[1], (int, float))


# ---------------------------------------------------------------------------
# Rotation validity (SO(3) membership)
# ---------------------------------------------------------------------------
class TestRotationValidity:
    def test_orthogonality(self, solver_output):
        for key, R_list in solver_output["rotations"].items():
            R = np.array(R_list, dtype=np.float64)
            np.testing.assert_allclose(
                R @ R.T,
                np.eye(3),
                atol=1e-3,
                err_msg=f"Camera {key}: R @ R^T != I",
            )

    def test_determinant_positive_one(self, solver_output):
        for key, R_list in solver_output["rotations"].items():
            R = np.array(R_list, dtype=np.float64)
            det = np.linalg.det(R)
            assert abs(det - 1.0) < 1e-3, (
                f"Camera {key}: det(R) = {det:.6f}, expected 1.0"
            )


# ---------------------------------------------------------------------------
# Rotation accuracy (after Procrustes alignment)
# ---------------------------------------------------------------------------
class TestRotationAccuracy:
    def _aligned_errors_deg(self, solver_output, ground_truth):
        gt_rots = [np.array(R) for R in ground_truth["rotations"]]
        est_rots = [
            np.array(solver_output["rotations"][str(i)])
            for i in range(len(gt_rots))
        ]
        G = align_rotations_right_procrustes(est_rots, gt_rots)
        aligned = [R @ G for R in est_rots]
        return [
            np.degrees(geodesic_distance(gt_rots[i], aligned[i]))
            for i in range(len(gt_rots))
        ]

    def test_mean_angular_error_below_2_deg(self, solver_output, ground_truth):
        errors = self._aligned_errors_deg(solver_output, ground_truth)
        mean_err = float(np.mean(errors))
        assert mean_err < 2.0, (
            f"Mean angular error {mean_err:.3f}° >= 2.0°"
        )

    def test_max_angular_error_below_5_deg(self, solver_output, ground_truth):
        errors = self._aligned_errors_deg(solver_output, ground_truth)
        max_err = float(max(errors))
        assert max_err < 5.0, (
            f"Max angular error {max_err:.3f}° >= 5.0°"
        )


# ---------------------------------------------------------------------------
# Outlier detection quality
# ---------------------------------------------------------------------------
class TestOutlierDetection:
    def _outlier_sets(self, solver_output, ground_truth, pose_graph_data):
        edges = pose_graph_data["edges"]
        true_outliers = set()
        for k, is_out in enumerate(ground_truth["edge_is_outlier"]):
            if is_out:
                i, j = edges[k]["i"], edges[k]["j"]
                true_outliers.add((min(i, j), max(i, j)))

        detected = set()
        for pair in solver_output["outlier_edges"]:
            i, j = int(pair[0]), int(pair[1])
            detected.add((min(i, j), max(i, j)))

        return true_outliers, detected

    def test_outlier_recall_above_60pct(
        self, solver_output, ground_truth, pose_graph_data
    ):
        """At least 60% of true outlier edges must be detected."""
        true_out, detected = self._outlier_sets(
            solver_output, ground_truth, pose_graph_data
        )
        if not true_out:
            return
        tp = len(true_out & detected)
        recall = tp / len(true_out)
        assert recall >= 0.6, (
            f"Outlier recall {recall:.2f} < 0.6 "
            f"({tp}/{len(true_out)} true outliers detected)"
        )

    def test_outlier_precision_above_60pct(
        self, solver_output, ground_truth, pose_graph_data
    ):
        """At least 60% of detected outlier edges must be true outliers."""
        true_out, detected = self._outlier_sets(
            solver_output, ground_truth, pose_graph_data
        )
        if not detected:
            pytest.skip("No outliers detected — cannot compute precision")
        tp = len(true_out & detected)
        precision = tp / len(detected)
        assert precision >= 0.6, (
            f"Outlier precision {precision:.2f} < 0.6 "
            f"({tp}/{len(detected)} detections are true outliers)"
        )


# ---------------------------------------------------------------------------
# Anti-cheat: solver must generalise to a fresh pose graph
# ---------------------------------------------------------------------------
class TestGeneralizesToNewGraph:
    """Verify the solver produces correct results on an unseen pose graph."""

    def test_solver_accuracy_on_new_graph(self):
        pg, gt = _generate_pose_graph(seed=99)

        # Overwrite the input with a fresh graph
        with open("/app/pose_graph.json", "w") as f:
            json.dump(pg, f, indent=2)
        shutil.rmtree("/app/output", ignore_errors=True)

        result = subprocess.run(
            ["python3", "/app/solver.py"],
            capture_output=True,
            text=True,
            timeout=180,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"Solver failed on new graph (exit {result.returncode}): "
            f"{result.stderr[-500:]}"
        )
        assert os.path.exists("/app/output/results.json"), (
            "results.json not created for new graph"
        )
        with open("/app/output/results.json") as f:
            data = json.load(f)

        n = pg["num_cameras"]
        assert "rotations" in data
        assert "outlier_edges" in data

        # All cameras present with valid SO(3) rotations
        for i in range(n):
            assert str(i) in data["rotations"], f"Camera {i} missing"
            R = np.array(data["rotations"][str(i)], dtype=np.float64)
            assert R.shape == (3, 3)
            assert abs(np.linalg.det(R) - 1.0) < 1e-3

        # Accuracy after Procrustes alignment
        gt_rots = [np.array(R) for R in gt["rotations"]]
        est_rots = [np.array(data["rotations"][str(i)]) for i in range(n)]
        G = align_rotations_right_procrustes(est_rots, gt_rots)
        aligned = [R @ G for R in est_rots]
        errors = [np.degrees(geodesic_distance(gt_rots[i], aligned[i]))
                  for i in range(n)]

        mean_err = float(np.mean(errors))
        max_err = float(max(errors))
        assert mean_err < 2.0, (
            f"Mean angular error {mean_err:.2f}° on new graph (seed=99)"
        )
        assert max_err < 5.0, (
            f"Max angular error {max_err:.2f}° on new graph (seed=99)"
        )

        # Outlier detection quality
        edges = pg["edges"]
        true_outliers = set()
        for k, is_out in enumerate(gt["edge_is_outlier"]):
            if is_out:
                i, j = edges[k]["i"], edges[k]["j"]
                true_outliers.add((min(i, j), max(i, j)))

        detected = set()
        for pair in data["outlier_edges"]:
            i, j = int(pair[0]), int(pair[1])
            detected.add((min(i, j), max(i, j)))

        if true_outliers:
            tp = len(true_outliers & detected)
            recall = tp / len(true_outliers)
            assert recall >= 0.6, (
                f"Outlier recall {recall:.2f} < 0.6 on new graph"
            )
        if detected:
            tp = len(true_outliers & detected)
            precision = tp / len(detected)
            assert precision >= 0.6, (
                f"Outlier precision {precision:.2f} < 0.6 on new graph"
            )
