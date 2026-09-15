
import sys
sys.path.insert(0, "/app")

import numpy as np
import mujoco
import pytest

from lie_ik import (
    so3_skew,
    so3_exp,
    so3_log,
    so3_left_jacobian,
    so3_left_jacobian_inv,
    se3_exp,
    se3_log,
    se3_adjoint,
    se3_left_jacobian,
    se3_left_jacobian_inv,
    compute_frame_error,
    compute_body_jacobian,
    compute_collision_constraint,
    solve_ik_step,
)


# =====================================================================
# SO(3) tests
# =====================================================================

class TestSO3Skew:
    def test_antisymmetric(self):
        v = np.array([1.0, 2.0, 3.0])
        S = so3_skew(v)
        np.testing.assert_allclose(S + S.T, np.zeros((3, 3)), atol=1e-15)

    def test_cross_product(self):
        v = np.array([1.7, -0.3, 2.1])
        w = np.array([-0.5, 1.2, 0.8])
        np.testing.assert_allclose(so3_skew(v) @ w, np.cross(v, w), atol=1e-14)


class TestSO3ExpLog:
    def test_exp_identity(self):
        R = so3_exp(np.zeros(3))
        np.testing.assert_allclose(R, np.eye(3), atol=1e-14)

    def test_exp_orthogonality(self):
        rng = np.random.RandomState(42)
        for _ in range(15):
            omega = rng.randn(3) * 2.0
            R = so3_exp(omega)
            np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-12)
            np.testing.assert_allclose(np.linalg.det(R), 1.0, atol=1e-12)

    def test_exp_log_roundtrip(self):
        rng = np.random.RandomState(43)
        for _ in range(20):
            omega = rng.randn(3)
            norm = np.linalg.norm(omega)
            if norm > 2.8:
                omega *= 2.8 / norm
            R = so3_exp(omega)
            omega_rec = so3_log(R)
            np.testing.assert_allclose(omega_rec, omega, atol=1e-10)

    def test_exp_small_angle(self):
        omega = np.array([1e-12, 2e-12, 3e-12])
        R = so3_exp(omega)
        np.testing.assert_allclose(R, np.eye(3), atol=1e-10)

    def test_log_near_pi(self):
        """Rotation near pi must correctly identify the rotation axis."""
        # Use theta within the near-pi branch threshold (abs(theta-pi) < 1e-6)
        theta = np.pi - 5e-7
        omega = np.array([0.0, 0.0, theta])
        R = so3_exp(omega)
        omega_rec = so3_log(R)
        R_rec = so3_exp(omega_rec)
        np.testing.assert_allclose(R_rec, R, atol=1e-8)


class TestSO3LeftJacobian:
    def test_identity_at_zero(self):
        J = so3_left_jacobian(np.zeros(3))
        np.testing.assert_allclose(J, np.eye(3), atol=1e-12)

    def test_inverse_relation(self):
        rng = np.random.RandomState(44)
        for _ in range(15):
            omega = rng.randn(3) * 1.5
            J = so3_left_jacobian(omega)
            J_inv = so3_left_jacobian_inv(omega)
            np.testing.assert_allclose(J @ J_inv, np.eye(3), atol=1e-10)


# =====================================================================
# SE(3) tests
# =====================================================================

class TestSE3ExpLog:
    def test_exp_identity(self):
        T = se3_exp(np.zeros(6))
        np.testing.assert_allclose(T, np.eye(4), atol=1e-14)

    def test_exp_homogeneous_structure(self):
        rng = np.random.RandomState(45)
        twist = rng.randn(6) * 0.5
        T = se3_exp(twist)
        assert T.shape == (4, 4)
        np.testing.assert_allclose(T[3, :], [0, 0, 0, 1], atol=1e-14)
        R = T[:3, :3]
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-12)

    def test_exp_log_roundtrip(self):
        rng = np.random.RandomState(46)
        for _ in range(20):
            twist = rng.randn(6) * 0.5
            T = se3_exp(twist)
            twist_rec = se3_log(T)
            np.testing.assert_allclose(twist_rec, twist, atol=1e-10)

    def test_exp_pure_translation(self):
        t = np.array([1.0, 2.0, 3.0])
        twist = np.array([1.0, 2.0, 3.0, 0.0, 0.0, 0.0])
        T = se3_exp(twist)
        np.testing.assert_allclose(T[:3, :3], np.eye(3), atol=1e-12)
        np.testing.assert_allclose(T[:3, 3], t, atol=1e-12)

    def test_exp_pure_rotation(self):
        omega = np.array([0.0, 0.0, 0.5])
        twist = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.5])
        T = se3_exp(twist)
        R_expected = so3_exp(omega)
        np.testing.assert_allclose(T[:3, :3], R_expected, atol=1e-12)
        np.testing.assert_allclose(T[:3, 3], np.zeros(3), atol=1e-12)


