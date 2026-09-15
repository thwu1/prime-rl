"""
Tests for SE(2) Pose-Graph SLAM Pipeline with Covariance Recovery and Consistency Analysis.

"""
import pytest
import subprocess
import os
import json
import math


GROUND_TRUTH = {
    0: (0.0, 0.0, 0.0),
    1: (2.0, 0.0, 0.0),
    2: (4.0, 0.0, math.pi / 2),
    3: (4.0, 2.0, math.pi / 2),
    4: (4.0, 4.0, math.pi),
    5: (2.0, 4.0, math.pi),
    6: (0.0, 4.0, -math.pi / 2),
    7: (0.0, 2.0, -math.pi / 2),
}

POS_TOL_CLEAN = 0.2
ANG_TOL_CLEAN = 0.15
POS_TOL_ROBUST = 0.5
ANG_TOL_ROBUST = 0.3


def parse_output(filepath):
    poses = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 4:
                vid = int(parts[0])
                x, y, theta = float(parts[1]), float(parts[2]), float(parts[3])
                poses[vid] = (x, y, theta)
    return poses


def pose_distance(p1, p2):
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def angle_distance(a1, a2):
    d = a1 - a2
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return abs(d)


def run_optimizer(graph, config, output):
    result = subprocess.run(
        [
            "python3", "/app/optimizer.py",
            "--graph", graph,
            "--config", config,
            "--output", output,
        ],
        capture_output=True, text=True, timeout=120,
    )
    return result


# ---------------------------------------------------------------------------
# Optimizer tests
# ---------------------------------------------------------------------------

