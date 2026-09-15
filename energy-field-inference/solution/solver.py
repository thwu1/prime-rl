#!/usr/bin/env python3

"""
Robust solver for Lux AI S3 energy field inference.

Strategy:
  1. Vectorized exhaustive position search with linearized parameter fitting:
     - Type 0 (sin): freq grid search + closed-form 2-var linear LS
     - Type 1 (rational): direct closed-form 2-var linear LS
  2. Greedy beam search over top candidates per pair.
  3. Joint Nelder-Mead refinement with multiple random starts.
  4. Local position refinement (coordinate descent, +/-2 cells).
  5. Fallback: alternate function-type assignments.
"""

import json
import os
import numpy as np
from scipy.optimize import minimize

MAP_W = 24
MAP_H = 24
MAX_NODES = 6
MIN_E = -20
MAX_E = 20

_X, _Y = np.meshgrid(np.arange(MAP_W), np.arange(MAP_H))
MM = np.stack([_X, _Y]).T.astype(np.float64)  # (W, H, 2); MM[a,b]=[a,b]


# ------------------------------------------------------------------ #
#  Forward model (must match engine / test exactly)                   #
# ------------------------------------------------------------------ #

def compute_field(positions, fn_types, fn_params, masks):
    contributions = np.zeros((MAX_NODES, MAP_W, MAP_H), dtype=np.float64)
    for n in range(MAX_NODES):
        if not masks[n]:
            continue
        pos = np.array(positions[n], dtype=np.float64)
        diff = MM - pos
        dist = np.sqrt(diff[..., 0] ** 2 + diff[..., 1] ** 2)
        x, y, z = fn_params[n]
        if fn_types[n] == 0:
            contributions[n] = np.sin(dist * x + y) * z
        else:
            contributions[n] = (x / (dist + 1) + y) * z
    mean_val = contributions.mean()
    if mean_val < 0.25:
        contributions += 0.25 - mean_val
    return np.clip(np.round(contributions.sum(axis=0)).astype(int),
                   MIN_E, MAX_E)


# ------------------------------------------------------------------ #
#  Helpers                                                            #
# ------------------------------------------------------------------ #

def precompute_distances(obs_x, obs_y):
    """dp_all[px,py,k] = dist( (px,py), obs_k ).
       dm_all[px,py,k] = dist( mirror(px,py), obs_k ).
       Mirror rule: (px,py) -> (23-py, 23-px).
    """
    px = np.arange(MAP_W, dtype=np.float64)[:, None, None]
    py = np.arange(MAP_H, dtype=np.float64)[None, :, None]
    ox = obs_x[None, None, :]
    oy = obs_y[None, None, :]
    dp = np.sqrt((ox - px) ** 2 + (oy - py) ** 2)
    mpx = 23.0 - np.arange(MAP_H, dtype=np.float64)[None, :, None]
    mpy = 23.0 - np.arange(MAP_W, dtype=np.float64)[:, None, None]
    dm = np.sqrt((ox - mpx) ** 2 + (oy - mpy) ** 2)
    return dp, dm


def predict_pair(dp, dm, ft, params):
    x, y, z = params
    if ft == 0:
        return np.sin(dp * x + y) * z + np.sin(dm * x + y) * z
    return (x / (dp + 1) + y) * z + (x / (dm + 1) + y) * z


def build_config(pos_l, ft_l, cont, n_pairs):
    positions = [(0, 0)] * MAX_NODES
    fn_types = [0] * MAX_NODES
    fn_par = [(0.0, 0.0, 0.0)] * MAX_NODES
    masks = [False] * MAX_NODES
    for i in range(n_pairs):
        px, py = pos_l[i]
        positions[i] = (px, py)
        fn_types[i] = ft_l[i]
        fn_par[i] = (float(cont[i * 3]),
                     float(cont[i * 3 + 1]),
                     float(cont[i * 3 + 2]))
        masks[i] = True
        mi = i + 3
        positions[mi] = (23 - py, 23 - px)
        fn_types[mi] = ft_l[i]
        fn_par[mi] = fn_par[i]
        masks[mi] = True
    return positions, fn_types, fn_par, masks


# ------------------------------------------------------------------ #
#  Vectorized exhaustive search (linearized parameter fitting)        #
# ------------------------------------------------------------------ #

