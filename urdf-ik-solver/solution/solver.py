#!/usr/bin/env python3
"""
Reference solver for the 6-DOF robot arm kinematic calibration and analysis task.
Parses URDF, calibrates kinematic parameters from measurement data, then performs
FK/IK/Jacobian/workspace analysis using the calibrated model.
"""

import xml.etree.ElementTree as ET
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull
import json
import copy
import sys
import os

np.random.seed(42)


# ================================================================
# Rotation / transformation helpers
# ================================================================

def rx(theta):
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def ry(theta):
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rz(theta):
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def rpy_matrix(roll, pitch, yaw):
    """URDF RPY convention: Rz(yaw) * Ry(pitch) * Rx(roll)."""
    return rz(yaw) @ ry(pitch) @ rx(roll)


def axis_rotation_matrix(axis, theta):
    """Rodrigues rotation about an arbitrary unit axis."""
    ax = np.array(axis, dtype=float)
    n = np.linalg.norm(ax)
    if n < 1e-10:
        return np.eye(3)
    ax = ax / n
    c = np.cos(theta)
    s = np.sin(theta)
    t = 1.0 - c
    x, y, z = ax
    return np.array([
        [t * x * x + c,     t * x * y - z * s, t * x * z + y * s],
        [t * x * y + z * s, t * y * y + c,     t * y * z - x * s],
        [t * x * z - y * s, t * y * z + x * s, t * z * z + c],
    ])


# ================================================================
# URDF parsing
# ================================================================

def parse_urdf(filepath):
    """Parse URDF and return the kinematic chain as a list of joint dicts."""
    tree = ET.parse(filepath)
    root = tree.getroot()

    link_to_joints = {}
    for joint_elem in root.findall("joint"):
        parent_link = joint_elem.find("parent").attrib["link"]
        child_link = joint_elem.find("child").attrib["link"]
        jtype = joint_elem.attrib["type"]
        jname = joint_elem.attrib["name"]

        origin = joint_elem.find("origin")
        xyz = [0.0, 0.0, 0.0]
        rpy_vals = [0.0, 0.0, 0.0]
        if origin is not None:
            if "xyz" in origin.attrib:
                xyz = [float(v) for v in origin.attrib["xyz"].split()]
            if "rpy" in origin.attrib:
                rpy_vals = [float(v) for v in origin.attrib["rpy"].split()]

        axis_elem = joint_elem.find("axis")
        axis = [0, 0, 1]
        if axis_elem is not None:
            axis = [float(v) for v in axis_elem.attrib["xyz"].split()]

        limit_elem = joint_elem.find("limit")
        lower, upper = -3.14159, 3.14159
        if limit_elem is not None:
            lower = float(limit_elem.attrib.get("lower", str(lower)))
            upper = float(limit_elem.attrib.get("upper", str(upper)))

        j = {
            "name": jname, "type": jtype,
            "parent": parent_link, "child": child_link,
            "xyz": xyz, "rpy": rpy_vals, "axis": axis,
            "lower": lower, "upper": upper,
        }
        link_to_joints.setdefault(parent_link, []).append(j)

    # Traverse linear chain from base_link
    chain = []
    current = "base_link"
    visited = set()
    while current in link_to_joints and current not in visited:
        visited.add(current)
        j = link_to_joints[current][0]
        chain.append(j)
        current = j["child"]

    return chain


# ================================================================
# Forward kinematics
# ================================================================

def forward_kinematics(chain, joint_angles):
    """Compute 4x4 end-effector transform from joint angles."""
    T = np.eye(4)
    q_idx = 0
    for j in chain:
        R_origin = rpy_matrix(*j["rpy"])
        T_origin = np.eye(4)
        T_origin[:3, :3] = R_origin
        T_origin[:3, 3] = j["xyz"]
        T = T @ T_origin

        if j["type"] == "revolute":
            R_joint = axis_rotation_matrix(j["axis"], joint_angles[q_idx])
            T_joint = np.eye(4)
            T_joint[:3, :3] = R_joint
            T = T @ T_joint
            q_idx += 1
    return T


