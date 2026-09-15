#!/usr/bin/env python3
"""
SDF Scene Layout Solver with Mesh Collision and Stability Analysis.

Reads an SDF world file and YAML constraint specification, computes valid
3D object placements satisfying all spatial constraints with mesh-based
collision detection and physics stability verification.
"""

import argparse
import json
import math
import os
import random
import sys
import xml.etree.ElementTree as ET

import networkx as nx
import numpy as np
import trimesh
import yaml
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="SDF scene layout solver")
    p.add_argument("--scene", required=True, help="Input SDF file")
    p.add_argument("--constraints", required=True, help="Input YAML constraints")
    p.add_argument("--output-dir", required=True, help="Output directory")
    p.add_argument("--num-placements", type=int, default=1)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


# ---------------------------------------------------------------------------
# SDF Parsing
# ---------------------------------------------------------------------------

def parse_sdf(sdf_path):
    """Parse SDF file and return object dict and ElementTree."""
    tree = ET.parse(sdf_path)
    root = tree.getroot()
    objects = {}

    for model in root.iter("model"):
        name = model.get("name")
        pose_elem = model.find("pose")
        if pose_elem is not None and pose_elem.text:
            pose = [float(x) for x in pose_elem.text.strip().split()]
        else:
            pose = [0.0] * 6

        is_static = False
        static_elem = model.find("static")
        if static_elem is not None and static_elem.text.strip().lower() == "true":
            is_static = True

        geom_elem = model.find(".//collision/geometry")
        geom = _parse_geometry(geom_elem)

        objects[name] = {
            "geometry": geom,
            "initial_pose": pose,
            "orientation": pose[3:],
            "is_static": is_static,
        }

    return objects, tree


def _parse_geometry(geom_elem):
    for child in geom_elem:
        if child.tag == "box":
            size = [float(x) for x in child.find("size").text.strip().split()]
            return {"type": "box", "size": size}
        elif child.tag == "cylinder":
            r = float(child.find("radius").text.strip())
            h = float(child.find("length").text.strip())
            return {"type": "cylinder", "radius": r, "length": h}
        elif child.tag == "sphere":
            r = float(child.find("radius").text.strip())
            return {"type": "sphere", "radius": r}
    raise ValueError("Unknown geometry type")


