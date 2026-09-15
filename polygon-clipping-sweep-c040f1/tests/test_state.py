"""
Tests for the boolean polygon clipping implementation.

"""

import subprocess
import json
import math
import os
import pytest

# Operation codes
INTERSECTION = 0
UNION = 1
DIFFERENCE = 2
XOR = 3


def run_op(subject, clipping, op_code):
    """Run a boolean polygon operation via the TypeScript CLI."""
    result = subprocess.run(
        ["npx", "tsx", "/app/run_op.ts", str(op_code),
         json.dumps(subject), json.dumps(clipping)],
        capture_output=True, text=True, cwd="/app", timeout=60
    )
    assert result.returncode == 0, (
        f"tsx exited with code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    out = result.stdout.strip()
    if out == "null" or not out:
        return None
    return json.loads(out)


def ring_signed_area(ring):
    """Signed area via shoelace formula."""
    n = len(ring)
    area = 0.0
    for i in range(n - 1):
        area += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return area / 2.0


def polygon_area(polygon):
    """Unsigned area of a polygon (exterior minus holes)."""
    area = abs(ring_signed_area(polygon[0]))
    for i in range(1, len(polygon)):
        area -= abs(ring_signed_area(polygon[i]))
    return area


def multi_polygon_area(mp):
    """Total area of a multipolygon result."""
    return sum(polygon_area(p) for p in mp)


def count_rings(mp):
    """Total number of rings across all polygons."""
    return sum(len(p) for p in mp)


# ----------- Test polygons -----------

RECT_A = [[[0, 0], [4, 0], [4, 3], [0, 3], [0, 0]]]
RECT_B = [[[2, 0], [6, 0], [6, 3], [2, 3], [2, 0]]]

RECT_FAR_A = [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
RECT_FAR_B = [[[3, 0], [4, 0], [4, 1], [3, 1], [3, 0]]]

TRI_A = [[[0, 0], [6, 0], [3, 4], [0, 0]]]
TRI_B = [[[2, 0], [8, 0], [5, 4], [2, 0]]]

BIG_SQUARE = [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]
SMALL_SQUARE = [[[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]]]

# L-shaped concave polygon (area=12) and intersecting rectangle (area=4)
L_SHAPE = [[[0, 0], [4, 0], [4, 2], [2, 2], [2, 4], [0, 4], [0, 0]]]
L_RECT = [[[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]

# MultiPolygon: two separated squares as subject
MULTI_SQ1 = [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
MULTI_SQ2 = [[[5, 0], [7, 0], [7, 2], [5, 2], [5, 0]]]
MULTI_SUBJ = [MULTI_SQ1, MULTI_SQ2]  # MultiPolygon with 2 polygons
MULTI_CLIP = [[[1, 0.5], [6, 0.5], [6, 1.5], [1, 1.5], [1, 0.5]]]  # area=5


# ----------- Overlapping rectangles -----------

class TestOverlappingRectangles:
    def test_intersection_area(self):
        result = run_op(RECT_A, RECT_B, INTERSECTION)
        assert result is not None, "intersection should not be null"
        area = multi_polygon_area(result)
        assert math.isclose(area, 6.0, rel_tol=1e-6), f"expected area 6.0, got {area}"

    def test_union_area(self):
        result = run_op(RECT_A, RECT_B, UNION)
        assert result is not None, "union should not be null"
        area = multi_polygon_area(result)
        assert math.isclose(area, 18.0, rel_tol=1e-6), f"expected area 18.0, got {area}"

    def test_difference_area(self):
        result = run_op(RECT_A, RECT_B, DIFFERENCE)
        assert result is not None, "difference should not be null"
        area = multi_polygon_area(result)
        assert math.isclose(area, 6.0, rel_tol=1e-6), f"expected area 6.0, got {area}"

    def test_xor_area(self):
        result = run_op(RECT_A, RECT_B, XOR)
        assert result is not None, "xor should not be null"
        area = multi_polygon_area(result)
        assert math.isclose(area, 12.0, rel_tol=1e-6), f"expected area 12.0, got {area}"

    def test_intersection_single_polygon(self):
        result = run_op(RECT_A, RECT_B, INTERSECTION)
        assert result is not None
        assert len(result) == 1, f"expected 1 polygon, got {len(result)}"

    def test_union_single_polygon(self):
        result = run_op(RECT_A, RECT_B, UNION)
        assert result is not None
        assert len(result) == 1, f"expected 1 polygon, got {len(result)}"

    def test_area_identity(self):
        """area(A) + area(B) = area(intersection) + area(union)"""
        i_result = run_op(RECT_A, RECT_B, INTERSECTION)
        u_result = run_op(RECT_A, RECT_B, UNION)
        assert i_result is not None and u_result is not None
        i_area = multi_polygon_area(i_result)
        u_area = multi_polygon_area(u_result)
        # area(A) + area(B) = 12 + 12 = 24 = area(intersection) + area(union)
        assert math.isclose(i_area + u_area, 24.0, rel_tol=1e-6)


# ----------- Non-overlapping rectangles -----------

class TestNonOverlapping:
    def test_intersection_null(self):
        result = run_op(RECT_FAR_A, RECT_FAR_B, INTERSECTION)
        assert result is None, "intersection of non-overlapping should be null"

    def test_union_area(self):
        result = run_op(RECT_FAR_A, RECT_FAR_B, UNION)
        assert result is not None, "union should not be null"
        area = multi_polygon_area(result)
        assert math.isclose(area, 2.0, rel_tol=1e-6), f"expected area 2.0, got {area}"

    def test_union_two_polygons(self):
        result = run_op(RECT_FAR_A, RECT_FAR_B, UNION)
        assert result is not None
        assert len(result) == 2, f"expected 2 polygons, got {len(result)}"

    def test_difference_equals_subject(self):
        result = run_op(RECT_FAR_A, RECT_FAR_B, DIFFERENCE)
        assert result is not None
        area = multi_polygon_area(result)
        assert math.isclose(area, 1.0, rel_tol=1e-6), f"expected area 1.0, got {area}"


# ----------- Two triangles -----------

class TestTriangles:
    def test_intersection_area(self):
        result = run_op(TRI_A, TRI_B, INTERSECTION)
        assert result is not None, "intersection should not be null"
        area = multi_polygon_area(result)
        expected = 16.0 / 3.0  # ~5.333
        assert math.isclose(area, expected, rel_tol=1e-4), (
            f"expected area {expected:.4f}, got {area:.4f}"
        )

    def test_union_area(self):
        result = run_op(TRI_A, TRI_B, UNION)
        assert result is not None
        area = multi_polygon_area(result)
        # area(A) + area(B) - area(intersection) = 12 + 12 - 16/3 = 56/3
        expected = 56.0 / 3.0
        assert math.isclose(area, expected, rel_tol=1e-4), (
            f"expected area {expected:.4f}, got {area:.4f}"
        )

    def test_area_identity_triangles(self):
        i_result = run_op(TRI_A, TRI_B, INTERSECTION)
        u_result = run_op(TRI_A, TRI_B, UNION)
        assert i_result is not None and u_result is not None
        total = multi_polygon_area(i_result) + multi_polygon_area(u_result)
        assert math.isclose(total, 24.0, rel_tol=1e-4)


# ----------- Containment / difference creating holes -----------

class TestContainment:
    def test_intersection_equals_inner(self):
        result = run_op(BIG_SQUARE, SMALL_SQUARE, INTERSECTION)
        assert result is not None
        area = multi_polygon_area(result)
        assert math.isclose(area, 36.0, rel_tol=1e-6), f"expected area 36.0, got {area}"

    def test_difference_creates_hole(self):
        result = run_op(BIG_SQUARE, SMALL_SQUARE, DIFFERENCE)
        assert result is not None
        area = multi_polygon_area(result)
        assert math.isclose(area, 64.0, rel_tol=1e-6), f"expected area 64.0, got {area}"

    def test_difference_has_hole_ring(self):
        result = run_op(BIG_SQUARE, SMALL_SQUARE, DIFFERENCE)
        assert result is not None
        total_rings = count_rings(result)
        assert total_rings == 2, f"expected 2 rings (exterior+hole), got {total_rings}"

    def test_union_equals_outer(self):
        result = run_op(BIG_SQUARE, SMALL_SQUARE, UNION)
        assert result is not None
        area = multi_polygon_area(result)
        assert math.isclose(area, 100.0, rel_tol=1e-6), f"expected area 100.0, got {area}"


# ----------- Fixture test: two_triangles.geojson -----------

class TestFixtureTwoTriangles:
    @pytest.fixture(autouse=True)
    def load_fixture(self):
        with open("/app/fixtures/two_triangles.geojson") as f:
            data = json.load(f)
        self.subject = data["features"][0]["geometry"]["coordinates"]
        self.clipping = data["features"][1]["geometry"]["coordinates"]

    def test_intersection_not_null(self):
        result = run_op(self.subject, self.clipping, INTERSECTION)
        assert result is not None, "fixture intersection should not be null"
        area = multi_polygon_area(result)
        assert area > 100, f"expected significant area, got {area}"

    def test_union_not_null(self):
        result = run_op(self.subject, self.clipping, UNION)
        assert result is not None
        area = multi_polygon_area(result)
        assert area > 1000, f"expected large union area, got {area}"

    def test_area_identity_fixture(self):
        """area(subject) + area(clipping) = area(intersection) + area(union)"""
        i_result = run_op(self.subject, self.clipping, INTERSECTION)
        u_result = run_op(self.subject, self.clipping, UNION)
        assert i_result is not None and u_result is not None

        # Compute subject and clipping areas
        s_area = abs(ring_signed_area(self.subject[0]))
        c_area = abs(ring_signed_area(self.clipping[0]))
        expected_sum = s_area + c_area

        actual_sum = multi_polygon_area(i_result) + multi_polygon_area(u_result)
        assert math.isclose(actual_sum, expected_sum, rel_tol=1e-4), (
            f"area identity failed: {actual_sum} != {expected_sum}"
        )

    def test_difference_area(self):
        i_result = run_op(self.subject, self.clipping, INTERSECTION)
        d_result = run_op(self.subject, self.clipping, DIFFERENCE)
        assert i_result is not None and d_result is not None
        s_area = abs(ring_signed_area(self.subject[0]))
        i_area = multi_polygon_area(i_result)
        d_area = multi_polygon_area(d_result)
        assert math.isclose(d_area, s_area - i_area, rel_tol=1e-4), (
            f"difference area mismatch: {d_area} != {s_area} - {i_area}"
        )

    def test_xor_produces_result(self):
        """XOR should produce a non-null result with positive area."""
        x_result = run_op(self.subject, self.clipping, XOR)
        assert x_result is not None, "fixture xor should not be null"
        x_area = multi_polygon_area(x_result)
        assert x_area > 100, f"xor area should be substantial, got {x_area}"
        for poly in x_result:
            for ring in poly:
                assert len(ring) >= 4, f"xor ring too short: {len(ring)} points"
                assert ring[0] == ring[-1], f"xor ring not closed"


# ----------- Collinear edge handling -----------

class TestCollinearEdges:
    """Test polygons that share a collinear edge."""

    def test_adjacent_squares_union(self):
        """Two squares sharing an edge should union into one rectangle."""
        sq_left = [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
        sq_right = [[[2, 0], [4, 0], [4, 2], [2, 2], [2, 0]]]
        result = run_op(sq_left, sq_right, UNION)
        assert result is not None
        area = multi_polygon_area(result)
        assert math.isclose(area, 8.0, rel_tol=1e-6), f"expected area 8.0, got {area}"

    def test_adjacent_squares_intersection(self):
        """Two squares sharing just an edge have zero-area intersection."""
        sq_left = [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
        sq_right = [[[2, 0], [4, 0], [4, 2], [2, 2], [2, 0]]]
        result = run_op(sq_left, sq_right, INTERSECTION)
        # May be null or a degenerate polygon with zero area
        if result is not None:
            area = multi_polygon_area(result)
            assert area < 1e-6, f"expected ~0 area, got {area}"


# ----------- Concave polygon operations -----------

class TestConcavePolygon:
    """Test operations on concave (L-shaped) polygons."""

    def test_intersection_area(self):
        # L-shape (area=12) intersected with rectangle (area=4)
        # Intersection: y=[1,2] x=[1,3] area=2 + y=[2,3] x=[1,2] area=1 = 3.0
        result = run_op(L_SHAPE, L_RECT, INTERSECTION)
        assert result is not None, "L-shape intersection should not be null"
        area = multi_polygon_area(result)
        assert math.isclose(area, 3.0, rel_tol=1e-4), f"expected area 3.0, got {area}"

    def test_union_area(self):
        # Union = 12 + 4 - 3 = 13.0
        result = run_op(L_SHAPE, L_RECT, UNION)
        assert result is not None
        area = multi_polygon_area(result)
        assert math.isclose(area, 13.0, rel_tol=1e-4), f"expected area 13.0, got {area}"

    def test_difference_area(self):
        # Difference = 12 - 3 = 9.0
        result = run_op(L_SHAPE, L_RECT, DIFFERENCE)
        assert result is not None
        area = multi_polygon_area(result)
        assert math.isclose(area, 9.0, rel_tol=1e-4), f"expected area 9.0, got {area}"

    def test_xor_area(self):
        # XOR = union - intersection = 13 - 3 = 10, or equivalently 12 + 4 - 2*3 = 10
        result = run_op(L_SHAPE, L_RECT, XOR)
        assert result is not None
        area = multi_polygon_area(result)
        assert math.isclose(area, 10.0, rel_tol=1e-4), f"expected area 10.0, got {area}"

    def test_area_identity_concave(self):
        """area(L) + area(rect) = area(intersection) + area(union)"""
        i_result = run_op(L_SHAPE, L_RECT, INTERSECTION)
        u_result = run_op(L_SHAPE, L_RECT, UNION)
        assert i_result is not None and u_result is not None
        total = multi_polygon_area(i_result) + multi_polygon_area(u_result)
        # 12 + 4 = 16
        assert math.isclose(total, 16.0, rel_tol=1e-4), (
            f"area identity failed: {total} != 16.0"
        )

    def test_concave_rings_closed(self):
        for op in [INTERSECTION, UNION, DIFFERENCE, XOR]:
            result = run_op(L_SHAPE, L_RECT, op)
            if result is not None:
                for poly in result:
                    for ring in poly:
                        assert len(ring) >= 4, f"ring too short (op={op}): {len(ring)}"
                        assert ring[0] == ring[-1], f"ring not closed (op={op})"


# ----------- MultiPolygon input handling -----------

class TestMultiPolygonInput:
    """Test operations with MultiPolygon subject input."""

    def test_multi_intersection_area(self):
        # Two squares (area 4 each) at x=[0,2] and x=[5,7]
        # Clipped by rectangle at y=[0.5,1.5] x=[1,6] (area=5)
        # Sq1 cap clip: x=[1,2] y=[0.5,1.5] area=1
        # Sq2 cap clip: x=[5,6] y=[0.5,1.5] area=1
        # Total = 2.0
        result = run_op(MULTI_SUBJ, MULTI_CLIP, INTERSECTION)
        assert result is not None, "multi-polygon intersection should not be null"
        area = multi_polygon_area(result)
        assert math.isclose(area, 2.0, rel_tol=1e-4), f"expected area 2.0, got {area}"

    def test_multi_union_area(self):
        # Union = 8 + 5 - 2 = 11.0
        result = run_op(MULTI_SUBJ, MULTI_CLIP, UNION)
        assert result is not None
        area = multi_polygon_area(result)
        assert math.isclose(area, 11.0, rel_tol=1e-4), f"expected area 11.0, got {area}"

    def test_multi_area_identity(self):
        """area(multi_subj) + area(clip) = area(intersection) + area(union)"""
        i_result = run_op(MULTI_SUBJ, MULTI_CLIP, INTERSECTION)
        u_result = run_op(MULTI_SUBJ, MULTI_CLIP, UNION)
        assert i_result is not None and u_result is not None
        total = multi_polygon_area(i_result) + multi_polygon_area(u_result)
        # subject area 8 + clipping area 5 = 13
        assert math.isclose(total, 13.0, rel_tol=1e-4), (
            f"area identity failed: {total} != 13.0"
        )

    def test_multi_difference_area(self):
        # Difference = subject - intersection = 8 - 2 = 6.0
        result = run_op(MULTI_SUBJ, MULTI_CLIP, DIFFERENCE)
        assert result is not None
        area = multi_polygon_area(result)
        assert math.isclose(area, 6.0, rel_tol=1e-4), f"expected area 6.0, got {area}"

    def test_multi_xor_produces_result(self):
        """XOR of multi-polygon input produces non-null result with valid rings."""
        result = run_op(MULTI_SUBJ, MULTI_CLIP, XOR)
        assert result is not None, "multi-polygon xor should not be null"
        assert len(result) >= 1, "xor should produce at least one polygon"
        for poly in result:
            for ring in poly:
                assert len(ring) >= 4, f"ring too short: {len(ring)} points"
                assert ring[0] == ring[-1], f"ring not closed: {ring[0]} != {ring[-1]}"


# ----------- Ring closure verification -----------

class TestRingClosure:
    """Verify that all output rings are properly closed."""

    def test_closed_rings_intersection(self):
        result = run_op(RECT_A, RECT_B, INTERSECTION)
        assert result is not None
        for poly in result:
            for ring in poly:
                assert len(ring) >= 4, f"ring too short: {len(ring)} points"
                assert ring[0] == ring[-1], f"ring not closed: {ring[0]} != {ring[-1]}"

    def test_closed_rings_union(self):
        result = run_op(BIG_SQUARE, SMALL_SQUARE, UNION)
        assert result is not None
        for poly in result:
            for ring in poly:
                assert len(ring) >= 4, f"ring too short: {len(ring)} points"
                assert ring[0] == ring[-1], f"ring not closed: {ring[0]} != {ring[-1]}"

    def test_closed_rings_difference_with_hole(self):
        result = run_op(BIG_SQUARE, SMALL_SQUARE, DIFFERENCE)
        assert result is not None
        for poly in result:
            for ring in poly:
                assert len(ring) >= 4, f"ring too short: {len(ring)} points"
                assert ring[0] == ring[-1], f"ring not closed: {ring[0]} != {ring[-1]}"
