#!/usr/bin/env python3
"""
Kinematic analysis solver for Baxter right arm.
Parses TOML config, computes FK/Jacobian/IK from scratch,
writes results to SQLite database and XML report.
"""

import json
import sqlite3
import tomllib
import xml.etree.ElementTree as ET

import numpy as np


# ====================================================================
# Rotation / transformation utilities
# ====================================================================

def rot_x(t):
    c, s = np.cos(t), np.sin(t)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_y(t):
    c, s = np.cos(t), np.sin(t)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rot_z(t):
    c, s = np.cos(t), np.sin(t)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def rpy_to_rotation(roll, pitch, yaw):
    return rot_z(yaw) @ rot_y(pitch) @ rot_x(roll)


def axis_angle_rotation(axis, theta):
    ax, ay, az = axis
    c, s = np.cos(theta), np.sin(theta)
    return np.array([
        [ax*ax + (1 - ax*ax)*c,  ax*ay*(1 - c) - az*s,  ax*az*(1 - c) + ay*s],
        [ax*ay*(1 - c) + az*s,  ay*ay + (1 - ay*ay)*c,  ay*az*(1 - c) - ax*s],
        [ax*az*(1 - c) - ay*s,  ay*az*(1 - c) + ax*s,  az*az + (1 - az*az)*c],
    ])


def to_homogeneous(R):
    T = np.eye(4)
    T[:3, :3] = R
    return T


def translation_matrix(x, y, z):
    T = np.eye(4)
    T[:3, 3] = [x, y, z]
    return T


# ====================================================================
# URDF joint representation
# ====================================================================

class URDFJoint:
    def __init__(self, name, joint_type, origin_xyz, origin_rpy, axis, limits):
        self.name = name
        self.joint_type = joint_type
        self.origin_xyz = np.array(origin_xyz, dtype=float)
        self.origin_rpy = np.array(origin_rpy, dtype=float)
        self.axis = np.array(axis, dtype=float) if axis is not None else None
        self.limits = limits

    def get_transform(self, theta=0.0):
        T = translation_matrix(*self.origin_xyz)
        T = T @ to_homogeneous(rpy_to_rotation(*self.origin_rpy))
        if self.joint_type == "revolute" and self.axis is not None:
            T = T @ to_homogeneous(axis_angle_rotation(self.axis, theta))
        return T


# ====================================================================
# URDF parser — extract Baxter right arm chain
# ====================================================================

def parse_urdf_right_arm(urdf_path):
    tree = ET.parse(urdf_path)
    root = tree.getroot()

    joints_by_name = {}
    for j in root.findall("joint"):
        jname = j.attrib["name"]
        jtype = j.attrib["type"]

        origin_xyz = [0.0, 0.0, 0.0]
        origin_rpy = [0.0, 0.0, 0.0]
        origin = j.find("origin")
        if origin is not None:
            if "xyz" in origin.attrib:
                origin_xyz = [float(v) for v in origin.attrib["xyz"].split()]
            if "rpy" in origin.attrib:
                origin_rpy = [float(v) for v in origin.attrib["rpy"].split()]

        axis = None
        axis_elem = j.find("axis")
        if axis_elem is not None and jtype == "revolute":
            axis = [float(v) for v in axis_elem.attrib["xyz"].split()]

        limits = None
        limit_elem = j.find("limit")
        if limit_elem is not None and jtype == "revolute":
            lo = float(limit_elem.attrib.get("lower", "-inf"))
            hi = float(limit_elem.attrib.get("upper", "inf"))
            limits = (lo, hi)

        joints_by_name[jname] = {
            "name": jname,
            "type": jtype,
            "origin_xyz": origin_xyz,
            "origin_rpy": origin_rpy,
            "axis": axis,
            "limits": limits,
        }

    chain_joint_names = [
        "torso_t0",
        "right_torso_arm_mount",
        "right_s0",
        "right_s1",
        "right_e0",
        "right_e1",
        "right_w0",
        "right_w1",
        "right_w2",
        "right_hand",
        "right_gripper_base",
        "right_endpoint",
    ]

    chain = []
    for jname in chain_joint_names:
        d = joints_by_name[jname]
        chain.append(URDFJoint(
            name=d["name"],
            joint_type=d["type"],
            origin_xyz=d["origin_xyz"],
            origin_rpy=d["origin_rpy"],
            axis=d["axis"],
            limits=d["limits"],
        ))

    return chain


