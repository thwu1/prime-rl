
import json
import os
import subprocess

import pytest


def run_solver(matrix_path, tol=1e-8, output_path="/app/results.json"):
    """Run the AMG solver on a given matrix and return parsed results."""
    cmd = [
        "python3", "/app/amg_solver.py",
        "--matrix", matrix_path,
        "--tol", str(tol),
        "--output", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (
        f"Solver exited with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists(output_path), f"Output file {output_path} not created"
    with open(output_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Fixtures: run each solver configuration once, share across tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def iso32_results(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("results") / "iso32.json")
    return run_solver("/app/data/iso_32.mtx", output_path=out)


@pytest.fixture(scope="module")
def aniso32_results(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("results") / "aniso32.json")
    return run_solver("/app/data/aniso_32.mtx", output_path=out)


@pytest.fixture(scope="module")
def iso64_results(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("results") / "iso64.json")
    return run_solver("/app/data/iso_64.mtx", output_path=out)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOutputFormat:
    """Verify the output JSON contains all required fields."""

    REQUIRED_KEYS = [
        "iterations", "residual_norm", "relative_residual",
        "converged", "grid_complexity", "operator_complexity",
        "n_levels", "level_sizes",
    ]

    def test_required_fields(self, iso32_results):
        for key in self.REQUIRED_KEYS:
            assert key in iso32_results, f"Missing key: {key}"

    def test_level_sizes_list(self, iso32_results):
        sizes = iso32_results["level_sizes"]
        assert isinstance(sizes, list)
        assert len(sizes) >= 2


class TestIsotropicConvergence:
    """Isotropic diffusion on 32x32 grid (1024 unknowns)."""

    def test_converged(self, iso32_results):
        assert iso32_results["converged"] is True

    def test_relative_residual(self, iso32_results):
        assert iso32_results["relative_residual"] < 1e-8

    def test_iteration_bound(self, iso32_results):
        assert iso32_results["iterations"] <= 30, (
            f"Too many iterations ({iso32_results['iterations']}); "
            "a working AMG-PCG solver should need far fewer than 30"
        )


class TestAnisotropicConvergence:
    """Strongly anisotropic diffusion (epsilon=0.001) on 32x32 grid."""

    def test_converged(self, aniso32_results):
        assert aniso32_results["converged"] is True

    def test_relative_residual(self, aniso32_results):
        assert aniso32_results["relative_residual"] < 1e-8

    def test_iteration_bound(self, aniso32_results):
        assert aniso32_results["iterations"] <= 100, (
            f"Too many iterations ({aniso32_results['iterations']}); "
            "PGM coarsening should handle anisotropy via strength-based matching"
        )


class TestMeshIndependence:
    """Isotropic diffusion on 64x64 grid — iteration count should stay bounded."""

    def test_converged(self, iso64_results):
        assert iso64_results["converged"] is True

    def test_relative_residual(self, iso64_results):
        assert iso64_results["relative_residual"] < 1e-8

    def test_iteration_bound(self, iso64_results):
        assert iso64_results["iterations"] <= 35, (
            f"Too many iterations ({iso64_results['iterations']}); "
            "AMG should exhibit mesh-independent convergence"
        )

    def test_iteration_growth(self, iso32_results, iso64_results):
        """Iteration count should not grow significantly with grid refinement."""
        growth = iso64_results["iterations"] - iso32_results["iterations"]
        assert growth <= 15, (
            f"Iteration growth {growth} from 32x32 to 64x64 is too large; "
            "AMG convergence should be roughly mesh-independent"
        )


class TestHierarchyQuality:
    """Verify the multigrid hierarchy has reasonable structure."""

    def test_min_levels(self, iso32_results):
        assert iso32_results["n_levels"] >= 3, (
            "AMG hierarchy should have at least 3 levels for 1024 unknowns"
        )

    def test_level_sizes_decreasing(self, iso32_results):
        sizes = iso32_results["level_sizes"]
        for i in range(len(sizes) - 1):
            assert sizes[i] > sizes[i + 1], (
                f"Level sizes must strictly decrease: {sizes}"
            )

    def test_grid_complexity(self, iso32_results):
        gc = iso32_results["grid_complexity"]
        assert 1.3 <= gc <= 4.0, (
            f"Grid complexity {gc} outside expected range [1.3, 4.0]"
        )

    def test_operator_complexity(self, iso32_results):
        oc = iso32_results["operator_complexity"]
        assert 1.0 <= oc <= 10.0, (
            f"Operator complexity {oc} outside expected range [1.0, 10.0]"
        )


class TestSolverExists:
    """Basic sanity checks."""

    def test_solver_file_exists(self):
        assert os.path.isfile("/app/amg_solver.py"), (
            "Solver not found at /app/amg_solver.py"
        )

    def test_matrices_exist(self):
        for name in ["iso_32.mtx", "aniso_32.mtx", "iso_64.mtx"]:
            path = f"/app/data/{name}"
            assert os.path.isfile(path), f"Test matrix not found: {path}"
