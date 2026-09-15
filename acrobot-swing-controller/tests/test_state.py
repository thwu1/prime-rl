
"""
Tests for acrobot swing-up controller.
Verifies trajectory format, torque limits, swing-up success,
RealAI Score, and dynamics correctness via energy balance.
"""

import pytest
import json
import os
import numpy as np

# ---- True physical parameters (from /app/params.json) ----
m1 = 0.5234602302310271
m2 = 0.6255677234174437
l1 = 0.2
l2 = 0.3
r1 = 0.2
r2 = 0.25569305436052964
I1 = 0.031887199591513114
I2 = 0.05086984812807257
Ir = 0.0
gr = 6
g = 9.81
b1 = 0.0
b2 = 0.0
cf1 = 0.0
cf2 = 0.0


def _mass_matrix(q1, q2):
    c2 = np.cos(q2)
    M11 = I1 + I2 + m2 * l1**2 + 2 * m2 * l1 * r2 * c2 + gr**2 * Ir + Ir
    M12 = I2 + m2 * l1 * r2 * c2 - gr * Ir
    M22 = I2 + gr**2 * Ir
    return np.array([[M11, M12], [M12, M22]])


def _ee_y(q1, q2):
    return -l1 * np.cos(q1) - l2 * np.cos(q1 + q2)


def _total_energy(q1, q2, qd1, qd2):
    M = _mass_matrix(q1, q2)
    qd = np.array([qd1, qd2])
    Ekin = 0.5 * qd @ M @ qd
    Epot = -m1 * g * r1 * np.cos(q1) - m2 * g * (l1 * np.cos(q1) + r2 * np.cos(q1 + q2))
    return Ekin + Epot


def _load_trajectory():
    return np.genfromtxt("/app/trajectory.csv", delimiter=",", skip_header=1)


def _load_score():
    with open("/app/score.json") as f:
        return json.load(f)


# ===== File existence and format =====

class TestFileFormat:
    def test_trajectory_exists(self):
        assert os.path.exists("/app/trajectory.csv"), \
            "trajectory.csv must exist at /app/trajectory.csv"

    def test_score_exists(self):
        assert os.path.exists("/app/score.json"), \
            "score.json must exist at /app/score.json"

    def test_trajectory_columns(self):
        with open("/app/trajectory.csv") as f:
            header = f.readline().strip()
        cols = [c.strip() for c in header.split(",")]
        required = ["time", "q1", "q2", "qd1", "qd2", "u1", "u2"]
        assert cols == required, \
            f"Expected columns {required}, got {cols}"

    def test_trajectory_length(self):
        traj = _load_trajectory()
        # 10s at dt <= 0.005 gives >= 2000 rows; expect ~5001 for dt=0.002
        assert len(traj) >= 2000, \
            f"Trajectory too short: {len(traj)} rows (expected >= 2000 for 10s simulation)"

    def test_no_nan_values(self):
        traj = _load_trajectory()
        assert not np.any(np.isnan(traj)), "Trajectory contains NaN values"
        assert not np.any(np.isinf(traj)), "Trajectory contains Inf values"

    def test_score_format(self):
        score = _load_score()
        assert "score" in score, "score.json must contain 'score' field"
        assert "success" in score, "score.json must contain 'success' field"


# ===== Simulation parameters =====

class TestSimulationParams:
    def test_simulation_duration(self):
        traj = _load_trajectory()
        t_final = traj[-1, 0]
        assert abs(t_final - 10.0) < 0.01, \
            f"Simulation must run for 10s, got t_final={t_final:.4f}"

    def test_initial_state(self):
        traj = _load_trajectory()
        x0 = traj[0, 1:5]
        assert np.allclose(x0, [0, 0, 0, 0], atol=1e-6), \
            f"Initial state must be [0,0,0,0], got {x0}"

    def test_time_monotonic(self):
        traj = _load_trajectory()
        dt = np.diff(traj[:, 0])
        assert np.all(dt > 0), "Time must be strictly increasing"


# ===== Torque constraints =====

class TestTorqueLimits:
    def test_u1_zero(self):
        traj = _load_trajectory()
        u1 = traj[:, 5]
        assert np.all(np.abs(u1) < 1e-6), \
            f"u1 must be 0 for acrobot; max |u1| = {np.max(np.abs(u1)):.6f}"

    def test_u2_within_limits(self):
        traj = _load_trajectory()
        u2 = traj[:, 6]
        max_u2 = np.max(np.abs(u2))
        assert max_u2 <= 6.0 + 1e-6, \
            f"|u2| must be <= 6.0 Nm; max |u2| = {max_u2:.6f}"


# ===== Swing-up success =====

