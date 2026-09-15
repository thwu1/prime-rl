
import sys
sys.path.insert(0, "/app")

import pytest
from vtbuffer import ScreenBuffer

NUL = '\x00'


def prepare_standard(buf):
    """Write the standard 8x8 test pattern used by esctest2."""
    lines = [
        "abcdefgh",
        "ijklmnop",
        "qrstuvwx",
        "yz012345",
        "ABCDEFGH",
        "IJKLMNOP",
        "QRSTUVWX",
        "YZ6789!@",
    ]
    buf.set_cursor(1, 1)
    for i, line in enumerate(lines):
        for ch in line:
            buf.write_char(ch)
        if i < len(lines) - 1:
            buf.carriage_return()
            buf.linefeed()


def assert_rect(buf, top, left, bottom, right, expected):
    actual = buf.get_rect(top, left, bottom, right)
    def norm(s):
        return s.replace(NUL, '.')
    actual_norm = [norm(s) for s in actual]
    expected_norm = [norm(s) for s in expected]
    assert actual_norm == expected_norm, (
        f"Rect({top},{left},{bottom},{right}):\n"
        f"  expected: {expected_norm}\n"
        f"  actual:   {actual_norm}"
    )


# ============================================================
# Bug 1: DECCRA must use a temporary buffer for overlapping copies
# ============================================================

class TestDECCRAOverlap:
    """Verifies DECCRA handles overlapping source/dest correctly.
    Per DEC VT420 spec, DECCRA copies as if through a temporary buffer,
    so source data is not corrupted by destination writes during the copy."""

    def test_overlapping_down_right(self):
        """Copy 3x3 block from (2,2)-(4,4) to (3,3) -- overlap down-right."""
        buf = ScreenBuffer(80, 24)
        prepare_standard(buf)
        buf.deccra(src_top=2, src_left=2, src_bottom=4, src_right=4,
                   src_page=1, dst_top=3, dst_left=3, dst_page=1)
        # Expected result from esctest2 deccra.py test_DECCRA_overlappingSourceAndDest
        assert_rect(buf, 1, 1, 8, 8,
                    ["abcdefgh",
                     "ijklmnop",
                     "qrjklvwx",
                     "yzrst345",
                     "ABz01FGH",
                     "IJKLMNOP",
                     "QRSTUVWX",
                     "YZ6789!@"])

    def test_overlapping_up_left(self):
        """Copy 3x3 block from (3,3)-(5,5) to (2,2) -- overlap up-left."""
        buf = ScreenBuffer(80, 24)
        prepare_standard(buf)
        buf.deccra(src_top=3, src_left=3, src_bottom=5, src_right=5,
                   src_page=1, dst_top=2, dst_left=2, dst_page=1)
        assert_rect(buf, 1, 1, 8, 8,
                    ["abcdefgh",
                     "istumnop",
                     "q012uvwx",
                     "yCDE2345",
                     "ABCDEFGH",
                     "IJKLMNOP",
                     "QRSTUVWX",
                     "YZ6789!@"])

    def test_non_overlapping(self):
        """Copy 3x3 block from (2,2)-(4,4) to dest (5,5). No overlap."""
        buf = ScreenBuffer(80, 24)
        prepare_standard(buf)
        buf.deccra(src_top=2, src_left=2, src_bottom=4, src_right=4,
                   src_page=1, dst_top=5, dst_left=5, dst_page=1)
        assert_rect(buf, 1, 1, 8, 8,
                    ["abcdefgh",
                     "ijklmnop",
                     "qrstuvwx",
                     "yz012345",
                     "ABCDjklH",
                     "IJKLrstP",
                     "QRSTz01X",
                     "YZ6789!@"])


# ============================================================
# Bug 2: DECSERA must respect only DEC protection (mode 1),
#         NOT ISO protection (mode 2)
# ============================================================

