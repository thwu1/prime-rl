"""
Tests for Xacro Manipulator Pipeline with Dynamics Analysis.

"""

import json
import math
import os

import numpy as np
from lxml import etree


# ---- Helper: Rodrigues rotation ----

def rodrigues(axis, angle):
    """Compute 3x3 rotation matrix from axis-angle using Rodrigues' formula."""
    axis = np.array(axis, dtype=float)
    norm = np.linalg.norm(axis)
    if norm < 1e-12:
        return np.eye(3)
    axis = axis / norm
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0]
    ])
    return np.eye(3) * math.cos(angle) + (1 - math.cos(angle)) * np.outer(axis, axis) + math.sin(angle) * K


def homogeneous(R, t):
    """Build 4x4 homogeneous transform from 3x3 rotation and 3-vector translation."""
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


# ---- Corrected robot parameters ----

# Corrected joint data: (axis_local, origin_xyz)
_JOINTS = [
    ([0, 0, 1], [0, 0, 0.1]),                                      # shoulder_pan
    ([0, 1.0 / math.sqrt(2), 1.0 / math.sqrt(2)], [0, 0, 0.3]),   # shoulder_lift (normalized)
    ([0, 1, 0], [0, 0, 0.4]),                                      # elbow
    ([0, 0, 1], [0, 0, 0.35]),                                     # wrist
]
_ANGLES = [0.5, -0.3, 0.8, -0.2]

# Corrected link data: (mass, com_local, I_local)
# shoulder_link izz corrected: 0.05 -> 0.02 (triangle inequality)
# wrist_link mass corrected: -1.0 -> 1.0 (absolute value)
_LINK_DATA = [
    (3.0, np.array([0, 0, 0.15]), np.diag([0.01, 0.01, 0.02])),
    (2.5, np.array([0, 0, 0.2]),  np.diag([0.04, 0.04, 0.005])),
    (2.0, np.array([0, 0, 0.175]), np.diag([0.025, 0.025, 0.003])),
    (1.0, np.array([0, 0, 0.05]), np.diag([0.002, 0.002, 0.001])),
    (0.5, np.array([0, 0, 0.01]), np.diag([0.0002, 0.0002, 0.0003])),
]


# ---- Unified FK chain computation ----

def _compute_chain_data():
    """Compute full FK chain: EE pose, joint origins/axes, link transforms."""
    T = np.eye(4)
    joint_origins = []
    joint_axes = []
    link_transforms = []

    for i, (axis_local, xyz) in enumerate(_JOINTS):
        p = T[:3, :3] @ np.array(xyz) + T[:3, 3]
        z = T[:3, :3] @ np.array(axis_local)
        joint_origins.append(p)
        joint_axes.append(z)

        R = rodrigues(axis_local, _ANGLES[i])
        T_j = homogeneous(R, xyz)
        T = T @ T_j
        link_transforms.append(T.copy())

    # Fixed ee_joint
    T_ee = T @ homogeneous(np.eye(3), [0, 0, 0.1])
    link_transforms.append(T_ee.copy())

    return T_ee, joint_origins, joint_axes, link_transforms


def compute_expected_fk():
    T_ee, _, _, _ = _compute_chain_data()
    return T_ee


def compute_expected_jacobian():
    T_ee, joint_origins, joint_axes, _ = _compute_chain_data()
    p_ee = T_ee[:3, 3]
    J = np.zeros((6, 4))
    for i in range(4):
        J[:3, i] = np.cross(joint_axes[i], p_ee - joint_origins[i])
        J[3:, i] = joint_axes[i]
    return J


def compute_expected_manipulability():
    J = compute_expected_jacobian()
    J_pos = J[:3, :]
    JJT = J_pos @ J_pos.T
    manip = math.sqrt(max(np.linalg.det(JJT), 0.0))
    eigenvalues = np.linalg.eigvalsh(JJT)
    axes = sorted([math.sqrt(max(ev, 0.0)) for ev in eigenvalues], reverse=True)
    return manip, axes


def compute_expected_mass_properties():
    """Compute total mass and CoM at zero configuration for corrected robot."""
    links = [
        (5.0, np.array([0, 0, 0.05]), np.array([0, 0, 0])),
        (3.0, np.array([0, 0, 0.15]), np.array([0, 0, 0.1])),
        (2.5, np.array([0, 0, 0.2]),  np.array([0, 0, 0.4])),
        (2.0, np.array([0, 0, 0.175]), np.array([0, 0, 0.8])),
        (1.0, np.array([0, 0, 0.05]), np.array([0, 0, 1.15])),
        (0.5, np.array([0, 0, 0.01]), np.array([0, 0, 1.25])),
    ]
    total_mass = sum(m for m, _, _ in links)
    com = sum(m * (origin + local_com) for m, local_com, origin in links) / total_mass
    return total_mass, com.tolist()


