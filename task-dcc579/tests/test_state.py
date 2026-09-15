
import subprocess
import os
import csv
import math
import sys
import secrets

sys.path.insert(0, "/tests")
from generate_data import generate_dataset


def _load_trajectory(path):
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                {
                    "time": float(row["time"]),
                    "x": float(row["x"]),
                    "y": float(row["y"]),
                    "theta": float(row["theta"]),
                }
            )
    return rows


def _position_rmse(est, gt_x, gt_y):
    n = min(len(est), len(gt_x))
    assert n > 0
    s = 0.0
    for i in range(n):
        s += (est[i]["x"] - gt_x[i]) ** 2 + (est[i]["y"] - gt_y[i]) ** 2
    return math.sqrt(s / n)


def _run_estimator(data_dir, output_path):
    result = subprocess.run(
        ["python3", "/app/estimator.py", data_dir, output_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"estimator.py failed (exit {result.returncode}):\n{result.stderr[:500]}"
    )
    return _load_trajectory(output_path)


class TestEstimator:
    def test_estimator_exists(self):
        """The agent must create /app/estimator.py."""
        assert os.path.exists("/app/estimator.py"), (
            "estimator.py not found at /app/estimator.py"
        )

    def test_output_format(self):
        """Estimator must produce a well-formed CSV with the right columns."""
        os.makedirs("/tmp/t_fmt", exist_ok=True)
        est = _run_estimator("/app/data", "/tmp/t_fmt/est.csv")
        assert len(est) >= 500, f"Too few rows: {len(est)}"
        for row in est[:5]:
            for key in ("time", "x", "y", "theta"):
                assert key in row, f"Missing column {key}"
            assert math.isfinite(row["x"])
            assert math.isfinite(row["y"])
            assert math.isfinite(row["theta"])

    def test_accuracy_seed42(self):
        """Accuracy on the provided dataset (seed 42)."""
        gt = generate_dataset(42, "/tmp/gt42")
        os.makedirs("/tmp/out42", exist_ok=True)
        est = _run_estimator("/app/data", "/tmp/out42/est.csv")
        rmse = _position_rmse(est, gt["x"], gt["y"])
        assert rmse < 1.5, f"Position RMSE {rmse:.3f} m exceeds 1.5 m (seed 42)"

    def test_accuracy_seed98765(self):
        """Accuracy on a fixed but different dataset."""
        gt = generate_dataset(98765, "/tmp/data98765")
        os.makedirs("/tmp/out98765", exist_ok=True)
        est = _run_estimator("/tmp/data98765", "/tmp/out98765/est.csv")
        rmse = _position_rmse(est, gt["x"], gt["y"])
        assert rmse < 1.5, f"Position RMSE {rmse:.3f} m exceeds 1.5 m (seed 98765)"

    def test_accuracy_random_seed(self):
        """Accuracy on a random dataset to prevent hard-coding."""
        seed = secrets.randbelow(900000) + 100000
        gt = generate_dataset(seed, f"/tmp/data_{seed}")
        os.makedirs(f"/tmp/out_{seed}", exist_ok=True)
        est = _run_estimator(f"/tmp/data_{seed}", f"/tmp/out_{seed}/est.csv")
        rmse = _position_rmse(est, gt["x"], gt["y"])
        assert rmse < 1.5, (
            f"Position RMSE {rmse:.3f} m exceeds 1.5 m (random seed {seed})"
        )
