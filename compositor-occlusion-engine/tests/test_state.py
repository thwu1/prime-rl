
import pytest
import sys
import subprocess
import os
import time

sys.path.insert(0, "/app")


# ---------------------------------------------------------------------------
# Shared library existence
# ---------------------------------------------------------------------------
class TestSharedLibrary:
    """Verify the compiled C library exists and is loadable."""

    def test_shared_library_exists(self):
        assert os.path.exists("/app/libregion.so"), (
            "libregion.so not found at /app/ — build with make"
        )

    def test_shared_library_loadable(self):
        import ctypes
        lib = ctypes.CDLL("/app/libregion.so")
        assert lib is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _validate_subtraction(result, base, occluder):
    """Validate rect_subtract correctness via invariants, without assuming
    any particular decomposition strategy or result ordering."""
    bx, by, bw, bh = base
    ox, oy, ow, oh = occluder

    # No zero-area rects
    for r in result:
        assert r[2] > 0 and r[3] > 0, f"Zero-area rect: {r}"

    # All within base bounds
    for r in result:
        assert r[0] >= bx and r[1] >= by, f"Out of base bounds: {r}"
        assert r[0] + r[2] <= bx + bw, f"Exceeds base right edge: {r}"
        assert r[1] + r[3] <= by + bh, f"Exceeds base bottom edge: {r}"

    # No overlap between result rects
    for i in range(len(result)):
        for j in range(i + 1, len(result)):
            a, b = result[i], result[j]
            ix = max(a[0], b[0])
            iy = max(a[1], b[1])
            ix2 = min(a[0] + a[2], b[0] + b[2])
            iy2 = min(a[1] + a[3], b[1] + b[3])
            assert ix >= ix2 or iy >= iy2, f"Result rects overlap: {a} and {b}"

    # Area conservation: result area == base area minus intersection area
    ix1, iy1 = max(bx, ox), max(by, oy)
    ix2 = min(bx + bw, ox + ow)
    iy2 = min(by + bh, oy + oh)
    int_area = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    result_area = sum(r[2] * r[3] for r in result)
    expected = bw * bh - int_area
    assert result_area == expected, (
        f"Area mismatch: base=({bx},{by},{bw},{bh}), "
        f"occ=({ox},{oy},{ow},{oh}), expected={expected}, got={result_area}"
    )


def _owner_at_pixel(regions, x, y):
    """Brute-force pixel ownership lookup for reference verification."""
    for owner, rects in regions.items():
        for rx, ry, rw, rh in rects:
            if rx <= x < rx + rw and ry <= y < ry + rh:
                return owner
    return None


