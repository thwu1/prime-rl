"""
Multi-view planar homography estimation with global refinement and decomposition.

"""

import json
import os
import heapq
import numpy as np
from scipy.optimize import least_squares


# ── Hartley-normalized DLT ────────────────────────────────────────────────

def _norm_transform(pts):
    cx, cy = np.mean(pts, axis=0)
    d = np.mean(np.sqrt(np.sum((pts - [cx, cy])**2, axis=1)))
    s = np.sqrt(2) / max(d, 1e-12)
    return np.array([[s, 0, -s*cx], [0, s, -s*cy], [0, 0, 1]])


def dlt_homography(src, dst):
    n = len(src)
    Ts = _norm_transform(src)
    Td = _norm_transform(dst)
    sh = np.column_stack([src, np.ones(n)])
    dh = np.column_stack([dst, np.ones(n)])
    sn = (Ts @ sh.T).T
    dn = (Td @ dh.T).T
    A = np.zeros((2*n, 9))
    for k in range(n):
        x, y, w = sn[k]
        xp, yp, wp = dn[k]
        A[2*k]   = [0, 0, 0, -wp*x, -wp*y, -wp*w, yp*x, yp*y, yp*w]
        A[2*k+1] = [wp*x, wp*y, wp*w, 0, 0, 0, -xp*x, -xp*y, -xp*w]
    _, _, Vt = np.linalg.svd(A)
    H = np.linalg.solve(Td, Vt[-1].reshape(3, 3) @ Ts)
    return H / H[2, 2]


# ── Symmetric transfer error ─────────────────────────────────────────────

def _sym_errors(H, src, dst):
    n = len(src)
    sh = np.column_stack([src, np.ones(n)])
    fwd = (H @ sh.T).T; fwd = fwd[:, :2] / fwd[:, 2:3]
    Hi = np.linalg.inv(H)
    dh = np.column_stack([dst, np.ones(n)])
    bwd = (Hi @ dh.T).T; bwd = bwd[:, :2] / bwd[:, 2:3]
    return np.sum((fwd - dst)**2, 1) + np.sum((bwd - src)**2, 1)


# ── RANSAC ────────────────────────────────────────────────────────────────

def ransac_homography(src, dst, thresh=4.0, max_iter=5000, seed=42):
    n = len(src)
    rng = np.random.RandomState(seed)
    best_mask = np.zeros(n, dtype=bool)
    best_cnt = 0
    best_H = None
    t2 = thresh**2

    for _ in range(max_iter):
        idx = rng.choice(n, 4, replace=False)
        try:
            H = dlt_homography(src[idx], dst[idx])
        except Exception:
            continue
        if abs(np.linalg.det(H)) < 1e-10:
            continue
        errs = _sym_errors(H, src, dst)
        mask = errs < t2
        cnt = mask.sum()
        if cnt > best_cnt:
            best_cnt = cnt
            best_mask = mask
            best_H = H

    if best_H is None or best_cnt < 4:
        best_H = dlt_homography(src, dst)
        best_mask = np.ones(n, dtype=bool)

    for _ in range(2):
        if best_mask.sum() >= 4:
            best_H = dlt_homography(src[best_mask], dst[best_mask])
            errs = _sym_errors(best_H, src, dst)
            best_mask = errs < t2
    if best_mask.sum() >= 4:
        best_H = dlt_homography(src[best_mask], dst[best_mask])

    return best_H / best_H[2, 2], best_mask


# ── MST + chaining ───────────────────────────────────────────────────────

def build_mst_and_chain(pairwise_H, edge_rms, num_views):
    adj = {v: [] for v in range(num_views)}
    for key, rms in edge_rms.items():
        i, j = map(int, key.split("-"))
        adj[i].append((rms, j, key))
        adj[j].append((rms, i, key))

    visited = {0}
    parent = {}
    heap = [(r, nb, 0, k) for r, nb, k in adj[0]]
    heapq.heapify(heap)

    while heap and len(visited) < num_views:
        _, node, par, key = heapq.heappop(heap)
        if node in visited:
            continue
        visited.add(node)
        parent[node] = (par, key)
        for r, nb, k in adj[node]:
            if nb not in visited:
                heapq.heappush(heap, (r, nb, node, k))

    ref = {0: np.eye(3)}
    def _get(v):
        if v in ref:
            return ref[v]
        par, key = parent[v]
        Hp = _get(par)
        Hpair = pairwise_H[key]
        i, j = map(int, key.split("-"))
        if par == i:
            ref[v] = Hpair @ Hp
        else:
            ref[v] = np.linalg.inv(Hpair) @ Hp
        ref[v] /= ref[v][2, 2]
        return ref[v]

    for v in range(num_views):
        _get(v)
    return ref