# ================================================================
# Kinematic calibration
# ================================================================

def calibrate_model(chain, calibration_data, bounds_xyz=0.015, bounds_rpy=0.02):
    """Identify kinematic parameter corrections from calibration measurements."""
    n_joints = len(chain)
    n_params = n_joints * 6

    def apply_corrections(params):
        chain_c = copy.deepcopy(chain)
        for i in range(n_joints):
            for k in range(3):
                chain_c[i]["xyz"][k] += params[i * 6 + k]
                chain_c[i]["rpy"][k] += params[i * 6 + 3 + k]
        return chain_c

    def residuals(params):
        chain_c = apply_corrections(params)
        res = []
        for meas in calibration_data:
            q = meas["joint_angles"]
            measured = np.array(meas["measured_position"])
            T = forward_kinematics(chain_c, q)
            predicted = T[:3, 3]
            res.extend((predicted - measured).tolist())
        return np.array(res)

    lo = np.zeros(n_params)
    hi = np.zeros(n_params)
    for i in range(n_joints):
        for k in range(3):
            lo[i * 6 + k] = -bounds_xyz
            hi[i * 6 + k] = bounds_xyz
            lo[i * 6 + 3 + k] = -bounds_rpy
            hi[i * 6 + 3 + k] = bounds_rpy

    x0 = np.zeros(n_params)
    result = least_squares(residuals, x0, bounds=(lo, hi),
                           method="trf", max_nfev=10000,
                           ftol=1e-12, xtol=1e-12, gtol=1e-12)

    calibrated_chain = apply_corrections(result.x)
    return calibrated_chain, result


# ================================================================
# Jacobian
# ================================================================

def compute_jacobian(chain, joint_angles, delta=1e-7):
    """Numerical 6xN geometric Jacobian via finite differences."""
    T0 = forward_kinematics(chain, joint_angles)
    p0 = T0[:3, 3].copy()
    R0 = T0[:3, :3].copy()
    n = len(joint_angles)
    J = np.zeros((6, n))

    for i in range(n):
        q_plus = np.array(joint_angles, dtype=float)
        q_plus[i] += delta
        T_plus = forward_kinematics(chain, q_plus)

        J[:3, i] = (T_plus[:3, 3] - p0) / delta

        dR = T_plus[:3, :3] @ R0.T
        J[3, i] = (dR[2, 1] - dR[1, 2]) / (2.0 * delta)
        J[4, i] = (dR[0, 2] - dR[2, 0]) / (2.0 * delta)
        J[5, i] = (dR[1, 0] - dR[0, 1]) / (2.0 * delta)

    return J


def manipulability_index(J):
    """Yoshikawa manipulability: sqrt(det(J J^T))."""
    JJT = J @ J.T
    return float(np.sqrt(max(0.0, np.linalg.det(JJT))))


# ================================================================
# Inverse kinematics
# ================================================================

def inverse_kinematics(chain, target_pos, joint_limits,
                       initial_guess=None, target_orientation_z=None,
                       n_restarts=40):
    """Solve IK via bounded least-squares with random restarts."""
    n_joints = len(joint_limits)
    lo = np.array([lim[0] for lim in joint_limits])
    hi = np.array([lim[1] for lim in joint_limits])

    target_pos_arr = np.array(target_pos, dtype=float)

    def pos_residual(q):
        T = forward_kinematics(chain, q)
        return T[:3, 3] - target_pos_arr

    def full_residual(q):
        T = forward_kinematics(chain, q)
        pos_err = T[:3, 3] - target_pos_arr
        if target_orientation_z is not None:
            z_ax = T[:3, 2]
            ori_err = z_ax - np.array(target_orientation_z)
            return np.concatenate([pos_err, ori_err])
        return pos_err

    best_q = None
    best_cost = float("inf")

    seeds = []
    if target_orientation_z is not None:
        for _ in range(25):
            q0 = np.array([np.random.uniform(l, h) for l, h in zip(lo, hi)])
            try:
                r = least_squares(pos_residual, q0, bounds=(lo, hi),
                                  method="trf", max_nfev=500)
                if np.linalg.norm(pos_residual(r.x)) < 0.01:
                    seeds.append(r.x.copy())
            except Exception:
                pass

    starts = []
    if initial_guess is not None:
        starts.append(np.array(initial_guess, dtype=float))
    starts.extend(seeds)

    for restart in range(n_restarts):
        if restart < len(starts):
            q0 = starts[restart]
        else:
            q0 = np.array([np.random.uniform(l, h) for l, h in zip(lo, hi)])

        try:
            result = least_squares(
                full_residual, q0, bounds=(lo, hi),
                method="trf", max_nfev=2000,
            )
            cost = float(np.sum(full_residual(result.x) ** 2))
            if cost < best_cost:
                best_cost = cost
                best_q = result.x.copy()
                if best_cost < 1e-10:
                    break
        except Exception:
            continue

    return best_q


