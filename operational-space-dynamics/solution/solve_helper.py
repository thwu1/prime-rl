#!/usr/bin/env python3

"""
Robotic workcell capability assessment solver.

Evaluates a Kuka IIWA 7-DOF robot arm's ability to sustain required contact
wrenches at each workstation, accounting for gravity and tool payload.
"""

import json
import numpy as np
import pybullet as p
import pybullet_data


def compute_max_wrench_scale(tau_static, tau_task, tau_limits):
    """
    Find the largest s >= 0 such that
        |tau_static[i] + s * tau_task[i]| <= tau_limits[i]
    holds for all joints i simultaneously.

    This is a 1-D linear feasibility problem: each joint constrains s
    to an interval, and we intersect all intervals with [0, inf).
    """
    n = len(tau_static)
    s_min_overall = 0.0
    s_max_overall = float('inf')

    for i in range(n):
        ts = float(tau_static[i])
        tt = float(tau_task[i])
        tl = float(tau_limits[i])

        if abs(tt) < 1e-12:
            if abs(ts) > tl + 1e-10:
                return 0.0
            continue

        a = (tl - ts) / tt
        b = (-tl - ts) / tt
        lo_i = min(a, b)
        hi_i = max(a, b)

        s_min_overall = max(s_min_overall, lo_i)
        s_max_overall = min(s_max_overall, hi_i)

    if s_max_overall < s_min_overall - 1e-10:
        return 0.0

    return max(0.0, s_max_overall)


def analyze_station(robot_id, config, station_id):
    """Perform complete capability analysis for a single workstation."""
    station = config['stations'][station_id]
    q = station['joint_configuration']
    wrench = np.array(station['required_wrench'], dtype=float)
    n = len(q)

    ee_link = config['robot']['end_effector_link_index']
    tool = config['tool']
    torque_limits = np.array(config['robot']['joint_torque_limits'], dtype=float)
    thresholds = config['classification_thresholds']
    tip_pos = tool['local_position']
    payload_mass = tool['mass_kg']
    gravity = np.array(config['robot']['gravity'], dtype=float)
    lj_threshold = thresholds.get('limiting_joint_utilization', 0.995)

    # Set joint configuration
    for i in range(n):
        p.resetJointState(robot_id, i, q[i])

    zero_vec = [0.0] * n

    # --- Jacobian at the tool tip ---
    jac_lin, jac_ang = p.calculateJacobian(
        robot_id, ee_link, tip_pos,
        list(q), zero_vec, zero_vec
    )
    J_lin = np.array(jac_lin)
    J_ang = np.array(jac_ang)
    J = np.vstack([J_lin, J_ang])  # 6x7

    # --- Static torques (gravity + payload, no task wrench) ---
    tau_gravity = np.array(p.calculateInverseDynamics(
        robot_id, list(q), zero_vec, zero_vec
    ))

    F_payload = payload_mass * gravity
    tau_payload = J_lin.T @ F_payload

    tau_static = tau_gravity + tau_payload

    # --- Task wrench mapping ---
    tau_task = J.T @ wrench

    # --- Force capacity analysis ---
    mws = compute_max_wrench_scale(tau_static, tau_task, torque_limits)

    # Identify limiting joints at max wrench scale
    tau_at_max = tau_static + mws * tau_task
    utilization_at_max = np.abs(tau_at_max) / torque_limits
    limiting = sorted([i for i in range(n) if float(utilization_at_max[i]) > lj_threshold])

    # Torque utilization at full required wrench (s=1.0)
    tau_at_one = tau_static + tau_task
    torque_util = (np.abs(tau_at_one) / torque_limits).tolist()

    # --- Kinematic conditioning ---
    _, sigma, _ = np.linalg.svd(J)
    if sigma[-1] > 1e-15:
        cond = float(sigma[0] / sigma[-1])
    else:
        cond = float('inf')
    is_singular = cond > thresholds['singularity_condition_number']

    # Yoshikawa manipulability: sqrt(det(J @ J^T))
    JJt = J @ J.T
    manip = float(np.sqrt(max(0.0, np.linalg.det(JJt))))

    # --- Classification ---
    if mws >= thresholds['feasible_min_scale']:
        fclass = "FEASIBLE"
    elif mws >= thresholds['marginal_min_scale']:
        fclass = "MARGINAL"
    else:
        fclass = "INFEASIBLE"

    return {
        'station_id': station_id,
        'feasibility_class': fclass,
        'max_wrench_scale': float(mws),
        'limiting_joints': limiting,
        'condition_number': float(cond),
        'is_near_singular': bool(is_singular),
        'manipulability': float(manip),
        'torque_utilization': [float(x) for x in torque_util],
    }


def main():
    with open('/app/workcell_config.json') as f:
        config = json.load(f)

    cid = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.setGravity(*config['robot']['gravity'])

    robot_id = p.loadURDF(
        config['robot']['urdf'],
        config['robot']['base_position'],
        useFixedBase=True
    )

    num_joints = p.getNumJoints(robot_id)
    print(f"Loaded {config['robot']['urdf']} with {num_joints} joints")

    station_ids = sorted(config['stations'].keys())
    results = []

    for sid in station_ids:
        result = analyze_station(robot_id, config, sid)
        results.append(result)

        flag = " [NEAR-SINGULAR]" if result['is_near_singular'] else ""
        print(f"  {sid}: class={result['feasibility_class']}, "
              f"max_scale={result['max_wrench_scale']:.4f}, "
              f"cond={result['condition_number']:.2f}, "
              f"manip={result['manipulability']:.6f}{flag}")

    ranked = sorted(results, key=lambda x: x['max_wrench_scale'], reverse=True)
    station_ranking = [r['station_id'] for r in ranked]

    classes = [r['feasibility_class'] for r in results]
    summary = {
        'feasible_count': classes.count('FEASIBLE'),
        'marginal_count': classes.count('MARGINAL'),
        'infeasible_count': classes.count('INFEASIBLE'),
        'station_ranking': station_ranking,
    }

    output = {
        'stations': results,
        'summary': summary,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(output, f, indent=2)

    p.disconnect()
    print(f"\nAssessment written to /app/results.json")
    print(f"  Feasible: {summary['feasible_count']}, "
          f"Marginal: {summary['marginal_count']}, "
          f"Infeasible: {summary['infeasible_count']}")
    print(f"  Ranking: {' > '.join(station_ranking)}")


if __name__ == '__main__':
    main()
