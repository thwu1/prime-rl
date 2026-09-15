#!/usr/bin/env python3
"""
Advanced Manipulator Kinematic and Dexterity Analyzer.
Validates URDFs, generates tree diagrams, computes FK/Jacobian/SVD/workspace.
"""


import json
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
from scipy.optimize import minimize


# ---------------------------------------------------------------------------
# URDF validation and tree diagram generation
# ---------------------------------------------------------------------------

def run_check_urdf(urdf_path):
    result = subprocess.run(
        ["check_urdf", urdf_path], capture_output=True, text=True
    )
    is_valid = result.returncode == 0
    root_link = None
    if is_valid:
        for line in result.stdout.split("\n"):
            if "root Link:" in line:
                root_link = line.split("root Link:")[1].split("has")[0].strip()
                break
    return is_valid, root_link


def count_links_joints(urdf_path):
    tree = ET.parse(urdf_path)
    root = tree.getroot()
    return len(root.findall("link")), len(root.findall("joint"))


def generate_tree_diagram(urdf_path, variant_id, output_dir):
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(
            ["urdf_to_graphviz", urdf_path], cwd=tmpdir,
            capture_output=True, text=True,
        )
        for fname in os.listdir(tmpdir):
            if fname.endswith(".gv"):
                gv_path = os.path.join(tmpdir, fname)
                png_path = os.path.join(output_dir, f"{variant_id}_tree.png")
                subprocess.run(
                    ["dot", "-Tpng", gv_path, "-o", png_path],
                    capture_output=True,
                )
                return True
    return False


# ---------------------------------------------------------------------------
# FK / Jacobian helpers
# ---------------------------------------------------------------------------

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
    axis = axis / np.linalg.norm(axis)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def make_transform(R, p):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = p
    return T


def parse_urdf(urdf_path):
    tree = ET.parse(urdf_path)
    root = tree.getroot()
    joints = {}
    for je in root.findall("joint"):
        name = je.get("name")
        jtype = je.get("type")
        parent = je.find("parent").get("link")
        child = je.find("child").get("link")
        origin = je.find("origin")
        xyz = [0.0, 0.0, 0.0]
        rpy = [0.0, 0.0, 0.0]
        if origin is not None:
            if origin.get("xyz"):
                xyz = list(map(float, origin.get("xyz").split()))
            if origin.get("rpy"):
                rpy = list(map(float, origin.get("rpy").split()))
        axis = [0.0, 0.0, 1.0]
        ae = je.find("axis")
        if ae is not None and ae.get("xyz"):
            axis = list(map(float, ae.get("xyz").split()))
        limits = {"lower": -np.pi, "upper": np.pi}
        le = je.find("limit")
        if le is not None:
            if le.get("lower"):
                limits["lower"] = float(le.get("lower"))
            if le.get("upper"):
                limits["upper"] = float(le.get("upper"))
        joints[name] = {
            "name": name, "type": jtype, "parent": parent, "child": child,
            "xyz": xyz, "rpy": rpy, "axis": axis, "limits": limits,
        }
    return joints


def build_chain(joints, start_link, end_link):
    child_to_joint = {j["child"]: j for j in joints.values()}
    chain = []
    cur = end_link
    while cur != start_link:
        if cur not in child_to_joint:
            raise ValueError(f"No path from {start_link} to {end_link}")
        j = child_to_joint[cur]
        chain.append(j)
        cur = j["parent"]
    chain.reverse()
    return chain


def get_active(chain):
    return [j for j in chain if j["type"] in ("revolute", "continuous", "prismatic")]


