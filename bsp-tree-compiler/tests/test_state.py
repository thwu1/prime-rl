"""
Tests for BSP tree compiler output verification.
Verifies JSON structure, segment conservation, partition correctness,
traversal ordering, convex polygon reconstruction, adjacency graph,
binary WAD output, and SVG visualization.
"""

import json
import math
import os
import struct
from collections import defaultdict

import pytest

TOLERANCE = 0.5


# --- WAD parsing utilities ---

def parse_wad(path):
    """Parse a PWAD file and return dict of lump_name -> raw bytes."""
    with open(path, 'rb') as f:
        data = f.read()
    magic = data[0:4]
    assert magic == b'PWAD', f"Invalid WAD magic: {magic!r}"
    num_lumps, dir_offset = struct.unpack_from('<ii', data, 4)
    lumps = {}
    for i in range(num_lumps):
        base = dir_offset + i * 16
        lump_off, lump_sz = struct.unpack_from('<ii', data, base)
        name = data[base + 8:base + 16].rstrip(b'\x00').decode('ascii')
        lumps[name] = data[lump_off:lump_off + lump_sz]
    return lumps


def parse_vertices_lump(data):
    count = len(data) // 8
    vertices = []
    for i in range(count):
        x, y = struct.unpack_from('<ii', data, i * 8)
        vertices.append({'id': i, 'x': x, 'y': y})
    return vertices


def parse_linedefs_lump(data):
    count = len(data) // 16
    linedefs = []
    for i in range(count):
        lid, v1, v2, fs, bs = struct.unpack_from('<iiihh', data, i * 16)
        linedefs.append({
            'id': lid, 'v1': v1, 'v2': v2,
            'front_sector': fs, 'back_sector': bs,
        })
    return linedefs


def parse_viewpoints_lump(data):
    count = len(data) // 8
    viewpoints = []
    for i in range(count):
        x, y = struct.unpack_from('<ii', data, i * 8)
        viewpoints.append({'x': x, 'y': y})
    return viewpoints


# --- JSON helpers ---

def load_json(path):
    with open(path) as f:
        return json.load(f)


def compute_split_plane(split_line):
    x1, y1 = split_line['x1'], split_line['y1']
    x2, y2 = split_line['x2'], split_line['y2']
    dx, dy = x2 - x1, y2 - y1
    length = math.sqrt(dx * dx + dy * dy)
    assert length > 1e-12, "Degenerate split line with zero length"
    nx = -dy / length
    ny = dx / length
    d = -(nx * x1 + ny * y1)
    return nx, ny, d


def point_side_dist(nx, ny, d, px, py):
    return nx * px + ny * py + d


def seg_length(seg):
    dx = seg['x2'] - seg['x1']
    dy = seg['y2'] - seg['y1']
    return math.sqrt(dx * dx + dy * dy)


def collect_leaves(node):
    if node['type'] == 'leaf':
        return [node]
    return collect_leaves(node['front']) + collect_leaves(node['back'])


def count_internal_nodes(node):
    if node['type'] == 'leaf':
        return 0
    return 1 + count_internal_nodes(node['front']) + count_internal_nodes(node['back'])


def bsp_traverse(node, px, py):
    if node['type'] == 'leaf':
        return [node['subsector_id']]
    nx, ny, d = compute_split_plane(node['split_line'])
    dist = point_side_dist(nx, ny, d, px, py)
    if dist >= 0:
        result = bsp_traverse(node['front'], px, py)
        result.extend(bsp_traverse(node['back'], px, py))
    else:
        result = bsp_traverse(node['back'], px, py)
        result.extend(bsp_traverse(node['front'], px, py))
    return result


# --- Polygon helpers ---

def polygon_area_signed(poly):
    """Compute signed area (positive for CCW)."""
    n = len(poly)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += poly[i][0] * poly[j][1]
        area -= poly[j][0] * poly[i][1]
    return area / 2.0


def polygon_area_abs(poly):
    return abs(polygon_area_signed(poly))


def point_in_convex_polygon(px, py, poly, tolerance=2.0):
    """Check if point is inside or on boundary of convex CCW polygon."""
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i][0], poly[i][1]
        x2, y2 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        # Cross product: positive means left of edge (inside for CCW)
        cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
        if cross < -tolerance:
            return False
    return True


