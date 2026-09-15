#!/usr/bin/env python3
"""Structure from Motion pipeline for multi-view reconstruction.

"""

import json
import os
import numpy as np
import cv2
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix


# -----------------------------------------------------------------------
# Data I/O
# -----------------------------------------------------------------------

def load_data():
    with open("/app/data/intrinsics.json") as f:
        intr = json.load(f)
    with open("/app/data/observations.json") as f:
        obs = json.load(f)
    return intr, obs


def build_K(cam):
    return np.array([
        [cam["fx"], 0, cam["cx"]],
        [0, cam["fy"], cam["cy"]],
        [0, 0, 1],
    ], dtype=np.float64)


# -----------------------------------------------------------------------
# Geometry helpers
# -----------------------------------------------------------------------

def normalize_pts(pts, K):
    """Pixel coords (Nx2) -> normalised image coords (Nx2)."""
    K_inv = np.linalg.inv(K)
    ones = np.ones((len(pts), 1))
    pts_h = np.hstack([pts, ones])
    pts_n = (K_inv @ pts_h.T).T
    return pts_n[:, :2].copy()


def reproj_error(pt3d, R, t, K, uv_obs):
    """Reprojection error for a single 3D point in one view."""
    P_cam = R @ pt3d + t
    if P_cam[2] < 0.01:
        return 1e6
    u = K[0, 0] * P_cam[0] / P_cam[2] + K[0, 2]
    v = K[1, 1] * P_cam[1] / P_cam[2] + K[1, 2]
    return np.sqrt((u - uv_obs[0])**2 + (v - uv_obs[1])**2)


# -----------------------------------------------------------------------
# Bundle adjustment
# -----------------------------------------------------------------------

def run_bundle_adjustment(cameras, pt3d, obs_list, K, max_nfev=3000, f_scale=1.0):
    """Run sparse bundle adjustment.

    obs_list: list of (camera_id, point_id, u, v)
    Returns (cameras_dict, pt3d_dict).
    """
    cam_order = sorted(cameras)
    pt_order = sorted(pt3d)
    pt_idx = {pi: i for i, pi in enumerate(pt_order)}

    # Parameter vector: [cam1_rvec, cam1_t, ..., camN_rvec, camN_t, pt0_xyz, ...]
    n_opt_cams = sum(1 for c in cam_order if c != 0)
    n_opt_pts = len(pt_order)
    params = np.empty(n_opt_cams * 6 + n_opt_pts * 3)
    cam_param_start = {}
    idx = 0
    for ci in cam_order:
        if ci == 0:
            cam_param_start[ci] = None
            continue
        cam_param_start[ci] = idx
        rv, _ = cv2.Rodrigues(cameras[ci]["R"])
        params[idx:idx + 3] = rv.flatten()
        params[idx + 3:idx + 6] = cameras[ci]["t"]
        idx += 6

    pt_offset = idx
    for i, pi in enumerate(pt_order):
        params[pt_offset + i * 3: pt_offset + i * 3 + 3] = pt3d[pi]

    # Filter observations to valid points/cameras
    valid_obs = [(ci, pi, u, v) for ci, pi, u, v in obs_list
                 if pi in pt_idx and ci in cameras]
    if len(valid_obs) < 10:
        return cameras, pt3d

    ba_ci = np.array([o[0] for o in valid_obs], dtype=np.int32)
    ba_pi_l = np.array([pt_idx[o[1]] for o in valid_obs], dtype=np.int32)
    ba_uv = np.array([[o[2], o[3]] for o in valid_obs], dtype=np.float64)
    n_obs = len(valid_obs)

    print(f"  [BA] {len(params)} params, {n_obs * 2} residuals, "
          f"max_nfev={max_nfev}, f_scale={f_scale}")

    def residuals(p):
        cam_R = {0: np.eye(3)}
        cam_t = {0: np.zeros(3)}
        for ci in cam_order:
            if ci == 0:
                continue
            s = cam_param_start[ci]
            R, _ = cv2.Rodrigues(p[s:s + 3])
            cam_R[ci] = R
            cam_t[ci] = p[s + 3:s + 6]

        all_pts = p[pt_offset:].reshape(-1, 3)
        res = np.empty(n_obs * 2)

        for ci_val in cam_order:
            mask = ba_ci == ci_val
            if not np.any(mask):
                continue
            idxs = np.where(mask)[0]
            pi_locals = ba_pi_l[mask]
            obs_uv = ba_uv[mask]
            pts = all_pts[pi_locals]

            pts_cam = (cam_R[ci_val] @ pts.T).T + cam_t[ci_val]
            K_ci = K[ci_val]
            depths = pts_cam[:, 2]
            safe = np.maximum(depths, 1e-8)
            u_proj = K_ci[0, 0] * pts_cam[:, 0] / safe + K_ci[0, 2]
            v_proj = K_ci[1, 1] * pts_cam[:, 1] / safe + K_ci[1, 2]

            res[2 * idxs] = u_proj - obs_uv[:, 0]
            res[2 * idxs + 1] = v_proj - obs_uv[:, 1]

            behind = depths < 0.01
            res[2 * idxs[behind]] = 1e3
            res[2 * idxs[behind] + 1] = 1e3

        return res

    # Jacobian sparsity
    n_params = len(params)
    n_res = n_obs * 2
    jac_sp = lil_matrix((n_res, n_params), dtype=int)
    for j in range(n_obs):
        r0 = 2 * j
        ci_val = int(ba_ci[j])
        pi_l = int(ba_pi_l[j])
        if ci_val != 0:
            s = cam_param_start[ci_val]
            jac_sp[r0, s:s + 6] = 1
            jac_sp[r0 + 1, s:s + 6] = 1
        ps = pt_offset + pi_l * 3
        jac_sp[r0, ps:ps + 3] = 1
        jac_sp[r0 + 1, ps:ps + 3] = 1

    result = least_squares(
        residuals, params,
        jac_sparsity=jac_sp,
        method="trf",
        loss="soft_l1",
        f_scale=f_scale,
        max_nfev=max_nfev,
        verbose=0,
    )
    print(f"  [BA] cost {result.cost:.2f} — {result.message}")

    # Unpack optimised values
    opt = result.x
    new_cameras = {0: {"R": np.eye(3), "t": np.zeros(3)}}
    for ci in cam_order:
        if ci == 0:
            continue
        s = cam_param_start[ci]
        Ropt, _ = cv2.Rodrigues(opt[s:s + 3])
        new_cameras[ci] = {"R": Ropt, "t": opt[s + 3:s + 6].copy()}

    new_pt3d = {}
    for i, pi in enumerate(pt_order):
        xyz = opt[pt_offset + i * 3: pt_offset + i * 3 + 3].copy()
        new_pt3d[pi] = xyz

    return new_cameras, new_pt3d


