#!/usr/bin/env python3
"""
Solution for the manipulator kinematic-dynamic analysis from URDF task.

Parses the URDF kinematic chain (including inertial parameters), computes
FK / IK / manipulability / gravity torques / max payload / trajectories,
and writes both JSON and SQLite outputs.

"""

import json
import sqlite3
import sys
import numpy as np
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# URDF Parsing
# ---------------------------------------------------------------------------

def rpy_to_matrix(roll, pitch, yaw):
    """R = Rz(yaw) . Ry(pitch) . Rx(roll)."""
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp,     cp * sr,                cp * cr               ],
    ])


def origin_to_transform(xyz, rpy):
    """Convert URDF origin (xyz, rpy) to 4x4 homogeneous transform."""
    T = np.eye(4)
    T[:3, :3] = rpy_to_matrix(rpy[0], rpy[1], rpy[2])
    T[:3, 3] = xyz
    return T


def axis_rotation_4x4(axis, angle):
    """4x4 rotation about an arbitrary axis (Rodrigues formula)."""
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


def parse_urdf_chain(urdf_path, base_name="base_link", ee_name="tool0"):
    """Parse URDF XML and return ordered kinematic chain with inertial data."""
    tree = ET.parse(urdf_path)
    root = tree.getroot()

    # Parse all link inertial parameters
    link_inertials = {}
    for link_elem in root.findall("link"):
        name = link_elem.get("name")
        inertial = link_elem.find("inertial")
        if inertial is not None:
            mass_elem = inertial.find("mass")
            mass = float(mass_elem.get("value", "0"))
            origin_elem = inertial.find("origin")
            com = [0.0, 0.0, 0.0]
            if origin_elem is not None:
                com = [float(v) for v in origin_elem.get("xyz", "0 0 0").split()]
            link_inertials[name] = {"mass": mass, "com": com}

    # Map each child link to its joint element
    child_to_joint = {}
    for je in root.findall("joint"):
        child_link = je.find("child").get("link")
        child_to_joint[child_link] = je

    # Walk backwards from end-effector to base
    chain = []
    current = ee_name
    while current != base_name:
        if current not in child_to_joint:
            raise ValueError(f"Cannot trace chain: no joint has child '{current}'")
        je = child_to_joint[current]

        jtype = je.get("type")
        origin_elem = je.find("origin")
        if origin_elem is not None:
            xyz = [float(v) for v in origin_elem.get("xyz", "0 0 0").split()]
            rpy_vals = [float(v) for v in origin_elem.get("rpy", "0 0 0").split()]
        else:
            xyz = [0.0, 0.0, 0.0]
            rpy_vals = [0.0, 0.0, 0.0]

        axis_elem = je.find("axis")
        if axis_elem is not None:
            axis = [float(v) for v in axis_elem.get("xyz", "0 0 1").split()]
        else:
            axis = [0.0, 0.0, 1.0]

        lower = upper = None
        effort = None
        limit_elem = je.find("limit")
        if limit_elem is not None:
            if jtype == "revolute":
                lower = float(limit_elem.get("lower", "-3.14159"))
                upper = float(limit_elem.get("upper", "3.14159"))
            effort = float(limit_elem.get("effort", "0"))

        # Get child link's inertial data
        child_name = je.find("child").get("link")
        child_inertial = link_inertials.get(child_name, {"mass": 0.0, "com": [0, 0, 0]})

        chain.append({
            "name": je.get("name"),
            "type": jtype,
            "xyz": xyz,
            "rpy": rpy_vals,
            "axis": axis,
            "lower": lower,
            "upper": upper,
            "effort": effort,
            "child_mass": child_inertial["mass"],
            "child_com": child_inertial["com"],
        })

        current = je.find("parent").get("link")

    chain.reverse()
    return chain


# ---------------------------------------------------------------------------
# Forward Kinematics
# ---------------------------------------------------------------------------

