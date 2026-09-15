
"""
Tests for VT/ANSI terminal state machine implementation.

Verifies correct handling of: cursor movement (CUP, CUU, CUD, CUF, CUB,
CNL, CPL, CHA, VPA, HVP), SGR attributes and colors (standard 16, 256-color
palette, 24-bit RGB, blink, reverse), erase operations (EL, ED, ECH),
insert/delete characters (ICH, DCH), insert/delete lines (IL, DL),
scroll operations (SU, SD, DECSTBM), line wrapping with pending-wrap
semantics, partial escape sequences split across chunks, cursor save/restore,
ESC sequences (index, next line, reverse index), and graceful handling
of OSC and DEC private modes.

Also tests shared library via Python ctypes bindings (bindings.py) and
cross-validates against tmux as a reference terminal (tmux_oracle.sh).
"""

import subprocess
import json
import os
import sys
import tempfile
import pytest

BINARY = '/app/vtterm'

# Attribute flags — must match terminal.h
ATTR_BOLD          = 1 << 0
ATTR_DIM           = 1 << 1
ATTR_ITALIC        = 1 << 2
ATTR_UNDERLINE     = 1 << 3
ATTR_BLINK         = 1 << 4
ATTR_REVERSE       = 1 << 5
ATTR_INVISIBLE     = 1 << 6
ATTR_STRIKETHROUGH = 1 << 7

DEFAULT_FG = (170, 170, 170)
DEFAULT_BG = (0, 0, 0)