class TestDECSERAProtection:
    """Verifies DECSERA character protection semantics per DEC VT420 spec."""

    def test_respects_dec_protection(self):
        """DECSERA preserves DEC-protected (mode 1) characters."""
        buf = ScreenBuffer(80, 24)
        buf.set_cursor(1, 1)
        buf.write_char('a')
        buf.set_character_protection(1)  # DEC protected
        buf.write_char('b')
        buf.set_character_protection(0)
        buf.write_char('c')
        buf.decsera(1, 1, 1, 3)
        assert_rect(buf, 1, 1, 1, 3, [NUL + "b" + NUL])

    def test_does_not_respect_iso_protection(self):
        """DECSERA does NOT respect ISO protection (mode 2).
        Per esctest2 test_DECSERA_doesNotRespectISOProtect."""
        buf = ScreenBuffer(80, 24)
        buf.set_cursor(1, 1)
        buf.write_char('a')
        buf.set_character_protection(2)  # ISO protected
        buf.write_char('b')
        buf.set_character_protection(0)
        buf.decsera(1, 1, 1, 2)
        # ISO protection must be ignored by DECSERA -- both cells erased
        assert_rect(buf, 1, 1, 1, 2, [NUL * 2])

    def test_mixed_protection_modes(self):
        """Only DEC protection (1) survives DECSERA; ISO (2) and none (0) are erased."""
        buf = ScreenBuffer(80, 24)
        buf.set_cursor(1, 1)
        buf.set_character_protection(0)
        buf.write_char('a')  # unprotected
        buf.set_character_protection(1)
        buf.write_char('b')  # DEC protected
        buf.set_character_protection(2)
        buf.write_char('c')  # ISO protected
        buf.set_character_protection(0)
        buf.write_char('d')  # unprotected
        buf.decsera(1, 1, 1, 4)
        # Only 'b' (DEC protected) should survive
        assert_rect(buf, 1, 1, 1, 4, [NUL + "b" + NUL + NUL])

    def test_alternating_protection_rows(self):
        """DECSERA with alternating DEC-protected/unprotected rows."""
        buf = ScreenBuffer(80, 24)
        lines = ["abcdefgh", "ijklmnop", "qrstuvwx", "yz012345",
                 "ABCDEFGH", "IJKLMNOP", "QRSTUVWX", "YZ6789!@"]
        buf.set_cursor(1, 1)
        protect = 1
        for i, line in enumerate(lines):
            buf.set_character_protection(protect)
            for ch in line:
                buf.write_char(ch)
            if i < len(lines) - 1:
                buf.carriage_return()
                buf.linefeed()
            protect = 1 - protect
        buf.set_character_protection(0)

        buf.decsera(5, 5, 7, 7)
        # Row 5 (protect=1): preserved; Row 6 (protect=0): erased; Row 7 (protect=1): preserved
        assert_rect(buf, 5, 5, 7, 7,
                    ["EFG",
                     NUL * 3,
                     "UVW"])


# ============================================================
# Bug 3: DECFRA must respect origin mode (translate coordinates)
# ============================================================

class TestDECFRAOriginMode:
    """Verifies DECFRA applies origin mode coordinate translation.
    Per esctest2 decrectops.py fillRectangle_respectsOriginMode."""

    def test_origin_mode_translates_coords(self):
        """DECFRA with origin mode: coords (1,1)-(3,3) should map to
        screen coords (2,2)-(4,4) when margins start at 2."""
        buf = ScreenBuffer(80, 24)
        prepare_standard(buf)
        buf.set_left_right_margin_mode(True)
        buf.set_left_right_margins(2, 9)
        buf.set_scrolling_region(2, 9)
        buf.set_origin_mode(True)
        # Fill (1,1)-(3,3) in origin coords = (2,2)-(4,4) absolute
        buf.decfra(ord('%'), 1, 1, 3, 3)
        buf.set_left_right_margin_mode(False)
        buf.set_scrolling_region(None, None)
        buf.set_origin_mode(False)
        # Verify fill went to absolute (2,2)-(4,4)
        assert_rect(buf, 1, 1, 8, 8,
                    ["abcdefgh",
                     "i%%%mnop",
                     "q%%%uvwx",
                     "y%%%2345",
                     "ABCDEFGH",
                     "IJKLMNOP",
                     "QRSTUVWX",
                     "YZ6789!@"])

    def test_no_origin_mode_uses_absolute(self):
        """Without origin mode, DECFRA uses absolute coordinates."""
        buf = ScreenBuffer(80, 24)
        prepare_standard(buf)
        buf.decfra(ord('%'), 5, 5, 7, 7)
        assert_rect(buf, 1, 1, 8, 8,
                    ["abcdefgh",
                     "ijklmnop",
                     "qrstuvwx",
                     "yz012345",
                     "ABCD%%%H",
                     "IJKL%%%P",
                     "QRST%%%X",
                     "YZ6789!@"])

    def test_decfra_ignores_margins_for_fill(self):
        """DECFRA ignores margins for the fill operation itself."""
        buf = ScreenBuffer(80, 24)
        prepare_standard(buf)
        buf.set_left_right_margin_mode(True)
        buf.set_left_right_margins(3, 6)
        buf.set_scrolling_region(3, 6)
        buf.decfra(ord('%'), 5, 5, 7, 7)
        buf.set_left_right_margin_mode(False)
        buf.set_scrolling_region(None, None)
        assert_rect(buf, 1, 1, 8, 8,
                    ["abcdefgh",
                     "ijklmnop",
                     "qrstuvwx",
                     "yz012345",
                     "ABCD%%%H",
                     "IJKL%%%P",
                     "QRST%%%X",
                     "YZ6789!@"])


