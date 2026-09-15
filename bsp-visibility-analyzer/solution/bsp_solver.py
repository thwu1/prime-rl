#!/usr/bin/env python3
"""
BSP Tree Construction, Visibility Analysis, and Graphviz Visualization.
Parses a custom BSPMAP2D binary format, builds the BSP tree,
computes per-viewpoint visibility, and generates DOT/PNG output.
"""

import json
import math
import struct
import subprocess


EPSILON = 1e-6
FRONT = 1
BACK = -1
ON_PLANE = 0
SPANNING = 2


# ── Binary format parser ─────────────────────────────────────

def parse_map_bin(path):
    """Parse BSPMAP2D binary format from the given file path."""
    with open(path, 'rb') as f:
        data = f.read()

    # Header: 8-byte magic + uint16 num_walls + uint16 num_vp + 4 reserved
    magic = data[0:8]
    assert magic == b'BSPMAP2D', f"Bad magic: {magic}"
    num_walls, num_vp = struct.unpack('<HH', data[8:12])

    walls = []
    offset = 16
    for i in range(num_walls):
        sx, sy, ex, ey = struct.unpack('<hhhh', data[offset:offset + 8])
        walls.append({
            'id': i,
            'start': [int(sx), int(sy)],
            'end': [int(ex), int(ey)],
        })
        offset += 8

    viewpoints = []
    for i in range(num_vp):
        x, y = struct.unpack('<hh', data[offset:offset + 4])
        angle_deg, fov_deg = struct.unpack('<ff', data[offset + 4:offset + 12])
        viewpoints.append({
            'id': i,
            'x': int(x),
            'y': int(y),
            'angle_deg': float(angle_deg),
            'fov_deg': float(fov_deg),
        })
        offset += 12

    return {'walls': walls, 'viewpoints': viewpoints}


# ── BSP primitives ───────────────────────────────────────────

class Seg:
    __slots__ = ('sx', 'sy', 'ex', 'ey', 'wall_id')

    def __init__(self, sx, sy, ex, ey, wall_id):
        self.sx = float(sx)
        self.sy = float(sy)
        self.ex = float(ex)
        self.ey = float(ey)
        self.wall_id = wall_id

    def length(self):
        return math.hypot(self.ex - self.sx, self.ey - self.sy)


class Plane:
    __slots__ = ('a', 'b', 'c')

    def __init__(self, a, b, c):
        length = math.hypot(a, b)
        if length < EPSILON:
            self.a = self.b = self.c = 0.0
        else:
            self.a = a / length
            self.b = b / length
            self.c = c / length

    def dist(self, x, y):
        return self.a * x + self.b * y + self.c

    def classify(self, x, y):
        d = self.dist(x, y)
        if d > EPSILON:
            return FRONT
        elif d < -EPSILON:
            return BACK
        return ON_PLANE


def plane_from_seg(seg):
    dx = seg.ex - seg.sx
    dy = seg.ey - seg.sy
    a = -dy
    b = dx
    c = -(a * seg.sx + b * seg.sy)
    return Plane(a, b, c)


def classify_seg(plane, seg):
    s1 = plane.classify(seg.sx, seg.sy)
    s2 = plane.classify(seg.ex, seg.ey)
    if s1 == ON_PLANE and s2 == ON_PLANE:
        return ON_PLANE
    if s1 == ON_PLANE:
        return s2
    if s2 == ON_PLANE:
        return s1
    if s1 == s2:
        return s1
    return SPANNING


def split_seg(plane, seg):
    d1 = plane.dist(seg.sx, seg.sy)
    d2 = plane.dist(seg.ex, seg.ey)
    t = d1 / (d1 - d2)
    t = max(0.0, min(1.0, t))
    ix = seg.sx + t * (seg.ex - seg.sx)
    iy = seg.sy + t * (seg.ey - seg.sy)
    if d1 >= 0:
        front = Seg(seg.sx, seg.sy, ix, iy, seg.wall_id)
        back = Seg(ix, iy, seg.ex, seg.ey, seg.wall_id)
    else:
        back = Seg(seg.sx, seg.sy, ix, iy, seg.wall_id)
        front = Seg(ix, iy, seg.ex, seg.ey, seg.wall_id)
    return front, back


# ── BSP tree builder ─────────────────────────────────────────

class BSPNode:
    __slots__ = ('plane', 'front', 'back', 'segs', 'is_leaf', 'node_id')

    def __init__(self):
        self.plane = None
        self.front = None
        self.back = None
        self.segs = None
        self.is_leaf = False
        self.node_id = -1


_leaf_counter = 0
_node_counter = 0


def _needs_splitting(segs):
    for i, s in enumerate(segs):
        p = plane_from_seg(s)
        for j, o in enumerate(segs):
            if i == j:
                continue
            if classify_seg(p, o) == SPANNING:
                return True
    return False