def compute_fk(chain, jv, joint_order):
    active = get_active(chain)
    q_map = {j["name"]: jv[i] for i, j in enumerate(active) if i < len(jv)}
    T = np.eye(4)
    for j in chain:
        R_o = rpy_to_rotation(j["rpy"][0], j["rpy"][1], j["rpy"][2])
        T_o = make_transform(R_o, j["xyz"])
        T = T @ T_o
        if j["type"] in ("revolute", "continuous"):
            q = q_map.get(j["name"], 0.0)
            R_j = axis_angle_rotation(j["axis"], q)
            T = T @ make_transform(R_j, [0, 0, 0])
        elif j["type"] == "prismatic":
            q = q_map.get(j["name"], 0.0)
            T = T @ make_transform(np.eye(3), q * np.array(j["axis"]))
    return T


def compute_joint_frames(chain, jv):
    active = get_active(chain)
    q_map = {j["name"]: jv[i] for i, j in enumerate(active) if i < len(jv)}
    frames = []
    T = np.eye(4)
    for j in chain:
        R_o = rpy_to_rotation(j["rpy"][0], j["rpy"][1], j["rpy"][2])
        T_o = make_transform(R_o, j["xyz"])
        T = T @ T_o
        if j["type"] in ("revolute", "continuous"):
            axis_w = T[:3, :3] @ np.array(j["axis"])
            frames.append({"axis": axis_w, "pos": T[:3, 3].copy(), "type": "revolute"})
            q = q_map.get(j["name"], 0.0)
            R_j = axis_angle_rotation(j["axis"], q)
            T = T @ make_transform(R_j, [0, 0, 0])
        elif j["type"] == "prismatic":
            axis_w = T[:3, :3] @ np.array(j["axis"])
            frames.append({"axis": axis_w, "pos": T[:3, 3].copy(), "type": "prismatic"})
            q = q_map.get(j["name"], 0.0)
            T = T @ make_transform(np.eye(3), q * np.array(j["axis"]))
    return frames


def compute_jacobian(chain, jv, joint_order):
    T_ee = compute_fk(chain, jv, joint_order)
    p_ee = T_ee[:3, 3]
    frames = compute_joint_frames(chain, jv)
    n = len(frames)
    J = np.zeros((6, n))
    for i, f in enumerate(frames):
        z = f["axis"]
        p = f["pos"]
        if f["type"] == "revolute":
            J[:3, i] = np.cross(z, p_ee - p)
            J[3:, i] = z
        elif f["type"] == "prismatic":
            J[:3, i] = z
    return J