def search_type0(dp_all, dm_all, residual, freq_grid):
    """Type-0 (sinusoidal) search over all (px,py) positions.

    For fixed frequency f the pair contribution is linearised as:
        A*(sin(dp*f)+sin(dm*f)) + B*(cos(dp*f)+cos(dm*f))
    with A = z*cos(y), B = z*sin(y).  Solved by closed-form 2x2 LS.

    Returns  best_mse (W,H),  params (W,H,3) = (freq, phase, amplitude).
    """
    N = len(residual)
    sum_r2 = np.sum(residual ** 2)
    r = residual[None, None, :]

    best_mse = np.full((MAP_W, MAP_H), np.inf)
    best_A = np.zeros((MAP_W, MAP_H))
    best_B = np.zeros((MAP_W, MAP_H))
    best_f = np.zeros((MAP_W, MAP_H))

    for f in freq_grid:
        S = np.sin(dp_all * f) + np.sin(dm_all * f)
        C = np.cos(dp_all * f) + np.cos(dm_all * f)
        SS = (S * S).sum(-1)
        SC = (S * C).sum(-1)
        CC = (C * C).sum(-1)
        Sr = (S * r).sum(-1)
        Cr = (C * r).sum(-1)

        det = SS * CC - SC * SC
        ok = np.abs(det) > 1e-12
        d = np.where(ok, det, 1.0)
        A = np.where(ok, (CC * Sr - SC * Cr) / d, 0.0)
        B = np.where(ok, (SS * Cr - SC * Sr) / d, 0.0)

        mse = (sum_r2 - 2 * (A * Sr + B * Cr)
               + A * A * SS + 2 * A * B * SC + B * B * CC) / N
        mse = np.where(ok, np.maximum(mse, 0.0), np.inf)

        better = mse < best_mse
        best_mse = np.where(better, mse, best_mse)
        best_A = np.where(better, A, best_A)
        best_B = np.where(better, B, best_B)
        best_f = np.where(better, f, best_f)

    z = np.sqrt(best_A ** 2 + best_B ** 2)
    y = np.arctan2(best_B, best_A)
    return best_mse, np.stack([best_f, y, z], axis=-1)


def search_type1(dp_all, dm_all, residual):
    """Type-1 (rational) search over all (px,py) positions.

    Pair contribution = a*(1/(dp+1)+1/(dm+1)) + c   (a=xz, c=2yz).
    Closed-form 2x2 LS.

    Returns  best_mse (W,H),  params (W,H,3) = (x, y, z) with z=1.
    """
    N = len(residual)
    F = 1.0 / (dp_all + 1) + 1.0 / (dm_all + 1)
    r = residual[None, None, :]
    sr = residual.sum()
    sr2 = np.sum(residual ** 2)

    FF = (F * F).sum(-1)
    F1 = F.sum(-1)
    Fr = (F * r).sum(-1)

    det = FF * N - F1 * F1
    ok = np.abs(det) > 1e-12
    d = np.where(ok, det, 1.0)
    a = np.where(ok, (N * Fr - F1 * sr) / d, 0.0)
    c = np.where(ok, (FF * sr - F1 * Fr) / d, 0.0)

    mse = (sr2 - 2 * (a * Fr + c * sr)
           + a * a * FF + 2 * a * c * F1 + c * c * N) / N
    mse = np.where(ok, np.maximum(mse, 0.0), np.inf)

    # Decompose: z=1, x=a, y=c/2
    return mse, np.stack([a, c / 2, np.ones_like(a)], axis=-1)


def top_k(mse0, p0, mse1, p1, K):
    """Merge both types and return top-K candidates by MSE."""
    entries = []
    for px in range(MAP_W):
        for py in range(MAP_H):
            m0 = float(mse0[px, py])
            if np.isfinite(m0):
                entries.append((m0, px, py, 0,
                                (float(p0[px, py, 0]),
                                 float(p0[px, py, 1]),
                                 float(p0[px, py, 2]))))
            m1 = float(mse1[px, py])
            if np.isfinite(m1):
                entries.append((m1, px, py, 1,
                                (float(p1[px, py, 0]),
                                 float(p1[px, py, 1]),
                                 float(p1[px, py, 2]))))
    entries.sort()
    seen, out = set(), []
    for e in entries:
        k = (e[1], e[2], e[3])
        if k not in seen:
            seen.add(k)
            out.append(e)
            if len(out) >= K:
                break
    return out


# ------------------------------------------------------------------ #
#  Main solver                                                        #
# ------------------------------------------------------------------ #

