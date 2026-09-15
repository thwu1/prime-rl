#!/usr/bin/env python3
"""
VLSI Floorplan Evaluator
Implements the ICCAD 2026 FloorSet cost function for evaluating floorplan solutions.
Self-contained: uses only Python standard library.

"""

import json
import math

# Contest parameters (from ICCAD 2026 FloorSet specification)
ALPHA = 0.5            # Quality metrics weight
BETA = 2.0             # Violation penalty exponent
AREA_TOLERANCE = 0.01  # 1% area tolerance for soft blocks
DIM_TOLERANCE = 1e-4   # Tolerance for dimension matching
OVERLAP_EPS = 1e-6     # Tolerance for overlap detection
EDGE_EPS = 1e-4        # Tolerance for edge abutment detection
INFEASIBLE_COST = 10.0 # Cost assigned to infeasible solutions


def check_overlaps(placement):
    """Check for pairwise block overlaps. Returns (count, first_pair_or_None)."""
    n = len(placement)
    for i in range(n):
        x1, y1, w1, h1 = placement[i]
        for j in range(i + 1, n):
            x2, y2, w2, h2 = placement[j]
            ox = max(0.0, min(x1 + w1, x2 + w2) - max(x1, x2))
            oy = max(0.0, min(y1 + h1, y2 + h2) - max(y1, y2))
            if ox > OVERLAP_EPS and oy > OVERLAP_EPS:
                return True, (i, j, ox * oy)
    return False, None


def check_area_tolerance(placement, area_targets, block_types):
    """Check soft block areas are within 1% of targets. Returns list of violating indices."""
    violations = []
    for i, (x, y, w, h) in enumerate(placement):
        if block_types[i] == 0:  # soft block only
            actual = w * h
            target = area_targets[i]
            if target > 0 and abs(actual - target) / target > AREA_TOLERANCE:
                violations.append(i)
    return violations


def check_hard_constraints(placement, block_types, target_dims, target_pos):
    """Check fixed-shape and preplaced block constraints."""
    violations = []
    for i, (x, y, w, h) in enumerate(placement):
        if block_types[i] >= 1:  # fixed or preplaced
            tw, th = target_dims[i]
            if abs(w - tw) > DIM_TOLERANCE or abs(h - th) > DIM_TOLERANCE:
                violations.append(("dim", i))
                continue
        if block_types[i] == 2:  # preplaced
            tx, ty = target_pos[i]
            if abs(x - tx) > DIM_TOLERANCE or abs(y - ty) > DIM_TOLERANCE:
                violations.append(("pos", i))
    return violations


def compute_hpwl_b2b(placement, b2b_edges):
    """Block-to-block weighted half-perimeter wirelength using centroids."""
    total = 0.0
    for src, dst, weight in b2b_edges:
        cx1 = placement[src][0] + placement[src][2] / 2.0
        cy1 = placement[src][1] + placement[src][3] / 2.0
        cx2 = placement[dst][0] + placement[dst][2] / 2.0
        cy2 = placement[dst][1] + placement[dst][3] / 2.0
        total += weight * (abs(cx1 - cx2) + abs(cy1 - cy2))
    return total


def compute_hpwl_p2b(placement, p2b_edges, pin_positions):
    """Pin-to-block weighted half-perimeter wirelength."""
    total = 0.0
    for pin_idx, block_idx, weight in p2b_edges:
        px, py = pin_positions[pin_idx]
        cx = placement[block_idx][0] + placement[block_idx][2] / 2.0
        cy = placement[block_idx][1] + placement[block_idx][3] / 2.0
        total += weight * (abs(px - cx) + abs(py - cy))
    return total


def compute_bbox_area(placement):
    """Bounding box area of all blocks."""
    min_x = min(p[0] for p in placement)
    min_y = min(p[1] for p in placement)
    max_x = max(p[0] + p[2] for p in placement)
    max_y = max(p[1] + p[3] for p in placement)
    return (max_x - min_x) * (max_y - min_y)


