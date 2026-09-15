
import sys
import pytest
import numpy as np

sys.path.insert(0, '/app')

from problem import (
    g0, m_wet, m_dry, T_min, T_max, alpha_m,
    x0, r0, v0, z0, rf, vf,
    gamma_gs, tan_gs, tf, N, dt, max_fuel,
    continuous_dynamics,
)


def simulate_rk4(x_init, controls, tf_val, n_steps, substeps=10):
    """Forward-simulate using RK4 with zero-order-hold controls."""
    dt_val = tf_val / n_steps
    h = dt_val / substeps
    x = x_init.copy().astype(np.float64)
    trajectory = [x.copy()]
    for k in range(n_steps):
        u = controls[k].astype(np.float64)
        for _ in range(substeps):
            k1 = continuous_dynamics(x, u)
            k2 = continuous_dynamics(x + 0.5 * h * k1, u)
            k3 = continuous_dynamics(x + 0.5 * h * k2, u)
            k4 = continuous_dynamics(x + h * k3, u)
            x = x + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        trajectory.append(x.copy())
    return np.array(trajectory)


# ---------------------------------------------------------------------------
# Fixtures: solve once, simulate once, reuse across all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def solution():
    """Import and run the optimizer."""
    try:
        from optimizer import solve
    except ImportError as exc:
        pytest.fail(f"Cannot import optimizer.solve: {exc}")
    result = solve()
    assert result is not None, "solve() returned None"
    return result


@pytest.fixture(scope='module')
def simulated(solution):
    """RK4 forward simulation of the returned controls."""
    ctrl = solution['control']
    tf_val = solution['tf']
    return simulate_rk4(x0, ctrl, tf_val, N)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSolutionFormat:
    def test_keys_present(self, solution):
        for key in ('state', 'control', 'sigma', 'tf'):
            assert key in solution, f"Missing key '{key}'"

    def test_shapes(self, solution):
        assert solution['state'].shape == (N + 1, 5), \
            f"state shape {solution['state'].shape} != {(N + 1, 5)}"
        assert solution['control'].shape == (N, 2), \
            f"control shape {solution['control'].shape} != {(N, 2)}"
        assert solution['sigma'].shape == (N,), \
            f"sigma shape {solution['sigma'].shape} != {(N,)}"

    def test_finite_values(self, solution):
        assert np.all(np.isfinite(solution['state'])), "state has non-finite values"
        assert np.all(np.isfinite(solution['control'])), "control has non-finite values"
        assert np.all(np.isfinite(solution['sigma'])), "sigma has non-finite values"


class TestInitialConditions:
    def test_optimizer_initial_state(self, solution):
        np.testing.assert_allclose(
            solution['state'][0], x0, atol=1e-4,
            err_msg="Optimizer initial state does not match x0",
        )


class TestTerminalConditions:
    def test_terminal_position(self, simulated):
        pos_err = np.linalg.norm(simulated[-1, :2] - rf)
        assert pos_err < 0.3, \
            f"Terminal position error {pos_err:.4f} exceeds tolerance 0.3"

    def test_terminal_velocity(self, simulated):
        vel_err = np.linalg.norm(simulated[-1, 2:4] - vf)
        assert vel_err < 0.3, \
            f"Terminal velocity error {vel_err:.4f} exceeds tolerance 0.3"


class TestThrustBounds:
    def test_max_thrust(self, solution):
        ctrl = solution['control']
        for k in range(N):
            mag = np.linalg.norm(ctrl[k])
            assert mag <= T_max + 0.15, \
                f"Max thrust violated at step {k}: ||u||={mag:.4f} > {T_max}"

    def test_min_thrust(self, solution):
        ctrl = solution['control']
        for k in range(N):
            mag = np.linalg.norm(ctrl[k])
            assert mag >= T_min - 0.15, \
                f"Min thrust violated at step {k}: ||u||={mag:.4f} < {T_min}"


class TestGlideslope:
    def test_glideslope_constraint(self, simulated):
        for k in range(N):
            rx, ry = simulated[k, 0], simulated[k, 1]
            required = tan_gs * abs(rx)
            violation = required - ry
            assert violation < 0.25, \
                f"Glideslope violated at step {k}: ry={ry:.4f}, " \
                f"need >= {required:.4f} (violation={violation:.4f})"


class TestMassBounds:
    def test_mass_within_bounds(self, simulated):
        for k in range(N + 1):
            mass = np.exp(simulated[k, 4])
            assert mass >= m_dry - 0.05, \
                f"Mass below m_dry at step {k}: m={mass:.4f}"
            assert mass <= m_wet + 0.05, \
                f"Mass above m_wet at step {k}: m={mass:.4f}"


class TestFuelConsumption:
    def test_fuel_below_threshold(self, simulated):
        final_mass = np.exp(simulated[-1, 4])
        fuel_used = m_wet - final_mass
        assert fuel_used < max_fuel, \
            f"Fuel consumption {fuel_used:.4f} exceeds threshold {max_fuel}"
        assert fuel_used > 0, "Fuel consumption is non-positive (unphysical)"


class TestDynamicsConsistency:
    def test_state_trajectory_consistent(self, solution, simulated):
        """Optimizer's returned state should roughly match RK4 simulation."""
        opt_final = solution['state'][-1, :4]
        sim_final = simulated[-1, :4]
        discrepancy = np.linalg.norm(opt_final - sim_final)
        assert discrepancy < 1.0, \
            f"Large discrepancy between optimizer state and RK4 simulation: {discrepancy:.4f}"

    def test_sigma_consistent_with_control(self, solution):
        """Returned sigma should approximately equal ||u||."""
        ctrl = solution['control']
        sigma = solution['sigma']
        for k in range(N):
            computed = np.linalg.norm(ctrl[k])
            assert abs(computed - sigma[k]) < 0.2, \
                f"sigma[{k}]={sigma[k]:.4f} != ||u[{k}]||={computed:.4f}"
