
"""Tests for the differential IK solver with SE(3) Lie group operations."""

import sys
sys.path.insert(0, "/app")

import numpy as np
import mujoco
import pytest

from ik_solver import (
    skew,
    so3_exp,
    so3_log,
    se3_exp,
    se3_log,
    se3_adjoint,
    body_jacobian,
    frame_error,
    solve_ik,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def robot():
    model = mujoco.MjModel.from_xml_path("/app/robot.xml")
    data = mujoco.MjData(model)
    return model, data


# ---------------------------------------------------------------------------
# Lie group unit tests
# ---------------------------------------------------------------------------

class TestSkew:
    def test_antisymmetric(self):
        v = np.array([1.0, 2.0, 3.0])
        S = skew(v)
        assert S.shape == (3, 3)
        np.testing.assert_allclose(S + S.T, np.zeros((3, 3)), atol=1e-15)

    def test_kernel(self):
        v = np.array([1.0, 2.0, 3.0])
        S = skew(v)
        np.testing.assert_allclose(S @ v, np.zeros(3), atol=1e-15)


class TestSO3:
    def test_exp_identity(self):
        R = so3_exp(np.zeros(3))
        np.testing.assert_allclose(R, np.eye(3), atol=1e-12)

    def test_exp_produces_valid_rotation(self):
        np.random.seed(42)
        for _ in range(30):
            omega = np.random.randn(3) * 2.0
            R = so3_exp(omega)
            np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-10,
                                       err_msg="R is not orthogonal")
            np.testing.assert_allclose(np.linalg.det(R), 1.0, atol=1e-10,
                                       err_msg="det(R) != 1")

    def test_exp_log_roundtrip(self):
        np.random.seed(42)
        for _ in range(30):
            omega = np.random.randn(3) * 2.0
            R = so3_exp(omega)
            omega_rec = so3_log(R)
            R_rec = so3_exp(omega_rec)
            np.testing.assert_allclose(R_rec, R, atol=1e-8)

    def test_log_near_zero(self):
        omega = np.array([1e-12, 2e-12, 3e-12])
        R = so3_exp(omega)
        omega_rec = so3_log(R)
        R_rec = so3_exp(omega_rec)
        np.testing.assert_allclose(R_rec, R, atol=1e-8)

    def test_log_near_pi(self):
        theta = np.pi - 1e-4
        axis = np.array([0.0, 0.0, 1.0])
        omega = theta * axis
        R = so3_exp(omega)
        omega_rec = so3_log(R)
        R_rec = so3_exp(omega_rec)
        np.testing.assert_allclose(R_rec, R, atol=1e-6)

    def test_log_at_pi_various_axes(self):
        np.random.seed(99)
        for _ in range(10):
            axis = np.random.randn(3)
            axis /= np.linalg.norm(axis)
            omega = np.pi * axis
            R = so3_exp(omega)
            omega_rec = so3_log(R)
            R_rec = so3_exp(omega_rec)
            np.testing.assert_allclose(R_rec, R, atol=1e-5)


class TestSE3:
    def test_exp_identity(self):
        T = se3_exp(np.zeros(6))
        np.testing.assert_allclose(T, np.eye(4), atol=1e-12)

    def test_exp_log_roundtrip(self):
        np.random.seed(123)
        for _ in range(30):
            twist = np.random.randn(6) * 0.5
            T = se3_exp(twist)
            R = T[:3, :3]
            np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-10)
            np.testing.assert_allclose(np.linalg.det(R), 1.0, atol=1e-10)
            np.testing.assert_allclose(T[3, :], [0, 0, 0, 1], atol=1e-12)
            twist_rec = se3_log(T)
            T_rec = se3_exp(twist_rec)
            np.testing.assert_allclose(T_rec, T, atol=1e-8)

    def test_exp_pure_rotation(self):
        twist = np.array([0, 0, 0, 0.3, -0.5, 0.7])
        T = se3_exp(twist)
        np.testing.assert_allclose(T[:3, 3], np.zeros(3), atol=1e-12)

    def test_exp_pure_translation(self):
        twist = np.array([1.0, 2.0, 3.0, 0.0, 0.0, 0.0])
        T = se3_exp(twist)
        np.testing.assert_allclose(T[:3, :3], np.eye(3), atol=1e-12)
        np.testing.assert_allclose(T[:3, 3], [1.0, 2.0, 3.0], atol=1e-12)

    def test_log_roundtrip_large_rotation(self):
        np.random.seed(77)
        for _ in range(10):
            omega = np.random.randn(3)
            omega = omega / np.linalg.norm(omega) * 2.5  # ~143 degrees
            v = np.random.randn(3) * 0.3
            twist = np.concatenate([v, omega])
            T = se3_exp(twist)
            twist_rec = se3_log(T)
            T_rec = se3_exp(twist_rec)
            np.testing.assert_allclose(T_rec, T, atol=1e-7)


