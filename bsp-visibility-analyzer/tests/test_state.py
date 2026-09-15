
"""
Verification tests for BSP tree construction and visibility analysis.
Tests are implementation-agnostic: any valid BSP tree is accepted.
Correctness is verified via structural properties and independent ray casting.
"""

import json
import math
import os
import subprocess
import pytest

EPSILON = 1e-4
RAY_STEP_DEG = 0.02

# ── Embedded reference map data ──────────────────────────────
# (Agent must parse map.bin; tests use this for ground-truth comparison)

MAP_DATA = {
    "walls": [
        {"id": 0, "start": [0, 0], "end": [250, 0]},
        {"id": 1, "start": [250, 0], "end": [250, 100]},
        {"id": 2, "start": [250, 200], "end": [250, 300]},
        {"id": 3, "start": [250, 300], "end": [0, 300]},
        {"id": 4, "start": [0, 300], "end": [0, 0]},
        {"id": 5, "start": [250, 100], "end": [400, 100]},
        {"id": 6, "start": [250, 200], "end": [400, 200]},
        {"id": 7, "start": [400, 0], "end": [650, 0]},
        {"id": 8, "start": [650, 0], "end": [650, 300]},
        {"id": 9, "start": [650, 300], "end": [400, 300]},
        {"id": 10, "start": [400, 300], "end": [400, 200]},
        {"id": 11, "start": [400, 100], "end": [400, 0]},
        {"id": 12, "start": [80, 130], "end": [120, 130]},
        {"id": 13, "start": [120, 130], "end": [120, 170]},
        {"id": 14, "start": [120, 170], "end": [80, 170]},
        {"id": 15, "start": [80, 170], "end": [80, 130]},
        {"id": 16, "start": [500, 30], "end": [620, 250]},
    ],
    "viewpoints": [
        {"id": 0, "x": 125, "y": 150, "angle_deg": 0, "fov_deg": 90},
        {"id": 1, "x": 325, "y": 150, "angle_deg": 0, "fov_deg": 90},
        {"id": 2, "x": 525, "y": 150, "angle_deg": 180, "fov_deg": 90},
        {"id": 3, "x": 125, "y": 50, "angle_deg": 45, "fov_deg": 90},
        {"id": 4, "x": 560, "y": 60, "angle_deg": 90, "fov_deg": 120},
    ],
}


# ── Helpers ────────────────────────────────────────────────

def get_map():
    return MAP_DATA


def load_results():
    with open('/app/results.json') as f:
        return json.load(f)