# ---------------------------------------------------------------------------
# rect_subtract tests
# ---------------------------------------------------------------------------
class TestRectSubtract:
    def test_no_intersection(self):
        from engine import rect_subtract

        result = rect_subtract((0, 0, 10, 10), (20, 20, 5, 5))
        assert len(result) == 1
        assert result[0] == (0, 0, 10, 10)

    def test_full_occlusion(self):
        from engine import rect_subtract

        result = rect_subtract((5, 5, 10, 10), (0, 0, 20, 20))
        assert result == []

    def test_corner_overlap(self):
        from engine import rect_subtract

        result = rect_subtract((0, 0, 10, 10), (5, 5, 10, 10))
        _validate_subtraction(result, (0, 0, 10, 10), (5, 5, 10, 10))

    def test_center_cut(self):
        from engine import rect_subtract

        result = rect_subtract((0, 0, 10, 10), (3, 3, 4, 4))
        _validate_subtraction(result, (0, 0, 10, 10), (3, 3, 4, 4))

    def test_left_half_occluded(self):
        from engine import rect_subtract

        result = rect_subtract((0, 0, 10, 10), (0, 0, 5, 10))
        _validate_subtraction(result, (0, 0, 10, 10), (0, 0, 5, 10))

    def test_top_strip_occluded(self):
        from engine import rect_subtract

        result = rect_subtract((0, 0, 10, 10), (0, 0, 10, 3))
        _validate_subtraction(result, (0, 0, 10, 10), (0, 0, 10, 3))

    def test_bottom_right_corner(self):
        from engine import rect_subtract

        result = rect_subtract((0, 0, 10, 10), (5, 5, 5, 5))
        _validate_subtraction(result, (0, 0, 10, 10), (5, 5, 5, 5))

    def test_edge_overlap_right(self):
        from engine import rect_subtract

        result = rect_subtract((0, 0, 10, 10), (8, 0, 10, 10))
        _validate_subtraction(result, (0, 0, 10, 10), (8, 0, 10, 10))

    def test_edge_overlap_bottom(self):
        from engine import rect_subtract

        result = rect_subtract((0, 0, 10, 10), (0, 7, 10, 10))
        _validate_subtraction(result, (0, 0, 10, 10), (0, 7, 10, 10))

    def test_occluder_extends_all_sides(self):
        from engine import rect_subtract

        # Occluder wider on left/right but only covers a horizontal strip
        result = rect_subtract((10, 10, 20, 20), (5, 15, 30, 5))
        _validate_subtraction(result, (10, 10, 20, 20), (5, 15, 30, 5))

    def test_random_fuzz(self):
        from engine import rect_subtract
        import random

        random.seed(42)
        for _ in range(500):
            bx, by = random.randint(0, 100), random.randint(0, 100)
            bw, bh = random.randint(1, 50), random.randint(1, 50)
            ox, oy = random.randint(0, 100), random.randint(0, 100)
            ow, oh = random.randint(1, 50), random.randint(1, 50)

            result = rect_subtract((bx, by, bw, bh), (ox, oy, ow, oh))
            _validate_subtraction(
                result, (bx, by, bw, bh), (ox, oy, ow, oh)
            )