def point_on_polygon_boundary(px, py, poly, tolerance=2.0):
    """Check if point is near any edge of the polygon."""
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i][0], poly[i][1]
        x2, y2 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        dx, dy = x2 - x1, y2 - y1
        seg_len = math.sqrt(dx * dx + dy * dy)
        if seg_len < 1e-9:
            continue
        cross = abs((px - x1) * dy - (py - y1) * dx) / seg_len
        if cross > tolerance:
            continue
        t = ((px - x1) * dx + (py - y1) * dy) / (seg_len * seg_len)
        if -0.02 <= t <= 1.02:
            return True
    return False


# --- Fixtures ---

@pytest.fixture(scope='module')
def map_data():
    lumps = parse_wad('/app/map.wad')
    vertices = parse_vertices_lump(lumps['VERTEXES'])
    linedefs = parse_linedefs_lump(lumps['LINEDEFS'])
    return {'vertices': vertices, 'linedefs': linedefs}


@pytest.fixture(scope='module')
def viewpoints():
    lumps = parse_wad('/app/map.wad')
    return parse_viewpoints_lump(lumps['VIEWPNTS'])


@pytest.fixture(scope='module')
def bsp_tree():
    return load_json('/app/output/bsp_tree.json')


@pytest.fixture(scope='module')
def traversals():
    return load_json('/app/output/traversals.json')


@pytest.fixture(scope='module')
def adjacency():
    return load_json('/app/output/adjacency.json')


@pytest.fixture(scope='module')
def output_wad_lumps():
    return parse_wad('/app/output/bsp_output.wad')


# --- Test Classes ---

class TestOutputExists:
    def test_bsp_tree_file(self):
        assert os.path.isfile('/app/output/bsp_tree.json'), \
            "Missing /app/output/bsp_tree.json"

    def test_traversals_file(self):
        assert os.path.isfile('/app/output/traversals.json'), \
            "Missing /app/output/traversals.json"

    def test_adjacency_file(self):
        assert os.path.isfile('/app/output/adjacency.json'), \
            "Missing /app/output/adjacency.json"

    def test_binary_wad_file(self):
        assert os.path.isfile('/app/output/bsp_output.wad'), \
            "Missing /app/output/bsp_output.wad"

    def test_svg_file(self):
        assert os.path.isfile('/app/output/bsp_tree.svg'), \
            "Missing /app/output/bsp_tree.svg"


class TestBSPTreeStructure:
    def _verify_node(self, node, depth=0):
        assert 'type' in node, f"Node at depth {depth} missing 'type' field"
        if node['type'] == 'node':
            assert 'split_line' in node, "Internal node missing 'split_line'"
            sl = node['split_line']
            for k in ('x1', 'y1', 'x2', 'y2'):
                assert k in sl, f"split_line missing '{k}'"
                assert isinstance(sl[k], (int, float)), \
                    f"split_line['{k}'] must be numeric"
            dx = sl['x2'] - sl['x1']
            dy = sl['y2'] - sl['y1']
            assert math.sqrt(dx * dx + dy * dy) > 1e-9, \
                "split_line has zero length"
            assert 'front' in node, "Internal node missing 'front' child"
            assert 'back' in node, "Internal node missing 'back' child"
            self._verify_node(node['front'], depth + 1)
            self._verify_node(node['back'], depth + 1)
        elif node['type'] == 'leaf':
            assert 'subsector_id' in node, "Leaf missing 'subsector_id'"
            assert isinstance(node['subsector_id'], int), \
                "subsector_id must be an integer"
            assert node['subsector_id'] >= 0, "subsector_id must be non-negative"
            assert 'segs' in node, "Leaf missing 'segs'"
            assert isinstance(node['segs'], list), "'segs' must be a list"
            assert len(node['segs']) > 0, "Leaf has empty segs list"
            for seg in node['segs']:
                for k in ('x1', 'y1', 'x2', 'y2', 'linedef_id'):
                    assert k in seg, f"Seg missing required key '{k}'"
                slen = seg_length(seg)
                assert slen > 1e-9, \
                    f"Degenerate seg with near-zero length {slen}"
            assert 'polygon' in node, \
                f"Leaf subsector {node['subsector_id']} missing 'polygon' field"
            assert isinstance(node['polygon'], list), "'polygon' must be a list"
        else:
            pytest.fail(f"Invalid node type: {node['type']}")

    def test_valid_structure(self, bsp_tree):
        self._verify_node(bsp_tree)


