"""
Tests for the tmux-based TUI testing harness.

Verifies that TUISession correctly manages tmux sessions, captures
screen state with ANSI attribute parsing, sends keystrokes, and
implements poll-based text search.
"""

import sys
import subprocess
import time
import os

sys.path.insert(0, '/app')

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def static_session():
    """Module-scoped session running the static fixture (read-only)."""
    from tui_harness import TUISession
    sess = TUISession(
        ["python3", "/app/fixtures/static_screen.py"],
        rows=10, cols=40,
    )
    found = sess.wait_for_text("BoldRed", timeout=10.0)
    assert found, "Static fixture did not render in time"
    yield sess
    sess.close()


@pytest.fixture
def interactive_session():
    """Function-scoped session running the interactive fixture."""
    from tui_harness import TUISession
    sess = TUISession(
        ["python3", "/app/fixtures/interactive_screen.py"],
        rows=10, cols=40,
    )
    found = sess.wait_for_text("Selected: 0", timeout=10.0)
    assert found, "Interactive fixture did not render in time"
    yield sess
    sess.close()


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_session_creates_tmux_session(self):
        from tui_harness import TUISession
        sess = TUISession(
            ["python3", "-c", "import time; time.sleep(3600)"],
            rows=5, cols=20,
        )
        name = sess.session_name
        rc = subprocess.run(
            ["tmux", "has-session", "-t", name], capture_output=True,
        ).returncode
        assert rc == 0, "tmux session should exist after creation"
        sess.close()
        rc = subprocess.run(
            ["tmux", "has-session", "-t", name], capture_output=True,
        ).returncode
        assert rc != 0, "tmux session should be gone after close()"

    def test_unique_session_names(self):
        from tui_harness import TUISession
        s1 = TUISession(
            ["python3", "-c", "import time; time.sleep(3600)"],
            rows=5, cols=20,
        )
        s2 = TUISession(
            ["python3", "-c", "import time; time.sleep(3600)"],
            rows=5, cols=20,
        )
        try:
            assert s1.session_name != s2.session_name
        finally:
            s1.close()
            s2.close()


# ---------------------------------------------------------------------------
# Text content capture
# ---------------------------------------------------------------------------

class TestTextCapture:
    def test_row0_text(self, static_session):
        snap = static_session.capture()
        text = ''.join(snap['screen'][0][c]['char'] for c in range(7))
        assert text == "BoldRed"

    def test_row1_text(self, static_session):
        snap = static_session.capture()
        text = ''.join(snap['screen'][1][c]['char'] for c in range(8))
        assert text == "Green256"

    def test_row4_plain_text(self, static_session):
        snap = static_session.capture()
        text = ''.join(snap['screen'][4][c]['char'] for c in range(9))
        assert text == "PlainText"


# ---------------------------------------------------------------------------
# Attribute detection
# ---------------------------------------------------------------------------

class TestAttributes:
    def test_bold_detected(self, static_session):
        snap = static_session.capture()
        for c in range(7):
            assert snap['screen'][0][c]['bold'] is True, (
                f"Cell (0,{c}) should be bold"
            )

    def test_underline_detected(self, static_session):
        snap = static_session.capture()
        for c in range(10):
            assert snap['screen'][2][c]['underline'] is True, (
                f"Cell (2,{c}) should be underlined"
            )

    def test_reverse_detected(self, static_session):
        snap = static_session.capture()
        for c in range(8):
            assert snap['screen'][3][c]['reverse'] is True, (
                f"Cell (3,{c}) should be reversed"
            )

    def test_plain_no_attributes(self, static_session):
        snap = static_session.capture()
        cell = snap['screen'][4][0]
        assert cell['bold'] is False
        assert cell['underline'] is False
        assert cell['reverse'] is False


# ---------------------------------------------------------------------------
# Color detection
# ---------------------------------------------------------------------------

class TestColors:
    def test_fg_8color_red(self, static_session):
        snap = static_session.capture()
        fg = snap['screen'][0][0]['fg']
        assert fg == 1, f"Expected fg=1 (red), got {fg}"

    def test_fg_256color_green(self, static_session):
        snap = static_session.capture()
        fg = snap['screen'][1][0]['fg']
        assert fg == 46, f"Expected fg=46, got {fg}"

    def test_bg_8color_blue(self, static_session):
        snap = static_session.capture()
        bg = snap['screen'][2][0]['bg']
        assert bg == 4, f"Expected bg=4 (blue), got {bg}"

    def test_default_colors_on_plain(self, static_session):
        snap = static_session.capture()
        cell = snap['screen'][4][0]
        assert cell['fg'] is None, f"Expected default fg, got {cell['fg']}"
        assert cell['bg'] is None, f"Expected default bg, got {cell['bg']}"


