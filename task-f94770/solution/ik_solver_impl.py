"""Differential inverse kinematics solver using SE(3) Lie group operations.

"""

import numpy as np
import mujoco
import qpsolvers


def skew(v):
    """Skew-symmetric matrix from 3-vector.

    Args:
        v: (3,) vector.
    Returns:
        (3, 3) skew-symmetric matrix [v]_x.
    """
    return np.array([
        [0.0, -v[2], v[1]],
        [v[2], 0.0, -v[0]],
        [-v[1], v[0], 0.0],
    ], dtype=np.float64)


def so3_exp(omega):
    """SO(3) exponential map via Rodrigues' formula.

    Args:
        omega: (3,) axis-angle vector.
    Returns:
        (3, 3) rotation matrix.
    """
    theta = np.linalg.norm(omega)
    if theta < 1e-10:
        return np.eye(3, dtype=np.float64) + skew(omega)
    K = skew(omega / theta)
    return (np.eye(3, dtype=np.float64)
            + np.sin(theta) * K
            + (1.0 - np.cos(theta)) * (K @ K))


def so3_log(R):
    """SO(3) logarithmic map.

    Handles edge cases near theta=0 and theta=pi.

    Args:
        R: (3, 3) rotation matrix.
    Returns:
        (3,) axis-angle vector.
    """
    cos_theta = np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0)
    theta = np.arccos(cos_theta)

    if theta < 1e-10:
        # Near identity: first-order approximation R ≈ I + [ω]_x
        return np.array([
            R[2, 1] - R[1, 2],
            R[0, 2] - R[2, 0],
            R[1, 0] - R[0, 1],
        ], dtype=np.float64) * 0.5

    if abs(theta - np.pi) < 1e-6:
        # Near pi: extract axis from R + I (rank-1 matrix whose column
        # space is the rotation axis).
        S = R + np.eye(3)
        col_norms = np.linalg.norm(S, axis=0)
        idx = np.argmax(col_norms)
        axis = S[:, idx] / col_norms[idx]
        return theta * axis

    # General case
    return (theta / (2.0 * np.sin(theta))) * np.array([
        R[2, 1] - R[1, 2],
        R[0, 2] - R[2, 0],
        R[1, 0] - R[0, 1],
    ], dtype=np.float64)


def se3_exp(twist):
    """SE(3) exponential map.

    Tangent parameterisation: [v; omega] where v is translational and omega
    is rotational.

    Args:
        twist: (6,) twist vector [v_x, v_y, v_z, w_x, w_y, w_z].
    Returns:
        (4, 4) homogeneous transformation matrix.
    """
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
    """SE(3) logarithmic map.

    Returns the twist vector [v; omega] such that exp(twist) = T.

    Args:
        T: (4, 4) homogeneous transformation matrix.
    Returns:
        (6,) twist vector [v_x, v_y, v_z, w_x, w_y, w_z].
    """
    R = T[:3, :3]
    p = T[:3, 3]
    omega = so3_log(R)
    theta = np.linalg.norm(omega)

    if theta < 1e-10:
        K = skew(omega)
        Vinv = np.eye(3, dtype=np.float64) - 0.5 * K + (1.0 / 12.0) * (K @ K)
    else:
        K = skew(omega)
        half_theta = 0.5 * theta
        t2 = theta * theta
        Vinv = (np.eye(3, dtype=np.float64)
                - 0.5 * K
                + (1.0 - 0.5 * theta * np.cos(half_theta) / np.sin(half_theta))
                / t2 * (K @ K))

    v = Vinv @ p
    return np.concatenate([v, omega])


def se3_adjoint(T):
    """SE(3) adjoint representation.

    Ad(T) maps body twists: xi' = Ad(T) xi.

    Args:
        T: (4, 4) homogeneous transformation matrix.
    Returns:
        (6, 6) adjoint matrix [[R, [p]_x R], [0, R]].
    """
    R = T[:3, :3]
    p = T[:3, 3]
    adj = np.zeros((6, 6), dtype=np.float64)
    adj[:3, :3] = R
    adj[:3, 3:] = skew(p) @ R
    adj[3:, 3:] = R
    return adj


def body_jacobian(model, data, site_id):
    """Compute the body-frame Jacobian for a site.

    MuJoCo's mj_jacSite returns a world-frame Jacobian.  To obtain the
    body-frame (spatial) Jacobian we left-multiply by the adjoint of the
    pure rotation T_{frame,world} = [R_fw, 0; 0, 1] where R_fw = R_wf^T.

    Args:
        model: MuJoCo MjModel.
        data:  MuJoCo MjData (after forward kinematics).
        site_id: Integer site id.
    Returns:
        (6, nv) body-frame Jacobian matrix.
    """
    nv = model.nv
    jac_pos = np.zeros((3, nv), dtype=np.float64)
    jac_rot = np.zeros((3, nv), dtype=np.float64)
    mujoco.mj_jacSite(model, data, jac_pos, jac_rot, site_id)

    # Rotation from world to frame
    xmat = data.site_xmat[site_id].reshape(3, 3)
    R_fw = xmat.T

    jac_b = np.zeros((6, nv), dtype=np.float64)
    jac_b[:3] = R_fw @ jac_pos
    jac_b[3:] = R_fw @ jac_rot
    return jac_b