# -----------------------------------------------------------------------
# Main pipeline
# -----------------------------------------------------------------------

def main():
    intr_data, obs_data = load_data()

    n_cams = obs_data["num_cameras"]
    n_pts = obs_data["num_points"]

    # Build intrinsic matrices
    K = {}
    for c in intr_data["cameras"]:
        K[c["camera_id"]] = build_K(c)

    # Organise observations: obs_by_cam[cam_id][pt_id] = (u, v)
    obs_by_cam = {i: {} for i in range(n_cams)}
    for o in obs_data["observations"]:
        obs_by_cam[o["camera_id"]][o["point_id"]] = np.array(
            [o["u"], o["v"]], dtype=np.float64
        )

    # ==================================================================
    # Step 1 — relative pose of camera 1 w.r.t. camera 0
    # ==================================================================
    shared_01 = sorted(set(obs_by_cam[0]) & set(obs_by_cam[1]))
    pts0 = np.array([obs_by_cam[0][pi] for pi in shared_01])
    pts1 = np.array([obs_by_cam[1][pi] for pi in shared_01])

    pts0_n = normalize_pts(pts0, K[0])
    pts1_n = normalize_pts(pts1, K[1])

    E, mask_e = cv2.findEssentialMat(
        pts0_n, pts1_n,
        focal=1.0, pp=(0.0, 0.0),
        method=cv2.RANSAC,
        prob=0.9999,
        threshold=0.002,
    )
    inlier_mask = mask_e.flatten().astype(bool)

    _, R1, t1, _ = cv2.recoverPose(
        E,
        pts0_n[inlier_mask],
        pts1_n[inlier_mask],
        focal=1.0, pp=(0.0, 0.0),
    )
    R1 = R1.astype(np.float64)
    t1 = t1.flatten().astype(np.float64)

    cameras = {
        0: {"R": np.eye(3), "t": np.zeros(3)},
        1: {"R": R1, "t": t1},
    }

    # ==================================================================
    # Step 2 — triangulate initial 3D points from cameras 0 & 1
    # ==================================================================
    P0_mat = K[0] @ np.hstack([np.eye(3), np.zeros((3, 1))])
    P1_mat = K[1] @ np.hstack([R1, t1.reshape(3, 1)])

    inlier_ids = [shared_01[i] for i in range(len(shared_01)) if inlier_mask[i]]
    inlier_p0 = np.array([obs_by_cam[0][pi] for pi in inlier_ids])
    inlier_p1 = np.array([obs_by_cam[1][pi] for pi in inlier_ids])

    pts4d = cv2.triangulatePoints(P0_mat, P1_mat, inlier_p0.T, inlier_p1.T)
    pts3d_h = (pts4d[:3] / pts4d[3:]).T

    pt3d = {}
    for i, pi in enumerate(inlier_ids):
        pt = pts3d_h[i]
        if pt[2] <= 0:
            continue
        pc1 = R1 @ pt + t1
        if pc1[2] <= 0:
            continue
        # Reject if reprojection error > 3px in either view
        e0 = reproj_error(pt, cameras[0]["R"], cameras[0]["t"], K[0], obs_by_cam[0][pi])
        e1 = reproj_error(pt, cameras[1]["R"], cameras[1]["t"], K[1], obs_by_cam[1][pi])
        if max(e0, e1) < 3.0:
            pt3d[pi] = pt

    print(f"[step2] triangulated {len(pt3d)} initial points from cams 0-1")

    # ==================================================================
    # Step 3 — register cameras 2-4 via PnP-RANSAC + refinement
    # ==================================================================
    for ci in range(2, n_cams):
        common = sorted(set(pt3d) & set(obs_by_cam.get(ci, {})))
        if len(common) < 6:
            print(f"[pnp] camera {ci}: only {len(common)} common pts, skipping")
            continue

        obj = np.array([pt3d[pi] for pi in common], dtype=np.float64)
        img = np.array([obs_by_cam[ci][pi] for pi in common], dtype=np.float64)

        ok, rvec, tvec, inl = cv2.solvePnPRansac(
            obj, img, K[ci], None,
            reprojectionError=4.0,
            confidence=0.9999,
            iterationsCount=5000,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )

        if not ok:
            ok, rvec, tvec, inl = cv2.solvePnPRansac(
                obj, img, K[ci], None,
                reprojectionError=8.0,
                confidence=0.999,
                iterationsCount=10000,
                flags=cv2.SOLVEPNP_EPNP,
            )

        if not ok:
            print(f"[pnp] camera {ci}: FAILED")
            continue

        # Refine on inliers
        if inl is not None and len(inl) >= 6:
            inl_idx = inl.flatten()
            ok2, rvec2, tvec2 = cv2.solvePnP(
                obj[inl_idx], img[inl_idx], K[ci], None,
                rvec=rvec.copy(), tvec=tvec.copy(),
                useExtrinsicGuess=True,
                flags=cv2.SOLVEPNP_ITERATIVE,
            )
            if ok2:
                rvec, tvec = rvec2, tvec2

        Rci, _ = cv2.Rodrigues(rvec)
        cameras[ci] = {"R": Rci, "t": tvec.flatten()}
        n_inl = len(inl) if inl is not None else 0
        print(f"[pnp] camera {ci}: registered with {n_inl} inliers")

    # ==================================================================
    # Step 4 — triangulate all points using multi-view DLT
    # ==================================================================
    for pi in range(n_pts):
        # Gather observations across all registered cameras
        vis = []
        for ci in sorted(cameras):
            if pi in obs_by_cam.get(ci, {}):
                vis.append((ci, obs_by_cam[ci][pi]))
        if len(vis) < 2:
            continue

        # Multi-view DLT: build a 2N x 4 linear system
        A = np.zeros((2 * len(vis), 4))
        for j, (ci, uv) in enumerate(vis):
            R = cameras[ci]["R"]
            t = cameras[ci]["t"]
            P = K[ci] @ np.hstack([R, t.reshape(3, 1)])
            u, v = uv[0], uv[1]
            A[2 * j]     = u * P[2] - P[0]
            A[2 * j + 1] = v * P[2] - P[1]

        _, _, Vt = np.linalg.svd(A)
        X = Vt[-1]
        if abs(X[3]) < 1e-12:
            continue
        X = X[:3] / X[3]

        # Positive depth in all views
        ok = True
        for ci, uv in vis:
            d = (cameras[ci]["R"] @ X + cameras[ci]["t"])[2]
            if d < 0.01:
                ok = False
                break
        if not ok:
            continue

        # Compute reprojection errors and keep only if inlier-dominant
        errors = []
        for ci, uv in vis:
            errors.append(reproj_error(X, cameras[ci]["R"], cameras[ci]["t"], K[ci], uv))
        errors = np.array(errors)

        # Accept if median error is small — outlier obs will be filtered before BA
        if np.median(errors) < 3.0:
            pt3d[pi] = X

    print(f"[step4] total triangulated points: {len(pt3d)}")

    # ==================================================================
    # Step 5 — iterative bundle adjustment with outlier filtering
    # ==================================================================
    def collect_observations(cameras, pt3d, obs_data, K, threshold):
        """Return observation list filtered by current reprojection error."""
        obs = []
        for o in obs_data["observations"]:
            ci, pi = o["camera_id"], o["point_id"]
            if ci not in cameras or pi not in pt3d:
                continue
            err = reproj_error(
                pt3d[pi], cameras[ci]["R"], cameras[ci]["t"], K[ci],
                np.array([o["u"], o["v"]])
            )
            if err < threshold:
                obs.append((ci, pi, o["u"], o["v"]))
        return obs

    def remove_bad_points(cameras, pt3d, obs_by_cam, K, threshold):
        """Remove points whose median reprojection error exceeds threshold."""
        removed = 0
        for pi in list(pt3d.keys()):
            errors = []
            for ci in cameras:
                if pi in obs_by_cam.get(ci, {}):
                    err = reproj_error(
                        pt3d[pi], cameras[ci]["R"], cameras[ci]["t"],
                        K[ci], obs_by_cam[ci][pi]
                    )
                    errors.append(err)
            if errors and np.median(errors) > threshold:
                del pt3d[pi]
                removed += 1
        return removed

    # --- Round 1: broad filter, large f_scale ---
    print("\n=== BA Round 1 ===")
    ba_obs = collect_observations(cameras, pt3d, obs_data, K, threshold=8.0)
    print(f"  observations: {len(ba_obs)}")
    cameras, pt3d = run_bundle_adjustment(
        cameras, pt3d, ba_obs, K, max_nfev=3000, f_scale=2.0
    )
    n_removed = remove_bad_points(cameras, pt3d, obs_by_cam, K, threshold=4.0)
    print(f"  removed {n_removed} bad points -> {len(pt3d)} remain")

    # --- Round 2: moderate filter ---
    print("\n=== BA Round 2 ===")
    ba_obs = collect_observations(cameras, pt3d, obs_data, K, threshold=5.0)
    print(f"  observations: {len(ba_obs)}")
    cameras, pt3d = run_bundle_adjustment(
        cameras, pt3d, ba_obs, K, max_nfev=5000, f_scale=1.0
    )
    n_removed = remove_bad_points(cameras, pt3d, obs_by_cam, K, threshold=3.0)
    print(f"  removed {n_removed} bad points -> {len(pt3d)} remain")

    # --- Round 3: tight filter, final polish ---
    print("\n=== BA Round 3 ===")
    ba_obs = collect_observations(cameras, pt3d, obs_data, K, threshold=3.0)
    print(f"  observations: {len(ba_obs)}")
    cameras, pt3d = run_bundle_adjustment(
        cameras, pt3d, ba_obs, K, max_nfev=5000, f_scale=0.5
    )

    # ==================================================================
    # Step 6 — write output
    # ==================================================================
    final_cameras = []
    final_cameras.append({
        "camera_id": 0,
        "R": np.eye(3).tolist(),
        "t": [0.0, 0.0, 0.0],
    })
    for ci in sorted(cameras):
        if ci == 0:
            continue
        final_cameras.append({
            "camera_id": ci,
            "R": cameras[ci]["R"].tolist(),
            "t": cameras[ci]["t"].tolist(),
        })

    final_points = []
    for pi in sorted(pt3d):
        final_points.append({"point_id": pi, "xyz": pt3d[pi].tolist()})

    output = {"cameras": final_cameras, "points_3d": final_points}

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/reconstruction.json", "w") as f:
        json.dump(output, f, indent=2)

    # Report statistics
    all_errors = []
    for o in obs_data["observations"]:
        ci, pi = o["camera_id"], o["point_id"]
        if ci in cameras and pi in pt3d:
            err = reproj_error(
                pt3d[pi], cameras[ci]["R"], cameras[ci]["t"], K[ci],
                np.array([o["u"], o["v"]])
            )
            all_errors.append(err)
    all_errors = np.array(all_errors)

    print(f"\nFinal reprojection error:")
    print(f"  Mean:   {np.mean(all_errors):.3f} px")
    print(f"  Median: {np.median(all_errors):.3f} px")
    print(f"  Max:    {np.max(all_errors):.3f} px")
    inlier_pct = 100.0 * np.mean(all_errors < 5.0)
    print(f"  <5px:   {inlier_pct:.1f}%")
    print(f"\nOutput: {len(final_cameras)} cameras, {len(final_points)} points")
    print("Written to /app/output/reconstruction.json")


if __name__ == "__main__":
    main()