class TestSubsectorIDs:
    def test_unique_ids(self, bsp_tree):
        leaves = collect_leaves(bsp_tree)
        ids = [leaf['subsector_id'] for leaf in leaves]
        assert len(ids) == len(set(ids)), \
            f"Duplicate subsector IDs found: " \
            f"{sorted(x for x in ids if ids.count(x) > 1)}"

    def test_multiple_leaves(self, bsp_tree):
        leaves = collect_leaves(bsp_tree)
        assert len(leaves) >= 2, \
            "BSP tree must have at least 2 leaf subsectors"


class TestSegConservation:
    def test_all_linedefs_covered(self, bsp_tree, map_data):
        leaves = collect_leaves(bsp_tree)
        covered_ids = set()
        for leaf in leaves:
            for seg in leaf['segs']:
                covered_ids.add(seg['linedef_id'])
        for ld in map_data['linedefs']:
            assert ld['id'] in covered_ids, \
                f"Linedef {ld['id']} has no segs in BSP tree"

    def test_length_conservation(self, bsp_tree, map_data):
        vertices = {v['id']: v for v in map_data['vertices']}
        leaves = collect_leaves(bsp_tree)
        seg_groups = defaultdict(list)
        for leaf in leaves:
            for seg in leaf['segs']:
                seg_groups[seg['linedef_id']].append(seg)
        for ld in map_data['linedefs']:
            v1 = vertices[ld['v1']]
            v2 = vertices[ld['v2']]
            expected = math.sqrt(
                (v2['x'] - v1['x']) ** 2 + (v2['y'] - v1['y']) ** 2
            )
            segs = seg_groups.get(ld['id'], [])
            actual = sum(seg_length(s) for s in segs)
            assert abs(actual - expected) < 1.0, \
                f"Linedef {ld['id']}: seg total length {actual:.4f} != " \
                f"expected {expected:.4f}"

    def test_seg_endpoints_on_linedef(self, bsp_tree, map_data):
        vertices = {v['id']: v for v in map_data['vertices']}
        leaves = collect_leaves(bsp_tree)
        linedef_map = {}
        for ld in map_data['linedefs']:
            v1 = vertices[ld['v1']]
            v2 = vertices[ld['v2']]
            linedef_map[ld['id']] = (v1['x'], v1['y'], v2['x'], v2['y'])
        for leaf in leaves:
            for seg in leaf['segs']:
                lid = seg['linedef_id']
                assert lid in linedef_map, f"Unknown linedef_id {lid}"
                lx1, ly1, lx2, ly2 = linedef_map[lid]
                dx, dy = lx2 - lx1, ly2 - ly1
                line_len = math.sqrt(dx * dx + dy * dy)
                for px, py in [(seg['x1'], seg['y1']),
                               (seg['x2'], seg['y2'])]:
                    cross = abs((px - lx1) * dy - (py - ly1) * dx)
                    assert cross < line_len * 0.01, \
                        f"Seg endpoint ({px:.4f},{py:.4f}) not on " \
                        f"linedef {lid} (cross={cross:.4f})"


class TestPartitionCorrectness:
    def _verify(self, node, constraints):
        if node['type'] == 'leaf':
            for seg in node['segs']:
                for px, py in [(seg['x1'], seg['y1']),
                               (seg['x2'], seg['y2'])]:
                    for nx, ny, d, side in constraints:
                        dist = point_side_dist(nx, ny, d, px, py)
                        if side == 'front':
                            assert dist > -TOLERANCE, \
                                f"({px:.2f},{py:.2f}) dist={dist:.4f} " \
                                f"but should be on front side"
                        else:
                            assert dist < TOLERANCE, \
                                f"({px:.2f},{py:.2f}) dist={dist:.4f} " \
                                f"but should be on back side"
        else:
            nx, ny, d = compute_split_plane(node['split_line'])
            self._verify(node['front'],
                         constraints + [(nx, ny, d, 'front')])
            self._verify(node['back'],
                         constraints + [(nx, ny, d, 'back')])

    def test_partition(self, bsp_tree):
        self._verify(bsp_tree, [])


