"""
Tests for the HSM dispatch engine implementation.

Verifies correct UML Statechart semantics by building the project,
running the test binary, and comparing execution traces line-by-line
against known-correct expected output.

"""

import subprocess
import pytest


# Expected output from a correct HSM dispatch engine.
# Each line corresponds to one init or dispatch operation.
EXPECTED_LINES = [
    "INIT: top-INIT;s-ENTRY;s2-ENTRY;s2-INIT;s21-ENTRY;s211-ENTRY;",
    "Signal G: s21-G;s211-EXIT;s21-EXIT;s2-EXIT;s1-ENTRY;s1-INIT;s11-ENTRY;",
    "Signal I: s1-I;",
    "Signal A: s1-A;s11-EXIT;s1-EXIT;s1-ENTRY;s1-INIT;s11-ENTRY;",
    "Signal D: s1-D;s11-EXIT;s1-EXIT;s-INIT;s1-ENTRY;s11-ENTRY;",
    "Signal D: s11-D;s11-EXIT;s1-INIT;s11-ENTRY;",
    "Signal C: s1-C;s11-EXIT;s1-EXIT;s2-ENTRY;s2-INIT;s21-ENTRY;s211-ENTRY;",
    "Signal F: s2-F;s211-EXIT;s21-EXIT;s2-EXIT;s1-ENTRY;s11-ENTRY;",
    "Signal F: s1-F;s11-EXIT;s1-EXIT;s2-ENTRY;s21-ENTRY;s211-ENTRY;",
    "Signal E: s-E;s211-EXIT;s21-EXIT;s2-EXIT;s1-ENTRY;s11-ENTRY;",
    "Signal H: s11-H;s11-EXIT;s1-EXIT;s-INIT;s1-ENTRY;s11-ENTRY;",
    "Signal B: s1-B;s11-EXIT;s11-ENTRY;",
    "Signal G: s11-G;s11-EXIT;s1-EXIT;s2-ENTRY;s21-ENTRY;s211-ENTRY;",
    "Signal I: s2-I;",
    "Signal I: s-I;",
    "Signal H: s211-H;s211-EXIT;s21-EXIT;s2-EXIT;s-INIT;s1-ENTRY;s11-ENTRY;",
    "Signal C: s1-C;s11-EXIT;s1-EXIT;s2-ENTRY;s2-INIT;s21-ENTRY;s211-ENTRY;",
    "Signal B: s21-B;s211-EXIT;s211-ENTRY;",
    "Signal D: s211-D;s211-EXIT;s21-INIT;s211-ENTRY;",
]