# ---------------------------------------------------------------------------
# compute_visible_regions tests
# ---------------------------------------------------------------------------
class TestVisibleRegions:
    def _check_invariants(self, result, screen_w, screen_h):
        all_rects = []
        for owner, rects in result.items():
            for r in rects:
                assert r[2] > 0 and r[3] > 0, f"Zero-area rect for {owner}: {r}"
                assert r[0] >= 0 and r[1] >= 0, f"Negative coord for {owner}: {r}"
                assert r[0] + r[2] <= screen_w, (
                    f"Exceeds screen width for {owner}: {r}"
                )
                assert r[1] + r[3] <= screen_h, (
                    f"Exceeds screen height for {owner}: {r}"
                )
                all_rects.append(r)

        total_area = sum(r[2] * r[3] for r in all_rects)
        assert total_area == screen_w * screen_h, (
            f"Total area {total_area} != {screen_w * screen_h}"
        )

        for i in range(len(all_rects)):
            for j in range(i + 1, len(all_rects)):
                a, b = all_rects[i], all_rects[j]
                ix = max(a[0], b[0])
                iy = max(a[1], b[1])
                ix2 = min(a[0] + a[2], b[0] + b[2])
                iy2 = min(a[1] + a[3], b[1] + b[3])
                assert ix >= ix2 or iy >= iy2, (
                    f"Overlap between rects: {a} and {b}"
                )

    def test_empty_screen(self):
        from engine import compute_visible_regions

        result = compute_visible_regions(100, 100, [])
        assert "bg" in result
        bg_area = sum(r[2] * r[3] for r in result["bg"])
        assert bg_area == 10000
        self._check_invariants(result, 100, 100)

    def test_single_window(self):
        from engine import compute_visible_regions

        result = compute_visible_regions(100, 100, [(1, 10, 10, 20, 20, 0)])
        assert 1 in result
        assert sum(r[2] * r[3] for r in result[1]) == 400
        assert sum(r[2] * r[3] for r in result["bg"]) == 9600
        self._check_invariants(result, 100, 100)

    def test_two_overlapping(self):
        from engine import compute_visible_regions

        result = compute_visible_regions(
            100, 100, [(1, 0, 0, 60, 60, 0), (2, 40, 40, 60, 60, 1)]
        )
        # Win2 on top: full 60x60
        assert sum(r[2] * r[3] for r in result[2]) == 3600
        # Win1: 3600 - overlap(40,40)-(60,60) = 3600 - 400 = 3200
        assert sum(r[2] * r[3] for r in result[1]) == 3200
        self._check_invariants(result, 100, 100)

    def test_fully_occluded(self):
        from engine import compute_visible_regions

        result = compute_visible_regions(
            100, 100, [(1, 20, 20, 10, 10, 0), (2, 10, 10, 40, 40, 1)]
        )
        assert sum(r[2] * r[3] for r in result[1]) == 0
        assert sum(r[2] * r[3] for r in result[2]) == 1600
        self._check_invariants(result, 100, 100)

    def test_window_partially_offscreen(self):
        from engine import compute_visible_regions

        result = compute_visible_regions(100, 100, [(1, -10, -10, 30, 30, 0)])
        # Clipped to (0,0,20,20)
        assert sum(r[2] * r[3] for r in result[1]) == 400
        self._check_invariants(result, 100, 100)

    def test_window_fully_offscreen(self):
        from engine import compute_visible_regions

        result = compute_visible_regions(100, 100, [(1, 200, 200, 50, 50, 0)])
        assert sum(r[2] * r[3] for r in result[1]) == 0
        self._check_invariants(result, 100, 100)

    def test_three_stacked(self):
        from engine import compute_visible_regions

        result = compute_visible_regions(
            100,
            100,
            [
                (1, 0, 0, 50, 50, 0),
                (2, 25, 25, 50, 50, 1),
                (3, 50, 50, 50, 50, 2),
            ],
        )
        # Win3 top: 2500
        assert sum(r[2] * r[3] for r in result[3]) == 2500
        # Win2: 2500 - overlap(50,50)-(75,75) = 2500 - 625 = 1875
        assert sum(r[2] * r[3] for r in result[2]) == 1875
        # Win1: 2500 - overlap(25,25)-(50,50) = 2500 - 625 = 1875
        assert sum(r[2] * r[3] for r in result[1]) == 1875
        self._check_invariants(result, 100, 100)

    def test_full_screen_window(self):
        from engine import compute_visible_regions

        result = compute_visible_regions(100, 100, [(1, 0, 0, 100, 100, 0)])
        assert sum(r[2] * r[3] for r in result[1]) == 10000
        assert sum(r[2] * r[3] for r in result["bg"]) == 0
        self._check_invariants(result, 100, 100)

    def test_random_20_windows(self):
        from engine import compute_visible_regions
        import random

        random.seed(42)
        windows = [
            (
                i,
                random.randint(0, 80),
                random.randint(0, 80),
                random.randint(5, 30),
                random.randint(5, 30),
                i,
            )
            for i in range(20)
        ]
        result = compute_visible_regions(100, 100, windows)
        self._check_invariants(result, 100, 100)

    def test_touching_windows_no_gap(self):
        from engine import compute_visible_regions

        # Two windows side by side covering full width
        result = compute_visible_regions(
            100, 100, [(1, 0, 0, 50, 100, 0), (2, 50, 0, 50, 100, 1)]
        )
        assert sum(r[2] * r[3] for r in result[1]) == 5000
        assert sum(r[2] * r[3] for r in result[2]) == 5000
        assert sum(r[2] * r[3] for r in result["bg"]) == 0
        self._check_invariants(result, 100, 100)

    def test_negative_coords_multiple_windows(self):
        from engine import compute_visible_regions

        result = compute_visible_regions(
            80,
            60,
            [
                (1, -20, -10, 50, 40, 0),
                (2, 50, 30, 60, 60, 1),
                (3, 10, 10, 30, 30, 2),
            ],
        )
        self._check_invariants(result, 80, 60)
        # Win3 at z=2 is fully on screen: 30*30 = 900 visible (topmost)
        assert sum(r[2] * r[3] for r in result[3]) == 900
        # Total must be 80*60 = 4800
        total = sum(
            sum(r[2] * r[3] for r in rects) for rects in result.values()
        )
        assert total == 4800

    def test_zero_size_window(self):
        from engine import compute_visible_regions

        result = compute_visible_regions(100, 100, [(1, 10, 10, 0, 0, 0)])
        assert sum(r[2] * r[3] for r in result.get("bg", [])) == 10000
        self._check_invariants(result, 100, 100)

    def test_comprehensive_random_50_windows(self):
        """Verify invariants hold across many random configurations."""
        from engine import compute_visible_regions
        import random

        random.seed(7654)
        for trial in range(10):
            sw = random.randint(100, 400)
            sh = random.randint(100, 400)
            nw = random.randint(10, 50)
            windows = [
                (i, random.randint(-50, sw), random.randint(-50, sh),
                 random.randint(10, 150), random.randint(10, 150), i)
                for i in range(nw)
            ]
            result = compute_visible_regions(sw, sh, windows)
            self._check_invariants(result, sw, sh)

    def test_pixel_ownership_correctness(self):
        """Verify pixel ownership against brute-force reference for a moderate scene."""
        from engine import compute_visible_regions

        sw, sh = 60, 60
        windows = [
            (1, 5, 5, 25, 25, 0),
            (2, 20, 10, 25, 25, 1),
            (3, 10, 30, 30, 20, 2),
            (4, 35, 35, 20, 20, 3),
        ]
        result = compute_visible_regions(sw, sh, windows)
        self._check_invariants(result, sw, sh)

        # Brute-force: determine owner of each pixel by z-order rule
        def expected_owner(px, py):
            best_owner = "bg"
            best_z = -1
            for wid, wx, wy, ww, wh, wz in windows:
                cx1 = max(0, wx)
                cy1 = max(0, wy)
                cx2 = min(sw, wx + ww)
                cy2 = min(sh, wy + wh)
                if cx1 <= px < cx2 and cy1 <= py < cy2:
                    if wz > best_z:
                        best_owner = wid
                        best_z = wz
            return best_owner

        for py in range(sh):
            for px in range(sw):
                actual = _owner_at_pixel(result, px, py)
                exp = expected_owner(px, py)
                assert actual == exp, (
                    f"Pixel ({px},{py}): expected owner {exp}, got {actual}"
                )


