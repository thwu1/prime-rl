"""
BSP Engine verification tests.

Verifies that the BSP tree compiler at /app/bsp_engine correctly:
- Constructs valid BSP trees from 2D map segments
- Preserves all original geometry (segment coverage)
- Produces non-crossing leaves
- Generates correct front-to-back traversal orderings

"""

import json
import math
import os
import subprocess
import pytest

EPSILON = 1e-4
MAP_DIR = "/app/maps"
RESULT_DIR = "/app/results"
ENGINE = "/app/bsp_engine"

MAP_NAMES = ["map1", "map2", "map3", "map4"]


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def point_side(px, py, lx1, ly1, lx2, ly2):
    """Signed area: positive = front/left, negative = back/right."""
    return (lx2 - lx1) * (py - ly1) - (ly2 - ly1) * (px - lx1)


def segs_cross_dict(s1, s2):
    """Check if two seg dicts have a proper interior crossing."""
    d1 = point_side(s1["x1"], s1["y1"], s2["x1"], s2["y1"], s2["x2"], s2["y2"])
    d2 = point_side(s1["x2"], s1["y2"], s2["x1"], s2["y1"], s2["x2"], s2["y2"])
    d3 = point_side(s2["x1"], s2["y1"], s1["x1"], s1["y1"], s1["x2"], s1["y2"])
    d4 = point_side(s2["x2"], s2["y2"], s1["x1"], s1["y1"], s1["x2"], s1["y2"])
    return (d1 * d2 < -EPSILON) and (d3 * d4 < -EPSILON)


def ray_seg_intersection(ox, oy, dx, dy, seg):
    """Find parameter t where ray (ox+t*dx, oy+t*dy) intersects seg.
    Returns t > 0 if hit, None otherwise.
    """
    sx = seg["x2"] - seg["x1"]
    sy = seg["y2"] - seg["y1"]
    r_cross_s = dx * sy - dy * sx
    if abs(r_cross_s) < 1e-10:
        return None
    qpx = seg["x1"] - ox
    qpy = seg["y1"] - oy
    t = (qpx * sy - qpy * sx) / r_cross_s
    u = (qpx * dy - qpy * dx) / r_cross_s
    if t > 1e-6 and -1e-6 <= u <= 1.0 + 1e-6:
        return t
    return None


# ---------------------------------------------------------------------------
# BSP tree helpers
# ---------------------------------------------------------------------------

def collect_all_segs(node):
    """Collect all seg dicts from BSP tree leaves."""
    if node["type"] == "leaf":
        return list(node["segs"])
    return collect_all_segs(node["front"]) + collect_all_segs(node["back"])


def collect_leaves(node):
    """Collect all leaf nodes."""
    if node["type"] == "leaf":
        return [node]
    return collect_leaves(node["front"]) + collect_leaves(node["back"])


def build_seg_to_leaf_map(node, leaf_idx=None):
    """Map each seg ID to its leaf index."""
    if leaf_idx is None:
        leaf_idx = [0]
    result = {}
    if node["type"] == "leaf":
        idx = leaf_idx[0]
        leaf_idx[0] += 1
        for seg in node["segs"]:
            result[seg["id"]] = idx
    else:
        result.update(build_seg_to_leaf_map(node["front"], leaf_idx))
        result.update(build_seg_to_leaf_map(node["back"], leaf_idx))
    return result


def re_traverse(node, vx, vy):
    """Re-traverse BSP tree front-to-back from viewpoint."""
    if node["type"] == "leaf":
        return list(node["segs"])
    side = point_side(
        vx, vy,
        node["split"]["x1"], node["split"]["y1"],
        node["split"]["x2"], node["split"]["y2"],
    )
    if side >= 0:
        result = re_traverse(node["front"], vx, vy)
        result.extend(re_traverse(node["back"], vx, vy))
    else:
        result = re_traverse(node["back"], vx, vy)
        result.extend(re_traverse(node["front"], vx, vy))
    return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def all_maps():
    """Load all input map data."""
    maps = {}
    for name in MAP_NAMES:
        path = os.path.join(MAP_DIR, f"{name}.json")
        with open(path) as f:
            maps[name] = json.load(f)
    return maps