def forward_kinematics(chain, q):
    """Compute the 4x4 end-effector transform from the URDF chain."""
    T = np.eye(4)
    qi = 0
    for joint in chain:
        T_origin = origin_to_transform(joint["xyz"], joint["rpy"])
        T = T @ T_origin
        if joint["type"] == "revolute":
            T = T @ axis_rotation_4x4(joint["axis"], q[qi])
            qi += 1
    return T


# ---------------------------------------------------------------------------
# Link center-of-mass positions in world frame
# ---------------------------------------------------------------------------

def link_com_positions(chain, q):
    """Compute world-frame CoM position and mass for each link."""
    positions = []
    T = np.eye(4)
    qi = 0
    for joint in chain:
        T_origin = origin_to_transform(joint["xyz"], joint["rpy"])
        T = T @ T_origin
        if joint["type"] == "revolute":
            T = T @ axis_rotation_4x4(joint["axis"], q[qi])
            qi += 1
        com = joint["child_com"]
        p_com = T @ np.array([com[0], com[1], com[2], 1.0])
        positions.append((joint["child_mass"], p_com[:3].copy()))
    return positions


# ---------------------------------------------------------------------------
# Gravitational potential energy and gravity torques
# ---------------------------------------------------------------------------

def potential_energy(chain, q, gravity):
    """V(q) = -sum(m_k * g . p_com_k)."""
    g = np.array(gravity)
    V = 0.0
    for mass, p_com in link_com_positions(chain, q):
        V -= mass * np.dot(g, p_com)
    return V


def compute_gravity_torques(chain, q, gravity, eps=1e-7):
    """Gravity torque vector g(q) = dV/dq via central differences."""
    n = sum(1 for j in chain if j["type"] == "revolute")
    tau = np.zeros(n)
    for i in range(n):
        qp = q.copy(); qp[i] += eps
        qm = q.copy(); qm[i] -= eps
        tau[i] = (potential_energy(chain, qp, gravity) -
                  potential_energy(chain, qm, gravity)) / (2.0 * eps)
    return tau


# ---------------------------------------------------------------------------
# Jacobian (numerical central differences)
# ---------------------------------------------------------------------------

def compute_jacobian(chain, q, eps=1e-8):
    """6xn Jacobian: [linear_vel; angular_vel] via central differences."""
    n = len(q)
    J = np.zeros((6, n))
    T0 = forward_kinematics(chain, q)
    R0 = T0[:3, :3].copy()

    for i in range(n):
        qp = q.copy(); qp[i] += eps
        qm = q.copy(); qm[i] -= eps
        Tp = forward_kinematics(chain, qp)
        Tm = forward_kinematics(chain, qm)

        J[:3, i] = (Tp[:3, 3] - Tm[:3, 3]) / (2.0 * eps)

        dR = (Tp[:3, :3] - Tm[:3, :3]) / (2.0 * eps)
        S = dR @ R0.T
        J[3:, i] = [S[2, 1], S[0, 2], S[1, 0]]

    return J


# ---------------------------------------------------------------------------
# Maximum static payload
# ---------------------------------------------------------------------------

def compute_max_payload(gravity_torques_vec, J, effort_limits, gravity):
    """
    Maximum payload mass at tool0 under gravity while respecting effort limits.

    Static equilibrium: tau_i = g_i(q) + m_p * |g| * J_{z,i}
    Constraint: |tau_i| <= effort_i for all i
    """
    g_mag = np.linalg.norm(gravity)
    upper_bounds = []
    lower_bounds = [0.0]

    for i in range(len(effort_limits)):
        c = g_mag * J[2, i]  # z-component of linear Jacobian, column i
        g_i = gravity_torques_vec[i]
        e_i = effort_limits[i]

        if abs(c) < 1e-12:
            if abs(g_i) > e_i + 1e-6:
                return 0.0
            continue

        # |g_i + c * m_p| <= e_i
        # => -e_i <= g_i + c * m_p <= e_i
        # => -e_i - g_i <= c * m_p <= e_i - g_i
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
# Pose error
# ---------------------------------------------------------------------------

