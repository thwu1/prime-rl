
import os
import sys
import json
import csv
import pytest
import numpy as np

sys.path.insert(0, '/app')

from core import GAMMA, cons2prim, prim2cons, euler_flux


# ============================================================
# Weighted mean (ln_mean)
# ============================================================

class TestWeightedMean:
    def test_symmetry(self):
        from fluxes import ln_mean
        assert abs(ln_mean(2.0, 3.0) - ln_mean(3.0, 2.0)) < 1e-14

    def test_equal_values(self):
        from fluxes import ln_mean
        assert abs(ln_mean(5.0, 5.0) - 5.0) < 1e-12

    def test_nearly_equal(self):
        from fluxes import ln_mean
        a, b = 1.0, 1.0 + 1e-10
        result = ln_mean(a, b)
        assert abs(result - 1.0) < 1e-6

    def test_known_value(self):
        from fluxes import ln_mean
        a, b = 1.0, np.e
        expected = (np.e - 1.0) / 1.0  # (e-1)/(ln e - ln 1)
        assert abs(ln_mean(a, b) - expected) < 1e-12

    def test_bounds(self):
        """ln_mean(a,b) lies between min(a,b) and arithmetic mean."""
        from fluxes import ln_mean
        a, b = 2.0, 8.0
        lm = ln_mean(a, b)
        assert lm >= min(a, b) - 1e-14
        assert lm <= 0.5 * (a + b) + 1e-14


# ============================================================
# Entropy-conservative flux
# ============================================================

class TestEntropyConservativeFlux:
    def test_consistency(self):
        """ec_flux(u, u) must equal euler_flux(u) (consistency)."""
        from fluxes import ec_flux
        u = prim2cons(1.0, 0.5, 1.0)
        f_ec = ec_flux(u, u)
        f_ex = euler_flux(u)
        np.testing.assert_allclose(f_ec, f_ex, atol=1e-12)

    def test_consistency_different_state(self):
        from fluxes import ec_flux
        u = prim2cons(2.5, -0.7, 3.2)
        f_ec = ec_flux(u, u)
        f_ex = euler_flux(u)
        np.testing.assert_allclose(f_ec, f_ex, atol=1e-12)

    def test_symmetry(self):
        """ec_flux(u_L, u_R) == ec_flux(u_R, u_L) (symmetric two-point flux)."""
        from fluxes import ec_flux
        u_L = prim2cons(1.0, 0.3, 1.0)
        u_R = prim2cons(2.0, 0.5, 1.5)
        f_LR = ec_flux(u_L, u_R)
        f_RL = ec_flux(u_R, u_L)
        np.testing.assert_allclose(f_LR, f_RL, atol=1e-12)

    def test_entropy_conservation(self):
        """Must satisfy (w_R - w_L)^T f_ec = psi_R - psi_L."""
        from fluxes import ec_flux

        u_L = prim2cons(1.2, 0.3, 1.1)
        u_R = prim2cons(0.8, -0.2, 0.9)

        f_ec = ec_flux(u_L, u_R)

        def entropy_vars(u):
            rho, v, p = cons2prim(u)
            beta = rho / (2.0 * p)
            s = np.log(p) - GAMMA * np.log(rho)
            w1 = (GAMMA - s) / (GAMMA - 1.0) - beta * v**2
            w2 = 2.0 * beta * v
            w3 = -2.0 * beta
            return np.array([w1, w2, w3])

        w_L = entropy_vars(u_L)
        w_R = entropy_vars(u_R)

        rho_L, v_L, _ = cons2prim(u_L)
        rho_R, v_R, _ = cons2prim(u_R)
        psi_L = rho_L * v_L
        psi_R = rho_R * v_R

        lhs = np.dot(w_R - w_L, f_ec)
        rhs = psi_R - psi_L

        assert abs(lhs - rhs) < 1e-10, \
            f"Entropy conservation violated: {lhs:.12e} != {rhs:.12e}"

    def test_entropy_conservation_second(self):
        """Entropy conservation with a different pair of states."""
        from fluxes import ec_flux

        u_L = prim2cons(0.5, 1.2, 2.0)
        u_R = prim2cons(1.5, -0.8, 0.5)

        f_ec = ec_flux(u_L, u_R)

        def entropy_vars(u):
            rho, v, p = cons2prim(u)
            beta = rho / (2.0 * p)
            s = np.log(p) - GAMMA * np.log(rho)
            w1 = (GAMMA - s) / (GAMMA - 1.0) - beta * v**2
            w2 = 2.0 * beta * v
            w3 = -2.0 * beta
            return np.array([w1, w2, w3])

        w_L = entropy_vars(u_L)
        w_R = entropy_vars(u_R)

        rho_L, v_L, _ = cons2prim(u_L)
        rho_R, v_R, _ = cons2prim(u_R)

        lhs = np.dot(w_R - w_L, f_ec)
        rhs = (rho_R * v_R) - (rho_L * v_L)

        assert abs(lhs - rhs) < 1e-10, \
            f"Entropy conservation violated: {lhs:.12e} != {rhs:.12e}"


