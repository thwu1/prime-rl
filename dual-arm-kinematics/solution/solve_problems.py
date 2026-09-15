#!/usr/bin/env python3
"""Solve kinematic problems for the Poppy Torso robot.

Handles FK, IK, Jacobian, manipulability optimization, and dual-arm IK.
"""

import json
import numpy as np
from scipy.optimize import minimize
from ikpy.chain import Chain

URDF_PATH = "/app/poppy_torso.urdf"
PROBLEMS_PATH = "/app/problems.json"
RESULTS_PATH = "/app/results.json"

ACTIVE_INDICES = [4, 5, 6, 7]


def build_chain(arm, specs):
    spec = specs[arm + "_arm"]
    return Chain.from_urdf_file(
        URDF_PATH,
        base_elements=spec["base_elements"],
        last_link_vector=spec["last_link_vector"],
        active_links_mask=spec["active_links_mask"],
        name=arm + "_arm",
    )


def solve_fk(chain, joint_angles):
    fk = chain.forward_kinematics(joint_angles)
    return {
        "position": fk[:3, 3].tolist(),
        "orientation_matrix": fk[:3, :3].tolist(),
    }


def solve_ik(chain, target_position):
    joints = chain.inverse_kinematics(target_position)
    fk = chain.forward_kinematics(joints)
    return {
        "joint_angles": joints.tolist(),
        "achieved_position": fk[:3, 3].tolist(),
    }


def compute_jacobian(chain, joint_angles, active_indices, epsilon=1e-7):
    fk_base = chain.forward_kinematics(joint_angles)[:3, 3]
    J = np.zeros((3, len(active_indices)))
    for i, idx in enumerate(active_indices):
        config_plus = list(joint_angles)
        config_plus[idx] += epsilon
        fk_plus = chain.forward_kinematics(config_plus)[:3, 3]
        J[:, i] = (fk_plus - fk_base) / epsilon
    return J


def solve_jacobian(chain, joint_angles):
    J = compute_jacobian(chain, joint_angles, ACTIVE_INDICES)
    return {"jacobian": J.tolist()}


def compute_manipulability(chain, joint_angles, active_indices):
    J = compute_jacobian(chain, joint_angles, active_indices)
    JJT = J @ J.T
    return np.sqrt(max(0.0, np.linalg.det(JJT)))


def solve_max_manipulability(chain):
    n_links = len(chain.links)

    # Get bounds for the 4 active joints
    bounds = []
    for idx in ACTIVE_INDICES:
        link = chain.links[idx]
        lb, ub = link.bounds
        lb = max(lb, -2 * np.pi)
        ub = min(ub, 2 * np.pi)
        bounds.append((lb, ub))

    def neg_manip(x):
        joints = [0.0] * n_links
        for i, idx in enumerate(ACTIVE_INDICES):
            joints[idx] = x[i]
        return -compute_manipulability(chain, joints, ACTIVE_INDICES)

    best_x = None
    best_manip = -1.0

    # Multiple random restarts for global optimization
    np.random.seed(42)
    for trial in range(80):
        if trial == 0:
            x0 = np.zeros(4)
        else:
            x0 = np.array(
                [np.random.uniform(lb, ub) for lb, ub in bounds]
            )
        result = minimize(
            neg_manip, x0, method="L-BFGS-B", bounds=bounds,
            options={"maxiter": 500, "ftol": 1e-12},
        )
        manip = -result.fun
        if manip > best_manip:
            best_manip = manip
            best_x = result.x.copy()

    # Build full joint vector
    joints = [0.0] * n_links
    for i, idx in enumerate(ACTIVE_INDICES):
        joints[idx] = float(best_x[i])

    return {
        "joint_angles": joints,
        "manipulability": float(best_manip),
    }


