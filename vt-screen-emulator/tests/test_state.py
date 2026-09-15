"""
VT-420 Escape Sequence Protocol Server — verification tests.

Tests launch the server via PTY, send raw escape sequences, and verify
DECRQCRA checksums returned as DCS responses.
"""

import sys
import os
import pytest

sys.path.insert(0, "/app")
from test_driver import VTSession, ProtocolError


# ──────────────────────────── fixtures ────────────────────────────

@pytest.fixture
def session():
    """Standard 80×24 session."""
    s = VTSession("/app/vt_server.py", cols=80, rows=24)
    yield s
    s.close()


@pytest.fixture
def small_session():
    """Compact 10×8 session for targeted tests."""
    s = VTSession("/app/vt_server.py", cols=10, rows=8)
    yield s
    s.close()


# ──────────────────────────── Protocol basics ────────────────────

class TestProtocolBasics:
    """Verify basic DCS response framing and DECRQCRA checksum."""

    def test_empty_screen(self, session):
        cs = session.decrqcra(1, 1, 24, 80)
        assert cs == 0, "Empty screen must checksum to 0"

    def test_single_character(self, session):
        session.cup(1, 1)
        session.write_text("A")
        assert session.decrqcra(1, 1, 1, 1) == 65

    def test_row_of_characters(self, session):
        session.cup(1, 1)
        session.write_text("Hello")
        expected = sum(ord(c) for c in "Hello")
        assert session.decrqcra(1, 1, 1, 5) == expected

    def test_partial_rectangle(self, session):
        session.cup(1, 1)
        session.write_text("ABCDE")
        # Checksum only cols 2–4
        expected = ord("B") + ord("C") + ord("D")
        assert session.decrqcra(1, 2, 1, 4) == expected

    def test_modulo_65536(self, session):
        # Fill 80×24 with '~' (126).  80*24*126 = 241920
        for r in range(1, 25):
            session.cup(r, 1)
            session.write_text("~" * 80)
        cs = session.decrqcra(1, 1, 24, 80)
        assert cs == (80 * 24 * 126) % 65536


# ──────────────────────── DECCRA snapshot semantics ──────────────

class TestDeccra:
    """DECCRA must snapshot source before writing to destination."""

    def test_non_overlapping(self, small_session):
        s = small_session
        s.cup(1, 1); s.write_text("AB")
        s.cup(2, 1); s.write_text("CD")
        # Copy (1,1)–(2,2) to (3,1)
        s.deccra(1, 1, 2, 2, 1, 3, 1, 1)
        assert s.decrqcra(3, 1, 3, 2) == ord("A") + ord("B")
        assert s.decrqcra(4, 1, 4, 2) == ord("C") + ord("D")

    def test_overlapping_shift_right(self, small_session):
        s = small_session
        s.cup(1, 1); s.write_text("AB")
        s.cup(2, 1); s.write_text("CD")
        # Copy (1,1)–(2,2) to (1,2) — shift right 1 col
        s.deccra(1, 1, 2, 2, 1, 1, 2, 1)
        # Row 1: A A B ...
        assert s.decrqcra(1, 1, 1, 3) == ord("A") + ord("A") + ord("B")
        # Row 2: C C D ...
        assert s.decrqcra(2, 1, 2, 3) == ord("C") + ord("C") + ord("D")

    def test_overlapping_shift_down(self, small_session):
        s = small_session
        s.cup(1, 1); s.write_text("X")
        s.cup(2, 1); s.write_text("Y")
        s.cup(3, 1); s.write_text("Z")
        # Copy (1,1)–(3,1) to (2,1) — shift down 1 row
        s.deccra(1, 1, 3, 1, 1, 2, 1, 1)
        assert s.decrqcra(1, 1, 1, 1) == ord("X")
        assert s.decrqcra(2, 1, 2, 1) == ord("X")
        assert s.decrqcra(3, 1, 3, 1) == ord("Y")
        assert s.decrqcra(4, 1, 4, 1) == ord("Z")

    def test_full_esctest2_overlap(self, session):
        """Reproduce the exact esctest2 DECCRA overlapping test case."""
        s = session
        s.cup(1, 1); s.write_text("abcdefgh")
        s.cup(2, 1); s.write_text("ijklmnop")
        s.cup(3, 1); s.write_text("qrstuvwx")
        s.cup(4, 1); s.write_text("yz012345")
        s.cup(5, 1); s.write_text("ABCDEFGH")
        s.cup(6, 1); s.write_text("IJKLMNOP")
        s.cup(7, 1); s.write_text("QRSTUVWX")
        s.cup(8, 1); s.write_text("YZ6789!@")

        s.deccra(2, 2, 4, 4, 1, 3, 3, 1)

        # Row 3 → q r j k l v w x
        assert s.decrqcra(3, 1, 3, 8) == sum(ord(c) for c in "qrjklvwx")
        # Row 4 → y z r s t 3 4 5
        assert s.decrqcra(4, 1, 4, 8) == sum(ord(c) for c in "yzrst345")
        # Row 5 → A B z 0 1 F G H
        assert s.decrqcra(5, 1, 5, 8) == sum(ord(c) for c in "ABz01FGH")


