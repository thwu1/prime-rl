"""
Verification tests for the manipulator kinematic-dynamic analysis from URDF task.

"""

import json
import sqlite3
import numpy as np
import pytest
import os


# ---------------------------------------------------------------------------
# Embedded reference DH parameters for independent FK/Jacobian verification.
# These correspond to the robot described in /app/robot.urdf but are
# expressed in standard DH convention for oracle FK computation.
# (a, alpha, d, theta_offset)
# ---------------------------------------------------------------------------

_ROBOT_DH_PARAMS = [
    (0.0,   1.5707963267948966,  0.340, 0.0),
    (0.400, 0.0,                 0.0,   0.0),
    (0.040, 1.5707963267948966,  0.0,   0.0),
    (0.0,  -1.5707963267948966,  0.400, 0.0),
    (0.0,   1.5707963267948966,  0.0,   0.0),
    (0.0,   0.0,                 0.126, 0.0),
]

_JOINT_LIMITS_LOWER = np.array([-2.9671, -2.0944, -2.9671, -2.9671, -2.0944, -2.9671])
_JOINT_LIMITS_UPPER = np.array([2.9671, 2.0944, 2.9671, 2.9671, 2.0944, 2.9671])
_EFFORT_LIMITS = np.array([87.0, 87.0, 40.0, 40.0, 28.0, 28.0])

# ---------------------------------------------------------------------------
# Embedded URDF chain structure for independent gravity torque verification.
# Each entry: (xyz, rpy, axis, joint_type, child_mass, child_com_xyz)
# Ordered from base to end-effector (joints + fixed tool0).
# ---------------------------------------------------------------------------

_URDF_CHAIN_DATA = [
    # shoulder_pan_joint -> shoulder_link
    ([0, 0, 0], [0, 0, 0], [0, 0, 1], "revolute",
     5.4, [0.0, 0.0, 0.16]),
    # shoulder_lift_joint -> upper_arm_link
    ([0, 0, 0.340], [1.5707963267948966, 0, 0], [0, 0, 1], "revolute",
     4.9, [0.19, 0.0, 0.0]),
    # elbow_joint -> forearm_link
    ([0.400, 0, 0], [0, 0, 0], [0, 0, 1], "revolute",
     3.1, [0.02, 0.0, 0.0]),
    # wrist_1_joint -> wrist_1_link
    ([0.040, 0, 0], [1.5707963267948966, 0, 0], [0, 0, 1], "revolute",
     1.8, [0.0, 0.0, 0.19]),
    # wrist_2_joint -> wrist_2_link
    ([0, 0, 0.400], [-1.5707963267948966, 0, 0], [0, 0, 1], "revolute",
     1.8, [0.0, 0.0, 0.0]),
    # wrist_3_joint -> wrist_3_link
    ([0, 0, 0], [1.5707963267948966, 0, 0], [0, 0, 1], "revolute",
     0.6, [0.0, 0.0, 0.0]),
    # tool0_joint (fixed) -> tool0
    ([0, 0, 0.126], [0, 0, 0], [0, 0, 1], "fixed",
     0.3, [0.0, 0.0, 0.063]),
]


# ---------------------------------------------------------------------------
# Reference DH implementation (independent oracle for FK/Jacobian)
# ---------------------------------------------------------------------------

def _dh_matrix(theta, d, a, alpha):
    """Standard DH transformation matrix: Rz(theta)·Tz(d)·Tx(a)·Rx(alpha)."""
    ct, st = np.cos(theta), np.sin(theta)
    ca, sa = np.cos(alpha), np.sin(alpha)
    return np.array([
        [ct, -st * ca,  st * sa, a * ct],
        [st,  ct * ca, -ct * sa, a * st],
        [0.0, sa,       ca,      d     ],
        [0.0, 0.0,      0.0,     1.0   ],
    ])


def _ref_fk(dh_params, q):
    """Reference forward kinematics."""
    T = np.eye(4)
    for i, (a_i, alpha_i, d_i, off_i) in enumerate(dh_params):
        T = T @ _dh_matrix(q[i] + off_i, d_i, a_i, alpha_i)
    return T