class TestTraversals:
    def test_traversal_count(self, traversals, viewpoints):
        assert len(traversals['traversals']) == len(viewpoints), \
            f"Expected {len(viewpoints)} traversals, " \
            f"got {len(traversals['traversals'])}"

    def test_traversal_completeness(self, bsp_tree, traversals):
        leaves = collect_leaves(bsp_tree)
        expected_ids = sorted([leaf['subsector_id'] for leaf in leaves])
        for i, trav in enumerate(traversals['traversals']):
            actual_ids = sorted(trav['subsector_order'])
            assert actual_ids == expected_ids, \
                f"Traversal {i}: expected subsectors {expected_ids}, " \
                f"got {actual_ids}"

    def test_traversal_ordering(self, bsp_tree, traversals, viewpoints):
        for i, vp in enumerate(viewpoints):
            expected = bsp_traverse(bsp_tree, vp['x'], vp['y'])
            actual = traversals['traversals'][i]['subsector_order']
            assert expected == actual, \
                f"Traversal {i} at ({vp['x']},{vp['y']}): " \
                f"order mismatch.\n  Expected: {expected}\n  Got: {actual}"

    def test_viewpoint_coordinates_match(self, traversals, viewpoints):
        for i, vp in enumerate(viewpoints):
            trav_vp = traversals['traversals'][i]['viewpoint']
            assert abs(trav_vp['x'] - vp['x']) < 0.01, \
                f"Traversal {i}: viewpoint x mismatch"
            assert abs(trav_vp['y'] - vp['y']) < 0.01, \
                f"Traversal {i}: viewpoint y mismatch"


class TestConvexPolygons:
    """Verify convex polygon reconstruction for each leaf subsector."""

    def test_polygon_min_vertices(self, bsp_tree):
        leaves = collect_leaves(bsp_tree)
        for leaf in leaves:
            poly = leaf['polygon']
            assert isinstance(poly, list) and len(poly) >= 3, \
                f"Subsector {leaf['subsector_id']}: polygon needs >= 3 vertices, " \
                f"got {len(poly) if isinstance(poly, list) else type(poly)}"

    def test_polygon_vertex_format(self, bsp_tree):
        leaves = collect_leaves(bsp_tree)
        for leaf in leaves:
            for i, v in enumerate(leaf['polygon']):
                assert isinstance(v, list) and len(v) == 2, \
                    f"Subsector {leaf['subsector_id']}: polygon vertex {i} " \
                    f"must be [x, y], got {v}"
                assert isinstance(v[0], (int, float)) and isinstance(v[1], (int, float)), \
                    f"Subsector {leaf['subsector_id']}: polygon vertex {i} " \
                    f"coordinates must be numeric"

    def test_polygon_is_convex_ccw(self, bsp_tree):
        leaves = collect_leaves(bsp_tree)
        for leaf in leaves:
            poly = leaf['polygon']
            n = len(poly)
            for i in range(n):
                p0 = poly[i]
                p1 = poly[(i + 1) % n]
                p2 = poly[(i + 2) % n]
                cross = ((p1[0] - p0[0]) * (p2[1] - p0[1]) -
                         (p1[1] - p0[1]) * (p2[0] - p0[0]))
                assert cross >= -TOLERANCE, \
                    f"Subsector {leaf['subsector_id']}: polygon not convex/CCW " \
                    f"at vertex {i} (cross={cross:.4f})"

    def test_polygon_positive_area(self, bsp_tree):
        leaves = collect_leaves(bsp_tree)
        for leaf in leaves:
            area = polygon_area_abs(leaf['polygon'])
            assert area > 1.0, \
                f"Subsector {leaf['subsector_id']}: polygon area {area:.4f} too small"

    def test_segs_inside_polygon(self, bsp_tree):
        leaves = collect_leaves(bsp_tree)
        for leaf in leaves:
            poly = leaf['polygon']
            for seg in leaf['segs']:
                for px, py in [(seg['x1'], seg['y1']),
                               (seg['x2'], seg['y2'])]:
                    assert point_in_convex_polygon(px, py, poly), \
                        f"Subsector {leaf['subsector_id']}: seg endpoint " \
                        f"({px:.2f},{py:.2f}) outside polygon"