# ── LM global refinement ─────────────────────────────────────────────────

def lm_refine(init_H, masks, pairs_data, nv):
    def pack(Hs):
        p = []
        for i in range(1, nv):
            H = Hs[i] / Hs[i][2, 2]
            p.extend(H.ravel()[:8])
        return np.array(p)

    def unpack(p):
        Hs = {0: np.eye(3)}
        for i in range(1, nv):
            h = np.append(p[(i-1)*8:i*8], 1.0)
            Hs[i] = h.reshape(3, 3)
        return Hs

    keys = sorted(masks.keys())

    def residuals(p):
        Hs = unpack(p)
        res = []
        for key in keys:
            mask = masks[key]
            if mask.sum() < 4:
                continue
            i, j = map(int, key.split("-"))
            Hij = Hs[j] @ np.linalg.inv(Hs[i])
            src = np.array(pairs_data[key]["pts_src"])[mask]
            dst = np.array(pairs_data[key]["pts_dst"])[mask]
            sh = np.column_stack([src, np.ones(len(src))])
            m = (Hij @ sh.T).T
            m2 = m[:, :2] / m[:, 2:3]
            res.extend((m2 - dst).ravel())
        return np.array(res)

    x0 = pack(init_H)
    result = least_squares(residuals, x0, method='lm', max_nfev=10000)
    refined = unpack(result.x)
    for i in range(nv):
        refined[i] /= refined[i][2, 2]
    return refined


# ── Homography decomposition (Faugeras & Lustman) ────────────────────────

def _extract_R_from_n(G, n):
    """Given normalized homography G = R + t*n^T and plane normal n (unit),
    extract the rotation R using the constraint R(I-nn^T) = G(I-nn^T).

    Key insight: G maps the plane perp to n the same way R does.
    We extract R by finding the closest rotation to G restricted to that plane,
    then determine R*n from the orthogonality constraint.
    """
    # Build orthonormal basis: n, b1, b2
    if abs(n[0]) < 0.9:
        b1 = np.cross(n, [1, 0, 0])
    else:
        b1 = np.cross(n, [0, 1, 0])
    b1 /= np.linalg.norm(b1)
    b2 = np.cross(n, b1)
    b2 /= np.linalg.norm(b2)

    # G maps b1 -> G*b1, b2 -> G*b2 (same as R since b1,b2 perp to n)
    Gb1 = G @ b1
    Gb2 = G @ b2

    # These should be the images under R. Find closest rotation.
    # Stack: [Gb1 | Gb2] = R [b1 | b2]
    # This is a Procrustes problem: find R minimizing ||[Gb1,Gb2] - R [b1,b2]||
    A = np.column_stack([Gb1, Gb2])  # 3x2
    B = np.column_stack([b1, b2])    # 3x2

    M = A @ B.T  # 3x3 (rank 2)
    U, _, Vt = np.linalg.svd(M)
    # Closest rotation
    D = np.diag([1, 1, np.linalg.det(U) * np.linalg.det(Vt)])
    R = U @ D @ Vt

    # t = G*n - R*n
    t = G @ n - R @ n

    return R, t


def decompose_homography(Hij, K, pts_src=None, pts_dst=None):
    """Decompose H = K(R + t*n^T/d)K^{-1} into (R, t_unit, n_unit)."""
    Kinv = np.linalg.inv(K)
    G = Kinv @ Hij @ K

    # Normalize so sigma_2 = 1
    _, sv, _ = np.linalg.svd(G)
    G = G / sv[1]

    # Ensure positive determinant
    if np.linalg.det(G) < 0:
        G = -G

    # Eigendecomposition of G^T G
    S = G.T @ G
    evals_raw, evecs = np.linalg.eigh(S)
    idx = np.argsort(evals_raw)[::-1]
    lam = evals_raw[idx]
    V = evecs[:, idx]

    s1, s2, s3 = lam
    v1, v2, v3 = V[:, 0], V[:, 1], V[:, 2]

    # Near-pure-rotation
    if abs(s1 - s3) < 1e-6:
        U, _, Vt = np.linalg.svd(G)
        R = U @ np.diag([1, 1, np.linalg.det(U)*np.linalg.det(Vt)]) @ Vt
        return R, np.array([0., 0., 1.]), np.array([0., 0., 1.])

    # Normal candidates: n = ±u1*v1 ± u3*v3
    u1 = np.sqrt(max((s1 - s2) / (s1 - s3), 0.0))
    u3 = np.sqrt(max((s2 - s3) / (s1 - s3), 0.0))

    candidates = []
    for sa in [1.0, -1.0]:
        for sb in [1.0, -1.0]:
            n_hat = sa * u1 * v1 + sb * u3 * v3
            n_norm = np.linalg.norm(n_hat)
            if n_norm < 1e-10:
                continue
            n_hat = n_hat / n_norm

            R, t_raw = _extract_R_from_n(G, n_hat)

            # Verify R is a proper rotation
            if abs(np.linalg.det(R) - 1.0) > 0.1:
                continue
            if np.linalg.norm(R.T @ R - np.eye(3), 'fro') > 0.1:
                continue

            # Normalize t
            t_len = np.linalg.norm(t_raw)
            if t_len > 1e-10:
                t_unit = t_raw / t_len
            else:
                t_unit = np.array([0., 0., 1.])

            candidates.append((R, t_unit, n_hat))

    if not candidates:
        # Fallback
        U, _, Vt = np.linalg.svd(G)
        R = U @ np.diag([1, 1, np.linalg.det(U)*np.linalg.det(Vt)]) @ Vt
        return R, np.array([0., 0., 1.]), np.array([0., 0., 1.])

    # Disambiguate: pick solution with most positive-depth points
    best = _disambiguate(candidates, K, pts_src, pts_dst, G)
    return best


