#!/usr/bin/env python3
"""
Constrained Floorplan Optimizer — Reference Solution


Simulated Annealing optimizer that handles all five constraint types:
  Hard: overlap-free, area tolerance, fixed/preplaced dimension immutability
  Soft: boundary edge placement, MIB dimension sharing, cluster adjacency

Uses numpy-vectorized overlap computation for efficiency.
"""

import json
import math
import os
import random
import sys
import time

import numpy as np


# ═════════════════════════════════════════════════════════════════════
# CONSTRAINT PARSING
# ═════════════════════════════════════════════════════════════════════

def parse_constraints(inst):
    """Extract constraint sets from an instance."""
    n = inst['block_count']
    cstr = inst['constraints']
    tpos = inst['target_positions']

    fixed = set()
    preplaced = set()
    mib = {}          # gid -> [block indices]
    cluster_g = {}    # gid -> [block indices]
    boundary = {}     # block_idx -> bitmask code
    block_mib = {}    # block_idx -> gid

    for i in range(n):
        if cstr[i][0]:
            fixed.add(i)
        if cstr[i][1]:
            preplaced.add(i)
        if cstr[i][2] > 0:
            mib.setdefault(cstr[i][2], []).append(i)
            block_mib[i] = cstr[i][2]
        if cstr[i][3] > 0:
            cluster_g.setdefault(cstr[i][3], []).append(i)
        if cstr[i][4] > 0:
            boundary[i] = cstr[i][4]

    movable = [i for i in range(n) if i not in preplaced]
    return fixed, preplaced, mib, cluster_g, boundary, block_mib, movable


# ═════════════════════════════════════════════════════════════════════
# COST FUNCTION (numpy-accelerated)
# ═════════════════════════════════════════════════════════════════════

def compute_sa_cost(pos, n, b2b, p2b, pins, areas, cstr, tpos,
                    mib, cluster_g, boundary, fixed, preplaced):
    """Weighted cost for SA acceptance criterion.

    Uses continuous penalties so the SA landscape is smooth.
    """
    x = pos[:, 0]
    y = pos[:, 1]
    w = pos[:, 2]
    h = pos[:, 3]
    xr = x + w
    yt = y + h

    # ── Overlap area (vectorized pairwise) ─────────────────────────
    ox = np.maximum(0, np.minimum(xr[:, None], xr[None, :])
                     - np.maximum(x[:, None], x[None, :]))
    oy = np.maximum(0, np.minimum(yt[:, None], yt[None, :])
                     - np.maximum(y[:, None], y[None, :]))
    overlap_mat = ox * oy
    np.fill_diagonal(overlap_mat, 0)
    total_overlap = overlap_mat.sum() / 2.0

    # ── HPWL ───────────────────────────────────────────────────────
    cx = x + w / 2
    cy = y + h / 2
    hpwl = 0.0
    for e in b2b:
        i, j, wt = int(e[0]), int(e[1]), float(e[2])
        hpwl += wt * (abs(cx[i] - cx[j]) + abs(cy[i] - cy[j]))
    for e in p2b:
        pi, bi, wt = int(e[0]), int(e[1]), float(e[2])
        hpwl += wt * (abs(pins[pi][0] - cx[bi]) + abs(pins[pi][1] - cy[bi]))

    # ── Bounding-box area ──────────────────────────────────────────
    bb_area = float((xr.max() - x.min()) * (yt.max() - y.min()))

    # ── Area tolerance (soft blocks only) ──────────────────────────
    fp = fixed | preplaced
    area_viol = 0.0
    for i in range(n):
        if i in fp:
            continue
        actual = float(w[i] * h[i])
        target = areas[i]
        if target > 0:
            diff = abs(actual - target) / target
            if diff > 0.01:
                area_viol += diff

    # ── Dimension immutability (fixed / preplaced) ─────────────────
    dim_viol = 0.0
    for i in range(n):
        if cstr[i][0] or cstr[i][1]:
            tp = tpos[i]
            if tp[2] != -1 and tp[3] != -1:
                dim_viol += abs(float(w[i]) - tp[2]) + abs(float(h[i]) - tp[3])
            if cstr[i][1] and tp[0] != -1 and tp[1] != -1:
                dim_viol += abs(float(x[i]) - tp[0]) + abs(float(y[i]) - tp[1])

    # ── Boundary distance ──────────────────────────────────────────
    bound_viol = 0.0
    if boundary:
        x_min = float(x.min())
        y_min = float(y.min())
        x_max = float(xr.max())
        y_max = float(yt.max())
        eps = 1e-4
        for idx, code in boundary.items():
            bx, by, bw, bh = float(x[idx]), float(y[idx]), float(w[idx]), float(h[idx])
            if code & 1 and abs(bx - x_min) > eps:
                bound_viol += abs(bx - x_min) + 1
            if code & 2 and abs(bx + bw - x_max) > eps:
                bound_viol += abs(bx + bw - x_max) + 1
            if code & 4 and abs(by + bh - y_max) > eps:
                bound_viol += abs(by + bh - y_max) + 1
            if code & 8 and abs(by - y_min) > eps:
                bound_viol += abs(by - y_min) + 1

    # ── MIB dimension mismatch ─────────────────────────────────────
    mib_viol = 0.0
    for gid, members in mib.items():
        rw, rh = float(w[members[0]]), float(h[members[0]])
        for m in members[1:]:
            mib_viol += abs(float(w[m]) - rw) + abs(float(h[m]) - rh)

    # ── Cluster gap ────────────────────────────────────────────────
    clust_viol = 0.0
    for gid, members in cluster_g.items():
        for ai in range(len(members)):
            a = members[ai]
            for b in members[ai + 1:]:
                ax, ay, aw, ah = float(x[a]), float(y[a]), float(w[a]), float(h[a])
                bx, by, bw, bh = float(x[b]), float(y[b]), float(w[b]), float(h[b])
                dx = max(0, max(ax, bx) - min(ax + aw, bx + bw))
                dy = max(0, max(ay, by) - min(ay + ah, by + bh))
                clust_viol += dx + dy

    return (hpwl
            + 0.01 * bb_area
            + 10000 * total_overlap
            + 5000 * dim_viol
            + 1000 * area_viol
            + 500 * bound_viol
            + 500 * mib_viol
            + 300 * clust_viol)


