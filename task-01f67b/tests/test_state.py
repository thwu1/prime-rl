"""
Tests for the terminal screen diff system.

Verifies:
1. diff_engine.py: correctness (roundtrip: apply diff to prev must equal curr)
   and efficiency (diff size vs full-redraw size).
2. tmux_validator.py: captures screen state from live tmux sessions and
   cross-validates diff results against VTParser.

"""

import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/opt/task_lib')

import pytest
from terminal import Screen, Cell, Attrs, VTParser, render_full
from diff_engine import compute_diff
from tmux_validator import validate_via_tmux


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def apply_diff(prev: Screen, diff_bytes: bytes) -> Screen:
    """Apply diff bytes to a clone of prev via the VTParser."""
    result = prev.clone()
    parser = VTParser(result)
    parser.process(diff_bytes)
    return result


def assert_diff_correct(prev: Screen, curr: Screen, label: str = ""):
    """Assert that compute_diff(prev, curr) produces a correct result."""
    diff = compute_diff(prev, curr)
    assert isinstance(diff, bytes), f"{label}: compute_diff must return bytes"
    result = apply_diff(prev, diff)

    # Check cursor
    assert result.cursor_row == curr.cursor_row, (
        f"{label}: cursor_row {result.cursor_row} != {curr.cursor_row}"
    )
    assert result.cursor_col == curr.cursor_col, (
        f"{label}: cursor_col {result.cursor_col} != {curr.cursor_col}"
    )

    # Check every cell
    for r in range(curr.rows):
        for c in range(curr.cols):
            rc = result.cells[r][c]
            cc = curr.cells[r][c]
            assert rc == cc, (
                f"{label}: cell({r},{c}) mismatch -- "
                f"got char={rc.char!r} attrs={rc.attrs}, "
                f"want char={cc.char!r} attrs={cc.attrs}"
            )

    return diff


# ---------------------------------------------------------------------------
# Correctness tests
# ---------------------------------------------------------------------------

