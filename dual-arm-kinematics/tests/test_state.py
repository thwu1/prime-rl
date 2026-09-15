"""Tests for the Robot Arm Kinematic Chain Solver.

Verifies FK, IK, Jacobian, manipulability, and dual-arm IK solutions
against ikpy reference implementation and self-consistency checks.
"""

import json
import numpy as np
import pytest
from ikpy.chain import Chain

URDF_PATH = "/app/poppy_torso.urdf"
RESULTS_PATH = "/app/results.json"
PROBLEMS_PATH = "/app/problems.json"


def _build_chain(arm):
    """Build a kinematic chain from the problems spec."""
    with open(PROBLEMS_PATH) as f:
        data = json.load(f)
    spec = data["chain_specs"][arm + "_arm"]
    return Chain.from_urdf_file(
        URDF_PATH,
        base_elements=spec["base_elements"],
        last_link_vector=spec["last_link_vector"],
        active_links_mask=spec["active_links_mask"],
        name=arm + "_arm",
    )


def _compute_jacobian(chain, joint_angles, active_indices, epsilon=1e-6):
    """Compute positional Jacobian via finite differences."""
    fk_base = chain.forward_kinematics(joint_angles)[:3, 3]
    J = np.zeros((3, len(active_indices)))
    for i, idx in enumerate(active_indices):
        config_plus = list(joint_angles)
        config_plus[idx] += epsilon
        fk_plus = chain.forward_kinematics(config_plus)[:3, 3]
        J[:, i] = (fk_plus - fk_base) / epsilon
    return J


def _compute_manipulability(chain, joint_angles, active_indices):
    """Compute Yoshikawa manipulability at a configuration."""
    J = _compute_jacobian(chain, joint_angles, active_indices)
    JJT = J @ J.T
    return np.sqrt(max(0.0, np.linalg.det(JJT)))


@pytest.fixture(scope="module")
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def left_chain():
    return _build_chain("left")


@pytest.fixture(scope="module")
def right_chain():
    return _build_chain("right")


# ---------- Forward Kinematics Tests ----------

class TestForwardKinematics:

    def test_fk_left_zero_position(self, results, left_chain):
        ref = left_chain.forward_kinematics([0.0] * 9)
        res = results["fk1"]
        np.testing.assert_allclose(res["position"], ref[:3, 3].tolist(), atol=1e-4)

    def test_fk_left_zero_orientation(self, results, left_chain):
        ref = left_chain.forward_kinematics([0.0] * 9)
        res = results["fk1"]
        np.testing.assert_allclose(
            res["orientation_matrix"], ref[:3, :3].tolist(), atol=1e-4
        )

    def test_fk_left_config1_position(self, results, left_chain):
        config = [0.0, 0.0, 0.0, 0.0, 0.5, -0.3, 0.2, -1.0, 0.0]
        ref = left_chain.forward_kinematics(config)
        res = results["fk2"]
        np.testing.assert_allclose(res["position"], ref[:3, 3].tolist(), atol=1e-4)

    def test_fk_left_config1_orientation(self, results, left_chain):
        config = [0.0, 0.0, 0.0, 0.0, 0.5, -0.3, 0.2, -1.0, 0.0]
        ref = left_chain.forward_kinematics(config)
        res = results["fk2"]
        np.testing.assert_allclose(
            res["orientation_matrix"], ref[:3, :3].tolist(), atol=1e-4
        )

    def test_fk_right_zero(self, results, right_chain):
        ref = right_chain.forward_kinematics([0.0] * 9)
        res = results["fk3"]
        np.testing.assert_allclose(res["position"], ref[:3, 3].tolist(), atol=1e-4)
        np.testing.assert_allclose(
            res["orientation_matrix"], ref[:3, :3].tolist(), atol=1e-4
        )

    def test_fk_right_config1(self, results, right_chain):
        config = [0.0, 0.2, -0.1, 0.15, 0.8, -0.4, 0.3, 1.5, 0.0]
        ref = right_chain.forward_kinematics(config)
        res = results["fk4"]
        np.testing.assert_allclose(res["position"], ref[:3, 3].tolist(), atol=1e-4)
        np.testing.assert_allclose(
            res["orientation_matrix"], ref[:3, :3].tolist(), atol=1e-4
        )

    def test_fk_valid_rotation_matrices(self, results):
        for key in ["fk1", "fk2", "fk3", "fk4"]:
            R = np.array(results[key]["orientation_matrix"])
            det = np.linalg.det(R)
            assert abs(det - 1.0) < 1e-3, (
                f"{key}: orientation is not a valid rotation matrix (det={det:.6f})"
            )
            RTR = R.T @ R
            np.testing.assert_allclose(
                RTR, np.eye(3), atol=1e-3,
                err_msg=f"{key}: R^T R != I",
            )


