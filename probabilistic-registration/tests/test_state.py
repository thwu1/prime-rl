
"""Verify point cloud registration accuracy against ground truth."""

import glob
import json
import os
import subprocess

import h5py
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Ground truth helpers (must match gen_data.py exactly)
# ---------------------------------------------------------------------------

def _rodrigues(axis, angle_rad):
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    return np.eye(3) + np.sin(angle_rad) * K + (1 - np.cos(angle_rad)) * (K @ K)


def ground_truth_a():
    axis = np.array([1.0, 2.0, 3.0])
    axis = axis / np.linalg.norm(axis)
    R = _rodrigues(axis, np.deg2rad(42.0))
    t = np.array([0.5, -0.3, 0.8])
    s = 1.12
    return R, t, s


def ground_truth_b():
    axis = np.array([-1.0, 0.5, 2.0])
    axis = axis / np.linalg.norm(axis)
    R = _rodrigues(axis, np.deg2rad(65.0))
    t = np.array([-0.4, 0.6, -0.2])
    s = 0.93
    return R, t, s


def rotation_error_deg(R_pred, R_gt):
    cos_angle = (np.trace(R_pred @ R_gt.T) - 1.0) / 2.0
    cos_angle = np.clip(cos_angle, -1.0, 1.0)
    return np.degrees(np.arccos(cos_angle))


def load_h5_points(path):
    """Load point cloud coordinates from HDF5 file."""
    with h5py.File(path, "r") as f:
        return f["/pointcloud/xyz"][:]


# ---------------------------------------------------------------------------
# Tests for primary problem (source.h5 / target.h5 -> result.json)
# ---------------------------------------------------------------------------

class TestPrimaryRegistration:

    @pytest.fixture(autouse=True)
    def load_result(self):
        assert os.path.exists("/app/result.json"), (
            "/app/result.json not found — the registration script must produce it"
        )
        with open("/app/result.json") as f:
            self.result = json.load(f)

    def test_result_format(self):
        assert "rotation_matrix" in self.result
        assert "translation" in self.result
        assert "scale" in self.result
        R = np.array(self.result["rotation_matrix"])
        assert R.shape == (3, 3), f"rotation_matrix shape {R.shape}, expected (3,3)"
        t = np.array(self.result["translation"])
        assert t.shape == (3,), f"translation shape {t.shape}, expected (3,)"
        assert isinstance(self.result["scale"], (int, float))

    def test_proper_rotation(self):
        R = np.array(self.result["rotation_matrix"])
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-3), "R^T R != I"
        assert abs(np.linalg.det(R) - 1.0) < 1e-3, f"det(R) = {np.linalg.det(R):.6f}, expected 1"

    def test_rotation_accuracy(self):
        R_gt, _, _ = ground_truth_a()
        R_pred = np.array(self.result["rotation_matrix"])
        err = rotation_error_deg(R_pred, R_gt)
        assert err < 2.0, f"Rotation error {err:.3f}° exceeds 2° threshold"

    def test_translation_accuracy(self):
        _, t_gt, _ = ground_truth_a()
        t_pred = np.array(self.result["translation"])
        err = np.linalg.norm(t_pred - t_gt)
        assert err < 0.1, f"Translation error {err:.4f} exceeds 0.1 threshold"

    def test_scale_accuracy(self):
        _, _, s_gt = ground_truth_a()
        s_pred = self.result["scale"]
        rel_err = abs(s_pred - s_gt) / s_gt
        assert rel_err < 0.05, f"Scale relative error {rel_err:.4f} exceeds 5% threshold"

    def test_alignment_quality(self):
        """Verify the transformation actually aligns point clouds."""
        source = load_h5_points("/app/data/source.h5")
        target = load_h5_points("/app/data/target.h5")
        R = np.array(self.result["rotation_matrix"])
        t = np.array(self.result["translation"])
        s = self.result["scale"]

        transformed = s * (source @ R.T) + t

        # brute-force nearest-neighbour (no extra deps)
        dists = np.sqrt(
            np.sum((transformed[:, None, :] - target[None, :, :]) ** 2, axis=2)
        ).min(axis=1)
        close_frac = np.mean(dists < 0.3)
        assert close_frac > 0.70, (
            f"Only {close_frac:.1%} of transformed source points within 0.3 of "
            f"a target point — expected >70%"
        )


# ---------------------------------------------------------------------------
# Tests for generalization (source_b.h5 / target_b.h5 -> result_b.json)
# ---------------------------------------------------------------------------

class TestGeneralization:
    """Run the agent's script on a second, independent registration problem."""

    @pytest.fixture(autouse=True)
    def prepare_and_run(self):
        """Find the registration script, substitute filenames, run, load result."""
        py_files = sorted(glob.glob("/app/*.py"))
        self.script = None
        for pf in py_files:
            if os.path.basename(pf).startswith("_register_b"):
                continue
            with open(pf) as fh:
                code = fh.read()
            if "source.h5" in code:
                self.script = pf
                break

        if self.script is None:
            pytest.skip("No registration script referencing source.h5 found in /app/")

        with open(self.script) as fh:
            code = fh.read()

        code_b = code.replace("source.h5", "source_b.h5")
        code_b = code_b.replace("target.h5", "target_b.h5")
        code_b = code_b.replace("result.json", "result_b.json")

        script_b = "/app/_register_b.py"
        with open(script_b, "w") as fh:
            fh.write(code_b)

        result = subprocess.run(
            ["python3", script_b],
            capture_output=True,
            text=True,
            timeout=300,
            cwd="/app",
        )
        self.run_result = result

        if os.path.exists("/app/result_b.json"):
            with open("/app/result_b.json") as fh:
                self.result = json.load(fh)
        else:
            self.result = None

    def test_generalization_runs(self):
        assert self.result is not None, (
            f"result_b.json not produced. returncode={self.run_result.returncode}, "
            f"stderr={self.run_result.stderr[:500]}"
        )

    def test_generalization_rotation(self):
        if self.result is None:
            pytest.skip("No result_b.json")
        R_gt, _, _ = ground_truth_b()
        R_pred = np.array(self.result["rotation_matrix"])
        err = rotation_error_deg(R_pred, R_gt)
        assert err < 3.0, f"Generalization rotation error {err:.3f}° exceeds 3° threshold"

    def test_generalization_translation(self):
        if self.result is None:
            pytest.skip("No result_b.json")
        _, t_gt, _ = ground_truth_b()
        t_pred = np.array(self.result["translation"])
        err = np.linalg.norm(t_pred - t_gt)
        assert err < 0.15, f"Generalization translation error {err:.4f} exceeds 0.15"

    def test_generalization_scale(self):
        if self.result is None:
            pytest.skip("No result_b.json")
        _, _, s_gt = ground_truth_b()
        s_pred = self.result["scale"]
        rel_err = abs(s_pred - s_gt) / s_gt
        assert rel_err < 0.05, f"Generalization scale error {rel_err:.4f} exceeds 5%"


# ---------------------------------------------------------------------------
# Anti-cheat: no forbidden imports
# ---------------------------------------------------------------------------

class TestCodeConstraints:

    def test_no_forbidden_imports(self):
        forbidden = [
            "import probreg",
            "from probreg",
            "import pycpd",
            "from pycpd",
            "open3d.pipelines.registration",
        ]
        for py_file in glob.glob("/app/*.py"):
            if os.path.basename(py_file).startswith("_register_b"):
                continue  # skip our generated copy
            with open(py_file) as fh:
                code = fh.read()
            for lib in forbidden:
                assert lib not in code, (
                    f"Forbidden import '{lib}' found in {py_file}"
                )
