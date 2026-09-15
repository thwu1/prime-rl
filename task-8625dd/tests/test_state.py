
import sys

sys.path.insert(0, "/app")

import json
import os
import numpy as np
import pytest

from ns2d import NS2DSolver


# ================================================================
# Solver correctness tests (verify bug fixes)
# ================================================================


class TestPoissonSolver:
    """Verify spectral Poisson inversion for known analytical modes."""

    def test_fundamental_mode(self):
        solver = NS2DSolver(N=64, Re=100.0, dt=0.01)
        omega = 2.0 * np.cos(solver.X) * np.cos(solver.Y)
        psi = solver.solve_poisson(omega)
        psi_exact = np.cos(solver.X) * np.cos(solver.Y)
        assert np.max(np.abs(psi - psi_exact)) < 1e-12

    def test_higher_harmonic(self):
        solver = NS2DSolver(N=64, Re=100.0, dt=0.01)
        m, n = 3, 5
        ksq = m ** 2 + n ** 2
        omega = float(ksq) * np.cos(m * solver.X) * np.cos(n * solver.Y)
        psi = solver.solve_poisson(omega)
        psi_exact = np.cos(m * solver.X) * np.cos(n * solver.Y)
        assert np.max(np.abs(psi - psi_exact)) < 1e-11


class TestVelocityField:
    """Verify velocity computation from streamfunction."""

    def test_taylor_green_velocity(self):
        solver = NS2DSolver(N=64, Re=100.0, dt=0.01)
        psi = np.cos(solver.X) * np.cos(solver.Y)
        u, v = solver.compute_velocity(psi)
        u_exact = -np.cos(solver.X) * np.sin(solver.Y)
        v_exact = np.sin(solver.X) * np.cos(solver.Y)
        assert np.max(np.abs(u - u_exact)) < 1e-12
        assert np.max(np.abs(v - v_exact)) < 1e-12


class TestTaylorGreenSimulation:
    """Taylor-Green vortex has exact analytical solution."""

    def test_vorticity_accuracy(self):
        solver = NS2DSolver(N=64, Re=100.0, dt=0.01)
        omega0 = solver.initialize_taylor_green()
        result = solver.run(omega0, T=5.0)
        nu = 1.0 / 100.0
        omega_exact = 2.0 * np.cos(solver.X) * np.cos(solver.Y) * np.exp(
            -2 * nu * 5.0
        )
        linf = np.max(np.abs(result["omega"] - omega_exact))
        assert linf < 1e-6, f"L-inf error = {linf}"

    def test_energy_decay(self):
        solver = NS2DSolver(N=64, Re=100.0, dt=0.01)
        omega0 = solver.initialize_taylor_green()
        result = solver.run(omega0, T=5.0)
        E_exact = 0.25 * np.exp(-4.0 / 100.0 * 5.0)
        rel = abs(result["energies"][-1] - E_exact) / E_exact
        assert rel < 1e-6, f"Energy relative error = {rel}"

    def test_enstrophy_decay(self):
        solver = NS2DSolver(N=64, Re=100.0, dt=0.01)
        omega0 = solver.initialize_taylor_green()
        result = solver.run(omega0, T=5.0)
        Z_exact = 0.5 * np.exp(-4.0 / 100.0 * 5.0)
        rel = abs(result["enstrophies"][-1] - Z_exact) / Z_exact
        assert rel < 1e-6, f"Enstrophy relative error = {rel}"

    def test_initial_energy_value(self):
        solver = NS2DSolver(N=64, Re=100.0, dt=0.01)
        omega0 = solver.initialize_taylor_green()
        E0 = solver.compute_energy(omega0)
        assert abs(E0 - 0.25) < 1e-12, f"E(0) = {E0}, expected 0.25"

    def test_initial_enstrophy_value(self):
        solver = NS2DSolver(N=64, Re=100.0, dt=0.01)
        omega0 = solver.initialize_taylor_green()
        Z0 = solver.compute_enstrophy(omega0)
        assert abs(Z0 - 0.5) < 1e-12, f"Z(0) = {Z0}, expected 0.5"


class TestSSPRK3Convergence:
    """Measure temporal convergence order using three dt values."""

    def test_third_order(self):
        Re, N, T = 100.0, 64, 1.0
        nu = 1.0 / Re
        dts = [0.1, 0.05, 0.025]
        errors = []
        for dt in dts:
            solver = NS2DSolver(N=N, Re=Re, dt=dt)
            omega0 = solver.initialize_taylor_green()
            result = solver.run(omega0, T)
            exact = 2.0 * np.cos(solver.X) * np.cos(solver.Y) * np.exp(
                -2 * nu * T
            )
            errors.append(np.max(np.abs(result["omega"] - exact)))
        order1 = np.log2(errors[0] / errors[1])
        order2 = np.log2(errors[1] / errors[2])
        assert 2.7 < order1 < 3.5, f"Order between dt=0.1 and dt=0.05: {order1}"
        assert 2.7 < order2 < 3.5, f"Order between dt=0.05 and dt=0.025: {order2}"