class TestAdjoint:
    def test_identity(self):
        adj = se3_adjoint(np.eye(4))
        np.testing.assert_allclose(adj, np.eye(6), atol=1e-12)

    def test_shape(self):
        T = se3_exp(np.random.randn(6) * 0.3)
        assert se3_adjoint(T).shape == (6, 6)

    def test_composition_property(self):
        """Ad(T1 @ T2) == Ad(T1) @ Ad(T2)."""
        np.random.seed(456)
        for _ in range(10):
            T1 = se3_exp(np.random.randn(6) * 0.5)
            T2 = se3_exp(np.random.randn(6) * 0.5)
            Ad_12 = se3_adjoint(T1 @ T2)
            Ad_1_Ad_2 = se3_adjoint(T1) @ se3_adjoint(T2)
            np.testing.assert_allclose(Ad_12, Ad_1_Ad_2, atol=1e-8)

    def test_inverse_property(self):
        """Ad(T^{-1}) == Ad(T)^{-1}."""
        np.random.seed(789)
        T = se3_exp(np.random.randn(6) * 0.4)
        T_inv = np.eye(4)
        T_inv[:3, :3] = T[:3, :3].T
        T_inv[:3, 3] = -T[:3, :3].T @ T[:3, 3]
        Ad_inv = se3_adjoint(T_inv)
        inv_Ad = np.linalg.inv(se3_adjoint(T))
        np.testing.assert_allclose(Ad_inv, inv_Ad, atol=1e-8)


# ---------------------------------------------------------------------------
# Body Jacobian tests
# ---------------------------------------------------------------------------

class TestBodyJacobian:
    def test_shape(self, robot):
        model, data = robot
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)
        site_id = model.site("end_effector").id
        J = body_jacobian(model, data, site_id)
        assert J.shape == (6, model.nv)

    def test_numerical_match(self, robot):
        """Compare analytic body Jacobian with finite differences."""
        model, data = robot
        site_id = model.site("end_effector").id

        data.qpos[:] = [0.3, 0.5, -0.4, 0.2, 0.3, -0.1]
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)

        J_analytic = body_jacobian(model, data, site_id)

        eps = 1e-7
        q0 = data.qpos.copy()
        xpos0 = data.site_xpos[site_id].copy()
        xmat0 = data.site_xmat[site_id].reshape(3, 3).copy()

        J_numeric = np.zeros((6, model.nv), dtype=np.float64)
        for i in range(model.nv):
            data.qpos[:] = q0.copy()
            dq = np.zeros(model.nv)
            dq[i] = eps
            mujoco.mj_integratePos(model, data.qpos, dq, 1.0)
            mujoco.mj_kinematics(model, data)
            mujoco.mj_comPos(model, data)

            xpos_p = data.site_xpos[site_id].copy()
            xmat_p = data.site_xmat[site_id].reshape(3, 3).copy()

            # Position error in body frame
            dp_body = xmat0.T @ (xpos_p - xpos0)

            # Rotation error in body frame via MuJoCo quat utilities
            R_delta = xmat0.T @ xmat_p
            quat = np.zeros(4, dtype=np.float64)
            mujoco.mju_mat2Quat(quat, R_delta.ravel())
            omega = np.zeros(3, dtype=np.float64)
            mujoco.mju_quat2Vel(omega, quat, 1.0)

            J_numeric[:3, i] = dp_body / eps
            J_numeric[3:, i] = omega / eps

        # Restore state
        data.qpos[:] = q0
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)

        np.testing.assert_allclose(J_analytic, J_numeric, atol=5e-4)