def rotation_to_angle_axis(R):
    """Angle-axis vector from rotation matrix."""
    trace = np.clip(np.trace(R), -1.0, 3.0)
    angle = np.arccos(np.clip((trace - 1.0) / 2.0, -1.0, 1.0))
    if abs(angle) < 1e-10:
        return np.zeros(3)
    if abs(angle - np.pi) < 1e-6:
        M = R + np.eye(3)
        k = int(np.argmax([np.linalg.norm(M[:, j]) for j in range(3)]))
        axis = M[:, k] / np.linalg.norm(M[:, k])
        return angle * axis
    axis = np.array([
        R[2, 1] - R[1, 2],
        R[0, 2] - R[2, 0],
        R[1, 0] - R[0, 1],
    ]) / (2.0 * np.sin(angle))
    return angle * axis


def pose_error(T_current, T_target):
    """6-vector error: [position_err; orientation_angle_axis_err]."""
    ep = T_target[:3, 3] - T_current[:3, 3]
    Re = T_target[:3, :3] @ T_current[:3, :3].T
    eo = rotation_to_angle_axis(Re)
    return np.concatenate([ep, eo])


# ---------------------------------------------------------------------------
# Inverse Kinematics (damped least-squares with random restarts)
# ---------------------------------------------------------------------------

def _wrap_joints(q, lower, upper):
    qw = q.copy()
    for i in range(len(q)):
        qw[i] = (qw[i] + np.pi) % (2 * np.pi) - np.pi
        if qw[i] < lower[i]:
            qw[i] += 2 * np.pi
        elif qw[i] > upper[i]:
            qw[i] -= 2 * np.pi
    return qw


def _within_limits(q, lower, upper):
    return np.all(q >= lower) and np.all(q <= upper)


def solve_ik(chain, target, q0, jl_lower, jl_upper,
             tol=1e-6, max_iter=100, max_restarts=50):
    """Iterative IK solver with damped least-squares and random restarts."""
    n = len(q0)
    rng = np.random.default_rng(42)
    best_q = q0.copy()
    best_err = float("inf")
    lam = 1.0

    for restart in range(max_restarts):
        q = q0.copy() if restart == 0 else rng.uniform(jl_lower, jl_upper)

        for _ in range(max_iter):
            Te = forward_kinematics(chain, q)
            e = pose_error(Te, target)
            E = 0.5 * float(e @ e)

            if E < tol:
                qw = _wrap_joints(q, jl_lower, jl_upper)
                if _within_limits(qw, jl_lower, jl_upper):
                    return qw, True, E
                if E < best_err:
                    best_err = E
                    best_q = qw.copy()
                break

            J = compute_jacobian(chain, q)
            Wn = lam * E * np.eye(n)
            A = J.T @ J + Wn
            g = J.T @ e
            try:
                dq = np.linalg.solve(A, g)
            except np.linalg.LinAlgError:
                break
            q = q + dq

        Te = forward_kinematics(chain, q)
        e = pose_error(Te, target)
        E = 0.5 * float(e @ e)
        qw = _wrap_joints(q, jl_lower, jl_upper)
        if E < best_err and _within_limits(qw, jl_lower, jl_upper):
            best_err = E
            best_q = qw.copy()

    if best_err < 1e-3 and _within_limits(best_q, jl_lower, jl_upper):
        return best_q, True, best_err
    return best_q, False, best_err


# ---------------------------------------------------------------------------
# Manipulability & condition number
# ---------------------------------------------------------------------------

def manipulability(chain, q):
    """w = sqrt(det(J . J^T))."""
    J = compute_jacobian(chain, q)
    return float(np.sqrt(max(0.0, np.linalg.det(J @ J.T))))


def condition_number(chain, q):
    """Ratio of largest to smallest singular value of the Jacobian."""
    J = compute_jacobian(chain, q)
    s = np.linalg.svd(J, compute_uv=False)
    if s[-1] < 1e-15:
        return float("inf")
    return float(s[0] / s[-1])


# ---------------------------------------------------------------------------
# Trajectory (smooth interpolation with zero boundary derivatives)
# ---------------------------------------------------------------------------