def build_bsp(segs):
    global _leaf_counter, _node_counter

    if len(segs) == 0 or not _needs_splitting(segs):
        node = BSPNode()
        node.is_leaf = True
        node.segs = list(segs)
        node.node_id = _leaf_counter
        _leaf_counter += 1
        return node

    best_score = float('inf')
    best_idx = -1
    for i, s in enumerate(segs):
        p = plane_from_seg(s)
        fc = bc = sc = 0
        for j, o in enumerate(segs):
            if i == j:
                continue
            c = classify_seg(p, o)
            if c == FRONT or c == ON_PLANE:
                fc += 1
            elif c == BACK:
                bc += 1
            else:
                sc += 1
        if bc == 0 and sc == 0:
            continue
        score = sc * 5 + abs(fc - bc)
        if score < best_score:
            best_score = score
            best_idx = i

    if best_idx < 0:
        node = BSPNode()
        node.is_leaf = True
        node.segs = list(segs)
        node.node_id = _leaf_counter
        _leaf_counter += 1
        return node

    splitter = segs[best_idx]
    plane = plane_from_seg(splitter)

    front_segs = []
    back_segs = []
    for s in segs:
        c = classify_seg(plane, s)
        if c == FRONT or c == ON_PLANE:
            front_segs.append(s)
        elif c == BACK:
            back_segs.append(s)
        else:
            f, b = split_seg(plane, s)
            if f.length() > EPSILON:
                front_segs.append(f)
            if b.length() > EPSILON:
                back_segs.append(b)

    if len(front_segs) == 0 or len(back_segs) == 0:
        node = BSPNode()
        node.is_leaf = True
        node.segs = list(segs)
        node.node_id = _leaf_counter
        _leaf_counter += 1
        return node

    node = BSPNode()
    node.is_leaf = False
    node.plane = plane
    node.node_id = _node_counter
    _node_counter += 1
    node.front = build_bsp(front_segs)
    node.back = build_bsp(back_segs)
    return node


# ── Tree metrics ─────────────────────────────────────────────

def tree_depth(node, d=0):
    if node.is_leaf:
        return d
    return max(tree_depth(node.front, d + 1), tree_depth(node.back, d + 1))


def count_nodes(node):
    if node.is_leaf:
        return 0
    return 1 + count_nodes(node.front) + count_nodes(node.back)


def count_leaves(node):
    if node.is_leaf:
        return 1
    return count_leaves(node.front) + count_leaves(node.back)


def collect_all_segs(node):
    if node.is_leaf:
        return list(node.segs)
    return collect_all_segs(node.front) + collect_all_segs(node.back)


def bsp_to_json(node):
    if node.is_leaf:
        return {
            'type': 'leaf',
            'leaf_id': node.node_id,
            'segs': [
                {
                    'start': [round(s.sx, 6), round(s.sy, 6)],
                    'end': [round(s.ex, 6), round(s.ey, 6)],
                    'source_wall': s.wall_id,
                }
                for s in node.segs
            ],
        }
    return {
        'type': 'node',
        'plane_a': round(node.plane.a, 10),
        'plane_b': round(node.plane.b, 10),
        'plane_c': round(node.plane.c, 10),
        'front': bsp_to_json(node.front),
        'back': bsp_to_json(node.back),
    }


# ── Traversal ────────────────────────────────────────────────

def traverse_ftb(node, vx, vy):
    if node.is_leaf:
        return [node.node_id]
    d = node.plane.dist(vx, vy)
    if d >= 0:
        return traverse_ftb(node.front, vx, vy) + traverse_ftb(node.back, vx, vy)
    else:
        return traverse_ftb(node.back, vx, vy) + traverse_ftb(node.front, vx, vy)


# ── Visibility ───────────────────────────────────────────────