def frame_error(T_target, T_current):
    """Compute frame task error as a body twist.

    Returns log(T_current^{-1} T_target), the SE(3) right-minus operation.

    Args:
        T_target:  (4, 4) desired pose.
        T_current: (4, 4) current pose.
    Returns:
        (6,) body twist error [v; omega].
    """
    R_c = T_current[:3, :3]
    p_c = T_current[:3, 3]

    T_c_inv = np.eye(4, dtype=np.float64)
    T_c_inv[:3, :3] = R_c.T
    T_c_inv[:3, 3] = -R_c.T @ p_c

    return se3_log(T_c_inv @ T_target)


def solve_ik(
    model,
    data,
    site_id,
    T_target,
    dt=0.01,
    pos_weight=1.0,
    ori_weight=1.0,
    damping=1e-6,
    max_iters=500,
    tol=1e-5,
    vel_limits=None,
    collision_pairs=None,
    collision_min_dist=0.01,
    collision_gain=0.85,
):
    """Iterative differential IK with QP-based joint limits and collision avoidance.

    At each iteration the QP is:

        min_{dq}  0.5 dq^T H dq + c^T dq
        s.t.      G dq <= h

    where (H, c) encode a weighted frame tracking objective and (G, h)
    encode joint position limits, optional velocity limits, and optional
    collision avoidance constraints.

    Args:
        model: MuJoCo MjModel.
        data:  MuJoCo MjData (modified in-place during solving).
        site_id: End-effector site id.
        T_target: (4, 4) target pose.
        dt: Integration timestep in seconds.
        pos_weight: Weight on position error.
        ori_weight: Weight on orientation error.
        damping: Levenberg-Marquardt regularisation.
        max_iters: Maximum number of iterations.
        tol: Convergence tolerance on twist-error norm.
        vel_limits: Optional (nv,) array of max joint velocity magnitudes.
        collision_pairs: Optional list of (geom_id_a, geom_id_b) tuples.
        collision_min_dist: Minimum allowed distance between collision pairs.
        collision_gain: Gain in (0, 1] for collision avoidance.
    Returns:
        (q_final, converged) — final joint configuration and convergence flag.
    """
    nv = model.nv
    W = np.diag(np.array([pos_weight] * 3 + [ori_weight] * 3, dtype=np.float64))

    for _ in range(max_iters):
        # Forward kinematics -------------------------------------------------
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)

        # Current end-effector pose ------------------------------------------
        xpos = data.site_xpos[site_id].copy()
        xmat = data.site_xmat[site_id].reshape(3, 3).copy()
        T_current = np.eye(4, dtype=np.float64)
        T_current[:3, :3] = xmat
        T_current[:3, 3] = xpos

        # Task-space error ----------------------------------------------------
        err = frame_error(T_target, T_current)
        if np.linalg.norm(err) < tol:
            return data.qpos.copy(), True

        # Body-frame Jacobian -------------------------------------------------
        J = body_jacobian(model, data, site_id)

        # QP objective --------------------------------------------------------
        H = J.T @ W @ J + damping * np.eye(nv, dtype=np.float64)
        c = -J.T @ W @ err

        # Inequality constraints ----------------------------------------------
        G_rows = []
        h_vals = []

        # --- Joint position limits ---
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
            row_lower[dof_id] = -1.0
            G_rows.append(row_lower)
            h_vals.append(0.95 * (q[qpos_id] - q_min))

        # --- Velocity limits ---
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

        # --- Collision avoidance ---
        if collision_pairs:
            fromto = np.zeros(6, dtype=np.float64)
            det_dist = max(collision_min_dist * 10.0, 0.1)
            for geom1_id, geom2_id in collision_pairs:
                dist = mujoco.mj_geomDistance(
                    model, data, geom1_id, geom2_id, det_dist, fromto,
                )
                if abs(dist - det_dist) < 1e-12:
                    continue

                normal = fromto[3:] - fromto[:3]
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

        # Build constraint matrices -------------------------------------------
        if G_rows:
            G = np.array(G_rows, dtype=np.float64)
            h = np.array(h_vals, dtype=np.float64)
        else:
            G = None
            h = None

        # Solve QP ------------------------------------------------------------
        problem = qpsolvers.Problem(H, c, G, h)
        solution = qpsolvers.solve_problem(problem, solver="daqp")

        if solution.x is not None and solution.found:
            delta_q = solution.x
        else:
            delta_q = np.linalg.solve(H, -c)

        # Integrate ------------------------------------------------------------
        v = delta_q / dt
        mujoco.mj_integratePos(model, data.qpos, v, dt)

    return data.qpos.copy(), False