def blocks_abut(p1, p2):
    """Check if two rectangles share an edge of positive length."""
    x1, y1, w1, h1 = p1
    x2, y2, w2, h2 = p2
    # Vertical edge shared (right of p1 touches left of p2 or vice versa)
    if abs((x1 + w1) - x2) < EDGE_EPS or abs((x2 + w2) - x1) < EDGE_EPS:
        y_overlap = min(y1 + h1, y2 + h2) - max(y1, y2)
        if y_overlap > EDGE_EPS:
            return True
    # Horizontal edge shared
    if abs((y1 + h1) - y2) < EDGE_EPS or abs((y2 + h2) - y1) < EDGE_EPS:
        x_overlap = min(x1 + w1, x2 + w2) - max(x1, x2)
        if x_overlap > EDGE_EPS:
            return True
    return False


def count_cluster_violations(placement, cluster_groups):
    """Count grouping violations: blocks in group must abut to form connected component.
    Violation = (number_of_connected_components - 1) per group."""
    violations = 0
    for group in cluster_groups:
        if len(group) <= 1:
            continue
        # Build adjacency among group members
        adj = {idx: set() for idx in group}
        for a in range(len(group)):
            for b in range(a + 1, len(group)):
                if blocks_abut(placement[group[a]], placement[group[b]]):
                    adj[group[a]].add(group[b])
                    adj[group[b]].add(group[a])
        # BFS to count connected components
        visited = set()
        components = 0
        for start in group:
            if start in visited:
                continue
            components += 1
            queue = [start]
            visited.add(start)
            while queue:
                node = queue.pop(0)
                for nb in adj[node]:
                    if nb not in visited:
                        visited.add(nb)
                        queue.append(nb)
        violations += components - 1
    return violations


def count_mib_violations(placement, mib_groups):
    """Count MIB violations: blocks in group must have identical dimensions.
    Violation = (number_of_distinct_shapes - 1) per group."""
    violations = 0
    for group in mib_groups:
        if len(group) <= 1:
            continue
        shapes = set()
        for idx in group:
            w = round(placement[idx][2], 4)
            h = round(placement[idx][3], 4)
            shapes.add((w, h))
        violations += len(shapes) - 1
    return violations


def count_boundary_violations(placement, boundary_constraints):
    """Count boundary violations. Bitmask: 1=left, 2=right, 4=top, 8=bottom.
    Block must touch the indicated edge(s) of the global bounding box."""
    if not any(b > 0 for b in boundary_constraints):
        return 0
    min_x = min(p[0] for p in placement)
    min_y = min(p[1] for p in placement)
    max_x = max(p[0] + p[2] for p in placement)
    max_y = max(p[1] + p[3] for p in placement)
    violations = 0
    for i, bitmask in enumerate(boundary_constraints):
        if bitmask == 0:
            continue
        x, y, w, h = placement[i]
        ok = True
        if bitmask & 1 and abs(x - min_x) > OVERLAP_EPS:
            ok = False
        if bitmask & 2 and abs(x + w - max_x) > OVERLAP_EPS:
            ok = False
        if bitmask & 4 and abs(y + h - max_y) > OVERLAP_EPS:
            ok = False
        if bitmask & 8 and abs(y - min_y) > OVERLAP_EPS:
            ok = False
        if not ok:
            violations += 1
    return violations


def count_soft_terms(instance):
    """Count total soft constraint terms for normalization (N_soft)."""
    n_cluster = sum(len(g) - 1 for g in instance.get("cluster_groups", []))
    n_mib = sum(len(g) - 1 for g in instance.get("mib_groups", []))
    n_boundary = sum(1 for b in instance.get("boundary_constraints", []) if b > 0)
    return n_cluster + n_mib + n_boundary