class TestInviscidConservation:
    """Energy must be conserved in the inviscid limit."""

    def test_energy_conserved(self):
        solver = NS2DSolver(N=64, Re=1e15, dt=0.01)
        omega0 = solver.initialize_taylor_green()
        E0 = solver.compute_energy(omega0)
        result = solver.run(omega0.copy(), T=1.0)
        rel = abs(result["energies"][-1] - E0) / E0
        assert rel < 1e-10, f"Energy relative change = {rel}"


class TestDissipationRelation:
    """Verify the energy-enstrophy dissipation relation."""

    def test_dEdt_equals_minus_2nu_Z(self):
        nu = 0.01
        solver = NS2DSolver(N=64, Re=100.0, dt=0.01)
        omega0 = solver.initialize_taylor_green()
        result = solver.run(omega0, T=1.0)
        E = result["energies"]
        Z = result["enstrophies"]
        dt = 0.01
        max_rel = 0.0
        for i in range(1, len(E)):
            dEdt = (E[i] - E[i - 1]) / dt
            Z_mid = 0.5 * (Z[i] + Z[i - 1])
            expected = -2.0 * nu * Z_mid
            if abs(expected) > 1e-15:
                rel = abs(dEdt - expected) / abs(expected)
                max_rel = max(max_rel, rel)
        assert max_rel < 1e-3, f"Max dissipation relation error = {max_rel}"


class TestEnergySpectrum:
    """Energy spectrum shell-summation properties."""

    def test_taylor_green_all_energy_at_k1(self):
        solver = NS2DSolver(N=64, Re=100.0, dt=0.01)
        omega = solver.initialize_taylor_green()
        spectrum = solver.compute_energy_spectrum(omega)
        E_total = solver.compute_energy(omega)
        assert abs(spectrum[1] - E_total) / E_total < 1e-10, (
            f"E(k=1) = {spectrum[1]}, E_total = {E_total}"
        )
        for k in range(2, len(spectrum)):
            assert spectrum[k] < 1e-20, f"E(k={k}) = {spectrum[k]} should be ~0"

    def test_spectrum_sums_to_total_energy(self):
        solver = NS2DSolver(N=64, Re=100.0, dt=0.01)
        omega = solver.initialize_taylor_green()
        spectrum = solver.compute_energy_spectrum(omega)
        E_total = solver.compute_energy(omega)
        assert abs(np.sum(spectrum) - E_total) / E_total < 1e-10


# ================================================================
# Convergence verification evaluation tests
# ================================================================


class TestConvergenceEvaluation:
    """Verify the convergence evaluation report is well-formed and accurate."""

    def test_file_exists_and_top_level_structure(self):
        path = "/app/results/convergence_eval.json"
        assert os.path.exists(path), "convergence_eval.json not found at /app/results/"
        with open(path) as f:
            data = json.load(f)
        assert "temporal" in data, "Missing 'temporal' section in convergence_eval.json"
        assert "spatial" in data, "Missing 'spatial' section in convergence_eval.json"

    def test_temporal_convergence_structure_and_orders(self):
        with open("/app/results/convergence_eval.json") as f:
            data = json.load(f)
        t = data["temporal"]
        for key in ["timesteps", "errors", "convergence_orders",
                     "theoretical_order", "matches_theory", "conclusion"]:
            assert key in t, f"Missing key '{key}' in temporal section"
        assert len(t["timesteps"]) >= 4, \
            f"Need >= 4 timestep values, found {len(t['timesteps'])}"
        assert len(t["errors"]) == len(t["timesteps"]), \
            "timesteps and errors arrays must have same length"
        assert len(t["convergence_orders"]) >= 2, \
            "Need >= 2 convergence order measurements"
        for order in t["convergence_orders"]:
            assert 2.5 < order < 3.5, \
                f"Temporal convergence order {order:.3f} outside [2.5, 3.5]"
        assert t["theoretical_order"] == 3
        assert t["matches_theory"] is True, \
            "matches_theory should be True for a correctly fixed SSP-RK3 solver"
        assert isinstance(t["conclusion"], str) and len(t["conclusion"]) > 30, \
            "Conclusion must be a substantive string (>30 chars)"

    def test_temporal_errors_spot_check(self):
        """Independently verify one reported temporal error value."""
        with open("/app/results/convergence_eval.json") as f:
            data = json.load(f)
        t = data["temporal"]
        # Pick the first reported timestep for verification
        dt_check = t["timesteps"][0]
        reported = t["errors"][0]
        assert dt_check > 0, "Timestep must be positive"
        solver = NS2DSolver(N=64, Re=100.0, dt=dt_check)
        omega0 = solver.initialize_taylor_green()
        nsteps = int(round(1.0 / dt_check))
        assert nsteps >= 1, "Need at least 1 timestep for T=1.0"
        result = solver.run(omega0, T=1.0)
        nu = 0.01
        exact = 2.0 * np.cos(solver.X) * np.cos(solver.Y) * np.exp(-2 * nu)
        actual = float(np.max(np.abs(result["omega"] - exact)))
        if reported > 1e-14:
            rel_diff = abs(actual - reported) / reported
            assert rel_diff < 0.2, \
                f"Spot-check failed: reported error {reported:.3e}, measured {actual:.3e}"
        else:
            assert actual < 1e-12, \
                f"Both errors should be near machine precision, got {actual:.3e}"

    def test_spatial_evaluation_structure(self):
        with open("/app/results/convergence_eval.json") as f:
            data = json.load(f)
        s = data["spatial"]
        for key in ["resolutions", "errors", "is_spectral", "justification"]:
            assert key in s, f"Missing key '{key}' in spatial section"
        assert len(s["resolutions"]) >= 3, \
            f"Need >= 3 resolutions, found {len(s['resolutions'])}"
        assert len(s["errors"]) == len(s["resolutions"]), \
            "resolutions and errors arrays must have same length"
        assert isinstance(s["is_spectral"], bool)
        assert isinstance(s["justification"], str) and len(s["justification"]) > 30, \
            "Justification must be a substantive string (>30 chars)"
        for e in s["errors"]:
            assert isinstance(e, (int, float)) and e >= 0, \
                f"Spatial error must be non-negative number, got {e}"


