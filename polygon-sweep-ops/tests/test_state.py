"""
Tests for Martinez-Rueda-Feito boolean polygon operations.

Verifies that the sweep-line pipeline is correctly implemented by running
end-to-end boolean operations on polygon pairs and checking structural
properties, areas, and point membership.
"""


import subprocess
import json
import os
import pytest


def run_op(subject, clipping, operation, timeout=60):
    """Run a boolean polygon operation via the TypeScript CLI."""
    input_data = json.dumps({
        "subject": subject,
        "clipping": clipping,
        "operation": operation,
    })
    result = subprocess.run(
        ["npx", "tsx", "/app/run_ops.ts"],
        input=input_data,
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Operation '{operation}' failed (exit {result.returncode}):\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
    output = result.stdout.strip()
    if output == "null":
        return None
    return json.loads(output)


def ring_area_signed(coords):
    """Compute signed area of a ring using the shoelace formula."""
    n = len(coords)
    if n < 4:
        return 0.0
    area = 0.0
    for i in range(n - 1):
        area += coords[i][0] * coords[i + 1][1] - coords[i + 1][0] * coords[i][1]
    return area / 2.0


def polygon_area(polygon):
    """Compute the net area of a polygon (exterior minus holes)."""
    if not polygon:
        return 0.0
    exterior = abs(ring_area_signed(polygon[0]))
    holes = sum(abs(ring_area_signed(polygon[h])) for h in range(1, len(polygon)))
    return exterior - holes


def multipolygon_area(result):
    """Compute total area across all polygons in a MultiPolygon result."""
    if result is None:
        return 0.0
    return sum(polygon_area(p) for p in result)


def point_in_ring(point, ring):
    """Ray-casting point-in-polygon test."""
    x, y = point
    n = len(ring) - 1
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def point_in_multipolygon(point, result):
    """Check if a point is inside any polygon in the result (accounting for holes)."""
    if result is None:
        return False
    for polygon in result:
        if point_in_ring(point, polygon[0]):
            in_hole = any(point_in_ring(point, polygon[h]) for h in range(1, len(polygon)))
            if not in_hole:
                return True
    return False


# ---------------------------------------------------------------------------
# Test polygon data
# ---------------------------------------------------------------------------

# Two 4x4 squares with 2x2 overlap at (2,2)-(4,4)
SUBJ_SQ = [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]]
CLIP_SQ = [[[2, 2], [6, 2], [6, 6], [2, 6], [2, 2]]]

# Non-overlapping 3x3 squares
SUBJ_NO = [[[0, 0], [3, 0], [3, 3], [0, 3], [0, 0]]]
CLIP_NO = [[[10, 10], [13, 10], [13, 13], [10, 13], [10, 10]]]

# 10x10 square containing a 4x4 square
SUBJ_CT = [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]
CLIP_CT = [[[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]]]

# Two overlapping triangles
SUBJ_TR = [[[0, 0], [6, 0], [3, 4], [0, 0]]]
CLIP_TR = [[[1, 1], [5, 1], [3, 5], [1, 1]]]

