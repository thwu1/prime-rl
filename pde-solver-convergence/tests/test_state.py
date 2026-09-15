"""
Tests for the multi-PDE solver suite with convergence verification.

Independently verifies numerical solutions against analytic solutions,
checks convergence rates, and validates physical conservation properties.

"""

import json
import os

import numpy as np
import pytest

RESULTS_PATH = "/app/results.json"
SOLUTIONS_DIR = "/app/solutions"


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ── Structure tests ──────────────────────────────────────────────────────────

class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_solutions_dir_exists(self):
        assert os.path.isdir(SOLUTIONS_DIR)

    def test_all_problems_present(self, results):
        for pid in ["fokker_planck_ou", "nls_soliton", "helmholtz_2d"]:
            assert pid in results, f"Missing problem: {pid}"

    def test_required_fields(self, results):
        for pid in ["fokker_planck_ou", "nls_soliton", "helmholtz_2d"]:
            r = results[pid]
            assert "l2_error" in r, f"{pid}: missing l2_error"
            assert "convergence_rate" in r, f"{pid}: missing convergence_rate"
            assert "convergence_study" in r, f"{pid}: missing convergence_study"
            assert isinstance(r["convergence_study"], list)
            assert len(r["convergence_study"]) >= 3, (
                f"{pid}: convergence_study has {len(r['convergence_study'])} "
                f"entries, need >= 3"
            )

    def test_solution_files_exist(self):
        for fname in [
            "fokker_planck_ou.npz",
            "nls_soliton.npz",
            "helmholtz_2d.npz",
        ]:
            path = os.path.join(SOLUTIONS_DIR, fname)
            assert os.path.exists(path), f"Solution file not found: {path}"


# ── Fokker-Planck tests ─────────────────────────────────────────────────────

class TestFokkerPlanck:
    def test_l2_error_independent(self):
        """Independently verify L2 error against analytic Gaussian solution."""
        data = np.load(os.path.join(SOLUTIONS_DIR, "fokker_planck_ou.npz"))
        u = data["u"]
        x = data["x"]

        # Analytic solution at t=1 for OU process
        mu_0, sigma_sq_0 = 1.0, 0.25
        t = 1.0
        mu_t = mu_0 * np.exp(-t)
        sigma_sq_t = 1.0 + (sigma_sq_0 - 1.0) * np.exp(-2 * t)
        p_exact = (1.0 / np.sqrt(2 * np.pi * sigma_sq_t)) * np.exp(
            -(x - mu_t) ** 2 / (2 * sigma_sq_t)
        )

        l2_error = np.sqrt(np.mean((u - p_exact) ** 2))
        assert l2_error < 5e-3, f"FP L2 error {l2_error:.6e} >= 5e-3"

    def test_non_negative(self):
        """Fokker-Planck solution is a probability density — must be >= 0."""
        data = np.load(os.path.join(SOLUTIONS_DIR, "fokker_planck_ou.npz"))
        u = data["u"]
        assert np.min(u) >= -1e-6, (
            f"FP solution has significant negative values: min={np.min(u):.6e}"
        )

    def test_convergence_rate(self, results):
        rate = results["fokker_planck_ou"]["convergence_rate"]
        assert 1.5 <= rate <= 2.8, (
            f"FP convergence rate {rate:.2f} not in [1.5, 2.8]"
        )

    def test_errors_monotonically_decrease(self, results):
        study = results["fokker_planck_ou"]["convergence_study"]
        sorted_study = sorted(study, key=lambda s: s["resolution"])
        errors = [s["l2_error"] for s in sorted_study]
        for i in range(1, len(errors)):
            assert errors[i] < errors[i - 1], (
                f"FP errors not monotonically decreasing: {errors}"
            )


# ── NLS soliton tests ───────────────────────────────────────────────────────

class TestNLSSoliton:
    def test_l2_error_independent(self):
        """Independently verify L2 error against analytic soliton solution."""
        data = np.load(os.path.join(SOLUTIONS_DIR, "nls_soliton.npz"))
        psi = data["psi"]
        x = data["x"]

        t_final = np.pi
        psi_exact = (1.0 / np.cosh(x)) * np.exp(1j * t_final)

        l2_error = np.sqrt(np.mean(np.abs(psi - psi_exact) ** 2))
        assert l2_error < 1e-2, f"NLS L2 error {l2_error:.6e} >= 1e-2"

    def test_mass_conservation(self):
        """Split-step Fourier should conserve L2 norm to high precision."""
        data = np.load(os.path.join(SOLUTIONS_DIR, "nls_soliton.npz"))
        mass_initial = float(data["mass_initial"])
        mass_final = float(data["mass_final"])

        assert mass_initial > 0, "Initial mass must be positive"
        rel_error = abs(mass_final - mass_initial) / mass_initial
        assert rel_error < 1e-4, (
            f"NLS mass conservation error {rel_error:.6e} >= 1e-4"
        )

    def test_convergence_rate(self, results):
        rate = results["nls_soliton"]["convergence_rate"]
        assert 1.5 <= rate <= 3.5, (
            f"NLS convergence rate {rate:.2f} not in [1.5, 3.5]"
        )

    def test_errors_monotonically_decrease(self, results):
        study = results["nls_soliton"]["convergence_study"]
        sorted_study = sorted(study, key=lambda s: s["resolution"])
        errors = [s["l2_error"] for s in sorted_study]
        for i in range(1, len(errors)):
            assert errors[i] < errors[i - 1], (
                f"NLS errors not monotonically decreasing: {errors}"
            )


# ── Helmholtz 2D tests ──────────────────────────────────────────────────────

class TestHelmholtz2D:
    def test_l2_error_independent(self):
        """Independently verify L2 error against manufactured solution."""
        data = np.load(os.path.join(SOLUTIONS_DIR, "helmholtz_2d.npz"))
        u = data["u"]
        x = data["x"]
        y = data["y"]

        X, Y = np.meshgrid(x, y, indexing="ij")
        u_exact = np.sin(np.pi * X) * np.sin(np.pi * Y)

        l2_error = np.sqrt(np.mean((u - u_exact) ** 2))
        assert l2_error < 1e-4, f"Helmholtz L2 error {l2_error:.6e} >= 1e-4"

    def test_convergence_rate(self, results):
        rate = results["helmholtz_2d"]["convergence_rate"]
        assert 1.5 <= rate <= 2.8, (
            f"Helmholtz convergence rate {rate:.2f} not in [1.5, 2.8]"
        )

    def test_errors_monotonically_decrease(self, results):
        study = results["helmholtz_2d"]["convergence_study"]
        sorted_study = sorted(study, key=lambda s: s["resolution"])
        errors = [s["l2_error"] for s in sorted_study]
        for i in range(1, len(errors)):
            assert errors[i] < errors[i - 1], (
                f"Helmholtz errors not monotonically decreasing: {errors}"
            )
