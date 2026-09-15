"""Tests for quadrotor dynamics simulator and system identification pipeline."""

import json
import os
import sys

import numpy as np
import pytest

# Add /app to path so we can import the agent's implementations
sys.path.insert(0, '/app')

# ============================================================
# Reference implementation (ground truth for trajectory checks)
# ============================================================

TRUE_MASS = 0.027
TRUE_KF = 3.16e-10
TRUE_KM = 7.94e-12
ARM_LENGTH = 0.0397
J_MATRIX = np.diag([1.4e-5, 1.4e-5, 2.17e-5])
J_INV_MATRIX = np.linalg.inv(J_MATRIX)
DRAG_MATRIX = np.diag([9.1785e-7, 9.1785e-7, 10.311e-7])
G_ACCEL = 9.81
DT = 0.002

TRUE_PARAMS = {
    'mass': TRUE_MASS,
    'k_f': TRUE_KF,
    'k_m': TRUE_KM,
    'arm_length': ARM_LENGTH,
    'J': J_MATRIX,
    'J_inv': J_INV_MATRIX,
    'drag': DRAG_MATRIX,
    'g': G_ACCEL,
}

HOVER_RPM = np.sqrt(TRUE_MASS * G_ACCEL / (4 * TRUE_KF))


def ref_compute_body_wrench(rpms, k_f, k_m, arm_length):
    d = arm_length / np.sqrt(2.0)
    thrusts = k_f * rpms ** 2
    moments = k_m * rpms ** 2
    fz = np.sum(thrusts)
    tau_x = d * (thrusts[0] + thrusts[1] - thrusts[2] - thrusts[3])
    tau_y = d * (-thrusts[0] + thrusts[1] + thrusts[2] - thrusts[3])
    tau_z = moments[0] - moments[1] + moments[2] - moments[3]
    return np.array([0.0, 0.0, fz]), np.array([tau_x, tau_y, tau_z])


def ref_quat_to_rotation_matrix(q):
    x, y, z, w = q
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w),     2*(x*z + y*w)],
        [2*(x*y + z*w),     1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w),     2*(y*z + x*w),     1 - 2*(x*x + y*y)]
    ])


def ref_quat_multiply(q1, q2):
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return np.array([
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
    ])


def ref_state_derivatives(pos, quat, vel, ang_vel, rpms, params):
    F_body, tau_body = ref_compute_body_wrench(
        rpms, params['k_f'], params['k_m'], params['arm_length']
    )
    R = ref_quat_to_rotation_matrix(quat)
    mass = params['mass']
    F_world = R @ F_body + np.array([0.0, 0.0, -mass * params['g']]) - params['drag'] @ vel
    d_pos = vel.copy()
    omega_quat = np.array([ang_vel[0], ang_vel[1], ang_vel[2], 0.0])
    d_quat = 0.5 * ref_quat_multiply(quat, omega_quat)
    d_vel = F_world / mass
    d_ang_vel = params['J_inv'] @ (tau_body - np.cross(ang_vel, params['J'] @ ang_vel))
    return d_pos, d_quat, d_vel, d_ang_vel


def ref_rk4_step(pos, quat, vel, ang_vel, rpms, params, dt):
    def f(p, q, v, w):
        return ref_state_derivatives(p, q, v, w, rpms, params)

    k1 = f(pos, quat, vel, ang_vel)

    p2 = pos + 0.5 * dt * k1[0]
    q2 = quat + 0.5 * dt * k1[1]
    q2 = q2 / np.linalg.norm(q2)
    v2 = vel + 0.5 * dt * k1[2]
    w2 = ang_vel + 0.5 * dt * k1[3]
    k2 = f(p2, q2, v2, w2)

    p3 = pos + 0.5 * dt * k2[0]
    q3 = quat + 0.5 * dt * k2[1]
    q3 = q3 / np.linalg.norm(q3)
    v3 = vel + 0.5 * dt * k2[2]
    w3 = ang_vel + 0.5 * dt * k2[3]
    k3 = f(p3, q3, v3, w3)

    p4 = pos + dt * k3[0]
    q4 = quat + dt * k3[1]
    q4 = q4 / np.linalg.norm(q4)
    v4 = vel + dt * k3[2]
    w4 = ang_vel + dt * k3[3]
    k4 = f(p4, q4, v4, w4)

    new_pos = pos + (dt / 6.0) * (k1[0] + 2*k2[0] + 2*k3[0] + k4[0])
    new_quat = quat + (dt / 6.0) * (k1[1] + 2*k2[1] + 2*k3[1] + k4[1])
    new_quat = new_quat / np.linalg.norm(new_quat)
    new_vel = vel + (dt / 6.0) * (k1[2] + 2*k2[2] + 2*k3[2] + k4[2])
    new_ang_vel = ang_vel + (dt / 6.0) * (k1[3] + 2*k2[3] + 2*k3[3] + k4[3])
    return new_pos, new_quat, new_vel, new_ang_vel