# ---------------------------------------------------------------------------
# Frame error tests
# ---------------------------------------------------------------------------

class TestFrameError:
    def test_zero_at_identity(self, robot):
        model, data = robot
        data.qpos[:] = [0.1, 0.2, -0.3, 0.1, 0.2, -0.1]
        mujoco.mj_kinematics(model, data)

        site_id = model.site("end_effector").id
        xpos = data.site_xpos[site_id].copy()
        xmat = data.site_xmat[site_id].reshape(3, 3).copy()
        T = np.eye(4, dtype=np.float64)
        T[:3, :3] = xmat
        T[:3, 3] = xpos

        err = frame_error(T, T)
        np.testing.assert_allclose(err, np.zeros(6), atol=1e-10)

    def test_pure_translation_error(self):
        T_curr = np.eye(4)
        T_targ = np.eye(4)
        T_targ[:3, 3] = [0.1, 0.2, 0.3]
        err = frame_error(T_targ, T_curr)
        np.testing.assert_allclose(err[:3], [0.1, 0.2, 0.3], atol=1e-10)
        np.testing.assert_allclose(err[3:], np.zeros(3), atol=1e-10)

    def test_right_minus_reconstruction(self):
        """frame_error must satisfy T_current @ exp(err) == T_target."""
        R_c = so3_exp(np.array([0.3, -0.5, 0.7]))
        T_curr = np.eye(4, dtype=np.float64)
        T_curr[:3, :3] = R_c
        T_curr[:3, 3] = [0.1, 0.2, 0.3]

        R_t = so3_exp(np.array([0.5, 0.2, -0.3]))
        T_targ = np.eye(4, dtype=np.float64)
        T_targ[:3, :3] = R_t
        T_targ[:3, 3] = [0.4, 0.1, 0.5]

        err = frame_error(T_targ, T_curr)
        T_reconstructed = T_curr @ se3_exp(err)
        np.testing.assert_allclose(T_reconstructed, T_targ, atol=1e-7)


# ---------------------------------------------------------------------------
# IK solver integration tests
# ---------------------------------------------------------------------------