@pytest.fixture(scope="session")
def all_results():
    """Run BSP engine on every map and collect results."""
    if not os.path.exists(ENGINE):
        pytest.fail(f"BSP engine not found at {ENGINE}")

    os.makedirs(RESULT_DIR, exist_ok=True)
    results = {}

    for name in MAP_NAMES:
        input_path = os.path.join(MAP_DIR, f"{name}.json")
        output_path = os.path.join(RESULT_DIR, f"{name}.json")
        try:
            proc = subprocess.run(
                [ENGINE, input_path, output_path],
                capture_output=True, text=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            pytest.fail(f"Engine timed out on {name}")
        if proc.returncode != 0:
            pytest.fail(
                f"Engine failed on {name} (rc={proc.returncode}): {proc.stderr}"
            )
        with open(output_path) as f:
            results[name] = json.load(f)

    return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOutputFormat:
    """Verify JSON structure of engine output."""

    @pytest.mark.parametrize("map_name", MAP_NAMES)
    def test_top_level_keys(self, all_results, map_name):
        out = all_results[map_name]
        for key in ("bsp", "stats", "query_results"):
            assert key in out, f"Missing top-level key '{key}'"

    @pytest.mark.parametrize("map_name", MAP_NAMES)
    def test_stats_keys(self, all_results, map_name):
        stats = all_results[map_name]["stats"]
        for key in ("num_nodes", "num_leaves", "num_segs", "max_depth"):
            assert key in stats, f"Missing stats key '{key}'"
        assert stats["num_leaves"] >= 1
        assert stats["num_segs"] >= 1

    @pytest.mark.parametrize("map_name", MAP_NAMES)
    def test_bsp_tree_structure(self, all_results, map_name):
        def _validate(node, depth=0):
            assert "type" in node
            if node["type"] == "node":
                assert "split" in node
                assert "front" in node
                assert "back" in node
                sp = node["split"]
                for k in ("x1", "y1", "x2", "y2"):
                    assert k in sp, f"Missing split key '{k}'"
                _validate(node["front"], depth + 1)
                _validate(node["back"], depth + 1)
            elif node["type"] == "leaf":
                assert "segs" in node
                for seg in node["segs"]:
                    for k in ("id", "x1", "y1", "x2", "y2", "line_id"):
                        assert k in seg, f"Missing seg key '{k}'"
            else:
                pytest.fail(f"Unknown node type: {node['type']}")

        _validate(all_results[map_name]["bsp"])

    @pytest.mark.parametrize("map_name", MAP_NAMES)
    def test_query_result_count(self, all_results, all_maps, map_name):
        expected = len(all_maps[map_name]["queries"])
        actual = len(all_results[map_name]["query_results"])
        assert actual == expected, (
            f"Expected {expected} query results, got {actual}"
        )

    @pytest.mark.parametrize("map_name", MAP_NAMES)
    def test_query_result_structure(self, all_results, map_name):
        for qr in all_results[map_name]["query_results"]:
            assert "viewpoint" in qr
            assert "x" in qr["viewpoint"]
            assert "y" in qr["viewpoint"]
            assert "seg_order" in qr
            for seg in qr["seg_order"]:
                for k in ("id", "x1", "y1", "x2", "y2", "line_id"):
                    assert k in seg


class TestSegmentCoverage:
    """Every original segment must be fully covered by BSP segs."""

    @pytest.mark.parametrize("map_name", MAP_NAMES)
    def test_coverage(self, all_results, all_maps, map_name):
        bsp_segs = collect_all_segs(all_results[map_name]["bsp"])
        originals = all_maps[map_name]["segments"]

        for orig in originals:
            lid = orig["id"]
            matching = [s for s in bsp_segs if s["line_id"] == lid]
            assert len(matching) > 0, f"No segs for line_id {lid}"

            ox1, oy1 = float(orig["x1"]), float(orig["y1"])
            ox2, oy2 = float(orig["x2"]), float(orig["y2"])
            dx = ox2 - ox1
            dy = oy2 - oy1
            length_sq = dx * dx + dy * dy
            assert length_sq > 0, f"Zero-length original segment {lid}"
            length = math.sqrt(length_sq)

            # Verify collinearity of each matching seg
            for seg in matching:
                d1 = abs(point_side(seg["x1"], seg["y1"], ox1, oy1, ox2, oy2))
                d2 = abs(point_side(seg["x2"], seg["y2"], ox1, oy1, ox2, oy2))
                assert d1 < EPSILON * length, (
                    f"Seg {seg['id']} start off line {lid} by {d1 / length:.6f}"
                )
                assert d2 < EPSILON * length, (
                    f"Seg {seg['id']} end off line {lid} by {d2 / length:.6f}"
                )

            # Verify parametric coverage of [0, 1]
            intervals = []
            for seg in matching:
                t1 = ((seg["x1"] - ox1) * dx + (seg["y1"] - oy1) * dy) / length_sq
                t2 = ((seg["x2"] - ox1) * dx + (seg["y2"] - oy1) * dy) / length_sq
                intervals.append((min(t1, t2), max(t1, t2)))
            intervals.sort()

            covered = -EPSILON
            for t_min, t_max in intervals:
                assert t_min <= covered + EPSILON, (
                    f"Gap in coverage for line {lid}: "
                    f"covered to {covered:.6f}, next at {t_min:.6f}"
                )
                covered = max(covered, t_max)
            assert covered >= 1.0 - EPSILON, (
                f"Incomplete coverage for line {lid}: covered to {covered:.6f}"
            )


class TestLeafValidity:
    """No two segments in the same leaf should cross."""

    @pytest.mark.parametrize("map_name", MAP_NAMES)
    def test_no_crossing_in_leaves(self, all_results, map_name):
        leaves = collect_leaves(all_results[map_name]["bsp"])
        for idx, leaf in enumerate(leaves):
            segs = leaf["segs"]
            for i in range(len(segs)):
                for j in range(i + 1, len(segs)):
                    assert not segs_cross_dict(segs[i], segs[j]), (
                        f"Crossing segs in leaf {idx}: "
                        f"seg {segs[i]['id']} and seg {segs[j]['id']}"
                    )


class TestTraversal:
    """Traversal order must match BSP tree re-traversal."""

    @pytest.mark.parametrize("map_name", MAP_NAMES)
    def test_traversal_consistency(self, all_results, map_name):
        bsp = all_results[map_name]["bsp"]
        for qr in all_results[map_name]["query_results"]:
            vx = qr["viewpoint"]["x"]
            vy = qr["viewpoint"]["y"]
            expected = re_traverse(bsp, vx, vy)
            actual = qr["seg_order"]
            exp_ids = [s["id"] for s in expected]
            act_ids = [s["id"] for s in actual]
            assert exp_ids == act_ids, (
                f"Traversal mismatch at ({vx}, {vy}): "
                f"expected {exp_ids}, got {act_ids}"
            )


class TestGeometricCorrectness:
    """Front-to-back ordering verified by raycasting across different leaves."""

    @pytest.mark.parametrize("map_name", ["map2", "map3", "map4"])
    def test_front_to_back_raycast(self, all_results, map_name):
        bsp = all_results[map_name]["bsp"]
        all_segs = collect_all_segs(bsp)
        seg_leaf = build_seg_to_leaf_map(bsp)

        for qr in all_results[map_name]["query_results"]:
            vx = qr["viewpoint"]["x"]
            vy = qr["viewpoint"]["y"]
            order = qr["seg_order"]

            # Build position-in-ordering map
            pos = {}
            for i, seg in enumerate(order):
                pos[seg["id"]] = i

            num_rays = 720
            for ray_idx in range(num_rays):
                angle = 2.0 * math.pi * ray_idx / num_rays
                rdx = math.cos(angle)
                rdy = math.sin(angle)

                hits = []
                for seg in all_segs:
                    t = ray_seg_intersection(vx, vy, rdx, rdy, seg)
                    if t is not None:
                        hits.append((t, seg["id"]))
                hits.sort()

                for i in range(len(hits)):
                    for j in range(i + 1, len(hits)):
                        dist_a, id_a = hits[i]
                        dist_b, id_b = hits[j]
                        if abs(dist_a - dist_b) < 1e-3:
                            continue  # nearly same distance, skip
                        # Only check across different leaves — within a
                        # leaf the order is arbitrary (non-crossing segs).
                        if seg_leaf.get(id_a) == seg_leaf.get(id_b):
                            continue
                        if id_a in pos and id_b in pos:
                            assert pos[id_a] <= pos[id_b], (
                                f"Geometric violation at angle "
                                f"{math.degrees(angle):.1f} deg from "
                                f"({vx},{vy}): seg {id_a} "
                                f"(dist {dist_a:.1f}) must precede "
                                f"seg {id_b} (dist {dist_b:.1f})"
                            )


class TestSplittingBehavior:
    """Maps with crossings must produce BSP nodes with splits."""

    def test_map2_requires_split(self, all_results):
        stats = all_results["map2"]["stats"]
        assert stats["num_nodes"] >= 1, (
            f"Map2 needs at least 1 BSP node, got {stats['num_nodes']}"
        )
        assert stats["num_segs"] >= 3, (
            f"Map2 needs at least 3 segs after splitting, got {stats['num_segs']}"
        )

    def test_map3_many_splits(self, all_results):
        stats = all_results["map3"]["stats"]
        assert stats["num_segs"] > 6, (
            f"Map3 needs more than 6 segs, got {stats['num_segs']}"
        )
        assert stats["num_nodes"] >= 3, (
            f"Map3 needs at least 3 BSP nodes, got {stats['num_nodes']}"
        )
        assert stats["max_depth"] <= 20, (
            f"Map3 tree too deep ({stats['max_depth']}), suggests degenerate splitting"
        )

    def test_map4_splitting(self, all_results):
        stats = all_results["map4"]["stats"]
        assert stats["num_segs"] > 8, (
            f"Map4 needs more than 8 segs, got {stats['num_segs']}"
        )
        assert stats["num_nodes"] >= 1, (
            f"Map4 needs at least 1 BSP node, got {stats['num_nodes']}"
        )

    def test_map1_no_splits_needed(self, all_results):
        stats = all_results["map1"]["stats"]
        # Map1 has no crossings, so zero nodes is acceptable
        assert stats["num_segs"] == 4, (
            f"Map1 should have exactly 4 segs (no splits), got {stats['num_segs']}"
        )


class TestUniqueSegIds:
    """All seg IDs within a result must be unique."""

    @pytest.mark.parametrize("map_name", MAP_NAMES)
    def test_unique_ids(self, all_results, map_name):
        all_segs = collect_all_segs(all_results[map_name]["bsp"])
        ids = [s["id"] for s in all_segs]
        assert len(ids) == len(set(ids)), (
            f"Duplicate seg IDs found: {len(ids)} total, {len(set(ids))} unique"
        )