class TestCorrectness:
    """Core correctness: diff applied to prev must reproduce curr exactly."""

    def test_identical_screens(self):
        prev = Screen(24, 80)
        curr = prev.clone()
        diff = assert_diff_correct(prev, curr, "identical")
        # Diff of identical screens should be very small (just cursor positioning at most)
        assert len(diff) < 50, f"Diff of identical screens too large: {len(diff)} bytes"

    def test_single_char_insert(self):
        """Insert one character into a blank screen."""
        prev = Screen(24, 80)
        curr = prev.clone()
        curr.set_cell(0, 0, 'A')
        curr.cursor_row = 0
        curr.cursor_col = 1
        assert_diff_correct(prev, curr, "single_char_insert")

    def test_single_char_overwrite(self):
        """Overwrite one character."""
        prev = Screen(24, 80)
        prev.set_cell(3, 10, 'X')
        prev.cursor_row = 3
        prev.cursor_col = 11
        curr = prev.clone()
        curr.set_cell(3, 10, 'Y')
        assert_diff_correct(prev, curr, "single_char_overwrite")

    def test_cursor_reposition_only(self):
        """Screen content unchanged; only cursor moves."""
        prev = Screen(24, 80)
        for c in range(5):
            prev.set_cell(0, c, chr(65 + c))
        prev.cursor_row = 0
        prev.cursor_col = 5

        curr = prev.clone()
        curr.cursor_row = 12
        curr.cursor_col = 40
        assert_diff_correct(prev, curr, "cursor_only")

    def test_consecutive_row_changes(self):
        """Multiple consecutive cells change in one row."""
        prev = Screen(24, 80)
        curr = prev.clone()
        msg = "Hello, World!"
        for i, ch in enumerate(msg):
            curr.set_cell(10, 20 + i, ch)
        curr.cursor_row = 10
        curr.cursor_col = 20 + len(msg)
        assert_diff_correct(prev, curr, "consecutive_row")

    def test_scattered_changes(self):
        """Non-adjacent cells change across multiple rows."""
        prev = Screen(24, 80)
        curr = prev.clone()
        positions = [(0, 0), (5, 20), (10, 40), (15, 60), (20, 70)]
        for idx, (r, c) in enumerate(positions):
            curr.set_cell(r, c, chr(65 + idx))
        curr.cursor_row = 20
        curr.cursor_col = 71
        assert_diff_correct(prev, curr, "scattered")

    def test_fg_color_change(self):
        """Same text, different foreground colours."""
        prev = Screen(24, 80)
        curr = prev.clone()
        for c in range(10):
            prev.set_cell(5, c, chr(65 + c), Attrs(fg=1))   # red
            curr.set_cell(5, c, chr(65 + c), Attrs(fg=2))   # green
        prev.cursor_row = curr.cursor_row = 5
        prev.cursor_col = curr.cursor_col = 10
        assert_diff_correct(prev, curr, "fg_color")

    def test_attr_transition_downgrade(self):
        """Bold+italic to just italic (must turn off bold without losing italic)."""
        prev = Screen(24, 80)
        curr = prev.clone()
        for c in range(8):
            prev.set_cell(7, c, chr(65 + c), Attrs(bold=True, italic=True, fg=1))
            curr.set_cell(7, c, chr(65 + c), Attrs(italic=True, fg=3))
        prev.cursor_row = curr.cursor_row = 7
        prev.cursor_col = curr.cursor_col = 8
        assert_diff_correct(prev, curr, "attr_downgrade")

    def test_extended_256_colors(self):
        """256-colour palette values."""
        prev = Screen(24, 80)
        curr = prev.clone()
        # A gradient of fg colours 16-31
        for c in range(16):
            curr.set_cell(4, c, '#', Attrs(fg=16 + c))
        # A gradient of bg colours 232-247
        for c in range(16):
            curr.set_cell(6, c, '.', Attrs(bg=232 + c))
        curr.cursor_row = 6
        curr.cursor_col = 16
        assert_diff_correct(prev, curr, "extended_256")

    def test_blank_cells_with_bg_color(self):
        """Blank (space) cells with non-default background differ from default blanks."""
        prev = Screen(24, 80)
        curr = prev.clone()
        # Row 10: spaces with red background
        for c in range(80):
            curr.set_cell(10, c, ' ', Attrs(bg=1))
        curr.cursor_row = 10
        curr.cursor_col = 0
        diff = assert_diff_correct(prev, curr, "blank_bg")

        # Verify each cell has bg=1
        result = apply_diff(prev, diff)
        for c in range(80):
            assert result.cells[10][c].attrs.bg == 1, (
                f"Cell (10,{c}) bg should be 1, got {result.cells[10][c].attrs.bg}"
            )

    def test_clear_row_end(self):
        """Text cleared from mid-row to end."""
        prev = Screen(24, 80)
        for c in range(80):
            prev.set_cell(10, c, chr(65 + c % 26))
        prev.cursor_row = 10
        prev.cursor_col = 0

        curr = prev.clone()
        for c in range(30, 80):
            curr.set_cell(10, c, ' ')  # clear to default blank
        curr.cursor_row = 10
        curr.cursor_col = 30
        assert_diff_correct(prev, curr, "clear_row_end")

    def test_multi_row_mixed(self):
        """Changes across several rows with mixed attribute patterns."""
        prev = Screen(24, 80)
        curr = prev.clone()

        # Row 0: title in inverse
        for c, ch in enumerate("== STATUS =="):
            curr.set_cell(0, c, ch, Attrs(inverse=True, bold=True))

        # Row 12: underlined text
        for c, ch in enumerate("important"):
            curr.set_cell(12, 35 + c, ch, Attrs(underline=True, fg=5))

        # Row 23: status bar
        bar = "Ln 1, Col 1  |  main.py"
        for c, ch in enumerate(bar):
            curr.set_cell(23, c, ch, Attrs(bold=True, bg=4, fg=7))

        curr.cursor_row = 23
        curr.cursor_col = len(bar)
        assert_diff_correct(prev, curr, "multi_row_mixed")

    def test_overwrite_with_different_attrs(self):
        """Overwrite existing coloured text with differently coloured text."""
        prev = Screen(24, 80)
        curr = prev.clone()
        text = "function"
        for c, ch in enumerate(text):
            prev.set_cell(3, c, ch, Attrs(fg=4, bold=True))        # blue bold
            curr.set_cell(3, c, ch, Attrs(fg=3, italic=True))      # yellow italic
        prev.cursor_row = curr.cursor_row = 3
        prev.cursor_col = curr.cursor_col = len(text)
        assert_diff_correct(prev, curr, "overwrite_attrs")

    def test_complex_editor_scene(self):
        """Simulate a code-editor screen with a single keystroke edit."""
        prev = Screen(24, 80)

        # Title bar (row 0)
        title = " main.py -- editor"
        for c in range(80):
            ch = title[c] if c < len(title) else ' '
            prev.set_cell(0, c, ch, Attrs(inverse=True))

        # Code area (rows 1-20): simple Python
        lines = [
            "def hello():",
            "    print('Hello')",
            "",
            "def goodbye():",
            "    print('Bye')",
        ]
        for r, line in enumerate(lines):
            for c, ch in enumerate(line):
                if ch in ('d', 'e', 'f') and c < 3:
                    attr = Attrs(fg=4, bold=True)     # keyword
                elif ch in ("'",):
                    attr = Attrs(fg=2)                # string
                else:
                    attr = Attrs()
                prev.set_cell(1 + r, c, ch, attr)

        # Status bar (row 22)
        status = "Ln 2, Col 18"
        for c, ch in enumerate(status):
            prev.set_cell(22, c, ch, Attrs(bg=4, fg=15))

        prev.cursor_row = 2
        prev.cursor_col = 18

        # Edit: add '!' inside the string on row 2
        curr = prev.clone()
        curr.set_cell(2, 16, '!', Attrs())
        curr.set_cell(2, 17, "'", Attrs(fg=2))
        curr.set_cell(2, 18, ")", Attrs())

        # Update status bar
        new_status = "Ln 2, Col 19"
        for c, ch in enumerate(new_status):
            curr.set_cell(22, c, ch, Attrs(bg=4, fg=15))

        curr.cursor_row = 2
        curr.cursor_col = 19
        assert_diff_correct(prev, curr, "editor_scene")