# ---------------------------------------------------------------------------
# merge_regions tests
# ---------------------------------------------------------------------------
class TestMergeRegions:
    def test_horizontal_merge(self):
        from engine import merge_regions

        result = merge_regions([(0, 0, 5, 10), (5, 0, 5, 10)])
        assert len(result) == 1
        assert result[0] == (0, 0, 10, 10)

    def test_vertical_merge(self):
        from engine import merge_regions

        result = merge_regions([(0, 0, 10, 5), (0, 5, 10, 5)])
        assert len(result) == 1
        assert result[0] == (0, 0, 10, 10)

    def test_chain_merge(self):
        from engine import merge_regions

        result = merge_regions([(0, 0, 5, 10), (5, 0, 5, 10), (10, 0, 5, 10)])
        assert len(result) == 1
        assert sum(r[2] * r[3] for r in result) == 150

    def test_no_merge_possible(self):
        from engine import merge_regions

        result = merge_regions([(0, 0, 5, 5), (10, 10, 5, 5)])
        assert len(result) == 2

    def test_grid_merge(self):
        from engine import merge_regions

        rects = [(0, 0, 5, 10), (5, 0, 5, 10), (0, 10, 5, 10), (5, 10, 5, 10)]
        result = merge_regions(rects)
        total_area = sum(r[2] * r[3] for r in result)
        assert total_area == 200
        assert len(result) <= 2  # should merge to at most 2 rows or 2 cols

    def test_preserves_area(self):
        from engine import merge_regions

        rects = [(i * 10, 0, 10, 10) for i in range(10)]
        result = merge_regions(rects)
        assert sum(r[2] * r[3] for r in result) == 1000
        assert len(result) == 1

    def test_empty(self):
        from engine import merge_regions

        assert merge_regions([]) == []

    def test_single(self):
        from engine import merge_regions

        result = merge_regions([(5, 5, 10, 10)])
        assert result == [(5, 5, 10, 10)]


