"""
Verify the point-to-plane ICP registration pipeline produces
transformations that match ground truth within tolerance.

Two different random datasets are tested to prevent hard-coded answers.
"""

import subprocess
import os
import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def generate_data(seed=42, rot_deg=20.0, axis="1 2 3", trans="0.03 -0.02 0.05"):
    ax = axis.split()
    tx = trans.split()
    cmd = [
        "python3", "/app/generate_data.py",
        "--seed", str(seed),
        "--rotation-deg", str(rot_deg),
        "--axis", ax[0], ax[1], ax[2],
        "--translation", tx[0], tx[1], tx[2],
        "--output-dir", "/app/data",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"generate_data.py failed:\n{r.stderr}"


def build_project():
    os.makedirs("/app/build", exist_ok=True)
    r = subprocess.run(
        ["cmake", ".."], cwd="/app/build",
        capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 0, f"cmake failed:\n{r.stderr}"
    r = subprocess.run(
        ["make", "-j2"], cwd="/app/build",
        capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 0, f"make failed:\n{r.stderr}"


def run_registration():
    return subprocess.run(
        ["/app/build/register_clouds",
         "/app/data/source.pcd", "/app/data/target.pcd"],
        capture_output=True, text=True, timeout=120,
    )


def parse_output(stdout):
    lines = stdout.strip().split("\n")
    matrix_rows = []
    fitness = None
    converged = None
    iterations = None
    for line in lines:
        line = line.strip()
        if line.startswith("FITNESS"):
            fitness = float(line.split()[1])
        elif line.startswith("CONVERGED"):
            converged = int(line.split()[1])
        elif line.startswith("ITERATIONS"):
            iterations = int(line.split()[1])
        else:
            parts = line.split()
            if len(parts) == 4:
                try:
                    matrix_rows.append([float(x) for x in parts])
                except ValueError:
                    pass
    if len(matrix_rows) < 4:
        raise ValueError(
            f"Could not parse 4x4 matrix from stdout:\n{stdout}")
    T = np.array(matrix_rows[:4])
    return T, fitness, converged, iterations


def rotation_error_deg(R_est, R_gt):
    R_diff = R_est @ R_gt.T
    cos_angle = (np.trace(R_diff) - 1.0) / 2.0
    cos_angle = np.clip(cos_angle, -1.0, 1.0)
    return float(np.degrees(np.arccos(cos_angle)))


# ---------------------------------------------------------------------------
# Test class 1 — primary dataset (seed 42, 20-degree rotation)
# ---------------------------------------------------------------------------

class TestRegistrationPrimary:

    @classmethod
    def setup_class(cls):
        generate_data(seed=42, rot_deg=20.0,
                      axis="1 2 3", trans="0.03 -0.02 0.05")
        build_project()
        result = run_registration()
        assert result.returncode == 0, (
            f"Binary failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")
        cls.T_est, cls.fitness, cls.converged, cls.iters = parse_output(
            result.stdout)
        cls.T_gt = np.loadtxt("/app/data/ground_truth.txt")

    def test_rotation_error(self):
        err = rotation_error_deg(self.T_est[:3, :3], self.T_gt[:3, :3])
        assert err < 2.0, f"Rotation error {err:.3f} deg >= 2.0 deg"

    def test_translation_error(self):
        err = float(np.linalg.norm(self.T_est[:3, 3] - self.T_gt[:3, 3]))
        assert err < 0.04, f"Translation error {err:.5f} >= 0.04"

    def test_fitness(self):
        assert self.fitness is not None, "Could not parse fitness"
        assert self.fitness < 0.01, f"Fitness {self.fitness:.6f} >= 0.01"

    def test_convergence(self):
        assert self.converged == 1, "Algorithm did not converge"

    def test_orthogonal_rotation(self):
        R = self.T_est[:3, :3]
        I_approx = R @ R.T
        np.testing.assert_allclose(I_approx, np.eye(3), atol=0.1)
        det = float(np.linalg.det(R))
        assert abs(det - 1.0) < 0.1, f"det(R) = {det:.4f}, expected ~1"

    def test_homogeneous_row(self):
        np.testing.assert_allclose(
            self.T_est[3, :], [0, 0, 0, 1], atol=1e-3)


# ---------------------------------------------------------------------------
# Test class 2 — different dataset to prevent hard-coded solutions
# ---------------------------------------------------------------------------

class TestRegistrationSecondary:

    @classmethod
    def setup_class(cls):
        generate_data(seed=99, rot_deg=12.0,
                      axis="2 -1 1", trans="-0.04 0.01 0.03")
        # Binary already built; just re-run with new data
        result = run_registration()
        assert result.returncode == 0, (
            f"Binary failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")
        cls.T_est, cls.fitness, cls.converged, cls.iters = parse_output(
            result.stdout)
        cls.T_gt = np.loadtxt("/app/data/ground_truth.txt")

    def test_rotation_error_secondary(self):
        err = rotation_error_deg(self.T_est[:3, :3], self.T_gt[:3, :3])
        assert err < 2.0, f"Rotation error {err:.3f} deg >= 2.0 deg"

    def test_translation_error_secondary(self):
        err = float(np.linalg.norm(self.T_est[:3, 3] - self.T_gt[:3, 3]))
        assert err < 0.04, f"Translation error {err:.5f} >= 0.04"

    def test_fitness_secondary(self):
        assert self.fitness is not None, "Could not parse fitness"
        assert self.fitness < 0.01, f"Fitness {self.fitness:.6f} >= 0.01"

    def test_convergence_secondary(self):
        assert self.converged == 1, "Algorithm did not converge"
