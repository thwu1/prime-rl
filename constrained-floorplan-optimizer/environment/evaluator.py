#!/usr/bin/env python3
"""
Floorplan Evaluator — Standalone evaluation engine for constrained floorplanning.


Evaluates placement solutions against instance specifications using
the ICCAD contest cost formula with hard/soft constraint checking.

Can be used as a library (import evaluate_solution, compute_total_score)
or from the command line:
    python3 evaluator.py --instance instances/instance_0.json --solution solutions/solution_0.json
    python3 evaluator.py --all --solution-dir solutions/
"""

import json
import math
import os
import sys
from typing import List, Tuple, Dict, Optional, Set

# =============================================================================
# CONTEST PARAMETERS
# =============================================================================
ALPHA = 0.5        # Quality metrics weight
BETA = 2.0         # Violation penalty exponent
M_PENALTY = 10.0   # Infeasibility penalty
AREA_TOLERANCE = 0.01  # 1% area tolerance


# =============================================================================
# WIRELENGTH AND AREA METRICS
# =============================================================================
def calculate_hpwl_b2b(positions, b2b_connectivity):
    """Calculate weighted block-to-block HPWL (centroid Manhattan distance)."""
    total_wl = 0.0
    for edge in b2b_connectivity:
        i, j, weight = int(edge[0]), int(edge[1]), float(edge[2])
        if i < len(positions) and j < len(positions):
            cx1 = positions[i][0] + positions[i][2] / 2
            cy1 = positions[i][1] + positions[i][3] / 2
            cx2 = positions[j][0] + positions[j][2] / 2
            cy2 = positions[j][1] + positions[j][3] / 2
            total_wl += weight * (abs(cx2 - cx1) + abs(cy2 - cy1))
    return total_wl


def calculate_hpwl_p2b(positions, p2b_connectivity, pins_pos):
    """Calculate weighted pin-to-block HPWL."""
    total_wl = 0.0
    for edge in p2b_connectivity:
        pin_idx, block_idx, weight = int(edge[0]), int(edge[1]), float(edge[2])
        if block_idx < len(positions) and pin_idx < len(pins_pos):
            px, py = float(pins_pos[pin_idx][0]), float(pins_pos[pin_idx][1])
            bx = positions[block_idx][0] + positions[block_idx][2] / 2
            by = positions[block_idx][1] + positions[block_idx][3] / 2
            total_wl += weight * (abs(px - bx) + abs(py - by))
    return total_wl


def calculate_bbox_area(positions):
    """Calculate bounding box area of all placed blocks."""
    if not positions:
        return 0.0
    x_min = min(p[0] for p in positions)
    y_min = min(p[1] for p in positions)
    x_max = max(p[0] + p[2] for p in positions)
    y_max = max(p[1] + p[3] for p in positions)
    return (x_max - x_min) * (y_max - y_min)


# =============================================================================
# HARD CONSTRAINT CHECKS (violation → infeasible, cost = M)
# =============================================================================
def check_overlap(positions):
    """Count overlapping block pairs (touching edges OK)."""
    violations = 0
    n = len(positions)
    for i in range(n):
        for j in range(i + 1, n):
            x1, y1, w1, h1 = positions[i]
            x2, y2, w2, h2 = positions[j]
            overlap_x = max(0, min(x1 + w1, x2 + w2) - max(x1, x2))
            overlap_y = max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
            if overlap_x > 1e-6 and overlap_y > 1e-6:
                violations += 1
    return violations


def check_area_tolerance(positions, target_areas, skip_indices=None,
                         tolerance=AREA_TOLERANCE):
    """Check if soft-block areas are within tolerance of targets."""
    violations = 0
    for i, (x, y, w, h) in enumerate(positions):
        if skip_indices and i in skip_indices:
            continue
        target = target_areas[i]
        if target <= 0:
            continue
        actual = w * h
        diff = abs(actual - target) / target
        if diff > tolerance:
            violations += 1
    return violations


def check_dimension_hard_constraints(positions, target_positions, constraints,
                                     block_count, tolerance=1e-4):
    """Check fixed-shape and preplaced dimension/location immutability."""
    violations = 0
    for i in range(min(block_count, len(positions), len(target_positions))):
        is_fixed = constraints[i][0] != 0
        is_preplaced = constraints[i][1] != 0
        if not (is_fixed or is_preplaced):
            continue

        px, py, pw, ph = positions[i]
        tx, ty, tw, th = target_positions[i]

        if tw == -1 or th == -1:
            continue

        if abs(pw - tw) > tolerance or abs(ph - th) > tolerance:
            violations += 1
            continue

        if is_preplaced and tx != -1 and ty != -1:
            if abs(px - tx) > tolerance or abs(py - ty) > tolerance:
                violations += 1

    return violations