class TestPolygonPartition:
    """Verify that polygons partition the map bounding box."""

    def test_area_conservation(self, bsp_tree, map_data):
        vertices = map_data['vertices']
        xs = [v['x'] for v in vertices]
        ys = [v['y'] for v in vertices]
        bbox_area = float((max(xs) - min(xs)) * (max(ys) - min(ys)))

        leaves = collect_leaves(bsp_tree)
        total_area = sum(polygon_area_abs(leaf['polygon']) for leaf in leaves)

        assert abs(total_area - bbox_area) < bbox_area * 0.01, \
            f"Total polygon area {total_area:.2f} != bbox area {bbox_area:.2f} " \
            f"(diff={abs(total_area - bbox_area):.2f}, " \
            f"threshold={bbox_area * 0.01:.2f})"

    def test_polygon_count_matches_leaves(self, bsp_tree):
        leaves = collect_leaves(bsp_tree)
        with_poly = [lf for lf in leaves if 'polygon' in lf]
        assert len(with_poly) == len(leaves), \
            f"Only {len(with_poly)}/{len(leaves)} leaves have polygon fields"


class TestAdjacencyGraph:
    """Verify subsector adjacency graph."""

    def test_adjacency_structure(self, adjacency):
        assert 'adjacency' in adjacency, \
            "adjacency.json missing 'adjacency' key"
        assert isinstance(adjacency['adjacency'], list), \
            "'adjacency' must be a list"

    def test_adjacency_canonical_pairs(self, adjacency):
        seen = set()
        for entry in adjacency['adjacency']:
            a = entry['subsector_a']
            b = entry['subsector_b']
            assert isinstance(a, int) and isinstance(b, int), \
                f"Subsector IDs must be integers, got {type(a)}, {type(b)}"
            assert a < b, \
                f"Adjacency pair ({a},{b}) not canonical (need a < b)"
            pair = (a, b)
            assert pair not in seen, \
                f"Duplicate adjacency pair ({a},{b})"
            seen.add(pair)

    def test_adjacency_ids_valid(self, bsp_tree, adjacency):
        leaves = collect_leaves(bsp_tree)
        valid_ids = {leaf['subsector_id'] for leaf in leaves}
        for entry in adjacency['adjacency']:
            assert entry['subsector_a'] in valid_ids, \
                f"Unknown subsector_a {entry['subsector_a']}"
            assert entry['subsector_b'] in valid_ids, \
                f"Unknown subsector_b {entry['subsector_b']}"

    def test_adjacency_connected(self, bsp_tree, adjacency):
        leaves = collect_leaves(bsp_tree)
        all_ids = {leaf['subsector_id'] for leaf in leaves}

        if len(all_ids) <= 1:
            return

        neighbors = defaultdict(set)
        for entry in adjacency['adjacency']:
            a, b = entry['subsector_a'], entry['subsector_b']
            neighbors[a].add(b)
            neighbors[b].add(a)

        start = min(all_ids)
        visited = {start}
        queue = [start]
        while queue:
            node = queue.pop(0)
            for n in neighbors.get(node, set()):
                if n not in visited:
                    visited.add(n)
                    queue.append(n)

        assert visited == all_ids, \
            f"Adjacency graph not connected: reached {sorted(visited)}, " \
            f"missing {sorted(all_ids - visited)}"

    def test_minimum_adjacency_count(self, bsp_tree, adjacency):
        leaves = collect_leaves(bsp_tree)
        k = len(leaves)
        assert len(adjacency['adjacency']) >= k - 1, \
            f"Only {len(adjacency['adjacency'])} adjacencies for {k} " \
            f"subsectors (need at least {k - 1} for connectivity)"

    def test_shared_edges_valid(self, adjacency):
        for entry in adjacency['adjacency']:
            edge = entry['shared_edge']
            assert isinstance(edge, list) and len(edge) == 2, \
                f"Shared edge must have 2 endpoints"
            assert len(edge[0]) == 2 and len(edge[1]) == 2, \
                f"Edge endpoints must be [x, y] pairs"
            dx = edge[1][0] - edge[0][0]
            dy = edge[1][1] - edge[0][1]
            edge_len = math.sqrt(dx * dx + dy * dy)
            assert edge_len > 0.5, \
                f"Degenerate shared edge between {entry['subsector_a']} " \
                f"and {entry['subsector_b']}: length {edge_len:.4f}"

    def test_shared_edges_on_polygon_boundaries(self, bsp_tree, adjacency):
        leaves = collect_leaves(bsp_tree)
        poly_map = {leaf['subsector_id']: leaf['polygon'] for leaf in leaves}

        for entry in adjacency['adjacency']:
            a_id = entry['subsector_a']
            b_id = entry['subsector_b']
            edge = entry['shared_edge']

            mx = (edge[0][0] + edge[1][0]) / 2.0
            my = (edge[0][1] + edge[1][1]) / 2.0

            assert a_id in poly_map, f"Unknown subsector {a_id}"
            assert b_id in poly_map, f"Unknown subsector {b_id}"

            assert point_on_polygon_boundary(mx, my, poly_map[a_id]), \
                f"Edge midpoint ({mx:.2f},{my:.2f}) not on subsector " \
                f"{a_id} polygon boundary"
            assert point_on_polygon_boundary(mx, my, poly_map[b_id]), \
                f"Edge midpoint ({mx:.2f},{my:.2f}) not on subsector " \
                f"{b_id} polygon boundary"


