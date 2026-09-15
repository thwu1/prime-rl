
import os
import subprocess
import tempfile
import pytest


# ═══════════════════════════════════════════════════════════════════
# Minimal VT100 state machine for verifying rasterizer output
# ═══════════════════════════════════════════════════════════════════

class VTerm:
    """Parse ANSI escape sequences and build a virtual terminal grid."""

    def __init__(self, rows, cols):
        self.rows = rows
        self.cols = cols
        # (char, fg_r, fg_g, fg_b, bg_r, bg_g, bg_b, style_mask)
        self.grid = [
            [(" ", -1, -1, -1, -1, -1, -1, 0) for _ in range(cols)]
            for _ in range(rows)
        ]
        self.cy = 0
        self.cx = 0
        self.fg = (-1, -1, -1)
        self.bg = (-1, -1, -1)
        self.style = 0

    def feed(self, data):
        i = 0
        while i < len(data):
            if data[i] == "\x1b" and i + 1 < len(data) and data[i + 1] == "[":
                i += 2
                params, i = self._read_csi(data, i)
                if i < len(data):
                    cmd = data[i]
                    i += 1
                    self._dispatch(params, cmd)
            elif 0x20 <= ord(data[i]) <= 0x7E:
                if 0 <= self.cy < self.rows and 0 <= self.cx < self.cols:
                    self.grid[self.cy][self.cx] = (
                        data[i], *self.fg, *self.bg, self.style
                    )
                self.cx += 1
                i += 1
            else:
                i += 1

    def _read_csi(self, data, i):
        parts = []
        cur = ""
        while i < len(data) and data[i] not in "ABCDHJKfhlmnsu":
            if data[i] == ";":
                parts.append(cur)
                cur = ""
            else:
                cur += data[i]
            i += 1
        parts.append(cur)
        return parts, i

    def _dispatch(self, params, cmd):
        if cmd == "H":
            r = int(params[0]) if params[0] else 1
            c = int(params[1]) if len(params) > 1 and params[1] else 1
            self.cy = r - 1
            self.cx = c - 1
        elif cmd == "m":
            self._sgr(params)

    def _sgr(self, params):
        if not params or params == [""]:
            params = ["0"]
        i = 0
        while i < len(params):
            p = int(params[i]) if params[i] else 0
            if p == 0:
                self.fg = (-1, -1, -1)
                self.bg = (-1, -1, -1)
                self.style = 0
            elif p == 1:
                self.style |= 0x0002
            elif p == 3:
                self.style |= 0x0010
            elif p == 4:
                self.style |= 0x0008
            elif p == 9:
                self.style |= 0x0001
            elif p == 22:
                self.style &= ~0x0002
            elif p == 23:
                self.style &= ~0x0010
            elif p == 24:
                self.style &= ~0x000C
            elif p == 29:
                self.style &= ~0x0001
            elif p == 38 and i + 4 < len(params):
                if int(params[i + 1]) == 2:
                    self.fg = (
                        int(params[i + 2]),
                        int(params[i + 3]),
                        int(params[i + 4]),
                    )
                    i += 4
            elif p == 39:
                self.fg = (-1, -1, -1)
            elif p == 48 and i + 4 < len(params):
                if int(params[i + 1]) == 2:
                    self.bg = (
                        int(params[i + 2]),
                        int(params[i + 3]),
                        int(params[i + 4]),
                    )
                    i += 4
            elif p == 49:
                self.bg = (-1, -1, -1)
            i += 1

    def cell(self, y, x):
        return self.grid[y][x]


# ═══════════════════════════════════════════════════════════════════
# Test helpers
# ═══════════════════════════════════════════════════════════════════

def _tmpscene(text):
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".scene", delete=False, dir="/tmp"
    )
    f.write(text)
    f.close()
    return f.name


def _grid_dims(text):
    for line in text.strip().splitlines():
        if line.startswith("GRID "):
            p = line.split()
            return int(p[1]), int(p[2])
    raise ValueError("No GRID line")


def _parse_text(stdout):
    cells = {}
    for line in stdout.strip().splitlines():
        parts = line.split()
        if len(parts) != 10:
            continue
        y, x = int(parts[0]), int(parts[1])
        egc = chr(int(parts[2]))
        fg = (int(parts[3]), int(parts[4]), int(parts[5]))
        bg = (int(parts[6]), int(parts[7]), int(parts[8]))
        sty = int(parts[9], 16)
        cells[(y, x)] = (egc, *fg, *bg, sty)
    return cells