def ref_simulate(initial_state, rpm_sequence, params, dt):
    T = len(rpm_sequence)
    positions = np.zeros((T + 1, 3))
    quaternions = np.zeros((T + 1, 4))
    velocities = np.zeros((T + 1, 3))
    angular_velocities = np.zeros((T + 1, 3))

    pos = initial_state['pos'].copy()
    quat = initial_state['quat'].copy()
    vel = initial_state['vel'].copy()
    ang_vel = initial_state['ang_vel'].copy()

    positions[0] = pos
    quaternions[0] = quat
    velocities[0] = vel
    angular_velocities[0] = ang_vel

    for t in range(T):
        pos, quat, vel, ang_vel = ref_rk4_step(
            pos, quat, vel, ang_vel, rpm_sequence[t], params, dt
        )
        positions[t + 1] = pos
        quaternions[t + 1] = quat
        velocities[t + 1] = vel
        angular_velocities[t + 1] = ang_vel

    return {
        'positions': positions,
        'quaternions': quaternions,
        'velocities': velocities,
        'angular_velocities': angular_velocities,
    }


# ============================================================
# Test classes
# ============================================================

class TestBodyWrench:
    """Test the compute_body_wrench function."""

    def test_hover_thrust(self):
        """Hover RPMs should produce thrust equal to weight, zero torque."""
        from dynamics import compute_body_wrench
        rpms = np.array([HOVER_RPM, HOVER_RPM, HOVER_RPM, HOVER_RPM])
        F, tau = compute_body_wrench(rpms, TRUE_KF, TRUE_KM, ARM_LENGTH)
        assert F.shape == (3,)
        assert tau.shape == (3,)
        assert np.isclose(F[0], 0.0, atol=1e-12)
        assert np.isclose(F[1], 0.0, atol=1e-12)
        assert np.isclose(F[2], TRUE_MASS * G_ACCEL, rtol=1e-4), \
            f"Hover thrust {F[2]:.6f} != weight {TRUE_MASS * G_ACCEL:.6f}"
        assert np.allclose(tau, 0.0, atol=1e-12), \
            f"Hover torque should be zero, got {tau}"

    def test_asymmetric_rpms_produce_torque(self):
        """Asymmetric RPMs should produce non-zero roll torque."""
        from dynamics import compute_body_wrench
        rpms = np.array([15000.0, 15000.0, 13000.0, 13000.0])
        F, tau = compute_body_wrench(rpms, TRUE_KF, TRUE_KM, ARM_LENGTH)
        F_ref, tau_ref = ref_compute_body_wrench(rpms, TRUE_KF, TRUE_KM, ARM_LENGTH)
        assert np.allclose(F, F_ref, rtol=1e-6), f"Force mismatch: {F} vs {F_ref}"
        assert np.allclose(tau, tau_ref, rtol=1e-6), f"Torque mismatch: {tau} vs {tau_ref}"
        assert abs(tau[0]) > 1e-6, "Roll torque should be non-zero"
        assert np.isclose(tau[1], 0.0, atol=1e-10), "Pitch torque should be zero"

    def test_yaw_torque_direction(self):
        """Increasing CW motors (0,2) and decreasing CCW motors (1,3) should give positive yaw."""
        from dynamics import compute_body_wrench
        rpms = np.array([15000.0, 13000.0, 15000.0, 13000.0])
        F, tau = compute_body_wrench(rpms, TRUE_KF, TRUE_KM, ARM_LENGTH)
        F_ref, tau_ref = ref_compute_body_wrench(rpms, TRUE_KF, TRUE_KM, ARM_LENGTH)
        assert np.allclose(tau, tau_ref, rtol=1e-6)
        assert tau[2] > 0, "Yaw torque should be positive when CW motors are faster"