# ──────────────────────── Scroll regions ─────────────────────────

class TestScrollRegion:
    """Test DECSTBM scroll region with IND and RI."""

    def test_ind_at_bottom_margin(self, small_session):
        s = small_session
        for i, ch in enumerate("ABCDEF", 1):
            s.cup(i, 1)
            s.write_text(ch)
        s.decstbm(2, 5)
        s.cup(5, 1)
        s.ind()
        s.decstbm()

        assert s.decrqcra(1, 1, 1, 1) == ord("A")  # outside, unchanged
        assert s.decrqcra(2, 1, 2, 1) == ord("C")  # was row 3
        assert s.decrqcra(3, 1, 3, 1) == ord("D")  # was row 4
        assert s.decrqcra(4, 1, 4, 1) == ord("E")  # was row 5
        assert s.decrqcra(5, 1, 5, 1) == 0          # new blank
        assert s.decrqcra(6, 1, 6, 1) == ord("F")  # outside, unchanged

    def test_ri_at_top_margin(self, small_session):
        s = small_session
        for i, ch in enumerate("ABCDEF", 1):
            s.cup(i, 1)
            s.write_text(ch)
        s.decstbm(2, 5)
        s.cup(2, 1)
        s.ri()
        s.decstbm()

        assert s.decrqcra(1, 1, 1, 1) == ord("A")  # unchanged
        assert s.decrqcra(2, 1, 2, 1) == 0          # blank inserted
        assert s.decrqcra(3, 1, 3, 1) == ord("B")  # was row 2
        assert s.decrqcra(4, 1, 4, 1) == ord("C")  # was row 3
        assert s.decrqcra(5, 1, 5, 1) == ord("D")  # was row 4 (E lost)
        assert s.decrqcra(6, 1, 6, 1) == ord("F")  # unchanged

    def test_ind_not_at_margin(self, small_session):
        s = small_session
        s.cup(1, 1); s.write_text("X")
        s.cup(2, 1); s.write_text("Y")
        s.decstbm(1, 8)
        s.cup(1, 1)
        s.ind()   # not at bottom margin → just move down
        s.write_text("Z")
        s.decstbm()
        # Z overwrites Y at row 2
        assert s.decrqcra(2, 1, 2, 1) == ord("Z")

    def test_decstbm_homes_cursor(self, small_session):
        s = small_session
        s.cup(3, 5)
        s.decstbm(2, 4)
        # DECSTBM must home cursor to (1,1)
        s.write_text("H")
        s.decstbm()
        assert s.decrqcra(1, 1, 1, 1) == ord("H")


# ──────────────────────── Origin mode ────────────────────────────

class TestOriginMode:
    """Test DECOM origin mode coordinate transformation."""

    def test_cup_in_origin_mode(self, small_session):
        s = small_session
        s.decstbm(2, 4)
        s.decset_decom()
        s.cup(1, 1)
        s.write_text("X")
        s.decreset_decom()
        s.decstbm()
        # X at absolute row 2, col 1
        assert s.decrqcra(2, 1, 2, 1) == ord("X")
        assert s.decrqcra(1, 1, 1, 1) == 0

    def test_cup_row2_in_origin_mode(self, small_session):
        s = small_session
        s.decstbm(2, 4)
        s.decset_decom()
        s.cup(2, 3)
        s.write_text("Q")
        s.decreset_decom()
        s.decstbm()
        # Q at absolute row 3, col 3
        assert s.decrqcra(3, 3, 3, 3) == ord("Q")

    def test_origin_mode_multiple_writes(self, small_session):
        s = small_session
        s.decstbm(3, 6)
        s.decset_decom()
        s.cup(1, 1); s.write_text("AB")
        s.cup(2, 1); s.write_text("CD")
        s.decreset_decom()
        s.decstbm()
        # Absolute row 3, cols 1-2
        assert s.decrqcra(3, 1, 3, 2) == ord("A") + ord("B")
        # Absolute row 4, cols 1-2
        assert s.decrqcra(4, 1, 4, 2) == ord("C") + ord("D")


# ──────────────────────── DECFRA / DECERA ────────────────────────