class TestSE3Adjoint:
    def test_identity(self):
        Ad = se3_adjoint(np.eye(4))
        np.testing.assert_allclose(Ad, np.eye(6), atol=1e-14)

    def test_composition(self):
        rng = np.random.RandomState(47)
        for _ in range(10):
            t1 = rng.randn(6) * 0.5
            t2 = rng.randn(6) * 0.5
            T1 = se3_exp(t1)
            T2 = se3_exp(t2)
            Ad_T1T2 = se3_adjoint(T1 @ T2)
            Ad_T1_Ad_T2 = se3_adjoint(T1) @ se3_adjoint(T2)
            np.testing.assert_allclose(Ad_T1T2, Ad_T1_Ad_T2, atol=1e-10)


class TestSE3LeftJacobian:
    def test_identity_at_zero(self):
        J = se3_left_jacobian(np.zeros(6))
        np.testing.assert_allclose(J, np.eye(6), atol=1e-12)

    def test_inverse_relation(self):
        rng = np.random.RandomState(48)
        for _ in range(10):
            twist = rng.randn(6) * 0.3
            J = se3_left_jacobian(twist)
            J_inv = se3_left_jacobian_inv(twist)
            np.testing.assert_allclose(J @ J_inv, np.eye(6), atol=1e-9)

    def test_pure_rotation_blocks(self):
        """When v=0, Q-matrix should be zero; diagonal blocks are SO3 J_l."""
        omega = np.array([0.3, -0.5, 0.7])
        twist = np.array([0.0, 0.0, 0.0, 0.3, -0.5, 0.7])
        J_se3 = se3_left_jacobian(twist)
        J_so3 = so3_left_jacobian(omega)
        np.testing.assert_allclose(J_se3[:3, :3], J_so3, atol=1e-12)
        np.testing.assert_allclose(J_se3[3:, 3:], J_so3, atol=1e-12)
        np.testing.assert_allclose(J_se3[:3, 3:], np.zeros((3, 3)), atol=1e-12)
        np.testing.assert_allclose(J_se3[3:, :3], np.zeros((3, 3)), atol=1e-12)

    def test_bch_first_order(self):
        """log(exp(a) @ exp(b)) ~ a + b for small a, b."""
        rng = np.random.RandomState(49)
        for _ in range(10):
            a = rng.randn(6) * 0.01
            b = rng.randn(6) * 0.01
            T_ab = se3_exp(a) @ se3_exp(b)
            log_ab = se3_log(T_ab)
            np.testing.assert_allclose(log_ab, a + b, atol=1e-3)

    def test_numerical_derivative(self):
        """J_l must match finite-difference derivative of the exponential map."""
        xi = np.array([0.3, -0.2, 0.15, 0.8, -0.5, 0.4])
        J_analytic = se3_left_jacobian(xi)
        eps = 1e-6
        J_numerical = np.zeros((6, 6))
        T_base = se3_exp(xi)
        T_base_inv = np.linalg.inv(T_base)
        for i in range(6):
            delta = np.zeros(6)
            delta[i] = eps
            T_perturbed = se3_exp(xi + delta)
            # Left Jacobian: exp(xi+delta) ≈ exp(J_l @ delta) @ exp(xi)
            # => log(exp(xi+delta) @ exp(-xi)) ≈ J_l @ delta
            diff_twist = se3_log(T_perturbed @ T_base_inv)
            J_numerical[:, i] = diff_twist / eps
        np.testing.assert_allclose(J_analytic, J_numerical, atol=1e-4)