def solve_dual_arm_ik(left_chain, right_chain, left_target, right_target):
    n_links = len(left_chain.links)
    left_target = np.array(left_target)
    right_target = np.array(right_target)

    # Optimization variables: [torso(3), left_arm(4), right_arm(4)] = 11 vars
    # torso_indices in chain: 1, 2, 3
    # arm_indices in chain: 4, 5, 6, 7

    # Collect bounds
    bounds = []
    # Torso joint bounds (use left chain, same for both)
    for idx in [1, 2, 3]:
        lb, ub = left_chain.links[idx].bounds
        lb = max(lb, -2 * np.pi)
        ub = min(ub, 2 * np.pi)
        bounds.append((lb, ub))
    # Left arm joint bounds
    for idx in ACTIVE_INDICES:
        lb, ub = left_chain.links[idx].bounds
        lb = max(lb, -2 * np.pi)
        ub = min(ub, 2 * np.pi)
        bounds.append((lb, ub))
    # Right arm joint bounds
    for idx in ACTIVE_INDICES:
        lb, ub = right_chain.links[idx].bounds
        lb = max(lb, -2 * np.pi)
        ub = min(ub, 2 * np.pi)
        bounds.append((lb, ub))

    def cost(x):
        torso = x[:3]
        left_arm = x[3:7]
        right_arm = x[7:11]

        left_joints = [0.0] * n_links
        left_joints[1] = torso[0]
        left_joints[2] = torso[1]
        left_joints[3] = torso[2]
        for i, idx in enumerate(ACTIVE_INDICES):
            left_joints[idx] = left_arm[i]

        right_joints = [0.0] * n_links
        right_joints[1] = torso[0]
        right_joints[2] = torso[1]
        right_joints[3] = torso[2]
        for i, idx in enumerate(ACTIVE_INDICES):
            right_joints[idx] = right_arm[i]

        left_fk = left_chain.forward_kinematics(left_joints)
        right_fk = right_chain.forward_kinematics(right_joints)

        left_err = np.sum((left_fk[:3, 3] - left_target) ** 2)
        right_err = np.sum((right_fk[:3, 3] - right_target) ** 2)

        return left_err + right_err

    best_result = None
    best_cost = float("inf")

    np.random.seed(123)
    for trial in range(30):
        if trial == 0:
            x0 = np.zeros(11)
        else:
            x0 = np.array(
                [np.random.uniform(lb, ub) for lb, ub in bounds]
            )
        result = minimize(
            cost, x0, method="L-BFGS-B", bounds=bounds,
            options={"maxiter": 2000, "ftol": 1e-14},
        )
        if result.fun < best_cost:
            best_cost = result.fun
            best_result = result

    # Extract results
    torso = best_result.x[:3]
    left_arm = best_result.x[3:7]
    right_arm = best_result.x[7:11]

    left_joints = [0.0] * n_links
    right_joints = [0.0] * n_links
    for k in range(3):
        left_joints[k + 1] = float(torso[k])
        right_joints[k + 1] = float(torso[k])
    for i, idx in enumerate(ACTIVE_INDICES):
        left_joints[idx] = float(left_arm[i])
        right_joints[idx] = float(right_arm[i])

    left_fk = left_chain.forward_kinematics(left_joints)
    right_fk = right_chain.forward_kinematics(right_joints)

    return {
        "left_joint_angles": left_joints,
        "right_joint_angles": right_joints,
        "left_achieved_position": left_fk[:3, 3].tolist(),
        "right_achieved_position": right_fk[:3, 3].tolist(),
    }


def main():
    with open(PROBLEMS_PATH) as f:
        data = json.load(f)

    specs = data["chain_specs"]
    problems = data["problems"]
    results = {}

    left_chain = build_chain("left", specs)
    right_chain = build_chain("right", specs)

    for problem in problems:
        pid = problem["id"]
        ptype = problem["type"]
        print(f"Solving {pid} ({ptype})...")

        if ptype == "forward_kinematics":
            arm = problem["arm"]
            chain = left_chain if arm == "left" else right_chain
            results[pid] = solve_fk(chain, problem["joint_angles"])

        elif ptype == "inverse_kinematics":
            arm = problem["arm"]
            chain = left_chain if arm == "left" else right_chain
            results[pid] = solve_ik(chain, problem["target_position"])

        elif ptype == "jacobian":
            arm = problem["arm"]
            chain = left_chain if arm == "left" else right_chain
            results[pid] = solve_jacobian(chain, problem["joint_angles"])

        elif ptype == "max_manipulability":
            arm = problem["arm"]
            chain = left_chain if arm == "left" else right_chain
            results[pid] = solve_max_manipulability(chain)

        elif ptype == "dual_arm_ik":
            results[pid] = solve_dual_arm_ik(
                left_chain,
                right_chain,
                problem["left_target"],
                problem["right_target"],
            )

        else:
            print(f"  Unknown problem type: {ptype}")

    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"All results written to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