class TestCleanGraph:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.output = str(tmp_path / "clean_output.txt")
        result = run_optimizer(
            "/app/graphs/square_loop.g2o", "/app/config_clean.yaml", self.output
        )
        assert result.returncode == 0, (
            f"Optimizer failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_all_vertices_present(self):
        poses = parse_output(self.output)
        for vid in range(8):
            assert vid in poses, f"Vertex {vid} missing from output"

    def test_position_accuracy(self):
        poses = parse_output(self.output)
        for vid, gt in GROUND_TRUTH.items():
            dist = pose_distance(poses[vid], gt)
            assert dist < POS_TOL_CLEAN, (
                f"V{vid} pos err {dist:.4f}m > {POS_TOL_CLEAN}m. "
                f"Got ({poses[vid][0]:.3f},{poses[vid][1]:.3f}) "
                f"exp ({gt[0]:.3f},{gt[1]:.3f})"
            )

    def test_angle_accuracy(self):
        poses = parse_output(self.output)
        for vid, gt in GROUND_TRUTH.items():
            adist = angle_distance(poses[vid][2], gt[2])
            assert adist < ANG_TOL_CLEAN, (
                f"V{vid} ang err {adist:.4f}rad > {ANG_TOL_CLEAN}rad. "
                f"Got {poses[vid][2]:.4f}, exp {gt[2]:.4f}"
            )

    def test_angles_normalized(self):
        poses = parse_output(self.output)
        for vid, (x, y, theta) in poses.items():
            assert -math.pi - 1e-6 <= theta <= math.pi + 1e-6, (
                f"V{vid} angle {theta:.6f} not in [-pi,pi]"
            )

    def test_fixed_vertex_unchanged(self):
        poses = parse_output(self.output)
        assert pose_distance(poses[0], (0, 0)) < 1e-4, "Fixed vertex 0 position changed"
        assert angle_distance(poses[0][2], 0.0) < 1e-4, "Fixed vertex 0 angle changed"

    def test_convergence_report(self):
        report_file = self.output + ".report"
        assert os.path.exists(report_file), "Convergence report not created"
        with open(report_file) as f:
            report = json.load(f)
        assert "iterations" in report
        assert "initial_cost" in report
        assert "final_cost" in report
        assert "converged" in report
        assert "cost_history" in report
        assert report["converged"] is True, "Optimizer did not converge on clean graph"
        assert report["final_cost"] < report["initial_cost"], "Cost did not decrease"
        assert isinstance(report["cost_history"], list)
        assert len(report["cost_history"]) >= 2


class TestCorruptedGraph:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.output = str(tmp_path / "corrupt_output.txt")
        result = run_optimizer(
            "/app/graphs/corrupted_loop.g2o", "/app/config_robust.yaml", self.output
        )
        assert result.returncode == 0, (
            f"Optimizer failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_position_with_robust_loss(self):
        poses = parse_output(self.output)
        for vid, gt in GROUND_TRUTH.items():
            dist = pose_distance(poses[vid], gt)
            assert dist < POS_TOL_ROBUST, (
                f"V{vid} pos err {dist:.4f}m > {POS_TOL_ROBUST}m with robust loss"
            )

    def test_angle_with_robust_loss(self):
        poses = parse_output(self.output)
        for vid, gt in GROUND_TRUTH.items():
            adist = angle_distance(poses[vid][2], gt[2])
            assert adist < ANG_TOL_ROBUST, (
                f"V{vid} ang err {adist:.4f}rad > {ANG_TOL_ROBUST}rad with robust loss"
            )


class TestTwoNodeGraph:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.graph = str(tmp_path / "twonode.g2o")
        with open(self.graph, "w") as f:
            f.write("VERTEX_SE2 0 0.0 0.0 0.0\n")
            f.write("VERTEX_SE2 1 1.0 0.0 0.0\n")
            f.write("FIX 0\n")
            f.write(
                "EDGE_SE2 0 1 1.0 0.5 0.1 1000.0 0.0 0.0 1000.0 0.0 1000.0\n"
            )
        self.output = str(tmp_path / "twonode_output.txt")
        result = run_optimizer(self.graph, "/app/config_clean.yaml", self.output)
        assert result.returncode == 0, f"Optimizer failed:\n{result.stderr}"

    def test_node1_position(self):
        poses = parse_output(self.output)
        assert abs(poses[1][0] - 1.0) < 0.01
        assert abs(poses[1][1] - 0.5) < 0.01
        assert angle_distance(poses[1][2], 0.1) < 0.01

    def test_node0_fixed(self):
        poses = parse_output(self.output)
        assert pose_distance(poses[0], (0, 0)) < 1e-6


class TestAngleWrapping:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.graph = str(tmp_path / "anglewrap.g2o")
        dx = math.cos(3.0) * 1.0
        dy = -math.sin(3.0) * 1.0
        dtheta = -3.0 - 3.0
        while dtheta > math.pi:
            dtheta -= 2 * math.pi
        while dtheta < -math.pi:
            dtheta += 2 * math.pi
        with open(self.graph, "w") as f:
            f.write("VERTEX_SE2 0 0.0 0.0 3.0\n")
            f.write("VERTEX_SE2 1 1.0 0.0 2.5\n")
            f.write("FIX 0\n")
            f.write(
                "EDGE_SE2 0 1 %.10f %.10f %.10f 1000.0 0.0 0.0 1000.0 0.0 1000.0\n"
                % (dx, dy, dtheta)
            )
        self.output = str(tmp_path / "anglewrap_output.txt")
        result = run_optimizer(self.graph, "/app/config_clean.yaml", self.output)
        assert result.returncode == 0, f"Optimizer failed:\n{result.stderr}"

    def test_angle_crosses_boundary(self):
        poses = parse_output(self.output)
        expected_theta = -3.0
        adist = angle_distance(poses[1][2], expected_theta)
        assert adist < 0.05, (
            f"Angle wrapping failed: got {poses[1][2]:.4f}, expected ~{expected_theta:.4f}"
        )

    def test_position_correct(self):
        poses = parse_output(self.output)
        assert abs(poses[1][0] - 1.0) < 0.05
        assert abs(poses[1][1] - 0.0) < 0.05

    def test_all_angles_normalized(self):
        poses = parse_output(self.output)
        for vid, (x, y, theta) in poses.items():
            assert -math.pi - 1e-6 <= theta <= math.pi + 1e-6


# ---------------------------------------------------------------------------
# Marginal covariance recovery tests
# ---------------------------------------------------------------------------

class TestCovarianceTwoNode:
    """Verify covariance on a 2-node graph with known analytical solution.

    With node 0 fixed at origin and a single edge to node 1 with info=1000*I,
    the free Hessian is H = J_j^T * Omega * J_j. Since theta_0=0, J_j = I,
    so H = 1000*I and Sigma = 0.001*I.
    """

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.graph = str(tmp_path / "cov_2node.g2o")
        with open(self.graph, "w") as f:
            f.write("VERTEX_SE2 0 0.0 0.0 0.0\n")
            f.write("VERTEX_SE2 1 1.0 0.5 0.1\n")
            f.write("FIX 0\n")
            f.write("EDGE_SE2 0 1 1.0 0.5 0.1 1000.0 0.0 0.0 1000.0 0.0 1000.0\n")

        self.opt_output = str(tmp_path / "cov_opt.txt")
        result = run_optimizer(self.graph, "/app/config_clean.yaml", self.opt_output)
        assert result.returncode == 0, f"Optimizer failed:\n{result.stderr}"

        self.cov_output = str(tmp_path / "cov_report.json")
        result = subprocess.run(
            [
                "python3", "/app/covariance.py",
                "--graph", self.graph,
                "--poses", self.opt_output,
                "--output", self.cov_output,
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"covariance.py failed:\n{result.stderr}"

    def test_report_structure(self):
        with open(self.cov_output) as f:
            report = json.load(f)
        assert "poses" in report
        assert "covariance_matrix_size" in report
        assert report["covariance_matrix_size"] == 3

    def test_fixed_node_zero_covariance(self):
        with open(self.cov_output) as f:
            report = json.load(f)
        node0 = report["poses"]["0"]
        assert node0["pos_trace"] == 0.0
        assert node0["ellipse"]["semi_major"] == 0.0

    def test_analytical_covariance(self):
        with open(self.cov_output) as f:
            report = json.load(f)
        node1 = report["poses"]["1"]
        cov = node1["covariance"]
        for i in range(3):
            assert abs(cov[i][i] - 0.001) < 0.0005, (
                f"cov[{i}][{i}] = {cov[i][i]}, expected ~0.001"
            )
        for i in range(3):
            for j in range(3):
                if i != j:
                    assert abs(cov[i][j]) < 0.0005, (
                        f"cov[{i}][{j}] = {cov[i][j]}, expected ~0"
                    )
        assert abs(node1["pos_trace"] - 0.002) < 0.001

    def test_ellipse_parameters(self):
        with open(self.cov_output) as f:
            report = json.load(f)
        node1 = report["poses"]["1"]
        expected_axis = math.sqrt(0.001)
        assert abs(node1["ellipse"]["semi_major"] - expected_axis) < 0.005
        assert abs(node1["ellipse"]["semi_minor"] - expected_axis) < 0.005


class TestCovarianceThreeNode:
    """Verify covariance on a 3-node chain with known analytical solution.

    Chain: 0 -> 1 -> 2, node 0 fixed. Node 1 at (2,0,pi/2), node 2 at (2,2,pi/2).
    Analytical: Sigma_11 = 0.001*I (pos_trace=0.002),
                Sigma_22 has pos_trace = 0.008 (more uncertain because farther from anchor).
    """

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.graph = str(tmp_path / "three_node.g2o")
        half_pi = 1.5707963268
        with open(self.graph, "w") as f:
            f.write("VERTEX_SE2 0 0.0 0.0 0.0\n")
            f.write("VERTEX_SE2 1 2.0 0.01 %.10f\n" % half_pi)
            f.write("VERTEX_SE2 2 2.01 2.0 %.10f\n" % half_pi)
            f.write("FIX 0\n")
            f.write(
                "EDGE_SE2 0 1 2.0 0.0 %.10f 1000.0 0.0 0.0 1000.0 0.0 1000.0\n"
                % half_pi
            )
            f.write(
                "EDGE_SE2 1 2 2.0 0.0 0.0 1000.0 0.0 0.0 1000.0 0.0 1000.0\n"
            )

        self.opt_output = str(tmp_path / "three_opt.txt")
        result = run_optimizer(self.graph, "/app/config_clean.yaml", self.opt_output)
        assert result.returncode == 0, f"Optimizer failed:\n{result.stderr}"

        self.cov_output = str(tmp_path / "three_cov.json")
        result = subprocess.run(
            [
                "python3", "/app/covariance.py",
                "--graph", self.graph,
                "--poses", self.opt_output,
                "--output", self.cov_output,
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"covariance.py failed:\n{result.stderr}"

    def test_node1_covariance(self):
        with open(self.cov_output) as f:
            report = json.load(f)
        node1 = report["poses"]["1"]
        assert abs(node1["pos_trace"] - 0.002) < 0.001, (
            f"Node 1 pos_trace {node1['pos_trace']:.6f}, expected ~0.002"
        )

    def test_node2_higher_uncertainty(self):
        with open(self.cov_output) as f:
            report = json.load(f)
        trace_1 = report["poses"]["1"]["pos_trace"]
        trace_2 = report["poses"]["2"]["pos_trace"]
        assert trace_2 > trace_1, (
            f"Node 2 trace ({trace_2:.6f}) should exceed node 1 trace ({trace_1:.6f})"
        )

    def test_node2_covariance_range(self):
        with open(self.cov_output) as f:
            report = json.load(f)
        node2 = report["poses"]["2"]
        assert abs(node2["pos_trace"] - 0.008) < 0.003, (
            f"Node 2 pos_trace {node2['pos_trace']:.6f}, expected ~0.008"
        )


class TestCovarianceSquareLoop:
    """Test covariance recovery on the 8-node square loop."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.opt_output = str(tmp_path / "sq_opt.txt")
        result = run_optimizer(
            "/app/graphs/square_loop.g2o", "/app/config_clean.yaml", self.opt_output
        )
        assert result.returncode == 0

        self.cov_output = str(tmp_path / "sq_cov.json")
        result = subprocess.run(
            [
                "python3", "/app/covariance.py",
                "--graph", "/app/graphs/square_loop.g2o",
                "--poses", self.opt_output,
                "--output", self.cov_output,
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"covariance.py failed:\n{result.stderr}"

    def test_matrix_size(self):
        with open(self.cov_output) as f:
            report = json.load(f)
        assert report["covariance_matrix_size"] == 21

    def test_all_covariances_spd(self):
        import numpy as np
        with open(self.cov_output) as f:
            report = json.load(f)
        for vid_str, data in report["poses"].items():
            if vid_str == "0":
                continue
            cov = np.array(data["covariance"])
            assert np.allclose(cov, cov.T, atol=1e-10), (
                f"Cov for V{vid_str} not symmetric"
            )
            eigvals = np.linalg.eigvalsh(cov)
            assert all(e > 0 for e in eigvals), (
                f"Cov for V{vid_str} not positive definite: {eigvals}"
            )

    def test_ellipse_parameters_valid(self):
        with open(self.cov_output) as f:
            report = json.load(f)
        for vid_str, data in report["poses"].items():
            if vid_str == "0":
                continue
            e = data["ellipse"]
            assert e["semi_major"] > 0
            assert e["semi_minor"] > 0
            assert e["semi_major"] >= e["semi_minor"] - 1e-10

    def test_uncertainty_reasonable(self):
        with open(self.cov_output) as f:
            report = json.load(f)
        for vid_str in ["1", "2", "3", "4", "5", "6", "7"]:
            trace = report["poses"][vid_str]["pos_trace"]
            assert 0 < trace < 0.1, (
                f"Node {vid_str} pos_trace {trace:.6f} outside reasonable range"
            )


# ---------------------------------------------------------------------------
# Edge consistency analysis tests
# ---------------------------------------------------------------------------

class TestConsistencyCleanGraph:
    """All edges in the clean optimized graph should be consistent."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.opt_output = str(tmp_path / "clean_opt.txt")
        result = run_optimizer(
            "/app/graphs/square_loop.g2o", "/app/config_clean.yaml", self.opt_output
        )
        assert result.returncode == 0

        self.con_output = str(tmp_path / "clean_con.json")
        result = subprocess.run(
            [
                "python3", "/app/consistency.py",
                "--graph", "/app/graphs/square_loop.g2o",
                "--poses", self.opt_output,
                "--threshold", "7.815",
                "--output", self.con_output,
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"consistency.py failed:\n{result.stderr}"

    def test_all_edges_consistent(self):
        with open(self.con_output) as f:
            report = json.load(f)
        assert report["num_inconsistent"] == 0, (
            f"Expected all edges consistent, got {report['num_inconsistent']} inconsistent"
        )
        assert report["num_consistent"] == len(report["edges"])

    def test_edge_fields_present(self):
        with open(self.con_output) as f:
            report = json.load(f)
        for edge in report["edges"]:
            assert "from" in edge
            assert "to" in edge
            assert "chi_squared" in edge
            assert "consistent" in edge
            assert edge["chi_squared"] >= 0


class TestConsistencyCorruptedGraph:
    """Outlier edges should be detected as inconsistent at ground truth poses."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.con_output = str(tmp_path / "corrupt_con.json")
        result = subprocess.run(
            [
                "python3", "/app/consistency.py",
                "--graph", "/app/graphs/corrupted_loop.g2o",
                "--poses", "/app/graphs/ground_truth.txt",
                "--threshold", "7.815",
                "--output", self.con_output,
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"consistency.py failed:\n{result.stderr}"

    def test_outlier_edges_detected(self):
        with open(self.con_output) as f:
            report = json.load(f)
        assert report["num_inconsistent"] >= 2, (
            f"Expected at least 2 inconsistent edges, got {report['num_inconsistent']}"
        )
        outlier_chisq = []
        for edge in report["edges"]:
            if (edge["from"] == 1 and edge["to"] == 5) or \
               (edge["from"] == 2 and edge["to"] == 6):
                outlier_chisq.append(edge["chi_squared"])
                assert not edge["consistent"], (
                    f"Outlier edge {edge['from']}->{edge['to']} marked consistent"
                )
        assert len(outlier_chisq) == 2, "Expected to find both outlier edges"

    def test_outlier_chi_squared_high(self):
        with open(self.con_output) as f:
            report = json.load(f)
        for edge in report["edges"]:
            if (edge["from"] == 1 and edge["to"] == 5) or \
               (edge["from"] == 2 and edge["to"] == 6):
                assert edge["chi_squared"] > 50, (
                    f"Outlier edge {edge['from']}->{edge['to']} "
                    f"chi_sq={edge['chi_squared']:.2f} not high enough"
                )

    def test_odometry_edges_mostly_consistent(self):
        with open(self.con_output) as f:
            report = json.load(f)
        odom_consistent = 0
        odom_total = 0
        for edge in report["edges"]:
            if abs(edge["from"] - edge["to"]) == 1 or \
               (edge["from"] == 7 and edge["to"] == 0):
                odom_total += 1
                if edge["consistent"]:
                    odom_consistent += 1
        assert odom_consistent >= 6, (
            f"Expected >=6 consistent odometry edges, got {odom_consistent}/{odom_total}"
        )


# ---------------------------------------------------------------------------
# Trajectory evaluation tests
# ---------------------------------------------------------------------------

class TestEvaluateTool:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.ref_file = str(tmp_path / "reference.txt")
        self.est_file = str(tmp_path / "estimated.txt")
        self.report_file = str(tmp_path / "eval_report.json")

        with open(self.ref_file, "w") as f:
            f.write("0 0.0 0.0 0.0\n")
            f.write("1 1.0 0.0 0.0\n")
            f.write("2 1.0 1.0 1.5707963\n")
            f.write("3 0.0 1.0 3.1415927\n")

        with open(self.est_file, "w") as f:
            f.write("0 0.0 0.0 0.0\n")
            f.write("1 1.05 0.02 0.01\n")
            f.write("2 1.03 1.04 1.58\n")
            f.write("3 -0.02 0.98 3.15\n")

        result = subprocess.run(
            [
                "python3", "/app/evaluate.py",
                "--estimated", self.est_file,
                "--reference", self.ref_file,
                "--output", self.report_file,
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            f"evaluate.py failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_report_has_required_fields(self):
        with open(self.report_file) as f:
            report = json.load(f)
        for key in ["ate_rmse", "ate_max", "rpe_trans_mean", "rpe_rot_mean", "num_poses"]:
            assert key in report, f"Missing required field: {key}"

    def test_ate_rmse_correct_range(self):
        with open(self.report_file) as f:
            report = json.load(f)
        assert 0.01 < report["ate_rmse"] < 0.1

    def test_ate_max_ge_rmse(self):
        with open(self.report_file) as f:
            report = json.load(f)
        assert report["ate_max"] >= report["ate_rmse"]

    def test_num_poses(self):
        with open(self.report_file) as f:
            report = json.load(f)
        assert report["num_poses"] == 4

    def test_rpe_reasonable(self):
        with open(self.report_file) as f:
            report = json.load(f)
        assert report["rpe_trans_mean"] > 0
        assert report["rpe_trans_mean"] < 0.2
        assert report["rpe_rot_mean"] >= 0
        assert report["rpe_rot_mean"] < 0.5


class TestEvaluateWithOptimizer:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.opt_output = str(tmp_path / "optimized.txt")
        self.eval_report = str(tmp_path / "eval_report.json")
        result = run_optimizer(
            "/app/graphs/square_loop.g2o", "/app/config_clean.yaml", self.opt_output
        )
        assert result.returncode == 0
        result = subprocess.run(
            [
                "python3", "/app/evaluate.py",
                "--estimated", self.opt_output,
                "--reference", "/app/graphs/ground_truth.txt",
                "--output", self.eval_report,
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0

    def test_ate_rmse_within_tolerance(self):
        with open(self.eval_report) as f:
            report = json.load(f)
        assert report["ate_rmse"] < 0.2

    def test_all_poses_evaluated(self):
        with open(self.eval_report) as f:
            report = json.load(f)
        assert report["num_poses"] == 8


# ---------------------------------------------------------------------------
# Full pipeline tests
# ---------------------------------------------------------------------------

class TestVisualizationPipeline:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.output_dir = str(tmp_path / "pipeline_out")
        result = subprocess.run(
            [
                "bash", "/app/pipeline.sh",
                "/app/graphs/square_loop.g2o",
                "/app/config_clean.yaml",
                self.output_dir,
            ],
            capture_output=True, text=True, timeout=120,
        )
        self.pipeline_result = result

    def test_pipeline_exits_successfully(self):
        assert self.pipeline_result.returncode == 0, (
            f"Pipeline failed:\nstdout: {self.pipeline_result.stdout}\n"
            f"stderr: {self.pipeline_result.stderr}"
        )

    def test_optimized_poses_created(self):
        opt_path = os.path.join(self.output_dir, "optimized.txt")
        assert os.path.exists(opt_path)
        poses = parse_output(opt_path)
        assert len(poses) == 8

    def test_svg_exists_and_valid(self):
        svg_path = os.path.join(self.output_dir, "graph.svg")
        assert os.path.exists(svg_path)
        with open(svg_path) as f:
            content = f.read()
        assert "<svg" in content
        has_shapes = ("ellipse" in content or "polygon" in content or "circle" in content)
        assert has_shapes, "SVG lacks node shape elements"

    def test_convergence_plot_exists(self):
        plot_path = os.path.join(self.output_dir, "convergence.png")
        assert os.path.exists(plot_path)
        assert os.path.getsize(plot_path) > 100

    def test_evaluation_report_valid(self):
        eval_path = os.path.join(self.output_dir, "evaluation.json")
        assert os.path.exists(eval_path)
        with open(eval_path) as f:
            report = json.load(f)
        assert report["ate_rmse"] < 0.2

    def test_covariance_report(self):
        cov_path = os.path.join(self.output_dir, "covariance.json")
        assert os.path.exists(cov_path), "covariance.json not produced by pipeline"
        with open(cov_path) as f:
            report = json.load(f)
        assert "poses" in report
        assert report["covariance_matrix_size"] == 21

    def test_consistency_report(self):
        con_path = os.path.join(self.output_dir, "consistency.json")
        assert os.path.exists(con_path), "consistency.json not produced by pipeline"
        with open(con_path) as f:
            report = json.load(f)
        assert "edges" in report
        assert report["num_consistent"] > 0