class TestRotationMatrix:
    """Test the quat_to_rotation_matrix function."""

    def test_identity_quaternion(self):
        """Identity quaternion [0,0,0,1] should give identity matrix."""
        from dynamics import quat_to_rotation_matrix
        R = quat_to_rotation_matrix(np.array([0.0, 0.0, 0.0, 1.0]))
        assert np.allclose(R, np.eye(3), atol=1e-10)

    def test_90deg_z_rotation(self):
        """90-degree rotation about z-axis."""
        from dynamics import quat_to_rotation_matrix
        angle = np.pi / 2
        q = np.array([0.0, 0.0, np.sin(angle / 2), np.cos(angle / 2)])
        R = quat_to_rotation_matrix(q)
        expected = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]])
        assert np.allclose(R, expected, atol=1e-10), f"90deg z-rotation:\n{R}\nvs\n{expected}"

    def test_orthogonality(self):
        """Rotation matrix must be orthogonal (R^T R = I)."""
        from dynamics import quat_to_rotation_matrix
        q = np.array([0.1, 0.2, 0.3, 0.9])
        q = q / np.linalg.norm(q)
        R = quat_to_rotation_matrix(q)
        assert np.allclose(R.T @ R, np.eye(3), atol=1e-10)
        assert np.isclose(np.linalg.det(R), 1.0, atol=1e-10)

    def test_body_z_to_world(self):
        """Body z-axis [0,0,1] rotated by 15-deg pitch should have correct world components."""
        from dynamics import quat_to_rotation_matrix
        pitch = 15 * np.pi / 180
        q = np.array([0.0, np.sin(pitch/2), 0.0, np.cos(pitch/2)])
        R = quat_to_rotation_matrix(q)
        world_z = R @ np.array([0.0, 0.0, 1.0])
        expected = np.array([np.sin(pitch), 0.0, np.cos(pitch)])
        assert np.allclose(world_z, expected, atol=1e-10)


class TestQuatMultiply:
    """Test the quat_multiply function."""

    def test_identity_multiply(self):
        """Multiplying by identity should return the same quaternion."""
        from dynamics import quat_multiply
        q = np.array([0.1, 0.2, 0.3, 0.9])
        q = q / np.linalg.norm(q)
        identity = np.array([0.0, 0.0, 0.0, 1.0])
        result = quat_multiply(q, identity)
        assert np.allclose(result, q, atol=1e-10)

    def test_matches_reference(self):
        """Quaternion product should match reference implementation."""
        from dynamics import quat_multiply
        q1 = np.array([0.1, 0.2, 0.3, 0.9])
        q1 = q1 / np.linalg.norm(q1)
        q2 = np.array([0.5, -0.1, 0.2, 0.8])
        q2 = q2 / np.linalg.norm(q2)
        result = quat_multiply(q1, q2)
        expected = ref_quat_multiply(q1, q2)
        assert np.allclose(result, expected, atol=1e-10)


class TestStateDeriv:
    """Test the state_derivatives function."""

    def test_free_fall(self):
        """Zero RPMs should give acceleration = -g in z."""
        from dynamics import state_derivatives
        pos = np.zeros(3)
        quat = np.array([0.0, 0.0, 0.0, 1.0])
        vel = np.zeros(3)
        ang_vel = np.zeros(3)
        rpms = np.zeros(4)
        d_pos, d_quat, d_vel, d_ang_vel = state_derivatives(
            pos, quat, vel, ang_vel, rpms, TRUE_PARAMS
        )
        assert np.allclose(d_pos, np.zeros(3), atol=1e-12)
        assert np.isclose(d_vel[2], -G_ACCEL, rtol=1e-6), \
            f"Free-fall z-acceleration {d_vel[2]} != {-G_ACCEL}"
        assert np.allclose(d_vel[:2], 0.0, atol=1e-10)

    def test_hover_equilibrium(self):
        """At hover RPMs with identity quaternion, acceleration should be ~zero."""
        from dynamics import state_derivatives
        pos = np.array([0.0, 0.0, 1.0])
        quat = np.array([0.0, 0.0, 0.0, 1.0])
        vel = np.zeros(3)
        ang_vel = np.zeros(3)
        rpms = np.full(4, HOVER_RPM)
        d_pos, d_quat, d_vel, d_ang_vel = state_derivatives(
            pos, quat, vel, ang_vel, rpms, TRUE_PARAMS
        )
        assert np.allclose(d_vel, 0.0, atol=1e-3), \
            f"Hover acceleration should be ~0, got {d_vel}"
        assert np.allclose(d_ang_vel, 0.0, atol=1e-10)

    def test_matches_reference(self):
        """State derivatives should match reference for an arbitrary state."""
        from dynamics import state_derivatives
        pos = np.array([1.0, -0.5, 2.0])
        quat = np.array([0.1, 0.2, -0.1, 0.96])
        quat = quat / np.linalg.norm(quat)
        vel = np.array([0.3, -0.1, 0.5])
        ang_vel = np.array([0.5, -0.2, 1.0])
        rpms = np.array([14000.0, 15000.0, 13500.0, 14800.0])

        d_pos, d_quat, d_vel, d_ang_vel = state_derivatives(
            pos, quat, vel, ang_vel, rpms, TRUE_PARAMS
        )
        ref = ref_state_derivatives(pos, quat, vel, ang_vel, rpms, TRUE_PARAMS)

        assert np.allclose(d_pos, ref[0], atol=1e-10), f"d_pos mismatch"
        assert np.allclose(d_quat, ref[1], atol=1e-10), f"d_quat mismatch"
        assert np.allclose(d_vel, ref[2], rtol=1e-6), f"d_vel mismatch: {d_vel} vs {ref[2]}"
        assert np.allclose(d_ang_vel, ref[3], rtol=1e-6), \
            f"d_ang_vel mismatch: {d_ang_vel} vs {ref[3]}"