# ---------------------------------------------------------------------------
# Efficiency tests
# ---------------------------------------------------------------------------

class TestEfficiency:
    """Diff output must be meaningfully smaller than a full redraw."""

    def test_sparse_changes(self):
        """Five scattered cell changes on a text-filled screen."""
        prev = Screen(24, 80)
        for r in range(24):
            for c in range(80):
                prev.set_cell(r, c, chr(65 + (r + c) % 26))
        prev.cursor_row = 0
        prev.cursor_col = 0

        curr = prev.clone()
        curr.set_cell(0, 0, 'Z', Attrs(bold=True))
        curr.set_cell(5, 20, '!', Attrs(fg=1))
        curr.set_cell(10, 40, '@', Attrs(underline=True))
        curr.set_cell(15, 60, '#', Attrs(inverse=True))
        curr.set_cell(20, 70, '$', Attrs(fg=5, bold=True))
        curr.cursor_row = 20
        curr.cursor_col = 71

        diff = assert_diff_correct(prev, curr, "eff_sparse")
        full = render_full(curr)
        ratio = len(diff) / len(full)
        assert ratio < 0.10, (
            f"Sparse diff too large: {len(diff)} bytes = {ratio:.1%} of "
            f"full redraw ({len(full)} bytes); must be < 10%"
        )

    def test_status_line_update(self):
        """Only the last row (status bar) changes -- common terminal pattern."""
        prev = Screen(24, 80)
        for r in range(24):
            for c in range(80):
                prev.set_cell(r, c, chr(65 + (r + c) % 26))
        prev.cursor_row = 23
        prev.cursor_col = 0

        curr = prev.clone()
        bar = "Ready | Ln 42, Col 7 | UTF-8 | Python"
        for c in range(80):
            ch = bar[c] if c < len(bar) else ' '
            curr.set_cell(23, c, ch, Attrs(bold=True, fg=15, bg=4))
        curr.cursor_row = 23
        curr.cursor_col = 0

        diff = assert_diff_correct(prev, curr, "eff_status")
        full = render_full(curr)
        ratio = len(diff) / len(full)
        assert ratio < 0.25, (
            f"Status-line diff too large: {len(diff)} bytes = {ratio:.1%} of "
            f"full redraw ({len(full)} bytes); must be < 25%"
        )

    def test_half_screen_change(self):
        """Bottom half of screen changes with per-row colouring."""
        prev = Screen(24, 80)
        for r in range(24):
            for c in range(80):
                prev.set_cell(r, c, chr(65 + (r * 3 + c) % 26))
        prev.cursor_row = 12
        prev.cursor_col = 0

        curr = prev.clone()
        for r in range(12, 24):
            row_fg = r % 8  # colour changes per-row, not per-cell
            for c in range(80):
                curr.set_cell(r, c, chr(97 + (r * 7 + c) % 26),
                              Attrs(fg=row_fg))
        curr.cursor_row = 23
        curr.cursor_col = 79

        diff = assert_diff_correct(prev, curr, "eff_half")
        full = render_full(curr)
        ratio = len(diff) / len(full)
        assert ratio < 0.70, (
            f"Half-screen diff too large: {len(diff)} bytes = {ratio:.1%} of "
            f"full redraw ({len(full)} bytes); must be < 70%"
        )