# ═════════════════════════════════════════════════════════════════════
# POST-PROCESSING: greedy overlap removal
# ═════════════════════════════════════════════════════════════════════

def remove_overlaps(pos, n, preplaced):
    """Greedily push apart overlapping blocks."""
    movable_set = set(range(n)) - preplaced
    for _iteration in range(200):
        moved = False
        for i in sorted(movable_set):
            for j in range(n):
                if i == j:
                    continue
                ox = max(0, min(pos[i, 0] + pos[i, 2], pos[j, 0] + pos[j, 2])
                         - max(pos[i, 0], pos[j, 0]))
                oy = max(0, min(pos[i, 1] + pos[i, 3], pos[j, 1] + pos[j, 3])
                         - max(pos[i, 1], pos[j, 1]))
                if ox > 1e-6 and oy > 1e-6:
                    if ox < oy:
                        shift = ox + 0.01
                        if pos[i, 0] + pos[i, 2] / 2 < pos[j, 0] + pos[j, 2] / 2:
                            pos[i, 0] -= shift
                        else:
                            pos[i, 0] += shift
                    else:
                        shift = oy + 0.01
                        if pos[i, 1] + pos[i, 3] / 2 < pos[j, 1] + pos[j, 3] / 2:
                            pos[i, 1] -= shift
                        else:
                            pos[i, 1] += shift
                    moved = True
        if not moved:
            break

    # Shift so all coordinates are non-negative
    x_min = pos[:, 0].min()
    y_min = pos[:, 1].min()
    if x_min < 0:
        pos[:, 0] -= x_min
    if y_min < 0:
        pos[:, 1] -= y_min


# ═════════════════════════════════════════════════════════════════════
# SOLVER
# ═════════════════════════════════════════════════════════════════════