# =====================================================================
# IK building-block tests
# =====================================================================

class TestBodyJacobian:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.model = mujoco.MjModel.from_xml_path("/app/robot.xml")
        self.data = mujoco.MjData(self.model)
        self.site_id = self.model.site("ee_site").id
        mujoco.mj_resetDataKeyframe(
            self.model, self.data, self.model.keyframe("home").id
        )
        mujoco.mj_forward(self.model, self.data)

    def test_dimension(self):
        J = compute_body_jacobian(self.model, self.data, self.site_id)
        assert J.shape == (6, self.model.nv)

    def test_world_consistency(self):
        """Ad(T_ws) @ J_body should equal J_world."""
        J_body = compute_body_jacobian(self.model, self.data, self.site_id)
        T_ws = np.eye(4)
        T_ws[:3, :3] = self.data.site_xmat[self.site_id].reshape(3, 3)
        T_ws[:3, 3] = self.data.site_xpos[self.site_id]
        Ad_ws = se3_adjoint(T_ws)
        J_world_from_body = Ad_ws @ J_body
        jacp = np.zeros((3, self.model.nv))
        jacr = np.zeros((3, self.model.nv))
        mujoco.mj_jacSite(self.model, self.data, jacp, jacr, self.site_id)
        J_world = np.vstack([jacp, jacr])
        np.testing.assert_allclose(J_world_from_body, J_world, atol=1e-8)


class TestFrameError:
    def test_zero_at_identity(self):
        T = np.eye(4)
        T[:3, :3] = so3_exp(np.array([0.3, -0.5, 0.7]))
        T[:3, 3] = [0.1, 0.2, 0.3]
        err = compute_frame_error(T, T)
        np.testing.assert_allclose(err, np.zeros(6), atol=1e-12)

    def test_pure_translation_error(self):
        T_cur = np.eye(4)
        T_tgt = np.eye(4)
        T_tgt[:3, 3] = [0.1, 0.0, 0.0]
        err = compute_frame_error(T_cur, T_tgt)
        assert err[0] > 0.09
        np.testing.assert_allclose(err[3:], np.zeros(3), atol=1e-12)


# =====================================================================
# IK convergence
# =====================================================================

class TestIKConvergence:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.model = mujoco.MjModel.from_xml_path("/app/robot.xml")
        self.data = mujoco.MjData(self.model)
        self.site_id = self.model.site("ee_site").id
        mujoco.mj_resetDataKeyframe(
            self.model, self.data, self.model.keyframe("home").id
        )
        mujoco.mj_forward(self.model, self.data)

    def test_ik_reaches_target(self):
        """IK should converge to a nearby target within 1 cm position error."""
        T_start = np.eye(4)
        T_start[:3, :3] = self.data.site_xmat[self.site_id].reshape(3, 3)
        T_start[:3, 3] = self.data.site_xpos[self.site_id].copy()

        T_target = T_start.copy()
        T_target[0, 3] += 0.04
        T_target[1, 3] += 0.03
        T_target[2, 3] -= 0.02

        dt = 0.01
        for _ in range(300):
            v = solve_ik_step(
                self.model,
                self.data,
                self.site_id,
                T_target,
                dt=dt,
                damping=1e-4,
                collision_pairs=[],
                min_collision_dist=0.005,
                gain=0.85,
            )
            q = self.data.qpos.copy()
            q += v * dt
            for j in range(self.model.njnt):
                qi = self.model.jnt_qposadr[j]
                q[qi] = np.clip(
                    q[qi],
                    self.model.jnt_range[j, 0],
                    self.model.jnt_range[j, 1],
                )
            self.data.qpos[:] = q
            mujoco.mj_forward(self.model, self.data)

        T_final = np.eye(4)
        T_final[:3, :3] = self.data.site_xmat[self.site_id].reshape(3, 3)
        T_final[:3, 3] = self.data.site_xpos[self.site_id]
        pos_err = np.linalg.norm(T_final[:3, 3] - T_target[:3, 3])
        assert pos_err < 0.01, f"Position error {pos_err:.4f} > 0.01"