def norm_angle(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a <= -math.pi:
        a += 2 * math.pi
    return a


def ray_seg_intersect(ox, oy, dx, dy, sx, sy, ex, ey):
    """Ray (ox,oy)+t*(dx,dy) vs segment (sx,sy)-(ex,ey). Returns t or None."""
    dsx = ex - sx
    dsy = ey - sy
    denom = dx * dsy - dy * dsx
    if abs(denom) < 1e-12:
        return None
    t = ((sx - ox) * dsy - (sy - oy) * dsx) / denom
    u = ((sx - ox) * dy - (sy - oy) * dx) / denom
    if t > 1e-6 and -1e-6 <= u <= 1.0 + 1e-6:
        return t
    return None


def seg_length(s):
    return math.hypot(s['end'][0] - s['start'][0], s['end'][1] - s['start'][1])


def wall_length(w):
    return math.hypot(w['end'][0] - w['start'][0], w['end'][1] - w['start'][1])


def point_on_segment(px, py, sx, sy, ex, ey, tol=1e-3):
    """Check if point (px,py) lies on segment (sx,sy)-(ex,ey)."""
    seg_len = math.hypot(ex - sx, ey - sy)
    if seg_len < 1e-12:
        return math.hypot(px - sx, py - sy) < tol
    t = ((px - sx) * (ex - sx) + (py - sy) * (ey - sy)) / (seg_len * seg_len)
    if t < -tol / seg_len or t > 1 + tol / seg_len:
        return False
    proj_x = sx + t * (ex - sx)
    proj_y = sy + t * (ey - sy)
    return math.hypot(px - proj_x, py - proj_y) < tol


# ── Collect all leaves/nodes from the BSP tree ──────────────

def collect_leaves(tree):
    if tree['type'] == 'leaf':
        return [tree]
    return collect_leaves(tree['front']) + collect_leaves(tree['back'])


def collect_nodes(tree):
    if tree['type'] == 'leaf':
        return []
    return [tree] + collect_nodes(tree['front']) + collect_nodes(tree['back'])


def all_segs_under(tree):
    if tree['type'] == 'leaf':
        return list(tree.get('segs', []))
    return all_segs_under(tree['front']) + all_segs_under(tree['back'])


# ── Reference ray-cast visibility ──────────────────────────

def reference_visibility(walls, vp):
    """Compute visible walls via brute-force ray casting."""
    vx, vy = vp['x'], vp['y']
    view_angle = math.radians(vp['angle_deg'])
    half_fov = math.radians(vp['fov_deg']) / 2.0

    visible = set()
    num_rays = int(vp['fov_deg'] / RAY_STEP_DEG) + 1

    for i in range(num_rays):
        rel = -half_fov + i * math.radians(RAY_STEP_DEG)
        angle = view_angle + rel
        dx = math.cos(angle)
        dy = math.sin(angle)
        best_t = float('inf')
        best_w = -1
        for w in walls:
            t = ray_seg_intersect(vx, vy, dx, dy,
                                  w['start'][0], w['start'][1],
                                  w['end'][0], w['end'][1])
            if t is not None and t < best_t:
                best_t = t
                best_w = w['id']
        if best_w >= 0:
            visible.add(best_w)

    for w in walls:
        for px, py in [w['start'], w['end']]:
            dist = math.hypot(px - vx, py - vy)
            if dist < 1e-6:
                continue
            a = math.atan2(py - vy, px - vx)
            rel = norm_angle(a - view_angle)
            if abs(rel) > half_fov + 0.01:
                continue
            for offset in [-0.0002, 0.0, 0.0002]:
                ang = a + offset
                dx = math.cos(ang)
                dy = math.sin(ang)
                best_t = float('inf')
                best_w = -1
                for w2 in walls:
                    t = ray_seg_intersect(vx, vy, dx, dy,
                                          w2['start'][0], w2['start'][1],
                                          w2['end'][0], w2['end'][1])
                    if t is not None and t < best_t:
                        best_t = t
                        best_w = w2['id']
                if best_w >= 0:
                    visible.add(best_w)

    return visible


# ── Tests ──────────────────────────────────────────────────

class TestResultsExist:
    def test_file_exists(self):
        assert os.path.isfile('/app/results.json'), "results.json not found"

    def test_valid_json(self):
        r = load_results()
        assert isinstance(r, dict)
        for key in ['bsp_tree', 'stats', 'traversals', 'visibility']:
            assert key in r, f"Missing key: {key}"


class TestBSPStructure:
    def test_stats_present(self):
        r = load_results()
        s = r['stats']
        assert s['num_nodes'] >= 1, "BSP must have at least one internal node"
        assert s['num_leaves'] >= 2, "BSP must have at least two leaves"
        assert s['max_depth'] >= 1
        assert s['total_segs'] >= 17, "Must have at least 17 segs (one per wall)"

    def test_all_walls_covered(self):
        """Every original wall must be covered by segs that union to the full wall."""
        m = get_map()
        r = load_results()
        tree = r['bsp_tree']
        segs = all_segs_under(tree)

        for wall in m['walls']:
            wid = wall['id']
            wall_segs = [s for s in segs if s['source_wall'] == wid]
            assert len(wall_segs) > 0, f"Wall {wid} has no segs in BSP tree"

            total_len = sum(seg_length(s) for s in wall_segs)
            orig_len = wall_length(wall)
            assert abs(total_len - orig_len) < 0.5, (
                f"Wall {wid}: seg lengths sum to {total_len:.4f}, "
                f"expected {orig_len:.4f}"
            )

    def test_segs_on_original_wall(self):
        """Each seg must lie on its source wall's line."""
        m = get_map()
        r = load_results()
        tree = r['bsp_tree']
        segs = all_segs_under(tree)

        walls_by_id = {w['id']: w for w in m['walls']}

        for seg in segs:
            w = walls_by_id[seg['source_wall']]
            wx1, wy1 = w['start']
            wx2, wy2 = w['end']
            for pt in [seg['start'], seg['end']]:
                assert point_on_segment(pt[0], pt[1], wx1, wy1, wx2, wy2, tol=0.1), (
                    f"Seg point {pt} not on wall {seg['source_wall']} "
                    f"({w['start']} -> {w['end']})"
                )

    def test_segs_on_correct_side_of_planes(self):
        """For each internal node, all segs in front subtree must be on front
        (or on) the splitting plane, and vice versa for back."""
        r = load_results()
        tree = r['bsp_tree']

        def check(node, ancestors):
            if node['type'] == 'leaf':
                for seg in node.get('segs', []):
                    for a, b, c, side in ancestors:
                        for pt in [seg['start'], seg['end']]:
                            d = a * pt[0] + b * pt[1] + c
                            if side == 'front':
                                assert d >= -EPSILON, (
                                    f"Seg {seg} point {pt} on wrong side "
                                    f"(d={d:.6f}, expected front)"
                                )
                            else:
                                assert d <= EPSILON, (
                                    f"Seg {seg} point {pt} on wrong side "
                                    f"(d={d:.6f}, expected back)"
                                )
                return

            pa = node['plane_a']
            pb = node['plane_b']
            pc = node['plane_c']
            check(node['front'], ancestors + [(pa, pb, pc, 'front')])
            check(node['back'], ancestors + [(pa, pb, pc, 'back')])

        check(tree, [])

    def test_leaf_ids_unique(self):
        r = load_results()
        leaves = collect_leaves(r['bsp_tree'])
        ids = [lf['leaf_id'] for lf in leaves]
        assert len(ids) == len(set(ids)), "Leaf IDs are not unique"

    def test_reasonable_depth(self):
        """BSP depth should be reasonable for 17 walls."""
        r = load_results()
        assert r['stats']['max_depth'] <= 30, "BSP tree unreasonably deep"


class TestTraversal:
    def test_traversal_count(self):
        m = get_map()
        r = load_results()
        assert len(r['traversals']) == len(m['viewpoints'])

    def test_traversal_covers_all_leaves(self):
        r = load_results()
        leaves = collect_leaves(r['bsp_tree'])
        leaf_ids = set(lf['leaf_id'] for lf in leaves)
        for trav in r['traversals']:
            trav_set = set(trav['leaf_order'])
            assert trav_set == leaf_ids, (
                f"VP {trav['viewpoint_id']}: traversal leaves {trav_set} "
                f"!= expected {leaf_ids}"
            )

    def test_traversal_near_before_far(self):
        """At each BSP node, the near subtree's leaves must appear before
        the far subtree's leaves in the traversal order."""
        m = get_map()
        r = load_results()
        tree = r['bsp_tree']

        def get_leaf_ids(node):
            if node['type'] == 'leaf':
                return {node['leaf_id']}
            return get_leaf_ids(node['front']) | get_leaf_ids(node['back'])

        def first_index(leaf_set, order):
            for i, lid in enumerate(order):
                if lid in leaf_set:
                    return i
            return len(order)

        def last_index(leaf_set, order):
            result = -1
            for i, lid in enumerate(order):
                if lid in leaf_set:
                    result = i
            return result

        vps_by_id = {v['id']: v for v in m['viewpoints']}

        for trav in r['traversals']:
            vp = vps_by_id[trav['viewpoint_id']]
            vx, vy = vp['x'], vp['y']
            order = trav['leaf_order']

            def check_node(node):
                if node['type'] == 'leaf':
                    return
                pa, pb, pc = node['plane_a'], node['plane_b'], node['plane_c']
                d = pa * vx + pb * vy + pc

                front_ids = get_leaf_ids(node['front'])
                back_ids = get_leaf_ids(node['back'])

                if abs(d) < EPSILON:
                    check_node(node['front'])
                    check_node(node['back'])
                    return

                if d > 0:
                    near_ids, far_ids = front_ids, back_ids
                else:
                    near_ids, far_ids = back_ids, front_ids

                last_near = last_index(near_ids, order)
                first_far = first_index(far_ids, order)
                assert last_near <= first_far, (
                    f"VP {trav['viewpoint_id']}: near side leaf appears after "
                    f"far side leaf at node with plane "
                    f"({pa}, {pb}, {pc})"
                )
                check_node(node['front'])
                check_node(node['back'])

            check_node(tree)


class TestVisibility:
    def test_visibility_count(self):
        m = get_map()
        r = load_results()
        assert len(r['visibility']) == len(m['viewpoints'])

    def test_visibility_correctness(self):
        """Compare submitted visibility against independent ray casting."""
        m = get_map()
        r = load_results()
        vps_by_id = {v['id']: v for v in m['viewpoints']}

        for vis in r['visibility']:
            vpid = vis['viewpoint_id']
            vp = vps_by_id[vpid]
            submitted = set(vis['visible_walls'])

            reference = reference_visibility(m['walls'], vp)

            false_positives = submitted - reference
            assert len(false_positives) <= 1, (
                f"VP {vpid}: false positive walls {false_positives}"
            )

            missed = reference - submitted
            assert len(missed) <= 2, (
                f"VP {vpid}: missed walls {missed} "
                f"(submitted={sorted(submitted)}, "
                f"reference={sorted(reference)})"
            )

    def test_visibility_nonempty(self):
        """Each viewpoint should see at least some walls."""
        r = load_results()
        for vis in r['visibility']:
            assert len(vis['visible_walls']) >= 2, (
                f"VP {vis['viewpoint_id']}: suspiciously few visible walls"
            )

    def test_vp0_sees_corridor_walls(self):
        """VP0 at (125,150) looking right should see corridor walls 5, 6."""
        r = load_results()
        vis = next(v for v in r['visibility'] if v['viewpoint_id'] == 0)
        visible = set(vis['visible_walls'])
        assert 5 in visible, "VP0 should see corridor bottom wall (5)"
        assert 6 in visible, "VP0 should see corridor top wall (6)"

    def test_vp1_sees_room_b(self):
        """VP1 at (325,150) in corridor looking right should see Room B walls."""
        r = load_results()
        vis = next(v for v in r['visibility'] if v['viewpoint_id'] == 1)
        visible = set(vis['visible_walls'])
        room_b_walls = {7, 8, 9, 10, 11, 16}
        assert len(visible & room_b_walls) >= 2, (
            f"VP1 should see Room B walls, got {visible & room_b_walls}"
        )

    def test_vp2_looks_left(self):
        """VP2 at (525,150) looking left should see Room B left walls (10, 11)."""
        r = load_results()
        vis = next(v for v in r['visibility'] if v['viewpoint_id'] == 2)
        visible = set(vis['visible_walls'])
        assert 10 in visible or 11 in visible, (
            "VP2 should see at least one Room B left wall (10 or 11)"
        )


class TestGraphvizOutputs:
    def test_dot_file_exists(self):
        assert os.path.isfile('/app/bsp_tree.dot'), "bsp_tree.dot not found"

    def test_dot_file_valid(self):
        """DOT file must be parseable by Graphviz."""
        result = subprocess.run(
            ['dot', '-Tpng', '/app/bsp_tree.dot', '-o', '/dev/null'],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"dot failed to parse bsp_tree.dot: {result.stderr}"
        )

    def test_png_file_exists(self):
        assert os.path.isfile('/app/bsp_tree.png'), "bsp_tree.png not found"

    def test_png_file_nonempty(self):
        size = os.path.getsize('/app/bsp_tree.png')
        assert size > 100, f"bsp_tree.png too small ({size} bytes)"

    def test_dot_contains_nodes_and_leaves(self):
        """DOT file should reference internal nodes and leaves."""
        with open('/app/bsp_tree.dot') as f:
            content = f.read()
        r = load_results()
        num_nodes = r['stats']['num_nodes']
        num_leaves = r['stats']['num_leaves']
        # DOT should contain at least some node/leaf references
        assert 'digraph' in content or 'graph' in content, (
            "DOT file missing graph declaration"
        )
        # Should have edges (internal nodes have children)
        assert '->' in content, "DOT file missing directed edges"
        # Rough check: should have at least num_nodes + num_leaves node definitions
        node_count = content.count('[label=')
        assert node_count >= num_nodes + num_leaves - 1, (
            f"DOT file has {node_count} labeled nodes, expected at least "
            f"{num_nodes + num_leaves - 1}"
        )