def compute_max_reach(chain, joints_data, joint_order):
    active = get_active(chain)
    bounds = [(j["limits"]["lower"], j["limits"]["upper"]) for j in active]

    def neg_distance(q):
        T = compute_fk(chain, q, joint_order)
        return -np.linalg.norm(T[:3, 3])

    best = 0.0
    np.random.seed(42)
    candidates = []
    for _ in range(3000):
        q = np.array([np.random.uniform(lo, hi) for lo, hi in bounds])
        d = -neg_distance(q)
        candidates.append((d, q))

    special = [
        [0, -np.pi / 2, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0],
        [0, -np.pi / 2, 0, np.pi / 2, 0, 0],
        [0, -np.pi / 2, 0, -np.pi / 2, 0, 0],
        [0, np.pi / 2, 0, 0, 0, 0],
    ]
    for sc in special:
        d = -neg_distance(sc)
        candidates.append((d, sc))

    candidates.sort(key=lambda x: -x[0])
    for d, q0 in candidates[:15]:
        result = minimize(neg_distance, q0, method="L-BFGS-B", bounds=bounds)
        reach = -result.fun
        if reach > best:
            best = reach
    return best


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def main():
    queries_path = "/app/queries.json"
    output_path = "/app/output/results.json"
    output_dir = "/app/output"

    with open(queries_path) as f:
        queries = json.load(f)

    joint_order = queries["joint_order"]
    wrench = np.array(queries["external_wrench"]["wrench"])
    ws_params = queries["workspace_analysis"]
    sing_thresh = queries["singularity_thresholds"]

    variants = ["variant_a", "variant_b", "variant_c"]
    results = {"variants": {}, "comparative_summary": {}}
    valid_workspace = {}

    for vid in variants:
        urdf_path = f"/app/{vid}.urdf"

        # Validation via check_urdf
        is_valid, root_link = run_check_urdf(urdf_path)
        num_links, num_joints = count_links_joints(urdf_path)

        validation = {
            "is_valid": is_valid,
            "root_link": root_link if is_valid else None,
            "num_links": num_links,
            "num_joints": num_joints,
        }

        if not is_valid:
            results["variants"][vid] = {
                "validation": validation,
                "kinematic_analysis": None,
                "workspace_analysis": None,
            }
            print(f"{vid}: INVALID")
            continue

        # Tree diagram
        generate_tree_diagram(urdf_path, vid, output_dir)
        print(f"{vid}: valid, generated tree diagram")

        # Parse and build chain
        joints_data = parse_urdf(urdf_path)
        chain = build_chain(joints_data, "base_link", "tool0")

        # Kinematic analysis per query
        kin_results = {}
        for q in queries["kinematic_queries"]:
            jv = q["joint_values"]
            T = compute_fk(chain, jv, joint_order)
            J = compute_jacobian(chain, jv, joint_order)

            # SVD analysis
            U, s, Vt = np.linalg.svd(J)
            s_sorted = np.sort(s)[::-1]
            manipulability = float(np.prod(s))
            min_sv = float(s_sorted[-1])
            max_sv = float(s_sorted[0])
            cond = max_sv / min_sv if min_sv > 1e-10 else 1e12

            if min_sv < sing_thresh["singular"]:
                sing_class = "singular"
            elif min_sv < sing_thresh["near_singular"]:
                sing_class = "near_singular"
            else:
                sing_class = "well_conditioned"

            static_torques = (J.T @ wrench).tolist()

            kin_results[q["id"]] = {
                "position": T[:3, 3].tolist(),
                "rotation_matrix": T[:3, :3].tolist(),
                "jacobian": J.tolist(),
                "manipulability": manipulability,
                "singular_values": s_sorted.tolist(),
                "condition_number": cond,
                "singularity_class": sing_class,
                "static_torques": static_torques,
            }
            print(f"  {q['id']}: w={manipulability:.6f}, class={sing_class}")

        # Workspace analysis
        max_reach = compute_max_reach(chain, joints_data, joint_order)

        # Monte Carlo workspace sampling
        np.random.seed(ws_params["random_seed"])
        active = get_active(chain)
        bounds = [(j["limits"]["lower"], j["limits"]["upper"]) for j in active]
        n_samples = ws_params["num_samples"]
        threshold = ws_params["manipulability_threshold"]

        manip_values = []
        for _ in range(n_samples):
            q_rand = np.array([np.random.uniform(lo, hi) for lo, hi in bounds])
            J_rand = compute_jacobian(chain, q_rand, joint_order)
            _, s_rand, _ = np.linalg.svd(J_rand)
            w_rand = float(np.prod(s_rand))
            manip_values.append(w_rand)

        dex_frac = sum(1 for w in manip_values if w > threshold) / n_samples
        avg_manip = sum(manip_values) / n_samples

        workspace = {
            "max_reach": max_reach,
            "dexterous_workspace_fraction": dex_frac,
            "average_manipulability": avg_manip,
        }

        results["variants"][vid] = {
            "validation": validation,
            "kinematic_analysis": kin_results,
            "workspace_analysis": workspace,
        }
        valid_workspace[vid] = workspace
        print(f"  max_reach={max_reach:.4f}, dex_frac={dex_frac:.4f}, avg_w={avg_manip:.6f}")

    # Comparative summary
    if valid_workspace:
        results["comparative_summary"] = {
            "best_max_reach": max(
                valid_workspace, key=lambda v: valid_workspace[v]["max_reach"]
            ),
            "best_avg_manipulability": max(
                valid_workspace, key=lambda v: valid_workspace[v]["average_manipulability"]
            ),
            "best_dexterous_fraction": max(
                valid_workspace, key=lambda v: valid_workspace[v]["dexterous_workspace_fraction"]
            ),
        }

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    main()