def _compute_link_world_data():
    """Compute link CoM and inertia in world frame at given joint angles."""
    _, _, _, link_transforms = _compute_chain_data()
    link_com_world = []
    link_I_world = []
    for k in range(5):
        _, com_local, I_local = _LINK_DATA[k]
        R_k = link_transforms[k][:3, :3]
        c_k = R_k @ com_local + link_transforms[k][:3, 3]
        I_k = R_k @ I_local @ R_k.T
        link_com_world.append(c_k)
        link_I_world.append(I_k)
    return link_com_world, link_I_world


def compute_expected_mass_matrix():
    """Compute 4x4 joint-space mass matrix M(q) via Lagrangian formulation."""
    _, joint_origins, joint_axes, _ = _compute_chain_data()
    link_com, link_I = _compute_link_world_data()
    n_joints = 4
    n_links = 5

    M = np.zeros((n_joints, n_joints))
    for i in range(n_joints):
        for j in range(i, n_joints):
            for k in range(max(i, j), n_links):
                m_k = _LINK_DATA[k][0]
                c_k = link_com[k]
                I_k = link_I[k]
                z_i = joint_axes[i]
                z_j = joint_axes[j]
                o_i = joint_origins[i]
                o_j = joint_origins[j]

                # Rotational inertia contribution
                M[i, j] += z_i @ I_k @ z_j
                # Translational inertia contribution
                M[i, j] += m_k * np.cross(z_i, c_k - o_i) @ np.cross(z_j, c_k - o_j)

            M[j, i] = M[i, j]

    return M


def compute_expected_gravity_torques():
    """Compute gravity torque vector g(q) with g_acc = [0, 0, -9.81]."""
    g_acc = np.array([0, 0, -9.81])
    _, joint_origins, joint_axes, _ = _compute_chain_data()
    link_com, _ = _compute_link_world_data()
    n_joints = 4
    n_links = 5

    g = np.zeros(n_joints)
    for i in range(n_joints):
        for k in range(i, n_links):
            m_k = _LINK_DATA[k][0]
            c_k = link_com[k]
            z_i = joint_axes[i]
            o_i = joint_origins[i]
            g[i] -= m_k * g_acc @ np.cross(z_i, c_k - o_i)

    return g


def compute_expected_dynamic_manipulability():
    """Compute dynamic manipulability from J_pos * M^{-1}."""
    J = compute_expected_jacobian()
    M = compute_expected_mass_matrix()
    J_pos = J[:3, :]
    M_inv = np.linalg.inv(M)
    A = J_pos @ M_inv  # 3x4
    AAT = A @ A.T  # 3x3
    dyn_manip = math.sqrt(max(np.linalg.det(AAT), 0.0))
    eigenvalues = np.linalg.eigvalsh(AAT)
    dyn_axes = sorted([math.sqrt(max(ev, 0.0)) for ev in eigenvalues], reverse=True)
    return dyn_manip, dyn_axes


EXPECTED_URDF_ERROR_ELEMENTS = {
    "shoulder_link",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_joint",
    "wrist_link",
}


# ---- Tests ----

class TestErrorsJson:
    def test_errors_file_exists(self):
        assert os.path.isfile("/app/errors.json"), "errors.json not found"

    def test_errors_count(self):
        with open("/app/errors.json") as f:
            errors = json.load(f)
        assert isinstance(errors, list), "errors.json must be a JSON list"
        assert len(errors) == 6, f"Expected 6 errors (1 xacro + 5 URDF), got {len(errors)}"

    def test_errors_have_required_keys(self):
        with open("/app/errors.json") as f:
            errors = json.load(f)
        for err in errors:
            assert "error_type" in err, f"Missing 'error_type' key in error: {err}"
            assert "element" in err, f"Missing 'element' key in error: {err}"
            assert "description" in err, f"Missing 'description' key in error: {err}"

    def test_errors_cover_urdf_elements(self):
        with open("/app/errors.json") as f:
            errors = json.load(f)
        found_elements = {e["element"] for e in errors}
        for expected in EXPECTED_URDF_ERROR_ELEMENTS:
            assert expected in found_elements, (
                f"Expected error on element '{expected}' not found. "
                f"Found elements: {found_elements}"
            )

    def test_errors_include_xacro_error(self):
        with open("/app/errors.json") as f:
            errors = json.load(f)
        xacro_keywords = {"xacro", "property", "undefined", "damping", "macro", "preprocess"}
        found = False
        for err in errors:
            text = (err.get("error_type", "") + " " + err.get("description", "")).lower()
            if any(kw in text for kw in xacro_keywords):
                found = True
                break
        assert found, (
            "Expected at least one error related to xacro preprocessing "
            "(should mention 'xacro', 'property', 'undefined', 'damping', or 'macro')"
        )