def solve_scenario(data):
    n_pairs = data["num_active_node_pairs"]
    obs = data["observations"]
    ox = np.array([o["x"] for o in obs], dtype=np.float64)
    oy = np.array([o["y"] for o in obs], dtype=np.float64)
    oe = np.array([o["energy"] for o in obs], dtype=np.float64)
    oxi, oyi = ox.astype(int), oy.astype(int)

    freq_grid = np.arange(0.05, 4.0, 0.015)
    dp_all, dm_all = precompute_distances(ox, oy)

    beams = {1: [1], 2: [10, 1], 3: [8, 4, 1]}[n_pairs]

    def obj(cont, pl, fl):
        pos, fnt, fnp, msk = build_config(pl, fl, cont, n_pairs)
        fld = compute_field(pos, fnt, fnp, msk)
        return float(np.mean((fld[oxi, oyi].astype(np.float64) - oe) ** 2))

    # ---------- Phase 1: greedy beam search ----------
    partials = [([], [], [])]          # (pos_list, ft_list, params_list)
    for depth in range(n_pairs):
        bw = beams[depth]
        nxt = []
        for pl, fl, prl in partials:
            residual = oe.copy()
            for i in range(depth):
                ppx, ppy = pl[i]
                residual -= predict_pair(dp_all[ppx, ppy],
                                         dm_all[ppx, ppy],
                                         fl[i], prl[i])
            m0, p0 = search_type0(dp_all, dm_all, residual, freq_grid)
            m1, p1 = search_type1(dp_all, dm_all, residual)
            for _, cpx, cpy, cft, cpar in top_k(m0, p0, m1, p1, bw):
                nxt.append((pl + [(cpx, cpy)],
                            fl + [cft],
                            prl + [cpar]))
        partials = nxt
        print(f"  Depth {depth + 1}/{n_pairs}: {len(partials)} candidates",
              flush=True)

    # ---------- Phase 2: pre-score & refine ----------
    scored = []
    for pl, fl, prl in partials:
        x0 = np.concatenate([list(p) for p in prl])
        scored.append((obj(x0, pl, fl), pl, fl, x0))
    scored.sort()
    n_ref = min(15, len(scored))
    print(f"  Refining top {n_ref} of {len(scored)} ...", flush=True)

    best_mse, best_cfg = np.inf, None
    for _, pl, fl, x0 in scored[:n_ref]:
        starts = [x0]
        for s in range(4):
            rng = np.random.RandomState(42 + s)
            starts.append(x0 + rng.randn(len(x0)) * 0.3)
        for st in starts:
            try:
                r = minimize(lambda p, _p=pl, _f=fl: obj(p, _p, _f),
                             st, method="Nelder-Mead",
                             options={"maxiter": 12000,
                                      "xatol": 1e-9, "fatol": 1e-11})
                if r.fun < best_mse:
                    best_mse = r.fun
                    best_cfg = (list(pl), list(fl), r.x.copy())
            except Exception:
                pass
    print(f"  MSE after refinement: {best_mse:.6f}", flush=True)

    # ---------- Phase 3: local position refinement ----------
    if best_mse > 0.01:
        pl, fl, cont = best_cfg
        pl = list(pl)
        changed = True
        while changed:
            changed = False
            best_imp = None            # (mse, pair_idx, new_px, new_py)
            for i in range(n_pairs):
                bpx, bpy = pl[i]
                for dx in range(-2, 3):
                    for dy in range(-2, 3):
                        if dx == 0 and dy == 0:
                            continue
                        npx, npy = bpx + dx, bpy + dy
                        if 0 <= npx < MAP_W and 0 <= npy < MAP_H:
                            npl = list(pl)
                            npl[i] = (npx, npy)
                            m = obj(cont, npl, fl)
                            if m < best_mse - 1e-6:
                                if best_imp is None or m < best_imp[0]:
                                    best_imp = (m, i, npx, npy)
            if best_imp is not None:
                m, i, npx, npy = best_imp
                pl[i] = (npx, npy)
                best_mse = m
                changed = True

        if pl != best_cfg[0]:
            try:
                r = minimize(lambda p, _p=pl, _f=fl: obj(p, _p, _f),
                             cont, method="Nelder-Mead",
                             options={"maxiter": 10000,
                                      "xatol": 1e-9, "fatol": 1e-11})
                if r.fun < best_mse:
                    best_mse = r.fun
                    cont = r.x.copy()
            except Exception:
                pass
        best_cfg = (pl, fl, cont)
        print(f"  MSE after pos-refine: {best_mse:.6f}", flush=True)

    # ---------- Phase 4: alternate function-type assignments ----------
    if best_mse > 0.5:
        print("  Trying alternate function types ...", flush=True)
        from itertools import product as iprod
        pl, fl, cont = best_cfg
        for combo in iprod([0, 1], repeat=n_pairs):
            alt = list(combo)
            if alt == fl:
                continue
            for seed in [42, 137, 271, 500]:
                rng = np.random.RandomState(seed)
                x0 = cont + rng.randn(len(cont)) * 0.5
                try:
                    r = minimize(
                        lambda p, _p=pl, _a=alt: obj(p, _p, _a),
                        x0, method="Nelder-Mead",
                        options={"maxiter": 8000})
                    if r.fun < best_mse:
                        best_mse = r.fun
                        best_cfg = (pl, alt, r.x.copy())
                except Exception:
                    pass
        print(f"  MSE after alt-types: {best_mse:.6f}", flush=True)

    # ---------- Build final field ----------
    pl, fl, cont = best_cfg
    pos, fnt, fnp, msk = build_config(pl, fl, cont, n_pairs)
    return compute_field(pos, fnt, fnp, msk)


def main():
    os.makedirs("/app/results", exist_ok=True)
    for i in range(1, 6):
        print(f"Solving scenario {i} ...", flush=True)
        with open(f"/app/data/scenario_{i}.json") as f:
            data = json.load(f)
        field = solve_scenario(data)
        with open(f"/app/results/scenario_{i}.json", "w") as f:
            json.dump({"energy_field": field.tolist()}, f)
        print(f"Scenario {i} done — range [{field.min()}, {field.max()}]",
              flush=True)
    print("All scenarios complete.", flush=True)


if __name__ == "__main__":
    main()