# ================================================================
# Comparative parameter estimation tests
# ================================================================


class TestEstimationComparison:
    """Verify comparative parameter estimation report."""

    def test_file_exists_and_structure(self):
        path = "/app/results/estimation_comparison.json"
        assert os.path.exists(path), "estimation_comparison.json not found"
        with open(path) as f:
            data = json.load(f)
        for key in ["methods", "best_method", "best_estimate",
                     "recommendation_rationale"]:
            assert key in data, f"Missing key '{key}' in estimation_comparison.json"

    def test_multiple_distinct_methods(self):
        with open("/app/results/estimation_comparison.json") as f:
            data = json.load(f)
        methods = data["methods"]
        assert len(methods) >= 2, f"Need >= 2 estimation methods, found {len(methods)}"
        names = [m["name"] for m in methods]
        assert len(set(names)) == len(names), \
            f"Method names must be unique, got: {names}"
        for m in methods:
            assert "name" in m and isinstance(m["name"], str) and len(m["name"]) > 0
            assert "estimated_Re" in m and isinstance(m["estimated_Re"], (int, float))
            assert "residual_norm" in m and isinstance(m["residual_norm"], (int, float))
            assert m["estimated_Re"] > 0, \
                f"estimated_Re must be positive, got {m['estimated_Re']}"

    def test_best_estimate_accuracy(self):
        with open("/app/results/estimation_comparison.json") as f:
            data = json.load(f)
        Re_true = 237.5
        rel_err = abs(data["best_estimate"] - Re_true) / Re_true
        assert rel_err < 0.01, (
            f"Best estimate {data['best_estimate']:.4f} is "
            f"{rel_err * 100:.2f}% off from true value"
        )

    def test_best_method_appears_in_methods(self):
        with open("/app/results/estimation_comparison.json") as f:
            data = json.load(f)
        names = [m["name"] for m in data["methods"]]
        assert data["best_method"] in names, (
            f"best_method '{data['best_method']}' not in methods list: {names}"
        )

    def test_recommendation_rationale_substantive(self):
        with open("/app/results/estimation_comparison.json") as f:
            data = json.load(f)
        r = data["recommendation_rationale"]
        assert isinstance(r, str) and len(r) > 50, (
            "recommendation_rationale must be a substantive explanation (>50 chars)"
        )


# ================================================================
# Output file existence and format tests
# ================================================================


class TestOutputFiles:
    """Verify required output files exist with correct format."""

    def test_bug_report_exists_and_valid(self):
        path = "/app/results/bug_report.json"
        assert os.path.exists(path), "bug_report.json not found at /app/results/"
        with open(path) as f:
            report = json.load(f)
        assert isinstance(report, list), "bug_report.json must be a JSON array"
        assert len(report) >= 3, f"Expected at least 3 bug entries, found {len(report)}"
        for i, entry in enumerate(report):
            assert "module" in entry, f"Entry {i} missing 'module' key"
            assert "description" in entry, f"Entry {i} missing 'description' key"
            assert "fix" in entry, f"Entry {i} missing 'fix' key"
            assert isinstance(entry["module"], str) and len(entry["module"]) > 0
            assert isinstance(entry["description"], str) and len(entry["description"]) > 0
            assert isinstance(entry["fix"], str) and len(entry["fix"]) > 0

    def test_estimated_re(self):
        path = "/app/results/estimated_Re.txt"
        assert os.path.exists(path), "estimated_Re.txt not found at /app/results/"
        with open(path) as f:
            content = f.read().strip()
        Re_est = float(content)
        Re_true = 237.5
        rel_err = abs(Re_est - Re_true) / Re_true
        assert rel_err < 0.01, (
            f"Re estimate {Re_est:.4f} is {rel_err * 100:.2f}% off from true value"
        )