class TestBinaryWADOutput:
    """Verify the binary WAD output structure and consistency with JSON."""

    def test_wad_header_valid(self, output_wad_lumps):
        assert 'NODES' in output_wad_lumps, "Output WAD missing NODES lump"
        assert 'SEGS' in output_wad_lumps, "Output WAD missing SEGS lump"
        assert 'SSECTORS' in output_wad_lumps, "Output WAD missing SSECTORS lump"

    def test_nodes_record_size(self, output_wad_lumps):
        nodes_data = output_wad_lumps['NODES']
        assert len(nodes_data) % 24 == 0, \
            f"NODES lump size {len(nodes_data)} is not a multiple of 24"

    def test_segs_record_size(self, output_wad_lumps):
        segs_data = output_wad_lumps['SEGS']
        assert len(segs_data) % 24 == 0, \
            f"SEGS lump size {len(segs_data)} is not a multiple of 24"

    def test_ssectors_record_size(self, output_wad_lumps):
        ss_data = output_wad_lumps['SSECTORS']
        assert len(ss_data) % 12 == 0, \
            f"SSECTORS lump size {len(ss_data)} is not a multiple of 12"

    def test_nodes_count_matches_json(self, bsp_tree, output_wad_lumps):
        nodes_data = output_wad_lumps['NODES']
        num_nodes = len(nodes_data) // 24
        expected = count_internal_nodes(bsp_tree)
        assert num_nodes == expected, \
            f"NODES has {num_nodes} entries but BSP tree has {expected} internal nodes"

    def test_ssectors_count_matches_json(self, bsp_tree, output_wad_lumps):
        ss_data = output_wad_lumps['SSECTORS']
        num_ss = len(ss_data) // 12
        leaves = collect_leaves(bsp_tree)
        assert num_ss == len(leaves), \
            f"SSECTORS has {num_ss} entries but BSP tree has {len(leaves)} leaves"

    def test_segs_count_matches_json(self, bsp_tree, output_wad_lumps):
        segs_data = output_wad_lumps['SEGS']
        num_segs = len(segs_data) // 24
        leaves = collect_leaves(bsp_tree)
        total_segs = sum(len(leaf['segs']) for leaf in leaves)
        assert num_segs == total_segs, \
            f"SEGS has {num_segs} entries but BSP tree has {total_segs} segs"

    def test_ssectors_indexing_valid(self, output_wad_lumps):
        segs_data = output_wad_lumps['SEGS']
        ss_data = output_wad_lumps['SSECTORS']
        num_segs = len(segs_data) // 24
        num_ss = len(ss_data) // 12
        for i in range(num_ss):
            ss_id, ns, fsi = struct.unpack_from('<iii', ss_data, i * 12)
            assert ss_id >= 0, f"SSECTOR {i}: negative subsector_id {ss_id}"
            assert ns > 0, f"SSECTOR {i}: num_segs must be > 0, got {ns}"
            assert fsi >= 0, f"SSECTOR {i}: negative first_seg_index {fsi}"
            assert fsi + ns <= num_segs, \
                f"SSECTOR {i}: first_seg_index {fsi} + num_segs {ns} > total segs {num_segs}"

    def test_ssector_ids_match_json(self, bsp_tree, output_wad_lumps):
        ss_data = output_wad_lumps['SSECTORS']
        num_ss = len(ss_data) // 12
        binary_ids = set()
        for i in range(num_ss):
            ss_id = struct.unpack_from('<i', ss_data, i * 12)[0]
            binary_ids.add(ss_id)
        leaves = collect_leaves(bsp_tree)
        json_ids = {leaf['subsector_id'] for leaf in leaves}
        assert binary_ids == json_ids, \
            f"SSECTOR IDs mismatch: binary={sorted(binary_ids)}, json={sorted(json_ids)}"

    def test_nodes_child_encoding(self, output_wad_lumps):
        nodes_data = output_wad_lumps['NODES']
        ss_data = output_wad_lumps['SSECTORS']
        num_nodes = len(nodes_data) // 24
        num_ss = len(ss_data) // 12
        valid_ss_ids = set()
        for i in range(num_ss):
            ss_id = struct.unpack_from('<i', ss_data, i * 12)[0]
            valid_ss_ids.add(ss_id)
        for i in range(num_nodes):
            _, _, _, _, fc, bc = struct.unpack_from('<ffffii', nodes_data, i * 24)
            for child_name, child in [('front', fc), ('back', bc)]:
                if child >= 0:
                    assert child < num_nodes, \
                        f"Node {i} {child_name}: node index {child} >= {num_nodes}"
                else:
                    ss_id = -(child + 1)
                    assert ss_id in valid_ss_ids, \
                        f"Node {i} {child_name}: decoded subsector {ss_id} not in SSECTORS"

    def test_segs_linedef_ids_valid(self, map_data, output_wad_lumps):
        segs_data = output_wad_lumps['SEGS']
        num_segs = len(segs_data) // 24
        valid_ids = {ld['id'] for ld in map_data['linedefs']}
        for i in range(num_segs):
            _, _, _, _, lid, _ = struct.unpack_from('<ffffii', segs_data, i * 24)
            assert lid in valid_ids, \
                f"Seg {i}: linedef_id {lid} not in map linedefs"

    def test_root_node_matches_json(self, bsp_tree, output_wad_lumps):
        nodes_data = output_wad_lumps['NODES']
        x1, y1, x2, y2, _, _ = struct.unpack_from('<ffffii', nodes_data, 0)
        json_sl = bsp_tree['split_line']
        assert abs(x1 - json_sl['x1']) < 0.5, \
            f"Root split x1: binary={x1}, json={json_sl['x1']}"
        assert abs(y1 - json_sl['y1']) < 0.5, \
            f"Root split y1: binary={y1}, json={json_sl['y1']}"
        assert abs(x2 - json_sl['x2']) < 0.5, \
            f"Root split x2: binary={x2}, json={json_sl['x2']}"
        assert abs(y2 - json_sl['y2']) < 0.5, \
            f"Root split y2: binary={y2}, json={json_sl['y2']}"