# ---------------------------------------------------------------------------
# compute_dirty_regions tests
# ---------------------------------------------------------------------------
class TestDirtyRegions:
    def test_no_change(self):
        from engine import compute_visible_regions, compute_dirty_regions

        windows = [(1, 10, 10, 20, 20, 0)]
        old = compute_visible_regions(100, 100, windows)
        new = compute_visible_regions(100, 100, windows)
        dirty = compute_dirty_regions(old, new, 100, 100)
        dirty_px = sum(r[2] * r[3] for r in dirty)
        assert dirty_px == 0

    def test_simple_move(self):
        from engine import compute_visible_regions, compute_dirty_regions

        old = compute_visible_regions(100, 100, [(1, 10, 10, 20, 20, 0)])
        new = compute_visible_regions(100, 100, [(1, 50, 50, 20, 20, 0)])
        dirty = compute_dirty_regions(old, new, 100, 100)
        dirty_px = sum(r[2] * r[3] for r in dirty)
        # old position (400px) became bg, new position (400px) became window
        assert dirty_px == 800

    def test_z_reorder(self):
        from engine import compute_visible_regions, compute_dirty_regions

        old = compute_visible_regions(
            100, 100, [(1, 10, 10, 30, 30, 0), (2, 20, 20, 30, 30, 1)]
        )
        new = compute_visible_regions(
            100, 100, [(1, 10, 10, 30, 30, 2), (2, 20, 20, 30, 30, 0)]
        )
        dirty = compute_dirty_regions(old, new, 100, 100)
        dirty_px = sum(r[2] * r[3] for r in dirty)
        # Only the overlap (20,20)-(40,40) = 20*20 = 400px changes owner
        assert dirty_px == 400

    def test_window_added(self):
        from engine import compute_visible_regions, compute_dirty_regions

        old = compute_visible_regions(100, 100, [])
        new = compute_visible_regions(100, 100, [(1, 10, 10, 20, 20, 0)])
        dirty = compute_dirty_regions(old, new, 100, 100)
        dirty_px = sum(r[2] * r[3] for r in dirty)
        assert dirty_px == 400

    def test_window_removed(self):
        from engine import compute_visible_regions, compute_dirty_regions

        old = compute_visible_regions(100, 100, [(1, 10, 10, 20, 20, 0)])
        new = compute_visible_regions(100, 100, [])
        dirty = compute_dirty_regions(old, new, 100, 100)
        dirty_px = sum(r[2] * r[3] for r in dirty)
        assert dirty_px == 400

    def test_from_empty(self):
        from engine import compute_visible_regions, compute_dirty_regions

        old_regions = {}
        new = compute_visible_regions(100, 100, [(1, 10, 10, 20, 20, 0)])
        dirty = compute_dirty_regions(old_regions, new, 100, 100)
        dirty_px = sum(r[2] * r[3] for r in dirty)
        # Everything is dirty when old is empty
        assert dirty_px == 10000

    def test_resize_grow(self):
        from engine import compute_visible_regions, compute_dirty_regions

        old = compute_visible_regions(100, 100, [(1, 10, 10, 20, 20, 0)])
        new = compute_visible_regions(100, 100, [(1, 10, 10, 40, 40, 0)])
        dirty = compute_dirty_regions(old, new, 100, 100)
        dirty_px = sum(r[2] * r[3] for r in dirty)
        # New area = 1600, old area = 400, growth = 1200 was bg now window
        assert dirty_px == 1200

    def test_resize_shrink(self):
        from engine import compute_visible_regions, compute_dirty_regions

        old = compute_visible_regions(100, 100, [(1, 10, 10, 40, 40, 0)])
        new = compute_visible_regions(100, 100, [(1, 10, 10, 20, 20, 0)])
        dirty = compute_dirty_regions(old, new, 100, 100)
        dirty_px = sum(r[2] * r[3] for r in dirty)
        # old area = 1600, new area = 400, shrinkage = 1200 was window now bg
        assert dirty_px == 1200

    def test_cascading_expose(self):
        """Move a large topmost window off-screen to expose many underlying windows."""
        from engine import compute_visible_regions, compute_dirty_regions

        # 5 small windows under a large top window
        windows = [(i, i * 15, 0, 20, 80, i) for i in range(5)]
        windows.append((99, 0, 0, 100, 80, 10))  # topmost covers all
        old = compute_visible_regions(100, 80, windows)

        # Move topmost off screen
        new_windows = [(i, i * 15, 0, 20, 80, i) for i in range(5)]
        new_windows.append((99, 500, 500, 100, 80, 10))
        new = compute_visible_regions(100, 80, new_windows)

        dirty = compute_dirty_regions(old, new, 100, 80)
        dirty_px = sum(r[2] * r[3] for r in dirty)
        # Entire screen changed ownership (from w99 to underlying windows/bg)
        assert dirty_px == 8000  # 100 * 80

    def test_pixel_accurate_move_and_reorder(self):
        """Verify dirty regions match pixel-by-pixel ownership changes."""
        from engine import compute_visible_regions, compute_dirty_regions

        sw, sh = 60, 50
        old_w = [(1, 5, 5, 20, 20, 0), (2, 15, 15, 20, 20, 1), (3, 30, 5, 20, 20, 2)]
        new_w = [(1, 10, 10, 20, 20, 0), (2, 15, 15, 20, 20, 2), (3, 30, 5, 20, 20, 1)]

        old = compute_visible_regions(sw, sh, old_w)
        new = compute_visible_regions(sw, sh, new_w)
        dirty = compute_dirty_regions(old, new, sw, sh)
        dirty_px = sum(r[2] * r[3] for r in dirty)

        expected_dirty = 0
        for py in range(sh):
            for px in range(sw):
                if _owner_at_pixel(old, px, py) != _owner_at_pixel(new, px, py):
                    expected_dirty += 1

        assert dirty_px == expected_dirty, (
            f"Dirty mismatch: got {dirty_px}, expected {expected_dirty}"
        )

    def test_pixel_accurate_add_remove(self):
        """Verify dirty tracking when windows are added, removed, and resized."""
        from engine import compute_visible_regions, compute_dirty_regions

        sw, sh = 60, 60
        old_w = [(1, 0, 0, 30, 30, 0), (2, 20, 20, 30, 30, 1)]
        # w1 shrunk, w2 removed, w3 added
        new_w = [(1, 0, 0, 20, 20, 0), (3, 10, 10, 25, 25, 2)]

        old = compute_visible_regions(sw, sh, old_w)
        new = compute_visible_regions(sw, sh, new_w)
        dirty = compute_dirty_regions(old, new, sw, sh)
        dirty_px = sum(r[2] * r[3] for r in dirty)

        expected_dirty = 0
        for py in range(sh):
            for px in range(sw):
                if _owner_at_pixel(old, px, py) != _owner_at_pixel(new, px, py):
                    expected_dirty += 1

        assert dirty_px == expected_dirty, (
            f"Dirty mismatch: got {dirty_px}, expected {expected_dirty}"
        )


