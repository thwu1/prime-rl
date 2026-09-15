"""Differential inverse kinematics solver using SE(3) Lie group operations.

"""

import numpy as np
import mujoco
import qpsolvers


def skew(v):
    """Skew-symmetric matrix from 3-vector."""
    return np.array([
        [0.0, -v[2], v[1]],
        [v[2], 0.0, -v[0]],
        [-v[1], v[0], 0.0],
    ], dtype=np.float64)


def so3_exp(omega):
    """SO(3) exponential map via Rodrigues' formula."""
    theta = np.linalg.norm(omega)
    if theta < 1e-10:
        return np.eye(3, dtype=np.float64) + skew(omega)
    K = skew(omega / theta)
    return (np.eye(3, dtype=np.float64)
            + np.sin(theta) * K
            + (1.0 - np.cos(theta)) * (K @ K))


def so3_log(R):
    """SO(3) logarithmic map."""
    cos_theta = np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0)
    theta = np.arccos(cos_theta)

    if theta < 1e-10:
        return np.array([
            R[2, 1] - R[1, 2],
            R[0, 2] - R[2, 0],
            R[1, 0] - R[0, 1],
        ], dtype=np.float64) * 0.5

    if abs(theta - np.pi) < 1e-6:
        S = R + np.eye(3)
        col_norms = np.linalg.norm(S, axis=0)
        idx = np.argmax(col_norms)
        axis = S[:, idx] / col_norms[idx]
        return theta * axis

    return (theta / (2.0 * np.sin(theta))) * np.array([
        R[2, 1] - R[1, 2],
        R[0, 2] - R[2, 0],
        R[1, 0] - R[0, 1],
    ], dtype=np.float64)


def se3_exp(twist):
    """SE(3) exponential map."""
    v = twist[:3]
    omega = twist[3:]
    theta = np.linalg.norm(omega)
    R = so3_exp(omega)

    if theta < 1e-10:
        V = R.copy()
    else:
        K = skew(omega)
        t2 = theta * theta
        V = (np.eye(3, dtype=np.float64)
             + ((1.0 - np.cos(theta)) / t2) * K
             + ((theta - np.sin(theta)) / (t2 * theta)) * (K @ K))

    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = R
    T[:3, 3] = V @ v
    return T


def se3_log(T):
    """SE(3) logarithmic map."""
    R = T[:3, :3]
    p = T[:3, 3]
    omega = so3_log(R)
    theta = np.linalg.norm(omega)

    if theta < 1e-10:
        K = skew(omega)
        Vinv = np.eye(3, dtype=np.float64) - 0.5 * K + (1.0 / 12.0) * (K @ K)
    else:
        K = skew(omega)
        t2 = theta * theta
        Vinv = (np.eye(3, dtype=np.float64)
                - 0.5 * K
                + (1.0 / t2) * (K @ K))

    v = Vinv @ p
    return np.concatenate([v, omega])


def se3_adjoint(T):
    """SE(3) adjoint representation."""
    R = T[:3, :3]
    p = T[:3, 3]
    adj = np.zeros((6, 6), dtype=np.float64)
    adj[:3, :3] = R
    adj[:3, 3:] = skew(p) @ R
    adj[3:, 3:] = R
    return adj


def body_jacobian(model, data, site_id):
    """Compute the body-frame Jacobian for a site."""
    nv = model.nv
    jac_pos = np.zeros((3, nv), dtype=np.float64)
    jac_rot = np.zeros((3, nv), dtype=np.float64)
    mujoco.mj_jacSite(model, data, jac_pos, jac_rot, site_id)

    xmat = data.site_xmat[site_id].reshape(3, 3)
    R_fw = xmat.T

    jac_b = np.zeros((6, nv), dtype=np.float64)
    jac_b[:3] = R_fw @ jac_rot
    jac_b[3:] = R_fw @ jac_pos
    return jac_b


def frame_error(T_target, T_current):
    """Compute frame task error as a body twist."""
    R_c = T_current[:3, :3]
    p_c = T_current[:3, 3]

    T_c_inv = np.eye(4, dtype=np.float64)
    T_c_inv[:3, :3] = R_c.T
    T_c_inv[:3, 3] = -R_c.T @ p_c

    return se3_log(T_target @ T_c_inv)