# ---------- Inverse Kinematics Tests ----------

class TestInverseKinematics:

    def test_ik_left_reaches_target(self, results, left_chain):
        res = results["ik1"]
        joints = res["joint_angles"]
        target = [0.1, -0.2, 0.1]
        fk = left_chain.forward_kinematics(joints)
        np.testing.assert_allclose(fk[:3, 3], target, atol=0.01)

    def test_ik_left_joint_count(self, results, left_chain):
        res = results["ik1"]
        assert len(res["joint_angles"]) == len(left_chain.links)

    def test_ik_left_respects_bounds(self, results, left_chain):
        res = results["ik1"]
        for i, (angle, link) in enumerate(zip(res["joint_angles"], left_chain.links)):
            lb, ub = link.bounds
            assert lb - 0.05 <= angle <= ub + 0.05, (
                f"Joint {i} ({link.name}): {angle:.4f} outside [{lb:.4f}, {ub:.4f}]"
            )

    def test_ik_left_achieved_position_consistent(self, results, left_chain):
        res = results["ik1"]
        fk = left_chain.forward_kinematics(res["joint_angles"])
        np.testing.assert_allclose(
            res["achieved_position"], fk[:3, 3].tolist(), atol=1e-3
        )

    def test_ik_right_reaches_target(self, results, right_chain):
        res = results["ik2"]
        joints = res["joint_angles"]
        target = [0.1, -0.2, 0.1]
        fk = right_chain.forward_kinematics(joints)
        np.testing.assert_allclose(fk[:3, 3], target, atol=0.01)

    def test_ik_right_joint_count(self, results, right_chain):
        res = results["ik2"]
        assert len(res["joint_angles"]) == len(right_chain.links)

    def test_ik_right_respects_bounds(self, results, right_chain):
        res = results["ik2"]
        for i, (angle, link) in enumerate(zip(res["joint_angles"], right_chain.links)):
            lb, ub = link.bounds
            assert lb - 0.05 <= angle <= ub + 0.05, (
                f"Joint {i} ({link.name}): {angle:.4f} outside [{lb:.4f}, {ub:.4f}]"
            )


# ---------- Jacobian Tests ----------

class TestJacobian:

    def test_jacobian_shape(self, results):
        J = np.array(results["jacobian1"]["jacobian"])
        assert J.shape == (3, 4), f"Expected shape (3,4), got {J.shape}"

    def test_jacobian_values(self, results, left_chain):
        J_agent = np.array(results["jacobian1"]["jacobian"])
        config = [0.0, 0.0, 0.0, 0.0, 0.3, -0.2, 0.1, -0.5, 0.0]
        J_ref = _compute_jacobian(left_chain, config, [4, 5, 6, 7])
        np.testing.assert_allclose(J_agent, J_ref, atol=1e-3)

    def test_jacobian_not_degenerate(self, results):
        J = np.array(results["jacobian1"]["jacobian"])
        assert np.linalg.norm(J) > 0.001, "Jacobian is near-zero"
        # With 3x4 matrix, rank should be 3 (full row rank) at non-singular config
        assert np.linalg.matrix_rank(J, tol=1e-4) == 3, (
            "Jacobian is rank-deficient at a non-singular configuration"
        )


# ---------- Manipulability Tests ----------