def _norm_angle(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a <= -math.pi:
        a += 2 * math.pi
    return a


class OcclusionTracker:
    """Tracks filled angular ranges for occlusion."""

    def __init__(self):
        self.ranges = []

    def is_fully_occluded(self, lo, hi):
        for rs, re in self.ranges:
            if rs <= lo + EPSILON and re >= hi - EPSILON:
                return True
        return False

    def is_completely_filled(self, fov_lo, fov_hi):
        for rs, re in self.ranges:
            if rs <= fov_lo + EPSILON and re >= fov_hi - EPSILON:
                return True
        return False

    def add(self, lo, hi):
        self.ranges.append((lo, hi))
        self.ranges.sort()
        merged = [self.ranges[0]]
        for s, e in self.ranges[1:]:
            if s <= merged[-1][1] + EPSILON:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        self.ranges = merged

    def any_visible(self, lo, hi):
        covered = 0.0
        total = hi - lo
        if total <= EPSILON:
            return False
        for rs, re in self.ranges:
            ov_lo = max(lo, rs)
            ov_hi = min(hi, re)
            if ov_hi > ov_lo:
                covered += ov_hi - ov_lo
        return covered < total - EPSILON


def compute_visibility(bsp_root, vp):
    vx = vp['x']
    vy = vp['y']
    view_angle = math.radians(vp['angle_deg'])
    half_fov = math.radians(vp['fov_deg']) / 2.0
    fov_lo = -half_fov
    fov_hi = half_fov

    occ = OcclusionTracker()
    visible = set()

    def process_leaf(leaf):
        if occ.is_completely_filled(fov_lo, fov_hi):
            return
        def _seg_dist(s):
            mx = (s.sx + s.ex) / 2
            my = (s.sy + s.ey) / 2
            return (mx - vx) ** 2 + (my - vy) ** 2
        sorted_segs = sorted(leaf.segs, key=_seg_dist)
        for seg in sorted_segs:
            if occ.is_completely_filled(fov_lo, fov_hi):
                return
            a1 = _norm_angle(math.atan2(seg.sy - vy, seg.sx - vx) - view_angle)
            a2 = _norm_angle(math.atan2(seg.ey - vy, seg.ex - vx) - view_angle)

            lo = min(a1, a2)
            hi = max(a1, a2)

            if hi - lo > math.pi:
                continue

            lo = max(lo, fov_lo)
            hi = min(hi, fov_hi)
            if lo >= hi - EPSILON:
                continue

            if occ.any_visible(lo, hi):
                visible.add(seg.wall_id)

            occ.add(lo, hi)

    def walk(node):
        if node.is_leaf:
            process_leaf(node)
            return
        d = node.plane.dist(vx, vy)
        if d >= 0:
            walk(node.front)
            walk(node.back)
        else:
            walk(node.back)
            walk(node.front)

    walk(bsp_root)
    return sorted(visible)


# ── DOT generation ───────────────────────────────────────────

def bsp_to_dot(root):
    """Generate Graphviz DOT representation of the BSP tree."""
    lines = ['digraph BSPTree {']
    lines.append('    rankdir=TB;')
    lines.append('    node [shape=record, fontsize=10];')
    _node_id = [0]

    def emit(node):
        nid = _node_id[0]
        _node_id[0] += 1
        if node.is_leaf:
            seg_walls = sorted(set(s.wall_id for s in node.segs))
            label = (
                f"Leaf {node.node_id}\\n"
                f"{len(node.segs)} segs\\n"
                f"walls: {seg_walls}"
            )
            lines.append(f'    n{nid} [label="{label}", shape=ellipse, '
                         f'style=filled, fillcolor=lightblue];')
            return nid
        label = (
            f"Node\\n"
            f"{node.plane.a:.4f}x + {node.plane.b:.4f}y + "
            f"{node.plane.c:.2f} = 0"
        )
        lines.append(f'    n{nid} [label="{label}"];')
        front_id = emit(node.front)
        back_id = emit(node.back)
        lines.append(f'    n{nid} -> n{front_id} [label="front"];')
        lines.append(f'    n{nid} -> n{back_id} [label="back"];')
        return nid

    emit(root)
    lines.append('}')
    return '\n'.join(lines)


# ── Main ─────────────────────────────────────────────────────

def main():
    global _leaf_counter, _node_counter
    _leaf_counter = 0
    _node_counter = 0

    # Parse binary map format
    data = parse_map_bin('/app/map.bin')

    segs = []
    for w in data['walls']:
        segs.append(Seg(w['start'][0], w['start'][1],
                        w['end'][0], w['end'][1], w['id']))

    root = build_bsp(segs)

    all_segs = collect_all_segs(root)
    wall_seg_counts = {}
    for s in all_segs:
        wall_seg_counts[s.wall_id] = wall_seg_counts.get(s.wall_id, 0) + 1
    split_walls = set(wid for wid, cnt in wall_seg_counts.items() if cnt > 1)

    traversals = []
    for vp in data['viewpoints']:
        order = traverse_ftb(root, vp['x'], vp['y'])
        traversals.append({'viewpoint_id': vp['id'], 'leaf_order': order})

    visibility = []
    for vp in data['viewpoints']:
        vis = compute_visibility(root, vp)
        visibility.append({'viewpoint_id': vp['id'], 'visible_walls': vis})

    results = {
        'bsp_tree': bsp_to_json(root),
        'stats': {
            'num_nodes': count_nodes(root),
            'num_leaves': count_leaves(root),
            'max_depth': tree_depth(root),
            'total_segs': len(all_segs),
            'total_splits': len(split_walls),
        },
        'traversals': traversals,
        'visibility': visibility,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    # Generate Graphviz DOT file
    dot_content = bsp_to_dot(root)
    with open('/app/bsp_tree.dot', 'w') as f:
        f.write(dot_content)

    # Render DOT to PNG
    subprocess.run(
        ['dot', '-Tpng', '/app/bsp_tree.dot', '-o', '/app/bsp_tree.png'],
        check=True,
    )


if __name__ == '__main__':
    main()
