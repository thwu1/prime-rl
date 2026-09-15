#!/usr/bin/env python3
"""
BSP tree compiler with convex decomposition and adjacency analysis.
Parses binary WAD input, constructs a BSP tree, reconstructs convex
subsector polygons, computes adjacency, writes JSON + binary WAD + SVG.
"""

import json
import math
import os
import struct
import subprocess

EPSILON = 1e-9
SPLIT_PENALTY = 8


# --- WAD Parsing ---

def parse_wad_raw(path):
    """Parse a PWAD file and return dict of lump_name -> raw bytes."""
    with open(path, 'rb') as f:
        data = f.read()
    magic, num_lumps, dir_offset = struct.unpack_from('<4sii', data, 0)
    assert magic == b'PWAD', f"Invalid WAD magic: {magic!r}"
    lumps = {}
    for i in range(num_lumps):
        base = dir_offset + i * 16
        lump_off, lump_sz = struct.unpack_from('<ii', data, base)
        name = data[base + 8:base + 16].rstrip(b'\x00').decode('ascii')
        lumps[name] = data[lump_off:lump_off + lump_sz]
    return lumps


def parse_input_wad(path):
    """Parse the input WAD and return vertices dict, linedefs list, viewpoints list."""
    lumps = parse_wad_raw(path)

    vdata = lumps['VERTEXES']
    num_verts = len(vdata) // 8
    vertices = {}
    for i in range(num_verts):
        x, y = struct.unpack_from('<ii', vdata, i * 8)
        vertices[i] = (x, y)

    ldata = lumps['LINEDEFS']
    num_lines = len(ldata) // 16
    linedefs = []
    for i in range(num_lines):
        lid, v1, v2, fs, bs = struct.unpack_from('<iiihh', ldata, i * 16)
        linedefs.append({
            'id': lid, 'v1': v1, 'v2': v2,
            'front_sector': fs, 'back_sector': bs,
        })

    vpdata = lumps['VIEWPNTS']
    num_vp = len(vpdata) // 8
    viewpoints = []
    for i in range(num_vp):
        x, y = struct.unpack_from('<ii', vpdata, i * 8)
        viewpoints.append({'x': x, 'y': y})

    return vertices, linedefs, viewpoints


# --- BSP Geometry ---

class Seg:
    __slots__ = ('x1', 'y1', 'x2', 'y2',
                 'linedef_id', 'front_sector', 'back_sector')

    def __init__(self, x1, y1, x2, y2, linedef_id, front_sector, back_sector):
        self.x1 = float(x1)
        self.y1 = float(y1)
        self.x2 = float(x2)
        self.y2 = float(y2)
        self.linedef_id = linedef_id
        self.front_sector = front_sector
        self.back_sector = back_sector


