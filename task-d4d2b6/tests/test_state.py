
import json
import os
import sqlite3
import subprocess

import numpy as np
import pytest
import ikpy.chain


# ============================================================
# Reference chain construction using ikpy as oracle
# ============================================================

def build_reference_chain():
    """Build Baxter right arm chain using ikpy."""
    base_elements = [
        "base", "torso_t0",
        "torso", "right_torso_arm_mount",
        "right_arm_mount", "right_s0",
        "right_upper_shoulder", "right_s1",
        "right_lower_shoulder", "right_e0",
        "right_upper_elbow", "right_e1",
        "right_lower_elbow", "right_w0",
        "right_upper_forearm", "right_w1",
        "right_lower_forearm", "right_w2",
        "right_wrist", "right_hand",
        "right_hand", "right_gripper_base",
        "right_gripper_base", "right_endpoint",
        "right_gripper",
    ]
    chain = ikpy.chain.Chain.from_urdf_file(
        "/app/baxter.urdf",
        base_elements=base_elements,
        active_links_mask=[
            False, False, False,
            True, True, True, True, True, True, True,
            False, False, False,
        ],
        name="baxter_right_arm",
    )
    return chain


def angles_to_full(q):
    """Convert 7 active joint angles to full 13-link vector."""
    return [0, 0, 0] + list(q) + [0, 0, 0]


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def db():
    conn = sqlite3.connect("/app/results.db")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def ref_chain():
    return build_reference_chain()


# ============================================================
# SQLite schema tests
# ============================================================

class TestSQLiteSchema:
    def test_database_exists(self):
        assert os.path.exists("/app/results.db"), "results.db not found"

    def test_chain_info_table(self, db):
        cur = db.execute(
            "SELECT joint_name, joint_index, lower_limit, upper_limit "
            "FROM chain_info ORDER BY joint_index"
        )
        rows = cur.fetchall()
        assert len(rows) == 7, f"Expected 7 chain_info rows, got {len(rows)}"

    def test_chain_info_names(self, db):
        cur = db.execute(
            "SELECT joint_name FROM chain_info ORDER BY joint_index"
        )
        names = [r["joint_name"] for r in cur.fetchall()]
        expected = [
            "right_s0", "right_s1", "right_e0", "right_e1",
            "right_w0", "right_w1", "right_w2",
        ]
        assert names == expected

    def test_chain_info_limits_valid(self, db):
        cur = db.execute("SELECT lower_limit, upper_limit FROM chain_info")
        for row in cur.fetchall():
            assert row["lower_limit"] < row["upper_limit"]
            assert row["lower_limit"] >= -4.0
            assert row["upper_limit"] <= 4.0

    def test_fk_results_count(self, db):
        cur = db.execute("SELECT COUNT(*) as cnt FROM fk_results")
        assert cur.fetchone()["cnt"] == 3

    def test_jacobian_results_count(self, db):
        cur = db.execute("SELECT COUNT(*) as cnt FROM jacobian_results")
        assert cur.fetchone()["cnt"] == 2

    def test_ik_solutions_count(self, db):
        cur = db.execute("SELECT COUNT(*) as cnt FROM ik_solutions")
        assert cur.fetchone()["cnt"] == 3


# ============================================================
# XML report tests (verified via xmlstarlet)
# ============================================================

