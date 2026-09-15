"""
Tests for the orbital integration benchmark audit and extension task.

Verifies that /app/results.json contains self-consistent, physically
valid results for all six methods after all defects have been corrected
and method_f has been implemented.  Also verifies /app/convergence.png
and /app/work_precision.csv.
"""
import csv
import json
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, '/app')

METHODS = ["method_a", "method_b", "method_c", "method_d", "method_e", "method_f"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def results():
    with open('/app/results.json', 'r') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. Results structure
# ---------------------------------------------------------------------------

class TestResultsStructure:

    def test_all_convergence_keys(self, results):
        for name in METHODS:
            key = f"{name}_convergence"
            assert key in results, f"Missing key: {key}"

    def test_all_conservation_keys(self, results):
        for name in METHODS:
            key = f"{name}_conservation"
            assert key in results, f"Missing key: {key}"

    def test_convergence_has_errors_and_orders(self, results):
        for name in METHODS:
            conv = results[f"{name}_convergence"]
            assert "errors" in conv and "orders" in conv
            assert len(conv["errors"]) == 5
            assert len(conv["orders"]) == 4

    def test_conservation_has_required_fields(self, results):
        required = [
            "max_energy_error", "max_momentum_error",
            "final_energy_error", "final_momentum_error",
            "energy_drift_rate",
        ]
        for name in METHODS:
            cons = results[f"{name}_conservation"]
            for field in required:
                assert field in cons, f"Missing {field} in {name}_conservation"

    def test_errors_are_positive(self, results):
        for name in METHODS:
            for err in results[f"{name}_convergence"]["errors"]:
                assert err > 0, f"{name}: convergence error must be > 0"

    def test_errors_decrease_monotonically(self, results):
        for name in METHODS:
            errors = results[f"{name}_convergence"]["errors"]
            for i in range(1, len(errors)):
                assert errors[i] < errors[i - 1], (
                    f"{name}: error did not decrease at index {i}: "
                    f"{errors[i]} >= {errors[i-1]}"
                )


# ---------------------------------------------------------------------------
# 2. Convergence orders — median within expected range
# ---------------------------------------------------------------------------

class TestConvergenceOrders:

    def _valid_orders(self, results, name):
        orders = results[f"{name}_convergence"]["orders"]
        return [o for o in orders if not math.isnan(o)]

    def _median(self, results, name):
        valid = self._valid_orders(results, name)
        assert len(valid) >= 2, f"{name}: too few valid order estimates"
        return float(np.median(valid))

    def test_method_b_order(self, results):
        med = self._median(results, "method_b")
        assert 1.5 <= med <= 2.8, (
            f"method_b median order {med:.2f} not in [1.5, 2.8]"
        )

    def test_method_c_order(self, results):
        med = self._median(results, "method_c")
        assert 3.5 <= med <= 4.5, (
            f"method_c median order {med:.2f} not in [3.5, 4.5]"
        )

    def test_method_d_order(self, results):
        med = self._median(results, "method_d")
        assert 3.5 <= med <= 5.0, (
            f"method_d median order {med:.2f} not in [3.5, 5.0]"
        )

    def test_method_e_order(self, results):
        med = self._median(results, "method_e")
        assert 1.5 <= med <= 2.8, (
            f"method_e median order {med:.2f} not in [1.5, 2.8]"
        )

    def test_method_f_order(self, results):
        med = self._median(results, "method_f")
        assert 5.0 <= med <= 7.0, (
            f"method_f median order {med:.2f} not in [5.0, 7.0]"
        )


# ---------------------------------------------------------------------------
# 3. Convergence order consistency — detects wrong formula
# ---------------------------------------------------------------------------

class TestOrderConsistency:
    """Order estimates should be stable across step-size pairs."""

    def _spread(self, results, name):
        orders = results[f"{name}_convergence"]["orders"]
        valid = [o for o in orders if not math.isnan(o)]
        if len(valid) < 2:
            return 0.0
        return max(valid) - min(valid)

    def test_method_c_order_spread(self, results):
        spread = self._spread(results, "method_c")
        assert spread < 1.0, (
            f"method_c order spread {spread:.2f} too large — "
            f"convergence rate formula may be incorrect"
        )

    def test_method_d_order_spread(self, results):
        spread = self._spread(results, "method_d")
        assert spread < 1.0, (
            f"method_d order spread {spread:.2f} too large — "
            f"convergence rate formula may be incorrect"
        )

    def test_method_e_order_spread(self, results):
        spread = self._spread(results, "method_e")
        assert spread < 0.8, (
            f"method_e order spread {spread:.2f} too large"
        )

    def test_method_f_order_spread(self, results):
        spread = self._spread(results, "method_f")
        assert spread < 1.5, (
            f"method_f order spread {spread:.2f} too large"
        )


# ---------------------------------------------------------------------------
# 4. Energy conservation
# ---------------------------------------------------------------------------

class TestEnergyConservation:

    def test_symplectic_energy_bounded(self, results):
        """Structure-preserving methods should have bounded energy error."""
        for name in ["method_b", "method_d", "method_e", "method_f"]:
            err = results[f"{name}_conservation"]["max_energy_error"]
            assert err < 0.1, (
                f"{name} max|dE| = {err:.3e} exceeds 0.1 — "
                f"method may not be structure-preserving"
            )

    def test_symplectic_drift_rate(self, results):
        """Structure-preserving methods should have near-zero energy drift."""
        for name in ["method_b", "method_d", "method_e", "method_f"]:
            drift = abs(results[f"{name}_conservation"]["energy_drift_rate"])
            assert drift < 1e-4, (
                f"{name} drift rate {drift:.3e} too large for "
                f"structure-preserving method"
            )

    def test_method_a_energy_drifts(self, results):
        """First-order explicit method should show measurable energy drift
        over 50 orbits."""
        err = results["method_a_conservation"]["max_energy_error"]
        assert err > 0.1, (
            f"method_a max|dE| = {err:.3e} suspiciously small for "
            f"a non-symplectic first-order method over 50 orbits"
        )


# ---------------------------------------------------------------------------
# 5. Angular momentum conservation
# ---------------------------------------------------------------------------

class TestAngularMomentumConservation:

    def test_symplectic_preserves_angular_momentum(self, results):
        """Symplectic integrators on a central-force problem must conserve
        angular momentum to near machine precision."""
        for name in ["method_b", "method_d", "method_e", "method_f"]:
            err = results[f"{name}_conservation"]["max_momentum_error"]
            assert err < 1e-10, (
                f"{name} max|dL| = {err:.3e} — angular momentum not "
                f"conserved (expected < 1e-10 for symplectic + central force)"
            )

    def test_rk4_angular_momentum_reasonable(self, results):
        err = results["method_c_conservation"]["max_momentum_error"]
        assert err < 0.01, (
            f"method_c max|dL| = {err:.3e} unreasonably large"
        )


# ---------------------------------------------------------------------------
# 6. Direct functional tests (anti-cheat)
# ---------------------------------------------------------------------------

class TestDirectFunctional:
    """Directly test method implementations to prevent hardcoded results."""

    def test_method_b_preserves_angular_momentum(self):
        """method_b must conserve L for a single step on a central force."""
        from methods import method_b
        from physics import force, angular_momentum
        q = np.array([0.4, 0.0])
        p = np.array([0.0, 2.0])
        L0 = angular_momentum(q, p)
        q1, p1 = method_b(q, p, 0.01, force)
        dL = abs(angular_momentum(q1, p1) - L0)
        assert dL < 1e-14, (
            f"method_b single step |dL| = {dL:.3e} — "
            f"splitting is not structure-preserving"
        )

    def test_method_b_second_order_convergence(self):
        """method_b must converge as a second-order method."""
        from methods import method_b, integrate
        from physics import force, Q0, P0, PERIOD
        N1, N2 = 128, 256
        qs1, ps1 = integrate(method_b, Q0, P0, PERIOD / N1, N1, force)
        qs2, ps2 = integrate(method_b, Q0, P0, PERIOD / N2, N2, force)
        err1 = np.sqrt(np.sum((qs1[-1] - Q0)**2) + np.sum((ps1[-1] - P0)**2))
        err2 = np.sqrt(np.sum((qs2[-1] - Q0)**2) + np.sum((ps2[-1] - P0)**2))
        order = np.log(err1 / max(err2, 1e-30)) / np.log(2.0)
        assert order > 1.5, (
            f"method_b convergence order {order:.2f} < 1.5 — not second order"
        )

    def test_method_d_higher_order_than_method_e(self):
        """method_d should converge faster than method_e over one period."""
        from methods import method_d, method_e, integrate
        from physics import force, Q0, P0, PERIOD

        N1, N2 = 64, 128
        qs_d1, ps_d1 = integrate(method_d, Q0, P0, PERIOD / N1, N1, force)
        qs_d2, ps_d2 = integrate(method_d, Q0, P0, PERIOD / N2, N2, force)
        qs_e1, ps_e1 = integrate(method_e, Q0, P0, PERIOD / N1, N1, force)
        qs_e2, ps_e2 = integrate(method_e, Q0, P0, PERIOD / N2, N2, force)

        err_d1 = np.sqrt(np.sum((qs_d1[-1] - Q0)**2) + np.sum((ps_d1[-1] - P0)**2))
        err_d2 = np.sqrt(np.sum((qs_d2[-1] - Q0)**2) + np.sum((ps_d2[-1] - P0)**2))
        err_e1 = np.sqrt(np.sum((qs_e1[-1] - Q0)**2) + np.sum((ps_e1[-1] - P0)**2))
        err_e2 = np.sqrt(np.sum((qs_e2[-1] - Q0)**2) + np.sum((ps_e2[-1] - P0)**2))

        order_d = np.log(err_d1 / max(err_d2, 1e-30)) / np.log(N2 / N1)
        order_e = np.log(err_e1 / max(err_e2, 1e-30)) / np.log(N2 / N1)

        assert order_d > order_e + 1.0, (
            f"method_d order ({order_d:.2f}) should exceed "
            f"method_e order ({order_e:.2f}) by > 1"
        )

    def test_method_d_energy_better_than_method_e(self):
        """method_d should conserve energy better than method_e at same dt."""
        from methods import method_d, method_e, integrate
        from physics import force, hamiltonian, Q0, P0, PERIOD

        dt = PERIOD / 64
        N = 64
        qs_d, ps_d = integrate(method_d, Q0, P0, dt, N, force)
        qs_e, ps_e = integrate(method_e, Q0, P0, dt, N, force)

        dE_d = abs(hamiltonian(qs_d[-1], ps_d[-1]) - hamiltonian(Q0, P0))
        dE_e = abs(hamiltonian(qs_e[-1], ps_e[-1]) - hamiltonian(Q0, P0))

        assert dE_d < dE_e, (
            f"method_d dE ({dE_d:.3e}) should be < method_e dE ({dE_e:.3e})"
        )

    def test_method_f_preserves_angular_momentum(self):
        """method_f must conserve L for a single step on a central force.
        Required for symplecticity on the Kepler problem."""
        from methods import method_f
        from physics import force, angular_momentum
        q = np.array([0.4, 0.0])
        p = np.array([0.0, 2.0])
        L0 = angular_momentum(q, p)
        q1, p1 = method_f(q, p, 0.01, force)
        dL = abs(angular_momentum(q1, p1) - L0)
        assert dL < 1e-14, (
            f"method_f single step |dL| = {dL:.3e} — "
            f"not structure-preserving"
        )

    def test_method_f_higher_order_than_method_d(self):
        """method_f should converge faster than method_d (6th vs 4th order)."""
        from methods import method_d, method_f, integrate
        from physics import force, Q0, P0, PERIOD

        N1, N2 = 128, 256
        qs_d1, ps_d1 = integrate(method_d, Q0, P0, PERIOD / N1, N1, force)
        qs_d2, ps_d2 = integrate(method_d, Q0, P0, PERIOD / N2, N2, force)
        qs_f1, ps_f1 = integrate(method_f, Q0, P0, PERIOD / N1, N1, force)
        qs_f2, ps_f2 = integrate(method_f, Q0, P0, PERIOD / N2, N2, force)

        err_d1 = np.sqrt(np.sum((qs_d1[-1] - Q0)**2) + np.sum((ps_d1[-1] - P0)**2))
        err_d2 = np.sqrt(np.sum((qs_d2[-1] - Q0)**2) + np.sum((ps_d2[-1] - P0)**2))
        err_f1 = np.sqrt(np.sum((qs_f1[-1] - Q0)**2) + np.sum((ps_f1[-1] - P0)**2))
        err_f2 = np.sqrt(np.sum((qs_f2[-1] - Q0)**2) + np.sum((ps_f2[-1] - P0)**2))

        order_d = np.log(err_d1 / max(err_d2, 1e-30)) / np.log(2.0)
        order_f = np.log(err_f1 / max(err_f2, 1e-30)) / np.log(2.0)

        assert order_f > order_d + 1.0, (
            f"method_f order ({order_f:.2f}) should exceed "
            f"method_d order ({order_d:.2f}) by > 1"
        )

    def test_integrate_returns_correct_shape(self):
        from methods import method_a, integrate
        from physics import force
        q0 = np.array([1.0, 0.0])
        p0 = np.array([0.0, 1.0])
        qs, ps = integrate(method_a, q0, p0, 0.1, 10, force)
        assert qs.shape == (11, 2)
        assert ps.shape == (11, 2)

    def test_integrate_preserves_initial_condition(self):
        from methods import method_a, integrate
        from physics import force
        q0 = np.array([0.4, 0.0])
        p0 = np.array([0.0, 2.0])
        qs, ps = integrate(method_a, q0, p0, 0.1, 5, force)
        np.testing.assert_array_almost_equal(qs[0], q0)
        np.testing.assert_array_almost_equal(ps[0], p0)


# ---------------------------------------------------------------------------
# 7. Convergence plot
# ---------------------------------------------------------------------------

class TestConvergencePlot:

    def test_convergence_png_exists(self):
        assert os.path.isfile('/app/convergence.png'), (
            "/app/convergence.png does not exist"
        )

    def test_convergence_png_valid_header(self):
        with open('/app/convergence.png', 'rb') as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', (
            "convergence.png does not have valid PNG magic bytes"
        )

    def test_convergence_png_reasonable_size(self):
        size = os.path.getsize('/app/convergence.png')
        assert size > 5000, (
            f"convergence.png is only {size} bytes — "
            f"expected a non-trivial plot (> 5 KB)"
        )