def compute_normal(x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    length = math.sqrt(dx * dx + dy * dy)
    if length < EPSILON:
        return 0.0, 0.0, 0.0
    nx = -dy / length
    ny = dx / length
    d = -(nx * x1 + ny * y1)
    return nx, ny, d


def point_side_dist(nx, ny, d, px, py):
    return nx * px + ny * py + d


def classify_seg(nx, ny, d, seg):
    d1 = point_side_dist(nx, ny, d, seg.x1, seg.y1)
    d2 = point_side_dist(nx, ny, d, seg.x2, seg.y2)
    on1 = abs(d1) <= EPSILON
    on2 = abs(d2) <= EPSILON
    if on1 and on2:
        return 'on'
    if on1:
        return 'front' if d2 > EPSILON else 'back'
    if on2:
        return 'front' if d1 > EPSILON else 'back'
    if d1 > EPSILON and d2 > EPSILON:
        return 'front'
    if d1 < -EPSILON and d2 < -EPSILON:
        return 'back'
    return 'spanning'


def split_seg(nx, ny, d, seg):
    d1 = point_side_dist(nx, ny, d, seg.x1, seg.y1)
    d2 = point_side_dist(nx, ny, d, seg.x2, seg.y2)
    t = d1 / (d1 - d2)
    ix = seg.x1 + t * (seg.x2 - seg.x1)
    iy = seg.y1 + t * (seg.y2 - seg.y1)
    if d1 >= 0:
        front = Seg(seg.x1, seg.y1, ix, iy,
                    seg.linedef_id, seg.front_sector, seg.back_sector)
        back = Seg(ix, iy, seg.x2, seg.y2,
                   seg.linedef_id, seg.front_sector, seg.back_sector)
    else:
        front = Seg(ix, iy, seg.x2, seg.y2,
                    seg.linedef_id, seg.front_sector, seg.back_sector)
        back = Seg(seg.x1, seg.y1, ix, iy,
                   seg.linedef_id, seg.front_sector, seg.back_sector)
    return front, back


def is_convex(segs):
    for i, s in enumerate(segs):
        nx, ny, d = compute_normal(s.x1, s.y1, s.x2, s.y2)
        if abs(nx) < EPSILON and abs(ny) < EPSILON:
            continue
        has_front = False
        has_back = False
        for j, other in enumerate(segs):
            if i == j:
                continue
            cls = classify_seg(nx, ny, d, other)
            if cls in ('front', 'spanning'):
                has_front = True
            if cls in ('back', 'spanning'):
                has_back = True
            if has_front and has_back:
                return False
    return True


def score_splitter(segs, idx):
    s = segs[idx]
    nx, ny, d = compute_normal(s.x1, s.y1, s.x2, s.y2)
    if abs(nx) < EPSILON and abs(ny) < EPSILON:
        return float('inf'), False
    front_count = 0
    back_count = 0
    split_count = 0
    for j, other in enumerate(segs):
        if j == idx:
            continue
        cls = classify_seg(nx, ny, d, other)
        if cls == 'front':
            front_count += 1
        elif cls == 'back':
            back_count += 1
        elif cls == 'spanning':
            split_count += 1
            front_count += 1
            back_count += 1
    if back_count == 0:
        return float('inf'), False
    score = split_count * SPLIT_PENALTY + abs(front_count - back_count)
    return score, True


_subsector_counter = 0


def next_subsector_id():
    global _subsector_counter
    sid = _subsector_counter
    _subsector_counter += 1
    return sid


def seg_to_dict(seg):
    return {
        'x1': seg.x1, 'y1': seg.y1,
        'x2': seg.x2, 'y2': seg.y2,
        'linedef_id': seg.linedef_id,
        'front_sector': seg.front_sector,
        'back_sector': seg.back_sector,
    }


def build_bsp(segs, depth=0):
    if not segs:
        return {
            'type': 'leaf',
            'subsector_id': next_subsector_id(),
            'segs': [],
        }
    if is_convex(segs):
        return {
            'type': 'leaf',
            'subsector_id': next_subsector_id(),
            'segs': [seg_to_dict(s) for s in segs],
        }

    best_idx = -1
    best_score = float('inf')
    for i in range(len(segs)):
        score, valid = score_splitter(segs, i)
        if valid and score < best_score:
            best_score = score
            best_idx = i

    if best_idx == -1:
        return {
            'type': 'leaf',
            'subsector_id': next_subsector_id(),
            'segs': [seg_to_dict(s) for s in segs],
        }

    splitter = segs[best_idx]
    nx, ny, d = compute_normal(
        splitter.x1, splitter.y1, splitter.x2, splitter.y2
    )

    front_segs = []
    back_segs = []
    for s in segs:
        cls = classify_seg(nx, ny, d, s)
        if cls in ('front', 'on'):
            front_segs.append(s)
        elif cls == 'back':
            back_segs.append(s)
        elif cls == 'spanning':
            f, b = split_seg(nx, ny, d, s)
            front_segs.append(f)
            back_segs.append(b)

    if not front_segs or not back_segs:
        all_segs = front_segs or back_segs
        return {
            'type': 'leaf',
            'subsector_id': next_subsector_id(),
            'segs': [seg_to_dict(s) for s in all_segs],
        }

    return {
        'type': 'node',
        'split_line': {
            'x1': splitter.x1, 'y1': splitter.y1,
            'x2': splitter.x2, 'y2': splitter.y2,
        },
        'front': build_bsp(front_segs, depth + 1),
        'back': build_bsp(back_segs, depth + 1),
    }


# --- Polygon Reconstruction ---

def clip_polygon(polygon, nx, ny, d, keep_front):
    """Clip convex polygon by half-plane using Sutherland-Hodgman."""
    if not polygon:
        return []
    output = []
    n = len(polygon)
    for i in range(n):
        curr = polygon[i]
        nxt = polygon[(i + 1) % n]
        dc = nx * curr[0] + ny * curr[1] + d
        dn = nx * nxt[0] + ny * nxt[1] + d
        if keep_front:
            c_in = dc >= -EPSILON
            n_in = dn >= -EPSILON
        else:
            c_in = dc <= EPSILON
            n_in = dn <= EPSILON
        if c_in:
            output.append(curr)
        if c_in != n_in:
            denom = dc - dn
            if abs(denom) > EPSILON:
                t = dc / denom
                ix = curr[0] + t * (nxt[0] - curr[0])
                iy = curr[1] + t * (nxt[1] - curr[1])
                output.append((ix, iy))
    return output


def polygon_area(poly):
    """Signed area (positive for CCW)."""
    n = len(poly)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += poly[i][0] * poly[j][1]
        area -= poly[j][0] * poly[i][1]
    return area / 2.0


def ensure_ccw(poly):
    if polygon_area(poly) < 0:
        poly = list(reversed(poly))
    return poly


def deduplicate(poly, tol=0.01):
    if len(poly) <= 2:
        return poly
    result = [poly[0]]
    for i in range(1, len(poly)):
        dx = poly[i][0] - result[-1][0]
        dy = poly[i][1] - result[-1][1]
        if dx * dx + dy * dy > tol * tol:
            result.append(poly[i])
    if len(result) > 1:
        dx = result[-1][0] - result[0][0]
        dy = result[-1][1] - result[0][1]
        if dx * dx + dy * dy <= tol * tol:
            result.pop()
    return result


def remove_collinear(poly, tol=0.1):
    if len(poly) <= 3:
        return poly
    result = []
    n = len(poly)
    for i in range(n):
        p0 = poly[(i - 1) % n]
        p1 = poly[i]
        p2 = poly[(i + 1) % n]
        cross = ((p1[0] - p0[0]) * (p2[1] - p0[1]) -
                 (p1[1] - p0[1]) * (p2[0] - p0[0]))
        if abs(cross) > tol:
            result.append(p1)
    return result if len(result) >= 3 else poly


def add_polygons(tree, bbox):
    """Reconstruct convex polygon for each leaf by clipping AABB through ancestor planes."""
    min_x, min_y, max_x, max_y = bbox
    initial = [
        (float(min_x), float(min_y)),
        (float(max_x), float(min_y)),
        (float(max_x), float(max_y)),
        (float(min_x), float(max_y)),
    ]
    _add_poly_recursive(tree, initial)


def _add_poly_recursive(node, polygon):
    if node['type'] == 'leaf':
        poly = ensure_ccw(polygon)
        poly = deduplicate(poly)
        poly = remove_collinear(poly)
        node['polygon'] = [[round(p[0], 4), round(p[1], 4)] for p in poly]
        return

    sl = node['split_line']
    nx, ny, d = compute_normal(sl['x1'], sl['y1'], sl['x2'], sl['y2'])

    front_poly = clip_polygon(polygon, nx, ny, d, keep_front=True)
    back_poly = clip_polygon(polygon, nx, ny, d, keep_front=False)

    _add_poly_recursive(node['front'], front_poly)
    _add_poly_recursive(node['back'], back_poly)


# --- Adjacency Computation ---

def find_shared_edge(poly_a, poly_b, tol=1.0):
    """Find the longest shared collinear edge between two polygons."""
    best = None
    best_len = 0.0

    for i in range(len(poly_a)):
        a1 = poly_a[i]
        a2 = poly_a[(i + 1) % len(poly_a)]
        ea_dx = a2[0] - a1[0]
        ea_dy = a2[1] - a1[1]
        ea_len = math.sqrt(ea_dx ** 2 + ea_dy ** 2)
        if ea_len < 0.1:
            continue

        for j in range(len(poly_b)):
            b1 = poly_b[j]
            b2 = poly_b[(j + 1) % len(poly_b)]
            eb_len = math.sqrt((b2[0] - b1[0]) ** 2 + (b2[1] - b1[1]) ** 2)
            if eb_len < 0.1:
                continue

            # Check collinearity
            cross1 = abs((b1[0] - a1[0]) * ea_dy -
                         (b1[1] - a1[1]) * ea_dx) / ea_len
            cross2 = abs((b2[0] - a1[0]) * ea_dy -
                         (b2[1] - a1[1]) * ea_dx) / ea_len
            if cross1 > tol or cross2 > tol:
                continue

            # Project b endpoints onto a's direction
            t_b1 = ((b1[0] - a1[0]) * ea_dx +
                     (b1[1] - a1[1]) * ea_dy) / (ea_len ** 2)
            t_b2 = ((b2[0] - a1[0]) * ea_dx +
                     (b2[1] - a1[1]) * ea_dy) / (ea_len ** 2)

            ov_start = max(0.0, min(t_b1, t_b2))
            ov_end = min(1.0, max(t_b1, t_b2))
            ov_len = (ov_end - ov_start) * ea_len

            if ov_len > tol and ov_len > best_len:
                sx = a1[0] + ov_start * ea_dx
                sy = a1[1] + ov_start * ea_dy
                ex = a1[0] + ov_end * ea_dx
                ey = a1[1] + ov_end * ea_dy
                best = [[round(sx, 4), round(sy, 4)],
                        [round(ex, 4), round(ey, 4)]]
                best_len = ov_len

    return best


def compute_adjacency(tree):
    """Compute subsector adjacency from shared polygon edges."""
    leaves = []
    stack = [tree]
    while stack:
        node = stack.pop()
        if node['type'] == 'leaf':
            leaves.append(node)
        else:
            stack.append(node['front'])
            stack.append(node['back'])

    adjacency = []
    for i in range(len(leaves)):
        for j in range(i + 1, len(leaves)):
            edge = find_shared_edge(leaves[i]['polygon'],
                                    leaves[j]['polygon'])
            if edge is not None:
                a_id = leaves[i]['subsector_id']
                b_id = leaves[j]['subsector_id']
                if a_id > b_id:
                    a_id, b_id = b_id, a_id
                adjacency.append({
                    'subsector_a': a_id,
                    'subsector_b': b_id,
                    'shared_edge': edge,
                })

    adjacency.sort(key=lambda x: (x['subsector_a'], x['subsector_b']))
    return adjacency


# --- Traversal ---

def traverse(node, px, py):
    if node['type'] == 'leaf':
        return [node['subsector_id']]
    sl = node['split_line']
    nx, ny, d = compute_normal(sl['x1'], sl['y1'], sl['x2'], sl['y2'])
    dist = point_side_dist(nx, ny, d, px, py)
    if dist >= 0:
        order = traverse(node['front'], px, py)
        order.extend(traverse(node['back'], px, py))
    else:
        order = traverse(node['back'], px, py)
        order.extend(traverse(node['front'], px, py))
    return order


# --- Binary WAD Output ---

def write_binary_wad(tree, output_path):
    """Serialize BSP tree into a PWAD with NODES, SEGS, SSECTORS lumps."""
    nodes_list = []
    segs_list = []
    ssectors_list = []

    def build_node_list(node):
        if node['type'] == 'leaf':
            ss_segs = node['segs']
            first_seg = len(segs_list)
            for seg in ss_segs:
                segs_list.append({
                    'x1': seg['x1'], 'y1': seg['y1'],
                    'x2': seg['x2'], 'y2': seg['y2'],
                    'linedef_id': seg['linedef_id'],
                    'subsector_id': node['subsector_id'],
                })
            ssectors_list.append({
                'subsector_id': node['subsector_id'],
                'num_segs': len(ss_segs),
                'first_seg_index': first_seg,
            })
            return -(node['subsector_id'] + 1)

        my_index = len(nodes_list)
        nodes_list.append(None)

        front_child = build_node_list(node['front'])
        back_child = build_node_list(node['back'])

        sl = node['split_line']
        nodes_list[my_index] = {
            'x1': sl['x1'], 'y1': sl['y1'],
            'x2': sl['x2'], 'y2': sl['y2'],
            'front_child': front_child,
            'back_child': back_child,
        }
        return my_index

    build_node_list(tree)
    ssectors_list.sort(key=lambda x: x['subsector_id'])

    nodes_data = b''
    for n in nodes_list:
        nodes_data += struct.pack('<ffffii',
                                  n['x1'], n['y1'], n['x2'], n['y2'],
                                  n['front_child'], n['back_child'])

    segs_data = b''
    for s in segs_list:
        segs_data += struct.pack('<ffffii',
                                 s['x1'], s['y1'], s['x2'], s['y2'],
                                 s['linedef_id'], s['subsector_id'])

    ss_data = b''
    for ss in ssectors_list:
        ss_data += struct.pack('<iii',
                               ss['subsector_id'], ss['num_segs'],
                               ss['first_seg_index'])

    lumps = [
        ('NODES', nodes_data),
        ('SEGS', segs_data),
        ('SSECTORS', ss_data),
    ]

    header_size = 12
    current_offset = header_size
    all_data = b''
    entries = []
    for name, data in lumps:
        entries.append((current_offset, len(data), name))
        all_data += data
        current_offset += len(data)
    dir_offset = current_offset

    with open(output_path, 'wb') as f:
        f.write(struct.pack('<4sii', b'PWAD', len(lumps), dir_offset))
        f.write(all_data)
        for offset, size, name in entries:
            f.write(struct.pack('<ii8s', offset, size,
                    name.encode('ascii').ljust(8, b'\x00')[:8]))


# --- Graphviz Visualization ---

def generate_dot(tree):
    """Generate a Graphviz DOT description of the BSP tree."""
    lines = ['digraph bsp_tree {']
    lines.append('    rankdir=TB;')
    lines.append('    node [fontname="Courier", fontsize=9];')
    lines.append('    edge [fontname="Courier", fontsize=8];')

    counter = [0]

    def visit(node):
        nid = counter[0]
        counter[0] += 1
        name = f'n{nid}'

        if node['type'] == 'leaf':
            nseg = len(node['segs'])
            label = f'SS {node["subsector_id"]}\\n{nseg} segs'
            lines.append(
                f'    {name} [shape=ellipse, style=filled, '
                f'fillcolor=lightblue, label="{label}"];'
            )
            return name

        sl = node['split_line']
        label = (f'({sl["x1"]:.1f},{sl["y1"]:.1f})-'
                 f'({sl["x2"]:.1f},{sl["y2"]:.1f})')
        lines.append(f'    {name} [shape=box, label="{label}"];')

        front_name = visit(node['front'])
        back_name = visit(node['back'])

        lines.append(f'    {name} -> {front_name} [label="front"];')
        lines.append(f'    {name} -> {back_name} [label="back"];')

        return name

    visit(tree)
    lines.append('}')
    return '\n'.join(lines) + '\n'


# --- Main ---

def main():
    vertices, linedefs, viewpoints = parse_input_wad('/app/map.wad')

    # Build initial segs from linedefs
    segs = []
    for ld in linedefs:
        v1 = vertices[ld['v1']]
        v2 = vertices[ld['v2']]
        segs.append(Seg(
            v1[0], v1[1], v2[0], v2[1],
            ld['id'], ld['front_sector'], ld['back_sector'],
        ))

    # Compute map AABB
    all_x = [v[0] for v in vertices.values()]
    all_y = [v[1] for v in vertices.values()]
    bbox = (min(all_x), min(all_y), max(all_x), max(all_y))

    # Build BSP tree
    tree = build_bsp(segs)

    # Reconstruct convex polygons for each leaf
    add_polygons(tree, bbox)

    # Compute subsector adjacency graph
    adj = compute_adjacency(tree)

    # Compute traversals
    traversals = []
    for vp in viewpoints:
        order = traverse(tree, vp['x'], vp['y'])
        traversals.append({
            'viewpoint': {'x': vp['x'], 'y': vp['y']},
            'subsector_order': order,
        })

    # Write outputs
    os.makedirs('/app/output', exist_ok=True)

    with open('/app/output/bsp_tree.json', 'w') as f:
        json.dump(tree, f, indent=2)

    with open('/app/output/traversals.json', 'w') as f:
        json.dump({'traversals': traversals}, f, indent=2)

    with open('/app/output/adjacency.json', 'w') as f:
        json.dump({'adjacency': adj}, f, indent=2)

    write_binary_wad(tree, '/app/output/bsp_output.wad')

    dot_content = generate_dot(tree)
    dot_path = '/app/output/bsp_tree.dot'
    svg_path = '/app/output/bsp_tree.svg'
    with open(dot_path, 'w') as f:
        f.write(dot_content)
    subprocess.run(
        ['dot', '-Tsvg', '-o', svg_path, dot_path],
        check=True,
    )

    # Summary
    leaves = []
    stack = [tree]
    while stack:
        node = stack.pop()
        if node['type'] == 'leaf':
            leaves.append(node)
        else:
            stack.append(node['front'])
            stack.append(node['back'])
    total_segs = sum(len(leaf['segs']) for leaf in leaves)
    total_poly_area = sum(
        abs(polygon_area([(p[0], p[1]) for p in leaf['polygon']]))
        for leaf in leaves
    )
    bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    print(f"BSP compiled: {len(leaves)} subsectors, {total_segs} segs, "
          f"{len(adj)} adjacencies, {len(viewpoints)} traversals.")
    print(f"Polygon area: {total_poly_area:.2f} / AABB: {bbox_area:.2f} "
          f"({total_poly_area / bbox_area * 100:.2f}%)")


if __name__ == '__main__':
    main()
