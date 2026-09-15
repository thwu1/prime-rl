"""
Tests for the batch reactor simulation: event detection, trajectory,
Jacobian, and sensitivity analysis verification.

"""
import json
import os
import numpy as np
import pytest
from scipy.integrate import solve_ivp

# ============================================================
# System parameters (ground truth, used for independent verification)
# ============================================================
K1_P1 = 0.04; K2 = 3.0e7; K3_P1 = 1.0e4
K1_P2 = 0.01; K3_P2 = 2.5e3
Q1 = 800.0; Q2 = 2.0e-4; U = 0.1; TC = 290.0; T_CRIT = 375.0
Y0 = np.array([1.0, 0.0, 0.0, 300.0])


def _rhs(t, y, k1, k2, k3, q1=Q1, u=U):
    A, B, C, T = y
    r1 = k1 * A; r2 = k2 * B**2; r3 = k3 * B * C
    return np.array([-r1 + r3, r1 - r2 - r3, r2, q1 * r1 + Q2 * r2 - u * (T - TC)])


def _solve_base(k1p1=K1_P1, k1p2=K1_P2, k2=K2, k3p1=K3_P1, k3p2=K3_P2,
                q1=Q1, u=U):
    """Independently solve the base 4-equation system with event handling."""
    def rhs1(t, y): return _rhs(t, y, k1p1, k2, k3p1, q1, u)
    def rhs2(t, y): return _rhs(t, y, k1p2, k2, k3p2, q1, u)
    def ev(t, y): return y[3] - T_CRIT
    ev.terminal = True; ev.direction = 1

    sol1 = solve_ivp(rhs1, [0, 100], Y0, method='BDF', events=ev,
                     rtol=1e-10, atol=1e-12, max_step=0.5, dense_output=True)
    if len(sol1.t_events[0]) > 0:
        te = float(sol1.t_events[0][0])
        ye = sol1.y_events[0][0]
        sol2 = solve_ivp(rhs2, [te, 100], ye, method='BDF',
                         rtol=1e-10, atol=1e-12, max_step=0.5, dense_output=True)
        return te, ye, sol1, sol2
    return None, None, sol1, None


# ============================================================
# Fixture: load results once
# ============================================================
@pytest.fixture(scope="module")
def results():
    data = {}
    for name in ["trajectory", "events", "sensitivity", "jacobian"]:
        path = f"/app/results/{name}.json"
        assert os.path.exists(path), f"Missing output file: {path}"
        with open(path) as f:
            data[name] = json.load(f)
    return data


@pytest.fixture(scope="module")
def reference():
    te, ye, sol1, sol2 = _solve_base()
    t_eval = np.arange(0, 101, dtype=float)
    traj = np.zeros((101, 4))
    for i, t in enumerate(t_eval):
        if t <= te:
            traj[i] = sol1.sol(t)[:4]
        else:
            traj[i] = sol2.sol(t)[:4]
    return {"event_time": te, "event_state": ye, "trajectory": traj,
            "final_state": sol2.y[:, -1]}


# ============================================================
# Test 1: Output files exist and have correct structure
# ============================================================
class TestOutputFormat:
    def test_trajectory_structure(self, results):
        traj = results["trajectory"]
        assert "times" in traj and "states" in traj
        assert len(traj["times"]) == 101
        assert len(traj["states"]) == 101
        assert all(len(s) == 4 for s in traj["states"])

    def test_events_structure(self, results):
        ev = results["events"]
        assert "event_time" in ev
        assert "state_at_event" in ev
        assert isinstance(ev["event_time"], (int, float))
        assert len(ev["state_at_event"]) == 4

    def test_sensitivity_structure(self, results):
        sens = results["sensitivity"]
        assert "sensitivity_matrix" in sens
        assert "final_state" in sens
        S = sens["sensitivity_matrix"]
        assert len(S) == 4 and all(len(row) == 3 for row in S)
        assert len(sens["final_state"]) == 4

    def test_jacobian_structure(self, results):
        jac = results["jacobian"]
        assert "test_point" in jac
        assert "jacobian" in jac
        assert "nnz" in jac
        J = jac["jacobian"]
        assert len(J) == 4 and all(len(row) == 4 for row in J)


# ============================================================
# Test 2: Mass conservation (A + B + C = 1 at all times)
# ============================================================
class TestMassConservation:
    def test_mass_conserved(self, results):
        states = np.array(results["trajectory"]["states"])
        mass = states[:, 0] + states[:, 1] + states[:, 2]
        np.testing.assert_allclose(mass, 1.0, atol=1e-6,
                                   err_msg="Mass conservation A+B+C=1 violated")


# ============================================================
# Test 3: Event detection
# ============================================================
class TestEventDetection:
    def test_event_time(self, results, reference):
        t_agent = results["events"]["event_time"]
        t_ref = reference["event_time"]
        assert abs(t_agent - t_ref) < 0.01, \
            f"Event time mismatch: agent={t_agent}, reference={t_ref}"

    def test_event_temperature(self, results):
        T_event = results["events"]["state_at_event"][3]
        assert abs(T_event - T_CRIT) < 0.01, \
            f"Temperature at event should be ~375, got {T_event}"

    def test_event_state_accuracy(self, results, reference):
        s_agent = np.array(results["events"]["state_at_event"])
        s_ref = reference["event_state"][:4]
        np.testing.assert_allclose(s_agent[:3], s_ref[:3], rtol=1e-3, atol=1e-6)