def solve_ik(
    model, data, site_id, T_target,
    dt=0.01, pos_weight=1.0, ori_weight=1.0,
    damping=1e-6, max_iters=500, tol=1e-5,
    vel_limits=None, collision_pairs=None,
    collision_min_dist=0.01, collision_gain=0.85,
):
    """Iterative differential IK with QP constraints."""
    nv = model.nv
    W = np.diag(np.array([pos_weight] * 3 + [ori_weight] * 3, dtype=np.float64))

    for _ in range(max_iters):
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)

        xpos = data.site_xpos[site_id].copy()
        xmat = data.site_xmat[site_id].reshape(3, 3).copy()
        T_current = np.eye(4, dtype=np.float64)
        T_current[:3, :3] = xmat
        T_current[:3, 3] = xpos

        err = frame_error(T_target, T_current)
        if np.linalg.norm(err) < tol:
            return data.qpos.copy(), True

        J = body_jacobian(model, data, site_id)

        H = J.T @ W @ J + damping * np.eye(nv, dtype=np.float64)
        c = -J.T @ W @ err

        G_rows = []
        h_vals = []

        q = data.qpos.copy()
        for j in range(model.njnt):
            if not model.jnt_limited[j]:
                continue
            jnt_type = model.jnt_type[j]
            if jnt_type == mujoco.mjtJoint.mjJNT_FREE:
                continue
            dof_id = model.jnt_dofadr[j]
            qpos_id = model.jnt_qposadr[j]
            q_min = model.jnt_range[j, 0]
            q_max = model.jnt_range[j, 1]

            row_upper = np.zeros(nv, dtype=np.float64)
            row_upper[dof_id] = 1.0
            G_rows.append(row_upper)
            h_vals.append(0.95 * (q_max - q[qpos_id]))

            row_lower = np.zeros(nv, dtype=np.float64)
            row_lower[dof_id] = 1.0
            G_rows.append(row_lower)
            h_vals.append(0.95 * (q[qpos_id] - q_min))

        if vel_limits is not None:
            for dof_id in range(min(len(vel_limits), nv)):
                if vel_limits[dof_id] > 0:
                    row_p = np.zeros(nv, dtype=np.float64)
                    row_p[dof_id] = 1.0
                    G_rows.append(row_p)
                    h_vals.append(dt * vel_limits[dof_id])

                    row_n = np.zeros(nv, dtype=np.float64)
                    row_n[dof_id] = -1.0
                    G_rows.append(row_n)
                    h_vals.append(dt * vel_limits[dof_id])

        if collision_pairs:
            fromto = np.zeros(6, dtype=np.float64)
            det_dist = max(collision_min_dist * 10.0, 0.1)
            for geom1_id, geom2_id in collision_pairs:
                dist = mujoco.mj_geomDistance(
                    model, data, geom1_id, geom2_id, det_dist, fromto,
                )
                if abs(dist - det_dist) < 1e-12:
                    continue

                normal = fromto[:3] - fromto[3:]
                n_len = np.linalg.norm(normal)
                if n_len < 1e-12:
                    continue
                normal = normal / n_len

                jac1 = np.zeros((3, nv), dtype=np.float64)
                jac2 = np.zeros((3, nv), dtype=np.float64)
                body1 = model.geom_bodyid[geom1_id]
                body2 = model.geom_bodyid[geom2_id]
                mujoco.mj_jac(model, data, jac2, None, fromto[3:].copy(), body2)
                mujoco.mj_jac(model, data, jac1, None, fromto[:3].copy(), body1)

                contact_jac = normal @ (jac2 - jac1)

                sign = -1.0 if dist >= 0 else 1.0
                if dist > collision_min_dist:
                    ub = collision_gain * (dist - collision_min_dist)
                else:
                    ub = 0.0

                G_rows.append(sign * contact_jac)
                h_vals.append(ub)

        if G_rows:
            G = np.array(G_rows, dtype=np.float64)
            h = np.array(h_vals, dtype=np.float64)
        else:
            G = None
            h = None

        problem = qpsolvers.Problem(H, c, G, h)
        solution = qpsolvers.solve_problem(problem, solver="daqp")

        if solution.x is not None and solution.found:
            delta_q = solution.x
        else:
            delta_q = np.linalg.solve(H, -c)

        v_int = delta_q / dt
        mujoco.mj_integratePos(model, data.qpos, v_int, dt)

    return data.qpos.copy(), False
