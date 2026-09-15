#!/usr/bin/env python3
"""
Kinematic calibration solver for a 6-DOF robot arm.

Identifies per-joint origin translation corrections by minimizing the
sum of squared residuals between nominal FK predictions and measured
end-effector positions using bounded Levenberg-Marquardt optimization.
"""

import json
import xml.etree.ElementTree as ET

import numpy as np
from scipy.optimize import least_squares


def parse_urdf(urdf_path):
    """Parse URDF and return ordered list of joint parameters."""
    tree = ET.parse(urdf_path)
    root = tree.getroot()

    joints_by_parent = {}
    for joint_elem in root.findall("joint"):
        parent = joint_elem.find("parent").get("link")
        joints_by_parent.setdefault(parent, []).append(joint_elem)

    joints = []
    current_link = "base_link"
    while current_link in joints_by_parent:
        jlist = joints_by_parent[current_link]
        if not jlist:
            break
        joint_elem = jlist[0]
        origin = joint_elem.find("origin")
        xyz = [float(v) for v in origin.get("xyz", "0 0 0").split()]
        rpy = [float(v) for v in origin.get("rpy", "0 0 0").split()]
        axis_elem = joint_elem.find("axis")
        axis = [float(v) for v in axis_elem.get("xyz", "0 0 1").split()]
        joints.append({
            "name": joint_elem.get("name"),
            "origin_xyz": xyz,
            "origin_rpy": rpy,
            "axis": axis,
        })
        current_link = joint_elem.find("child").get("link")
    return joints


def rot_x(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_y(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rot_z(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def rpy_to_rotation(roll, pitch, yaw):
    return rot_z(yaw) @ rot_y(pitch) @ rot_x(roll)


def axis_angle_rotation(axis, angle):
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
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def make_transform(R, t):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def forward_kinematics(joint_angles, joints, corrections=None, tool_tip=None):
    """Compute FK with optional origin_xyz corrections."""
    T = np.eye(4)
    for i, (angle, joint) in enumerate(zip(joint_angles, joints)):
        ox = np.array(joint["origin_xyz"], dtype=float)
        if corrections is not None and joint["name"] in corrections:
            ox = ox + corrections[joint["name"]]
        rpy = joint["origin_rpy"]
        R_origin = rpy_to_rotation(rpy[0], rpy[1], rpy[2])
        T_origin = make_transform(R_origin, ox)
        R_joint = axis_angle_rotation(joint["axis"], angle)
        T_joint = make_transform(R_joint, np.zeros(3))
        T = T @ T_origin @ T_joint

    if tool_tip is not None:
        T_tool = make_transform(np.eye(3), np.array(tool_tip))
        T = T @ T_tool
    return T


def residuals(param_vector, joints, measurements, tool_tip):
    """Compute residual vector (3*N) for all measurements."""
    corrections = {}
    for i, joint in enumerate(joints):
        corrections[joint["name"]] = param_vector[3 * i: 3 * i + 3]

    res = np.zeros(3 * len(measurements))
    for k, m in enumerate(measurements):
        q = np.array(m["joint_angles"])
        p_meas = np.array(m["measured_position"])
        T = forward_kinematics(q, joints, corrections, tool_tip)
        res[3 * k: 3 * k + 3] = T[:3, 3] - p_meas
    return res


def compute_rms_position_error(param_vector, joints, measurements, tool_tip):
    """RMS of position error norms (standard robotics metric)."""
    corrections = {}
    for i, joint in enumerate(joints):
        corrections[joint["name"]] = param_vector[3 * i: 3 * i + 3]

    errors_sq = []
    for m in measurements:
        q = np.array(m["joint_angles"])
        p_meas = np.array(m["measured_position"])
        T = forward_kinematics(q, joints, corrections, tool_tip)
        diff = T[:3, 3] - p_meas
        errors_sq.append(np.dot(diff, diff))
    return np.sqrt(np.mean(errors_sq))


def main():
    joints = parse_urdf("/app/robot.urdf")
    with open("/app/measurements.json") as f:
        data = json.load(f)
    measurements = data["measurements"]
    tool_tip = data["tool_tip_offset"]

    with open("/app/validation_configs.json") as f:
        val_data = json.load(f)
    validation = val_data["validation_configs"]

    n_params = 3 * len(joints)
    p0 = np.zeros(n_params)

    # Compute nominal RMS error
    nominal_rms = compute_rms_position_error(p0, joints, measurements, tool_tip)
    print(f"Nominal RMS error: {nominal_rms * 1000:.2f} mm")

    # Bounded optimization to prevent parameter blow-up from identifiability issues
    # Perturbations are known to be on the order of 1-5mm, so ±10mm is generous
    bounds_lo = np.full(n_params, -0.010)
    bounds_hi = np.full(n_params, 0.010)

    result = least_squares(
        residuals, p0,
        args=(joints, measurements, tool_tip),
        bounds=(bounds_lo, bounds_hi),
        method="trf",
        max_nfev=2000,
    )
    p_opt = result.x
    calibrated_rms = compute_rms_position_error(p_opt, joints, measurements, tool_tip)
    print(f"Calibrated RMS error: {calibrated_rms * 1000:.2f} mm")
    print(f"Improvement: {nominal_rms / calibrated_rms:.1f}x")

    # Extract corrections
    corrections_dict = {}
    corrections_for_fk = {}
    for i, joint in enumerate(joints):
        dx, dy, dz = p_opt[3*i], p_opt[3*i+1], p_opt[3*i+2]
        corrections_dict[joint["name"]] = {
            "dx": float(dx), "dy": float(dy), "dz": float(dz)
        }
        corrections_for_fk[joint["name"]] = np.array([dx, dy, dz])
        print(f"  {joint['name']}: dx={dx*1000:.2f} dy={dy*1000:.2f} dz={dz*1000:.2f} mm")

    # Validation predictions
    val_predictions = []
    for vc in validation:
        q = np.array(vc["joint_angles"])
        T = forward_kinematics(q, joints, corrections_for_fk, tool_tip)
        val_predictions.append([float(v) for v in T[:3, 3]])

    output = {
        "nominal_rms_error_m": float(nominal_rms),
        "calibrated_rms_error_m": float(calibrated_rms),
        "parameter_corrections": corrections_dict,
        "validation_predictions": val_predictions,
    }
    with open("/app/calibration_result.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults written to /app/calibration_result.json")


if __name__ == "__main__":
    main()