class TestIntegrator:
    """Test the RK4 integrator."""

    def test_free_fall_single_step(self):
        """Single RK4 step in free fall: velocity should equal -g*dt."""
        from integrator import rk4_step
        pos = np.zeros(3)
        quat = np.array([0.0, 0.0, 0.0, 1.0])
        vel = np.zeros(3)
        ang_vel = np.zeros(3)
        rpms = np.zeros(4)

        new_pos, new_quat, new_vel, new_ang_vel = rk4_step(
            pos, quat, vel, ang_vel, rpms, TRUE_PARAMS, DT
        )
        ref_new = ref_rk4_step(pos, quat, vel, ang_vel, rpms, TRUE_PARAMS, DT)

        assert np.allclose(new_vel, ref_new[2], rtol=1e-6)
        assert np.isclose(new_vel[2], -G_ACCEL * DT, rtol=1e-3)

    def test_quaternion_normalization(self):
        """Quaternion must stay unit-norm over many integration steps."""
        from integrator import simulate
        initial_state = {
            'pos': np.zeros(3),
            'quat': np.array([0.0, 0.1, 0.0, 0.995]),
            'vel': np.zeros(3),
            'ang_vel': np.array([1.0, 0.5, -0.3]),
        }
        initial_state['quat'] /= np.linalg.norm(initial_state['quat'])
        rpms = np.full((200, 4), HOVER_RPM)

        result = simulate(initial_state, rpms, TRUE_PARAMS, DT)
        norms = np.linalg.norm(result['quaternions'], axis=1)
        assert np.allclose(norms, 1.0, atol=1e-6), \
            f"Quaternion norm deviation: max={np.max(np.abs(norms - 1.0))}"

    def test_hover_stability(self):
        """Hovering drone should maintain position over 1 second."""
        from integrator import simulate
        initial_state = {
            'pos': np.array([0.0, 0.0, 1.0]),
            'quat': np.array([0.0, 0.0, 0.0, 1.0]),
            'vel': np.zeros(3),
            'ang_vel': np.zeros(3),
        }
        rpms = np.full((500, 4), HOVER_RPM)

        result = simulate(initial_state, rpms, TRUE_PARAMS, DT)
        max_drift = np.max(np.abs(result['positions'] - np.array([0.0, 0.0, 1.0])))
        assert max_drift < 0.001, f"Hover drift: {max_drift} m (should be < 1mm)"

    def test_trajectory_matches_reference(self):
        """Multi-step trajectory should match reference implementation."""
        from integrator import simulate
        initial_state = {
            'pos': np.array([0.0, 0.0, 1.0]),
            'quat': np.array([0.0, 0.0, 0.0, 1.0]),
            'vel': np.zeros(3),
            'ang_vel': np.zeros(3),
        }
        # 50 steps with above-hover thrust
        rpms = np.full((50, 4), 15000.0)

        result = simulate(initial_state, rpms, TRUE_PARAMS, DT)
        ref = ref_simulate(initial_state, rpms, TRUE_PARAMS, DT)

        pos_rmse = np.sqrt(np.mean((result['positions'] - ref['positions'])**2))
        assert pos_rmse < 1e-8, f"Trajectory RMSE vs reference: {pos_rmse}"