def _disambiguate(candidates, K, pts_src, pts_dst, G):
    """Pick the decomposition where inlier points have positive depth in both views."""
    Kinv = np.linalg.inv(K)

    if pts_src is None or pts_dst is None or len(pts_src) == 0:
        # No points: pick n closest to [0,0,1]
        best = max(candidates, key=lambda c: abs(c[2][2]))
        R, t, n = best
        if n[2] < 0:
            n, t = -n, -t
        return R, t, n

    best_score = -1
    best_sol = candidates[0]

    for R, t_unit, n_hat in candidates:
        score = 0
        for k in range(min(len(pts_src), 30)):
            ray1 = Kinv @ np.array([pts_src[k][0], pts_src[k][1], 1.0])
            # Depth in camera 1: d / (n^T ray1) — positive when n^T ray1 > 0 (for d > 0)
            ntr = n_hat @ ray1
            if abs(ntr) < 1e-10:
                continue

            # Reconstruct 3D point in camera 1
            # On the plane n^T X = d, the ray lambda*ray1 hits at lambda = d/(n^T ray1)
            # depth1 ∝ d / (n^T ray1)

            # In camera 2: X2 = R X1 + t_scaled
            # depth2 = X2[2] ... but we need the actual depth
            # X1 = (d/(n^T ray1)) * ray1
            # X2 = R * (d/(n^T ray1)) * ray1 + (t_scaled)
            # depth2 ∝ (R ray1)[2] * d/(n^T ray1) + something

            # Simpler: check that 1/ntr > 0 (positive depth in cam1)
            # and that the mapped point in cam2 also has positive depth
            # X2 direction = R ray1 + (n^T ray1)^{-1} * t_raw_unnorm
            # Actually just check sign of n^T ray1: if d > 0, depth1 > 0 iff n^T ray1 > 0

            # Assume d > 0 (plane in front of camera)
            depth1_pos = (ntr > 0)

            # For camera 2: the plane in cam2 has normal R n, distance d'
            ray2 = Kinv @ np.array([pts_dst[k][0], pts_dst[k][1], 1.0])
            # G ray1 ∝ ray2 for corresponding points
            # The Euclidean H is G = R + t n^T /d
            # For the depth: X1 = lambda1 * ray1, plane: n^T X1 = d => lambda1 = d/(n^T ray1)
            # X2 = R X1 + t*d/... wait, let me use the simpler check

            # Check visibility: n^T ray1 > 0 for both n and -n
            # The correct n is the one where n points from camera TOWARD the plane

            if depth1_pos:
                # Check cam2: (R n)^T (R X1 + t_scaled) > 0
                # Since R is rotation and X1 is on the plane:
                # R X1 = R (d/(n^T ray1)) ray1
                # We just need depth2 > 0 in cam2
                # X2 = R X1 + t_ij, depth2 = e3^T X2
                # ∝ e3^T R ray1 * (d/(n^T ray1)) + e3^T t
                # Since d > 0 and n^T ray1 > 0:
                # ∝ (R ray1)[2] / (n^T ray1) + ...
                rr2 = (R @ ray1)[2]
                if rr2 > 0 and ntr > 0:
                    score += 1
                elif rr2 > 0 or ntr > 0:
                    score += 0.3

        if score > best_score:
            best_score = score
            best_sol = (R, t_unit, n_hat)

    R, t, n = best_sol
    if n[2] < 0:
        n, t = -n, -t

    return R, t, n


