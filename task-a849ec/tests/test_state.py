
import json
import os
import subprocess
import pytest

PIPELINE = "/app/slam_eval/pipeline.py"
DATA = "/app/data"
RESULTS = "/app/results"


def run_pipeline(fmt, gt, est, output, align="se3", max_diff=0.02,
                 robust=False, ransac_threshold=0.2, ransac_iterations=1000,
                 ransac_seed=42, rpe=False):
    """Run the evaluation pipeline and return parsed JSON metrics."""
    cmd = [
        "python3", PIPELINE,
        "--format", fmt,
        "--gt", gt,
        "--est", est,
        "--output", output,
        "--align", align,
        "--max_diff", str(max_diff),
    ]
    if robust:
        cmd += [
            "--robust",
            "--ransac_threshold", str(ransac_threshold),
            "--ransac_iterations", str(ransac_iterations),
            "--ransac_seed", str(ransac_seed),
        ]
    if rpe:
        cmd.append("--rpe")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (
        f"Pipeline exited with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists(output), f"Output file {output} not created"
    with open(output) as f:
        return json.load(f)


class TestPipelineFiles:
    """Verify required files exist."""

    def test_pipeline_exists(self):
        assert os.path.exists(PIPELINE), f"{PIPELINE} not found"

    def test_data_files_exist(self):
        for name in ["kitti_gt.txt", "kitti_est.txt", "tum_gt.txt", "tum_est.txt",
                      "euroc_gt.csv", "euroc_est.txt", "tum_outliers_est.txt"]:
            path = os.path.join(DATA, name)
            assert os.path.exists(path), f"Data file {path} not found"


class TestKITTI:
    """KITTI format: row-major 3x4 matrix, index-based association, SE(3) alignment."""

    @pytest.fixture(autouse=True)
    def setup(self):
        os.makedirs(RESULTS, exist_ok=True)
        self.metrics = run_pipeline(
            "kitti",
            f"{DATA}/kitti_gt.txt",
            f"{DATA}/kitti_est.txt",
            f"{RESULTS}/kitti.json",
            align="se3",
        )

    def test_required_fields(self):
        for key in ["rmse", "mean", "median", "std", "max", "num_poses", "scale"]:
            assert key in self.metrics, f"Missing field: {key}"

    def test_num_poses(self):
        assert self.metrics["num_poses"] == 150

    def test_scale_is_one(self):
        assert abs(self.metrics["scale"] - 1.0) < 1e-6, "SE(3) scale must be 1.0"

    def test_rmse(self):
        assert 0.02 < self.metrics["rmse"] < 0.12, \
            f"KITTI RMSE {self.metrics['rmse']} out of expected range"
        assert abs(self.metrics["rmse"] - 0.04979) < 0.005, \
            f"KITTI RMSE {self.metrics['rmse']} not close to expected 0.04979"

    def test_mean(self):
        assert abs(self.metrics["mean"] - 0.04553) < 0.005

    def test_median(self):
        assert abs(self.metrics["median"] - 0.04408) < 0.006

    def test_max(self):
        assert abs(self.metrics["max"] - 0.10814) < 0.015

    def test_invariants(self):
        m = self.metrics
        assert m["mean"] <= m["rmse"] + 1e-9
        assert m["median"] <= m["max"] + 1e-9
        assert m["std"] >= 0


class TestTUM:
    """TUM format: timestamp-based association, SE(3) alignment."""

    @pytest.fixture(autouse=True)
    def setup(self):
        os.makedirs(RESULTS, exist_ok=True)
        self.metrics = run_pipeline(
            "tum",
            f"{DATA}/tum_gt.txt",
            f"{DATA}/tum_est.txt",
            f"{RESULTS}/tum.json",
            align="se3",
        )

    def test_num_poses(self):
        assert self.metrics["num_poses"] == 150

    def test_rmse(self):
        assert 0.03 < self.metrics["rmse"] < 0.15, \
            f"TUM RMSE {self.metrics['rmse']} out of expected range"
        assert abs(self.metrics["rmse"] - 0.06614) < 0.005, \
            f"TUM RMSE {self.metrics['rmse']} not close to expected 0.06614"

    def test_mean(self):
        assert abs(self.metrics["mean"] - 0.06089) < 0.005

    def test_max(self):
        assert abs(self.metrics["max"] - 0.14118) < 0.015

    def test_scale_is_one(self):
        assert abs(self.metrics["scale"] - 1.0) < 1e-6


class TestEuRoCSim3:
    """EuRoC format with Sim(3) alignment to recover scale."""

    @pytest.fixture(autouse=True)
    def setup(self):
        os.makedirs(RESULTS, exist_ok=True)
        self.metrics = run_pipeline(
            "euroc",
            f"{DATA}/euroc_gt.csv",
            f"{DATA}/euroc_est.txt",
            f"{RESULTS}/euroc_sim3.json",
            align="sim3",
            max_diff=0.03,
        )

    def test_num_poses(self):
        assert self.metrics["num_poses"] == 150

    def test_scale_recovery(self):
        assert 0.65 < self.metrics["scale"] < 0.85, \
            f"EuRoC scale {self.metrics['scale']} not in expected range [0.65, 0.85]"
        assert abs(self.metrics["scale"] - 0.7409) < 0.01, \
            f"EuRoC scale {self.metrics['scale']} not close to expected 0.7409"

    def test_rmse(self):
        assert 0.03 < self.metrics["rmse"] < 0.15, \
            f"EuRoC Sim3 RMSE {self.metrics['rmse']} out of expected range"
        assert abs(self.metrics["rmse"] - 0.06648) < 0.005, \
            f"EuRoC Sim3 RMSE {self.metrics['rmse']} not close to expected 0.06648"

    def test_mean(self):
        assert abs(self.metrics["mean"] - 0.06143) < 0.005

    def test_max(self):
        assert abs(self.metrics["max"] - 0.14846) < 0.015


class TestEuRoCSE3:
    """EuRoC with SE(3) alignment: RMSE should be much larger due to unrecovered scale."""

    @pytest.fixture(autouse=True)
    def setup(self):
        os.makedirs(RESULTS, exist_ok=True)
        self.metrics = run_pipeline(
            "euroc",
            f"{DATA}/euroc_gt.csv",
            f"{DATA}/euroc_est.txt",
            f"{RESULTS}/euroc_se3.json",
            align="se3",
            max_diff=0.03,
        )

    def test_rmse_much_larger(self):
        assert self.metrics["rmse"] > 0.8, \
            f"EuRoC SE(3) RMSE {self.metrics['rmse']} should be >0.8 without scale correction"

    def test_scale_is_one(self):
        assert abs(self.metrics["scale"] - 1.0) < 1e-6


class TestRANSAC:
    """RANSAC robust alignment on outlier-corrupted trajectory data."""

    @pytest.fixture(autouse=True)
    def setup(self):
        os.makedirs(RESULTS, exist_ok=True)
        self.naive_metrics = run_pipeline(
            "tum",
            f"{DATA}/tum_gt.txt",
            f"{DATA}/tum_outliers_est.txt",
            f"{RESULTS}/tum_naive.json",
            align="se3",
        )
        self.robust_metrics = run_pipeline(
            "tum",
            f"{DATA}/tum_gt.txt",
            f"{DATA}/tum_outliers_est.txt",
            f"{RESULTS}/tum_robust.json",
            align="se3",
            robust=True,
            ransac_threshold=0.2,
            ransac_iterations=1000,
            ransac_seed=42,
        )

    def test_naive_large_rmse(self):
        """Without RANSAC, outliers severely bias the alignment."""
        assert self.naive_metrics["rmse"] > 0.5, \
            f"Naive RMSE {self.naive_metrics['rmse']} should be >0.5 with outliers"

    def test_robust_low_rmse(self):
        """RANSAC should reject outliers and recover clean alignment."""
        assert self.robust_metrics["rmse"] < 0.10, \
            f"Robust RMSE {self.robust_metrics['rmse']} should be <0.10"

    def test_num_inliers_field(self):
        assert "num_inliers" in self.robust_metrics, "Missing num_inliers field"

    def test_num_inliers_range(self):
        """Should identify ~135 inliers (150 total minus 15 outliers)."""
        assert 125 <= self.robust_metrics["num_inliers"] <= 145, \
            f"num_inliers {self.robust_metrics['num_inliers']} not in expected range"

    def test_robust_much_better(self):
        """RANSAC RMSE should be at least 5x better than naive."""
        assert self.robust_metrics["rmse"] < self.naive_metrics["rmse"] * 0.2

    def test_robust_num_poses_equals_inliers(self):
        """In robust mode, metrics are computed on inlier poses only."""
        assert self.robust_metrics["num_poses"] == self.robust_metrics["num_inliers"]


class TestRPE:
    """Relative Pose Error computation on KITTI data."""

    @pytest.fixture(autouse=True)
    def setup(self):
        os.makedirs(RESULTS, exist_ok=True)
        self.metrics = run_pipeline(
            "kitti",
            f"{DATA}/kitti_gt.txt",
            f"{DATA}/kitti_est.txt",
            f"{RESULTS}/kitti_rpe.json",
            align="se3",
            rpe=True,
        )

    def test_rpe_fields_exist(self):
        for key in ["rpe_rmse", "rpe_mean", "rpe_median", "rpe_max", "rpe_num_pairs"]:
            assert key in self.metrics, f"Missing RPE field: {key}"

    def test_rpe_num_pairs(self):
        """RPE has N-1 consecutive pairs for N=150 poses."""
        assert self.metrics["rpe_num_pairs"] == 149

    def test_rpe_reasonable_range(self):
        """RPE RMSE should be in a reasonable range for this noise level."""
        assert 0.02 < self.metrics["rpe_rmse"] < 0.12, \
            f"RPE RMSE {self.metrics['rpe_rmse']} out of expected range"

    def test_rpe_invariants(self):
        assert self.metrics["rpe_mean"] <= self.metrics["rpe_rmse"] + 1e-9
        assert self.metrics["rpe_median"] <= self.metrics["rpe_max"] + 1e-9

    def test_ate_also_present(self):
        """RPE output is additive: ATE fields must still be present."""
        assert "rmse" in self.metrics
        assert abs(self.metrics["rmse"] - 0.04979) < 0.005
        assert self.metrics["num_poses"] == 150