# =============================================================================
# SOFT CONSTRAINT CHECKS (violations → exponential penalty)
# =============================================================================
def check_boundary_violations(positions, constraints, block_count):
    """Count blocks that don't touch their required bounding-box edge(s).

    Encoding: bitmask 1=left, 2=right, 4=top, 8=bottom.
    """
    if not any(constraints[i][4] != 0 for i in range(block_count)):
        return 0

    x_min_bb = min(p[0] for p in positions)
    y_min_bb = min(p[1] for p in positions)
    x_max_bb = max(p[0] + p[2] for p in positions)
    y_max_bb = max(p[1] + p[3] for p in positions)
    eps = 1e-4

    violations = 0
    for i in range(block_count):
        code = int(constraints[i][4])
        if code == 0:
            continue
        bx, by, bw, bh = positions[i]
        touches = {
            1: abs(bx - x_min_bb) < eps,
            2: abs(bx + bw - x_max_bb) < eps,
            4: abs(by + bh - y_max_bb) < eps,
            8: abs(by - y_min_bb) < eps,
        }
        if not all(touches[bit] for bit in (1, 2, 4, 8) if code & bit):
            violations += 1
    return violations


def check_mib_violations(positions, constraints, block_count):
    """Count MIB violations: distinct (w,h) pairs minus 1 per group."""
    groups = {}
    for i in range(block_count):
        gid = int(constraints[i][2])
        if gid > 0:
            groups.setdefault(gid, []).append(i)

    violations = 0
    for gid, indices in groups.items():
        distinct = set()
        for i in indices:
            bw = round(positions[i][2], 4)
            bh = round(positions[i][3], 4)
            distinct.add((bw, bh))
        violations += len(distinct) - 1
    return violations


def check_cluster_violations(positions, constraints, block_count):
    """Count cluster violations: connected components minus 1 per group.

    Two blocks are adjacent iff they share an edge segment (touch along
    one axis with non-zero overlap along the other).
    """
    groups = {}
    for i in range(block_count):
        gid = int(constraints[i][3])
        if gid > 0:
            groups.setdefault(gid, []).append(i)

    violations = 0
    eps = 1e-4
    for gid, indices in groups.items():
        adj = {i: set() for i in indices}
        for a_idx, a in enumerate(indices):
            for b in indices[a_idx + 1:]:
                ax, ay, aw, ah = positions[a]
                bx, by, bw, bh = positions[b]
                h_touch = (abs(ax + aw - bx) < eps or abs(bx + bw - ax) < eps)
                v_touch = (abs(ay + ah - by) < eps or abs(by + bh - ay) < eps)
                h_overlap = min(ax + aw, bx + bw) - max(ax, bx) > eps
                v_overlap = min(ay + ah, by + bh) - max(ay, by) > eps
                if (h_touch and v_overlap) or (v_touch and h_overlap):
                    adj[a].add(b)
                    adj[b].add(a)

        visited = set()
        components = 0
        for start in indices:
            if start in visited:
                continue
            components += 1
            queue = [start]
            visited.add(start)
            while queue:
                node = queue.pop(0)
                for nbr in adj[node]:
                    if nbr not in visited:
                        visited.add(nbr)
                        queue.append(nbr)
        violations += components - 1
    return violations


def compute_max_soft_violations(constraints, block_count):
    """Compute N_soft: max possible soft violations (normalization denominator)."""
    n_soft = 0
    for i in range(block_count):
        if constraints[i][4] != 0:
            n_soft += 1

    mib_groups = {}
    for i in range(block_count):
        gid = int(constraints[i][2])
        if gid > 0:
            mib_groups.setdefault(gid, []).append(i)
    for indices in mib_groups.values():
        n_soft += max(0, len(indices) - 1)

    cluster_groups = {}
    for i in range(block_count):
        gid = int(constraints[i][3])
        if gid > 0:
            cluster_groups.setdefault(gid, []).append(i)
    for indices in cluster_groups.values():
        n_soft += max(0, len(indices) - 1)

    return n_soft


# =============================================================================
# COST AND SCORING
# =============================================================================
def compute_cost(hpwl_gap, area_gap, violations_relative, is_feasible):
    """Compute ICCAD contest cost (RuntimeFactor fixed at 1.0 for local eval)."""
    if not is_feasible:
        return M_PENALTY
    quality = 1 + ALPHA * (max(0, hpwl_gap) + max(0, area_gap))
    violation = math.exp(BETA * violations_relative)
    return min(quality * violation, M_PENALTY - 1e-6)


def compute_total_score(costs, block_counts):
    """Exponentially weighted average: Total = Σ C_i·e^(n_i/12) / Σ e^(n_j/12)."""
    if not costs:
        return 0.0
    max_n = max(block_counts)
    weights = [math.exp((n - max_n) / 12) for n in block_counts]
    total_w = sum(weights)
    return sum(c * w for c, w in zip(costs, weights)) / total_w