# ============================================================
# Bug 4: DECSTBM must reset cursor to (1,1)
# ============================================================

class TestDECSTBMCursorReset:
    """Verifies DECSTBM moves cursor to (1,1) per DEC VT420 spec.
    Per esctest2 decstbm.py test_DECSTBM_MovsCursorToOrigin."""

    def test_set_region_moves_cursor_to_origin(self):
        """Setting scrolling region must move cursor to (1,1)."""
        buf = ScreenBuffer(80, 24)
        buf.set_cursor(3, 2)
        assert buf.get_cursor() == (3, 2)
        buf.set_scrolling_region(2, 3)
        assert buf.get_cursor() == (1, 1)

    def test_reset_region_moves_cursor_to_origin(self):
        """Resetting scrolling region (no args) must also move cursor to (1,1)."""
        buf = ScreenBuffer(80, 24)
        buf.set_scrolling_region(2, 5)
        buf.set_cursor(4, 3)
        assert buf.get_cursor() == (4, 3)
        buf.set_scrolling_region(None, None)
        assert buf.get_cursor() == (1, 1)

    def test_cursor_position_independent_of_region(self):
        """After DECSTBM resets cursor, subsequent set_cursor works correctly."""
        buf = ScreenBuffer(80, 24)
        buf.set_cursor(10, 10)
        buf.set_scrolling_region(5, 15)
        assert buf.get_cursor() == (1, 1)
        buf.set_cursor(7, 3)
        assert buf.get_cursor() == (7, 3)


# ============================================================
# Bug 5: DECERA must ignore character protection entirely
# ============================================================

class TestDECERAProtection:
    """Verifies DECERA ignores all character protection.
    DECERA erases unconditionally regardless of DEC or ISO protection."""

    def test_ignores_dec_protection(self):
        """DECERA must erase even DEC-protected cells."""
        buf = ScreenBuffer(80, 24)
        buf.set_cursor(1, 1)
        buf.write_char('a')
        buf.set_character_protection(1)  # DEC protected
        buf.write_char('b')
        buf.set_character_protection(0)
        buf.decera(1, 1, 1, 2)
        # Both must be erased -- DECERA ignores protection
        assert_rect(buf, 1, 1, 1, 2, [NUL * 2])

    def test_ignores_iso_protection(self):
        """DECERA must erase ISO-protected cells too."""
        buf = ScreenBuffer(80, 24)
        buf.set_cursor(1, 1)
        buf.set_character_protection(2)  # ISO protected
        buf.write_char('x')
        buf.set_character_protection(0)
        buf.decera(1, 1, 1, 1)
        assert_rect(buf, 1, 1, 1, 1, [NUL])

    def test_erases_all_regardless_of_protection(self):
        """DECERA erases all cells in the rect, regardless of protection status."""
        buf = ScreenBuffer(80, 24)
        buf.set_cursor(1, 1)
        buf.set_character_protection(0)
        buf.write_char('a')
        buf.set_character_protection(1)
        buf.write_char('b')
        buf.set_character_protection(2)
        buf.write_char('c')
        buf.set_character_protection(0)
        buf.write_char('d')
        buf.decera(1, 1, 1, 4)
        assert_rect(buf, 1, 1, 1, 4, [NUL * 4])

    def test_decera_vs_decsera_difference(self):
        """DECERA and DECSERA differ: DECERA ignores protection, DECSERA respects DEC protection."""
        buf = ScreenBuffer(80, 24)
        buf.set_cursor(1, 1)
        buf.set_character_protection(1)  # DEC protected
        buf.write_char('P')
        buf.set_character_protection(0)
        buf.write_char('U')

        # DECSERA should preserve protected 'P'
        buf.decsera(1, 1, 1, 2)
        assert_rect(buf, 1, 1, 1, 2, ["P" + NUL])

        # DECERA should erase everything including protected 'P'
        buf.decera(1, 1, 1, 2)
        assert_rect(buf, 1, 1, 1, 2, [NUL * 2])


# ============================================================
# Integration tests combining multiple operations
# ============================================================

