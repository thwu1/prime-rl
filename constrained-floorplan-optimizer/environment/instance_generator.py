#!/usr/bin/env python3
"""
Instance generator for the constrained floorplanning task.


Generates 5 test instances with varying block counts and constraint
combinations. Instances include baselines computed from a reference
grid layout (positions NOT stored — only aggregate metrics).
"""

import json
import math
import os
import random


def compute_hpwl_b2b(positions, b2b):
    total = 0.0
    for i, j, w in b2b:
        cx1 = positions[i][0] + positions[i][2] / 2
        cy1 = positions[i][1] + positions[i][3] / 2
        cx2 = positions[j][0] + positions[j][2] / 2
        cy2 = positions[j][1] + positions[j][3] / 2
        total += w * (abs(cx2 - cx1) + abs(cy2 - cy1))
    return total


def compute_hpwl_p2b(positions, p2b, pins):
    total = 0.0
    for pi, bi, w in p2b:
        px, py = pins[pi]
        bx = positions[bi][0] + positions[bi][2] / 2
        by = positions[bi][1] + positions[bi][3] / 2
        total += w * (abs(px - bx) + abs(py - by))
    return total


def compute_bbox_area(positions):
    x_min = min(p[0] for p in positions)
    y_min = min(p[1] for p in positions)
    x_max = max(p[0] + p[2] for p in positions)
    y_max = max(p[1] + p[3] for p in positions)
    return (x_max - x_min) * (y_max - y_min)


