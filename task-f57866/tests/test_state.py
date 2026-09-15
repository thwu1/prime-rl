"""Tests for 2D pose-graph SLAM optimizer output.

"""
import math
import os
import pytest

# Ground truth poses (40 nodes on a circle of radius 8m)
GROUND_TRUTH = {
    0: (8.0, 0.0, 1.570796),
    1: (7.901507, 1.251476, 1.727876),
    2: (7.608452, 2.472136, 1.884956),
    3: (7.128052, 3.631924, 2.042035),
    4: (6.472136, 4.702282, 2.199115),
    5: (5.656854, 5.656854, 2.356194),
    6: (4.702282, 6.472136, 2.513274),
    7: (3.631924, 7.128052, 2.670354),
    8: (2.472136, 7.608452, 2.827433),
    9: (1.251476, 7.901507, 2.984513),
    10: (0.0, 8.0, -3.141593),
    11: (-1.251476, 7.901507, -2.984513),
    12: (-2.472136, 7.608452, -2.827433),
    13: (-3.631924, 7.128052, -2.670354),
    14: (-4.702282, 6.472136, -2.513274),
    15: (-5.656854, 5.656854, -2.356194),
    16: (-6.472136, 4.702282, -2.199115),
    17: (-7.128052, 3.631924, -2.042035),
    18: (-7.608452, 2.472136, -1.884956),
    19: (-7.901507, 1.251476, -1.727876),
    20: (-8.0, 0.0, -1.570796),
    21: (-7.901507, -1.251476, -1.413717),
    22: (-7.608452, -2.472136, -1.256637),
    23: (-7.128052, -3.631924, -1.099557),
    24: (-6.472136, -4.702282, -0.942478),
    25: (-5.656854, -5.656854, -0.785398),
    26: (-4.702282, -6.472136, -0.628319),
    27: (-3.631924, -7.128052, -0.471239),
    28: (-2.472136, -7.608452, -0.314159),
    29: (-1.251476, -7.901507, -0.157080),
    30: (0.0, -8.0, 0.0),
    31: (1.251476, -7.901507, 0.157080),
    32: (2.472136, -7.608452, 0.314159),
    33: (3.631924, -7.128052, 0.471239),
    34: (4.702282, -6.472136, 0.628319),
    35: (5.656854, -5.656854, 0.785398),
    36: (6.472136, -4.702282, 0.942478),
    37: (7.128052, -3.631924, 1.099557),
    38: (7.608452, -2.472136, 1.256637),
    39: (7.901507, -1.251476, 1.413717),
}

# Known outlier edge pairs
OUTLIER_EDGES = {(7, 22), (3, 33), (18, 38)}

# Odometry edges (consecutive)
ODOMETRY_EDGES = {(i, i + 1) for i in range(39)}


def normalize_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def read_poses(filepath):
    """Read optimized poses from file."""
    poses = {}
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            vid = int(parts[0])
            x, y, theta = float(parts[1]), float(parts[2]), float(parts[3])
            poses[vid] = (x, y, theta)
    return poses


def read_residuals(filepath):
    """Read per-edge chi-squared residuals."""
    residuals = {}
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            i, j = int(parts[0]), int(parts[1])
            chi2 = float(parts[2])
            residuals[(i, j)] = chi2
    return residuals


def read_summary(filepath):
    """Read summary key-value pairs."""
    summary = {}
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                try:
                    summary[key] = float(val.strip())
                except ValueError:
                    summary[key] = val.strip()
    return summary


class TestOutputFilesExist:
    def test_optimized_poses_exist(self):
        assert os.path.isfile("/app/output/optimized_poses.txt"), \
            "Missing /app/output/optimized_poses.txt"

    def test_edge_residuals_exist(self):
        assert os.path.isfile("/app/output/edge_residuals.txt"), \
            "Missing /app/output/edge_residuals.txt"

    def test_summary_exists(self):
        assert os.path.isfile("/app/output/summary.txt"), \
            "Missing /app/output/summary.txt"


class TestOptimizedPoses:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.poses = read_poses("/app/output/optimized_poses.txt")

    def test_all_vertices_present(self):
        for vid in GROUND_TRUTH:
            assert vid in self.poses, f"Missing vertex {vid} in output"

    def test_position_rmse(self):
        sum_sq = 0.0
        for vid, (gx, gy, _) in GROUND_TRUTH.items():
            ox, oy, _ = self.poses[vid]
            sum_sq += (ox - gx) ** 2 + (oy - gy) ** 2
        rmse = math.sqrt(sum_sq / len(GROUND_TRUTH))
        assert rmse < 0.6, \
            f"Position RMSE {rmse:.4f}m exceeds threshold 0.6m"

    def test_angle_rmse(self):
        sum_sq = 0.0
        for vid, (_, _, gt) in GROUND_TRUTH.items():
            _, _, ot = self.poses[vid]
            err = abs(normalize_angle(ot - gt))
            sum_sq += err ** 2
        rmse = math.sqrt(sum_sq / len(GROUND_TRUTH))
        assert rmse < 0.15, \
            f"Angle RMSE {rmse:.4f}rad exceeds threshold 0.15rad"

    def test_angles_normalized(self):
        for vid, (_, _, theta) in self.poses.items():
            assert -math.pi - 0.01 <= theta <= math.pi + 0.01, \
                f"Vertex {vid} theta={theta:.4f} not normalized to [-pi,pi]"


class TestEdgeResiduals:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.residuals = read_residuals("/app/output/edge_residuals.txt")

    def test_outlier_edges_high_residual(self):
        for edge in OUTLIER_EDGES:
            assert edge in self.residuals, \
                f"Missing residual for outlier edge {edge}"
            chi2 = self.residuals[edge]
            assert chi2 > 500, \
                f"Outlier edge {edge} chi2={chi2:.1f} should be >500"

    def test_odometry_edges_low_residual(self):
        for edge in ODOMETRY_EDGES:
            if edge in self.residuals:
                chi2 = self.residuals[edge]
                assert chi2 < 500, \
                    f"Odometry edge {edge} chi2={chi2:.1f} should be <500"

    def test_has_all_edges(self):
        # 39 odom + 1 loop closure (39-0) + 4 cross-circle LC + 3 outliers = 47
        assert len(self.residuals) >= 47, \
            f"Expected at least 47 edge residuals, got {len(self.residuals)}"


class TestSummary:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.summary = read_summary("/app/output/summary.txt")

    def test_has_initial_chi2(self):
        assert "initial_chi2" in self.summary, \
            "Missing initial_chi2 in summary"
        val = self.summary["initial_chi2"]
        assert isinstance(val, float) and val > 1000, \
            f"initial_chi2={val} seems wrong (should be large)"

    def test_has_final_chi2(self):
        assert "final_chi2" in self.summary, \
            "Missing final_chi2 in summary"

    def test_has_num_outliers(self):
        assert "num_outliers" in self.summary, \
            "Missing num_outliers in summary"
        val = self.summary["num_outliers"]
        assert int(val) >= 3, \
            f"num_outliers={int(val)}, expected at least 3"

    def test_chi2_consistency(self):
        if "initial_chi2" in self.summary and "final_chi2" in self.summary:
            init = self.summary["initial_chi2"]
            final = self.summary["final_chi2"]
            assert isinstance(init, float) and isinstance(final, float)
