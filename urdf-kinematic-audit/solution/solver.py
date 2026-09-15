"""
Xacro Manipulator Pipeline with Dynamics Analysis — solver.

"""

import copy
import json
import math
import subprocess

import numpy as np
from lxml import etree


def rodrigues(axis, angle):
    """Rotation matrix via Rodrigues' formula."""
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
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def parse_xyz(elem, attr="xyz"):
    return [float(v) for v in elem.get(attr).split()]


def main():
    errors = []

    # ==================== STEP 1: Fix and process xacro ====================

    # Read the xacro source
    with open("/app/manipulator.xacro", "r") as f:
        xacro_content = f.read()

    # Detect the xacro property error: damping_coefficient is referenced but
    # the property is defined as damping_coeff
    errors.append({
        "error_type": "xacro_undefined_property",
        "element": "arm_link_joint",
        "description": (
            "Macro 'arm_link_joint' references undefined xacro property "
            "'damping_coefficient' in <dynamics> element. The defined property "
            "name is 'damping_coeff'."
        )
    })

    # Fix: replace the incorrect property reference
    fixed_xacro = xacro_content.replace("damping_coefficient", "damping_coeff")
    with open("/app/manipulator_fixed.xacro", "w") as f:
        f.write(fixed_xacro)

    # Process xacro to URDF
    result = subprocess.run(
        ["xacro", "/app/manipulator_fixed.xacro", "-o", "/app/robot_raw.urdf"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Xacro processing failed: {result.stderr}")
        return
    print("Xacro processed successfully")

    # ==================== STEP 2: Detect and fix URDF errors ====================

    tree = etree.parse("/app/robot_raw.urdf")
    root = tree.getroot()

    link_names = {l.get("name") for l in root.findall(".//link")}

    # Check inertia triangle inequality
    for link in root.findall(".//link"):
        inertia = link.find(".//inertia")
        if inertia is None:
            continue
        ixx = float(inertia.get("ixx"))
        iyy = float(inertia.get("iyy"))
        izz = float(inertia.get("izz"))
        if ixx + iyy < izz or ixx + izz < iyy or iyy + izz < ixx:
            errors.append({
                "error_type": "invalid_inertia",
                "element": link.get("name"),
                "description": (
                    f"Inertia tensor violates triangle inequality: "
                    f"ixx={ixx}, iyy={iyy}, izz={izz}."
                )
            })

    # Check joint axis normalization
    for joint in root.findall(".//joint"):
        axis_elem = joint.find("axis")
        if axis_elem is None:
            continue
        xyz = parse_xyz(axis_elem)
        length = math.sqrt(sum(v * v for v in xyz))
        if abs(length - 1.0) > 1e-6:
            errors.append({
                "error_type": "non_unit_axis",
                "element": joint.get("name"),
                "description": (
                    f"Joint axis is not unit length: xyz=({xyz[0]}, {xyz[1]}, {xyz[2]}), "
                    f"length={length:.6f}."
                )
            })

    # Check child link references
    for joint in root.findall(".//joint"):
        child = joint.find("child")
        if child is None:
            continue
        child_link = child.get("link")
        if child_link not in link_names:
            errors.append({
                "error_type": "dangling_child_link",
                "element": joint.get("name"),
                "description": (
                    f"Joint references non-existent child link '{child_link}'."
                )
            })

    # Check revolute joint limits
    for joint in root.findall(".//joint"):
        if joint.get("type") != "revolute":
            continue
        limit = joint.find("limit")
        if limit is None:
            continue
        lower = float(limit.get("lower"))
        upper = float(limit.get("upper"))
        if lower > upper:
            errors.append({
                "error_type": "inverted_joint_limits",
                "element": joint.get("name"),
                "description": (
                    f"Joint limits inverted: lower={lower} > upper={upper}."
                )
            })

    # Check mass positivity
    for link in root.findall(".//link"):
        mass_elem = link.find(".//mass")
        if mass_elem is None:
            continue
        mass_val = float(mass_elem.get("value"))
        if mass_val <= 0:
            errors.append({
                "error_type": "negative_mass",
                "element": link.get("name"),
                "description": f"Link has non-positive mass: value={mass_val}."
            })

    # Write errors
    with open("/app/errors.json", "w") as f:
        json.dump(errors, f, indent=2)
    print(f"Found {len(errors)} errors")

    # ---- Apply fixes ----
    fixed_tree = copy.deepcopy(tree)
    fixed_root = fixed_tree.getroot()

    # Fix inertia triangle inequality
    for link in fixed_root.findall(".//link"):
        inertia = link.find(".//inertia")
        if inertia is None:
            continue
        ixx = float(inertia.get("ixx"))
        iyy = float(inertia.get("iyy"))
        izz = float(inertia.get("izz"))
        if ixx + iyy < izz:
            inertia.set("izz", str(ixx + iyy))
        if ixx + izz < iyy:
            inertia.set("iyy", str(ixx + izz))
        if iyy + izz < ixx:
            inertia.set("ixx", str(iyy + izz))

    # Normalize joint axes
    for joint in fixed_root.findall(".//joint"):
        axis_elem = joint.find("axis")
        if axis_elem is None:
            continue
        xyz = parse_xyz(axis_elem)
        length = math.sqrt(sum(v * v for v in xyz))
        if abs(length - 1.0) > 1e-6 and length > 1e-12:
            normalized = [v / length for v in xyz]
            axis_elem.set("xyz", f"{normalized[0]} {normalized[1]} {normalized[2]}")

    # Fix dangling child references
    for joint in fixed_root.findall(".//joint"):
        child = joint.find("child")
        if child is None:
            continue
        child_link = child.get("link")
        if child_link not in link_names:
            import difflib
            matches = difflib.get_close_matches(child_link, link_names, n=1, cutoff=0.5)
            if matches:
                child.set("link", matches[0])

    # Fix inverted joint limits
    for joint in fixed_root.findall(".//joint"):
        if joint.get("type") != "revolute":
            continue
        limit = joint.find("limit")
        if limit is None:
            continue
        lower = float(limit.get("lower"))
        upper = float(limit.get("upper"))
        if lower > upper:
            limit.set("lower", str(upper))
            limit.set("upper", str(lower))

    # Fix negative masses
    for link in fixed_root.findall(".//link"):
        mass_elem = link.find(".//mass")
        if mass_elem is None:
            continue
        mass_val = float(mass_elem.get("value"))
        if mass_val <= 0:
            mass_elem.set("value", str(abs(mass_val)))

    # Write fixed URDF
    fixed_tree.write("/app/robot_fixed.urdf", xml_declaration=True, encoding="UTF-8")
    print("Written robot_fixed.urdf")

    # ==================== STEP 3: Kinematics and Dynamics ====================

    joint_order = ["shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
                   "wrist_joint", "ee_joint"]
    angles = [0.5, -0.3, 0.8, -0.2]

    T_total = np.eye(4)
    angle_idx = 0
    joint_origins = []
    joint_axes = []
    link_transforms = []

    for jname in joint_order:
        joint = fixed_root.find(f".//joint[@name='{jname}']")
        origin = joint.find("origin")
        xyz = parse_xyz(origin) if origin is not None else [0, 0, 0]

        jtype = joint.get("type")

        if jtype == "revolute":
            axis_elem = joint.find("axis")
            axis_local = parse_xyz(axis_elem) if axis_elem is not None else [0, 0, 1]
            theta = angles[angle_idx]
            angle_idx += 1
            R = rodrigues(axis_local, theta)

            p_joint = T_total[:3, :3] @ np.array(xyz) + T_total[:3, 3]
            z_joint = T_total[:3, :3] @ np.array(axis_local)
            joint_origins.append(p_joint)
            joint_axes.append(z_joint)
        else:
            R = np.eye(3)

        T_joint = homogeneous(R, xyz)
        T_total = T_total @ T_joint

        if jtype == "revolute":
            link_transforms.append(T_total.copy())

    # EE link transform (from fixed joint)
    link_transforms.append(T_total.copy())

    # Write FK result
    ee_pose = T_total.tolist()
    with open("/app/ee_pose.json", "w") as f:
        json.dump({"transform": ee_pose}, f, indent=2)
    print(f"EE position: {T_total[:3, 3]}")

    # Build 6x4 geometric Jacobian
    p_ee = T_total[:3, 3]
    J = np.zeros((6, 4))
    for i in range(4):
        J[:3, i] = np.cross(joint_axes[i], p_ee - joint_origins[i])
        J[3:, i] = joint_axes[i]

    with open("/app/jacobian.json", "w") as f:
        json.dump({"jacobian": J.tolist()}, f, indent=2)

    # ---- Mass matrix M(q) ----
    # Collect link data from fixed URDF
    chain = [
        ("shoulder_pan_joint", "shoulder_link"),
        ("shoulder_lift_joint", "upper_arm_link"),
        ("elbow_joint", "forearm_link"),
        ("wrist_joint", "wrist_link"),
        (None, "ee_link"),
    ]

    link_masses = []
    link_com_local = []
    link_I_local = []

    for _, lname in chain:
        link_elem = fixed_root.find(f".//link[@name='{lname}']")
        mass_val = float(link_elem.find(".//mass").get("value"))
        com_origin = link_elem.find(".//inertial/origin")
        com_l = parse_xyz(com_origin) if com_origin is not None else [0, 0, 0]

        inertia_elem = link_elem.find(".//inertia")
        ixx = float(inertia_elem.get("ixx"))
        ixy = float(inertia_elem.get("ixy"))
        ixz = float(inertia_elem.get("ixz"))
        iyy = float(inertia_elem.get("iyy"))
        iyz = float(inertia_elem.get("iyz"))
        izz = float(inertia_elem.get("izz"))
        I_l = np.array([[ixx, ixy, ixz], [ixy, iyy, iyz], [ixz, iyz, izz]])

        link_masses.append(mass_val)
        link_com_local.append(np.array(com_l))
        link_I_local.append(I_l)

    # Compute link CoM and inertia in world frame
    link_com_world = []
    link_I_world = []
    for k in range(5):
        R_k = link_transforms[k][:3, :3]
        c_k = R_k @ link_com_local[k] + link_transforms[k][:3, 3]
        I_k = R_k @ link_I_local[k] @ R_k.T
        link_com_world.append(c_k)
        link_I_world.append(I_k)

    # Compute mass matrix using Lagrangian formulation
    n_joints = 4
    n_links = 5
    M = np.zeros((n_joints, n_joints))

    for i in range(n_joints):
        for j in range(i, n_joints):
            for k in range(max(i, j), n_links):
                m_k = link_masses[k]
                c_k = link_com_world[k]
                I_k = link_I_world[k]
                z_i = joint_axes[i]
                z_j = joint_axes[j]
                o_i = joint_origins[i]
                o_j = joint_origins[j]

                M[i, j] += z_i @ I_k @ z_j
                M[i, j] += m_k * np.cross(z_i, c_k - o_i) @ np.cross(z_j, c_k - o_j)

            M[j, i] = M[i, j]

    # Compute gravity torques
    g_acc = np.array([0, 0, -9.81])
    g = np.zeros(n_joints)
    for i in range(n_joints):
        for k in range(i, n_links):
            m_k = link_masses[k]
            c_k = link_com_world[k]
            z_i = joint_axes[i]
            o_i = joint_origins[i]
            g[i] -= m_k * g_acc @ np.cross(z_i, c_k - o_i)

    with open("/app/dynamics.json", "w") as f:
        json.dump({
            "mass_matrix": M.tolist(),
            "gravity_torques": g.tolist()
        }, f, indent=2)
    print(f"Mass matrix diagonal: {np.diag(M)}")
    print(f"Gravity torques: {g}")

    # ---- Kinematic manipulability ----
    J_pos = J[:3, :]
    JJT = J_pos @ J_pos.T
    manip = math.sqrt(max(np.linalg.det(JJT), 0.0))
    eigenvalues = np.linalg.eigvalsh(JJT)
    kin_axes = sorted([math.sqrt(max(ev, 0.0)) for ev in eigenvalues], reverse=True)

    # ---- Dynamic manipulability ----
    M_inv = np.linalg.inv(M)
    A = J_pos @ M_inv
    AAT = A @ A.T
    dyn_manip = math.sqrt(max(np.linalg.det(AAT), 0.0))
    dyn_eigenvalues = np.linalg.eigvalsh(AAT)
    dyn_axes = sorted([math.sqrt(max(ev, 0.0)) for ev in dyn_eigenvalues], reverse=True)

    with open("/app/manipulability.json", "w") as f:
        json.dump({
            "manipulability_index": manip,
            "ellipsoid_axes": kin_axes,
            "dynamic_manipulability_index": dyn_manip,
            "dynamic_ellipsoid_axes": dyn_axes
        }, f, indent=2)
    print(f"Kinematic manipulability: {manip}")
    print(f"Dynamic manipulability: {dyn_manip}")

    # ---- Mass properties at zero configuration ----
    T_accum = np.eye(4)
    total_mass = 0.0
    weighted_com = np.zeros(3)

    # Base link (no parent joint)
    base_link = fixed_root.find(".//link[@name='base_link']")
    base_mass = float(base_link.find(".//mass").get("value"))
    base_com_origin = base_link.find(".//inertial/origin")
    base_com = parse_xyz(base_com_origin) if base_com_origin is not None else [0, 0, 0]
    total_mass += base_mass
    weighted_com += base_mass * np.array(base_com)

    zero_chain = [
        ("shoulder_pan_joint", "shoulder_link"),
        ("shoulder_lift_joint", "upper_arm_link"),
        ("elbow_joint", "forearm_link"),
        ("wrist_joint", "wrist_link"),
        ("ee_joint", "ee_link"),
    ]

    T_accum = np.eye(4)
    for jname, lname in zero_chain:
        joint = fixed_root.find(f".//joint[@name='{jname}']")
        origin = joint.find("origin")
        xyz = parse_xyz(origin) if origin is not None else [0, 0, 0]

        T_joint = homogeneous(np.eye(3), xyz)
        T_accum = T_accum @ T_joint

        link = fixed_root.find(f".//link[@name='{lname}']")
        mass_val = float(link.find(".//mass").get("value"))
        com_origin = link.find(".//inertial/origin")
        com_local = parse_xyz(com_origin) if com_origin is not None else [0, 0, 0]

        com_world = T_accum[:3, :3] @ np.array(com_local) + T_accum[:3, 3]
        total_mass += mass_val
        weighted_com += mass_val * com_world

    com = (weighted_com / total_mass).tolist()

    with open("/app/mass_properties.json", "w") as f:
        json.dump({
            "total_mass": total_mass,
            "center_of_mass": com
        }, f, indent=2)
    print(f"Total mass: {total_mass}")
    print(f"Center of mass: {com}")


if __name__ == "__main__":
    main()