def evaluate_solution(instance, positions):
    """Evaluate a solution against an instance. Returns a dict of metrics."""
    block_count = instance['block_count']
    area_targets = instance['area_targets']
    b2b = instance['b2b_connectivity']
    p2b = instance['p2b_connectivity']
    pins = instance['pins_pos']
    constraints = instance['constraints']
    target_positions = instance['target_positions']
    baseline_hpwl = instance['baseline_hpwl']
    baseline_area = instance['baseline_area']

    if len(positions) != block_count:
        return {
            'error': f'Expected {block_count} positions, got {len(positions)}',
            'is_feasible': False, 'cost': M_PENALTY,
        }

    # Identify fixed/preplaced for area-tolerance exclusion
    fixed_or_preplaced = set()
    for i in range(block_count):
        if constraints[i][0] != 0 or constraints[i][1] != 0:
            fixed_or_preplaced.add(i)

    # Hard constraints
    overlap_v = check_overlap(positions)
    area_v = check_area_tolerance(positions, area_targets,
                                  skip_indices=fixed_or_preplaced)
    dim_v = check_dimension_hard_constraints(positions, target_positions,
                                             constraints, block_count)
    is_feasible = (overlap_v == 0 and area_v == 0 and dim_v == 0)

    # Soft constraints
    boundary_v = check_boundary_violations(positions, constraints, block_count)
    mib_v = check_mib_violations(positions, constraints, block_count)
    cluster_v = check_cluster_violations(positions, constraints, block_count)

    total_soft = boundary_v + mib_v + cluster_v
    max_soft = compute_max_soft_violations(constraints, block_count)
    v_rel = total_soft / max(max_soft, 1)

    # Quality metrics
    hpwl_b2b = calculate_hpwl_b2b(positions, b2b)
    hpwl_p2b = calculate_hpwl_p2b(positions, p2b, pins)
    hpwl_total = hpwl_b2b + hpwl_p2b
    bbox_area = calculate_bbox_area(positions)

    hpwl_gap = (hpwl_total - baseline_hpwl) / max(baseline_hpwl, 1e-6)
    area_gap = (bbox_area - baseline_area) / max(baseline_area, 1e-6)

    cost = compute_cost(hpwl_gap, area_gap, v_rel, is_feasible)

    return {
        'is_feasible': is_feasible,
        'overlap_violations': overlap_v,
        'area_violations': area_v,
        'dimension_violations': dim_v,
        'boundary_violations': boundary_v,
        'mib_violations': mib_v,
        'cluster_violations': cluster_v,
        'total_soft_violations': total_soft,
        'max_soft_violations': max_soft,
        'v_rel': v_rel,
        'hpwl_total': hpwl_total,
        'baseline_hpwl': baseline_hpwl,
        'hpwl_gap': hpwl_gap,
        'bbox_area': bbox_area,
        'baseline_area': baseline_area,
        'area_gap': area_gap,
        'cost': cost,
    }


# =============================================================================
# CLI
# =============================================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description='Floorplan Evaluator')
    parser.add_argument('--instance', help='Path to instance JSON')
    parser.add_argument('--solution', help='Path to solution JSON')
    parser.add_argument('--all', action='store_true',
                        help='Evaluate all instances')
    parser.add_argument('--instance-dir', default='/app/instances')
    parser.add_argument('--solution-dir', default='/app/solutions')
    args = parser.parse_args()

    if args.all:
        costs, block_counts = [], []
        for fname in sorted(os.listdir(args.instance_dir)):
            if not fname.endswith('.json'):
                continue
            with open(os.path.join(args.instance_dir, fname)) as f:
                inst = json.load(f)
            sol_path = os.path.join(args.solution_dir,
                                    f"solution_{inst['id']}.json")
            if not os.path.isfile(sol_path):
                print(f"MISSING solution for instance {inst['id']}")
                costs.append(M_PENALTY)
                block_counts.append(inst['block_count'])
                continue
            with open(sol_path) as f:
                sol = json.load(f)
            positions = [tuple(p) for p in sol['positions']]
            result = evaluate_solution(inst, positions)
            costs.append(result['cost'])
            block_counts.append(inst['block_count'])
            status = 'FEASIBLE' if result['is_feasible'] else 'INFEASIBLE'
            print(f"Instance {inst['id']:2d} | {inst['block_count']:3d} blocks "
                  f"| {status:10s} | cost={result['cost']:.4f} "
                  f"| hpwl_gap={result['hpwl_gap']:+.3f} "
                  f"| area_gap={result['area_gap']:+.3f} "
                  f"| v_rel={result['v_rel']:.3f}")
        if costs:
            total = compute_total_score(costs, block_counts)
            print(f"\nOverall score: {total:.4f}")
    elif args.instance and args.solution:
        with open(args.instance) as f:
            inst = json.load(f)
        with open(args.solution) as f:
            sol = json.load(f)
        positions = [tuple(p) for p in sol['positions']]
        result = evaluate_solution(inst, positions)
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