def smooth_trajectory(q_start, q_end, n_samples):
    """Joint-space interpolation: zero velocity and acceleration at boundaries."""
    tau = np.linspace(0.0, 1.0, n_samples)
    s = 10 * tau**3 - 15 * tau**4 + 6 * tau**5
    return np.outer(1 - s, q_start) + np.outer(s, q_end)


# ---------------------------------------------------------------------------
# SQLite output
# ---------------------------------------------------------------------------

def write_sqlite(output, db_path):
    """Write analysis results to a SQLite database."""
    conn = sqlite3.connect(db_path)

    conn.execute("""CREATE TABLE fk_results (
        config_name TEXT PRIMARY KEY,
        row0 TEXT NOT NULL,
        row1 TEXT NOT NULL,
        row2 TEXT NOT NULL,
        row3 TEXT NOT NULL
    )""")
    for name, mat in output["fk_verification"].items():
        conn.execute(
            "INSERT INTO fk_results VALUES (?,?,?,?,?)",
            (name, json.dumps(mat[0]), json.dumps(mat[1]),
             json.dumps(mat[2]), json.dumps(mat[3])),
        )

    conn.execute("""CREATE TABLE waypoint_analysis (
        id INTEGER PRIMARY KEY,
        reachable INTEGER NOT NULL,
        ik_solution TEXT,
        manipulability REAL,
        condition_number REAL,
        near_singular INTEGER,
        gravity_torques TEXT,
        max_payload_kg REAL
    )""")
    for wp in output["waypoint_analysis"]:
        conn.execute(
            "INSERT INTO waypoint_analysis VALUES (?,?,?,?,?,?,?,?)",
            (
                wp["id"],
                1 if wp["reachable"] else 0,
                json.dumps(wp["ik_solution"]) if wp["ik_solution"] is not None else None,
                wp["manipulability"],
                wp["condition_number"],
                (1 if wp["near_singular"] else 0) if wp["reachable"] else None,
                json.dumps(wp["gravity_torques"]) if wp["gravity_torques"] is not None else None,
                wp["max_payload_kg"],
            ),
        )

    conn.execute("""CREATE TABLE trajectory_segments (
        from_id INTEGER NOT NULL,
        to_id INTEGER NOT NULL,
        min_manipulability REAL NOT NULL,
        max_torque_ratio REAL NOT NULL,
        dynamically_feasible INTEGER NOT NULL,
        feasible INTEGER NOT NULL,
        PRIMARY KEY (from_id, to_id)
    )""")
    for seg in output["trajectory_segments"]:
        conn.execute(
            "INSERT INTO trajectory_segments VALUES (?,?,?,?,?,?)",
            (
                seg["from_id"],
                seg["to_id"],
                seg["min_manipulability"],
                seg["max_torque_ratio"],
                1 if seg["dynamically_feasible"] else 0,
                1 if seg["feasible"] else 0,
            ),
        )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    # Parse inputs
    chain = parse_urdf_chain("/app/robot.urdf")

    with open("/app/waypoints.json") as f:
        wp_data = json.load(f)

    # Load config with robust fallbacks
    config = {}
    try:
        with open("/app/config.json") as f:
            raw = f.read()
        config = json.loads(raw)
        print(f"Loaded config.json, keys: {list(config.keys())}", file=sys.stderr)
    except Exception as exc:
        print(f"Warning: could not load config.json: {exc}", file=sys.stderr)

    # Extract joint limits and effort limits from the parsed chain
    revolute_joints = [j for j in chain if j["type"] == "revolute"]
    n_joints = len(revolute_joints)
    jl_lower = np.array([j["lower"] for j in revolute_joints])
    jl_upper = np.array([j["upper"] for j in revolute_joints])
    effort_limits = [j["effort"] for j in revolute_joints]

    # Config values with robust defaults
    ik_cfg = config.get("ik_solver", {})
    tol = ik_cfg.get("tolerance", 1e-6)
    max_attempts = ik_cfg.get("max_attempts", 50)
    threshold = config.get("manipulability_threshold", 0.001)
    traj_cfg = config.get("trajectory", {})
    n_samples = traj_cfg.get("num_samples", 50)
    gravity = config.get("gravity_vector", [0, 0, -9.81])

    fk_test_cfgs = config.get("fk_test_configurations", {
        "q_zero": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "q_test1": [0.7853981633974483, -0.5235987755982988,
                    1.0471975511965976, -0.7853981633974483,
                    0.5235987755982988, 1.5707963267948966],
        "q_test2": [0.0, -1.5707963267948966, 0.0, 0.0, 0.0, 0.0],
    })

    # ----- FK verification -----
    fk_results = {}
    for name, q_vals in fk_test_cfgs.items():
        q = np.array(q_vals, dtype=float)
        T = forward_kinematics(chain, q)
        fk_results[name] = T.tolist()

    # ----- Waypoint analysis -----
    waypoint_results = []
    reachable_safe = []

    for wp in wp_data["waypoints"]:
        target = np.eye(4)
        target[:3, :3] = rpy_to_matrix(
            wp["orientation_rpy"][0],
            wp["orientation_rpy"][1],
            wp["orientation_rpy"][2],
        )
        target[:3, 3] = wp["position"]

        q0 = np.zeros(n_joints)
        q_sol, success, residual = solve_ik(
            chain, target, q0, jl_lower, jl_upper,
            tol=tol, max_restarts=max_attempts,
        )

        entry = {"id": wp["id"]}
        if success:
            m = manipulability(chain, q_sol)
            cn = condition_number(chain, q_sol)
            ns = bool(m < threshold)

            # Gravity torques
            gt = compute_gravity_torques(chain, q_sol, gravity)

            # Maximum static payload
            J = compute_jacobian(chain, q_sol)
            mp = compute_max_payload(gt, J, effort_limits, gravity)

            entry.update({
                "reachable": True,
                "ik_solution": q_sol.tolist(),
                "manipulability": m,
                "condition_number": cn,
                "near_singular": ns,
                "gravity_torques": gt.tolist(),
                "max_payload_kg": mp,
            })
            if not ns:
                reachable_safe.append((wp["id"], q_sol))
        else:
            entry.update({
                "reachable": False,
                "ik_solution": None,
                "manipulability": None,
                "condition_number": None,
                "near_singular": None,
                "gravity_torques": None,
                "max_payload_kg": None,
            })
        waypoint_results.append(entry)

    # ----- Trajectory segments -----
    trajectory_segments = []
    for i in range(len(reachable_safe) - 1):
        id_from, q_from = reachable_safe[i]
        id_to, q_to = reachable_safe[i + 1]
        traj = smooth_trajectory(q_from, q_to, n_samples)

        min_m = float("inf")
        max_tr = 0.0

        for j in range(len(traj)):
            q_t = traj[j]
            m_t = manipulability(chain, q_t)
            if m_t < min_m:
                min_m = m_t

            gt_t = compute_gravity_torques(chain, q_t, gravity)
            for k in range(n_joints):
                ratio = abs(gt_t[k]) / effort_limits[k]
                if ratio > max_tr:
                    max_tr = ratio

        dyn_feasible = bool(max_tr < 1.0)
        trajectory_segments.append({
            "from_id": id_from,
            "to_id": id_to,
            "min_manipulability": min_m,
            "max_torque_ratio": max_tr,
            "dynamically_feasible": dyn_feasible,
            "feasible": bool((min_m > threshold) and dyn_feasible),
        })

    # ----- Write outputs -----
    output = {
        "fk_verification": fk_results,
        "waypoint_analysis": waypoint_results,
        "trajectory_segments": trajectory_segments,
    }

    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)

    write_sqlite(output, "/app/analysis.db")

    n_reach = sum(1 for w in waypoint_results if w["reachable"])
    n_sing = sum(1 for w in waypoint_results if w["reachable"] and w["near_singular"])
    print(
        f"Done: {n_reach}/6 reachable, {n_sing} near-singular, "
        f"{len(trajectory_segments)} trajectory segments"
    )
    print("Outputs: /app/results.json, /app/analysis.db")


if __name__ == "__main__":
    main()