def run_text(scene):
    p = _tmpscene(scene)
    try:
        r = subprocess.run(
            ["/app/compositor", p], capture_output=True, text=True, timeout=10
        )
        assert r.returncode == 0, f"text mode failed: {r.stderr}"
        return _parse_text(r.stdout)
    finally:
        os.unlink(p)


def run_raster(scene):
    p = _tmpscene(scene)
    try:
        r = subprocess.run(
            ["/app/compositor", "-r", p],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0, f"raster mode failed: {r.stderr}"
        return r.stdout
    finally:
        os.unlink(p)


def run_diff(scene1, scene2):
    p1 = _tmpscene(scene1)
    p2 = _tmpscene(scene2)
    try:
        r = subprocess.run(
            ["/app/compositor", "-d", p1, p2],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0, f"diff mode failed: {r.stderr}"
        return r.stdout
    finally:
        os.unlink(p1)
        os.unlink(p2)


def verify_raster(scene, raster_out):
    """Feed raster output through VTerm, compare cell-by-cell to expected."""
    rows, cols = _grid_dims(scene)
    expected = run_text(scene)
    vt = VTerm(rows, cols)
    vt.feed(raster_out)
    for y in range(rows):
        for x in range(cols):
            act = vt.cell(y, x)
            exp = expected.get((y, x))
            assert exp is not None, f"Missing expected cell ({y},{x})"
            assert act == exp, (
                f"Cell ({y},{x}): expected {exp}, got {act}"
            )


def extract_data_chars(output):
    """Extract only the characters written to cells (skip escape seqs)."""
    chars = []
    i = 0
    while i < len(output):
        if output[i] == "\x1b" and i + 1 < len(output) and output[i + 1] == "[":
            i += 2
            while i < len(output) and output[i] not in "ABCDHJKfhlmnsu":
                i += 1
            if i < len(output):
                i += 1
        elif 0x20 <= ord(output[i]) <= 0x7E:
            chars.append(output[i])
            i += 1
        else:
            i += 1
    return chars


# ═══════════════════════════════════════════════════════════════════
# Build
# ═══════════════════════════════════════════════════════════════════


class TestBuild:
    def test_binary_exists(self):
        assert os.path.isfile("/app/compositor")

    def test_modes_run(self):
        r = subprocess.run(
            ["/app/compositor"], capture_output=True, text=True
        )
        assert r.returncode != 0  # usage error, but it runs


# ═══════════════════════════════════════════════════════════════════
# Full render correctness
# ═══════════════════════════════════════════════════════════════════


class TestFullRenderSingleCell:
    """1x1 grid, single opaque cell with explicit fg/bg."""
    SCENE = (
        "GRID 1 1\n"
        "PLANE 0 0 1 1\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 A 0000 40ff00004000ff00\n"
        "ENDPLANE\n"
    )

    def test_correctness(self):
        raw = run_raster(self.SCENE)
        assert len(raw) > 0, "Rasterizer produced no output"
        verify_raster(self.SCENE, raw)


class TestFullRenderRow:
    """1x3 row: different colors per cell, mixed styles."""
    SCENE = (
        "GRID 1 3\n"
        "PLANE 0 0 1 3\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 X 0002 40c8c8c840323232\n"
        "CELL 0 1 Y 0010 4064c83200000000\n"
        "CELL 0 2 Z 0000 0000000000000000\n"
        "ENDPLANE\n"
    )

    def test_correctness(self):
        raw = run_raster(self.SCENE)
        verify_raster(self.SCENE, raw)


class TestFullRenderGrid:
    """2x2 grid, distinct colors and styles per cell."""
    SCENE = (
        "GRID 2 2\n"
        "PLANE 0 0 2 2\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 A 0002 40ff000040000000\n"
        "CELL 0 1 B 0010 400000ff40ffffff\n"
        "CELL 1 0 C 0001 4000ff0040808080\n"
        "CELL 1 1 D 0000 40ffffff40000000\n"
        "ENDPLANE\n"
    )

    def test_correctness(self):
        raw = run_raster(self.SCENE)
        verify_raster(self.SCENE, raw)


class TestFullRenderDefaultColors:
    """Cells with default fg and bg."""
    SCENE = (
        "GRID 1 2\n"
        "PLANE 0 0 1 2\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 P 0000 0000000000000000\n"
        "CELL 0 1 Q 0000 40ff000000000000\n"
        "ENDPLANE\n"
    )

    def test_correctness(self):
        raw = run_raster(self.SCENE)
        verify_raster(self.SCENE, raw)


class TestFullRenderAllStyles:
    """One cell per style flag: bold, italic, underline, struck."""
    SCENE = (
        "GRID 1 4\n"
        "PLANE 0 0 1 4\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 B 0002 40ff000040000000\n"
        "CELL 0 1 I 0010 400000ff40000000\n"
        "CELL 0 2 U 0008 4000ff0040000000\n"
        "CELL 0 3 S 0001 40ffffff40000000\n"
        "ENDPLANE\n"
    )

    def test_correctness(self):
        raw = run_raster(self.SCENE)
        verify_raster(self.SCENE, raw)


class TestFullRenderCombinedStyles:
    """Cell with bold+italic combined (style 0x0012)."""
    SCENE = (
        "GRID 1 1\n"
        "PLANE 0 0 1 1\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 M 0012 40ff808040000000\n"
        "ENDPLANE\n"
    )

    def test_correctness(self):
        raw = run_raster(self.SCENE)
        verify_raster(self.SCENE, raw)


class TestFullRenderMultiPlane:
    """Multi-plane scene with blending, then rasterize."""
    SCENE = (
        "GRID 1 2\n"
        "PLANE 0 0 1 2\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 T 0000 50c8640040000000\n"
        "CELL 0 1 V 0000 40ff000040ffffff\n"
        "ENDPLANE\n"
        "PLANE 0 0 1 2\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 U 0000 400064c840ffffff\n"
        "CELL 0 1 W 0000 400000ff40000000\n"
        "ENDPLANE\n"
    )

    def test_correctness(self):
        raw = run_raster(self.SCENE)
        verify_raster(self.SCENE, raw)


# ═══════════════════════════════════════════════════════════════════
# Full render format and optimization
# ═══════════════════════════════════════════════════════════════════


class TestFullRenderReset:
    """Output must start and end with ESC[0m."""
    SCENE = (
        "GRID 1 1\n"
        "PLANE 0 0 1 1\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 R 0000 40ff000040000000\n"
        "ENDPLANE\n"
    )

    def test_starts_with_reset(self):
        raw = run_raster(self.SCENE)
        assert raw.startswith("\x1b[0m"), "Output must start with ESC[0m"

    def test_ends_with_reset(self):
        raw = run_raster(self.SCENE)
        assert raw.endswith("\x1b[0m"), "Output must end with ESC[0m"


class TestFullRenderTrailingTrim:
    """Trailing blank cells at end of row must be trimmed."""
    SCENE = (
        "GRID 1 6\n"
        "PLANE 0 0 1 2\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 A 0000 40ff000040000000\n"
        "CELL 0 1 B 0000 400000ff40000000\n"
        "ENDPLANE\n"
    )

    def test_correctness(self):
        raw = run_raster(self.SCENE)
        verify_raster(self.SCENE, raw)

    def test_no_trailing_spaces(self):
        raw = run_raster(self.SCENE)
        data = extract_data_chars(raw)
        assert len(data) <= 2, (
            f"Expected at most 2 data chars (A,B), got {len(data)}: {data}"
        )


class TestSGREfficiency:
    """Consecutive identical-attribute cells: no redundant SGR."""
    SCENE = (
        "GRID 1 4\n"
        "PLANE 0 0 1 4\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 W 0002 40ff000040000000\n"
        "CELL 0 1 X 0002 40ff000040000000\n"
        "CELL 0 2 Y 0002 40ff000040000000\n"
        "CELL 0 3 Z 0002 40ff000040000000\n"
        "ENDPLANE\n"
    )

    def test_correctness(self):
        raw = run_raster(self.SCENE)
        verify_raster(self.SCENE, raw)

    def test_byte_efficiency(self):
        raw = run_raster(self.SCENE)
        # With state tracking: ~50 bytes (1 SGR + 4 chars + CUP + resets)
        # Without: ~120+ bytes (4 identical SGR sequences)
        assert len(raw) < 100, (
            f"Output too large ({len(raw)} bytes); "
            "SGR state tracking likely missing"
        )


# ═══════════════════════════════════════════════════════════════════
# Diff correctness
# ═══════════════════════════════════════════════════════════════════


class TestDiffSingleChange:
    """One cell changes between frames."""
    SCENE1 = (
        "GRID 2 2\n"
        "PLANE 0 0 2 2\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 A 0000 40ff000040000000\n"
        "CELL 0 1 A 0000 40ff000040000000\n"
        "CELL 1 0 A 0000 40ff000040000000\n"
        "CELL 1 1 A 0000 40ff000040000000\n"
        "ENDPLANE\n"
    )
    SCENE2 = (
        "GRID 2 2\n"
        "PLANE 0 0 2 2\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 B 0002 4000ff0040ffffff\n"
        "CELL 0 1 A 0000 40ff000040000000\n"
        "CELL 1 0 A 0000 40ff000040000000\n"
        "CELL 1 1 A 0000 40ff000040000000\n"
        "ENDPLANE\n"
    )

    def test_visual_correctness(self):
        rows, cols = _grid_dims(self.SCENE2)
        full1 = run_raster(self.SCENE1)
        vt = VTerm(rows, cols)
        vt.feed(full1)
        diff = run_diff(self.SCENE1, self.SCENE2)
        vt.feed(diff)
        expected = run_text(self.SCENE2)
        for y in range(rows):
            for x in range(cols):
                assert vt.cell(y, x) == expected[(y, x)], (
                    f"Cell ({y},{x}): expected {expected[(y,x)]}, "
                    f"got {vt.cell(y, x)}"
                )


class TestDiffMultiChange:
    """Three cells change at scattered positions."""
    SCENE1 = (
        "GRID 3 3\n"
        "PLANE 0 0 3 3\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 A 0000 40ff000040000000\n"
        "CELL 0 1 B 0000 40ff000040000000\n"
        "CELL 0 2 C 0000 40ff000040000000\n"
        "CELL 1 0 D 0000 40ff000040000000\n"
        "CELL 1 1 E 0000 40ff000040000000\n"
        "CELL 1 2 F 0000 40ff000040000000\n"
        "CELL 2 0 G 0000 40ff000040000000\n"
        "CELL 2 1 H 0000 40ff000040000000\n"
        "CELL 2 2 I 0000 40ff000040000000\n"
        "ENDPLANE\n"
    )
    SCENE2 = (
        "GRID 3 3\n"
        "PLANE 0 0 3 3\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 X 0002 4000ff0040808080\n"
        "CELL 0 1 B 0000 40ff000040000000\n"
        "CELL 0 2 C 0000 40ff000040000000\n"
        "CELL 1 0 D 0000 40ff000040000000\n"
        "CELL 1 1 Y 0010 400000ff40ffffff\n"
        "CELL 1 2 F 0000 40ff000040000000\n"
        "CELL 2 0 G 0000 40ff000040000000\n"
        "CELL 2 1 H 0000 40ff000040000000\n"
        "CELL 2 2 Z 0001 40ffffff40323232\n"
        "ENDPLANE\n"
    )

    def test_visual_correctness(self):
        rows, cols = _grid_dims(self.SCENE2)
        full1 = run_raster(self.SCENE1)
        vt = VTerm(rows, cols)
        vt.feed(full1)
        diff = run_diff(self.SCENE1, self.SCENE2)
        vt.feed(diff)
        expected = run_text(self.SCENE2)
        for y in range(rows):
            for x in range(cols):
                assert vt.cell(y, x) == expected[(y, x)], (
                    f"Cell ({y},{x}): expected {expected[(y,x)]}, "
                    f"got {vt.cell(y, x)}"
                )


class TestDiffStyleTransition:
    """Cells transition between different style combinations."""
    SCENE1 = (
        "GRID 1 3\n"
        "PLANE 0 0 1 3\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 A 0012 40ff000040000000\n"
        "CELL 0 1 B 0001 400000ff40000000\n"
        "CELL 0 2 C 0008 4000ff0040000000\n"
        "ENDPLANE\n"
    )
    SCENE2 = (
        "GRID 1 3\n"
        "PLANE 0 0 1 3\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 A 0001 40ff000040000000\n"
        "CELL 0 1 B 0012 400000ff40000000\n"
        "CELL 0 2 C 0002 4000ff0040000000\n"
        "ENDPLANE\n"
    )

    def test_visual_correctness(self):
        rows, cols = _grid_dims(self.SCENE2)
        full1 = run_raster(self.SCENE1)
        vt = VTerm(rows, cols)
        vt.feed(full1)
        diff = run_diff(self.SCENE1, self.SCENE2)
        vt.feed(diff)
        expected = run_text(self.SCENE2)
        for y in range(rows):
            for x in range(cols):
                assert vt.cell(y, x) == expected[(y, x)], (
                    f"Cell ({y},{x}): expected {expected[(y,x)]}, "
                    f"got {vt.cell(y, x)}"
                )


# ═══════════════════════════════════════════════════════════════════
# Diff optimization
# ═══════════════════════════════════════════════════════════════════


class TestDiffIdentical:
    """Identical frames should produce minimal diff output."""
    SCENE = (
        "GRID 2 2\n"
        "PLANE 0 0 2 2\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 A 0000 40ff000040000000\n"
        "CELL 0 1 B 0000 400000ff40000000\n"
        "CELL 1 0 C 0000 4000ff0040000000\n"
        "CELL 1 1 D 0000 40ffffff40000000\n"
        "ENDPLANE\n"
    )

    def test_minimal_output(self):
        diff = run_diff(self.SCENE, self.SCENE)
        # Only the two resets: ESC[0m ESC[0m = 8 bytes
        assert len(diff) <= 12, (
            f"Identical frames should produce <= 12 bytes, got {len(diff)}"
        )

    def test_no_data_chars(self):
        diff = run_diff(self.SCENE, self.SCENE)
        data = extract_data_chars(diff)
        assert len(data) == 0, (
            f"Identical frames should emit no data chars, got {data}"
        )


class TestDiffByteEfficiency:
    """Diff of 1-cell change in large grid should be small."""
    SCENE1 = (
        "GRID 4 4\n"
        "PLANE 0 0 4 4\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 A 0000 40ff000040000000\n"
        "CELL 0 1 B 0002 400000ff40000000\n"
        "CELL 0 2 C 0010 4000ff0040000000\n"
        "CELL 0 3 D 0001 40ffffff40000000\n"
        "CELL 1 0 E 0000 40808080400000ff\n"
        "CELL 1 1 F 0002 40c8000040000000\n"
        "CELL 1 2 G 0010 400064c840000000\n"
        "CELL 1 3 H 0001 4000c86440000000\n"
        "CELL 2 0 I 0000 40ff808040808080\n"
        "CELL 2 1 J 0002 4080ff8040808080\n"
        "CELL 2 2 K 0010 408080ff40808080\n"
        "CELL 2 3 L 0001 40ff008040808080\n"
        "CELL 3 0 M 0000 4080ff0040404040\n"
        "CELL 3 1 N 0002 400080ff40404040\n"
        "CELL 3 2 O 0010 40ff800040404040\n"
        "CELL 3 3 P 0001 4000ff8040404040\n"
        "ENDPLANE\n"
    )
    SCENE2 = (
        "GRID 4 4\n"
        "PLANE 0 0 4 4\n"
        "BASE _ 0000 0000000000000000\n"
        "CELL 0 0 A 0000 40ff000040000000\n"
        "CELL 0 1 B 0002 400000ff40000000\n"
        "CELL 0 2 C 0010 4000ff0040000000\n"
        "CELL 0 3 D 0001 40ffffff40000000\n"
        "CELL 1 0 E 0000 40808080400000ff\n"
        "CELL 1 1 F 0002 40c8000040000000\n"
        "CELL 1 2 G 0010 400064c840000000\n"
        "CELL 1 3 H 0001 4000c86440000000\n"
        "CELL 2 0 I 0000 40ff808040808080\n"
        "CELL 2 1 J 0002 4080ff8040808080\n"
        "CELL 2 2 Q 0000 40c8c8c840323232\n"
        "CELL 2 3 L 0001 40ff008040808080\n"
        "CELL 3 0 M 0000 4080ff0040404040\n"
        "CELL 3 1 N 0002 400080ff40404040\n"
        "CELL 3 2 O 0010 40ff800040404040\n"
        "CELL 3 3 P 0001 4000ff8040404040\n"
        "ENDPLANE\n"
    )

    def test_diff_smaller_than_full(self):
        full2 = run_raster(self.SCENE2)
        diff = run_diff(self.SCENE1, self.SCENE2)
        assert len(diff) < len(full2) * 0.5, (
            f"Diff ({len(diff)} bytes) should be < 50% of "
            f"full ({len(full2)} bytes)"
        )

    def test_diff_correctness(self):
        rows, cols = _grid_dims(self.SCENE2)
        full1 = run_raster(self.SCENE1)
        vt = VTerm(rows, cols)
        vt.feed(full1)
        diff = run_diff(self.SCENE1, self.SCENE2)
        vt.feed(diff)
        expected = run_text(self.SCENE2)
        for y in range(rows):
            for x in range(cols):
                assert vt.cell(y, x) == expected[(y, x)], (
                    f"Cell ({y},{x}): expected {expected[(y,x)]}, "
                    f"got {vt.cell(y, x)}"
                )
