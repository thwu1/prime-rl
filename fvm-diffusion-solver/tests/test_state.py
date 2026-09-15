"""
Tests for the FVM diffusion solver benchmark.

Verifies:
  1. results.json format and numerical correctness (convergence, flux, errors)
  2. solver.py produces correct results on an unseen mesh (anti-cheat)
"""


import json
import math
import os
import subprocess
import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_results():
    with open("/app/results.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Test suite 1: convergence study results
# ---------------------------------------------------------------------------

class TestConvergenceStudy:

    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found"

    def test_results_has_required_keys(self):
        r = _load_results()
        for key in ("l2_errors", "mesh_sizes", "convergence_order",
                     "inner_boundary_flux_finest"):
            assert key in r, f"Missing key: {key}"

    def test_l2_errors_length(self):
        r = _load_results()
        assert len(r["l2_errors"]) == 3

    def test_mesh_sizes_length(self):
        r = _load_results()
        assert len(r["mesh_sizes"]) == 3

    def test_errors_positive(self):
        r = _load_results()
        for e in r["l2_errors"]:
            assert e > 0, f"L2 error must be positive, got {e}"

    def test_errors_monotonically_decreasing(self):
        r = _load_results()
        errs = r["l2_errors"]
        assert errs[0] > errs[1] > errs[2], (
            f"Errors must decrease: {errs}"
        )

    def test_convergence_order_in_range(self):
        r = _load_results()
        p = r["convergence_order"]
        assert 1.3 < p < 2.7, (
            f"Convergence order {p:.3f} outside expected range (1.3, 2.7)"
        )

    def test_inner_boundary_flux(self):
        r = _load_results()
        Q = r["inner_boundary_flux_finest"]
        Q_exact = -math.pi
        rel_err = abs(Q - Q_exact) / abs(Q_exact)
        assert rel_err < 0.15, (
            f"Inner flux {Q:.6f} differs from analytical {Q_exact:.6f} "
            f"by {rel_err*100:.1f}%"
        )

    def test_finest_l2_error_bound(self):
        r = _load_results()
        assert r["l2_errors"][2] < 0.1, (
            f"Finest L2 error {r['l2_errors'][2]:.6f} exceeds 0.1"
        )


# ---------------------------------------------------------------------------
# Test suite 2: solver on a new mesh (anti-cheat)
# ---------------------------------------------------------------------------

class TestSolverOnNewMesh:

    def test_solver_script_exists(self):
        assert os.path.isfile("/app/solver.py"), "solver.py not found at /app/"

    def test_solver_on_unseen_mesh(self, tmp_path):
        # Generate a mesh the agent has never seen (level 2, seed 99)
        gen = subprocess.run(
            ["python3", "/app/mesh_generator.py", "2", "99"],
            cwd=str(tmp_path),
            capture_output=True, text=True, timeout=60,
        )
        assert gen.returncode == 0, (
            f"Mesh generation failed: {gen.stderr}"
        )

        mesh_file = str(tmp_path / "mesh_level_2.json")
        out_file = str(tmp_path / "test_output.json")

        # Run the agent's solver
        run = subprocess.run(
            ["python3", "/app/solver.py", mesh_file, out_file],
            capture_output=True, text=True, timeout=120,
        )
        assert run.returncode == 0, (
            f"Solver failed on new mesh: {run.stderr}"
        )

        with open(out_file) as f:
            out = json.load(f)

        # Verify output structure
        assert "l2_error" in out, "Output missing l2_error"
        assert "inner_boundary_flux" in out, "Output missing inner_boundary_flux"
        assert "cell_temperatures" in out, "Output missing cell_temperatures"

        # Verify accuracy on the unseen mesh
        assert out["l2_error"] < 0.1, (
            f"L2 error {out['l2_error']:.6f} too large on new mesh"
        )

        Q = out["inner_boundary_flux"]
        Q_exact = -math.pi
        rel_err = abs(Q - Q_exact) / abs(Q_exact)
        assert rel_err < 0.2, (
            f"Inner flux {Q:.6f} on new mesh differs from {Q_exact:.6f} "
            f"by {rel_err*100:.1f}%"
        )
