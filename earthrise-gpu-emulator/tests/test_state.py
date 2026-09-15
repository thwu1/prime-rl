
import subprocess
import os
import pytest

WIDTH = 160
HEIGHT = 120
CANVAS_SIZE = WIDTH * HEIGHT


def run_emulator(program, output):
    result = subprocess.run(
        ["python3", "/app/emulator.py", program, output],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Emulator failed with stderr: {result.stderr}"


def read_fb(path):
    with open(path, "rb") as f:
        data = f.read()
    assert len(data) == CANVAS_SIZE, f"Expected {CANVAS_SIZE} bytes, got {len(data)}"
    return data


def px(fb, x, y):
    return fb[y * WIDTH + x]


# ---------------------------------------------------------------------------
# Reference implementations matching the hardware exactly
# Uses dict {(x,y): color} so later draws overwrite earlier ones.
# ---------------------------------------------------------------------------


def ref_line(fb_dict, x0, y0, x1, y1, c):
    """Reference draw_line matching draw_line.sv."""
    if y0 > y1:
        x0, x1 = x1, x0
        y0, y1 = y1, y0
    right = x0 < x1
    dx = (x1 - x0) if right else (x0 - x1)
    dy = y0 - y1
    err = dx + dy
    x, y = x0, y0
    while True:
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            fb_dict[(x, y)] = c
        if x == x1 and y == y1:
            break
        mx = 2 * err >= dy
        my = 2 * err <= dx
        if mx and my:
            x += 1 if right else -1
            y += 1
            err += dy + dx
        elif mx:
            x += 1 if right else -1
            err += dy
        elif my:
            y += 1
            err += dx


def ref_circle(fb_dict, cx, cy, r, c):
    """Reference draw_circle matching draw_circle.sv."""
    if r <= 0:
        if r == 0:
            if 0 <= cx < WIDTH and 0 <= cy < HEIGHT:
                fb_dict[(cx, cy)] = c
        return
    xa, ya = -r, 0
    err = 2 - 2 * r
    while True:
        for qx, qy in [
            (cx - xa, cy + ya),
            (cx + xa, cy + ya),
            (cx + xa, cy - ya),
            (cx - xa, cy - ya),
        ]:
            if 0 <= qx < WIDTH and 0 <= qy < HEIGHT:
                fb_dict[(qx, qy)] = c
        if xa == 0:
            break
        err_tmp = err
        if err <= ya:
            ya += 1
            err += 2 * ya + 1
        if err_tmp > xa or err > ya:
            xa += 1
            err += 2 * xa + 1


def ref_rect(fb_dict, x0, y0, x1, y1, c):
    """Reference draw_rectangle matching draw_rectangle.sv (4 lines)."""
    ref_line(fb_dict, x0, y0, x1, y0, c)
    ref_line(fb_dict, x1, y0, x1, y1, c)
    ref_line(fb_dict, x1, y1, x0, y1, c)
    ref_line(fb_dict, x0, y1, x0, y0, c)


def ref_filled_rect(fb_dict, x0, y0, x1, y1, c):
    lx, hx = min(x0, x1), max(x0, x1)
    ly, hy = min(y0, y1), max(y0, y1)
    for yy in range(ly, hy + 1):
        for xx in range(lx, hx + 1):
            if 0 <= xx < WIDTH and 0 <= yy < HEIGHT:
                fb_dict[(xx, yy)] = c


def ref_filled_triangle(fb_dict, x0, y0, x1, y1, x2, y2, c):
    """Reference draw_triangle_fill matching draw_triangle_fill.sv.

    Edge function rasterization with incremental evaluation.
    """
    sa01 = y0 - y1
    sa12 = y1 - y2
    sa20 = y2 - y0
    sb01 = x1 - x0
    sb12 = x2 - x1
    sb20 = x0 - x2
    cross = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
    cw = cross < 0
    bbx0 = min(x0, x1, x2)
    bby0 = min(y0, y1, y2)
    bbx1 = max(x0, x1, x2)
    bby1 = max(y0, y1, y2)
    w0_row = (bbx0 - x0) * sa01 + (bby0 - y0) * sb01
    w1_row = (bbx0 - x1) * sa12 + (bby0 - y1) * sb12
    w2_row = (bbx0 - x2) * sa20 + (bby0 - y2) * sb20
    for scan_y in range(bby0, bby1 + 1):
        w0 = w0_row
        w1 = w1_row
        w2 = w2_row
        for scan_x in range(bbx0, bbx1 + 1):
            if cw:
                inside = w0 <= 0 and w1 <= 0 and w2 <= 0
            else:
                inside = w0 >= 0 and w1 >= 0 and w2 >= 0
            if inside:
                if 0 <= scan_x < WIDTH and 0 <= scan_y < HEIGHT:
                    fb_dict[(scan_x, scan_y)] = c
            w0 += sa01
            w1 += sa12
            w2 += sa20
        w0_row += sb01
        w1_row += sb12
        w2_row += sb20


def ref_triangle_outline(fb_dict, x0, y0, x1, y1, x2, y2, c):
    ref_line(fb_dict, x0, y0, x1, y1, c)
    ref_line(fb_dict, x1, y1, x2, y2, c)
    ref_line(fb_dict, x2, y2, x0, y0, c)


def build_reference_fb(fb_dict):
    """Build framebuffer from dict {(x,y): color}."""
    fb = bytearray(CANVAS_SIZE)
    for (x, y), c in fb_dict.items():
        fb[y * WIDTH + x] = c
    return fb


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fb_primitives(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("prim") / "out.raw")
    run_emulator("/app/programs/test_primitives.hex", out)
    return read_fb(out)


@pytest.fixture(scope="module")
def fb_shapes(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("shapes") / "out.raw")
    run_emulator("/app/programs/test_shapes.hex", out)
    return read_fb(out)


@pytest.fixture(scope="module")
def fb_composite(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("comp") / "out.raw")
    run_emulator("/app/programs/test_composite.hex", out)
    return read_fb(out)


@pytest.fixture(scope="module")
def fb_triangles(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("tri") / "out.raw")
    run_emulator("/app/programs/test_triangles.hex", out)
    return read_fb(out)


@pytest.fixture(scope="module")
def fb_combined(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("comb") / "out.raw")
    run_emulator("/app/programs/test_combined.hex", out)
    return read_fb(out)


# ===================================================================
# Test: Primitives
# ===================================================================


class TestPixel:
    def test_pixel_set(self, fb_primitives):
        assert px(fb_primitives, 10, 10) == 1

    def test_pixel_neighbors_clear(self, fb_primitives):
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            assert px(fb_primitives, 10 + dx, 10 + dy) == 0


class TestHorizontalLine:
    def test_all_pixels_set(self, fb_primitives):
        for x in range(20, 41):
            assert px(fb_primitives, x, 15) == 2, f"Missing pixel at ({x}, 15)"

    def test_endpoints_only(self, fb_primitives):
        assert px(fb_primitives, 19, 15) == 0
        assert px(fb_primitives, 41, 15) == 0

    def test_above_below_clear(self, fb_primitives):
        assert px(fb_primitives, 30, 14) == 0
        assert px(fb_primitives, 30, 16) == 0


class TestVerticalLine:
    def test_all_pixels_set(self, fb_primitives):
        for y in range(5, 31):
            assert px(fb_primitives, 50, y) == 3, f"Missing pixel at (50, {y})"

    def test_endpoints_only(self, fb_primitives):
        assert px(fb_primitives, 50, 4) == 0
        assert px(fb_primitives, 50, 31) == 0

    def test_left_right_clear(self, fb_primitives):
        assert px(fb_primitives, 49, 15) == 0
        assert px(fb_primitives, 51, 15) == 0


class TestDiagonalLine:
    def test_perfect_diagonal(self, fb_primitives):
        """Line from (60,10) to (80,30): dx=dy=20, every step is both x+1 y+1."""
        for i in range(21):
            assert px(fb_primitives, 60 + i, 10 + i) == 4, f"Missing at offset {i}"

    def test_off_diagonal_clear(self, fb_primitives):
        assert px(fb_primitives, 61, 10) == 0
        assert px(fb_primitives, 60, 11) == 0


class TestSwapLine:
    """Line from (100,60) to (130,40): y0 > y1 triggers endpoint swap."""

    def test_both_endpoints_drawn(self, fb_primitives):
        assert px(fb_primitives, 100, 60) == 5
        assert px(fb_primitives, 130, 40) == 5

    def test_midpoint_drawn(self, fb_primitives):
        assert px(fb_primitives, 115, 50) == 5

    def test_total_pixels(self, fb_primitives):
        count = sum(1 for i in range(CANVAS_SIZE) if fb_primitives[i] == 5)
        assert count == 31


# ===================================================================
# Test: Shapes
# ===================================================================


class TestCircle:
    """Circle at (40,40) radius 5."""

    def test_axis_points(self, fb_shapes):
        assert px(fb_shapes, 45, 40) == 1
        assert px(fb_shapes, 35, 40) == 1
        assert px(fb_shapes, 40, 45) == 1
        assert px(fb_shapes, 40, 35) == 1

    def test_center_empty(self, fb_shapes):
        assert px(fb_shapes, 40, 40) == 0

    def test_pixel_count(self, fb_shapes):
        count = sum(1 for i in range(CANVAS_SIZE) if fb_shapes[i] == 1)
        assert count == 28

    def test_x_symmetry(self, fb_shapes):
        for x in range(WIDTH):
            for y in range(HEIGHT):
                if px(fb_shapes, x, y) == 1:
                    mx = 80 - x
                    if 0 <= mx < WIDTH:
                        assert px(fb_shapes, mx, y) == 1, (
                            f"X-asymmetry at ({x},{y})"
                        )

    def test_y_symmetry(self, fb_shapes):
        for x in range(WIDTH):
            for y in range(HEIGHT):
                if px(fb_shapes, x, y) == 1:
                    my = 80 - y
                    if 0 <= my < HEIGHT:
                        assert px(fb_shapes, x, my) == 1, (
                            f"Y-asymmetry at ({x},{y})"
                        )

    def test_matches_reference(self, fb_shapes):
        ref = {}
        ref_circle(ref, 40, 40, 5, 1)
        for (x, y), c in ref.items():
            assert px(fb_shapes, x, y) == c, f"Mismatch at ({x},{y})"
        emulator_pixels = {
            (x, y)
            for x in range(WIDTH)
            for y in range(HEIGHT)
            if px(fb_shapes, x, y) == 1
        }
        ref_pixels = set(ref.keys())
        assert emulator_pixels == ref_pixels


class TestOutlineRect:
    """Outline rectangle from (80,20) to (120,50)."""

    def test_top_edge(self, fb_shapes):
        for x in range(80, 121):
            assert px(fb_shapes, x, 20) == 2

    def test_bottom_edge(self, fb_shapes):
        for x in range(80, 121):
            assert px(fb_shapes, x, 50) == 2

    def test_left_edge(self, fb_shapes):
        for y in range(20, 51):
            assert px(fb_shapes, 80, y) == 2

    def test_right_edge(self, fb_shapes):
        for y in range(20, 51):
            assert px(fb_shapes, 120, y) == 2

    def test_interior_empty(self, fb_shapes):
        assert px(fb_shapes, 100, 35) == 0
        assert px(fb_shapes, 90, 30) == 0

    def test_exterior_empty(self, fb_shapes):
        assert px(fb_shapes, 79, 35) == 0
        assert px(fb_shapes, 121, 35) == 0
        assert px(fb_shapes, 100, 19) == 0
        assert px(fb_shapes, 100, 51) == 0


class TestFilledRect:
    """Filled rectangle from (10,70) to (60,100)."""

    def test_interior_filled(self, fb_shapes):
        for x in [10, 35, 60]:
            for y in [70, 85, 100]:
                assert px(fb_shapes, x, y) == 3, f"Not filled at ({x},{y})"

    def test_full_coverage(self, fb_shapes):
        count = sum(1 for i in range(CANVAS_SIZE) if fb_shapes[i] == 3)
        expected = (60 - 10 + 1) * (100 - 70 + 1)
        assert count == expected

    def test_exterior_empty(self, fb_shapes):
        assert px(fb_shapes, 9, 85) == 0
        assert px(fb_shapes, 61, 85) == 0
        assert px(fb_shapes, 35, 69) == 0
        assert px(fb_shapes, 35, 101) == 0


# ===================================================================
# Test: Composite (overlapping shapes)
# ===================================================================


class TestComposite:
    """Background fill (1), circle (2), rect outline (3), diagonal line (4)."""

    def test_background_corners(self, fb_composite):
        assert px(fb_composite, 0, 119) == 1
        assert px(fb_composite, 159, 0) == 1

    def test_circle_axis_point(self, fb_composite):
        assert px(fb_composite, 80, 40) == 2
        assert px(fb_composite, 40, 40) == 2
        assert px(fb_composite, 60, 60) == 2
        assert px(fb_composite, 60, 20) == 2

    def test_circle_center_is_background(self, fb_composite):
        assert px(fb_composite, 60, 40) == 1

    def test_rect_edges(self, fb_composite):
        assert px(fb_composite, 90, 10) == 3
        assert px(fb_composite, 140, 10) == 3
        assert px(fb_composite, 90, 70) == 3
        assert px(fb_composite, 140, 70) == 3

    def test_rect_interior_background(self, fb_composite):
        assert px(fb_composite, 115, 40) == 1

    def test_diagonal_line_endpoints(self, fb_composite):
        assert px(fb_composite, 5, 5) == 4
        assert px(fb_composite, 155, 115) == 4

    def test_line_overwrites_background(self, fb_composite):
        assert px(fb_composite, 5, 5) == 4

    def test_full_reference_comparison(self, fb_composite):
        ref = {}
        ref_filled_rect(ref, 0, 0, 159, 119, 1)
        ref_circle(ref, 60, 40, 20, 2)
        ref_rect(ref, 90, 10, 140, 70, 3)
        ref_line(ref, 5, 5, 155, 115, 4)
        ref_fb = build_reference_fb(ref)
        mismatches = []
        for i in range(CANVAS_SIZE):
            if fb_composite[i] != ref_fb[i]:
                x = i % WIDTH
                y = i // WIDTH
                mismatches.append((x, y, fb_composite[i], ref_fb[i]))
        assert len(mismatches) == 0, (
            f"{len(mismatches)} pixel mismatches, first 10: {mismatches[:10]}"
        )


# ===================================================================
# Test: Filled triangles
# ===================================================================


class TestFilledTriangleCCW:
    """Filled CCW triangle: (10,10)-(50,10)-(30,40) color 1."""

    def test_vertex_0(self, fb_triangles):
        assert px(fb_triangles, 10, 10) == 1

    def test_vertex_1(self, fb_triangles):
        assert px(fb_triangles, 50, 10) == 1

    def test_vertex_2(self, fb_triangles):
        assert px(fb_triangles, 30, 40) == 1

    def test_interior_center(self, fb_triangles):
        """Point (30, 20) is well inside the triangle."""
        assert px(fb_triangles, 30, 20) == 1

    def test_top_edge_filled(self, fb_triangles):
        """The top edge from (10,10) to (50,10) should be filled."""
        for x in range(10, 51):
            assert px(fb_triangles, x, 10) == 1, f"Top edge missing at ({x}, 10)"

    def test_outside_left(self, fb_triangles):
        """Point (9,10) is outside the triangle."""
        assert px(fb_triangles, 9, 10) == 0

    def test_outside_right(self, fb_triangles):
        """Point (51,10) is outside the triangle."""
        assert px(fb_triangles, 51, 10) == 0

    def test_outside_below(self, fb_triangles):
        """Point (30,41) is below the bottom vertex."""
        assert px(fb_triangles, 30, 41) == 0

    def test_matches_reference(self, fb_triangles):
        ref = {}
        ref_filled_triangle(ref, 10, 10, 50, 10, 30, 40, 1)
        ref_fb = build_reference_fb(ref)
        for (x, y), c in ref.items():
            assert px(fb_triangles, x, y) == c, (
                f"Missing/wrong at ({x},{y}): got {px(fb_triangles, x, y)} expected {c}"
            )
        emu_pixels = {
            (x, y)
            for x in range(WIDTH)
            for y in range(HEIGHT)
            if px(fb_triangles, x, y) == 1
        }
        ref_pixels = set(ref.keys())
        extra = emu_pixels - ref_pixels
        assert len(extra) == 0, f"Extra pixels: {list(extra)[:10]}"
        missing = ref_pixels - emu_pixels
        assert len(missing) == 0, f"Missing pixels: {list(missing)[:10]}"


class TestOutlineTriangle:
    """Outline triangle: (80,10)-(120,10)-(100,40) color 2."""

    def test_edge_0_midpoint(self, fb_triangles):
        """Top edge midpoint (100,10) drawn."""
        assert px(fb_triangles, 100, 10) == 2

    def test_vertex_2(self, fb_triangles):
        assert px(fb_triangles, 100, 40) == 2

    def test_interior_empty(self, fb_triangles):
        """Interior of outline triangle should be empty."""
        assert px(fb_triangles, 100, 25) == 0

    def test_matches_reference(self, fb_triangles):
        ref = {}
        ref_triangle_outline(ref, 80, 10, 120, 10, 100, 40, 2)
        ref_fb = build_reference_fb(ref)
        emu_pixels = {
            (x, y) for x in range(WIDTH) for y in range(HEIGHT)
            if px(fb_triangles, x, y) == 2
        }
        ref_pixels = set(ref.keys())
        assert emu_pixels == ref_pixels, (
            f"Mismatch: extra={list(emu_pixels - ref_pixels)[:5]}, "
            f"missing={list(ref_pixels - emu_pixels)[:5]}"
        )


class TestFilledTriangleCW:
    """Filled CW triangle: (70,60)-(70,100)-(100,80) color 3."""

    def test_vertices(self, fb_triangles):
        assert px(fb_triangles, 70, 60) == 3
        assert px(fb_triangles, 70, 100) == 3
        assert px(fb_triangles, 100, 80) == 3

    def test_interior(self, fb_triangles):
        """Point (80, 80) is inside."""
        assert px(fb_triangles, 80, 80) == 3

    def test_outside_left(self, fb_triangles):
        """Point (69,80) is outside (left of leftmost vertex)."""
        assert px(fb_triangles, 69, 80) == 0

    def test_matches_reference(self, fb_triangles):
        ref = {}
        ref_filled_triangle(ref, 70, 60, 70, 100, 100, 80, 3)
        ref_fb = build_reference_fb(ref)
        emu_pixels = {
            (x, y) for x in range(WIDTH) for y in range(HEIGHT)
            if px(fb_triangles, x, y) == 3
        }
        ref_pixels = set(ref.keys())
        assert emu_pixels == ref_pixels, (
            f"CW triangle mismatch: extra={list(emu_pixels - ref_pixels)[:5]}, "
            f"missing={list(ref_pixels - emu_pixels)[:5]}"
        )


class TestTrianglesFullReference:
    """Full pixel comparison of entire triangle test framebuffer."""

    def test_full_reference(self, fb_triangles):
        ref = {}
        ref_filled_triangle(ref, 10, 10, 50, 10, 30, 40, 1)
        ref_triangle_outline(ref, 80, 10, 120, 10, 100, 40, 2)
        ref_filled_triangle(ref, 70, 60, 70, 100, 100, 80, 3)
        ref_fb = build_reference_fb(ref)
        mismatches = []
        for i in range(CANVAS_SIZE):
            if fb_triangles[i] != ref_fb[i]:
                x = i % WIDTH
                y = i // WIDTH
                mismatches.append((x, y, fb_triangles[i], ref_fb[i]))
        assert len(mismatches) == 0, (
            f"{len(mismatches)} mismatches, first 10: {mismatches[:10]}"
        )


# ===================================================================
# Test: Combined scene (triangles + other shapes)
# ===================================================================


class TestCombined:
    """Background(1), filled triangle(2), circle(3), line(4)."""

    def test_background_corners(self, fb_combined):
        assert px(fb_combined, 0, 0) == 1
        assert px(fb_combined, 159, 119) == 1

    def test_triangle_interior(self, fb_combined):
        """Triangle (20,20)-(60,20)-(40,50): center area should be color 2."""
        assert px(fb_combined, 40, 30) == 2

    def test_triangle_vertex(self, fb_combined):
        assert px(fb_combined, 40, 50) == 2

    def test_circle_axis(self, fb_combined):
        """Circle at (100,60) r=15: right axis point."""
        assert px(fb_combined, 115, 60) == 3

    def test_circle_center_background(self, fb_combined):
        """Circle center is outline only, so should be background color 1."""
        assert px(fb_combined, 100, 60) == 1

    def test_line_overwrites_triangle(self, fb_combined):
        """Line y=35 crosses the triangle. At x=30 the line should overwrite."""
        assert px(fb_combined, 30, 35) == 4

    def test_line_overwrites_background(self, fb_combined):
        """Line pixel outside triangle should be line color 4."""
        assert px(fb_combined, 65, 35) == 4

    def test_full_reference(self, fb_combined):
        ref = {}
        ref_filled_rect(ref, 0, 0, 159, 119, 1)
        ref_filled_triangle(ref, 20, 20, 60, 20, 40, 50, 2)
        ref_circle(ref, 100, 60, 15, 3)
        ref_line(ref, 10, 35, 70, 35, 4)
        ref_fb = build_reference_fb(ref)
        mismatches = []
        for i in range(CANVAS_SIZE):
            if fb_combined[i] != ref_fb[i]:
                x = i % WIDTH
                y = i // WIDTH
                mismatches.append((x, y, fb_combined[i], ref_fb[i]))
        assert len(mismatches) == 0, (
            f"{len(mismatches)} combined mismatches, first 10: {mismatches[:10]}"
        )


# ===================================================================
# Test: Negative coordinates & clipping
# ===================================================================


class TestClipping:
    def test_negative_coordinate_line(self, tmp_path):
        """Line starting off-screen with negative x should be clipped."""
        prog = tmp_path / "neg.hex"
        prog.write_text(
            "C001\n"
            "0FFB\n"
            "1005\n"
            "200A\n"
            "3005\n"
            "D100\n"
            "CE00\n"
        )
        out = str(tmp_path / "neg.raw")
        run_emulator(str(prog), out)
        fb = read_fb(out)
        for x in range(0, 11):
            assert px(fb, x, 5) == 1, f"Missing clipped pixel at ({x}, 5)"
        count = sum(1 for b in fb if b == 1)
        assert count == 11

    def test_triangle_partial_clip(self, tmp_path):
        """Filled triangle with one vertex off-screen (negative coords)."""
        prog = tmp_path / "triclip.hex"
        prog.write_text(
            "C201\n"
            "0FF6\n"
            "1FF6\n"
            "2014\n"
            "3FF6\n"
            "4005\n"
            "5014\n"
            "D201\n"
            "CE00\n"
        )
        out = str(tmp_path / "triclip.raw")
        run_emulator(str(prog), out)
        fb = read_fb(out)
        assert px(fb, 0, 0) == 1
        assert px(fb, 5, 20) == 1
        ref = {}
        ref_filled_triangle(ref, -10, -10, 20, -10, 5, 20, 1)
        ref_fb = build_reference_fb(ref)
        for i in range(CANVAS_SIZE):
            assert fb[i] == ref_fb[i], (
                f"Clip mismatch at ({i % WIDTH},{i // WIDTH})"
            )


# ===================================================================
# Test: Register persistence
# ===================================================================


class TestRegisterPersistence:
    def test_reuse_coordinates(self, tmp_path):
        """Registers persist: second draw should reuse unchanged registers."""
        prog = tmp_path / "persist.hex"
        prog.write_text(
            "C001\n"
            "C002\n"
            "0000\n"
            "1000\n"
            "200A\n"
            "300A\n"
            "D100\n"
            "C003\n"
            "2014\n"
            "D100\n"
            "CE00\n"
        )
        out = str(tmp_path / "persist.raw")
        run_emulator(str(prog), out)
        fb = read_fb(out)
        assert px(fb, 0, 0) == 3
        assert px(fb, 20, 10) == 3
        assert px(fb, 10, 10) == 2


# ===================================================================
# Test: Edge case - degenerate triangles
# ===================================================================


class TestDegenerateTriangle:
    def test_collinear_horizontal(self, tmp_path):
        """Degenerate triangle with all vertices on same y (collinear horizontal)."""
        prog = tmp_path / "degen_h.hex"
        prog.write_text(
            "C201\n"
            "000A\n"
            "1032\n"
            "2032\n"
            "3032\n"
            "401E\n"
            "5032\n"
            "D201\n"
            "CE00\n"
        )
        out = str(tmp_path / "degen_h.raw")
        run_emulator(str(prog), out)
        fb = read_fb(out)
        ref = {}
        ref_filled_triangle(ref, 10, 50, 50, 50, 30, 50, 1)
        ref_fb = build_reference_fb(ref)
        for i in range(CANVAS_SIZE):
            assert fb[i] == ref_fb[i]

    def test_single_point_triangle(self, tmp_path):
        """All three vertices at the same point - single pixel."""
        prog = tmp_path / "degen_pt.hex"
        prog.write_text(
            "C201\n"
            "0014\n"
            "1014\n"
            "2014\n"
            "3014\n"
            "4014\n"
            "5014\n"
            "D201\n"
            "CE00\n"
        )
        out = str(tmp_path / "degen_pt.raw")
        run_emulator(str(prog), out)
        fb = read_fb(out)
        assert px(fb, 20, 20) == 1
        count = sum(1 for b in fb if b == 1)
        assert count == 1


# ===================================================================
# Test: Full reference match for all standard programs
# ===================================================================


class TestFullReferenceMatch:
    def test_primitives_reference(self, fb_primitives):
        ref = {}
        ref[(10, 10)] = 1
        ref_line(ref, 20, 15, 40, 15, 2)
        ref_line(ref, 50, 5, 50, 30, 3)
        ref_line(ref, 60, 10, 80, 30, 4)
        ref_line(ref, 100, 60, 130, 40, 5)
        ref_fb = build_reference_fb(ref)
        mismatches = []
        for i in range(CANVAS_SIZE):
            if fb_primitives[i] != ref_fb[i]:
                x = i % WIDTH
                y = i // WIDTH
                mismatches.append((x, y, fb_primitives[i], ref_fb[i]))
        assert len(mismatches) == 0, (
            f"{len(mismatches)} mismatches, first 10: {mismatches[:10]}"
        )

    def test_shapes_reference(self, fb_shapes):
        ref = {}
        ref_circle(ref, 40, 40, 5, 1)
        ref_rect(ref, 80, 20, 120, 50, 2)
        ref_filled_rect(ref, 10, 70, 60, 100, 3)
        ref_fb = build_reference_fb(ref)
        mismatches = []
        for i in range(CANVAS_SIZE):
            if fb_shapes[i] != ref_fb[i]:
                x = i % WIDTH
                y = i // WIDTH
                mismatches.append((x, y, fb_shapes[i], ref_fb[i]))
        assert len(mismatches) == 0, (
            f"{len(mismatches)} mismatches, first 10: {mismatches[:10]}"
        )
