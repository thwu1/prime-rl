#!/usr/bin/env python3
"""
Generate floorplanning test instances for the VLSI Floorplan Optimization task.
Each instance is deterministic (seeded) and guaranteed to have a feasible solution.

"""

import json
import math
import os
import random


def generate_instance(name, n_blocks, seed, n_fixed=0, n_preplaced=0,
                      n_mib_groups=0, n_cluster_groups=0, n_boundary=0,
                      connectivity_density=0.08):
    rng = random.Random(seed)

    cols = int(math.ceil(math.sqrt(n_blocks)))
    rows = int(math.ceil(n_blocks / cols))
    cell_size = 10.0
    spacing = 0.5

    # Ground truth grid placement (known feasible)
    gt_placement = []
    area_targets = []
    for i in range(n_blocks):
        r = i // cols
        c = i % cols
        w = cell_size * rng.uniform(0.7, 1.3)
        h = cell_size * rng.uniform(0.7, 1.3)
        x = c * (cell_size * 1.2 + spacing)
        y = r * (cell_size * 1.2 + spacing)
        gt_placement.append([round(x, 4), round(y, 4), round(w, 4), round(h, 4)])
        area_targets.append(round(w * h, 4))

    block_types = [0] * n_blocks
    target_dims = [[0.0, 0.0] for _ in range(n_blocks)]
    target_pos = [[0.0, 0.0] for _ in range(n_blocks)]

    # Assign fixed blocks
    indices = list(range(n_blocks))
    rng.shuffle(indices)
    for i in range(min(n_fixed, n_blocks)):
        idx = indices[i]
        block_types[idx] = 1
        target_dims[idx] = [gt_placement[idx][2], gt_placement[idx][3]]

    # Assign preplaced blocks (from remaining soft blocks)
    soft_left = [i for i in indices if block_types[i] == 0]
    for i in range(min(n_preplaced, len(soft_left))):
        idx = soft_left[i]
        block_types[idx] = 2
        target_dims[idx] = [gt_placement[idx][2], gt_placement[idx][3]]
        target_pos[idx] = [gt_placement[idx][0], gt_placement[idx][1]]

    # Generate block-to-block connectivity
    b2b_edges = []
    for i in range(n_blocks):
        ri, ci = i // cols, i % cols
        for j in range(i + 1, n_blocks):
            rj, cj = j // cols, j % cols
            dist = abs(ri - rj) + abs(ci - cj)
            if dist == 1:
                weight = rng.uniform(1.0, 5.0)
                b2b_edges.append([i, j, round(weight, 2)])
            elif dist <= 3 and rng.random() < connectivity_density:
                weight = rng.uniform(0.5, 2.0)
                b2b_edges.append([i, j, round(weight, 2)])

    # Generate pins on the periphery
    bbox_w = cols * (cell_size * 1.2 + spacing)
    bbox_h = rows * (cell_size * 1.2 + spacing)
    n_pins = max(4, n_blocks // 4)
    pin_positions = []
    p2b_edges = []
    for p in range(n_pins):
        side = p % 4
        if side == 0:
            pin_positions.append([0.0, round(rng.uniform(0, bbox_h), 2)])
        elif side == 1:
            pin_positions.append([round(bbox_w, 2), round(rng.uniform(0, bbox_h), 2)])
        elif side == 2:
            pin_positions.append([round(rng.uniform(0, bbox_w), 2), round(bbox_h, 2)])
        else:
            pin_positions.append([round(rng.uniform(0, bbox_w), 2), 0.0])
        for _ in range(rng.randint(1, 2)):
            block = rng.randint(0, n_blocks - 1)
            weight = rng.uniform(1.0, 3.0)
            p2b_edges.append([p, block, round(weight, 2)])

    # MIB groups (blocks with identical dimensions)
    mib_groups = []
    remaining = [i for i in range(n_blocks) if block_types[i] == 0]
    rng.shuffle(remaining)
    pos = 0
    for _ in range(n_mib_groups):
        if pos + 2 > len(remaining):
            break
        sz = rng.randint(2, min(3, len(remaining) - pos))
        group = remaining[pos:pos + sz]
        avg_area = sum(area_targets[i] for i in group) / len(group)
        for idx in group:
            area_targets[idx] = round(avg_area, 4)
        mib_groups.append(group)
        pos += sz

    # Cluster groups (blocks that must abut) — pick grid-adjacent blocks
    used_in_mib = set()
    for g in mib_groups:
        used_in_mib.update(g)
    cluster_cands = [i for i in range(n_blocks)
                     if block_types[i] == 0 and i not in used_in_mib]
    rng.shuffle(cluster_cands)
    cluster_groups = []
    for _ in range(n_cluster_groups):
        if len(cluster_cands) < 2:
            break
        start = cluster_cands.pop(0)
        sr, sc = start // cols, start % cols
        group = [start]
        # Find grid-adjacent candidates
        for _ in range(rng.randint(1, 2)):
            neighbors = [c for c in cluster_cands
                         if abs(c // cols - sr) + abs(c % cols - sc) <= 2]
            if neighbors:
                nb = rng.choice(neighbors)
                group.append(nb)
                cluster_cands.remove(nb)
        if len(group) >= 2:
            cluster_groups.append(group)

    # Boundary constraints
    boundary_constraints = [0] * n_blocks
    bnd_cands = [i for i in range(n_blocks) if block_types[i] == 0]
    rng.shuffle(bnd_cands)
    for i in range(min(n_boundary, len(bnd_cands))):
        idx = bnd_cands[i]
        boundary_constraints[idx] = rng.choice([1, 2, 4, 8])

    # Compute ground truth metrics for baselines
    gt_hpwl = 0.0
    for src, dst, w in b2b_edges:
        cx1 = gt_placement[src][0] + gt_placement[src][2] / 2.0
        cy1 = gt_placement[src][1] + gt_placement[src][3] / 2.0
        cx2 = gt_placement[dst][0] + gt_placement[dst][2] / 2.0
        cy2 = gt_placement[dst][1] + gt_placement[dst][3] / 2.0
        gt_hpwl += w * (abs(cx1 - cx2) + abs(cy1 - cy2))
    for pin_idx, block_idx, w in p2b_edges:
        px, py = pin_positions[pin_idx]
        cx = gt_placement[block_idx][0] + gt_placement[block_idx][2] / 2.0
        cy = gt_placement[block_idx][1] + gt_placement[block_idx][3] / 2.0
        gt_hpwl += w * (abs(px - cx) + abs(py - cy))

    gt_min_x = min(p[0] for p in gt_placement)
    gt_min_y = min(p[1] for p in gt_placement)
    gt_max_x = max(p[0] + p[2] for p in gt_placement)
    gt_max_y = max(p[1] + p[3] for p in gt_placement)
    gt_area = (gt_max_x - gt_min_x) * (gt_max_y - gt_min_y)

    # Baselines at 1.4x ground truth — achievable by a decent optimizer
    baseline_hpwl = round(gt_hpwl * 1.4, 2)
    baseline_area = round(gt_area * 1.4, 2)

    return {
        "name": name,
        "block_count": n_blocks,
        "area_targets": area_targets,
        "block_types": block_types,
        "target_dims": target_dims,
        "target_pos": target_pos,
        "b2b_edges": b2b_edges,
        "p2b_edges": p2b_edges,
        "pin_positions": pin_positions,
        "mib_groups": mib_groups,
        "cluster_groups": cluster_groups,
        "boundary_constraints": boundary_constraints,
        "baseline_hpwl": baseline_hpwl,
        "baseline_area": baseline_area,
    }


def main():
    os.makedirs("/app/instances", exist_ok=True)

    instances = [
        generate_instance("basic_20", 20, seed=42),
        generate_instance("constrained_30", 30, seed=137,
                          n_fixed=3, n_preplaced=2),
        generate_instance("mib_boundary_45", 45, seed=256,
                          n_fixed=4, n_preplaced=2,
                          n_mib_groups=3, n_boundary=5),
        generate_instance("cluster_60", 60, seed=389,
                          n_fixed=5, n_preplaced=3,
                          n_mib_groups=3, n_cluster_groups=4, n_boundary=6),
        generate_instance("full_80", 80, seed=512,
                          n_fixed=6, n_preplaced=4,
                          n_mib_groups=4, n_cluster_groups=5, n_boundary=8,
                          connectivity_density=0.12),
    ]

    for inst in instances:
        path = os.path.join("/app/instances", f"{inst['name']}.json")
        with open(path, "w") as f:
            json.dump(inst, f, indent=2)
        print(f"Generated {path}: {inst['block_count']} blocks, "
              f"{len(inst['b2b_edges'])} b2b edges, "
              f"{len(inst['p2b_edges'])} p2b edges, "
              f"baseline_hpwl={inst['baseline_hpwl']}, "
              f"baseline_area={inst['baseline_area']}")


if __name__ == "__main__":
    main()