class TestManipulability:

    ACTIVE_INDICES = [4, 5, 6, 7]

    def test_manipulability_value_correct(self, results, left_chain):
        res = results["manipulability1"]
        joints = res["joint_angles"]
        reported = res["manipulability"]
        computed = _compute_manipulability(left_chain, joints, self.ACTIVE_INDICES)
        assert abs(reported - computed) < 0.001, (
            f"Reported manipulability {reported:.6f} != computed {computed:.6f}"
        )

    def test_manipulability_positive(self, results):
        res = results["manipulability1"]
        assert res["manipulability"] > 1e-6, "Manipulability is near zero"

    def test_manipulability_joint_count(self, results, left_chain):
        res = results["manipulability1"]
        assert len(res["joint_angles"]) == len(left_chain.links)

    def test_manipulability_respects_bounds(self, results, left_chain):
        res = results["manipulability1"]
        for i, (angle, link) in enumerate(zip(res["joint_angles"], left_chain.links)):
            lb, ub = link.bounds
            assert lb - 0.05 <= angle <= ub + 0.05, (
                f"Joint {i} ({link.name}): {angle:.4f} outside [{lb:.4f}, {ub:.4f}]"
            )

    def test_manipulability_better_than_references(self, results, left_chain):
        opt_manip = results["manipulability1"]["manipulability"]
        reference_configs = [
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0, -0.5, 0.0],
            [0.0, 0.0, 0.0, 0.0, 1.0, -0.5, 0.3, -1.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, -0.3, 0.5, -0.2, -0.3, 0.0],
        ]
        for config in reference_configs:
            ref_manip = _compute_manipulability(
                left_chain, config, self.ACTIVE_INDICES
            )
            assert opt_manip >= ref_manip - 0.0001, (
                f"Reported optimal {opt_manip:.6f} worse than reference "
                f"config {config[4:8]}: {ref_manip:.6f}"
            )


# ---------- Dual-Arm IK Tests ----------

class TestDualArmIK:

    def test_dual_arm_has_required_keys(self, results):
        res = results["dual1"]
        for key in [
            "left_joint_angles",
            "right_joint_angles",
            "left_achieved_position",
            "right_achieved_position",
        ]:
            assert key in res, f"Missing key '{key}' in dual1 result"

    def test_dual_arm_shared_torso(self, results):
        res = results["dual1"]
        left = res["left_joint_angles"]
        right = res["right_joint_angles"]
        for i in [1, 2, 3]:
            assert abs(left[i] - right[i]) < 1e-3, (
                f"Torso joint {i} differs: left={left[i]:.6f}, right={right[i]:.6f}"
            )

    def test_dual_arm_left_reaches_target(self, results, left_chain):
        res = results["dual1"]
        fk = left_chain.forward_kinematics(res["left_joint_angles"])
        target = [0.1, -0.15, 0.15]
        np.testing.assert_allclose(fk[:3, 3], target, atol=0.02)

    def test_dual_arm_right_reaches_target(self, results, right_chain):
        res = results["dual1"]
        fk = right_chain.forward_kinematics(res["right_joint_angles"])
        target = [-0.05, -0.2, 0.1]
        np.testing.assert_allclose(fk[:3, 3], target, atol=0.02)

    def test_dual_arm_joint_counts(self, results, left_chain, right_chain):
        res = results["dual1"]
        assert len(res["left_joint_angles"]) == len(left_chain.links)
        assert len(res["right_joint_angles"]) == len(right_chain.links)

    def test_dual_arm_left_bounds(self, results, left_chain):
        res = results["dual1"]
        for i, (angle, link) in enumerate(
            zip(res["left_joint_angles"], left_chain.links)
        ):
            lb, ub = link.bounds
            assert lb - 0.05 <= angle <= ub + 0.05, (
                f"Left joint {i} ({link.name}): {angle:.4f} outside [{lb:.4f}, {ub:.4f}]"
            )

    def test_dual_arm_right_bounds(self, results, right_chain):
        res = results["dual1"]
        for i, (angle, link) in enumerate(
            zip(res["right_joint_angles"], right_chain.links)
        ):
            lb, ub = link.bounds
            assert lb - 0.05 <= angle <= ub + 0.05, (
                f"Right joint {i} ({link.name}): {angle:.4f} outside [{lb:.4f}, {ub:.4f}]"
            )

    def test_dual_arm_achieved_positions_consistent(self, results, left_chain, right_chain):
        res = results["dual1"]
        left_fk = left_chain.forward_kinematics(res["left_joint_angles"])
        right_fk = right_chain.forward_kinematics(res["right_joint_angles"])
        np.testing.assert_allclose(
            res["left_achieved_position"], left_fk[:3, 3].tolist(), atol=1e-3
        )
        np.testing.assert_allclose(
            res["right_achieved_position"], right_fk[:3, 3].tolist(), atol=1e-3
        )