# ---------------------------------------------------------------------------
# tmux validator tests
# ---------------------------------------------------------------------------

class TestTmuxValidator:
    """Validate that tmux_validator.py correctly captures screen state."""

    def test_text_capture(self):
        """validate_via_tmux captures basic text content from a tmux pane."""
        prev = Screen(24, 80)
        msg = "Terminal test content"
        for c, ch in enumerate(msg):
            prev.set_cell(2, c, ch)
        prev.cursor_row = 2
        prev.cursor_col = len(msg)

        result = validate_via_tmux(prev, b'')
        for c, ch in enumerate(msg):
            assert result.cells[2][c].char == ch, (
                f"tmux capture: cell (2,{c}) expected {ch!r}, "
                f"got {result.cells[2][c].char!r}"
            )

    def test_colored_text_capture(self):
        """validate_via_tmux captures text with color and bold attributes."""
        prev = Screen(24, 80)
        msg = "Color"
        for c, ch in enumerate(msg):
            prev.set_cell(1, c, ch, Attrs(fg=1, bold=True))
        prev.cursor_row = 1
        prev.cursor_col = len(msg)

        result = validate_via_tmux(prev, b'')
        for c, ch in enumerate(msg):
            assert result.cells[1][c].char == ch, (
                f"tmux color capture: cell (1,{c}) char expected {ch!r}, "
                f"got {result.cells[1][c].char!r}"
            )
            assert result.cells[1][c].attrs.fg == 1, (
                f"tmux color capture: cell (1,{c}) fg expected 1, "
                f"got {result.cells[1][c].attrs.fg}"
            )
            assert result.cells[1][c].attrs.bold is True, (
                f"tmux color capture: cell (1,{c}) bold expected True, "
                f"got {result.cells[1][c].attrs.bold}"
            )

    def test_cursor_position(self):
        """validate_via_tmux captures cursor position from tmux pane."""
        prev = Screen(24, 80)
        prev.set_cell(10, 30, 'X')
        prev.cursor_row = 10
        prev.cursor_col = 31

        result = validate_via_tmux(prev, b'')
        assert result.cursor_row == 10, (
            f"tmux cursor_row: expected 10, got {result.cursor_row}"
        )
        assert result.cursor_col == 31, (
            f"tmux cursor_col: expected 31, got {result.cursor_col}"
        )

    def test_diff_cross_validation(self):
        """Diff applied via tmux produces same characters as via VTParser."""
        prev = Screen(24, 80)
        for c in range(30):
            prev.set_cell(0, c, chr(65 + c % 26))
        prev.cursor_row = 0
        prev.cursor_col = 0

        curr = prev.clone()
        curr.set_cell(0, 5, '!')
        curr.set_cell(0, 15, '@')
        curr.set_cell(10, 40, '#', Attrs(bold=True))
        curr.cursor_row = 10
        curr.cursor_col = 41

        diff = compute_diff(prev, curr)

        # VTParser result
        vt_result = apply_diff(prev, diff)

        # tmux result
        tmux_result = validate_via_tmux(prev, diff)

        # Cross-validate character content at changed positions
        check_positions = [(0, 5), (0, 15), (10, 40)]
        for r, c in check_positions:
            assert vt_result.cells[r][c].char == tmux_result.cells[r][c].char, (
                f"Cross-validation at ({r},{c}): "
                f"VTParser={vt_result.cells[r][c].char!r}, "
                f"tmux={tmux_result.cells[r][c].char!r}"
            )

        # Cross-validate unchanged positions in first row
        for c in [0, 1, 2, 3, 4, 6, 7, 8]:
            assert vt_result.cells[0][c].char == tmux_result.cells[0][c].char, (
                f"Cross-validation at (0,{c}): "
                f"VTParser={vt_result.cells[0][c].char!r}, "
                f"tmux={tmux_result.cells[0][c].char!r}"
            )