class TestFixedUrdf:
    def _parse(self):
        tree = etree.parse("/app/robot_fixed.urdf")
        return tree.getroot()

    def test_fixed_urdf_exists(self):
        assert os.path.isfile("/app/robot_fixed.urdf"), "robot_fixed.urdf not found"

    def test_valid_xml(self):
        root = self._parse()
        assert root.tag == "robot", "Root element must be <robot>"

    def test_elbow_child_link_fixed(self):
        root = self._parse()
        elbow = root.find(".//joint[@name='elbow_joint']")
        assert elbow is not None, "elbow_joint not found"
        child = elbow.find("child")
        assert child is not None, "elbow_joint missing <child>"
        child_link = child.get("link")
        assert child_link == "forearm_link", (
            f"elbow_joint child should be 'forearm_link', got '{child_link}'"
        )

    def test_shoulder_lift_axis_normalized(self):
        root = self._parse()
        joint = root.find(".//joint[@name='shoulder_lift_joint']")
        assert joint is not None
        axis_elem = joint.find("axis")
        assert axis_elem is not None
        xyz = axis_elem.get("xyz").split()
        vals = [float(v) for v in xyz]
        length = math.sqrt(sum(v * v for v in vals))
        assert abs(length - 1.0) < 1e-4, (
            f"shoulder_lift_joint axis not normalized: length={length}"
        )

    def test_shoulder_inertia_valid(self):
        root = self._parse()
        link = root.find(".//link[@name='shoulder_link']")
        assert link is not None
        inertia = link.find(".//inertia")
        assert inertia is not None
        ixx = float(inertia.get("ixx"))
        iyy = float(inertia.get("iyy"))
        izz = float(inertia.get("izz"))
        assert ixx + iyy >= izz, f"Triangle inequality violated: {ixx}+{iyy} < {izz}"
        assert ixx + izz >= iyy, f"Triangle inequality violated: {ixx}+{izz} < {iyy}"
        assert iyy + izz >= ixx, f"Triangle inequality violated: {iyy}+{izz} < {ixx}"

    def test_wrist_joint_limits_valid(self):
        root = self._parse()
        joint = root.find(".//joint[@name='wrist_joint']")
        assert joint is not None
        limit = joint.find("limit")
        assert limit is not None
        lower = float(limit.get("lower"))
        upper = float(limit.get("upper"))
        assert lower < upper, f"wrist_joint limits inverted: lower={lower}, upper={upper}"

    def test_wrist_link_mass_positive(self):
        root = self._parse()
        link = root.find(".//link[@name='wrist_link']")
        assert link is not None
        mass = link.find(".//mass")
        assert mass is not None
        val = float(mass.get("value"))
        assert val > 0, f"wrist_link mass must be positive, got {val}"

    def test_all_links_reachable(self):
        root = self._parse()
        link_names = {l.get("name") for l in root.findall(".//link")}
        for j in root.findall(".//joint"):
            child = j.find("child")
            if child is not None:
                child_name = child.get("link")
                assert child_name in link_names, (
                    f"Joint '{j.get('name')}' references non-existent child link '{child_name}'"
                )