# ============================================================
# Riemann solver flux
# ============================================================

class TestRiemannSolverFlux:
    def test_consistency(self):
        """rs_flux(u, u) must equal euler_flux(u)."""
        from fluxes import rs_flux
        u = prim2cons(1.0, 0.5, 1.0)
        f_rs = rs_flux(u, u)
        f_ex = euler_flux(u)
        np.testing.assert_allclose(f_rs, f_ex, atol=1e-12)

    def test_consistency_stationary(self):
        from fluxes import rs_flux
        u = prim2cons(1.4, 0.0, 2.0)
        f_rs = rs_flux(u, u)
        f_ex = euler_flux(u)
        np.testing.assert_allclose(f_rs, f_ex, atol=1e-12)

    def test_isolated_contact(self):
        """Must exactly resolve an isolated contact (same v, p)."""
        from fluxes import rs_flux
        v, p = 0.5, 1.0
        u_L = prim2cons(1.0, v, p)
        u_R = prim2cons(2.0, v, p)
        f_rs = rs_flux(u_L, u_R)
        f_exact = euler_flux(u_L)
        np.testing.assert_allclose(f_rs, f_exact, atol=1e-10)

    def test_isolated_contact_negative_v(self):
        """Contact with v < 0: right state is upwind."""
        from fluxes import rs_flux
        v, p = -0.3, 1.5
        u_L = prim2cons(1.0, v, p)
        u_R = prim2cons(3.0, v, p)
        f_rs = rs_flux(u_L, u_R)
        f_exact = euler_flux(u_R)
        np.testing.assert_allclose(f_rs, f_exact, atol=1e-10)

    def test_supersonic_left(self):
        """Supersonic flow to the right: flux = f(u_L)."""
        from fluxes import rs_flux
        u_L = prim2cons(1.0, 5.0, 1.0)  # v >> a
        u_R = prim2cons(0.5, 5.0, 0.5)
        f_rs = rs_flux(u_L, u_R)
        f_ex = euler_flux(u_L)
        np.testing.assert_allclose(f_rs, f_ex, atol=1e-10)


# ============================================================
# Convergence study results
# ============================================================

class TestConvergence:
    def test_results_exist(self):
        assert os.path.exists('/app/results/convergence.json'), \
            "convergence.json not found -- run the simulation first"

    def test_convergence_order(self):
        """Empirical order must be ~N+1 for the last two refinement levels."""
        with open('/app/results/convergence.json') as f:
            data = json.load(f)
        orders = data['orders']
        N = data['polynomial_degree']
        expected = N + 1
        assert len(orders) >= 2, "Need at least 3 mesh levels"
        for order in orders[-2:]:
            assert order > expected - 0.5, \
                f"Order {order:.2f} too low (expected ~{expected})"
            assert order < expected + 1.0, \
                f"Order {order:.2f} too high (expected ~{expected})"

    def test_errors_decrease(self):
        """Errors must decrease monotonically with refinement."""
        with open('/app/results/convergence.json') as f:
            data = json.load(f)
        errors = data['errors']
        for i in range(1, len(errors)):
            assert errors[i] < errors[i - 1], \
                f"Error did not decrease: {errors[i]} >= {errors[i-1]}"


# ============================================================
# Sod shock tube results
# ============================================================