def generate_instance(inst_id, n, constraint_config, seed):
    rng = random.Random(seed)

    # Generate target areas
    areas = [round(rng.uniform(8, 35), 2) for _ in range(n)]

    # Compute dimensions (roughly square with slight aspect variation)
    dims = []
    for a in areas:
        aspect = rng.uniform(0.65, 1.55)
        w = math.sqrt(a * aspect)
        h = a / w
        dims.append((round(w, 4), round(h, 4)))

    # Lay out blocks in a compact grid (with small gaps) for baseline
    cols = max(1, math.ceil(math.sqrt(n)))
    max_w = max(d[0] for d in dims)
    max_h = max(d[1] for d in dims)
    spacing_x = max_w + 0.5
    spacing_y = max_h + 0.5

    positions = [None] * n
    for i in range(n):
        row, col = i // cols, i % cols
        w, h = dims[i]
        positions[i] = [round(col * spacing_x, 4), round(row * spacing_y, 4),
                        round(w, 4), round(h, 4)]

    canvas_w = cols * spacing_x
    canvas_h = math.ceil(n / cols) * spacing_y

    # --- Connectivity ---
    b2b = []
    for i in range(n):
        ci = (positions[i][0] + positions[i][2] / 2,
              positions[i][1] + positions[i][3] / 2)
        for j in range(i + 1, n):
            cj = (positions[j][0] + positions[j][2] / 2,
                  positions[j][1] + positions[j][3] / 2)
            dist = math.sqrt((ci[0] - cj[0]) ** 2 + (ci[1] - cj[1]) ** 2)
            threshold = spacing_x * 2.5
            if dist < threshold and rng.random() < 0.35:
                weight = round(rng.uniform(0.5, 3.0), 2)
                b2b.append([i, j, weight])

    # Ensure minimum spanning-tree connectivity
    for i in range(n - 1):
        if not any((e[0] == i and e[1] == i + 1) or
                   (e[0] == i + 1 and e[1] == i) for e in b2b):
            b2b.append([i, i + 1, round(rng.uniform(0.5, 2.0), 2)])

    # Cap edges
    if len(b2b) > n * 4:
        b2b.sort(key=lambda e: e[2], reverse=True)
        b2b = b2b[:n * 4]

    # --- Pins ---
    n_pins = rng.randint(4, max(4, n // 4))
    pins = []
    for p in range(n_pins):
        side = p % 4
        if side == 0:
            pins.append([0, round(rng.uniform(0, canvas_h), 4)])
        elif side == 1:
            pins.append([round(canvas_w, 4), round(rng.uniform(0, canvas_h), 4)])
        elif side == 2:
            pins.append([round(rng.uniform(0, canvas_w), 4), 0])
        else:
            pins.append([round(rng.uniform(0, canvas_w), 4), round(canvas_h, 4)])

    p2b = []
    for p in range(n_pins):
        bi = rng.randint(0, n - 1)
        weight = round(rng.uniform(0.5, 2.0), 2)
        p2b.append([p, bi, weight])

    # --- Constraints ---
    constraints = [[0, 0, 0, 0, 0] for _ in range(n)]
    target_positions = [[-1, -1, -1, -1] for _ in range(n)]
    used = set()

    def pick(count):
        """Pick `count` unused block indices."""
        cands = [i for i in range(n) if i not in used]
        rng.shuffle(cands)
        chosen = cands[:count]
        used.update(chosen)
        return chosen

    if 'fixed' in constraint_config:
        for i in pick(constraint_config['fixed']):
            constraints[i][0] = 1
            _, _, w, h = positions[i]
            target_positions[i] = [-1, -1, w, h]

    if 'preplaced' in constraint_config:
        for i in pick(constraint_config['preplaced']):
            constraints[i][1] = 1
            x, y, w, h = positions[i]
            target_positions[i] = [x, y, w, h]

    if 'boundary' in constraint_config:
        for i in pick(constraint_config['boundary']):
            constraints[i][4] = rng.choice([1, 2, 4, 8])

    if 'mib_groups' in constraint_config:
        gid = 1
        for gs in constraint_config['mib_groups']:
            members = pick(gs)
            shared_area = areas[members[0]]
            w_shared = math.sqrt(shared_area)
            h_shared = shared_area / w_shared
            for m in members:
                areas[m] = round(shared_area, 2)
                constraints[m][2] = gid
                positions[m][2] = round(w_shared, 4)
                positions[m][3] = round(h_shared, 4)
            gid += 1

    if 'cluster_groups' in constraint_config:
        gid = 1
        for gs in constraint_config['cluster_groups']:
            cands = [i for i in range(n) if constraints[i][3] == 0]
            if len(cands) < gs:
                continue
            start = rng.choice(cands)
            members = [start]
            cands.remove(start)
            for _ in range(gs - 1):
                best, best_d = None, float('inf')
                for c in cands:
                    for m in members:
                        cm = (positions[m][0] + positions[m][2] / 2,
                              positions[m][1] + positions[m][3] / 2)
                        cc = (positions[c][0] + positions[c][2] / 2,
                              positions[c][1] + positions[c][3] / 2)
                        d = abs(cm[0] - cc[0]) + abs(cm[1] - cc[1])
                        if d < best_d:
                            best_d = d
                            best = c
                if best is not None:
                    members.append(best)
                    cands.remove(best)
            for m in members:
                constraints[m][3] = gid
            gid += 1

    # --- Baselines ---
    pos_tuples = [tuple(p) for p in positions]
    baseline_hpwl = (compute_hpwl_b2b(pos_tuples, b2b)
                     + compute_hpwl_p2b(pos_tuples, p2b, pins))
    baseline_area = compute_bbox_area(pos_tuples)

    return {
        'id': inst_id,
        'block_count': n,
        'area_targets': [round(a, 4) for a in areas],
        'b2b_connectivity': b2b,
        'p2b_connectivity': p2b,
        'pins_pos': pins,
        'constraints': constraints,
        'target_positions': target_positions,
        'baseline_hpwl': round(baseline_hpwl, 4),
        'baseline_area': round(baseline_area, 4),
    }


def main():
    os.makedirs('/app/instances', exist_ok=True)

    configs = [
        # (id, block_count, constraint_config, seed)
        (0, 15, {}, 1001),
        (1, 22, {'boundary': 4}, 1002),
        (2, 28, {'mib_groups': [3, 3], 'boundary': 3}, 1003),
        (3, 35, {'fixed': 3, 'preplaced': 2, 'boundary': 3}, 1004),
        (4, 48, {'fixed': 3, 'preplaced': 2, 'mib_groups': [3, 3],
                 'cluster_groups': [3, 4], 'boundary': 4}, 1005),
    ]

    for inst_id, n, cfg, seed in configs:
        inst = generate_instance(inst_id, n, cfg, seed)
        path = f'/app/instances/instance_{inst_id}.json'
        with open(path, 'w') as f:
            json.dump(inst, f, indent=2)
        n_b2b = len(inst['b2b_connectivity'])
        print(f'Generated {path}: {n} blocks, {n_b2b} b2b edges, '
              f'baseline HPWL={inst["baseline_hpwl"]:.2f}, '
              f'baseline area={inst["baseline_area"]:.2f}')


if __name__ == '__main__':
    main()