# ============================================================
# Test 4: Trajectory accuracy (compare to independent solution)
# ============================================================
class TestTrajectory:
    def test_final_state(self, results, reference):
        s_agent = np.array(results["sensitivity"]["final_state"])
        s_ref = reference["final_state"]
        np.testing.assert_allclose(s_agent, s_ref, rtol=1e-4, atol=1e-8,
                                   err_msg="Final state mismatch")

    def test_trajectory_at_key_times(self, results, reference):
        states = np.array(results["trajectory"]["states"])
        ref = reference["trajectory"]
        for t_idx in [1, 5, 10, 50, 100]:
            np.testing.assert_allclose(
                states[t_idx], ref[t_idx], rtol=1e-3, atol=1e-8,
                err_msg=f"Trajectory mismatch at t={t_idx}")

    def test_temperature_profile(self, results, reference):
        """Temperature should rise, hit 375, then decrease."""
        states = np.array(results["trajectory"]["states"])
        T = states[:, 3]
        assert T[0] == pytest.approx(300.0, abs=0.01)
        assert max(T) >= 374.0
        assert T[-1] < 375.0


# ============================================================
# Test 5: Jacobian correctness (finite-difference verification)
# ============================================================
class TestJacobian:
    def test_jacobian_finite_difference(self, results):
        jac_data = results["jacobian"]
        y_test = np.array(jac_data["test_point"])
        J_agent = np.array(jac_data["jacobian"])

        eps = 1e-7
        J_fd = np.zeros((4, 4))
        for j in range(4):
            y_plus = y_test.copy(); y_plus[j] += eps
            y_minus = y_test.copy(); y_minus[j] -= eps
            f_plus = _rhs(0, y_plus, K1_P1, K2, K3_P1)
            f_minus = _rhs(0, y_minus, K1_P1, K2, K3_P1)
            J_fd[:, j] = (f_plus - f_minus) / (2 * eps)

        np.testing.assert_allclose(J_agent, J_fd, rtol=1e-4, atol=1e-10,
                                   err_msg="Analytical Jacobian does not match FD")

    def test_jacobian_sparsity(self, results):
        jac_data = results["jacobian"]
        assert jac_data["nnz"] == 10, f"Expected 10 nonzeros, got {jac_data['nnz']}"

    def test_jacobian_known_values(self, results):
        """Verify specific entries at test point [0.5, 1e-5, 0.3, 340]."""
        J = np.array(results["jacobian"]["jacobian"])
        assert J[0][0] == pytest.approx(-0.04, abs=1e-10)
        assert J[0][1] == pytest.approx(3000.0, rel=1e-6)
        assert J[3][3] == pytest.approx(-0.1, abs=1e-10)
        assert J[2][0] == pytest.approx(0.0, abs=1e-10)


# ============================================================
# Test 6: Sensitivity correctness (finite-difference verification)
# ============================================================
class TestSensitivity:
    def _fd_sensitivity(self, param_idx, eps=1e-5):
        """Compute sensitivity column via central finite differences."""
        args_plus = [K1_P1, K1_P2, K2, K3_P1, K3_P2, Q1, U]
        args_minus = [K1_P1, K1_P2, K2, K3_P1, K3_P2, Q1, U]

        if param_idx == 0:  # k1_phase1
            args_plus[0] += eps; args_minus[0] -= eps
        elif param_idx == 1:  # Q1
            args_plus[5] += eps; args_minus[5] -= eps
        elif param_idx == 2:  # U
            args_plus[6] += eps; args_minus[6] -= eps

        _, _, sol1p, sol2p = _solve_base(*args_plus)
        yf_plus = sol2p.y[:, -1] if sol2p is not None else sol1p.y[:, -1]

        _, _, sol1m, sol2m = _solve_base(*args_minus)
        yf_minus = sol2m.y[:, -1] if sol2m is not None else sol1m.y[:, -1]

        return (yf_plus - yf_minus) / (2 * eps)

    def test_sensitivity_k1(self, results):
        S_agent = np.array(results["sensitivity"]["sensitivity_matrix"])
        fd = self._fd_sensitivity(0)
        np.testing.assert_allclose(
            S_agent[:, 0], fd, rtol=0.02, atol=1e-7,
            err_msg="Sensitivity w.r.t. k1_phase1 incorrect")

    def test_sensitivity_Q1(self, results):
        S_agent = np.array(results["sensitivity"]["sensitivity_matrix"])
        fd = self._fd_sensitivity(1)
        np.testing.assert_allclose(
            S_agent[:, 1], fd, rtol=0.02, atol=1e-12,
            err_msg="Sensitivity w.r.t. Q1 incorrect")

    def test_sensitivity_U(self, results):
        S_agent = np.array(results["sensitivity"]["sensitivity_matrix"])
        fd = self._fd_sensitivity(2)
        np.testing.assert_allclose(
            S_agent[:, 2], fd, rtol=0.02, atol=1e-9,
            err_msg="Sensitivity w.r.t. U incorrect")

    def test_sensitivity_signs(self, results):
        """Physical sanity: increasing k1 -> more reaction -> less A, more C."""
        S = np.array(results["sensitivity"]["sensitivity_matrix"])
        assert S[0, 0] < 0, "dA/dk1 should be negative (more reaction depletes A)"
        assert S[2, 0] > 0, "dC/dk1 should be positive (more reaction produces C)"
        assert S[3, 2] < 0, "dT/dU should be negative (more cooling lowers T)"

    def test_sensitivity_temperature_to_Q1(self, results):
        """Increasing Q1 should increase final temperature."""
        S = np.array(results["sensitivity"]["sensitivity_matrix"])
        assert S[3, 1] > 0, "dT/dQ1 should be positive"