class TestDecfraDecera:
    """Test rectangle fill and erase operations."""

    def test_decfra_basic(self, small_session):
        s = small_session
        s.decfra(ord("#"), 2, 3, 4, 7)
        # 3 rows × 5 cols filled with '#'
        assert s.decrqcra(2, 3, 4, 7) == 3 * 5 * ord("#")

    def test_decfra_preserves_outside(self, small_session):
        s = small_session
        s.cup(1, 1); s.write_text("ABCDEFGHIJ")
        s.decfra(ord("*"), 1, 3, 1, 5)
        assert s.decrqcra(1, 1, 1, 2) == ord("A") + ord("B")
        assert s.decrqcra(1, 3, 1, 5) == 3 * ord("*")
        assert s.decrqcra(1, 6, 1, 10) == sum(
            ord(c) for c in "FGHIJ"
        )

    def test_decera_basic(self, small_session):
        s = small_session
        s.cup(1, 1); s.write_text("ABCDEFGHIJ")
        s.cup(2, 1); s.write_text("KLMNOPQRST")
        s.decera(1, 3, 2, 6)
        assert s.decrqcra(1, 3, 2, 6) == 0
        assert s.decrqcra(1, 1, 1, 2) == ord("A") + ord("B")

    def test_ed_clears_all(self, small_session):
        s = small_session
        s.cup(1, 1); s.write_text("HELLO")
        s.ed(2)
        assert s.decrqcra(1, 1, 8, 10) == 0


# ──────────────────── Custom dimensions (anti-cheat) ─────────────

class TestCustomDimensions:
    """Use non-standard screen size to prevent hardcoding."""

    def test_20x10_operations(self):
        s = VTSession("/app/vt_server.py", cols=20, rows=10)
        try:
            s.cup(1, 1)
            s.write_text("Hello")
            assert s.decrqcra(1, 1, 1, 5) == sum(ord(c) for c in "Hello")

            s.decfra(ord("*"), 1, 1, 10, 20)
            cs = s.decrqcra(1, 1, 10, 20)
            assert cs == (10 * 20 * ord("*")) % 65536

            s.decera(3, 5, 7, 15)
            remaining = (10 * 20 - 5 * 11) * ord("*")
            cs = s.decrqcra(1, 1, 10, 20)
            assert cs == remaining % 65536
        finally:
            s.close()


# ──────────────────── Compound multi-operation scenario ──────────

class TestCompoundScenario:
    """Multi-operation sequences testing subsystem interactions."""

    def test_scroll_then_deccra(self, small_session):
        s = small_session
        s.cup(1, 1); s.write_text("ABCDEFGHIJ")
        s.cup(2, 1); s.write_text("KLMNOPQRST")
        s.cup(3, 1); s.write_text("UVWXYZ0123")
        s.cup(4, 1); s.write_text("4567890abc")

        # Scroll rows 2-3
        s.decstbm(2, 3)
        s.cup(3, 1)
        s.ind()
        s.decstbm()

        # After scroll: row 1 unchanged, row 2 ← row 3, row 3 blank, row 4 unchanged
        assert s.decrqcra(1, 1, 1, 10) == sum(ord(c) for c in "ABCDEFGHIJ")
        assert s.decrqcra(2, 1, 2, 10) == sum(ord(c) for c in "UVWXYZ0123")
        assert s.decrqcra(3, 1, 3, 10) == 0
        assert s.decrqcra(4, 1, 4, 10) == sum(ord(c) for c in "4567890abc")

        # Fill blank row and copy
        s.decfra(ord("@"), 3, 1, 3, 10)
        s.deccra(2, 1, 3, 5, 1, 1, 6, 1)

        # Row 1 cols 6-10 ← source row 2 cols 1-5 (UVWXY)
        assert s.decrqcra(1, 1, 1, 10) == sum(
            ord(c) for c in "ABCDEUVWXY"
        )
        # Row 2 cols 6-10 ← source row 3 cols 1-5 (@@@@@)
        assert s.decrqcra(2, 6, 2, 10) == 5 * ord("@")

    def test_origin_scroll_verify(self, small_session):
        """Origin mode write → scroll → checksum."""
        s = small_session
        # Write in origin mode inside margins 3-6
        s.decstbm(3, 6)
        s.decset_decom()
        s.cup(1, 1); s.write_text("WW")
        s.cup(2, 1); s.write_text("XX")
        s.cup(3, 1); s.write_text("YY")
        s.cup(4, 1); s.write_text("ZZ")
        s.decreset_decom()
        s.decstbm()

        # Abs rows 3-6 should have WW XX YY ZZ
        assert s.decrqcra(3, 1, 3, 2) == 2 * ord("W")
        assert s.decrqcra(6, 1, 6, 2) == 2 * ord("Z")

        # Now scroll within those margins
        s.decstbm(3, 6)
        s.cup(6, 1)
        s.ind()
        s.decstbm()

        # After scroll: abs row 3 ← XX, row 4 ← YY, row 5 ← ZZ, row 6 blank
        assert s.decrqcra(3, 1, 3, 2) == 2 * ord("X")
        assert s.decrqcra(4, 1, 4, 2) == 2 * ord("Y")
        assert s.decrqcra(5, 1, 5, 2) == 2 * ord("Z")
        assert s.decrqcra(6, 1, 6, 2) == 0