class TestForwardKinematics:
    def test_ee_pose_exists(self):
        assert os.path.isfile("/app/ee_pose.json"), "ee_pose.json not found"

    def test_ee_pose_shape(self):
        with open("/app/ee_pose.json") as f:
            data = json.load(f)
        assert "transform" in data, "ee_pose.json must have 'transform' key"
        T = data["transform"]
        assert len(T) == 4, "Transform must be 4x4"
        for row in T:
            assert len(row) == 4, "Each row must have 4 elements"

    def test_ee_pose_bottom_row(self):
        with open("/app/ee_pose.json") as f:
            data = json.load(f)
        T = np.array(data["transform"])
        np.testing.assert_allclose(T[3], [0, 0, 0, 1], atol=1e-6,
                                    err_msg="Bottom row must be [0,0,0,1]")

    def test_ee_pose_rotation_orthogonal(self):
        with open("/app/ee_pose.json") as f:
            data = json.load(f)
        T = np.array(data["transform"])
        R = T[:3, :3]
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-4,
                                    err_msg="Rotation must be orthogonal")
        np.testing.assert_allclose(np.linalg.det(R), 1.0, atol=1e-4,
                                    err_msg="Rotation must have det=1")

    def test_ee_pose_values(self):
        with open("/app/ee_pose.json") as f:
            data = json.load(f)
        T_actual = np.array(data["transform"])
        T_expected = compute_expected_fk()
        np.testing.assert_allclose(T_actual, T_expected, atol=1e-3,
                                    err_msg="FK result does not match expected values")


class TestMassProperties:
    def test_mass_properties_exists(self):
        assert os.path.isfile("/app/mass_properties.json"), "mass_properties.json not found"

    def test_total_mass(self):
        with open("/app/mass_properties.json") as f:
            data = json.load(f)
        assert "total_mass" in data
        assert abs(data["total_mass"] - 14.0) < 1e-4, (
            f"Total mass should be 14.0, got {data['total_mass']}"
        )

    def test_center_of_mass(self):
        with open("/app/mass_properties.json") as f:
            data = json.load(f)
        assert "center_of_mass" in data
        com = data["center_of_mass"]
        assert len(com) == 3

        _, expected_com = compute_expected_mass_properties()
        np.testing.assert_allclose(com, expected_com, atol=1e-3,
                                    err_msg="Center of mass does not match expected values")


class TestJacobian:
    def test_jacobian_exists(self):
        assert os.path.isfile("/app/jacobian.json"), "jacobian.json not found"

    def test_jacobian_shape(self):
        with open("/app/jacobian.json") as f:
            data = json.load(f)
        assert "jacobian" in data, "jacobian.json must have 'jacobian' key"
        J = data["jacobian"]
        assert len(J) == 6, f"Jacobian must have 6 rows, got {len(J)}"
        for i, row in enumerate(J):
            assert len(row) == 4, f"Row {i} must have 4 elements, got {len(row)}"

    def test_jacobian_values(self):
        with open("/app/jacobian.json") as f:
            data = json.load(f)
        J_actual = np.array(data["jacobian"])
        J_expected = compute_expected_jacobian()
        np.testing.assert_allclose(J_actual, J_expected, atol=1e-3,
                                    err_msg="Jacobian does not match expected values")

    def test_jacobian_angular_rows_unit_norm(self):
        with open("/app/jacobian.json") as f:
            data = json.load(f)
        J = np.array(data["jacobian"])
        for col in range(4):
            angular = J[3:, col]
            norm = np.linalg.norm(angular)
            assert abs(norm - 1.0) < 1e-3, (
                f"Angular part of column {col} should be unit length, got {norm}"
            )


class TestDynamics:
    def test_dynamics_exists(self):
        assert os.path.isfile("/app/dynamics.json"), "dynamics.json not found"

    def test_mass_matrix_shape(self):
        with open("/app/dynamics.json") as f:
            data = json.load(f)
        assert "mass_matrix" in data, "dynamics.json must have 'mass_matrix' key"
        M = data["mass_matrix"]
        assert len(M) == 4, f"Mass matrix must have 4 rows, got {len(M)}"
        for i, row in enumerate(M):
            assert len(row) == 4, f"Row {i} must have 4 elements, got {len(row)}"

    def test_mass_matrix_symmetric(self):
        with open("/app/dynamics.json") as f:
            data = json.load(f)
        M = np.array(data["mass_matrix"])
        np.testing.assert_allclose(M, M.T, atol=1e-6,
                                    err_msg="Mass matrix must be symmetric")

    def test_mass_matrix_positive_definite(self):
        with open("/app/dynamics.json") as f:
            data = json.load(f)
        M = np.array(data["mass_matrix"])
        eigenvalues = np.linalg.eigvalsh(M)
        assert all(ev > 0 for ev in eigenvalues), (
            f"Mass matrix must be positive definite, eigenvalues: {eigenvalues}"
        )

    def test_mass_matrix_values(self):
        with open("/app/dynamics.json") as f:
            data = json.load(f)
        M_actual = np.array(data["mass_matrix"])
        M_expected = compute_expected_mass_matrix()
        np.testing.assert_allclose(M_actual, M_expected, atol=1e-3,
                                    err_msg="Mass matrix does not match expected values")

    def test_gravity_torques_length(self):
        with open("/app/dynamics.json") as f:
            data = json.load(f)
        assert "gravity_torques" in data, "dynamics.json must have 'gravity_torques' key"
        g = data["gravity_torques"]
        assert len(g) == 4, f"Gravity torques must have 4 elements, got {len(g)}"

    def test_gravity_shoulder_pan_zero(self):
        """Shoulder pan rotates about the gravity axis — its gravity torque is always zero."""
        with open("/app/dynamics.json") as f:
            data = json.load(f)
        g = data["gravity_torques"]
        assert abs(g[0]) < 1e-6, (
            f"Shoulder pan gravity torque should be 0 (vertical axis), got {g[0]}"
        )

    def test_gravity_torques_values(self):
        with open("/app/dynamics.json") as f:
            data = json.load(f)
        g_actual = np.array(data["gravity_torques"])
        g_expected = compute_expected_gravity_torques()
        np.testing.assert_allclose(g_actual, g_expected, atol=1e-3,
                                    err_msg="Gravity torques do not match expected values")