# ================================================================
# Workspace volume estimation
# ================================================================

def estimate_workspace_volume(chain, joint_limits, n_samples=50000):
    """Workspace volume via random FK sampling and convex hull."""
    positions = np.zeros((n_samples, 3))

    for i in range(n_samples):
        q = [np.random.uniform(lim[0], lim[1]) for lim in joint_limits]
        T = forward_kinematics(chain, q)
        positions[i] = T[:3, 3]

    try:
        hull = ConvexHull(positions)
        return float(hull.volume)
    except Exception:
        return 0.0


# ================================================================
# Main
# ================================================================

def main():
    urdf_path = "/app/robot.urdf"
    config_path = "/app/task_config.json"

    # Verify files exist
    for p in [urdf_path, config_path]:
        if not os.path.exists(p):
            print(f"ERROR: {p} not found", file=sys.stderr)
            sys.exit(1)

    chain = parse_urdf(urdf_path)

    with open(config_path, encoding="utf-8") as f:
        raw = f.read()
    print(f"Config file size: {len(raw)} bytes")
    config = json.loads(raw)
    print(f"Config keys: {list(config.keys())}")

    # Verify expected keys
    required_keys = ["fk_tests", "calibration_measurements",
                     "validation_measurements", "ik_targets",
                     "ik_with_orientation", "jacobian_config"]
    missing = [k for k in required_keys if k not in config]
    if missing:
        print(f"ERROR: missing keys {missing}. Present keys: {list(config.keys())}",
              file=sys.stderr)
        sys.exit(1)

    revolute = [j for j in chain if j["type"] == "revolute"]
    joint_limits = [(j["lower"], j["upper"]) for j in revolute]

    results = {}

    # ---- Nominal FK ----
    print("Computing nominal FK...")
    nominal_fk = {}
    for test in config["fk_tests"]:
        q = test["joint_angles"]
        T = forward_kinematics(chain, q)
        nominal_fk[test["name"]] = {
            "position": T[:3, 3].tolist(),
            "orientation": T[:3, :3].tolist(),
        }
    results["nominal_fk"] = nominal_fk

    # ---- Kinematic calibration ----
    print("Running kinematic calibration...")
    cal_data = config["calibration_measurements"]
    calibrated_chain, cal_result = calibrate_model(chain, cal_data)

    # Compute nominal validation RMSE
    val_data = config["validation_measurements"]
    val_errors_nom = []
    for meas in val_data:
        T = forward_kinematics(chain, meas["joint_angles"])
        err = np.linalg.norm(T[:3, 3] - np.array(meas["measured_position"]))
        val_errors_nom.append(err)
    nominal_val_rmse = float(np.sqrt(np.mean(np.array(val_errors_nom) ** 2)))

    # Compute calibrated validation RMSE and per-entry results
    val_errors_cal = []
    calibrated_fk = []
    for meas in val_data:
        q = meas["joint_angles"]
        T = forward_kinematics(calibrated_chain, q)
        predicted = T[:3, 3]
        measured = np.array(meas["measured_position"])
        err = float(np.linalg.norm(predicted - measured))
        val_errors_cal.append(err)
        calibrated_fk.append({
            "joint_angles": q,
            "predicted_position": predicted.tolist(),
            "measured_position": meas["measured_position"],
            "position_error": err,
        })
    cal_val_rmse = float(np.sqrt(np.mean(np.array(val_errors_cal) ** 2)))

    # Compute calibration RMSE
    cal_errors = []
    for meas in cal_data:
        T = forward_kinematics(calibrated_chain, meas["joint_angles"])
        err = np.linalg.norm(T[:3, 3] - np.array(meas["measured_position"]))
        cal_errors.append(err)
    cal_rmse = float(np.sqrt(np.mean(np.array(cal_errors) ** 2)))

    results["calibration_stats"] = {
        "calibration_rmse": cal_rmse,
        "validation_rmse": cal_val_rmse,
        "nominal_validation_rmse": nominal_val_rmse,
    }
    results["calibrated_fk"] = calibrated_fk

    print(f"  Nominal validation RMSE: {nominal_val_rmse:.6f} m")
    print(f"  Calibrated validation RMSE: {cal_val_rmse:.6f} m")
    print(f"  Improvement: {(1 - cal_val_rmse / nominal_val_rmse) * 100:.1f}%")

    # ---- IK using calibrated model ----
    print("Solving IK targets...")
    cal_revolute = [j for j in calibrated_chain if j["type"] == "revolute"]
    cal_joint_limits = [(j["lower"], j["upper"]) for j in cal_revolute]

    ik_solutions = []
    for tgt in config["ik_targets"]:
        tpos = np.array(tgt["position"])
        q_sol = inverse_kinematics(calibrated_chain, tpos, cal_joint_limits)
        T_ach = forward_kinematics(calibrated_chain, q_sol)
        pos_err = float(np.linalg.norm(T_ach[:3, 3] - tpos))
        ik_solutions.append({
            "name": tgt["name"],
            "target_position": tgt["position"],
            "joint_angles": q_sol.tolist(),
            "achieved_position": T_ach[:3, 3].tolist(),
            "position_error": pos_err,
        })
        print(f"  {tgt['name']}: error = {pos_err:.6f} m")
    results["ik_solutions"] = ik_solutions

    # ---- Oriented IK ----
    print("Solving oriented IK...")
    ot = config["ik_with_orientation"]
    tpos = np.array(ot["position"])
    q_sol = inverse_kinematics(
        calibrated_chain, tpos, cal_joint_limits,
        target_orientation_z=ot["orientation_z"],
    )
    T_ach = forward_kinematics(calibrated_chain, q_sol)
    pos_err = float(np.linalg.norm(T_ach[:3, 3] - tpos))
    z_axis = T_ach[:3, 2]
    ori_err = float(np.linalg.norm(z_axis - np.array(ot["orientation_z"])))
    results["ik_with_orientation"] = {
        "name": ot["name"],
        "target_position": ot["position"],
        "target_orientation_z": ot["orientation_z"],
        "joint_angles": q_sol.tolist(),
        "achieved_position": T_ach[:3, 3].tolist(),
        "achieved_z_axis": z_axis.tolist(),
        "position_error": pos_err,
        "orientation_error": ori_err,
    }
    print(f"  Oriented IK: pos_err={pos_err:.6f}, ori_err={ori_err:.6f}")

    # ---- Jacobian analysis ----
    print("Computing Jacobian...")
    q_jac = config["jacobian_config"]
    J = compute_jacobian(calibrated_chain, q_jac)
    sv = np.linalg.svd(J, compute_uv=False)
    results["jacobian"] = {
        "config": q_jac,
        "jacobian": J.tolist(),
        "rank": int(np.linalg.matrix_rank(J)),
        "manipulability": manipulability_index(J),
        "singular_values": sv.tolist(),
    }

    # ---- Workspace volume ----
    print("Estimating workspace volume...")
    n_ws = config.get("workspace_samples", 50000)
    vol = estimate_workspace_volume(calibrated_chain, cal_joint_limits,
                                    n_samples=n_ws)
    results["workspace_volume"] = vol
    print(f"  Workspace volume: {vol:.4f} m^3")

    with open("/app/results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