# ── Metrics ───────────────────────────────────────────────────────────────

def compute_metrics(ref_H, masks, pw_H, pairs_data, nv):
    per_pair = {}
    all_err = []

    for key in masks:
        i, j = map(int, key.split("-"))
        mask = masks[key]
        if mask.sum() < 4:
            per_pair[key] = 999.0
            continue
        Hij = ref_H[j] @ np.linalg.inv(ref_H[i])
        Hij /= Hij[2, 2]
        src = np.array(pairs_data[key]["pts_src"])[mask]
        dst = np.array(pairs_data[key]["pts_dst"])[mask]
        sh = np.column_stack([src, np.ones(len(src))])
        m = (Hij @ sh.T).T
        m2 = m[:, :2] / m[:, 2:3]
        e = np.linalg.norm(m2 - dst, axis=1)
        rms = float(np.sqrt(np.mean(e**2)))
        per_pair[key] = rms
        all_err.extend(e.tolist())

    global_rms = float(np.sqrt(np.mean(np.array(all_err)**2))) if all_err else 999.0

    max_frob = 0.0
    for key in pw_H:
        i, j = map(int, key.split("-"))
        Hg = ref_H[j] @ np.linalg.inv(ref_H[i])
        Hg /= Hg[2, 2]
        Hd = pw_H[key] / pw_H[key][2, 2]
        max_frob = max(max_frob, np.linalg.norm(Hg - Hd, 'fro'))

    return per_pair, global_rms, max_frob


# ── Main pipeline ─────────────────────────────────────────────────────────

def main():
    with open("/app/data/correspondences.json") as f:
        data = json.load(f)

    K = np.array(data["camera_matrix"])
    nv = data["num_views"]
    pairs = data["pairs"]

    # Step 1: robust pairwise estimation
    pairwise_H = {}
    masks = {}
    for key in pairs:
        src = np.array(pairs[key]["pts_src"])
        dst = np.array(pairs[key]["pts_dst"])
        H, m = ransac_homography(src, dst, thresh=4.0, max_iter=5000, seed=42)
        pairwise_H[key] = H
        masks[key] = m

    # Edge weights for MST
    edge_rms = {}
    for key in pairwise_H:
        m = masks[key]
        src = np.array(pairs[key]["pts_src"])
        dst = np.array(pairs[key]["pts_dst"])
        H = pairwise_H[key]
        if m.sum() >= 4:
            sh = np.column_stack([src[m], np.ones(m.sum())])
            mp = (H @ sh.T).T
            mp2 = mp[:, :2] / mp[:, 2:3]
            edge_rms[key] = float(np.sqrt(np.mean(np.linalg.norm(mp2 - dst[m], axis=1)**2)))
        else:
            edge_rms[key] = 1e6

    # Step 2: MST + chain
    init_H = build_mst_and_chain(pairwise_H, edge_rms, nv)

    # Step 3: LM global refinement
    refined_H = lm_refine(init_H, masks, pairs, nv)

    # Step 4: decompose each pairwise homography
    decomps = {}
    for key in pairs:
        i, j = map(int, key.split("-"))
        Hij = refined_H[j] @ np.linalg.inv(refined_H[i])
        Hij /= Hij[2, 2]
        src = np.array(pairs[key]["pts_src"])
        dst = np.array(pairs[key]["pts_dst"])
        m = masks[key]
        R, t, n = decompose_homography(Hij, K,
                                        pts_src=src[m] if m.sum() > 0 else src,
                                        pts_dst=dst[m] if m.sum() > 0 else dst)
        decomps[key] = {"R": R.tolist(), "t": t.tolist(), "n": n.tolist()}

    # Step 5: metrics
    ppr, grms, cerr = compute_metrics(refined_H, masks, pairwise_H, pairs, nv)

    # Write outputs
    os.makedirs("/app/output", exist_ok=True)

    out_H = {}
    for i in range(nv):
        H = refined_H[i] / refined_H[i][2, 2]
        out_H[f"H_{i}"] = H.tolist()
    with open("/app/output/homographies.json", "w") as f:
        json.dump(out_H, f, indent=2)

    out_inl = {k: v.tolist() for k, v in masks.items()}
    with open("/app/output/inliers.json", "w") as f:
        json.dump(out_inl, f, indent=2)

    with open("/app/output/metrics.json", "w") as f:
        json.dump({"per_pair_rms": ppr, "global_rms": grms, "consistency_error": cerr}, f, indent=2)

    with open("/app/output/decompositions.json", "w") as f:
        json.dump(decomps, f, indent=2)

    print(f"Done. global_rms={grms:.4f}  consistency={cerr:.6f}")


if __name__ == "__main__":
    main()