class TestSystemIdentification:
    """Test the parameter estimation results."""

    def test_output_files_exist(self):
        """Estimated parameters file must exist."""
        assert os.path.exists('/app/output/estimated_params.json'), \
            "estimated_params.json not found in /app/output/"

    def test_mass_accuracy(self):
        """Estimated mass should be within 3% of true value."""
        with open('/app/output/estimated_params.json') as f:
            est = json.load(f)
        assert 'mass' in est, "Missing 'mass' in estimated parameters"
        assert np.isclose(est['mass'], TRUE_MASS, rtol=0.03), \
            f"Mass {est['mass']:.6f} not within 3% of {TRUE_MASS}"

    def test_kf_accuracy(self):
        """Estimated k_f should be within 3% of true value."""
        with open('/app/output/estimated_params.json') as f:
            est = json.load(f)
        assert 'k_f' in est, "Missing 'k_f' in estimated parameters"
        assert np.isclose(est['k_f'], TRUE_KF, rtol=0.03), \
            f"k_f {est['k_f']:.4e} not within 3% of {TRUE_KF:.4e}"

    def test_km_accuracy(self):
        """Estimated k_m should be within 5% of true value."""
        with open('/app/output/estimated_params.json') as f:
            est = json.load(f)
        assert 'k_m' in est, "Missing 'k_m' in estimated parameters"
        assert np.isclose(est['k_m'], TRUE_KM, rtol=0.05), \
            f"k_m {est['k_m']:.4e} not within 5% of {TRUE_KM:.4e}"


class TestTrajectoryPrediction:
    """Test the trajectory prediction outputs."""

    def test_scenario_files_exist(self):
        """All three scenario output files must exist."""
        for i in range(1, 4):
            path = f'/app/output/scenario_{i}.npz'
            assert os.path.exists(path), f"{path} not found"

    def test_scenario_shapes(self):
        """Output arrays must have correct shapes (501 states for 500 steps)."""
        for i in range(1, 4):
            pred = np.load(f'/app/output/scenario_{i}.npz')
            assert 'positions' in pred, f"Missing 'positions' in scenario_{i}"
            assert pred['positions'].shape == (501, 3), \
                f"scenario_{i} positions shape {pred['positions'].shape} != (501, 3)"
            assert pred['quaternions'].shape == (501, 4)
            assert pred['velocities'].shape == (501, 3)
            assert pred['angular_velocities'].shape == (501, 3)

    def test_scenario_1_accuracy(self):
        """Scenario 1 (ascent): prediction should match ground truth within 5cm RMSE."""
        self._check_scenario_rmse(1, tolerance=0.05)

    def test_scenario_2_accuracy(self):
        """Scenario 2 (tilted hover): prediction should match ground truth within 5cm RMSE."""
        self._check_scenario_rmse(2, tolerance=0.05)

    def test_scenario_3_accuracy(self):
        """Scenario 3 (oscillating RPMs): prediction should match ground truth within 5cm RMSE."""
        self._check_scenario_rmse(3, tolerance=0.05)

    def _check_scenario_rmse(self, scenario_id, tolerance):
        test_data = np.load('/app/data/test_inputs.npz')
        scenario = f'scenario_{scenario_id}'
        initial_state = {
            'pos': test_data[f'{scenario}_pos0'].copy(),
            'quat': test_data[f'{scenario}_quat0'].copy(),
            'vel': test_data[f'{scenario}_vel0'].copy(),
            'ang_vel': test_data[f'{scenario}_angvel0'].copy(),
        }
        rpms = test_data[f'{scenario}_rpms']
        ref_traj = ref_simulate(initial_state, rpms, TRUE_PARAMS, DT)

        pred = np.load(f'/app/output/{scenario}.npz')
        pos_rmse = np.sqrt(np.mean((pred['positions'] - ref_traj['positions'])**2))
        assert pos_rmse < tolerance, \
            f"Scenario {scenario_id} position RMSE {pos_rmse:.4f} > {tolerance}"

    def test_scenario_quaternion_norms(self):
        """Predicted quaternions should all be unit-norm."""
        for i in range(1, 4):
            pred = np.load(f'/app/output/scenario_{i}.npz')
            norms = np.linalg.norm(pred['quaternions'], axis=1)
            assert np.allclose(norms, 1.0, atol=1e-4), \
                f"Scenario {i}: quaternion norm deviation max={np.max(np.abs(norms - 1.0))}"