def _ref_jacobian(dh_params, q, eps=1e-8):
    """Reference geometric Jacobian via central differences."""
    n = len(q)
    J = np.zeros((6, n))
    T0 = _ref_fk(dh_params, q)
    R0 = T0[:3, :3].copy()
    for i in range(n):
        qp = q.copy(); qp[i] += eps
        qm = q.copy(); qm[i] -= eps
        Tp = _ref_fk(dh_params, qp)
        Tm = _ref_fk(dh_params, qm)
        J[:3, i] = (Tp[:3, 3] - Tm[:3, 3]) / (2.0 * eps)
        dR = (Tp[:3, :3] - Tm[:3, :3]) / (2.0 * eps)
        S = dR @ R0.T
        J[3:, i] = np.array([S[2, 1], S[0, 2], S[1, 0]])
    return J


def _ref_manipulability(dh_params, q):
    """Reference manipulability: w = sqrt(det(J·J^T))."""
    J = _ref_jacobian(dh_params, q)
    return float(np.sqrt(max(0.0, np.linalg.det(J @ J.T))))


def _rpy_to_rotation(roll, pitch, yaw):
    """ZYX Euler: R = Rz(yaw)·Ry(pitch)·Rx(roll)."""
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp,     cp * sr,                cp * cr               ],
    ])


def _pose_to_se3(position, rpy):
    T = np.eye(4)
    T[:3, :3] = _rpy_to_rotation(*rpy)
    T[:3, 3] = position
    return T


# ---------------------------------------------------------------------------
# Reference URDF-chain based gravity torque computation
# ---------------------------------------------------------------------------

def _urdf_origin_transform(xyz, rpy):
    """Convert URDF origin (xyz, rpy) to 4x4 transform."""
    T = np.eye(4)
    T[:3, :3] = _rpy_to_rotation(rpy[0], rpy[1], rpy[2])
    T[:3, 3] = xyz
    return T


def _urdf_axis_rotation(axis, angle):
    """4x4 rotation about an axis using Rodrigues formula."""
    a = np.array(axis, dtype=float)
    a = a / np.linalg.norm(a)
    K = np.array([
        [0, -a[2], a[1]],
        [a[2], 0, -a[0]],
        [-a[1], a[0], 0],
    ])
    R = np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)
    T = np.eye(4)
    T[:3, :3] = R
    return T


def _urdf_link_com_positions(q):
    """Compute world-frame CoM positions using embedded URDF chain data."""
    positions = []
    T = np.eye(4)
    qi = 0
    for xyz, rpy, axis, jtype, mass, com in _URDF_CHAIN_DATA:
        T_origin = _urdf_origin_transform(xyz, rpy)
        T = T @ T_origin
        if jtype == "revolute":
            T = T @ _urdf_axis_rotation(axis, q[qi])
            qi += 1
        p_com = T @ np.array([com[0], com[1], com[2], 1.0])
        positions.append((mass, p_com[:3].copy()))
    return positions


def _ref_potential_energy(q, gravity=(0, 0, -9.81)):
    """Gravitational potential energy: V = -sum(m * g . p_com)."""
    g = np.array(gravity)
    V = 0.0
    for mass, p_com in _urdf_link_com_positions(q):
        V -= mass * np.dot(g, p_com)
    return V


def _ref_gravity_torques(q, gravity=(0, 0, -9.81), eps=1e-7):
    """Reference gravity torques via numerical differentiation of V(q)."""
    n = len(q)
    tau = np.zeros(n)
    for i in range(n):
        qp = q.copy(); qp[i] += eps
        qm = q.copy(); qm[i] -= eps
        tau[i] = (_ref_potential_energy(qp, gravity) -
                  _ref_potential_energy(qm, gravity)) / (2.0 * eps)
    return tau