# ---------------------------------------------------------------------------
# 8. Work-precision CSV
# ---------------------------------------------------------------------------

class TestWorkPrecision:

    @pytest.fixture(scope="class")
    def wp_data(self):
        rows = {}
        with open('/app/work_precision.csv', 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows[row['method']] = row
        return rows

    def test_csv_exists(self):
        assert os.path.isfile('/app/work_precision.csv'), (
            "/app/work_precision.csv does not exist"
        )

    def test_csv_has_all_methods(self, wp_data):
        for name in METHODS:
            assert name in wp_data, f"Missing method {name} in CSV"

    def test_force_evals_per_step_method_a(self, wp_data):
        assert int(wp_data['method_a']['force_evals_per_step']) == 1

    def test_force_evals_per_step_method_b(self, wp_data):
        assert int(wp_data['method_b']['force_evals_per_step']) == 2

    def test_force_evals_per_step_method_c(self, wp_data):
        assert int(wp_data['method_c']['force_evals_per_step']) == 4

    def test_force_evals_per_step_method_d(self, wp_data):
        assert int(wp_data['method_d']['force_evals_per_step']) == 3

    def test_force_evals_per_step_method_e(self, wp_data):
        assert int(wp_data['method_e']['force_evals_per_step']) == 1

    def test_force_evals_per_step_method_f(self, wp_data):
        assert int(wp_data['method_f']['force_evals_per_step']) == 9

    def test_errors_are_positive(self, wp_data):
        for name in METHODS:
            err = float(wp_data[name]['error_at_500_steps'])
            assert err > 0, f"{name}: error_at_500_steps must be > 0"

    def test_method_f_more_accurate_than_d(self, wp_data):
        """Sixth-order method should be more accurate at same step count."""
        err_d = float(wp_data['method_d']['error_at_500_steps'])
        err_f = float(wp_data['method_f']['error_at_500_steps'])
        assert err_f < err_d, (
            f"method_f error ({err_f:.3e}) should be < "
            f"method_d error ({err_d:.3e}) at 500 steps"
        )