# =====================================================================
# Collision-avoidance tests
# =====================================================================

class TestCollisionConstraint:
    def test_basic_two_spheres(self):
        """Constraint dimensions and sign on a minimal slide-joint model."""
        xml = """
        <mujoco>
          <worldbody>
            <body name="a">
              <joint type="slide" axis="1 0 0"/>
              <geom name="ga" type="sphere" size="0.05"/>
            </body>
            <body name="b" pos="0.15 0 0">
              <geom name="gb" type="sphere" size="0.05"/>
            </body>
          </worldbody>
        </mujoco>
        """
        m = mujoco.MjModel.from_xml_string(xml)
        d = mujoco.MjData(m)
        mujoco.mj_forward(m, d)
        ga = m.geom("ga").id
        gb = m.geom("gb").id

        g_row, h_val = compute_collision_constraint(
            m, d, ga, gb, min_dist=0.01, dt=0.01, gain=0.85, detection_dist=1.0
        )

        assert g_row.shape == (m.nv,)
        assert np.isfinite(h_val)
        assert h_val > 0  # dist > min_dist => h > 0

        # Approaching velocity (sphere a moves toward b in +x)
        assert g_row @ np.array([1.0]) > 0, "Approach should be resisted"
        # Separating velocity
        assert g_row @ np.array([-1.0]) < 0, "Separation should be allowed"

    def test_out_of_range(self):
        """Geoms beyond detection_dist should return inf upper bound."""
        xml = """
        <mujoco>
          <worldbody>
            <body name="a">
              <joint type="slide" axis="1 0 0"/>
              <geom name="ga" type="sphere" size="0.01"/>
            </body>
            <body name="b" pos="5 0 0">
              <geom name="gb" type="sphere" size="0.01"/>
            </body>
          </worldbody>
        </mujoco>
        """
        m = mujoco.MjModel.from_xml_string(xml)
        d = mujoco.MjData(m)
        mujoco.mj_forward(m, d)
        ga = m.geom("ga").id
        gb = m.geom("gb").id

        _, h_val = compute_collision_constraint(
            m, d, ga, gb, min_dist=0.01, dt=0.01, gain=0.85, detection_dist=0.5
        )
        assert h_val == np.inf


class TestIKCollisionAvoidance:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.model = mujoco.MjModel.from_xml_path("/app/robot.xml")
        self.data = mujoco.MjData(self.model)
        self.site_id = self.model.site("ee_site").id
        mujoco.mj_resetDataKeyframe(
            self.model, self.data, self.model.keyframe("home").id
        )
        mujoco.mj_forward(self.model, self.data)

    def test_maintains_min_distance(self):
        """IK with collision avoidance should not violate the distance bound."""
        arm_geom_ids = [self.model.geom(f"g{i}").id for i in range(4, 8)]
        obs_id = self.model.geom("obstacle1").id

        collision_pairs = [(ag, obs_id) for ag in arm_geom_ids]

        T_target = np.eye(4)
        T_target[:3, 3] = np.array([0.15, 0.05, 0.55])

        min_dist = 0.02
        dt = 0.01

        for _ in range(120):
            v = solve_ik_step(
                self.model,
                self.data,
                self.site_id,
                T_target,
                dt=dt,
                damping=1e-4,
                collision_pairs=collision_pairs,
                min_collision_dist=min_dist,
                gain=0.85,
            )
            q = self.data.qpos.copy()
            q += v * dt
            for j in range(self.model.njnt):
                qi = self.model.jnt_qposadr[j]
                q[qi] = np.clip(
                    q[qi],
                    self.model.jnt_range[j, 0],
                    self.model.jnt_range[j, 1],
                )
            self.data.qpos[:] = q
            mujoco.mj_forward(self.model, self.data)

        fromto = np.zeros(6)
        for ag in arm_geom_ids:
            dist = mujoco.mj_geomDistance(
                self.model, self.data, ag, obs_id, 10.0, fromto
            )
            assert dist >= min_dist - 0.005, (
                f"Geom {ag} too close to obstacle: "
                f"dist={dist:.4f}, min={min_dist}"
            )