class TestSVGVisualization:
    """Verify the Graphviz SVG output."""

    def test_svg_exists_and_valid(self):
        path = '/app/output/bsp_tree.svg'
        assert os.path.isfile(path), "Missing /app/output/bsp_tree.svg"
        with open(path) as f:
            content = f.read()
        assert len(content) > 500, \
            f"SVG file too small ({len(content)} bytes), likely not a valid rendering"
        assert '<svg' in content.lower(), \
            "SVG file does not contain <svg tag"

    def test_svg_contains_tree_structure(self):
        with open('/app/output/bsp_tree.svg') as f:
            content = f.read()
        assert 'front' in content, \
            "SVG does not contain 'front' edge label"
        assert 'back' in content, \
            "SVG does not contain 'back' edge label"

    def test_svg_contains_subsector_labels(self, bsp_tree):
        with open('/app/output/bsp_tree.svg') as f:
            content = f.read()
        leaves = collect_leaves(bsp_tree)
        found = sum(1 for leaf in leaves
                    if f'SS {leaf["subsector_id"]}' in content
                    or f'Subsector {leaf["subsector_id"]}' in content
                    or f'ss{leaf["subsector_id"]}' in content.lower())
        assert found >= len(leaves) // 2, \
            f"SVG contains only {found}/{len(leaves)} subsector labels"