# Subject polygon with a hole: 10x10 outer, 4x4 hole at (3,3)-(7,7)
SUBJ_HOLED = [
    [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
    [[3, 3], [3, 7], [7, 7], [7, 3], [3, 3]]
]
CLIP_RIGHT = [[[5, 0], [15, 0], [15, 10], [5, 10], [5, 0]]]

# Diamond (non-axis-aligned) and rectangle
SUBJ_DIAMOND = [[[3, 0], [6, 3], [3, 6], [0, 3], [3, 0]]]
CLIP_DRECT = [[[1, 1], [5, 1], [5, 5], [1, 5], [1, 1]]]


# ---------------------------------------------------------------------------
# Intersection tests
# ---------------------------------------------------------------------------

class TestIntersection:
    def test_overlapping_squares_area(self):
        result = run_op(SUBJ_SQ, CLIP_SQ, "intersection")
        assert result is not None, "Intersection of overlapping squares must not be null"
        area = multipolygon_area(result)
        assert abs(area - 4.0) < 0.01, f"Expected area ~4.0, got {area}"

    def test_overlapping_squares_structure(self):
        result = run_op(SUBJ_SQ, CLIP_SQ, "intersection")
        assert result is not None
        assert len(result) == 1, f"Expected 1 polygon, got {len(result)}"
        assert len(result[0]) == 1, f"Expected 1 ring (no holes), got {len(result[0])}"

    def test_nonoverlapping_null(self):
        result = run_op(SUBJ_NO, CLIP_NO, "intersection")
        assert result is None, "Intersection of non-overlapping polygons must be null"

    def test_contained_area(self):
        result = run_op(SUBJ_CT, CLIP_CT, "intersection")
        assert result is not None
        area = multipolygon_area(result)
        assert abs(area - 16.0) < 0.01, f"Expected area ~16.0, got {area}"

    def test_triangles_area(self):
        result = run_op(SUBJ_TR, CLIP_TR, "intersection")
        assert result is not None, "Intersection of overlapping triangles must not be null"
        area = multipolygon_area(result)
        assert abs(area - 6.5) < 0.01, f"Expected area ~6.5, got {area}"


# ---------------------------------------------------------------------------
# Union tests
# ---------------------------------------------------------------------------

class TestUnion:
    def test_overlapping_squares_area(self):
        result = run_op(SUBJ_SQ, CLIP_SQ, "union")
        assert result is not None
        area = multipolygon_area(result)
        assert abs(area - 28.0) < 0.01, f"Expected area ~28.0, got {area}"

    def test_nonoverlapping_two_polygons(self):
        result = run_op(SUBJ_NO, CLIP_NO, "union")
        assert result is not None
        assert len(result) == 2, f"Expected 2 separate polygons, got {len(result)}"
        area = multipolygon_area(result)
        assert abs(area - 18.0) < 0.01, f"Expected area ~18.0, got {area}"

    def test_contained_area(self):
        result = run_op(SUBJ_CT, CLIP_CT, "union")
        assert result is not None
        area = multipolygon_area(result)
        assert abs(area - 100.0) < 0.01, f"Expected area ~100.0, got {area}"

    def test_triangles_area(self):
        result = run_op(SUBJ_TR, CLIP_TR, "union")
        assert result is not None
        area = multipolygon_area(result)
        assert abs(area - 13.5) < 0.1, f"Expected area ~13.5, got {area}"


# ---------------------------------------------------------------------------
# Difference tests
# ---------------------------------------------------------------------------

class TestDifference:
    def test_overlapping_squares_area(self):
        result = run_op(SUBJ_SQ, CLIP_SQ, "difference")
        assert result is not None
        area = multipolygon_area(result)
        assert abs(area - 12.0) < 0.01, f"Expected area ~12.0, got {area}"

    def test_nonoverlapping_unchanged(self):
        result = run_op(SUBJ_NO, CLIP_NO, "difference")
        assert result is not None
        area = multipolygon_area(result)
        assert abs(area - 9.0) < 0.01, f"Expected area ~9.0, got {area}"

    def test_contained_has_hole(self):
        result = run_op(SUBJ_CT, CLIP_CT, "difference")
        assert result is not None
        assert len(result) == 1, f"Expected 1 polygon, got {len(result)}"
        assert len(result[0]) == 2, f"Expected 2 rings (exterior + hole), got {len(result[0])}"

    def test_contained_area(self):
        result = run_op(SUBJ_CT, CLIP_CT, "difference")
        assert result is not None
        area = multipolygon_area(result)
        assert abs(area - 84.0) < 0.01, f"Expected area ~84.0, got {area}"

    def test_triangles_area(self):
        result = run_op(SUBJ_TR, CLIP_TR, "difference")
        assert result is not None
        area = multipolygon_area(result)
        assert abs(area - 5.5) < 0.1, f"Expected area ~5.5, got {area}"


# ---------------------------------------------------------------------------
# XOR tests
# ---------------------------------------------------------------------------

class TestXOR:
    def test_overlapping_squares_area(self):
        result = run_op(SUBJ_SQ, CLIP_SQ, "xor")
        assert result is not None
        area = multipolygon_area(result)
        assert abs(area - 24.0) < 0.01, f"Expected area ~24.0, got {area}"

    def test_contained_xor_area(self):
        result = run_op(SUBJ_CT, CLIP_CT, "xor")
        assert result is not None
        area = multipolygon_area(result)
        assert abs(area - 84.0) < 0.01, f"Expected area ~84.0, got {area}"


# ---------------------------------------------------------------------------
# Point-in-result tests
# ---------------------------------------------------------------------------

class TestPointMembership:
    def test_intersection_center_inside(self):
        result = run_op(SUBJ_SQ, CLIP_SQ, "intersection")
        assert point_in_multipolygon([3.0, 3.0], result), \
            "Center of overlap (3,3) must be inside intersection"

    def test_intersection_outside_excluded(self):
        result = run_op(SUBJ_SQ, CLIP_SQ, "intersection")
        assert not point_in_multipolygon([1.0, 1.0], result), \
            "(1,1) must be outside intersection"
        assert not point_in_multipolygon([5.0, 5.0], result), \
            "(5,5) must be outside intersection"

    def test_difference_subject_only_inside(self):
        result = run_op(SUBJ_SQ, CLIP_SQ, "difference")
        assert point_in_multipolygon([1.0, 1.0], result), \
            "(1,1) in subject-only region must be inside difference"
        assert not point_in_multipolygon([5.0, 5.0], result), \
            "(5,5) in clipping-only region must be outside difference"

    def test_contained_difference_hole(self):
        result = run_op(SUBJ_CT, CLIP_CT, "difference")
        assert point_in_multipolygon([1.0, 1.0], result), \
            "(1,1) outside hole must be inside difference"
        assert not point_in_multipolygon([5.0, 5.0], result), \
            "(5,5) inside hole must be outside difference"


# ---------------------------------------------------------------------------
# Structural validity tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_rings_are_closed(self):
        result = run_op(SUBJ_SQ, CLIP_SQ, "intersection")
        assert result is not None
        for pi, polygon in enumerate(result):
            for ri, ring in enumerate(polygon):
                assert len(ring) >= 4, \
                    f"Polygon {pi} ring {ri}: need >= 4 points, got {len(ring)}"
                assert ring[0][0] == ring[-1][0] and ring[0][1] == ring[-1][1], \
                    f"Polygon {pi} ring {ri}: ring not closed"

    def test_union_rings_closed(self):
        result = run_op(SUBJ_SQ, CLIP_SQ, "union")
        assert result is not None
        for pi, polygon in enumerate(result):
            for ri, ring in enumerate(polygon):
                assert len(ring) >= 4, \
                    f"Polygon {pi} ring {ri}: need >= 4 points, got {len(ring)}"
                assert ring[0][0] == ring[-1][0] and ring[0][1] == ring[-1][1], \
                    f"Polygon {pi} ring {ri}: ring not closed"

    def test_difference_rings_closed(self):
        result = run_op(SUBJ_CT, CLIP_CT, "difference")
        assert result is not None
        for pi, polygon in enumerate(result):
            for ri, ring in enumerate(polygon):
                assert len(ring) >= 4
                assert ring[0][0] == ring[-1][0] and ring[0][1] == ring[-1][1]


# ---------------------------------------------------------------------------
# Holed subject polygon tests
# ---------------------------------------------------------------------------

class TestHoledSubject:
    """Test operations where the subject polygon has an interior hole."""

    def test_intersection_area(self):
        """Intersection of holed subject with right-side clipping.
        Outer intersection: [5,0]-[10,10] = 50
        Hole intersection: [5,3]-[7,7] = 8
        Net: 42
        """
        result = run_op(SUBJ_HOLED, CLIP_RIGHT, "intersection")
        assert result is not None, "Holed subject intersection should not be null"
        area = multipolygon_area(result)
        assert abs(area - 42.0) < 0.5, f"Expected area ~42.0, got {area}"

    def test_intersection_has_hole(self):
        """The intersection result must include vertices from the subject's
        hole boundary, proving that hole geometry is processed."""
        result = run_op(SUBJ_HOLED, CLIP_RIGHT, "intersection")
        assert result is not None
        # Collect all vertices across every ring of every polygon
        all_pts = [pt for p in result for ring in p for pt in ring]
        # Subject hole corners (7,3) and (7,7) lie inside the clipping
        # region and must appear as vertices in the intersection result
        has_7_3 = any(
            abs(pt[0] - 7) < 0.01 and abs(pt[1] - 3) < 0.01
            for pt in all_pts
        )
        has_7_7 = any(
            abs(pt[0] - 7) < 0.01 and abs(pt[1] - 7) < 0.01
            for pt in all_pts
        )
        assert has_7_3, "Hole vertex (7,3) must appear in intersection result"
        assert has_7_7, "Hole vertex (7,7) must appear in intersection result"

    def test_intersection_point_in_hole(self):
        """Point inside the hole portion of the intersection should be excluded."""
        result = run_op(SUBJ_HOLED, CLIP_RIGHT, "intersection")
        assert result is not None
        # (9,5) is in the outer intersection region, outside the hole
        assert point_in_multipolygon([9.0, 5.0], result), \
            "(9,5) should be inside intersection (outer region)"
        # (6,5) is inside the hole [5,3]-[7,7]
        assert not point_in_multipolygon([6.0, 5.0], result), \
            "(6,5) should be outside intersection (inside hole)"

    def test_difference_area(self):
        """Difference of holed subject minus right clipping.
        Left part of outer: [0,0]-[5,10] = 50
        Left part of hole: [3,3]-[5,7] = 8
        Net: 42
        """
        result = run_op(SUBJ_HOLED, CLIP_RIGHT, "difference")
        assert result is not None, "Holed subject difference should not be null"
        area = multipolygon_area(result)
        assert abs(area - 42.0) < 0.5, f"Expected area ~42.0, got {area}"

    def test_union_area(self):
        """Union should cover subject (84) + clipping (100) - intersection (42) = 142."""
        result = run_op(SUBJ_HOLED, CLIP_RIGHT, "union")
        assert result is not None
        area = multipolygon_area(result)
        assert abs(area - 142.0) < 1.0, f"Expected area ~142.0, got {area}"


# ---------------------------------------------------------------------------
# Diamond-rectangle (non-axis-aligned) tests
# ---------------------------------------------------------------------------

class TestDiamondRect:
    """Test operations with non-axis-aligned polygon (diamond) against a rectangle.
    Diamond vertices: (3,0),(6,3),(3,6),(0,3) — area 18
    Rectangle: (1,1)-(5,5) — area 16
    Intersection is an octagon with area 14.
    """

    def test_intersection_area(self):
        result = run_op(SUBJ_DIAMOND, CLIP_DRECT, "intersection")
        assert result is not None, "Diamond-rect intersection should not be null"
        area = multipolygon_area(result)
        assert abs(area - 14.0) < 0.5, f"Expected area ~14.0, got {area}"

    def test_difference_area(self):
        """Diamond minus rectangle: 18 - 14 = 4."""
        result = run_op(SUBJ_DIAMOND, CLIP_DRECT, "difference")
        assert result is not None
        area = multipolygon_area(result)
        assert abs(area - 4.0) < 0.5, f"Expected area ~4.0, got {area}"

    def test_union_area(self):
        """Union: 18 + 16 - 14 = 20."""
        result = run_op(SUBJ_DIAMOND, CLIP_DRECT, "union")
        assert result is not None
        area = multipolygon_area(result)
        assert abs(area - 20.0) < 0.5, f"Expected area ~20.0, got {area}"

    def test_intersection_point_membership(self):
        """Center (3,3) should be inside intersection;
        diamond-only point (0.5,3) should be outside."""
        result = run_op(SUBJ_DIAMOND, CLIP_DRECT, "intersection")
        assert point_in_multipolygon([3.0, 3.0], result), \
            "(3,3) should be inside diamond-rect intersection"
        assert not point_in_multipolygon([0.5, 3.0], result), \
            "(0.5,3) is outside the rectangle, should not be in intersection"


# ---------------------------------------------------------------------------
# Fixture tests  (GeoJSON files)
# ---------------------------------------------------------------------------

class TestFixtures:
    def test_two_triangles_intersection(self):
        with open("/app/fixtures/two_triangles.geojson") as f:
            data = json.load(f)
        s = data["features"][0]["geometry"]["coordinates"]
        c = data["features"][1]["geometry"]["coordinates"]
        result = run_op(s, c, "intersection")
        assert result is not None, "two_triangles intersection should not be null"
        area = multipolygon_area(result)
        assert area > 100, f"Expected large intersection area, got {area}"

    def test_two_triangles_union(self):
        with open("/app/fixtures/two_triangles.geojson") as f:
            data = json.load(f)
        s = data["features"][0]["geometry"]["coordinates"]
        c = data["features"][1]["geometry"]["coordinates"]
        result = run_op(s, c, "union")
        assert result is not None
        area = multipolygon_area(result)
        assert area > 20000, f"Expected union area > 20000, got {area}"

    def test_two_shapes_intersection(self):
        with open("/app/fixtures/two_shapes.geojson") as f:
            data = json.load(f)
        s = data["features"][0]["geometry"]["coordinates"]
        c = data["features"][1]["geometry"]["coordinates"]
        result = run_op(s, c, "intersection")
        assert result is not None, "two_shapes intersection should not be null"
        area = multipolygon_area(result)
        assert area > 0, f"Expected positive area, got {area}"

    def test_hole_hole_difference(self):
        with open("/app/fixtures/hole_hole.geojson") as f:
            data = json.load(f)
        s = data["features"][0]["geometry"]["coordinates"]
        c = data["features"][1]["geometry"]["coordinates"]
        result = run_op(s, c, "difference")
        assert result is not None, "hole_hole difference should not be null"
        area = multipolygon_area(result)
        assert area > 0, f"Expected positive area, got {area}"