# ====================================================================
# Forward kinematics
# ====================================================================

def forward_kinematics(chain, joint_angles, full=False):
    T = np.eye(4)
    frames = [T.copy()] if full else None
    ai = 0
    for joint in chain:
        if joint.joint_type == "revolute":
            T = T @ joint.get_transform(joint_angles[ai])
            ai += 1
        else:
            T = T @ joint.get_transform()
        if full:
            frames.append(T.copy())
    return (T, frames) if full else T


# ====================================================================
# Geometric Jacobian  (6 x 7)
# ====================================================================

def geometric_jacobian(chain, joint_angles):
    T_ee, frames = forward_kinematics(chain, joint_angles, full=True)
    p_ee = T_ee[:3, 3]
    J = np.zeros((6, 7))
    ri = 0
    for i, joint in enumerate(chain):
        if joint.joint_type == "revolute":
            T_i = frames[i + 1]
            z_i = T_i[:3, 2]
            o_i = T_i[:3, 3]
            J[:3, ri] = np.cross(z_i, p_ee - o_i)
            J[3:, ri] = z_i
            ri += 1
    return J


# ====================================================================
# Manipulability
# ====================================================================

def manipulability(chain, q):
    J = geometric_jacobian(chain, q)
    return np.sqrt(max(0.0, np.linalg.det(J @ J.T)))


def manipulability_gradient(chain, q, eps=1e-5):
    grad = np.zeros(7)
    for i in range(7):
        qp = q.copy(); qp[i] += eps
        qm = q.copy(); qm[i] -= eps
        grad[i] = (manipulability(chain, qp) - manipulability(chain, qm)) / (2 * eps)
    return grad


# ====================================================================
# Orientation error (angle-axis)
# ====================================================================

def rotation_error(R_target, R_current):
    R_err = R_target @ R_current.T
    cos_a = np.clip((np.trace(R_err) - 1) / 2, -1, 1)
    angle = np.arccos(cos_a)
    if abs(angle) < 1e-10:
        return np.zeros(3)
    axis_un = np.array([
        R_err[2, 1] - R_err[1, 2],
        R_err[0, 2] - R_err[2, 0],
        R_err[1, 0] - R_err[0, 1],
    ])
    n = np.linalg.norm(axis_un)
    if n < 1e-10:
        return np.zeros(3)
    return angle * axis_un / n


# ====================================================================
# IK solver
# ====================================================================

def solve_ik(chain, target_pos, target_orient, damping, max_iter,
             pos_tol, orient_tol, joint_limits):
    q = np.array([(lo + hi) / 2 for lo, hi in joint_limits])
    use_orient = target_orient is not None

    phase1_iters = max_iter if not use_orient else max_iter // 2
    for _ in range(phase1_iters):
        T_ee = forward_kinematics(chain, q)
        pos_err = target_pos - T_ee[:3, 3]
        if np.linalg.norm(pos_err) < pos_tol:
            break

        J = geometric_jacobian(chain, q)[:3, :]
        JJT = J @ J.T + damping ** 2 * np.eye(3)
        J_pinv = J.T @ np.linalg.inv(JJT)
        dq = J_pinv @ pos_err

        null_proj = np.eye(7) - J_pinv @ J
        mg = manipulability_gradient(chain, q)
        dq += 0.02 * null_proj @ mg

        q = q + dq
        for i, (lo, hi) in enumerate(joint_limits):
            q[i] = np.clip(q[i], lo, hi)

    if use_orient:
        for _ in range(max_iter - phase1_iters):
            T_ee = forward_kinematics(chain, q)
            pos_err = target_pos - T_ee[:3, 3]
            o_err = rotation_error(target_orient, T_ee[:3, :3])
            if np.linalg.norm(pos_err) < pos_tol and np.linalg.norm(o_err) < orient_tol:
                break

            err = np.concatenate([pos_err, o_err])
            J = geometric_jacobian(chain, q)
            JJT = J @ J.T + damping ** 2 * np.eye(6)
            J_pinv = J.T @ np.linalg.inv(JJT)
            dq = J_pinv @ err

            null_proj = np.eye(7) - J_pinv @ J
            mg = manipulability_gradient(chain, q)
            dq += 0.02 * null_proj @ mg

            q = q + dq
            for i, (lo, hi) in enumerate(joint_limits):
                q[i] = np.clip(q[i], lo, hi)

    return q