class TestSolveIK:
    def test_convergence_to_known_config(self, robot):
        """Set a target from a known configuration and verify IK converges."""
        model, data = robot
        site_id = model.site("end_effector").id

        # Record EE pose at a known joint configuration
        q_goal = np.array([0.3, 0.4, -0.5, 0.2, 0.3, -0.2])
        data.qpos[:] = q_goal
        mujoco.mj_kinematics(model, data)
        xpos_goal = data.site_xpos[site_id].copy()
        xmat_goal = data.site_xmat[site_id].reshape(3, 3).copy()
        T_target = np.eye(4, dtype=np.float64)
        T_target[:3, :3] = xmat_goal
        T_target[:3, 3] = xpos_goal

        # Reset to home
        data.qpos[:] = 0
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)

        q_result, converged = solve_ik(
            model, data, site_id, T_target,
            dt=0.01, max_iters=500, tol=1e-4,
        )
        assert converged, "IK failed to converge to a reachable target"

        # Verify EE position
        data.qpos[:] = q_result
        mujoco.mj_kinematics(model, data)
        xpos_final = data.site_xpos[site_id].copy()
        np.testing.assert_allclose(xpos_final, xpos_goal, atol=2e-3)

    def test_convergence_second_target(self, robot):
        """Test convergence to a second distinct target."""
        model, data = robot
        site_id = model.site("end_effector").id

        q_goal = np.array([-0.5, 0.3, -0.8, -0.4, 0.2, 0.6])
        data.qpos[:] = q_goal
        mujoco.mj_kinematics(model, data)
        xpos_goal = data.site_xpos[site_id].copy()
        xmat_goal = data.site_xmat[site_id].reshape(3, 3).copy()
        T_target = np.eye(4, dtype=np.float64)
        T_target[:3, :3] = xmat_goal
        T_target[:3, 3] = xpos_goal

        data.qpos[:] = 0
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)

        q_result, converged = solve_ik(
            model, data, site_id, T_target,
            dt=0.01, max_iters=500, tol=1e-4,
        )
        assert converged, "IK failed to converge to second target"

        data.qpos[:] = q_result
        mujoco.mj_kinematics(model, data)
        xpos_final = data.site_xpos[site_id].copy()
        np.testing.assert_allclose(xpos_final, xpos_goal, atol=2e-3)

    def test_joint_limits_respected(self, robot):
        """Joint limits must be respected even for unreachable targets."""
        model, data = robot
        site_id = model.site("end_effector").id

        # Target below the base — unreachable, forces joints toward limits
        T_target = np.eye(4, dtype=np.float64)
        T_target[:3, 3] = [0.3, 0.0, -0.5]

        data.qpos[:] = 0
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)

        q_result, _ = solve_ik(
            model, data, site_id, T_target,
            dt=0.01, max_iters=500, tol=1e-4,
        )

        for j in range(model.njnt):
            if model.jnt_limited[j]:
                qpos_id = model.jnt_qposadr[j]
                q_val = q_result[qpos_id]
                q_min = model.jnt_range[j, 0]
                q_max = model.jnt_range[j, 1]
                assert q_val >= q_min - 1e-3, (
                    f"Joint {j} below lower limit: {q_val:.4f} < {q_min:.4f}"
                )
                assert q_val <= q_max + 1e-3, (
                    f"Joint {j} above upper limit: {q_val:.4f} > {q_max:.4f}"
                )

    def test_collision_avoidance(self, robot):
        """Collision avoidance must maintain minimum distance."""
        model, data = robot
        site_id = model.site("end_effector").id

        obstacle_id = model.geom("obstacle_geom").id
        link3_id = model.geom("link3_geom").id
        link2_id = model.geom("link2_geom").id
        collision_pairs = [
            (link2_id, obstacle_id),
            (link3_id, obstacle_id),
        ]

        # Target behind the obstacle — forces the arm past it
        T_target = np.eye(4, dtype=np.float64)
        T_target[:3, 3] = [0.35, 0.20, 0.30]

        data.qpos[:] = 0
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)

        min_dist = 0.02
        q_result, _ = solve_ik(
            model, data, site_id, T_target,
            dt=0.01, max_iters=300, tol=1e-3,
            collision_pairs=collision_pairs,
            collision_min_dist=min_dist,
        )

        # Check distances at the final configuration
        data.qpos[:] = q_result
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)

        fromto = np.zeros(6, dtype=np.float64)
        for g1, g2 in collision_pairs:
            dist = mujoco.mj_geomDistance(model, data, g1, g2, 1.0, fromto)
            assert dist >= min_dist - 0.01, (
                f"Collision distance {dist:.4f} < {min_dist} - 0.01 "
                f"for geom pair ({g1}, {g2})"
            )

    def test_velocity_limits(self, robot):
        """Velocity limits should bound per-step joint displacement."""
        model, data = robot
        site_id = model.site("end_effector").id

        q_goal = np.array([0.5, 0.3, -0.4, 0.3, 0.2, -0.1])
        data.qpos[:] = q_goal
        mujoco.mj_kinematics(model, data)
        xpos_goal = data.site_xpos[site_id].copy()
        xmat_goal = data.site_xmat[site_id].reshape(3, 3).copy()
        T_target = np.eye(4, dtype=np.float64)
        T_target[:3, :3] = xmat_goal
        T_target[:3, 3] = xpos_goal

        data.qpos[:] = 0
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)

        vel_lim = np.full(model.nv, 2.0)
        q_result, converged = solve_ik(
            model, data, site_id, T_target,
            dt=0.01, max_iters=500, tol=1e-4,
            vel_limits=vel_lim,
        )
        assert converged, "IK with velocity limits should still converge"