class TestSodSolution:
    @staticmethod
    def _load():
        with open('/app/results/sod_solution.csv') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return {
            'x': np.array([float(r['x']) for r in rows]),
            'rho': np.array([float(r['rho']) for r in rows]),
            'v': np.array([float(r['v']) for r in rows]),
            'p': np.array([float(r['p']) for r in rows]),
        }

    def test_file_exists(self):
        assert os.path.exists('/app/results/sod_solution.csv'), \
            "sod_solution.csv not found -- run the simulation first"

    def test_left_state_preserved(self):
        """Undisturbed left state (x < 0.2) should be rho~1, v~0, p~1."""
        d = self._load()
        mask = d['x'] < 0.2
        assert np.sum(mask) > 5
        assert np.mean(np.abs(d['rho'][mask] - 1.0)) < 0.05
        assert np.mean(np.abs(d['v'][mask])) < 0.05
        assert np.mean(np.abs(d['p'][mask] - 1.0)) < 0.05

    def test_right_state_preserved(self):
        """Undisturbed right state (x > 0.92) should be rho~0.125, v~0, p~0.1."""
        d = self._load()
        mask = d['x'] > 0.92
        assert np.sum(mask) > 5
        assert np.mean(np.abs(d['rho'][mask] - 0.125)) < 0.05
        assert np.mean(np.abs(d['v'][mask])) < 0.05
        assert np.mean(np.abs(d['p'][mask] - 0.1)) < 0.05

    def test_positive_quantities(self):
        """All densities and pressures must be positive."""
        d = self._load()
        assert np.all(d['rho'] > 0), "Negative density detected"
        assert np.all(d['p'] > 0), "Negative pressure detected"

    def test_mass_conservation(self):
        """Total mass should be conserved (initial = 0.5*1 + 0.5*0.125 = 0.5625)."""
        d = self._load()
        mass = np.trapz(d['rho'], d['x'])
        assert abs(mass - 0.5625) < 0.02, \
            f"Mass not conserved: {mass:.4f} vs 0.5625"

    def test_density_structure(self):
        """Density should decrease on average from left to right."""
        d = self._load()
        n = len(d['rho'])
        left_avg = np.mean(d['rho'][:n // 4])
        right_avg = np.mean(d['rho'][3 * n // 4:])
        assert left_avg > right_avg, "Density structure is wrong"


# ============================================================
# Post-processing pipeline outputs
# ============================================================

class TestReport:
    def test_report_exists(self):
        assert os.path.exists('/app/results/report.json'), \
            "report.json not found -- complete and run the Makefile report target"

    def test_report_keys(self):
        with open('/app/results/report.json') as f:
            data = json.load(f)
        for key in ('mean_order', 'max_error', 'min_error', 'num_levels'):
            assert key in data, f"Missing key '{key}' in report.json"

    def test_report_values_reasonable(self):
        with open('/app/results/report.json') as f:
            data = json.load(f)
        assert 3.0 < data['mean_order'] < 5.5, \
            f"mean_order {data['mean_order']} out of expected range"
        assert data['max_error'] > data['min_error'], \
            "max_error should exceed min_error"
        assert data['num_levels'] == 4, \
            f"num_levels should be 4, got {data['num_levels']}"

    def test_report_cross_check(self):
        """Report mean_order must match convergence.json data."""
        with open('/app/results/convergence.json') as f:
            conv = json.load(f)
        with open('/app/results/report.json') as f:
            report = json.load(f)
        expected_mean = sum(conv['orders']) / len(conv['orders'])
        assert abs(report['mean_order'] - expected_mean) < 0.01, \
            f"mean_order mismatch: report={report['mean_order']}, expected={expected_mean}"


class TestValidation:
    def test_validation_exists(self):
        assert os.path.exists('/app/results/validation.txt'), \
            "validation.txt not found -- complete and run the Makefile validate target"

    def test_validation_pass(self):
        with open('/app/results/validation.txt') as f:
            content = f.read().strip()
        assert content == "PASS", \
            f"Expected 'PASS' in validation.txt, got '{content}'"


class TestMakefileTools:
    def _non_comment_content(self):
        with open('/app/Makefile') as f:
            lines = f.readlines()
        return ''.join(l for l in lines if not l.strip().startswith('#'))

    def test_no_stubs(self):
        with open('/app/Makefile') as f:
            content = f.read()
        assert 'STUB' not in content, \
            "Makefile still has STUB placeholders -- complete report and validate targets"

    def test_jq_used(self):
        """The report target must use jq for JSON processing."""
        content = self._non_comment_content()
        assert 'jq' in content, \
            "Makefile report target must use jq for JSON transformation"

    def test_awk_used(self):
        """The validate target must use awk for CSV processing."""
        content = self._non_comment_content()
        assert 'awk' in content, \
            "Makefile validate target must use awk for CSV validation"