class TestManipulability:
    def test_manipulability_exists(self):
        assert os.path.isfile("/app/manipulability.json"), "manipulability.json not found"

    def test_manipulability_index(self):
        with open("/app/manipulability.json") as f:
            data = json.load(f)
        assert "manipulability_index" in data
        expected_manip, _ = compute_expected_manipulability()
        assert abs(data["manipulability_index"] - expected_manip) < 1e-3, (
            f"Manipulability index expected {expected_manip:.6f}, "
            f"got {data['manipulability_index']}"
        )

    def test_ellipsoid_axes_count(self):
        with open("/app/manipulability.json") as f:
            data = json.load(f)
        assert "ellipsoid_axes" in data
        axes = data["ellipsoid_axes"]
        assert len(axes) == 3, f"Expected 3 ellipsoid axes, got {len(axes)}"

    def test_ellipsoid_axes_values(self):
        with open("/app/manipulability.json") as f:
            data = json.load(f)
        _, expected_axes = compute_expected_manipulability()
        np.testing.assert_allclose(data["ellipsoid_axes"], expected_axes, atol=1e-3,
                                    err_msg="Ellipsoid axes do not match expected values")

    def test_ellipsoid_axes_descending(self):
        with open("/app/manipulability.json") as f:
            data = json.load(f)
        axes = data["ellipsoid_axes"]
        for i in range(len(axes) - 1):
            assert axes[i] >= axes[i + 1] - 1e-6, (
                f"Axes must be in descending order: {axes}"
            )

    def test_manipulability_positive(self):
        with open("/app/manipulability.json") as f:
            data = json.load(f)
        assert data["manipulability_index"] > 0, (
            "Manipulability index should be positive at a non-singular configuration"
        )

    def test_dynamic_manipulability_index(self):
        with open("/app/manipulability.json") as f:
            data = json.load(f)
        assert "dynamic_manipulability_index" in data
        expected_dyn, _ = compute_expected_dynamic_manipulability()
        assert abs(data["dynamic_manipulability_index"] - expected_dyn) < 1e-3, (
            f"Dynamic manipulability expected {expected_dyn:.6f}, "
            f"got {data['dynamic_manipulability_index']}"
        )

    def test_dynamic_ellipsoid_axes_count(self):
        with open("/app/manipulability.json") as f:
            data = json.load(f)
        assert "dynamic_ellipsoid_axes" in data
        axes = data["dynamic_ellipsoid_axes"]
        assert len(axes) == 3, f"Expected 3 dynamic ellipsoid axes, got {len(axes)}"

    def test_dynamic_ellipsoid_axes_values(self):
        with open("/app/manipulability.json") as f:
            data = json.load(f)
        _, expected_axes = compute_expected_dynamic_manipulability()
        np.testing.assert_allclose(data["dynamic_ellipsoid_axes"], expected_axes, atol=1e-3,
                                    err_msg="Dynamic ellipsoid axes do not match expected")

    def test_dynamic_ellipsoid_axes_descending(self):
        with open("/app/manipulability.json") as f:
            data = json.load(f)
        axes = data["dynamic_ellipsoid_axes"]
        for i in range(len(axes) - 1):
            assert axes[i] >= axes[i + 1] - 1e-6, (
                f"Dynamic axes must be in descending order: {axes}"
            )