def _ref_max_payload(gravity_torques_vec, J, effort_limits=_EFFORT_LIMITS,
                     g_mag=9.81):
    """Reference maximum static payload computation."""
    upper_bounds = []
    lower_bounds = [0.0]

    for i in range(len(effort_limits)):
        c = g_mag * J[2, i]
        g_i = gravity_torques_vec[i]
        e_i = effort_limits[i]

        if abs(c) < 1e-12:
            if abs(g_i) > e_i + 1e-6:
                return 0.0
            continue

        if c > 0:
            upper_bounds.append((e_i - g_i) / c)
            lower_bounds.append((-e_i - g_i) / c)
        else:
            lower_bounds.append((e_i - g_i) / c)
            upper_bounds.append((-e_i - g_i) / c)

    max_lower = max(lower_bounds)
    min_upper = min(upper_bounds) if upper_bounds else float("inf")

    if max_lower > min_upper + 1e-9:
        return 0.0

    return max(0.0, min_upper)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def waypoints_data():
    with open("/app/waypoints.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def config():
    with open("/app/config.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def dh_params():
    return _ROBOT_DH_PARAMS


@pytest.fixture(scope="module")
def joint_limits():
    return (_JOINT_LIMITS_LOWER, _JOINT_LIMITS_UPPER)


# ---------------------------------------------------------------------------
# Tests: Output Structure
# ---------------------------------------------------------------------------

class TestResultsStructure:
    """Verify /app/results.json exists and has correct schema."""

    def test_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found"

    def test_top_level_keys(self, results):
        assert "fk_verification" in results
        assert "waypoint_analysis" in results
        assert "trajectory_segments" in results

    def test_fk_keys(self, results):
        fk = results["fk_verification"]
        for key in ("q_zero", "q_test1", "q_test2"):
            assert key in fk, f"Missing FK key: {key}"
            mat = fk[key]
            assert len(mat) == 4, f"{key} must be 4 rows"
            for row in mat:
                assert len(row) == 4, f"{key} rows must have 4 elements"

    def test_waypoint_count(self, results):
        assert len(results["waypoint_analysis"]) == 6


# ---------------------------------------------------------------------------
# Tests: Forward Kinematics
# ---------------------------------------------------------------------------

class TestForwardKinematics:
    """Verify FK at known joint configurations against reference."""

    def test_fk_q_zero(self, results, dh_params):
        q = np.zeros(6)
        T_ref = _ref_fk(dh_params, q)
        T_rep = np.array(results["fk_verification"]["q_zero"])
        np.testing.assert_allclose(T_rep, T_ref, atol=1e-4,
                                   err_msg="FK mismatch at q=0")

    def test_fk_q_test1(self, results, dh_params, config):
        q = np.array(config["fk_test_configurations"]["q_test1"])
        T_ref = _ref_fk(dh_params, q)
        T_rep = np.array(results["fk_verification"]["q_test1"])
        np.testing.assert_allclose(T_rep, T_ref, atol=1e-4,
                                   err_msg="FK mismatch at q_test1")

    def test_fk_q_test2(self, results, dh_params, config):
        q = np.array(config["fk_test_configurations"]["q_test2"])
        T_ref = _ref_fk(dh_params, q)
        T_rep = np.array(results["fk_verification"]["q_test2"])
        np.testing.assert_allclose(T_rep, T_ref, atol=1e-4,
                                   err_msg="FK mismatch at q_test2")

    def test_fk_rotation_orthogonal(self, results):
        """All FK rotation matrices must be orthogonal with det=1."""
        for key in ("q_zero", "q_test1", "q_test2"):
            T = np.array(results["fk_verification"][key])
            R = T[:3, :3]
            np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-4,
                                       err_msg=f"R not orthogonal at {key}")
            np.testing.assert_allclose(np.linalg.det(R), 1.0, atol=1e-4,
                                       err_msg=f"det(R)!=1 at {key}")

    def test_fk_last_row(self, results):
        for key in ("q_zero", "q_test1", "q_test2"):
            T = np.array(results["fk_verification"][key])
            np.testing.assert_allclose(T[3, :], [0, 0, 0, 1], atol=1e-10,
                                       err_msg=f"Last row wrong at {key}")


# ---------------------------------------------------------------------------
# Tests: Inverse Kinematics
# ---------------------------------------------------------------------------

class TestInverseKinematics:
    """Verify IK solutions achieve target poses."""

    def test_ik_position_accuracy(self, results, dh_params, waypoints_data):
        for wp_res in results["waypoint_analysis"]:
            if not wp_res["reachable"]:
                continue
            q_sol = np.array(wp_res["ik_solution"])
            wp_id = wp_res["id"]
            wp = next(w for w in waypoints_data["waypoints"] if w["id"] == wp_id)
            target = _pose_to_se3(wp["position"], wp["orientation_rpy"])
            Te = _ref_fk(dh_params, q_sol)
            pos_err = np.linalg.norm(Te[:3, 3] - target[:3, 3])
            assert pos_err < 5e-3, (
                f"Waypoint {wp_id}: position error {pos_err:.6f} exceeds 5e-3"
            )

    def test_ik_orientation_accuracy(self, results, dh_params, waypoints_data):
        for wp_res in results["waypoint_analysis"]:
            if not wp_res["reachable"]:
                continue
            q_sol = np.array(wp_res["ik_solution"])
            wp_id = wp_res["id"]
            wp = next(w for w in waypoints_data["waypoints"] if w["id"] == wp_id)
            target = _pose_to_se3(wp["position"], wp["orientation_rpy"])
            Te = _ref_fk(dh_params, q_sol)
            R_err = Te[:3, :3] @ target[:3, :3].T
            trace_val = np.clip(np.trace(R_err), -1.0, 3.0)
            angle_err = np.arccos(np.clip((trace_val - 1.0) / 2.0, -1.0, 1.0))
            assert angle_err < 5e-2, (
                f"Waypoint {wp_id}: orientation error {angle_err:.6f} rad exceeds 5e-2"
            )

    def test_joint_limits_respected(self, results, joint_limits):
        jl_lo, jl_hi = joint_limits
        for wp_res in results["waypoint_analysis"]:
            if not wp_res["reachable"]:
                continue
            q = np.array(wp_res["ik_solution"])
            assert np.all(q >= jl_lo - 0.02), (
                f"Waypoint {wp_res['id']}: lower joint limit violated"
            )
            assert np.all(q <= jl_hi + 0.02), (
                f"Waypoint {wp_res['id']}: upper joint limit violated"
            )


# ---------------------------------------------------------------------------
# Tests: Manipulability
# ---------------------------------------------------------------------------

class TestManipulability:
    """Verify manipulability computations."""

    def test_manipulability_values(self, results, dh_params):
        for wp_res in results["waypoint_analysis"]:
            if not wp_res["reachable"]:
                continue
            q_sol = np.array(wp_res["ik_solution"])
            m_rep = wp_res["manipulability"]
            m_ref = _ref_manipulability(dh_params, q_sol)
            assert abs(m_rep - m_ref) < 0.01 or (
                m_ref > 1e-10 and abs(m_rep - m_ref) / m_ref < 0.15
            ), (
                f"Waypoint {wp_res['id']}: manipulability {m_rep:.6f} "
                f"vs reference {m_ref:.6f}"
            )

    def test_near_singular_consistency(self, results, config):
        threshold = config["manipulability_threshold"]
        for wp_res in results["waypoint_analysis"]:
            if not wp_res["reachable"]:
                continue
            m = wp_res["manipulability"]
            flag = wp_res["near_singular"]
            assert flag == (m < threshold), (
                f"Waypoint {wp_res['id']}: near_singular={flag} but "
                f"manipulability={m}, threshold={threshold}"
            )

    def test_condition_number_positive(self, results):
        for wp_res in results["waypoint_analysis"]:
            if not wp_res["reachable"]:
                continue
            cn = wp_res["condition_number"]
            assert cn > 0, f"Waypoint {wp_res['id']}: condition_number must be > 0"


# ---------------------------------------------------------------------------
# Tests: Reachability
# ---------------------------------------------------------------------------

class TestReachability:
    """Verify reachability classification."""

    def test_unreachable_waypoint_5(self, results):
        wp5 = next(
            w for w in results["waypoint_analysis"] if w["id"] == 5
        )
        assert not wp5["reachable"], (
            "Waypoint 5 at position [2,0,0.5] is beyond workspace and must "
            "be classified as unreachable"
        )

    def test_unreachable_has_nulls(self, results):
        for wp_res in results["waypoint_analysis"]:
            if not wp_res["reachable"]:
                assert wp_res["ik_solution"] is None
                assert wp_res["manipulability"] is None
                assert wp_res["condition_number"] is None
                assert wp_res["near_singular"] is None
                assert wp_res["gravity_torques"] is None
                assert wp_res["max_payload_kg"] is None

    def test_at_least_three_reachable(self, results):
        reachable = sum(
            1 for w in results["waypoint_analysis"] if w["reachable"]
        )
        assert reachable >= 3, f"Expected >=3 reachable waypoints, got {reachable}"

    def test_at_least_one_unreachable(self, results):
        unreachable = sum(
            1 for w in results["waypoint_analysis"] if not w["reachable"]
        )
        assert unreachable >= 1, f"Expected >=1 unreachable waypoint, got {unreachable}"


# ---------------------------------------------------------------------------
# Tests: Gravity Torques
# ---------------------------------------------------------------------------

class TestGravityTorques:
    """Verify gravity torque computation against independent oracle."""

    def test_gravity_torques_exist(self, results):
        """Reachable waypoints must have 6-element gravity_torques."""
        for wp in results["waypoint_analysis"]:
            if wp["reachable"]:
                assert wp["gravity_torques"] is not None, (
                    f"Waypoint {wp['id']}: gravity_torques is None"
                )
                assert len(wp["gravity_torques"]) == 6, (
                    f"Waypoint {wp['id']}: gravity_torques has wrong length"
                )

    def test_gravity_torques_accuracy(self, results, config):
        """Gravity torques must match reference computation within 0.5 Nm."""
        gravity = tuple(config["gravity_vector"])
        for wp in results["waypoint_analysis"]:
            if not wp["reachable"]:
                continue
            q = np.array(wp["ik_solution"])
            gt_ref = _ref_gravity_torques(q, gravity)
            gt_rep = np.array(wp["gravity_torques"])
            np.testing.assert_allclose(
                gt_rep, gt_ref, atol=0.5,
                err_msg=f"Waypoint {wp['id']}: gravity torques mismatch"
            )

    def test_shoulder_pan_gravity_near_zero(self, results):
        """Shoulder pan rotates around vertical axis — its gravity torque
        must be near zero regardless of configuration (physics sanity)."""
        for wp in results["waypoint_analysis"]:
            if not wp["reachable"]:
                continue
            tau0 = wp["gravity_torques"][0]
            assert abs(tau0) < 0.5, (
                f"Waypoint {wp['id']}: shoulder pan gravity torque = "
                f"{tau0:.4f}, expected ~0 (vertical axis rotation)"
            )

    def test_gravity_torques_sign_at_q_zero(self, results, config):
        """At q=0, the arm extends outward; shoulder lift torque should be
        significantly nonzero (it must support the arm against gravity)."""
        # Find a waypoint whose IK solution is near the zero config, or
        # just check that gravity torques at any config have physically
        # reasonable magnitudes (shoulder lift >> wrist torques)
        for wp in results["waypoint_analysis"]:
            if not wp["reachable"]:
                continue
            gt = wp["gravity_torques"]
            # At least one of joints 1-2 (shoulder lift, elbow) should
            # have significant gravity torque (>1 Nm) since the arm has mass
            shoulder_elbow_max = max(abs(gt[1]), abs(gt[2]))
            assert shoulder_elbow_max > 1.0, (
                f"Waypoint {wp['id']}: shoulder/elbow gravity torques "
                f"are suspiciously small ({shoulder_elbow_max:.4f} Nm)"
            )


# ---------------------------------------------------------------------------
# Tests: Maximum Static Payload
# ---------------------------------------------------------------------------

class TestMaxPayload:
    """Verify maximum static payload capacity computation."""

    def test_max_payload_exists(self, results):
        for wp in results["waypoint_analysis"]:
            if wp["reachable"]:
                assert wp["max_payload_kg"] is not None, (
                    f"Waypoint {wp['id']}: max_payload_kg is None"
                )
                assert wp["max_payload_kg"] >= 0, (
                    f"Waypoint {wp['id']}: negative max_payload_kg"
                )

    def test_max_payload_accuracy(self, results, dh_params, config):
        """Max payload must match independently computed value."""
        gravity = config["gravity_vector"]
        for wp in results["waypoint_analysis"]:
            if not wp["reachable"]:
                continue
            q = np.array(wp["ik_solution"])
            J = _ref_jacobian(dh_params, q)
            gt_ref = _ref_gravity_torques(q, tuple(gravity))
            mp_ref = _ref_max_payload(gt_ref, J)
            mp_rep = wp["max_payload_kg"]
            # Allow tolerance of 15% or 1 kg absolute
            assert abs(mp_rep - mp_ref) < max(1.0, 0.15 * abs(mp_ref)), (
                f"Waypoint {wp['id']}: max_payload {mp_rep:.2f} kg "
                f"vs reference {mp_ref:.2f} kg"
            )

    def test_max_payload_satisfies_constraints(self, results, dh_params, config):
        """Verify reported max payload doesn't violate effort limits."""
        gravity = config["gravity_vector"]
        g_mag = np.linalg.norm(gravity)
        for wp in results["waypoint_analysis"]:
            if not wp["reachable"]:
                continue
            q = np.array(wp["ik_solution"])
            J = _ref_jacobian(dh_params, q)
            gt = np.array(wp["gravity_torques"])
            mp = wp["max_payload_kg"]
            for i in range(6):
                tau_total = gt[i] + mp * g_mag * J[2, i]
                assert abs(tau_total) <= _EFFORT_LIMITS[i] + 1.0, (
                    f"Waypoint {wp['id']}, joint {i}: |tau_total| = "
                    f"{abs(tau_total):.2f} > effort {_EFFORT_LIMITS[i]}"
                )

    def test_max_payload_reasonable_range(self, results):
        """Max payload should be in a physically reasonable range (0-100 kg)."""
        for wp in results["waypoint_analysis"]:
            if not wp["reachable"]:
                continue
            mp = wp["max_payload_kg"]
            assert 0 <= mp <= 100, (
                f"Waypoint {wp['id']}: max_payload_kg={mp:.2f} is "
                f"outside reasonable range [0, 100]"
            )


# ---------------------------------------------------------------------------
# Tests: Trajectory Segments
# ---------------------------------------------------------------------------

class TestTrajectorySegments:
    """Verify trajectory segment structure and values."""

    def test_segment_structure(self, results):
        for seg in results["trajectory_segments"]:
            assert "from_id" in seg
            assert "to_id" in seg
            assert "min_manipulability" in seg
            assert "max_torque_ratio" in seg
            assert "dynamically_feasible" in seg
            assert "feasible" in seg

    def test_min_manipulability_non_negative(self, results):
        for seg in results["trajectory_segments"]:
            assert seg["min_manipulability"] >= 0, (
                f"Segment {seg['from_id']}->{seg['to_id']}: "
                f"negative min_manipulability"
            )

    def test_max_torque_ratio_non_negative(self, results):
        for seg in results["trajectory_segments"]:
            assert seg["max_torque_ratio"] >= 0, (
                f"Segment {seg['from_id']}->{seg['to_id']}: "
                f"negative max_torque_ratio"
            )

    def test_dynamically_feasible_consistency(self, results):
        """dynamically_feasible must be consistent with max_torque_ratio."""
        for seg in results["trajectory_segments"]:
            expected = seg["max_torque_ratio"] < 1.0
            assert seg["dynamically_feasible"] == expected, (
                f"Segment {seg['from_id']}->{seg['to_id']}: "
                f"dynamically_feasible={seg['dynamically_feasible']} but "
                f"max_torque_ratio={seg['max_torque_ratio']}"
            )

    def test_feasibility_consistency(self, results, config):
        """feasible must be consistent with both kinematic and dynamic checks."""
        threshold = config["manipulability_threshold"]
        for seg in results["trajectory_segments"]:
            kinematic_ok = seg["min_manipulability"] > threshold
            dynamic_ok = seg["dynamically_feasible"]
            expected = kinematic_ok and dynamic_ok
            assert seg["feasible"] == expected, (
                f"Segment {seg['from_id']}->{seg['to_id']}: "
                f"feasible={seg['feasible']} but kinematic_ok={kinematic_ok}, "
                f"dynamic_ok={dynamic_ok}"
            )

    def test_segments_connect_reachable_waypoints(self, results):
        """Segments must only connect reachable, non-singular waypoints."""
        safe_ids = set()
        for wp in results["waypoint_analysis"]:
            if wp["reachable"] and not wp["near_singular"]:
                safe_ids.add(wp["id"])
        for seg in results["trajectory_segments"]:
            assert seg["from_id"] in safe_ids, (
                f"Segment from_id {seg['from_id']} is not a safe waypoint"
            )
            assert seg["to_id"] in safe_ids, (
                f"Segment to_id {seg['to_id']} is not a safe waypoint"
            )

    def test_segments_are_consecutive_pairs(self, results):
        """Segments must connect consecutive safe waypoints in ID order."""
        safe_ids = sorted(
            wp["id"]
            for wp in results["waypoint_analysis"]
            if wp["reachable"] and not wp["near_singular"]
        )
        expected_pairs = [
            (safe_ids[i], safe_ids[i + 1]) for i in range(len(safe_ids) - 1)
        ]
        actual_pairs = [
            (seg["from_id"], seg["to_id"])
            for seg in results["trajectory_segments"]
        ]
        assert actual_pairs == expected_pairs, (
            f"Trajectory segments {actual_pairs} don't match expected "
            f"consecutive pairs {expected_pairs}"
        )


# ---------------------------------------------------------------------------
# Tests: SQLite Database Output
# ---------------------------------------------------------------------------

class TestSQLiteOutput:
    """Verify /app/analysis.db exists with correct schema and data."""

    def test_db_file_exists(self):
        assert os.path.isfile("/app/analysis.db"), "analysis.db not found"

    def test_fk_results_table_exists(self):
        conn = sqlite3.connect("/app/analysis.db")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='fk_results'"
        )
        assert cursor.fetchone() is not None, "Table 'fk_results' not found"
        conn.close()

    def test_waypoint_table_exists(self):
        conn = sqlite3.connect("/app/analysis.db")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='waypoint_analysis'"
        )
        assert cursor.fetchone() is not None, "Table 'waypoint_analysis' not found"
        conn.close()

    def test_trajectory_table_exists(self):
        conn = sqlite3.connect("/app/analysis.db")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trajectory_segments'"
        )
        assert cursor.fetchone() is not None, "Table 'trajectory_segments' not found"
        conn.close()

    def test_fk_results_row_count(self):
        conn = sqlite3.connect("/app/analysis.db")
        cursor = conn.execute("SELECT count(*) FROM fk_results")
        count = cursor.fetchone()[0]
        assert count == 3, f"Expected 3 FK results, got {count}"
        conn.close()

    def test_waypoint_row_count(self):
        conn = sqlite3.connect("/app/analysis.db")
        cursor = conn.execute("SELECT count(*) FROM waypoint_analysis")
        count = cursor.fetchone()[0]
        assert count == 6, f"Expected 6 waypoint rows, got {count}"
        conn.close()

    def test_trajectory_row_count(self):
        conn = sqlite3.connect("/app/analysis.db")
        cursor = conn.execute("SELECT count(*) FROM trajectory_segments")
        count = cursor.fetchone()[0]
        assert count > 0, "Expected at least 1 trajectory segment"
        conn.close()

    def test_waypoint_has_dynamics_columns(self):
        """Verify the waypoint_analysis table has gravity_torques and max_payload_kg."""
        conn = sqlite3.connect("/app/analysis.db")
        cursor = conn.execute("PRAGMA table_info(waypoint_analysis)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "gravity_torques" in columns, "Missing column: gravity_torques"
        assert "max_payload_kg" in columns, "Missing column: max_payload_kg"
        conn.close()

    def test_trajectory_has_dynamics_columns(self):
        """Verify trajectory_segments has max_torque_ratio and dynamically_feasible."""
        conn = sqlite3.connect("/app/analysis.db")
        cursor = conn.execute("PRAGMA table_info(trajectory_segments)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "max_torque_ratio" in columns, "Missing column: max_torque_ratio"
        assert "dynamically_feasible" in columns, "Missing column: dynamically_feasible"
        conn.close()

    def test_fk_results_consistency(self, results):
        """FK data in SQLite must match JSON."""
        conn = sqlite3.connect("/app/analysis.db")
        for config_name in ("q_zero", "q_test1", "q_test2"):
            cursor = conn.execute(
                "SELECT row0, row1, row2, row3 FROM fk_results WHERE config_name=?",
                (config_name,)
            )
            row = cursor.fetchone()
            assert row is not None, f"Missing FK result for {config_name}"
            for i, row_json in enumerate(row):
                db_row = json.loads(row_json)
                json_row = results["fk_verification"][config_name][i]
                np.testing.assert_allclose(
                    db_row, json_row, atol=1e-10,
                    err_msg=f"FK row {i} mismatch for {config_name} between DB and JSON"
                )
        conn.close()

    def test_waypoint_consistency(self, results):
        """Waypoint data in SQLite must match JSON."""
        conn = sqlite3.connect("/app/analysis.db")
        for wp in results["waypoint_analysis"]:
            cursor = conn.execute(
                "SELECT reachable, manipulability, condition_number, near_singular, "
                "gravity_torques, max_payload_kg "
                "FROM waypoint_analysis WHERE id=?",
                (wp["id"],)
            )
            row = cursor.fetchone()
            assert row is not None, f"Missing waypoint {wp['id']} in DB"
            assert row[0] == (1 if wp["reachable"] else 0), (
                f"Waypoint {wp['id']}: reachable mismatch"
            )
            if wp["reachable"]:
                assert row[1] is not None, f"Waypoint {wp['id']}: NULL manipulability"
                assert abs(row[1] - wp["manipulability"]) < 1e-6, (
                    f"Waypoint {wp['id']}: manipulability mismatch"
                )
                assert abs(row[2] - wp["condition_number"]) < 1e-3, (
                    f"Waypoint {wp['id']}: condition_number mismatch"
                )
                assert row[3] == (1 if wp["near_singular"] else 0), (
                    f"Waypoint {wp['id']}: near_singular mismatch"
                )
                # gravity_torques consistency
                gt_db = json.loads(row[4])
                np.testing.assert_allclose(
                    gt_db, wp["gravity_torques"], atol=1e-6,
                    err_msg=f"Waypoint {wp['id']}: gravity_torques mismatch DB/JSON"
                )
                # max_payload_kg consistency
                assert abs(row[5] - wp["max_payload_kg"]) < 1e-6, (
                    f"Waypoint {wp['id']}: max_payload_kg mismatch"
                )
            else:
                assert row[1] is None, f"Waypoint {wp['id']}: should be NULL"
                assert row[4] is None, f"Waypoint {wp['id']}: gravity_torques should be NULL"
                assert row[5] is None, f"Waypoint {wp['id']}: max_payload_kg should be NULL"
        conn.close()

    def test_trajectory_consistency(self, results):
        """Trajectory segment data in SQLite must match JSON."""
        conn = sqlite3.connect("/app/analysis.db")
        for seg in results["trajectory_segments"]:
            cursor = conn.execute(
                "SELECT min_manipulability, max_torque_ratio, dynamically_feasible, feasible "
                "FROM trajectory_segments WHERE from_id=? AND to_id=?",
                (seg["from_id"], seg["to_id"])
            )
            row = cursor.fetchone()
            assert row is not None, (
                f"Missing segment {seg['from_id']}->{seg['to_id']} in DB"
            )
            assert abs(row[0] - seg["min_manipulability"]) < 1e-6, (
                f"Segment {seg['from_id']}->{seg['to_id']}: "
                f"min_manipulability mismatch"
            )
            assert abs(row[1] - seg["max_torque_ratio"]) < 1e-6, (
                f"Segment {seg['from_id']}->{seg['to_id']}: "
                f"max_torque_ratio mismatch"
            )
            assert row[2] == (1 if seg["dynamically_feasible"] else 0), (
                f"Segment {seg['from_id']}->{seg['to_id']}: "
                f"dynamically_feasible mismatch"
            )
            assert row[3] == (1 if seg["feasible"] else 0), (
                f"Segment {seg['from_id']}->{seg['to_id']}: feasible mismatch"
            )
        conn.close()