# ---------------------------------------------------------------------------
# Cursor position
# ---------------------------------------------------------------------------

class TestCursor:
    def test_static_cursor_position(self, static_session):
        snap = static_session.capture()
        assert snap['cursor']['row'] == 5, (
            f"Expected cursor row 5, got {snap['cursor']['row']}"
        )
        assert snap['cursor']['col'] == 0, (
            f"Expected cursor col 0, got {snap['cursor']['col']}"
        )

    def test_interactive_initial_cursor(self, interactive_session):
        snap = interactive_session.capture()
        assert snap['cursor']['row'] == 0, (
            f"Expected cursor row 0, got {snap['cursor']['row']}"
        )


# ---------------------------------------------------------------------------
# Snapshot format compatibility
# ---------------------------------------------------------------------------

class TestSnapshotFormat:
    def test_top_level_keys(self, static_session):
        snap = static_session.capture()
        assert snap['rows'] == 10
        assert snap['cols'] == 40
        assert 'cursor' in snap
        assert 'screen' in snap

    def test_screen_dimensions(self, static_session):
        snap = static_session.capture()
        assert len(snap['screen']) == 10, (
            f"Expected 10 rows, got {len(snap['screen'])}"
        )
        for r in range(10):
            assert len(snap['screen'][r]) == 40, (
                f"Row {r}: expected 40 cols, got {len(snap['screen'][r])}"
            )

    def test_cell_keys_match_emulator(self, static_session):
        from terminal_emulator import TerminalEmulator
        snap = static_session.capture()
        emu = TerminalEmulator(10, 40)
        ref = emu.snapshot()
        expected_keys = set(ref['screen'][0][0].keys())
        for r in range(10):
            for c in range(40):
                actual_keys = set(snap['screen'][r][c].keys())
                assert actual_keys == expected_keys, (
                    f"Cell ({r},{c}) keys {actual_keys} != {expected_keys}"
                )

    def test_empty_cell_defaults(self, static_session):
        snap = static_session.capture()
        cell = snap['screen'][9][0]
        assert cell['char'] == ' '
        assert cell['fg'] is None
        assert cell['bg'] is None
        assert cell['bold'] is False
        assert cell['underline'] is False
        assert cell['reverse'] is False


# ---------------------------------------------------------------------------
# Keyboard interaction
# ---------------------------------------------------------------------------

class TestInteraction:
    def test_send_j_updates_selection(self, interactive_session):
        interactive_session.send_keys('j')
        found = interactive_session.wait_for_text("Selected: 1", timeout=5.0)
        assert found, "Selection did not update to 1 after j"

    def test_send_k_moves_back(self, interactive_session):
        interactive_session.send_keys('j')
        assert interactive_session.wait_for_text("Selected: 1", timeout=5.0)
        interactive_session.send_keys('k')
        assert interactive_session.wait_for_text("Selected: 0", timeout=5.0)

    def test_multiple_navigations(self, interactive_session):
        for i in range(3):
            interactive_session.send_keys('j')
            expected = f"Selected: {i + 1}"
            assert interactive_session.wait_for_text(expected, timeout=5.0), \
                f"Expected '{expected}' after pressing j {i + 1} times"

    def test_reverse_on_selected_item(self, interactive_session):
        snap = interactive_session.capture()
        assert snap['screen'][0][0]['reverse'] is True, (
            "Initially selected row 0 should have reverse"
        )
        assert snap['screen'][1][0]['reverse'] is False, (
            "Non-selected row 1 should not have reverse"
        )

    def test_reverse_follows_selection(self, interactive_session):
        interactive_session.send_keys('j')
        assert interactive_session.wait_for_text("Selected: 1", timeout=5.0)
        snap = interactive_session.capture()
        assert snap['screen'][0][0]['reverse'] is False, (
            "Row 0 should lose reverse after navigating down"
        )
        assert snap['screen'][1][0]['reverse'] is True, (
            "Row 1 should gain reverse after navigating down"
        )


# ---------------------------------------------------------------------------
# wait_for_text
# ---------------------------------------------------------------------------

class TestWaitForText:
    def test_returns_true_on_existing_text(self, static_session):
        result = static_session.wait_for_text("PlainText", timeout=5.0)
        assert result is True

    def test_returns_false_on_timeout(self):
        from tui_harness import TUISession
        sess = TUISession(
            ["python3", "/app/fixtures/static_screen.py"],
            rows=10, cols=40,
        )
        try:
            assert sess.wait_for_text("BoldRed", timeout=10.0)
            result = sess.wait_for_text("NonExistentXYZ123", timeout=1.5)
            assert result is False
        finally:
            sess.close()