@pytest.fixture(scope="session")
def build_and_run():
    """Build the HSM project and run it, returning the output lines."""
    # Build
    result = subprocess.run(
        ["make", "clean", "all"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Build failed:\n{result.stderr}\n{result.stdout}"

    # Run
    result = subprocess.run(
        ["/app/qhsmtst"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Program crashed:\n{result.stderr}"

    lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
    return lines


class TestOutputLineCount:
    def test_program_produces_expected_number_of_lines(self, build_and_run):
        lines = build_and_run
        assert len(lines) == len(EXPECTED_LINES), (
            f"Expected {len(EXPECTED_LINES)} output lines, got {len(lines)}.\n"
            f"Actual output:\n" + "\n".join(lines)
        )


class TestInitialTransition:
    def test_top_most_initial_transition(self, build_and_run):
        """Init: top → s2 → (s2 init) → s211. Enters s, s2, s21, s211."""
        lines = build_and_run
        assert lines[0] == EXPECTED_LINES[0], (
            f"INIT trace mismatch:\n  got:    {lines[0]}\n  expect: {EXPECTED_LINES[0]}"
        )


class TestEventDispatches:
    @pytest.mark.parametrize("idx", range(1, len(EXPECTED_LINES)))
    def test_event_dispatch(self, build_and_run, idx):
        """Verify each event produces the correct trace output."""
        lines = build_and_run
        assert idx < len(lines), f"Missing output line at index {idx}"
        assert lines[idx] == EXPECTED_LINES[idx], (
            f"Line {idx} mismatch:\n  got:    {lines[idx]}\n  expect: {EXPECTED_LINES[idx]}"
        )


class TestCrossBranchTransition:
    def test_exits_source_branch_enters_target_branch(self, build_and_run):
        """Signal G from s211: exit s211,s21,s2 — enter s1,s11 (via init)."""
        g_line = build_and_run[1]
        assert "s211-EXIT" in g_line
        assert "s21-EXIT" in g_line
        assert "s2-EXIT" in g_line
        assert "s1-ENTRY" in g_line
        assert "s11-ENTRY" in g_line


class TestSelfTransition:
    def test_exits_and_reenters_state(self, build_and_run):
        """Signal A from s11: s1 takes self-transition — must exit and re-enter."""
        a_line = build_and_run[3]
        assert "s1-A;" in a_line, "Action must fire"
        assert "s1-EXIT" in a_line, "Self-transition must exit"
        assert "s1-ENTRY" in a_line, "Self-transition must re-enter"


class TestGuardConditions:
    def test_guard_false_propagates_to_superstate(self, build_and_run):
        """First D (foo=0): s11 guard fails → s1 handles it."""
        d1 = build_and_run[4]
        assert "s1-D;" in d1, "s1 should handle D when s11 guard fails"
        assert "s11-D;" not in d1

    def test_guard_true_handles_locally(self, build_and_run):
        """Second D (foo=1): s11 guard passes → s11 handles it."""
        d2 = build_and_run[5]
        assert "s11-D;" in d2, "s11 should handle D when guard passes"

    def test_i_signal_guard_alternation(self, build_and_run):
        """I from s211: s2 handles (foo=0→1), then s handles (foo=1→0)."""
        assert build_and_run[13].strip() == "Signal I: s2-I;"
        assert build_and_run[14].strip() == "Signal I: s-I;"


class TestInternalTransition:
    def test_no_exit_entry_actions(self, build_and_run):
        """Signal I from s11: handled by s1 internally — no exit/entry."""
        i_line = build_and_run[2]
        assert i_line.strip() == "Signal I: s1-I;"


class TestEntryExitOrder:
    def test_entry_actions_are_top_down(self, build_and_run):
        """Signal C from s11→s2: entries must be s2, s21, s211 (top-down)."""
        c_line = build_and_run[6]
        s2_pos = c_line.index("s2-ENTRY")
        s21_pos = c_line.index("s21-ENTRY")
        s211_pos = c_line.index("s211-ENTRY")
        assert s2_pos < s21_pos < s211_pos, (
            "Entry actions must be top-down: s2 before s21 before s211"
        )

    def test_exit_actions_are_bottom_up(self, build_and_run):
        """Signal F from s211: exits must be s211, s21, s2 (bottom-up)."""
        f_line = build_and_run[7]
        s211_pos = f_line.index("s211-EXIT")
        s21_pos = f_line.index("s21-EXIT")
        s2_pos = f_line.index("s2-EXIT")
        assert s211_pos < s21_pos < s2_pos, (
            "Exit actions must be bottom-up: s211 before s21 before s2"
        )


class TestParentChildTransitions:
    def test_parent_to_child_no_parent_exit(self, build_and_run):
        """Signal B from s11: s1→s11 — s1 stays active, just enter s11."""
        b_line = build_and_run[11]
        assert b_line.strip() == "Signal B: s1-B;s11-EXIT;s11-ENTRY;"

    def test_child_to_parent(self, build_and_run):
        """Signal D from s211: s211→s21 — exit s211, s21 re-inits to s211."""
        d_line = build_and_run[18]
        assert d_line.strip() == "Signal D: s211-D;s211-EXIT;s21-INIT;s211-ENTRY;"


class TestDeepTransitions:
    def test_deep_transition_from_ancestor(self, build_and_run):
        """Signal E from s211: handled by s → s11. Exits entire s2 branch."""
        e_line = build_and_run[9]
        assert "s-E;" in e_line
        assert "s211-EXIT" in e_line
        assert "s2-EXIT" in e_line
        assert "s1-ENTRY" in e_line
        assert "s11-ENTRY" in e_line

    def test_deep_transition_to_ancestor(self, build_and_run):
        """Signal H from s211: s211→s. Exits s211,s21,s2; s re-inits."""
        h_line = build_and_run[15]
        assert "s211-H;" in h_line
        assert "s211-EXIT" in h_line
        assert "s21-EXIT" in h_line
        assert "s2-EXIT" in h_line
        assert "s-INIT" in h_line