def solve_instance(inst):
    """Solve a single instance using constrained SA."""
    n = inst['block_count']
    areas = inst['area_targets']
    b2b = inst['b2b_connectivity']
    p2b = inst['p2b_connectivity']
    pins = inst['pins_pos']
    cstr = inst['constraints']
    tpos = inst['target_positions']

    (fixed, preplaced, mib, cluster_g, boundary,
     block_mib, movable) = parse_constraints(inst)

    if not movable:
        return [[tpos[i][0], tpos[i][1], tpos[i][2], tpos[i][3]]
                for i in range(n)]

    # ── Initialize positions ───────────────────────────────────────
    pos = np.zeros((n, 4), dtype=np.float64)

    for i in range(n):
        tp = tpos[i]
        if tp[2] != -1 and tp[3] != -1:
            pos[i, 2] = tp[2]
            pos[i, 3] = tp[3]
        else:
            w = math.sqrt(areas[i])
            pos[i, 2] = w
            pos[i, 3] = areas[i] / w

    # MIB: equalize dimensions within each group
    for gid, members in mib.items():
        avg_a = sum(areas[m] for m in members) / len(members)
        w = math.sqrt(avg_a)
        h = avg_a / w
        for m in members:
            if m not in fixed and m not in preplaced:
                pos[m, 2] = w
                pos[m, 3] = h

    # Place preplaced blocks at their fixed positions
    for i in preplaced:
        pos[i] = [tpos[i][0], tpos[i][1], tpos[i][2], tpos[i][3]]

    # Grid layout for movable blocks
    cols = max(1, math.ceil(math.sqrt(len(movable))))
    max_w = float(max(pos[i, 2] for i in movable))
    max_h = float(max(pos[i, 3] for i in movable))
    sp_x = max_w * 1.6
    sp_y = max_h * 1.6

    # Offset grid to avoid overlap with preplaced blocks
    offset_x = 0.0
    offset_y = 0.0
    if preplaced:
        offset_x = max(tpos[i][0] + tpos[i][2] for i in preplaced) + 1.0

    for rank, i in enumerate(movable):
        row, col = rank // cols, rank % cols
        pos[i, 0] = offset_x + col * sp_x
        pos[i, 1] = offset_y + row * sp_y

    # ── Simulated Annealing ────────────────────────────────────────
    T = 200.0
    alpha = 0.998
    T_min = 0.05
    n_movable = len(movable)

    current_cost = compute_sa_cost(pos, n, b2b, p2b, pins, areas,
                                   cstr, tpos, mib, cluster_g, boundary,
                                   fixed, preplaced)
    best_pos = pos.copy()
    best_cost = current_cost

    while T > T_min:
        for _ in range(n_movable):
            idx = movable[random.randint(0, n_movable - 1)]

            saved = pos[idx].copy()
            saved_others = {}

            r = random.random()

            if r < 0.65:
                # ─── Translate ─────────────────────────────────────
                canvas = max(float(pos[:, 0].max() + pos[:, 2].max()),
                             float(pos[:, 1].max() + pos[:, 3].max()))
                scale = max(0.1, canvas * 0.08 * (T / 200.0 + 0.05))
                pos[idx, 0] = max(0.0, pos[idx, 0] + random.gauss(0, scale))
                pos[idx, 1] = max(0.0, pos[idx, 1] + random.gauss(0, scale))

            elif r < 0.82 and idx not in fixed:
                # ─── Resize (area-preserving) ──────────────────────
                area = areas[idx]
                aspect = random.uniform(0.4, 2.5)
                w = math.sqrt(area * aspect)
                h = area / w
                pos[idx, 2] = w
                pos[idx, 3] = h
                # MIB: apply same shape to all group members
                if idx in block_mib:
                    for m in mib[block_mib[idx]]:
                        if m != idx and m not in fixed and m not in preplaced:
                            saved_others[m] = pos[m].copy()
                            pos[m, 2] = w
                            pos[m, 3] = h

            else:
                # ─── Position swap ─────────────────────────────────
                other = movable[random.randint(0, n_movable - 1)]
                if other != idx:
                    saved_others[other] = pos[other].copy()
                    ox, oy = float(pos[other, 0]), float(pos[other, 1])
                    pos[other, 0] = float(saved[0])
                    pos[other, 1] = float(saved[1])
                    pos[idx, 0] = ox
                    pos[idx, 1] = oy

            new_cost = compute_sa_cost(pos, n, b2b, p2b, pins, areas,
                                       cstr, tpos, mib, cluster_g,
                                       boundary, fixed, preplaced)
            delta = new_cost - current_cost

            if delta < 0 or random.random() < math.exp(-delta / max(T, 1e-10)):
                current_cost = new_cost
                if current_cost < best_cost:
                    best_cost = current_cost
                    best_pos = pos.copy()
            else:
                pos[idx] = saved
                for m, s in saved_others.items():
                    pos[m] = s

        T *= alpha

    # ── Post-processing ────────────────────────────────────────────
    pos = best_pos.copy()
    remove_overlaps(pos, n, preplaced)

    return pos.tolist()


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def main():
    inst_dir = '/app/instances'
    sol_dir = '/app/solutions'
    os.makedirs(sol_dir, exist_ok=True)

    for fname in sorted(os.listdir(inst_dir)):
        if not fname.endswith('.json'):
            continue
        with open(os.path.join(inst_dir, fname)) as f:
            inst = json.load(f)

        iid = inst['id']
        n = inst['block_count']
        t0 = time.time()
        print(f'Solving instance {iid} ({n} blocks)...', end=' ', flush=True)

        random.seed(42 + iid)
        np.random.seed(42 + iid)

        positions = solve_instance(inst)

        elapsed = time.time() - t0
        sol = {'instance_id': iid, 'positions': positions}
        sol_path = os.path.join(sol_dir, f'solution_{iid}.json')
        with open(sol_path, 'w') as f:
            json.dump(sol, f)
        print(f'done in {elapsed:.1f}s')


if __name__ == '__main__':
    main()