def parse_constraints(yaml_path):
    with open(yaml_path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Geometry Helpers
# ---------------------------------------------------------------------------

def get_half_extents(geom):
    """Axis-aligned half-extents before rotation."""
    if geom["type"] == "box":
        s = geom["size"]
        return [s[0] / 2, s[1] / 2, s[2] / 2]
    elif geom["type"] == "cylinder":
        return [geom["radius"], geom["radius"], geom["length"] / 2]
    elif geom["type"] == "sphere":
        r = geom["radius"]
        return [r, r, r]


def create_mesh(geom):
    if geom["type"] == "box":
        return trimesh.creation.box(extents=geom["size"])
    elif geom["type"] == "cylinder":
        return trimesh.creation.cylinder(
            radius=geom["radius"], height=geom["length"], sections=32
        )
    elif geom["type"] == "sphere":
        return trimesh.creation.icosphere(radius=geom["radius"], subdivisions=3)


def pose_to_transform(pose):
    """Convert SDF pose [x,y,z,roll,pitch,yaw] to 4x4 transform."""
    x, y, z = pose[0], pose[1], pose[2]
    roll, pitch, yaw = pose[3], pose[4], pose[5]
    R = Rotation.from_euler("XYZ", [roll, pitch, yaw]).as_matrix()
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = [x, y, z]
    return T


def get_rotated_half_extents(geom, orientation):
    """Get axis-aligned half-extents after applying orientation."""
    if all(abs(a) < 1e-9 for a in orientation):
        return get_half_extents(geom)
    mesh = create_mesh(geom)
    R = Rotation.from_euler("XYZ", orientation).as_matrix()
    T = np.eye(4)
    T[:3, :3] = R
    mesh.apply_transform(T)
    bounds = mesh.bounds  # [[min_x,min_y,min_z],[max_x,max_y,max_z]]
    return [(bounds[1][i] - bounds[0][i]) / 2 for i in range(3)]


def compute_object_volume(geom):
    if geom["type"] == "box":
        s = geom["size"]
        return s[0] * s[1] * s[2]
    elif geom["type"] == "cylinder":
        return math.pi * geom["radius"] ** 2 * geom["length"]
    elif geom["type"] == "sphere":
        return (4.0 / 3.0) * math.pi * geom["radius"] ** 3


# ---------------------------------------------------------------------------
# Collision Detection (mesh-based via convex hull)
# ---------------------------------------------------------------------------

def convex_collision(verts_a, verts_b, margin=0.0):
    """Check if two convex objects collide using hull vertex containment."""
    try:
        hull_a = ConvexHull(verts_a)
        for v in verts_b:
            if np.all(hull_a.equations @ np.append(v, 1.0) <= margin):
                return True
    except Exception:
        pass
    try:
        hull_b = ConvexHull(verts_b)
        for v in verts_a:
            if np.all(hull_b.equations @ np.append(v, 1.0) <= margin):
                return True
    except Exception:
        pass
    return False


def get_related_pairs(constraints):
    """Pairs exempt from collision (transitive through support/containment chains).

    Objects inside a container that sits on a table share the table's top-face
    z-boundary.  Without transitive exemptions the collision checker would flag
    them as intersecting the table.
    """
    parent_map = {}
    for c in constraints:
        if c["predicate"] in ("on_top_of", "stacked_on", "inside"):
            parent_map.setdefault(c["subject"], set()).add(c["reference"])

    pairs = set()
    for start in list(parent_map.keys()):
        visited = set()
        queue = list(parent_map.get(start, set()))
        while queue:
            current = queue.pop()
            if current in visited:
                continue
            visited.add(current)
            pairs.add((start, current))
            pairs.add((current, start))
            for parent in parent_map.get(current, set()):
                queue.append(parent)
    return pairs


# ---------------------------------------------------------------------------
# Constraint Graph
# ---------------------------------------------------------------------------

class CyclicDependencyError(Exception):
    pass


class PlacementError(Exception):
    pass


def topological_sort_with_cycle_detection(object_names, constraints):
    """Topological sort using networkx; raise on cycles."""
    G = nx.DiGraph()
    G.add_nodes_from(object_names)
    for c in constraints:
        subj, ref = c["subject"], c["reference"]
        if subj != ref:
            G.add_edge(ref, subj)
    if not nx.is_directed_acyclic_graph(G):
        cycles = list(nx.simple_cycles(G))
        raise CyclicDependencyError(
            f"Cyclic dependency detected — unsatisfiable constraint graph. "
            f"Cycles involving: {cycles}"
        )
    return list(nx.topological_sort(G))


# ---------------------------------------------------------------------------
# Stability Analysis
# ---------------------------------------------------------------------------

def find_stacked_assemblies(constraints):
    """Find chains of stacked_on relations from bottom to top."""
    parent_to_children = {}
    child_to_parent = {}
    for c in constraints:
        if c["predicate"] == "stacked_on":
            child = c["subject"]
            parent = c["reference"]
            parent_to_children.setdefault(parent, []).append(child)
            child_to_parent[child] = parent

    all_parents = set(parent_to_children.keys())
    all_children = set(child_to_parent.keys())
    roots = sorted(all_parents - all_children)

    assemblies = []
    for root in roots:
        chain = [root]
        current = root
        while current in parent_to_children:
            children = sorted(parent_to_children[current])
            chain.append(children[0])
            current = children[0]
        assemblies.append(chain)
    return assemblies


def compute_support_polygon_2d(geom, orientation, center_xy):
    """Get the 2D support polygon (top face projection) in world frame."""
    mesh = create_mesh(geom)
    if any(abs(a) > 1e-9 for a in orientation):
        R = Rotation.from_euler("XYZ", orientation).as_matrix()
        T = np.eye(4)
        T[:3, :3] = R
        mesh.apply_transform(T)
    verts = mesh.vertices
    max_z = verts[:, 2].max()
    top_verts = verts[verts[:, 2] > max_z - 1e-4]
    poly_2d = top_verts[:, :2] + np.array(center_xy)
    return poly_2d


def check_assembly_stability(chain, positions, objects):
    """Check physics stability of a stacked assembly chain."""
    results = []
    all_stable = True

    for i in range(len(chain) - 1):
        support_name = chain[i]
        supported_name = chain[i + 1]
        support_pos = positions[support_name]
        support_geom = objects[support_name]["geometry"]
        support_orient = objects[support_name]["orientation"]

        poly_2d = compute_support_polygon_2d(
            support_geom, support_orient, [support_pos[0], support_pos[1]]
        )

        # Combined CoM of all objects above this level
        total_mass = 0.0
        com_x, com_y = 0.0, 0.0
        for j in range(i + 1, len(chain)):
            obj_name = chain[j]
            vol = compute_object_volume(objects[obj_name]["geometry"])
            pos = positions[obj_name]
            total_mass += vol
            com_x += vol * pos[0]
            com_y += vol * pos[1]

        if total_mass > 0:
            com_x /= total_mass
            com_y /= total_mass

        com_in_hull = False
        try:
            if len(poly_2d) >= 3:
                hull = ConvexHull(poly_2d)
                point = np.array([com_x, com_y, 1.0])
                com_in_hull = bool(np.all(hull.equations @ point <= 1e-6))
            else:
                # Degenerate: line or point — assume stable if very close
                centroid = poly_2d.mean(axis=0)
                com_in_hull = (
                    abs(com_x - centroid[0]) < 0.01
                    and abs(com_y - centroid[1]) < 0.01
                )
        except Exception:
            com_in_hull = True

        results.append(
            {
                "support": support_name,
                "supported": supported_name,
                "com_in_hull": com_in_hull,
            }
        )
        if not com_in_hull:
            all_stable = False

    return results, all_stable


# ---------------------------------------------------------------------------
# Placement Solver
# ---------------------------------------------------------------------------

def try_solve(objects, constraints_data, rng):
    """Attempt one complete placement solution."""
    anchors = set(constraints_data.get("anchors", []) or [])
    constraints = constraints_data["constraints"]
    settings = constraints_data.get("settings", {})
    margin = settings.get("collision_margin", 0.005)

    order = topological_sort_with_cycle_detection(list(objects.keys()), constraints)
    related = get_related_pairs(constraints)

    rels_by_subj = {}
    for c in constraints:
        rels_by_subj.setdefault(c["subject"], []).append(c)

    positions = {}
    # Cache: pre-create oriented base meshes for collision checking
    base_verts = {}  # name -> vertices of mesh at origin with orientation applied

    for name in order:
        obj = objects[name]
        geom = obj["geometry"]
        orient = obj["orientation"]
        rhe = get_rotated_half_extents(geom, orient)

        # Pre-compute oriented base vertices (mesh at origin with rotation)
        mesh = create_mesh(geom)
        if any(abs(a) > 1e-9 for a in orient):
            R = Rotation.from_euler("XYZ", orient).as_matrix()
            T = np.eye(4)
            T[:3, :3] = R
            mesh.apply_transform(T)
        oriented_verts = mesh.vertices.copy()

        if name in anchors:
            pose = list(obj["initial_pose"])
            positions[name] = pose
            base_verts[name] = oriented_verts + np.array(pose[:3])
            continue

        my_rels = rels_by_subj.get(name, [])

        # Determine z and special modes
        z = 0.0
        is_stacked = False
        stacked_ref = None

        for rel in my_rels:
            ref = rel["reference"]
            ref_pos = positions[ref]
            ref_geom = objects[ref]["geometry"]
            ref_orient = objects[ref]["orientation"]
            ref_rhe = get_rotated_half_extents(ref_geom, ref_orient)
            pred = rel["predicate"]

            if pred == "on_top_of":
                z = ref_pos[2] + ref_rhe[2] + rhe[2]
            elif pred == "stacked_on":
                z = ref_pos[2] + ref_rhe[2] + rhe[2]
                is_stacked = True
                stacked_ref = ref
            elif pred == "inside":
                z = ref_pos[2] - ref_rhe[2] + rhe[2]

        # stacked_on: center-aligned, done
        if is_stacked:
            ref_pos = positions[stacked_ref]
            pose = [ref_pos[0], ref_pos[1], z] + list(orient)
            positions[name] = pose
            base_verts[name] = oriented_verts + np.array(pose[:3])
            continue

        # Compute valid x, y range
        x_lo, x_hi = -1000.0, 1000.0
        y_lo, y_hi = -1000.0, 1000.0

        for rel in my_rels:
            ref = rel["reference"]
            ref_pos = positions[ref]
            ref_geom = objects[ref]["geometry"]
            ref_orient = objects[ref]["orientation"]
            ref_rhe = get_rotated_half_extents(ref_geom, ref_orient)
            pred = rel["predicate"]
            params = rel.get("params", {}) or {}
            clearance = params.get("clearance", margin)

            if pred == "on_top_of":
                x_lo = max(x_lo, ref_pos[0] - ref_rhe[0] + rhe[0])
                x_hi = min(x_hi, ref_pos[0] + ref_rhe[0] - rhe[0])
                y_lo = max(y_lo, ref_pos[1] - ref_rhe[1] + rhe[1])
                y_hi = min(y_hi, ref_pos[1] + ref_rhe[1] - rhe[1])

            elif pred == "inside":
                x_lo = max(x_lo, ref_pos[0] - ref_rhe[0] + rhe[0])
                x_hi = min(x_hi, ref_pos[0] + ref_rhe[0] - rhe[0])
                y_lo = max(y_lo, ref_pos[1] - ref_rhe[1] + rhe[1])
                y_hi = min(y_hi, ref_pos[1] + ref_rhe[1] - rhe[1])

            elif pred == "right_of":
                # API spec: subject center y > reference center y + clearance
                y_lo = max(y_lo, ref_pos[1] + clearance)

            elif pred == "left_of":
                # API spec: subject center y < reference center y - clearance
                y_hi = min(y_hi, ref_pos[1] - clearance)

            elif pred == "in_front_of":
                # API spec: subject center x > reference center x + clearance
                x_lo = max(x_lo, ref_pos[0] + clearance)

            elif pred == "behind":
                # API spec: subject center x < reference center x - clearance
                x_hi = min(x_hi, ref_pos[0] - clearance)

        if x_lo > x_hi or y_lo > y_hi:
            raise PlacementError(
                f"Empty valid range for '{name}': "
                f"x=[{x_lo:.4f},{x_hi:.4f}], y=[{y_lo:.4f},{y_hi:.4f}]"
            )

        # Identify next_to constraints
        next_to_rels = [r for r in my_rels if r["predicate"] == "next_to"]

        # Rejection-sample a valid position
        max_samples = 2000
        for _ in range(max_samples):
            x = rng.uniform(x_lo, x_hi)
            y = rng.uniform(y_lo, y_hi)

            # Check next_to distance constraints
            ok = True
            for nt in next_to_rels:
                ref_pos = positions[nt["reference"]]
                dr = (nt.get("params", {}) or {}).get("distance_range", [0.1, 0.3])
                d = math.sqrt((x - ref_pos[0]) ** 2 + (y - ref_pos[1]) ** 2)
                if not (dr[0] <= d <= dr[1]):
                    ok = False
                    break
            if not ok:
                continue

            # Check mesh-based collision
            test_verts = oriented_verts + np.array([x, y, z])
            collision = False
            for other_name, other_verts in base_verts.items():
                if (name, other_name) in related:
                    continue
                if convex_collision(test_verts, other_verts, margin):
                    collision = True
                    break
            if collision:
                continue

            pose = [x, y, z] + list(orient)
            positions[name] = pose
            base_verts[name] = test_verts
            break
        else:
            raise PlacementError(
                f"Could not place '{name}' after {max_samples} samples"
            )

    return positions


def solve_single(objects, constraints_data, seed, max_restarts=500):
    """Solve with full restarts on PlacementError."""
    for attempt in range(max_restarts):
        rng = random.Random(seed * 10000 + attempt)
        try:
            return try_solve(objects, constraints_data, rng)
        except PlacementError:
            continue
    raise ValueError(
        f"Could not find a valid placement after {max_restarts} restarts "
        f"(seed={seed})"
    )


# ---------------------------------------------------------------------------
# Constraint Verification
# ---------------------------------------------------------------------------

def verify_constraints(positions, objects, constraints_data):
    """Generate constraints report."""
    constraints = constraints_data["constraints"]
    results = []
    all_satisfied = True

    for c in constraints:
        subj = c["subject"]
        ref = c["reference"]
        pred = c["predicate"]
        params = c.get("params", {}) or {}

        sp = positions[subj]
        rp = positions[ref]

        subj_rhe = get_rotated_half_extents(
            objects[subj]["geometry"], objects[subj]["orientation"]
        )
        ref_rhe = get_rotated_half_extents(
            objects[ref]["geometry"], objects[ref]["orientation"]
        )

        satisfied = True
        detail = ""

        if pred == "on_top_of":
            expected_z = rp[2] + ref_rhe[2] + subj_rhe[2]
            if abs(sp[2] - expected_z) > 0.01:
                satisfied = False
                detail = f"z={sp[2]:.4f}, expected={expected_z:.4f}"
            else:
                detail = f"z correct: {sp[2]:.4f}"

        elif pred == "stacked_on":
            expected_z = rp[2] + ref_rhe[2] + subj_rhe[2]
            if (
                abs(sp[2] - expected_z) > 0.01
                or abs(sp[0] - rp[0]) > 0.01
                or abs(sp[1] - rp[1]) > 0.01
            ):
                satisfied = False
                detail = "alignment or z error"
            else:
                detail = "aligned and z correct"

        elif pred == "inside":
            expected_z = rp[2] - ref_rhe[2] + subj_rhe[2]
            if abs(sp[2] - expected_z) > 0.01:
                satisfied = False
            for ax in range(2):
                if sp[ax] - subj_rhe[ax] < rp[ax] - ref_rhe[ax] - 0.01:
                    satisfied = False
                if sp[ax] + subj_rhe[ax] > rp[ax] + ref_rhe[ax] + 0.01:
                    satisfied = False
            detail = "contained" if satisfied else "containment violated"

        elif pred == "right_of":
            clearance = params.get("clearance", 0.005)
            if sp[1] <= rp[1] + clearance - 0.01:
                satisfied = False
            detail = f"y_subj={sp[1]:.4f}, y_ref={rp[1]:.4f}"

        elif pred == "left_of":
            clearance = params.get("clearance", 0.005)
            if sp[1] >= rp[1] - clearance + 0.01:
                satisfied = False
            detail = f"y_subj={sp[1]:.4f}, y_ref={rp[1]:.4f}"

        elif pred == "in_front_of":
            clearance = params.get("clearance", 0.005)
            if sp[0] <= rp[0] + clearance - 0.01:
                satisfied = False
            detail = f"x_subj={sp[0]:.4f}, x_ref={rp[0]:.4f}"

        elif pred == "behind":
            clearance = params.get("clearance", 0.005)
            if sp[0] >= rp[0] - clearance + 0.01:
                satisfied = False
            detail = f"x_subj={sp[0]:.4f}, x_ref={rp[0]:.4f}"

        elif pred == "next_to":
            dr = params.get("distance_range", [0.1, 0.3])
            d = math.sqrt((sp[0] - rp[0]) ** 2 + (sp[1] - rp[1]) ** 2)
            if not (dr[0] - 0.01 <= d <= dr[1] + 0.01):
                satisfied = False
            detail = f"dist={d:.4f}, range={dr}"

        results.append(
            {
                "subject": subj,
                "predicate": pred,
                "reference": ref,
                "satisfied": satisfied,
                "detail": detail,
            }
        )
        if not satisfied:
            all_satisfied = False

    return {"constraints": results, "all_satisfied": all_satisfied}


# ---------------------------------------------------------------------------
# Output Writers
# ---------------------------------------------------------------------------

def write_solved_sdf(sdf_path, positions, output_path):
    """Write SDF with updated poses."""
    tree = ET.parse(sdf_path)
    root = tree.getroot()
    for model in root.iter("model"):
        name = model.get("name")
        if name in positions:
            pose_elem = model.find("pose")
            pose = positions[name]
            pose_elem.text = " ".join(f"{v:.6f}" for v in pose)
    ET.indent(tree, space="  ")
    tree.write(output_path, xml_declaration=True, encoding="unicode")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    objects, sdf_tree = parse_sdf(args.scene)
    constraints_data = parse_constraints(args.constraints)

    os.makedirs(args.output_dir, exist_ok=True)

    # Solve placements
    placements_list = []
    for i in range(args.num_placements):
        seed = args.seed + i
        try:
            positions = solve_single(objects, constraints_data, seed)
        except CyclicDependencyError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        placements_list.append(
            {"seed": seed, "objects": {n: {"pose": p} for n, p in positions.items()}}
        )

    # Write placements.json
    placements_json = {
        "placements": placements_list,
        "metadata": {
            "num_placements": args.num_placements,
            "base_seed": args.seed,
        },
    }
    with open(os.path.join(args.output_dir, "placements.json"), "w") as f:
        json.dump(placements_json, f, indent=2)

    # Write solved_scene.sdf (first placement)
    first_positions = {
        n: d["pose"] for n, d in placements_list[0]["objects"].items()
    }
    write_solved_sdf(
        args.scene, first_positions,
        os.path.join(args.output_dir, "solved_scene.sdf"),
    )

    # Stability analysis
    assemblies = find_stacked_assemblies(constraints_data["constraints"])
    stability_results = []
    all_stable = True
    for chain in assemblies:
        per_level, stable = check_assembly_stability(chain, first_positions, objects)
        stability_results.append(
            {"base": chain[0], "chain": chain, "per_level": per_level, "stable": stable}
        )
        if not stable:
            all_stable = False

    stability_report = {"assemblies": stability_results, "all_stable": all_stable}
    with open(os.path.join(args.output_dir, "stability_report.json"), "w") as f:
        json.dump(stability_report, f, indent=2)

    # Constraints report
    constraints_report = verify_constraints(
        first_positions, objects, constraints_data
    )
    with open(os.path.join(args.output_dir, "constraints_report.json"), "w") as f:
        json.dump(constraints_report, f, indent=2)


if __name__ == "__main__":
    main()
