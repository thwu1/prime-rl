"""Schur-complement bundle adjustment with depth anchoring.

Implements the bipartite Schur trick (Triggs et al. 1999) with
Levenberg-Marquardt optimisation.  The Hessian has block structure

    H = [ A   B  ]    A : 6P x 6P camera blocks  (block-diagonal)
        [ B'  C  ]    C : 3N x 3N point blocks   (block-diagonal)
                       B : 6P x 3N cross terms    (sparse)

Reduced camera system:
    M = A - B C^{-1} B^T           (dense 6P x 6P)
    m = g_pose - B C^{-1} g_point

Back-substitution:
    delta_point = C^{-1} (g_point - B^T delta_pose)

Supports optional depth residuals for metric-scale anchoring and
Huber robust kernel (IRLS weighting) for outlier rejection.
"""
import numpy as np
from se3 import se3_retract, transform_point

MIN_Z = 1e-3


def _cz(z):
    """Clamp z to avoid division by zero while preserving sign."""
    if abs(z) < MIN_Z:
        return MIN_Z if z >= 0 else -MIN_Z
    return z


def _hw(rsq, scale):
    """Huber IRLS weight: w = 1 if ||r|| <= scale, else scale/||r||."""
    if not np.isfinite(scale) or scale <= 0:
        return 1.0
    rn = np.sqrt(max(rsq, 0.0))
    return 1.0 if rn <= scale else scale / rn


def reproj_jac(R, t, pw, pix, cam):
    """Reprojection residual and analytical Jacobians.

    Parameters
    ----------
    R : (3,3) rotation matrix (world -> camera)
    t : (3,) translation
    pw : (3,) world point
    pix : (2,) observed pixel [u, v]
    cam : dict with fx, fy, cx, cy

    Returns
    -------
    res : (2,) residual [u_pred - u_obs, v_pred - v_obs]
    j_pose : (2, 6) Jacobian w.r.t. pose tangent [rho(3) | omega(3)]
    j_point : (2, 3) Jacobian w.r.t. world point
    """
    fx, fy, cx, cy = cam['fx'], cam['fy'], cam['cx'], cam['cy']
    pc = transform_point(R, t, pw)
    z = _cz(pc[2])
    iz = 1.0 / z
    iz2 = iz * iz

    res = np.array([fx * pc[0] * iz + cx - pix[0],
                    fy * pc[1] * iz + cy - pix[1]])

    # Projection Jacobian coefficients
    a0, a2 = fx * iz, -fx * pc[0] * iz2
    b1, b2 = fy * iz, -fy * pc[1] * iz2

    # Rotation matrix elements
    r00, r01, r02 = R[0, 0], R[0, 1], R[0, 2]
    r10, r11, r12 = R[1, 0], R[1, 1], R[1, 2]
    r20, r21, r22 = R[2, 0], R[2, 1], R[2, 2]
    px, py, pz = pw[0], pw[1], pw[2]

    # S = -R @ skew(pw)
    s00 =  pz * r01 + py * r02
    s10 =  pz * r11 + py * r12
    s20 =  pz * r21 + py * r22
    s01 =  pz * r00 - px * r02
    s11 =  pz * r10 - px * r12
    s21 =  pz * r20 - px * r22
    s02 = -py * r00 + px * r01
    s12 = -py * r10 + px * r11
    s22 = -py * r20 + px * r21

    # J_point = J_proj @ R  (also equals the rho / upsilon part of J_pose)
    jpt = np.array([[a0*r00 + a2*r20, a0*r01 + a2*r21, a0*r02 + a2*r22],
                    [b1*r10 + b2*r20, b1*r11 + b2*r21, b1*r12 + b2*r22]])

    # J_omega = J_proj @ S
    jom = np.array([[a0*s00 + a2*s20, a0*s01 + a2*s21, a0*s02 + a2*s22],
                    [b1*s10 + b2*s20, b1*s11 + b2*s21, b1*s12 + b2*s22]])

    return res, np.hstack([jpt, jom]), jpt


def depth_jac(R, t, pw, dm, ds):
    """Depth residual and Jacobians.

    Residual: r_z = (Z_pred - d_meas) / sigma
    where Z_pred is the z-coordinate of the point in the camera frame.

    Returns (r_z, J_pose[1x6], J_point[1x3]).
    """
    pc = transform_point(R, t, pw)
    z = _cz(pc[2])
    ivs = 1.0 / max(ds, 1e-6)
    rz = (z - dm) * ivs

    r00, r01, r02 = R[0, 0], R[0, 1], R[0, 2]
    r20, r21, r22 = R[2, 0], R[2, 1], R[2, 2]
    px, py, pz = pw[0], pw[1], pw[2]

    # Row 2 of S = -R @ skew(pw)
    s20 = -pz * r21 + py * r22
    s21 =  pz * r20 - px * r22
    s22 = -py * r20 + px * r21

    jp = np.array([[0., 0., ivs, s20 * ivs, s21 * ivs, s22 * ivs]])
    jx = np.array([[r00 * ivs, r01 * ivs, r02 * ivs]])
    return rz, jp, jx