# ====================================================================
# Output: SQLite database
# ====================================================================

def write_sqlite(results, db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE chain_info (
        joint_name TEXT,
        joint_index INTEGER,
        lower_limit REAL,
        upper_limit REAL
    )""")
    for info in results["chain_info"]:
        c.execute(
            "INSERT INTO chain_info VALUES (?, ?, ?, ?)",
            (info["name"], info["index"], info["lower"], info["upper"]),
        )

    c.execute("""CREATE TABLE fk_results (
        config_id INTEGER,
        joint_angles TEXT,
        pose_matrix TEXT
    )""")
    for fk in results["fk_results"]:
        c.execute(
            "INSERT INTO fk_results VALUES (?, ?, ?)",
            (fk["config_id"],
             json.dumps(fk["joint_angles"]),
             json.dumps(fk["pose_matrix"])),
        )

    c.execute("""CREATE TABLE jacobian_results (
        config_id INTEGER,
        joint_angles TEXT,
        jacobian_matrix TEXT,
        manipulability REAL,
        condition_number REAL
    )""")
    for jr in results["jacobian_results"]:
        c.execute(
            "INSERT INTO jacobian_results VALUES (?, ?, ?, ?, ?)",
            (jr["config_id"],
             json.dumps(jr["joint_angles"]),
             json.dumps(jr["jacobian_matrix"]),
             jr["manipulability"],
             jr["condition_number"]),
        )

    c.execute("""CREATE TABLE ik_solutions (
        target_id INTEGER,
        target_position TEXT,
        target_orientation TEXT,
        solution_angles TEXT,
        achieved_position TEXT,
        position_error REAL,
        orientation_error REAL
    )""")
    for ik in results["ik_solutions"]:
        c.execute(
            "INSERT INTO ik_solutions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ik["target_id"],
             json.dumps(ik["target_position"]),
             json.dumps(ik["target_orientation"]) if ik["target_orientation"] is not None else None,
             json.dumps(ik["solution_angles"]),
             json.dumps(ik["achieved_position"]),
             ik["position_error"],
             ik["orientation_error"]),
        )

    conn.commit()
    conn.close()


# ====================================================================
# Output: XML report
# ====================================================================

def write_xml(results, xml_path):
    root = ET.Element("kinematic_report")
    root.set("robot", "baxter")
    root.set("chain", "right_arm")
    root.set("dof", "7")

    chain_el = ET.SubElement(root, "chain")
    for info in results["chain_info"]:
        j = ET.SubElement(chain_el, "joint")
        j.set("name", info["name"])
        j.set("index", str(info["index"]))
        j.set("lower", f"{info['lower']:.6f}")
        j.set("upper", f"{info['upper']:.6f}")

    fk_el = ET.SubElement(root, "fk_results")
    for fk in results["fk_results"]:
        cfg = ET.SubElement(fk_el, "config")
        cfg.set("id", str(fk["config_id"]))
        pose = fk["pose_matrix"]
        pos = ET.SubElement(cfg, "position")
        pos.set("x", f"{pose[0][3]:.6f}")
        pos.set("y", f"{pose[1][3]:.6f}")
        pos.set("z", f"{pose[2][3]:.6f}")
        orient = ET.SubElement(cfg, "orientation")
        for r in range(3):
            for c in range(3):
                orient.set(f"r{r}{c}", f"{pose[r][c]:.6f}")

    ik_el = ET.SubElement(root, "ik_solutions")
    for ik in results["ik_solutions"]:
        tgt = ET.SubElement(ik_el, "target")
        tgt.set("id", str(ik["target_id"]))
        tgt.set("px", f"{ik['target_position'][0]:.6f}")
        tgt.set("py", f"{ik['target_position'][1]:.6f}")
        tgt.set("pz", f"{ik['target_position'][2]:.6f}")
        tgt.set("error", f"{ik['position_error']:.6f}")

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(xml_path, xml_declaration=True, encoding="UTF-8")


# ====================================================================
# Main
# ====================================================================

def main():
    with open("/app/task_config.toml", "rb") as f:
        cfg = tomllib.load(f)

    chain = parse_urdf_right_arm("/app/baxter.urdf")

    rev = [j for j in chain if j.joint_type == "revolute"]
    joint_names = [j.name for j in rev]
    joint_limits = [list(j.limits) for j in rev]
    limits_t = [(lo, hi) for lo, hi in joint_limits]

    results = {
        "chain_info": [],
        "fk_results": [],
        "jacobian_results": [],
        "ik_solutions": [],
    }

    for i, (name, lim) in enumerate(zip(joint_names, joint_limits)):
        results["chain_info"].append({
            "name": name, "index": i,
            "lower": lim[0], "upper": lim[1],
        })

    # --- FK ---
    for cid, fc in enumerate(cfg["fk_configs"]):
        q = np.array(fc["joint_angles"])
        T = forward_kinematics(chain, q)
        results["fk_results"].append({
            "config_id": cid,
            "joint_angles": fc["joint_angles"],
            "pose_matrix": T.tolist(),
        })

    # --- Jacobian ---
    for cid, jc in enumerate(cfg["jacobian_configs"]):
        q = np.array(jc["joint_angles"])
        J = geometric_jacobian(chain, q)
        m = manipulability(chain, q)
        cn = float(np.linalg.cond(J)) if m > 1e-10 else float("inf")
        results["jacobian_results"].append({
            "config_id": cid,
            "joint_angles": jc["joint_angles"],
            "jacobian_matrix": J.tolist(),
            "manipulability": float(m),
            "condition_number": cn,
        })

    # --- IK ---
    solver_cfg = cfg["solver"]
    for tid, tgt in enumerate(cfg["ik_targets"]):
        tp = np.array(tgt["position"])
        to_r = np.array(tgt["orientation"]) if "orientation" in tgt else None

        q = solve_ik(
            chain, tp, to_r,
            damping=solver_cfg["damping_factor"],
            max_iter=solver_cfg["max_iterations"],
            pos_tol=solver_cfg["position_tolerance"],
            orient_tol=solver_cfg["orientation_tolerance"],
            joint_limits=limits_t,
        )

        T_a = forward_kinematics(chain, q)
        pa = T_a[:3, 3]
        pe = float(np.linalg.norm(pa - tp))
        oe = None
        if to_r is not None:
            oe = float(np.linalg.norm(rotation_error(to_r, T_a[:3, :3])))

        results["ik_solutions"].append({
            "target_id": tid,
            "target_position": tgt["position"],
            "target_orientation": tgt.get("orientation"),
            "solution_angles": q.tolist(),
            "achieved_position": pa.tolist(),
            "position_error": pe,
            "orientation_error": oe,
        })

    # Write outputs
    write_sqlite(results, "/app/results.db")
    write_xml(results, "/app/results.xml")
    print("Results written to /app/results.db and /app/results.xml")


if __name__ == "__main__":
    main()