def evaluate_solution(instance, placement):
    """Full evaluation of a floorplan solution.
    Returns dict with feasibility, cost, and detailed metrics."""
    n = instance["block_count"]

    if len(placement) != n:
        return {"feasible": False, "cost": INFEASIBLE_COST,
                "error": f"Expected {n} blocks, got {len(placement)}"}

    for i, (x, y, w, h) in enumerate(placement):
        if w <= 0 or h <= 0:
            return {"feasible": False, "cost": INFEASIBLE_COST,
                    "error": f"Block {i}: non-positive dimensions w={w:.6f}, h={h:.6f}"}

    # Hard constraint checks
    has_overlap, info = check_overlaps(placement)
    if has_overlap:
        return {"feasible": False, "cost": INFEASIBLE_COST,
                "error": f"Overlap: blocks {info[0]} and {info[1]}, area={info[2]:.8f}"}

    area_v = check_area_tolerance(placement, instance["area_targets"],
                                  instance["block_types"])
    if area_v:
        return {"feasible": False, "cost": INFEASIBLE_COST,
                "error": f"Area tolerance violated for blocks: {area_v[:5]}"}

    hard_v = check_hard_constraints(placement, instance["block_types"],
                                     instance["target_dims"], instance["target_pos"])
    if hard_v:
        return {"feasible": False, "cost": INFEASIBLE_COST,
                "error": f"Hard constraint violations: {hard_v[:5]}"}

    # Quality metrics
    hpwl_b2b = compute_hpwl_b2b(placement, instance["b2b_edges"])
    hpwl_p2b = compute_hpwl_p2b(placement, instance["p2b_edges"],
                                 instance["pin_positions"])
    total_hpwl = hpwl_b2b + hpwl_p2b
    bbox_area = compute_bbox_area(placement)

    # Soft constraint violations
    cluster_v = count_cluster_violations(placement,
                                         instance.get("cluster_groups", []))
    mib_v = count_mib_violations(placement, instance.get("mib_groups", []))
    boundary_v = count_boundary_violations(
        placement, instance.get("boundary_constraints", [0] * n))
    n_soft = count_soft_terms(instance)
    v_rel = (cluster_v + mib_v + boundary_v) / n_soft if n_soft > 0 else 0.0

    # Quality gaps (clamped to zero from below)
    hpwl_gap = max(0.0, (total_hpwl - instance["baseline_hpwl"])
                   / max(instance["baseline_hpwl"], 1e-6))
    area_gap = max(0.0, (bbox_area - instance["baseline_area"])
                   / max(instance["baseline_area"], 1e-6))

    # Cost formula: Cost = (1 + alpha*(HPWL_gap + Area_gap)) * exp(beta * V_rel)
    quality_factor = 1.0 + ALPHA * (hpwl_gap + area_gap)
    violation_factor = math.exp(BETA * v_rel)
    cost = quality_factor * violation_factor
    cost = min(cost, INFEASIBLE_COST - 1e-6)  # cap so feasible < infeasible

    return {
        "feasible": True, "cost": cost,
        "hpwl_b2b": hpwl_b2b, "hpwl_p2b": hpwl_p2b,
        "total_hpwl": total_hpwl, "bbox_area": bbox_area,
        "hpwl_gap": hpwl_gap, "area_gap": area_gap,
        "cluster_violations": cluster_v, "mib_violations": mib_v,
        "boundary_violations": boundary_v, "v_rel": v_rel,
        "quality_factor": quality_factor, "violation_factor": violation_factor,
    }


def compute_total_score(instance_results):
    """Compute exponentially-weighted total score.
    instance_results: list of (block_count, cost) pairs.
    Total = sum(cost_i * exp(n_i/12)) / sum(exp(n_j/12))"""
    if not instance_results:
        return 0.0
    max_n = max(n for n, _ in instance_results)
    weights = [math.exp((n - max_n) / 12.0) for n, _ in instance_results]
    total_w = sum(weights)
    return sum(c * w for (_, c), w in zip(instance_results, weights)) / total_w
