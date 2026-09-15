
import pytest
import numpy as np
import csv
import json
import os
import sys

sys.path.insert(0, '/app')


def read_csv(filepath):
    """Read a CSV file and return list of float lists."""
    rows = []
    with open(filepath, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            stripped = [v.strip() for v in row if v.strip()]
            if stripped:
                rows.append([float(v) for v in stripped])
    return rows


def read_config():
    with open('/app/config.json', 'r') as f:
        return json.load(f)


class TestTrajectoryFormat:
    """Verify output files exist with correct dimensions."""

    def test_trajectory_exists(self):
        assert os.path.exists('/app/output/trajectory.csv'), \
            "trajectory.csv not found at /app/output/"

    def test_error_log_exists(self):
        assert os.path.exists('/app/output/error_log.csv'), \
            "error_log.csv not found at /app/output/"

    def test_trajectory_columns(self):
        rows = read_csv('/app/output/trajectory.csv')
        assert len(rows) > 0, "trajectory.csv is empty"
        bad = [(i, len(r)) for i, r in enumerate(rows) if len(r) != 13]
        assert len(bad) == 0, \
            f"Rows with wrong column count (expected 13): {bad[:5]}"

    def test_error_log_columns(self):
        rows = read_csv('/app/output/error_log.csv')
        assert len(rows) > 0, "error_log.csv is empty"
        bad = [(i, len(r)) for i, r in enumerate(rows) if len(r) != 6]
        assert len(bad) == 0, \
            f"Rows with wrong column count (expected 6): {bad[:5]}"

    def test_trajectory_length(self):
        rows = read_csv('/app/output/trajectory.csv')
        n = len(rows)
        assert n >= 1000, f"Trajectory too short: {n} rows (need >= 1000)"
        assert n <= 6000, f"Trajectory too long: {n} rows (need <= 6000)"

    def test_error_log_length_consistent(self):
        traj = read_csv('/app/output/trajectory.csv')
        errs = read_csv('/app/output/error_log.csv')
        assert abs(len(traj) - len(errs)) <= 5, \
            f"Length mismatch: trajectory={len(traj)}, error_log={len(errs)}"


class TestInitialConfig:
    """Verify the first trajectory row matches the specified initial config."""

    def test_initial_chassis(self):
        rows = read_csv('/app/output/trajectory.csv')
        config = read_config()
        ri = config['robot_initial']
        first = rows[0]
        for i in range(3):
            assert abs(first[i] - ri[i]) < 0.01, \
                f"Initial chassis mismatch at idx {i}: got {first[i]}, expected {ri[i]}"

    def test_initial_arm(self):
        rows = read_csv('/app/output/trajectory.csv')
        config = read_config()
        ri = config['robot_initial']
        first = rows[0]
        for i in range(3, 8):
            assert abs(first[i] - ri[i]) < 0.01, \
                f"Initial arm mismatch at idx {i}: got {first[i]}, expected {ri[i]}"

    def test_initial_wheels(self):
        rows = read_csv('/app/output/trajectory.csv')
        config = read_config()
        ri = config['robot_initial']
        first = rows[0]
        for i in range(8, 12):
            assert abs(first[i] - ri[i]) < 0.01, \
                f"Initial wheel mismatch at idx {i}: got {first[i]}, expected {ri[i]}"

    def test_gripper_starts_open(self):
        rows = read_csv('/app/output/trajectory.csv')
        assert rows[0][12] == 0.0, \
            f"Gripper should start open (0), got {rows[0][12]}"


class TestGripperTransitions:
    """Verify correct gripper open/close/open sequence for pick-and-place."""

    def test_gripper_closes(self):
        rows = read_csv('/app/output/trajectory.csv')
        grippers = [r[12] for r in rows]
        assert any(g >= 1.0 for g in grippers), \
            "Gripper never closes (state=1) during trajectory"

    def test_gripper_reopens(self):
        rows = read_csv('/app/output/trajectory.csv')
        grippers = [r[12] for r in rows]
        first_close = next(i for i, g in enumerate(grippers) if g >= 1.0)
        remaining = grippers[first_close:]
        assert any(g == 0.0 for g in remaining), \
            "Gripper never reopens after closing"

    def test_gripper_transition_order(self):
        rows = read_csv('/app/output/trajectory.csv')
        grippers = [r[12] for r in rows]
        transitions = []
        prev = grippers[0]
        for i, g in enumerate(grippers[1:], 1):
            if abs(g - prev) > 0.5:
                transitions.append((i, prev, g))
                prev = g
        assert len(transitions) >= 2, \
            f"Expected >= 2 gripper transitions, found {len(transitions)}"
        assert transitions[0][1] < 0.5 and transitions[0][2] > 0.5, \
            f"First transition should be open->close, got {transitions[0]}"
        assert transitions[1][1] > 0.5 and transitions[1][2] < 0.5, \
            f"Second transition should be close->open, got {transitions[1]}"


class TestErrorConvergence:
    """Verify that the controller drives the tracking error toward zero."""

    def test_error_decreases_overall(self):
        rows = read_csv('/app/output/error_log.csv')
        errors = [np.linalg.norm(r) for r in rows]
        n = len(errors)
        chunk = max(n // 10, 5)
        avg_first = np.mean(errors[:chunk])
        avg_last = np.mean(errors[-chunk:])
        assert avg_last < avg_first, \
            f"Error did not decrease: first 10% avg={avg_first:.4f}, last 10% avg={avg_last:.4f}"

    def test_final_error_bounded(self):
        rows = read_csv('/app/output/error_log.csv')
        errors = [np.linalg.norm(r) for r in rows]
        n = len(errors)
        tail = max(n // 20, 10)
        avg_final = np.mean(errors[-tail:])
        assert avg_final < 1.5, \
            f"Final error too large: avg of last 5% = {avg_final:.4f} (threshold 1.5)"

    def test_initial_error_nonzero(self):
        rows = read_csv('/app/output/error_log.csv')
        errors = [np.linalg.norm(r) for r in rows]
        assert errors[0] > 0.05, \
            f"Initial error suspiciously small: {errors[0]:.6f} (expected > 0.05)"


class TestKinematicsConsistency:
    """Verify FK and odometry produce physically reasonable results."""

    def test_fk_initial_reasonable(self):
        import modern_robotics as mr

        rows = read_csv('/app/output/trajectory.csv')
        first = rows[0]
        phi, x, y = first[0], first[1], first[2]
        theta = first[3:8]

        Tsb = np.array([[np.cos(phi), -np.sin(phi), 0, x],
                        [np.sin(phi),  np.cos(phi), 0, y],
                        [0, 0, 1, 0.0963],
                        [0, 0, 0, 1]])
        M0e = np.array([[1,0,0,0.033],[0,1,0,0],[0,0,1,0.6546],[0,0,0,1]])
        Tb0 = np.array([[1,0,0,0.1662],[0,1,0,0],[0,0,1,0.0026],[0,0,0,1]])
        Blist = np.array([[0,0,1,0,0.033,0],
                          [0,-1,0,-0.5076,0,0],
                          [0,-1,0,-0.3526,0,0],
                          [0,-1,0,-0.2176,0,0],
                          [0,0,1,0,0,0]]).T

        T0e = mr.FKinBody(M0e, Blist, theta)
        Tse = Tsb @ Tb0 @ T0e

        ee_z = Tse[2, 3]
        assert 0 < ee_z < 1.2, f"End-effector height {ee_z:.3f} not in (0, 1.2)"
        R = Tse[:3, :3]
        assert abs(np.linalg.det(R) - 1.0) < 0.01, \
            f"FK rotation det = {np.linalg.det(R):.4f}, expected 1.0"

    def test_fk_late_trajectory_reasonable(self):
        import modern_robotics as mr

        rows = read_csv('/app/output/trajectory.csv')
        idx = int(0.75 * len(rows))
        row = rows[idx]
        phi, x, y = row[0], row[1], row[2]
        theta = row[3:8]

        Tsb = np.array([[np.cos(phi), -np.sin(phi), 0, x],
                        [np.sin(phi),  np.cos(phi), 0, y],
                        [0, 0, 1, 0.0963],
                        [0, 0, 0, 1]])
        M0e = np.array([[1,0,0,0.033],[0,1,0,0],[0,0,1,0.6546],[0,0,0,1]])
        Tb0 = np.array([[1,0,0,0.1662],[0,1,0,0],[0,0,1,0.0026],[0,0,0,1]])
        Blist = np.array([[0,0,1,0,0.033,0],
                          [0,-1,0,-0.5076,0,0],
                          [0,-1,0,-0.3526,0,0],
                          [0,-1,0,-0.2176,0,0],
                          [0,0,1,0,0,0]]).T

        T0e = mr.FKinBody(M0e, Blist, theta)
        Tse = Tsb @ Tb0 @ T0e

        ee_pos = Tse[:3, 3]
        assert -3 < ee_pos[0] < 3, f"EE x={ee_pos[0]:.3f} out of bounds"
        assert -3 < ee_pos[1] < 3, f"EE y={ee_pos[1]:.3f} out of bounds"
        assert -0.5 < ee_pos[2] < 1.5, f"EE z={ee_pos[2]:.3f} out of bounds"

    def test_odometry_consistency(self):
        """Wheel angle changes must be consistent with chassis displacement."""
        rows = read_csv('/app/output/trajectory.csv')

        r = 0.0475
        lv = 0.235
        wv = 0.15
        F = (r / 4.0) * np.array([
            [-1.0/(lv+wv), 1.0/(lv+wv), 1.0/(lv+wv), -1.0/(lv+wv)],
            [1, 1, 1, 1],
            [-1, 1, -1, 1]
        ])

        n_check = min(100, len(rows) - 1)
        total_dphi = 0.0

        for i in range(n_check):
            dw = np.array(rows[i+1][8:12]) - np.array(rows[i][8:12])
            dq = F @ dw
            total_dphi += dq[0]

        actual_dphi = rows[n_check][0] - rows[0][0]
        assert abs(actual_dphi - total_dphi) < 1.0, \
            f"Odometry phi inconsistency: actual={actual_dphi:.4f}, from wheels={total_dphi:.4f}"

    def test_smooth_trajectory(self):
        """No large jumps between consecutive configurations."""
        rows = read_csv('/app/output/trajectory.csv')
        n_check = min(200, len(rows) - 1)
        for i in range(n_check):
            for j in range(12):
                diff = abs(rows[i+1][j] - rows[i][j])
                assert diff < 5.0, \
                    f"Large jump at row {i}, col {j}: delta={diff:.4f}"