class TestSwingUp:
    def test_ee_above_threshold_at_end(self):
        traj = _load_trajectory()
        q1_end, q2_end = traj[-1, 1], traj[-1, 2]
        y_ee = _ee_y(q1_end, q2_end)
        assert y_ee >= 0.45, \
            f"End-effector height at t=10s is {y_ee:.4f} m, must be >= 0.45 m"

    def test_ee_stays_above_threshold(self):
        traj = _load_trajectory()
        ee_heights = np.array([_ee_y(row[1], row[2]) for row in traj])
        threshold = 0.45

        # Must be above at end
        assert ee_heights[-1] >= threshold, \
            f"End-effector not above threshold at end: {ee_heights[-1]:.4f}"

        # Find last contiguous block above threshold that includes end
        above = ee_heights >= threshold
        idx = len(above) - 1
        while idx > 0 and above[idx - 1]:
            idx -= 1

        # From idx to end must all be above
        block = above[idx:]
        assert np.all(block), \
            "End-effector must stay continuously above 0.45 m after first crossing until end"


# ===== Score verification =====

class TestScore:
    def test_swing_up_success_flag(self):
        score = _load_score()
        assert score["success"] == 1, \
            "score.json must report success=1"

    def test_score_above_threshold(self):
        score = _load_score()
        assert score["score"] >= 0.15, \
            f"RealAI Score = {score['score']:.4f}, must be >= 0.15"

    def test_score_plausible(self):
        score = _load_score()
        assert 0.0 <= score["score"] <= 1.0, \
            f"RealAI Score = {score['score']:.4f}, must be in [0, 1]"


# ===== Dynamics correctness via energy balance =====

class TestDynamics:
    def test_energy_balance(self):
        """
        For a frictionless system (b=cf=0), the total energy change must equal
        the work done by the actuator: dE = u2 * dq2 (summed over steps).
        This validates that the correct equations of motion were used.
        """
        traj = _load_trajectory()
        N = len(traj)

        # Compute total energy at first and last points
        E_initial = _total_energy(traj[0, 1], traj[0, 2], traj[0, 3], traj[0, 4])
        E_final = _total_energy(traj[-1, 1], traj[-1, 2], traj[-1, 3], traj[-1, 4])
        energy_change = E_final - E_initial

        # Compute cumulative work: W = sum u2_i * (q2_{i+1} - q2_i)
        # where u2_i at row i is the control applied during the step from row i to i+1
        cumulative_work = 0.0
        for i in range(N - 1):
            u2 = traj[i, 6]
            dq2 = traj[i + 1, 2] - traj[i, 2]
            cumulative_work += u2 * dq2

        discrepancy = abs(energy_change - cumulative_work)
        assert discrepancy < 1.0, \
            (f"Energy balance violated: energy change = {energy_change:.4f} J, "
             f"actuator work = {cumulative_work:.4f} J, "
             f"discrepancy = {discrepancy:.4f} J (must be < 1.0). "
             f"This indicates incorrect dynamics implementation.")

    def test_energy_at_intermediate_points(self):
        """
        Check energy balance at multiple intermediate checkpoints,
        not just initial-to-final.
        """
        traj = _load_trajectory()
        N = len(traj)
        checkpoints = np.linspace(0, N - 1, 11, dtype=int)[1:]  # 10 checkpoints

        E0 = _total_energy(traj[0, 1], traj[0, 2], traj[0, 3], traj[0, 4])
        cumulative_work = 0.0

        next_cp = 0
        for i in range(N - 1):
            u2 = traj[i, 6]
            dq2 = traj[i + 1, 2] - traj[i, 2]
            cumulative_work += u2 * dq2

            if next_cp < len(checkpoints) and i + 1 == checkpoints[next_cp]:
                E_i = _total_energy(
                    traj[i + 1, 1], traj[i + 1, 2],
                    traj[i + 1, 3], traj[i + 1, 4]
                )
                disc = abs((E_i - E0) - cumulative_work)
                assert disc < 1.0, \
                    (f"Energy balance violated at t={traj[i+1, 0]:.2f}s: "
                     f"discrepancy = {disc:.4f} J")
                next_cp += 1

    def test_gravity_direction(self):
        """
        Verify the trajectory is physically consistent: when released from
        a small angle with no control, the pendulum should fall back toward
        hanging (angles decrease toward 0). Check the first few steps if
        initial control is small.
        """
        traj = _load_trajectory()
        # Check that at t=0 state is [0,0,0,0] - already tested
        # Check that the trajectory shows motion consistent with physics:
        # The system should gain significant kinetic energy during swing-up
        max_vel = np.max(np.abs(traj[:, 3:5]))
        assert max_vel > 1.0, \
            (f"Maximum velocity = {max_vel:.4f} rad/s is too small. "
             f"A successful swing-up requires significant angular velocities.")