# ---------------------------------------------------------------------------
# Compositor script integration tests
# ---------------------------------------------------------------------------
class TestCompositorScript:
    def test_basic_scenario(self):
        scenario = "SCREEN 100 100\nCREATE 1 10 10 20 20 0\nFRAME\n"
        result = subprocess.run(
            ["python3", "/app/compositor.py"],
            input=scenario,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = result.stdout
        assert "FRAME 1" in out
        assert "END_FRAME" in out
        for line in out.split("\n"):
            if line.startswith("STATS"):
                parts = line.split()
                total_px = int(parts[1])
                dirty_px = int(parts[2])
                assert total_px == 10000
                # First frame: everything dirty
                assert dirty_px == 10000
                break
        else:
            pytest.fail("No STATS line found")

    def test_multiframe_move(self):
        scenario = (
            "SCREEN 100 100\n"
            "CREATE 1 10 10 20 20 0\n"
            "FRAME\n"
            "MOVE 1 50 50\n"
            "FRAME\n"
        )
        result = subprocess.run(
            ["python3", "/app/compositor.py"],
            input=scenario,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = result.stdout
        assert "FRAME 1" in out
        assert "FRAME 2" in out

        # Parse frame 2 stats
        in_frame2 = False
        for line in out.split("\n"):
            stripped = line.strip()
            if stripped == "FRAME 2":
                in_frame2 = True
            elif in_frame2 and stripped.startswith("STATS"):
                parts = stripped.split()
                total_px = int(parts[1])
                dirty_px = int(parts[2])
                assert total_px == 10000
                assert dirty_px == 800
                break
        else:
            pytest.fail("No STATS for frame 2")

    def test_output_sorting(self):
        scenario = (
            "SCREEN 100 100\n"
            "CREATE 1 60 60 30 30 0\n"
            "CREATE 2 10 10 30 30 1\n"
            "FRAME\n"
        )
        result = subprocess.run(
            ["python3", "/app/compositor.py"],
            input=scenario,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = result.stdout

        region_lines = [
            l.strip() for l in out.split("\n") if l.strip().startswith("REGION")
        ]
        # bg regions must come before window regions
        bg_indices = [i for i, l in enumerate(region_lines) if "bg" in l.split()[1]]
        win_indices = [i for i, l in enumerate(region_lines) if "bg" not in l.split()[1]]
        if bg_indices and win_indices:
            assert max(bg_indices) < min(win_indices), (
                "bg regions must appear before window regions"
            )

        # Window regions must be sorted by ascending id
        win_ids = []
        for l in region_lines:
            parts = l.split()
            if parts[1] != "bg":
                win_ids.append(int(parts[1]))
        for i in range(len(win_ids) - 1):
            assert win_ids[i] <= win_ids[i + 1], "Window regions not sorted by id"

        # DIRTY lines must be sorted by (y, x)
        dirty_lines = [
            l.strip() for l in out.split("\n") if l.strip().startswith("DIRTY")
        ]
        dirty_coords = []
        for l in dirty_lines:
            parts = l.split()
            dirty_coords.append((int(parts[2]), int(parts[1])))  # (y, x)
        for i in range(len(dirty_coords) - 1):
            assert dirty_coords[i] <= dirty_coords[i + 1], (
                "DIRTY lines not sorted by (y, x)"
            )

    def test_complex_scenario_file(self):
        result = subprocess.run(
            ["python3", "/app/compositor.py"],
            stdin=open("/app/scenarios/complex.txt"),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = result.stdout
        # Should have 3 frames
        assert out.count("END_FRAME") == 3
        # All frames should have total_pixels = 40000
        for line in out.split("\n"):
            if line.strip().startswith("STATS"):
                parts = line.strip().split()
                assert int(parts[1]) == 40000

    def test_destroy_and_recreate(self):
        scenario = (
            "SCREEN 80 80\n"
            "CREATE 1 10 10 30 30 0\n"
            "FRAME\n"
            "DESTROY 1\n"
            "FRAME\n"
            "CREATE 2 20 20 40 40 0\n"
            "FRAME\n"
        )
        result = subprocess.run(
            ["python3", "/app/compositor.py"],
            input=scenario,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = result.stdout
        assert out.count("END_FRAME") == 3

        # Frame 2: window destroyed, dirty = 900 (the window area)
        in_frame2 = False
        for line in out.split("\n"):
            stripped = line.strip()
            if stripped == "FRAME 2":
                in_frame2 = True
            elif stripped.startswith("FRAME 3"):
                break
            elif in_frame2 and stripped.startswith("STATS"):
                parts = stripped.split()
                assert int(parts[1]) == 6400  # 80*80
                assert int(parts[2]) == 900   # 30*30 destroyed
                break


# ---------------------------------------------------------------------------
# Performance tests
# ---------------------------------------------------------------------------
class TestPerformance:
    def test_100_windows(self):
        from engine import compute_visible_regions
        import random

        random.seed(12345)
        windows = [
            (
                i,
                random.randint(-100, 1800),
                random.randint(-100, 900),
                random.randint(50, 400),
                random.randint(50, 300),
                i,
            )
            for i in range(100)
        ]
        start = time.time()
        result = compute_visible_regions(1920, 1080, windows)
        elapsed = time.time() - start
        assert elapsed < 10, f"Too slow: {elapsed:.1f}s (limit 10s)"

        all_rects = []
        for rects in result.values():
            for r in rects:
                assert r[2] > 0 and r[3] > 0
                all_rects.append(r)
        total = sum(r[2] * r[3] for r in all_rects)
        assert total == 1920 * 1080

    def test_500_windows_4k(self):
        """500 windows at 4K resolution — requires efficient C acceleration."""
        from engine import compute_visible_regions
        import random

        random.seed(54321)
        windows = [
            (
                i,
                random.randint(-200, 3600),
                random.randint(-200, 1900),
                random.randint(50, 600),
                random.randint(50, 400),
                i,
            )
            for i in range(500)
        ]
        start = time.time()
        result = compute_visible_regions(3840, 2160, windows)
        elapsed = time.time() - start
        assert elapsed < 15, f"Too slow: {elapsed:.1f}s (limit 15s)"

        all_rects = [r for rects in result.values() for r in rects]
        for r in all_rects:
            assert r[2] > 0 and r[3] > 0
        total = sum(r[2] * r[3] for r in all_rects)
        assert total == 3840 * 2160

    def test_multiframe_pipeline(self):
        """50-frame sequence with 200 windows and incremental state changes."""
        from engine import compute_visible_regions, compute_dirty_regions
        import random

        random.seed(99999)

        windows = {
            i: (random.randint(0, 1800), random.randint(0, 900),
                random.randint(50, 300), random.randint(50, 200), i)
            for i in range(200)
        }

        start = time.time()
        prev_regions = {}
        for frame in range(50):
            win_list = [(wid, *vals) for wid, vals in windows.items()]
            regions = compute_visible_regions(1920, 1080, win_list)
            dirty = compute_dirty_regions(prev_regions, regions, 1920, 1080)

            total = sum(
                r[2] * r[3] for rects in regions.values() for r in rects
            )
            assert total == 1920 * 1080, (
                f"Frame {frame}: area {total} != {1920 * 1080}"
            )

            prev_regions = regions

            # Move 10 random windows each frame
            for _ in range(10):
                wid = random.randint(0, 199)
                x, y, w, h, z = windows[wid]
                windows[wid] = (
                    random.randint(0, 1800), random.randint(0, 900), w, h, z
                )

        elapsed = time.time() - start
        assert elapsed < 45, f"Multi-frame too slow: {elapsed:.1f}s (limit 45s)"