def bundle_adjust_schur(poses, points, observations, camera, params=None):
    """Run Schur-complement bundle adjustment.

    Parameters
    ----------
    poses : list of (R, t)
        Initial camera poses (world -> camera).
    points : ndarray (N, 3)
        Initial 3D point estimates.
    observations : list of dict
        Each dict has: pose_idx, point_idx, pixel(2),
        depth_meas (float or None), depth_sigma, fixed_pose (bool).
    camera : dict
        Intrinsics {fx, fy, cx, cy}.
    params : dict, optional
        {max_iterations, cost_tolerance, initial_lambda, huber_scale}.

    Returns
    -------
    dict with optimized_poses, optimized_points, iterations, converged.
    """
    p = params or {}
    max_iter = p.get('max_iterations', 100)
    cost_tol = p.get('cost_tolerance', 1e-8)
    lam = p.get('initial_lambda', 1e-3)
    hub_scale = p.get('huber_scale', float('inf'))
    use_hub = np.isfinite(hub_scale) and hub_scale > 0

    nP = len(poses)
    nN = len(points)

    # Determine which poses / points are free (optimised)
    pose_free = [False] * nP
    point_free = [False] * nN
    for o in observations:
        if not o.get('fixed_pose', False):
            pose_free[o['pose_idx']] = True
        point_free[o['point_idx']] = True

    # Build local index maps (free variable -> dense index)
    p_loc = [-1] * nP
    x_loc = [-1] * nN
    idx = 0
    for i in range(nP):
        if pose_free[i]:
            p_loc[i] = idx
            idx += 1
    n_fp = idx  # number of free poses
    idx = 0
    for i in range(nN):
        if point_free[i]:
            x_loc[i] = idx
            idx += 1
    n_fx = idx  # number of free points

    if n_fp == 0:
        raise ValueError("No free poses to optimise")

    # Mutable optimisation state
    Rs = [R.copy() for R, _ in poses]
    ts = [t.copy() for _, t in poses]
    pts = points.copy().astype(np.float64)

    converged = False
    iters_done = 0

    for _it in range(max_iter):
        iters_done += 1

        # Allocate blocks
        A_blk = [np.zeros((6, 6)) for _ in range(n_fp)]
        C_blk = [np.zeros((3, 3)) for _ in range(n_fx)]
        g_pose = [np.zeros(6) for _ in range(n_fp)]
        g_point = [np.zeros(3) for _ in range(n_fx)]
        B_by_pt = [[] for _ in range(n_fx)]  # B blocks grouped by point index

        cost = 0.0

        # ---- Linearise all observations ----
        for o in observations:
            pi, xi = o['pose_idx'], o['point_idx']
            r, jp, jx = reproj_jac(Rs[pi], ts[pi], pts[xi], o['pixel'], camera)
            rsq = float(r @ r)

            # Huber IRLS weighting
            w = _hw(rsq, hub_scale) if use_hub else 1.0
            if w != 1.0:
                sw = np.sqrt(w)
                r = r * sw
                jp = jp * sw
                jx = jx * sw
            cost += 0.5 * float(r @ r)

            pli, xli = p_loc[pi], x_loc[xi]

            # Accumulate into A (camera block)
            if pli >= 0:
                A_blk[pli] += jp.T @ jp
                g_pose[pli] -= jp.T @ r

            # Accumulate into C (point block)
            if xli >= 0:
                C_blk[xli] += jx.T @ jx
                g_point[xli] -= jx.T @ r

            # Cross term B (stored per-point for Schur reduction)
            if pli >= 0 and xli >= 0:
                B_by_pt[xli].append((pli, jp.T @ jx))

            # ---- Depth residual ----
            dm = o.get('depth_meas')
            if dm is not None:
                rz, jpd, jxd = depth_jac(Rs[pi], ts[pi], pts[xi], dm, o['depth_sigma'])
                rsqd = rz * rz
                wd = _hw(rsqd, hub_scale) if use_hub else 1.0
                cost += 0.5 * wd * rsqd

                if pli >= 0:
                    A_blk[pli] += wd * (jpd.T @ jpd)
                    g_pose[pli] -= wd * jpd.T.flatten() * rz
                if xli >= 0:
                    C_blk[xli] += wd * (jxd.T @ jxd)
                    g_point[xli] -= wd * jxd.T.flatten() * rz
                if pli >= 0 and xli >= 0:
                    B_by_pt[xli].append((pli, wd * (jpd.T @ jxd)))

        # ---- LM damping ----
        for a in A_blk:
            a += lam * np.eye(6)
        for c in C_blk:
            c += lam * np.eye(3)

        # ---- Build reduced camera system M, m ----
        dim = n_fp * 6
        M = np.zeros((dim, dim))
        m = np.zeros(dim)

        # Place A on diagonal
        for k in range(n_fp):
            s = k * 6
            M[s:s + 6, s:s + 6] = A_blk[k]
            m[s:s + 6] = g_pose[k]

        # Invert C blocks (3x3 each)
        C_inv = []
        for c in C_blk:
            det = np.linalg.det(c)
            C_inv.append(np.linalg.inv(c) if abs(det) > 1e-20 else None)

        # Schur complement: M -= B C^{-1} B^T,  m -= B C^{-1} g_point
        for j in range(n_fx):
            ci = C_inv[j]
            if ci is None:
                continue

            # RHS correction
            for pli, b_block in B_by_pt[j]:
                m[pli * 6:(pli + 1) * 6] -= b_block @ ci @ g_point[j]

            # LHS correction
            for _, (pli1, b1) in enumerate(B_by_pt[j]):
                for _, (pli2, b2) in enumerate(B_by_pt[j]):
                    M[pli1*6:(pli1+1)*6, pli2*6:(pli2+1)*6] -= b1 @ ci @ b2.T

        # Symmetrise (numerical hygiene)
        M = 0.5 * (M + M.T)

        # Solve reduced system via Cholesky
        try:
            L = np.linalg.cholesky(M)
            delta_pose = np.linalg.solve(L @ L.T, m)
        except np.linalg.LinAlgError:
            lam *= 10.0
            if lam > 1e10:
                break
            continue

        # ---- Back-substitute for point updates ----
        delta_pts = [np.zeros(3) for _ in range(n_fx)]
        for j in range(n_fx):
            ci = C_inv[j]
            if ci is None:
                continue
            rhs = g_point[j].copy()
            for pli, b_block in B_by_pt[j]:
                rhs += b_block.T @ delta_pose[pli * 6:(pli + 1) * 6]
            delta_pts[j] = ci @ rhs

        # ---- Trial step: retract poses, add to points ----
        Rs_trial = [R.copy() for R in Rs]
        ts_trial = [t.copy() for t in ts]
        for i in range(nP):
            if p_loc[i] >= 0:
                pli = p_loc[i]
                Rs_trial[i], ts_trial[i] = se3_retract(
                    Rs[i], ts[i], delta_pose[pli * 6:(pli + 1) * 6])

        pts_trial = pts.copy()
        for i in range(nN):
            if x_loc[i] >= 0:
                pts_trial[i] += delta_pts[x_loc[i]]

        # ---- Evaluate trial cost ----
        new_cost = 0.0
        for o in observations:
            pc = transform_point(
                Rs_trial[o['pose_idx']], ts_trial[o['pose_idx']],
                pts_trial[o['point_idx']])
            z = _cz(pc[2])
            u = camera['fx'] * pc[0] / z + camera['cx']
            v = camera['fy'] * pc[1] / z + camera['cy']
            r = np.array([u - o['pixel'][0], v - o['pixel'][1]])
            rsq = float(r @ r)
            w = _hw(rsq, hub_scale) if use_hub else 1.0
            new_cost += 0.5 * w * rsq

            dm = o.get('depth_meas')
            if dm is not None:
                rz = (_cz(pc[2]) - dm) / max(o['depth_sigma'], 1e-6)
                rsqd = rz * rz
                wd = _hw(rsqd, hub_scale) if use_hub else 1.0
                new_cost += 0.5 * wd * rsqd

        # ---- Accept / reject step ----
        if new_cost < cost:
            rel = (cost - new_cost) / cost if cost > 1e-12 else 0.0
            Rs, ts, pts = Rs_trial, ts_trial, pts_trial
            lam = max(lam / 3.0, 1e-8)
            if rel < cost_tol:
                converged = True
                break
        else:
            lam *= 10.0
            if lam > 1e10:
                break

    return {
        'optimized_poses': [(Rs[i], ts[i]) for i in range(nP)],
        'optimized_points': pts,
        'iterations': iters_done,
        'converged': converged,
    }