class TestXMLReport:
    def test_xml_exists(self):
        assert os.path.exists("/app/results.xml"), "results.xml not found"

    def test_xml_wellformed(self):
        result = subprocess.run(
            ["xmlstarlet", "val", "-w", "/app/results.xml"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"XML not well-formed: {result.stderr}"
        )

    def test_xml_root_attributes(self):
        result = subprocess.run(
            ["xmlstarlet", "sel", "-t",
             "-v", "/kinematic_report/@robot", "-n",
             "-v", "/kinematic_report/@chain", "-n",
             "-v", "/kinematic_report/@dof", "-n",
             "/app/results.xml"],
            capture_output=True, text=True,
        )
        lines = result.stdout.strip().split("\n")
        assert lines[0] == "baxter"
        assert lines[1] == "right_arm"
        assert lines[2] == "7"

    def test_xml_joint_count(self):
        result = subprocess.run(
            ["xmlstarlet", "sel", "-t",
             "-v", "count(//chain/joint)",
             "/app/results.xml"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "7"

    def test_xml_joint_names(self):
        result = subprocess.run(
            ["xmlstarlet", "sel", "-t",
             "-m", "//chain/joint",
             "-v", "@name", "-n",
             "/app/results.xml"],
            capture_output=True, text=True,
        )
        names = result.stdout.strip().split("\n")
        expected = [
            "right_s0", "right_s1", "right_e0", "right_e1",
            "right_w0", "right_w1", "right_w2",
        ]
        assert names == expected

    def test_xml_fk_config_count(self):
        result = subprocess.run(
            ["xmlstarlet", "sel", "-t",
             "-v", "count(//fk_results/config)",
             "/app/results.xml"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "3"

    def test_xml_fk_position_elements(self):
        result = subprocess.run(
            ["xmlstarlet", "sel", "-t",
             "-v", "count(//fk_results/config/position)",
             "/app/results.xml"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "3"

    def test_xml_ik_target_count(self):
        result = subprocess.run(
            ["xmlstarlet", "sel", "-t",
             "-v", "count(//ik_solutions/target)",
             "/app/results.xml"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "3"

    def test_xml_ik_errors_small(self):
        """IK position errors reported in XML must be below 2cm."""
        result = subprocess.run(
            ["xmlstarlet", "sel", "-t",
             "-m", "//ik_solutions/target",
             "-v", "@error", "-n",
             "/app/results.xml"],
            capture_output=True, text=True,
        )
        for line in result.stdout.strip().split("\n"):
            err = float(line)
            assert err < 0.02, f"IK error {err} exceeds 2cm in XML report"


# ============================================================
# Forward kinematics accuracy tests (from SQLite)
# ============================================================

class TestForwardKinematics:
    def test_fk_pose_shape(self, db):
        cur = db.execute("SELECT pose_matrix FROM fk_results")
        for row in cur.fetchall():
            pose = np.array(json.loads(row["pose_matrix"]))
            assert pose.shape == (4, 4)

    def test_fk_homogeneous(self, db):
        """Last row of homogeneous matrix should be [0, 0, 0, 1]."""
        cur = db.execute("SELECT pose_matrix FROM fk_results")
        for row in cur.fetchall():
            pose = np.array(json.loads(row["pose_matrix"]))
            np.testing.assert_allclose(pose[3, :], [0, 0, 0, 1], atol=1e-6)

    def test_fk_rotation_orthogonal(self, db):
        cur = db.execute("SELECT pose_matrix FROM fk_results")
        for row in cur.fetchall():
            R = np.array(json.loads(row["pose_matrix"]))[:3, :3]
            np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-4)

    def test_fk_position_accuracy(self, db, ref_chain):
        """FK positions must match ikpy oracle within 1cm."""
        cur = db.execute(
            "SELECT joint_angles, pose_matrix FROM fk_results "
            "ORDER BY config_id"
        )
        for row in cur.fetchall():
            q = json.loads(row["joint_angles"])
            agent_pose = np.array(json.loads(row["pose_matrix"]))
            ref_pose = ref_chain.forward_kinematics(angles_to_full(q))
            np.testing.assert_allclose(
                agent_pose[:3, 3], ref_pose[:3, 3], atol=0.01,
                err_msg=f"FK position mismatch for q={q}",
            )

    def test_fk_orientation_accuracy(self, db, ref_chain):
        """FK orientations must match ikpy oracle."""
        cur = db.execute(
            "SELECT joint_angles, pose_matrix FROM fk_results "
            "ORDER BY config_id"
        )
        for row in cur.fetchall():
            q = json.loads(row["joint_angles"])
            agent_R = np.array(json.loads(row["pose_matrix"]))[:3, :3]
            ref_R = ref_chain.forward_kinematics(angles_to_full(q))[:3, :3]
            np.testing.assert_allclose(
                agent_R, ref_R, atol=0.02,
                err_msg=f"FK orientation mismatch for q={q}",
            )


# ============================================================
# Jacobian / velocity analysis tests (from SQLite)
# ============================================================

class TestJacobian:
    def test_jacobian_shape(self, db):
        cur = db.execute("SELECT jacobian_matrix FROM jacobian_results")
        for row in cur.fetchall():
            J = np.array(json.loads(row["jacobian_matrix"]))
            assert J.shape == (6, 7)

    def test_jacobian_finite_diff(self, db, ref_chain):
        """Position rows of Jacobian must match finite differences of ikpy FK."""
        eps = 1e-5
        cur = db.execute(
            "SELECT joint_angles, jacobian_matrix FROM jacobian_results "
            "ORDER BY config_id"
        )
        for row in cur.fetchall():
            q = json.loads(row["joint_angles"])
            J_agent = np.array(json.loads(row["jacobian_matrix"]))

            J_num = np.zeros((3, 7))
            for i in range(7):
                q_plus = list(q)
                q_plus[i] += eps
                p_plus = ref_chain.forward_kinematics(
                    angles_to_full(q_plus)
                )[:3, 3]

                q_minus = list(q)
                q_minus[i] -= eps
                p_minus = ref_chain.forward_kinematics(
                    angles_to_full(q_minus)
                )[:3, 3]

                J_num[:, i] = (p_plus - p_minus) / (2 * eps)

            np.testing.assert_allclose(
                J_agent[:3, :], J_num, atol=0.01,
                err_msg=f"Jacobian position rows mismatch for q={q}",
            )

    def test_manipulability_positive(self, db):
        cur = db.execute("SELECT manipulability FROM jacobian_results")
        for row in cur.fetchall():
            assert row["manipulability"] > 0
            assert np.isfinite(row["manipulability"])

    def test_condition_number(self, db):
        cur = db.execute("SELECT condition_number FROM jacobian_results")
        for row in cur.fetchall():
            assert row["condition_number"] > 0
            assert np.isfinite(row["condition_number"])


# ============================================================
# Inverse kinematics tests (from SQLite)
# ============================================================

class TestInverseKinematics:
    def test_ik_joint_count(self, db):
        cur = db.execute("SELECT solution_angles FROM ik_solutions")
        for row in cur.fetchall():
            q = json.loads(row["solution_angles"])
            assert len(q) == 7

    def test_ik_position_accuracy(self, db, ref_chain):
        """IK solutions must place end-effector near target (ikpy FK oracle)."""
        cur = db.execute(
            "SELECT target_position, solution_angles FROM ik_solutions "
            "ORDER BY target_id"
        )
        for row in cur.fetchall():
            q = json.loads(row["solution_angles"])
            target = np.array(json.loads(row["target_position"]))
            ref_pose = ref_chain.forward_kinematics(angles_to_full(q))
            achieved = ref_pose[:3, 3]
            err = np.linalg.norm(achieved - target)
            assert err < 0.02, (
                f"IK position error {err:.4f}m exceeds 2cm for "
                f"target={target.tolist()}"
            )

    def test_ik_orientation_accuracy(self, db, ref_chain):
        """IK solutions with orientation constraints must approximate target."""
        cur = db.execute(
            "SELECT target_orientation, solution_angles "
            "FROM ik_solutions ORDER BY target_id"
        )
        for row in cur.fetchall():
            orient_str = row["target_orientation"]
            if orient_str is None or orient_str == "null":
                continue
            q = json.loads(row["solution_angles"])
            target_R = np.array(json.loads(orient_str))
            ref_pose = ref_chain.forward_kinematics(angles_to_full(q))
            achieved_R = ref_pose[:3, :3]
            orient_err = np.linalg.norm(achieved_R - target_R, "fro")
            assert orient_err < 0.5, (
                f"IK orientation error (Frobenius) {orient_err:.4f} "
                f"exceeds 0.5"
            )

    def test_ik_joint_limits(self, db):
        """All IK solutions must respect joint limits."""
        limits_cur = db.execute(
            "SELECT lower_limit, upper_limit FROM chain_info "
            "ORDER BY joint_index"
        )
        limits = [(r["lower_limit"], r["upper_limit"])
                  for r in limits_cur.fetchall()]

        sol_cur = db.execute("SELECT solution_angles FROM ik_solutions")
        for row in sol_cur.fetchall():
            q = json.loads(row["solution_angles"])
            for i, (lo, hi) in enumerate(limits):
                assert q[i] >= lo - 0.01, (
                    f"Joint {i} angle {q[i]} below lower limit {lo}"
                )
                assert q[i] <= hi + 0.01, (
                    f"Joint {i} angle {q[i]} above upper limit {hi}"
                )

    def test_ik_self_consistency(self, db):
        """Agent's reported position error should be small."""
        cur = db.execute("SELECT position_error FROM ik_solutions")
        for row in cur.fetchall():
            assert row["position_error"] < 0.02