class TestIntegration:
    """Cross-cutting tests that exercise multiple operations together."""

    def test_deccra_with_origin_mode(self):
        """DECCRA with origin mode applies coordinate translation."""
        buf = ScreenBuffer(80, 24)
        prepare_standard(buf)
        buf.set_left_right_margin_mode(True)
        buf.set_left_right_margins(2, 9)
        buf.set_scrolling_region(2, 9)
        buf.set_origin_mode(True)
        buf.deccra(src_top=1, src_left=1, src_bottom=3, src_right=3,
                   src_page=1, dst_top=4, dst_left=4, dst_page=1)
        buf.set_left_right_margin_mode(False)
        buf.set_scrolling_region(None, None)
        buf.set_origin_mode(False)
        assert_rect(buf, 1, 1, 8, 8,
                    ["abcdefgh",
                     "ijklmnop",
                     "qrstuvwx",
                     "yz012345",
                     "ABCDjklH",
                     "IJKLrstP",
                     "QRSTz01X",
                     "YZ6789!@"])

    def test_scroll_region_basic(self):
        """Scrolling within a region works correctly."""
        buf = ScreenBuffer(80, 24)
        buf.set_scrolling_region(2, 3)
        buf.set_cursor(2, 1)
        buf.write_char('1')
        buf.carriage_return()
        buf.linefeed()
        buf.write_char('2')
        assert_rect(buf, 2, 1, 3, 1, ["1", "2"])
        buf.carriage_return()
        buf.linefeed()
        assert_rect(buf, 2, 1, 3, 1, ["2", NUL])

    def test_combined_fill_selective_erase_copy(self):
        """Fill, then selectively erase with protection, then copy."""
        buf = ScreenBuffer(80, 24)
        buf.decfra(ord('A'), 1, 1, 4, 4)
        buf.set_cursor(2, 1)
        buf.set_character_protection(1)
        for _ in range(4):
            buf.write_char('A')
        buf.set_character_protection(0)
        buf.decsera(1, 1, 4, 4)
        assert_rect(buf, 1, 1, 4, 4,
                    [NUL * 4,
                     "AAAA",
                     NUL * 4,
                     NUL * 4])
        buf.deccra(src_top=2, src_left=1, src_bottom=2, src_right=4,
                   src_page=1, dst_top=3, dst_left=1, dst_page=1)
        assert_rect(buf, 1, 1, 4, 4,
                    [NUL * 4,
                     "AAAA",
                     "AAAA",
                     NUL * 4])

    def test_deccra_cursor_does_not_move(self):
        """DECCRA must not change cursor position."""
        buf = ScreenBuffer(80, 24)
        prepare_standard(buf)
        buf.set_cursor(4, 3)
        buf.deccra(src_top=2, src_left=2, src_bottom=4, src_right=4,
                   src_page=1, dst_top=5, dst_left=5, dst_page=1)
        assert buf.get_cursor() == (4, 3)

    def test_deccra_invalid_source_rect(self):
        """Invalid source rect (top > bottom) is a no-op."""
        buf = ScreenBuffer(80, 24)
        prepare_standard(buf)
        buf.deccra(src_top=2, src_left=2, src_bottom=1, src_right=1,
                   src_page=1, dst_top=5, dst_left=5, dst_page=1)
        assert_rect(buf, 1, 1, 8, 8,
                    ["abcdefgh",
                     "ijklmnop",
                     "qrstuvwx",
                     "yz012345",
                     "ABCDEFGH",
                     "IJKLMNOP",
                     "QRSTUVWX",
                     "YZ6789!@"])

    def test_decfra_cursor_does_not_move(self):
        """DECFRA must not change cursor position."""
        buf = ScreenBuffer(80, 24)
        prepare_standard(buf)
        buf.set_cursor(4, 3)
        buf.decfra(ord('%'), 2, 2, 4, 4)
        assert buf.get_cursor() == (4, 3)

    def test_origin_mode_cursor_placement(self):
        """In origin mode, set_cursor(1,1) maps to the margin corner."""
        buf = ScreenBuffer(80, 24)
        buf.set_scrolling_region(3, 10)
        buf.set_left_right_margin_mode(True)
        buf.set_left_right_margins(5, 15)
        buf.set_origin_mode(True)
        buf.set_cursor(1, 1)
        buf.write_char('X')
        buf.set_origin_mode(False)
        buf.set_left_right_margin_mode(False)
        buf.set_scrolling_region(None, None)
        assert buf.get_cell(3, 5) == 'X'
