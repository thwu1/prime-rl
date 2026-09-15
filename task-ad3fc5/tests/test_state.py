
"""
Tests for the HSM (Hierarchical State Machine) dispatch engine.

Verifies correct initialization, event dispatch, state transitions,
entry/exit action ordering, guard conditions, memory safety (valgrind),
and undefined behavior (AddressSanitizer / UBSan).
"""

import subprocess
import os
import pytest


def run_hsm(commands):
    """Run the HSM test binary with the given command sequence.

    Returns a list of output lines (one per command).
    """
    binary = "/app/hsm_test"
    assert os.path.isfile(binary), f"Binary not found: {binary}"

    input_str = "\n".join(commands) + "\n"
    result = subprocess.run(
        [binary],
        input=input_str,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Binary exited with code {result.returncode}: {result.stderr}"
    lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    return lines


class TestInitialization:
    """Test HSM initialization via the top-most initial transition."""

    def test_init_enters_correct_states(self):
        """Initial pseudostate -> r2: must enter r, r2, drill to r211."""
        out = run_hsm(["INIT", "STATE"])
        assert out[0] == "top-INIT;r-ENTRY;r2-ENTRY;r2-INIT;r21-ENTRY;r211-ENTRY;"
        assert out[1] == "r211"


class TestSelfTransition:
    """Test self-transitions (source == target)."""

    def test_self_transition_on_parent(self):
        """P from r211 -> handled by r21, self-transition on r21."""
        out = run_hsm(["INIT", "P"])
        assert out[1] == "r21-P;r211-EXIT;r21-EXIT;r21-ENTRY;r21-INIT;r211-ENTRY;"

    def test_self_transition_bubbled(self):
        """P from r11 -> handled by r1, self-transition on r1."""
        out = run_hsm(["INIT", "V", "P"])
        assert out[2] == "r1-P;r11-EXIT;r1-EXIT;r1-ENTRY;r1-INIT;r11-ENTRY;"


class TestParentChildTransition:
    """Test transitions between parent and child states."""

    def test_parent_to_child(self):
        """Q from r211 -> handled by r21, transition r21->r211."""
        out = run_hsm(["INIT", "Q"])
        assert out[1] == "r21-Q;r211-EXIT;r211-ENTRY;"

    def test_child_to_parent(self):
        """S from r211 -> transition r211->r21, then r21 drills to r211."""
        out = run_hsm(["INIT", "S"])
        assert out[1] == "r211-S;r211-EXIT;r21-INIT;r211-ENTRY;"


class TestSiblingTransition:
    """Test transitions between sibling states (same superstate)."""

    def test_sibling_r11_to_r12(self):
        """W from r11 -> transition to r12 (siblings under r1)."""
        out = run_hsm(["INIT", "V", "W"])
        assert out[2] == "r11-W;r11-EXIT;r12-ENTRY;"

    def test_sibling_r12_to_r11(self):
        """W from r12 -> transition to r11 (siblings under r1)."""
        out = run_hsm(["INIT", "V", "W", "W"])
        assert out[3] == "r12-W;r12-EXIT;r11-ENTRY;"

    def test_cross_hierarchy_siblings(self):
        """R from r11 -> handled by r1, transition r1->r2 (siblings under r)."""
        out = run_hsm(["INIT", "V", "R"])
        assert out[2] == "r1-R;r11-EXIT;r1-EXIT;r2-ENTRY;r2-INIT;r21-ENTRY;r211-ENTRY;"


class TestCrossHierarchyTransition:
    """Test transitions across different branches of the hierarchy."""

    def test_cross_v_from_r211(self):
        """V from r211 -> handled by r21, transition r21->r1."""
        out = run_hsm(["INIT", "V"])
        assert out[1] == "r21-V;r211-EXIT;r21-EXIT;r2-EXIT;r1-ENTRY;r1-INIT;r11-ENTRY;"

    def test_deep_cross_down(self):
        """U from r11 -> handled by r1, transition r1->r211."""
        out = run_hsm(["INIT", "V", "U"])
        assert out[2] == "r1-U;r11-EXIT;r1-EXIT;r2-ENTRY;r21-ENTRY;r211-ENTRY;"

    def test_deep_cross_up(self):
        """U from r211 -> handled by r2, transition r2->r11."""
        out = run_hsm(["INIT", "V", "R", "U"])
        assert out[3] == "r2-U;r211-EXIT;r21-EXIT;r2-EXIT;r1-ENTRY;r11-ENTRY;"

    def test_cross_from_r12(self):
        """R from r12 -> transition r12->r21."""
        out = run_hsm(["INIT", "V", "W", "R"])
        assert out[3] == "r12-R;r12-EXIT;r1-EXIT;r2-ENTRY;r21-ENTRY;r21-INIT;r211-ENTRY;"


class TestAncestorDescendantTransition:
    """Test transitions between ancestor and descendant states."""

    def test_deep_exit_to_ancestor(self):
        """W from r211 -> transition r211->r (target is ancestor)."""
        out = run_hsm(["INIT", "W"])
        assert out[1] == "r211-W;r211-EXIT;r21-EXIT;r2-EXIT;r-INIT;r1-ENTRY;r1-INIT;r11-ENTRY;"

    def test_ancestor_to_descendant(self):
        """T from r11 -> handled by r, transition r->r11."""
        out = run_hsm(["INIT", "W", "T"])
        assert out[2] == "r-T;r11-EXIT;r1-EXIT;r1-ENTRY;r11-ENTRY;"


class TestGuardCondition:
    """Test guard conditions that cause UNHANDLED propagation."""

    def test_guard_s_from_r11_foo_zero(self):
        """S from r11 with foo=0: r11 guard fails, parent r1 handles."""
        out = run_hsm(["INIT", "V", "S"])
        assert out[2] == "r1-S;r11-EXIT;r1-EXIT;r-INIT;r1-ENTRY;r1-INIT;r11-ENTRY;"

    def test_guard_s_from_r11_foo_one(self):
        """S from r11 with foo=1: r11 handles."""
        out = run_hsm(["INIT", "V", "S", "S"])
        assert out[2] == "r1-S;r11-EXIT;r1-EXIT;r-INIT;r1-ENTRY;r1-INIT;r11-ENTRY;"
        assert out[3] == "r11-S;r11-EXIT;r1-INIT;r11-ENTRY;"

    def test_guard_x_toggles(self):
        """X from r211: r2 handles when foo=0, r handles when foo=1."""
        out = run_hsm(["INIT", "X", "X"])
        assert out[1] == "r2-X;"
        assert out[2] == "r-X;"


class TestInternalTransition:
    """Test internal transitions (event handled without state change)."""

    def test_internal_x_in_r1(self):
        """X from r11 -> handled by r1 as internal."""
        out = run_hsm(["INIT", "V", "X", "STATE"])
        assert out[2] == "r1-X;"
        assert out[3] == "r11"


class TestFullSequence:
    """Comprehensive multi-step test covering all transition types."""

    def test_long_sequence(self):
        """Full 17-step sequence exercising all transition categories."""
        commands = [
            "INIT",   # 0: initialize
            "P",      # 1: self-transition (r21)
            "Q",      # 2: parent-to-child (r21->r211)
            "S",      # 3: child-to-parent (r211->r21)
            "V",      # 4: cross hierarchy (r21->r1)
            "W",      # 5: sibling (r11->r12)
            "W",      # 6: sibling back (r12->r11)
            "P",      # 7: self on parent (r1)
            "R",      # 8: sibling cross (r1->r2)
            "U",      # 9: deep cross up (r2->r11)
            "U",      # 10: deep cross down (r1->r211)
            "X",      # 11: guard X (r2 handles, foo=0->1)
            "X",      # 12: guard X (r handles, foo=1->0)
            "W",      # 13: deep exit (r211->r)
            "T",      # 14: ancestor-to-desc (r->r11)
            "S",      # 15: guard S (r1 handles, foo=0->1)
            "S",      # 16: guard S (r11 handles, foo=1->0)
        ]
        expected = [
            "top-INIT;r-ENTRY;r2-ENTRY;r2-INIT;r21-ENTRY;r211-ENTRY;",
            "r21-P;r211-EXIT;r21-EXIT;r21-ENTRY;r21-INIT;r211-ENTRY;",
            "r21-Q;r211-EXIT;r211-ENTRY;",
            "r211-S;r211-EXIT;r21-INIT;r211-ENTRY;",
            "r21-V;r211-EXIT;r21-EXIT;r2-EXIT;r1-ENTRY;r1-INIT;r11-ENTRY;",
            "r11-W;r11-EXIT;r12-ENTRY;",
            "r12-W;r12-EXIT;r11-ENTRY;",
            "r1-P;r11-EXIT;r1-EXIT;r1-ENTRY;r1-INIT;r11-ENTRY;",
            "r1-R;r11-EXIT;r1-EXIT;r2-ENTRY;r2-INIT;r21-ENTRY;r211-ENTRY;",
            "r2-U;r211-EXIT;r21-EXIT;r2-EXIT;r1-ENTRY;r11-ENTRY;",
            "r1-U;r11-EXIT;r1-EXIT;r2-ENTRY;r21-ENTRY;r211-ENTRY;",
            "r2-X;",
            "r-X;",
            "r211-W;r211-EXIT;r21-EXIT;r2-EXIT;r-INIT;r1-ENTRY;r1-INIT;r11-ENTRY;",
            "r-T;r11-EXIT;r1-EXIT;r1-ENTRY;r11-ENTRY;",
            "r1-S;r11-EXIT;r1-EXIT;r-INIT;r1-ENTRY;r1-INIT;r11-ENTRY;",
            "r11-S;r11-EXIT;r1-INIT;r11-ENTRY;",
        ]
        out = run_hsm(commands)
        assert len(out) == len(expected), (
            f"Expected {len(expected)} output lines, got {len(out)}\n"
            f"Output: {out}"
        )
        for i, (got, want) in enumerate(zip(out, expected)):
            assert got == want, (
                f"Step {i} ({commands[i]}): "
                f"expected '{want}', got '{got}'"
            )


class TestTraceReference:
    """Verify output matches the reference trace files."""

    def test_matches_reference_traces(self):
        """Binary output for /app/traces/input.txt must match expected.txt exactly."""
        binary = "/app/hsm_test"
        assert os.path.isfile(binary), f"Binary not found: {binary}"

        with open("/app/traces/input.txt") as f:
            input_str = f.read()
        with open("/app/traces/expected.txt") as f:
            expected = f.read().strip()

        result = subprocess.run(
            [binary],
            input=input_str,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Binary exited with code {result.returncode}"
        actual = result.stdout.strip()
        assert actual == expected, (
            f"Trace output does not match reference.\n"
            f"Run: diff <(cat /app/traces/input.txt | /app/hsm_test) "
            f"/app/traces/expected.txt\nto see differences."
        )


class TestMemorySafety:
    """Verify implementation has no memory errors under valgrind."""

    def test_valgrind_clean(self):
        """Full test sequence must produce zero valgrind errors."""
        binary = "/app/hsm_test"
        assert os.path.isfile(binary), f"Binary not found: {binary}"

        with open("/app/traces/input.txt") as f:
            input_str = f.read()

        result = subprocess.run(
            ["valgrind", "--error-exitcode=42", "--leak-check=full",
             "--errors-for-leak-kinds=definite,possible", binary],
            input=input_str,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 42, (
            f"Valgrind detected memory errors:\n{result.stderr}"
        )
        assert result.returncode == 0, (
            f"Binary under valgrind exited with code {result.returncode}:\n"
            f"{result.stderr}"
        )


class TestSanitizerClean:
    """Verify implementation is clean under UBSan (undefined behavior sanitizer)."""

    def test_ubsan_clean(self):
        """Build with UBSan and run the full test sequence without errors."""
        # Build a separate binary with UBSan only. We avoid ASAN here
        # because ASAN requires specific shared-library setup that varies
        # across environments. UBSan catches undefined behavior, integer
        # overflow, alignment errors, etc. Valgrind already covers
        # memory safety (leaks, out-of-bounds, use-after-free).
        build = subprocess.run(
            ["gcc", "-std=c11", "-Wall", "-Wextra",
             "-fsanitize=undefined",
             "-fno-sanitize-recover=all",
             "-g", "-O0",
             "-o", "/app/hsm_test_ubsan",
             "/app/main.c", "/app/hsm.c", "/app/test_sm.c"],
            capture_output=True,
            text=True,
            cwd="/app",
            timeout=30,
        )
        assert build.returncode == 0, (
            f"UBSan build failed:\n{build.stderr}"
        )

        with open("/app/traces/input.txt") as f:
            input_str = f.read()

        result = subprocess.run(
            ["/app/hsm_test_ubsan"],
            input=input_str,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"UBSan detected undefined behavior (exit code {result.returncode}):\n"
            f"stderr:\n{result.stderr}\n"
            f"stdout:\n{result.stdout}"
        )