@pytest.fixture(autouse=True, scope='session')
def build_binary():
    """Build the terminal binary and shared library once before all tests."""
    result = subprocess.run(
        ['make', '-C', '/app'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        pytest.fail(f"Build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")


def run_term(input_bytes, width=80, height=24, chunk_size=0):
    """Run vtterm with given input and return parsed JSON state."""
    args = [BINARY, str(width), str(height)]
    if chunk_size > 0:
        args.append(str(chunk_size))
    result = subprocess.run(args, input=input_bytes, capture_output=True)
    assert result.returncode == 0, \
        f"vtterm failed (rc={result.returncode}): {result.stderr.decode(errors='replace')}"
    return json.loads(result.stdout.decode())


def cell_cp(state, x, y):
    """Get codepoint of cell at (x, y)."""
    return state['cells'][y][x]['cp']


def cell_fg(state, x, y):
    """Get foreground RGB tuple of cell at (x, y)."""
    c = state['cells'][y][x]
    return tuple(c['fg'])


def cell_bg(state, x, y):
    """Get background RGB tuple of cell at (x, y)."""
    c = state['cells'][y][x]
    return tuple(c['bg'])


def cell_at(state, x, y):
    """Get attribute flags of cell at (x, y)."""
    return state['cells'][y][x]['at']


def cursor(state):
    """Get cursor position as (x, y) tuple."""
    return (state['cursor']['x'], state['cursor']['y'])


# ========================================================================
# Basic text and control characters
# ========================================================================

class TestBasicText:
    def test_simple_ascii(self):
        state = run_term(b"Hello", 20, 5)
        assert cell_cp(state, 0, 0) == ord('H')
        assert cell_cp(state, 1, 0) == ord('e')
        assert cell_cp(state, 2, 0) == ord('l')
        assert cell_cp(state, 3, 0) == ord('l')
        assert cell_cp(state, 4, 0) == ord('o')
        assert cell_cp(state, 5, 0) == 0  # unwritten
        assert cursor(state) == (5, 0)

    def test_empty_input(self):
        state = run_term(b"", 10, 5)
        assert cursor(state) == (0, 0)
        assert len(state['cells']) == 5
        assert len(state['cells'][0]) == 10
        for y in range(5):
            for x in range(10):
                assert cell_cp(state, x, y) == 0
                assert cell_fg(state, x, y) == DEFAULT_FG
                assert cell_bg(state, x, y) == DEFAULT_BG
                assert cell_at(state, x, y) == 0

    def test_newline(self):
        """LF moves cursor down without changing column (no implicit CR)."""
        state = run_term(b"AB\nCD", 20, 5)
        assert cell_cp(state, 0, 0) == ord('A')
        assert cell_cp(state, 1, 0) == ord('B')
        assert cell_cp(state, 2, 1) == ord('C')
        assert cell_cp(state, 3, 1) == ord('D')
        assert cursor(state) == (4, 1)

    def test_carriage_return(self):
        state = run_term(b"ABC\rDE", 20, 5)
        assert cell_cp(state, 0, 0) == ord('D')
        assert cell_cp(state, 1, 0) == ord('E')
        assert cell_cp(state, 2, 0) == ord('C')
        assert cursor(state) == (2, 0)

    def test_crlf(self):
        state = run_term(b"AB\r\nCD", 20, 5)
        assert cell_cp(state, 0, 0) == ord('A')
        assert cell_cp(state, 1, 0) == ord('B')
        assert cell_cp(state, 0, 1) == ord('C')
        assert cell_cp(state, 1, 1) == ord('D')

    def test_tab(self):
        state = run_term(b"A\tB", 20, 5)
        assert cell_cp(state, 0, 0) == ord('A')
        assert cell_cp(state, 8, 0) == ord('B')
        assert cursor(state) == (9, 0)

    def test_backspace(self):
        state = run_term(b"ABC\bX", 20, 5)
        assert cell_cp(state, 0, 0) == ord('A')
        assert cell_cp(state, 1, 0) == ord('B')
        assert cell_cp(state, 2, 0) == ord('X')  # overwrites C
        assert cursor(state) == (3, 0)


# ========================================================================
# Cursor positioning and movement
# ========================================================================

class TestCursorMovement:
    def test_cup_explicit(self):
        """CSI row;col H positions cursor (1-indexed)."""
        state = run_term(b"\x1b[3;5HX", 20, 5)
        assert cell_cp(state, 4, 2) == ord('X')
        assert cursor(state) == (5, 2)

    def test_cup_default(self):
        """CSI H with no params goes to (0,0)."""
        state = run_term(b"ABC\x1b[HX", 20, 5)
        assert cell_cp(state, 0, 0) == ord('X')  # overwrites A
        assert cursor(state) == (1, 0)

    def test_cursor_up(self):
        state = run_term(b"\x1b[3;1HABCDE\x1b[2AX", 20, 5)
        assert cell_cp(state, 5, 0) == ord('X')
        assert cursor(state) == (6, 0)

    def test_cursor_down(self):
        state = run_term(b"AB\x1b[2BX", 20, 5)
        assert cell_cp(state, 2, 2) == ord('X')
        assert cursor(state) == (3, 2)

    def test_cursor_forward(self):
        state = run_term(b"A\x1b[3CX", 20, 5)
        assert cell_cp(state, 4, 0) == ord('X')
        assert cursor(state) == (5, 0)

    def test_cursor_back(self):
        state = run_term(b"ABCDE\x1b[2DX", 20, 5)
        assert cell_cp(state, 3, 0) == ord('X')
        assert cursor(state) == (4, 0)

    def test_cursor_bounds_up(self):
        """Cursor up can't go above row 0."""
        state = run_term(b"\x1b[99AX", 20, 5)
        assert cell_cp(state, 0, 0) == ord('X')
        assert cursor(state) == (1, 0)

    def test_cursor_bounds_left(self):
        """Cursor back can't go before column 0."""
        state = run_term(b"\x1b[99DX", 20, 5)
        assert cell_cp(state, 0, 0) == ord('X')
        assert cursor(state) == (1, 0)

    def test_cha(self):
        """CSI n G - Cursor Horizontal Absolute (1-indexed)."""
        state = run_term(b"ABCDE\x1b[3GX", 20, 5)
        assert cell_cp(state, 2, 0) == ord('X')

    def test_cursor_next_line(self):
        """CSI n E - Cursor Next Line: move to col 0 of line N below."""
        state = run_term(b"\x1b[3;5HABCDE\x1b[2EX", 20, 5)
        # Cursor was at (9, 2) after writing ABCDE (started at col 4, row 2)
        # CSI 2E moves 2 lines down and to column 0 => (0, 4)
        assert cursor(state) == (1, 4)
        assert cell_cp(state, 0, 4) == ord('X')

    def test_cursor_prev_line(self):
        """CSI n F - Cursor Previous Line: move to col 0 of line N above."""
        state = run_term(b"\x1b[4;5H\x1b[2FX", 20, 5)
        # Cursor at (4, 3), CSI 2F moves 2 up and to col 0 => (0, 1)
        assert cursor(state) == (1, 1)
        assert cell_cp(state, 0, 1) == ord('X')

    def test_hvp(self):
        """CSI row;col f - Horizontal and Vertical Position (same as CUP)."""
        state = run_term(b"\x1b[3;5fX", 20, 5)
        assert cell_cp(state, 4, 2) == ord('X')
        assert cursor(state) == (5, 2)

    def test_vpa(self):
        """CSI n d - Vertical Position Absolute (1-indexed row)."""
        state = run_term(b"\x1b[5CABCDE\x1b[3dX", 20, 5)
        # Cursor initially at (0,0), move forward 5 => (5,0), write ABCDE => (10,0)
        # CSI 3d sets row to 2 (0-indexed), column stays at 10
        assert cell_cp(state, 10, 2) == ord('X')
        assert cursor(state) == (11, 2)


# ========================================================================
# SGR attributes
# ========================================================================

class TestSGR:
    def test_bold(self):
        state = run_term(b"\x1b[1mA\x1b[0mB", 20, 5)
        assert cell_at(state, 0, 0) & ATTR_BOLD
        assert not (cell_at(state, 1, 0) & ATTR_BOLD)

    def test_italic(self):
        state = run_term(b"\x1b[3mA", 20, 5)
        assert cell_at(state, 0, 0) & ATTR_ITALIC

    def test_underline(self):
        state = run_term(b"\x1b[4mA", 20, 5)
        assert cell_at(state, 0, 0) & ATTR_UNDERLINE

    def test_combined_attrs(self):
        """Multiple attributes in one SGR sequence."""
        state = run_term(b"\x1b[1;3;4mA", 20, 5)
        at = cell_at(state, 0, 0)
        assert at & ATTR_BOLD
        assert at & ATTR_ITALIC
        assert at & ATTR_UNDERLINE

    def test_selective_reset(self):
        """SGR 24 turns off underline but keeps bold."""
        state = run_term(b"\x1b[1;4mAB\x1b[24mCD", 20, 5)
        assert cell_at(state, 0, 0) & ATTR_BOLD
        assert cell_at(state, 0, 0) & ATTR_UNDERLINE
        assert cell_at(state, 2, 0) & ATTR_BOLD
        assert not (cell_at(state, 2, 0) & ATTR_UNDERLINE)

    def test_strikethrough(self):
        state = run_term(b"\x1b[9mA\x1b[29mB", 20, 5)
        assert cell_at(state, 0, 0) & ATTR_STRIKETHROUGH
        assert not (cell_at(state, 1, 0) & ATTR_STRIKETHROUGH)

    def test_dim_and_invisible(self):
        state = run_term(b"\x1b[2;8mA\x1b[22;28mB", 20, 5)
        assert cell_at(state, 0, 0) & ATTR_DIM
        assert cell_at(state, 0, 0) & ATTR_INVISIBLE
        assert not (cell_at(state, 1, 0) & ATTR_DIM)
        assert not (cell_at(state, 1, 0) & ATTR_INVISIBLE)

    def test_blink(self):
        """SGR 5 sets blink, SGR 25 clears it."""
        state = run_term(b"\x1b[5mA\x1b[25mB", 20, 5)
        assert cell_at(state, 0, 0) & ATTR_BLINK
        assert not (cell_at(state, 1, 0) & ATTR_BLINK)

    def test_reverse(self):
        """SGR 7 sets reverse, SGR 27 clears it."""
        state = run_term(b"\x1b[7mA\x1b[27mB", 20, 5)
        assert cell_at(state, 0, 0) & ATTR_REVERSE
        assert not (cell_at(state, 1, 0) & ATTR_REVERSE)


# ========================================================================
# Colors
# ========================================================================

class TestColors:
    def test_fg_standard(self):
        """SGR 31 = red foreground."""
        state = run_term(b"\x1b[31mA", 20, 5)
        assert cell_fg(state, 0, 0) == (170, 0, 0)

    def test_bg_standard(self):
        """SGR 42 = green background."""
        state = run_term(b"\x1b[42mA", 20, 5)
        assert cell_bg(state, 0, 0) == (0, 170, 0)

    def test_bright_fg(self):
        """SGR 91 = bright red foreground."""
        state = run_term(b"\x1b[91mA", 20, 5)
        assert cell_fg(state, 0, 0) == (255, 85, 85)

    def test_bright_bg(self):
        """SGR 104 = bright blue background."""
        state = run_term(b"\x1b[104mA", 20, 5)
        assert cell_bg(state, 0, 0) == (85, 85, 255)

    def test_24bit_fg(self):
        state = run_term(b"\x1b[38;2;100;200;50mA", 20, 5)
        assert cell_fg(state, 0, 0) == (100, 200, 50)

    def test_24bit_bg(self):
        state = run_term(b"\x1b[48;2;10;20;30mA", 20, 5)
        assert cell_bg(state, 0, 0) == (10, 20, 30)

    def test_256color_standard(self):
        """256-color index 1 = standard red."""
        state = run_term(b"\x1b[38;5;1mA", 20, 5)
        assert cell_fg(state, 0, 0) == (170, 0, 0)

    def test_256color_cube(self):
        """256-color index 196 = 6x6x6 cube (5,0,0) = (255,0,0)."""
        state = run_term(b"\x1b[38;5;196mA", 20, 5)
        assert cell_fg(state, 0, 0) == (255, 0, 0)

    def test_256color_cube_mixed(self):
        """256-color index 82 = (1,5,0) = (95,255,0)."""
        state = run_term(b"\x1b[38;5;82mA", 20, 5)
        assert cell_fg(state, 0, 0) == (95, 255, 0)

    def test_256color_grayscale(self):
        """256-color index 240 = gray 88."""
        state = run_term(b"\x1b[38;5;240mA", 20, 5)
        assert cell_fg(state, 0, 0) == (88, 88, 88)

    def test_default_fg_reset(self):
        """SGR 39 resets foreground to default."""
        state = run_term(b"\x1b[31mA\x1b[39mB", 20, 5)
        assert cell_fg(state, 0, 0) == (170, 0, 0)
        assert cell_fg(state, 1, 0) == DEFAULT_FG

    def test_default_bg_reset(self):
        """SGR 49 resets background to default."""
        state = run_term(b"\x1b[42mA\x1b[49mB", 20, 5)
        assert cell_bg(state, 0, 0) == (0, 170, 0)
        assert cell_bg(state, 1, 0) == DEFAULT_BG

    def test_complex_sgr_combined(self):
        """Bold + italic + 24-bit fg + 24-bit bg in one sequence."""
        state = run_term(
            b"\x1b[1;3;38;2;10;20;30;48;2;40;50;60mA", 20, 5
        )
        c = state['cells'][0][0]
        assert c['at'] & ATTR_BOLD
        assert c['at'] & ATTR_ITALIC
        assert tuple(c['fg']) == (10, 20, 30)
        assert tuple(c['bg']) == (40, 50, 60)


# ========================================================================
# Erase operations
# ========================================================================

class TestErase:
    def test_erase_line_to_end(self):
        """CSI 0 K erases from cursor to end of line."""
        state = run_term(b"ABCDE\x1b[3G\x1b[K", 20, 5)
        assert cell_cp(state, 0, 0) == ord('A')
        assert cell_cp(state, 1, 0) == ord('B')
        assert cell_cp(state, 2, 0) == 0
        assert cell_cp(state, 3, 0) == 0
        assert cell_cp(state, 4, 0) == 0

    def test_erase_line_to_beginning(self):
        """CSI 1 K erases from beginning to cursor (inclusive)."""
        state = run_term(b"ABCDE\x1b[3G\x1b[1K", 20, 5)
        assert cell_cp(state, 0, 0) == 0
        assert cell_cp(state, 1, 0) == 0
        assert cell_cp(state, 2, 0) == 0  # cursor pos is inclusive
        assert cell_cp(state, 3, 0) == ord('D')
        assert cell_cp(state, 4, 0) == ord('E')

    def test_erase_entire_line(self):
        """CSI 2 K erases entire line."""
        state = run_term(b"ABCDE\x1b[3G\x1b[2K", 20, 5)
        for x in range(5):
            assert cell_cp(state, x, 0) == 0

    def test_erase_display_below(self):
        """CSI 0 J erases from cursor to end of display."""
        state = run_term(
            b"\x1b[1;1HA\x1b[2;3HC\x1b[3;5HE\x1b[2;1H\x1b[J",
            20, 5
        )
        assert cell_cp(state, 0, 0) == ord('A')  # row 0 untouched
        assert cell_cp(state, 2, 1) == 0          # row 1 erased from cursor
        assert cell_cp(state, 4, 2) == 0          # row 2 fully erased

    def test_erase_display_above(self):
        """CSI 1 J erases from beginning to cursor (inclusive)."""
        state = run_term(
            b"\x1b[1;1HA\x1b[2;3HC\x1b[3;5HE\x1b[2;4H\x1b[1J",
            20, 5
        )
        assert cell_cp(state, 0, 0) == 0          # row 0 erased
        assert cell_cp(state, 2, 1) == 0           # erased (before cursor)
        assert cell_cp(state, 4, 2) == ord('E')    # row 2 untouched

    def test_erase_entire_display(self):
        """CSI 2 J erases entire display."""
        state = run_term(b"ABCDE\x1b[2J", 20, 5)
        for x in range(5):
            assert cell_cp(state, x, 0) == 0

    def test_erase_with_bg_color(self):
        """Erased cells inherit current pen's background color."""
        state = run_term(
            b"ABCDE\x1b[48;2;100;0;0m\x1b[3G\x1b[K", 20, 5
        )
        assert cell_bg(state, 0, 0) == DEFAULT_BG       # A - original
        assert cell_bg(state, 1, 0) == DEFAULT_BG       # B - original
        assert cell_bg(state, 2, 0) == (100, 0, 0)      # erased with custom bg
        assert cell_bg(state, 3, 0) == (100, 0, 0)
        assert cell_cp(state, 2, 0) == 0                 # content erased

    def test_erase_chars(self):
        """CSI n X erases N characters at cursor without shifting."""
        state = run_term(b"ABCDE\x1b[2G\x1b[2X", 20, 5)
        # Cursor at col 1 (0-indexed), erase 2 chars: B and C become blank
        assert cell_cp(state, 0, 0) == ord('A')
        assert cell_cp(state, 1, 0) == 0   # erased
        assert cell_cp(state, 2, 0) == 0   # erased
        assert cell_cp(state, 3, 0) == ord('D')  # NOT shifted
        assert cell_cp(state, 4, 0) == ord('E')


# ========================================================================
# Insert / Delete characters
# ========================================================================

class TestInsertDeleteChars:
    def test_insert_chars(self):
        """CSI n @ inserts N blank characters at cursor, shifting content right."""
        state = run_term(b"ABCDE\x1b[2G\x1b[2@", 10, 5)
        # Cursor at col 1 (0-indexed), insert 2 blanks
        # A _ _ B C D E ... (E may be lost if cols are tight)
        assert cell_cp(state, 0, 0) == ord('A')
        assert cell_cp(state, 1, 0) == 0   # inserted blank
        assert cell_cp(state, 2, 0) == 0   # inserted blank
        assert cell_cp(state, 3, 0) == ord('B')  # shifted right
        assert cell_cp(state, 4, 0) == ord('C')  # shifted right
        assert cell_cp(state, 5, 0) == ord('D')  # shifted right
        assert cell_cp(state, 6, 0) == ord('E')  # shifted right

    def test_delete_chars(self):
        """CSI n P deletes N characters at cursor, shifting content left."""
        state = run_term(b"ABCDE\x1b[2G\x1b[2P", 10, 5)
        # Cursor at col 1 (0-indexed), delete 2 chars (B, C)
        # A D E _ _ ...
        assert cell_cp(state, 0, 0) == ord('A')
        assert cell_cp(state, 1, 0) == ord('D')  # shifted left
        assert cell_cp(state, 2, 0) == ord('E')  # shifted left
        assert cell_cp(state, 3, 0) == 0   # blank from shift


# ========================================================================
# Line wrap and scrolling
# ========================================================================

class TestWrapAndScroll:
    def test_line_wrap(self):
        """Writing past end of line wraps to next line (pending wrap)."""
        state = run_term(b"1234567890X", 10, 5)
        assert cell_cp(state, 0, 0) == ord('1')
        assert cell_cp(state, 9, 0) == ord('0')
        assert cell_cp(state, 0, 1) == ord('X')
        assert cursor(state) == (1, 1)

    def test_pending_wrap_then_move(self):
        """Pending wrap is cancelled by explicit cursor movement."""
        state = run_term(b"1234567890\x1b[1;5HX", 10, 5)
        assert cell_cp(state, 9, 0) == ord('0')
        assert cell_cp(state, 4, 0) == ord('X')  # overwrites '5'
        assert cell_cp(state, 0, 1) == 0          # no wrap happened

    def test_scroll_at_bottom(self):
        """LF at bottom row scrolls content up."""
        state = run_term(b"A\r\nB\r\nC\r\nD", 10, 3)
        assert cell_cp(state, 0, 0) == ord('B')
        assert cell_cp(state, 0, 1) == ord('C')
        assert cell_cp(state, 0, 2) == ord('D')
        assert cursor(state) == (1, 2)

    def test_scroll_region(self):
        """DECSTBM restricts scrolling to the set region."""
        state = run_term(
            b"\x1b[1;1HL1"
            b"\x1b[2;1HL2"
            b"\x1b[3;1HL3"
            b"\x1b[4;1HL4"
            b"\x1b[5;1HL5"
            b"\x1b[2;4r"      # scroll region rows 2-4 (0-indexed: 1-3)
            b"\x1b[4;1H"      # cursor at row 4 = bottom of region
            b"\n"              # LF scrolls within region
            b"XX",
            10, 5
        )
        assert cell_cp(state, 0, 0) == ord('L')
        assert cell_cp(state, 1, 0) == ord('1')
        assert cell_cp(state, 0, 1) == ord('L')
        assert cell_cp(state, 1, 1) == ord('3')
        assert cell_cp(state, 0, 2) == ord('L')
        assert cell_cp(state, 1, 2) == ord('4')
        assert cell_cp(state, 0, 3) == ord('X')
        assert cell_cp(state, 1, 3) == ord('X')
        assert cell_cp(state, 0, 4) == ord('L')
        assert cell_cp(state, 1, 4) == ord('5')

    def test_scroll_up_csi(self):
        """CSI n S scrolls entire scroll region up by N lines."""
        state = run_term(
            b"\x1b[1;1HL1"
            b"\x1b[2;1HL2"
            b"\x1b[3;1HL3"
            b"\x1b[4;1HL4"
            b"\x1b[5;1HL5"
            b"\x1b[2S",       # scroll up 2 lines
            10, 5
        )
        # After scroll up 2: L3, L4, L5, blank, blank
        assert cell_cp(state, 0, 0) == ord('L')
        assert cell_cp(state, 1, 0) == ord('3')
        assert cell_cp(state, 0, 1) == ord('L')
        assert cell_cp(state, 1, 1) == ord('4')
        assert cell_cp(state, 0, 2) == ord('L')
        assert cell_cp(state, 1, 2) == ord('5')
        assert cell_cp(state, 0, 3) == 0  # blank
        assert cell_cp(state, 0, 4) == 0  # blank

    def test_scroll_down_csi(self):
        """CSI n T scrolls entire scroll region down by N lines."""
        state = run_term(
            b"\x1b[1;1HL1"
            b"\x1b[2;1HL2"
            b"\x1b[3;1HL3"
            b"\x1b[4;1HL4"
            b"\x1b[5;1HL5"
            b"\x1b[2T",       # scroll down 2 lines
            10, 5
        )
        # After scroll down 2: blank, blank, L1, L2, L3
        assert cell_cp(state, 0, 0) == 0  # blank
        assert cell_cp(state, 0, 1) == 0  # blank
        assert cell_cp(state, 0, 2) == ord('L')
        assert cell_cp(state, 1, 2) == ord('1')
        assert cell_cp(state, 0, 3) == ord('L')
        assert cell_cp(state, 1, 3) == ord('2')
        assert cell_cp(state, 0, 4) == ord('L')
        assert cell_cp(state, 1, 4) == ord('3')


# ========================================================================
# Insert / Delete lines
# ========================================================================

class TestInsertDeleteLines:
    def _fill_rows(self):
        """Helper: fill 5 rows with AA, BB, CC, DD, EE."""
        return (
            b"\x1b[1;1HAA"
            b"\x1b[2;1HBB"
            b"\x1b[3;1HCC"
            b"\x1b[4;1HDD"
            b"\x1b[5;1HEE"
        )

    def test_insert_line(self):
        state = run_term(
            self._fill_rows() + b"\x1b[2;1H\x1b[L",
            10, 5
        )
        assert cell_cp(state, 0, 0) == ord('A')   # row 0 unchanged
        assert cell_cp(state, 0, 1) == 0           # inserted blank
        assert cell_cp(state, 0, 2) == ord('B')   # pushed down from row 1
        assert cell_cp(state, 0, 3) == ord('C')   # pushed down
        assert cell_cp(state, 0, 4) == ord('D')   # pushed down, EE lost

    def test_delete_line(self):
        state = run_term(
            self._fill_rows() + b"\x1b[2;1H\x1b[M",
            10, 5
        )
        assert cell_cp(state, 0, 0) == ord('A')   # row 0 unchanged
        assert cell_cp(state, 0, 1) == ord('C')   # shifted up from row 2
        assert cell_cp(state, 0, 2) == ord('D')
        assert cell_cp(state, 0, 3) == ord('E')
        assert cell_cp(state, 0, 4) == 0           # blank at bottom


# ========================================================================
# Cursor save / restore
# ========================================================================

class TestCursorSaveRestore:
    def test_esc_7_8(self):
        """ESC 7 saves, ESC 8 restores cursor position and attributes."""
        state = run_term(
            b"\x1b[3;3HA"     # write A at (2,2)
            b"\x1b7"          # save cursor
            b"\x1b[1;1HB"    # write B at (0,0)
            b"\x1b8"          # restore cursor to (3,2) — one past 'A'
            b"C",             # write C at (3,2)
            20, 5
        )
        assert cell_cp(state, 2, 2) == ord('A')
        assert cell_cp(state, 0, 0) == ord('B')
        assert cell_cp(state, 3, 2) == ord('C')
        assert cursor(state) == (4, 2)

    def test_csi_s_u(self):
        """CSI s / CSI u save/restore cursor."""
        state = run_term(
            b"\x1b[3;3HA\x1b[s\x1b[1;1HB\x1b[uC",
            20, 5
        )
        assert cell_cp(state, 2, 2) == ord('A')
        assert cell_cp(state, 0, 0) == ord('B')
        assert cell_cp(state, 3, 2) == ord('C')


# ========================================================================
# Partial escape sequences (chunked input)
# ========================================================================

class TestPartialSequences:
    def test_1byte_chunks(self):
        """Same result when input is fed one byte at a time."""
        input_data = (
            b"\x1b[38;2;100;200;50m"
            b"\x1b[3;5HHello"
            b"\x1b[1mWorld"
        )
        state_full = run_term(input_data, 20, 5, chunk_size=0)
        state_chunked = run_term(input_data, 20, 5, chunk_size=1)
        assert state_full == state_chunked

    def test_2byte_chunks(self):
        """Same result with 2-byte chunks (ESC and [ may split)."""
        input_data = (
            b"\x1b[48;2;10;20;30m"
            b"\x1b[2;4H"
            b"Test\x1b[0m done"
        )
        state_full = run_term(input_data, 20, 5, chunk_size=0)
        state_chunked = run_term(input_data, 20, 5, chunk_size=2)
        assert state_full == state_chunked

    def test_3byte_chunks(self):
        """Complex sequence with scroll region, split into 3-byte chunks."""
        input_data = (
            b"\x1b[1;1HAA\x1b[2;1HBB\x1b[3;1HCC"
            b"\x1b[1;2r\x1b[2;1H\n"
            b"XX"
        )
        state_full = run_term(input_data, 10, 3, chunk_size=0)
        state_chunked = run_term(input_data, 10, 3, chunk_size=3)
        assert state_full == state_chunked


# ========================================================================
# Complex / integration tests
# ========================================================================

class TestIntegration:
    def test_termbench_fgperchar_style(self):
        """
        Simulate termbench's FGPerChar workload: per-character color changes
        with cursor positioning, and verify final state.
        """
        width, height = 10, 3
        data = bytearray()
        for y in range(height):
            data.extend(f"\x1b[{y+1};1H".encode())
            for x in range(width):
                r = (x * 25) & 0xff
                g = (y * 80) & 0xff
                b = ((x + y) * 40) & 0xff
                data.extend(f"\x1b[38;2;{r};{g};{b}m".encode())
                data.append(ord('a') + (x + y) % 26)

        state = run_term(bytes(data), width, height)
        for y in range(height):
            for x in range(width):
                expected_char = ord('a') + (x + y) % 26
                assert cell_cp(state, x, y) == expected_char
                r = (x * 25) & 0xff
                g = (y * 80) & 0xff
                b = ((x + y) * 40) & 0xff
                assert cell_fg(state, x, y) == (r, g, b)

    def test_reverse_index(self):
        """ESC M at top of scroll region scrolls down."""
        state = run_term(
            b"\x1b[1;1HAA"
            b"\x1b[2;1HBB"
            b"\x1b[3;1HCC"
            b"\x1b[1;3r"      # scroll region rows 1-3
            b"\x1b[1;1H"      # cursor at top of region
            b"\x1bM"          # reverse index -> scroll down within region
            b"XX",            # write on new blank line at top
            10, 3
        )
        assert cell_cp(state, 0, 0) == ord('X')
        assert cell_cp(state, 1, 0) == ord('X')
        assert cell_cp(state, 0, 1) == ord('A')
        assert cell_cp(state, 1, 1) == ord('A')
        assert cell_cp(state, 0, 2) == ord('B')
        assert cell_cp(state, 1, 2) == ord('B')

    def test_esc_index(self):
        """ESC D (index) moves cursor down, scrolling at bottom of region."""
        state = run_term(
            b"\x1b[1;1HA"
            b"\x1b[2;1HB"
            b"\x1b[3;1HC"
            b"\x1b[3;1H"      # cursor at row 3 (bottom)
            b"\x1bD"           # ESC D = index (same as LF)
            b"\rX",            # CR then write X on new blank bottom line
            10, 3
        )
        # After index at bottom: scroll up. B, C, X
        assert cell_cp(state, 0, 0) == ord('B')
        assert cell_cp(state, 0, 1) == ord('C')
        assert cell_cp(state, 0, 2) == ord('X')

    def test_esc_next_line(self):
        """ESC E (next line) moves cursor to beginning of next line."""
        state = run_term(
            b"\x1b[1;5HTEST"    # write TEST starting at col 5
            b"\x1bE"             # ESC E = next line (CR + LF)
            b"XY",              # write XY at beginning of next line
            20, 5
        )
        # ESC E should put cursor at col 0 of next line
        assert cell_cp(state, 0, 1) == ord('X')
        assert cell_cp(state, 1, 1) == ord('Y')

    def test_osc_ignored(self):
        """OSC sequences (window title etc.) are consumed without effect."""
        state = run_term(
            b"\x1b]0;My Title\x07"   # OSC set title, terminated by BEL
            b"A"
            b"\x1b]2;Other\x1b\\"    # OSC terminated by ST
            b"B",
            20, 5
        )
        assert cell_cp(state, 0, 0) == ord('A')
        assert cell_cp(state, 1, 0) == ord('B')
        assert cursor(state) == (2, 0)

    def test_dec_private_mode_ignored(self):
        """CSI ? ... h/l (DEC private modes) are consumed gracefully."""
        state = run_term(
            b"\x1b[?25l"      # hide cursor
            b"A"
            b"\x1b[?25h"      # show cursor
            b"B",
            20, 5
        )
        assert cell_cp(state, 0, 0) == ord('A')
        assert cell_cp(state, 1, 0) == ord('B')

    def test_multiple_scroll_regions(self):
        """
        Set scroll region, scroll, then reset region and verify
        content outside old region is untouched.
        """
        state = run_term(
            b"\x1b[1;1HL1"
            b"\x1b[2;1HL2"
            b"\x1b[3;1HL3"
            b"\x1b[4;1HL4"
            b"\x1b[5;1HL5"
            b"\x1b[2;4r"      # region rows 2-4
            b"\x1b[4;1H\nNEW" # scroll within region, write NEW
            b"\x1b[r"          # reset region to full screen
            b"\x1b[5;1H"      # go to row 5
            b"ZZ",
            10, 5
        )
        assert cell_cp(state, 0, 0) == ord('L')
        assert cell_cp(state, 1, 0) == ord('1')
        assert cell_cp(state, 0, 4) == ord('Z')  # after region reset
        assert cell_cp(state, 1, 4) == ord('Z')


# ========================================================================
# Shared library + ctypes bindings
# ========================================================================

class TestCtypesBindings:
    """Tests that libterminal.so is loadable via Python ctypes bindings."""

    @pytest.fixture(autouse=True)
    def _load_bindings(self):
        """Import the bindings module from /app/bindings.py."""
        import importlib.util
        assert os.path.exists('/app/libterminal.so'), \
            "libterminal.so not found; make must produce it"
        assert os.path.exists('/app/bindings.py'), \
            "bindings.py not found; must be implemented from bindings_skel.py"
        spec = importlib.util.spec_from_file_location("bindings", "/app/bindings.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_library_loads(self):
        """libterminal.so must exist and be loadable via TerminalEmulator."""
        term = self.mod.TerminalEmulator(10, 5)
        term.close()

    def test_simple_text_via_bindings(self):
        """Basic text output through ctypes bindings matches expected state."""
        term = self.mod.TerminalEmulator(20, 5)
        term.process(b"Hello")
        assert term.get_cell(0, 0)['cp'] == ord('H')
        assert term.get_cell(1, 0)['cp'] == ord('e')
        assert term.get_cell(4, 0)['cp'] == ord('o')
        assert term.get_cell(5, 0)['cp'] == 0
        assert term.cursor() == (5, 0)
        term.close()

    def test_sgr_via_bindings(self):
        """SGR attributes and colors through ctypes bindings."""
        term = self.mod.TerminalEmulator(20, 5)
        term.process(b"\x1b[1;31mA")
        cell = term.get_cell(0, 0)
        assert cell['at'] & ATTR_BOLD
        assert cell['fg'] == [170, 0, 0]
        term.close()

    def test_24bit_color_via_bindings(self):
        """24-bit color through ctypes bindings."""
        term = self.mod.TerminalEmulator(20, 5)
        term.process(b"\x1b[38;2;10;20;30;48;2;40;50;60mA")
        cell = term.get_cell(0, 0)
        assert cell['fg'] == [10, 20, 30]
        assert cell['bg'] == [40, 50, 60]
        term.close()

    def test_bindings_match_binary(self):
        """Bindings get_state() must produce identical JSON to vtterm binary."""
        input_data = (
            b"\x1b[38;2;100;200;50m"
            b"\x1b[3;5HHello"
            b"\x1b[1mWorld"
        )
        # Get state from binary
        binary_state = run_term(input_data, 20, 5)
        # Get state from bindings
        term = self.mod.TerminalEmulator(20, 5)
        term.process(input_data)
        bindings_state = term.get_state()
        term.close()
        assert binary_state == bindings_state

    def test_scroll_via_bindings(self):
        """Scroll region and line feed through ctypes bindings."""
        term = self.mod.TerminalEmulator(10, 3)
        term.process(b"A\r\nB\r\nC\r\nD")
        # After scroll: B, C, D
        assert term.get_cell(0, 0)['cp'] == ord('B')
        assert term.get_cell(0, 1)['cp'] == ord('C')
        assert term.get_cell(0, 2)['cp'] == ord('D')
        term.close()


# ========================================================================
# tmux oracle validation
# ========================================================================

class TestTmuxOracle:
    """Cross-validate the VT parser against tmux as a reference terminal."""

    @pytest.fixture(autouse=True)
    def _check_tmux(self):
        """Skip if tmux or oracle script is not available."""
        result = subprocess.run(['which', 'tmux'], capture_output=True)
        if result.returncode != 0:
            pytest.skip("tmux not available")
        if not os.path.exists('/app/tmux_oracle.sh'):
            pytest.skip("tmux_oracle.sh not found")
        # Ensure executable
        os.chmod('/app/tmux_oracle.sh', 0o755)

    def _run_oracle(self, input_bytes, width, height):
        """Run tmux_oracle.sh and return captured lines."""
        result = subprocess.run(
            ['/app/tmux_oracle.sh', str(width), str(height)],
            input=input_bytes,
            capture_output=True,
            timeout=15
        )
        assert result.returncode == 0, \
            f"tmux_oracle.sh failed (rc={result.returncode}): " \
            f"{result.stderr.decode(errors='replace')}"
        lines = result.stdout.decode(errors='replace').split('\n')
        # Remove trailing empty line from final newline
        if lines and lines[-1] == '':
            lines = lines[:-1]
        # Pad to expected height
        while len(lines) < height:
            lines.append('')
        return lines

    def _parser_text_grid(self, input_bytes, width, height):
        """Get text grid from the parser as list of strings."""
        state = run_term(input_bytes, width, height)
        rows = []
        for y in range(height):
            row_chars = []
            for x in range(width):
                cp = cell_cp(state, x, y)
                row_chars.append(chr(cp) if cp >= 0x20 else ' ')
            rows.append(''.join(row_chars).rstrip())
        return rows

    def test_simple_text_oracle(self):
        """Simple text placement matches between parser and tmux."""
        input_data = b"Hello World"
        width, height = 20, 5

        oracle_lines = self._run_oracle(input_data, width, height)
        parser_lines = self._parser_text_grid(input_data, width, height)

        assert oracle_lines[0].rstrip() == parser_lines[0]

    def test_cursor_positioning_oracle(self):
        """CSI H cursor positioning matches between parser and tmux."""
        input_data = b"\x1b[3;5HXY\x1b[1;1HAB"
        width, height = 20, 5

        oracle_lines = self._run_oracle(input_data, width, height)
        parser_lines = self._parser_text_grid(input_data, width, height)

        # Row 0 should start with AB
        assert oracle_lines[0][:2] == 'AB'
        assert parser_lines[0][:2] == 'AB'
        # Row 2 should have XY at column 4
        oracle_row2 = oracle_lines[2] if len(oracle_lines) > 2 else ''
        assert oracle_row2[4:6] == 'XY'
        assert parser_lines[2][4:6] == 'XY'

    def test_multiline_oracle(self):
        """Multiple lines with CR/LF match between parser and tmux."""
        input_data = b"Line1\r\nLine2\r\nLine3"
        width, height = 20, 5

        oracle_lines = self._run_oracle(input_data, width, height)
        parser_lines = self._parser_text_grid(input_data, width, height)

        for y in range(3):
            assert oracle_lines[y].rstrip() == parser_lines[y], \
                f"Row {y} mismatch: oracle={oracle_lines[y]!r}, parser={parser_lines[y]!r}"

    def test_erase_oracle(self):
        """Erase operations match between parser and tmux."""
        input_data = b"ABCDE\x1b[3G\x1b[K"
        width, height = 20, 5

        oracle_lines = self._run_oracle(input_data, width, height)
        parser_lines = self._parser_text_grid(input_data, width, height)

        # First two chars should be AB, rest should be blank
        assert oracle_lines[0].rstrip() == parser_lines[0]
        assert parser_lines[0] == 'AB'
