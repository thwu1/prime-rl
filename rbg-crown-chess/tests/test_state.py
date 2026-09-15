
"""
Tests for the Crown game RBG implementation.
Verifies the agent's /app/crown.rbg against a Python reference implementation.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

# Import the reference implementation
sys.path.insert(0, os.path.dirname(__file__))
from reference_game import compute_reference_perft, perft, INITIAL_BOARD, WHITE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RBG2CPP = "/opt/rbg/rbg2cpp/bin/rbg2cpp"
CROWN_RBG = "/app/crown.rbg"


def compile_and_perft(rbg_path, depth):
    """Compile an RBG file and run perft at the given depth. Returns leaves count."""
    rbg_abs = os.path.abspath(rbg_path)
    with tempfile.TemporaryDirectory() as tmpdir:
        # Step 1: RBG -> C++ reasoner
        # Use cwd=tmpdir and -o reasoner (relative, no path separators)
        # because rbg2cpp derives C++ namespace and header guards from the
        # -o path.  An absolute path like /tmp/xxx/reasoner produces invalid
        # C++ identifiers that contain '/' characters.
        result = subprocess.run(
            [RBG2CPP, "-Whide", "-o", "reasoner", rbg_abs],
            capture_output=True, text=True, timeout=60,
            cwd=tmpdir
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"rbg2cpp compilation failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )

        # Step 2: C++ compilation
        shutil.copy("/opt/rbg/rbg2cpp/test/perft.cpp", tmpdir)

        result = subprocess.run(
            ["g++", "-O3", "-std=c++23", "-c", "-o", "reasoner.o", "reasoner.cpp"],
            capture_output=True, text=True, timeout=120,
            cwd=tmpdir
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"C++ compilation of reasoner failed:\n{result.stderr}"
            )

        result = subprocess.run(
            ["g++", "-O3", "-std=c++23", "-o", "perft_test", "reasoner.o", "perft.cpp"],
            capture_output=True, text=True, timeout=120,
            cwd=tmpdir
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"C++ linking failed:\n{result.stderr}"
            )

        # Step 3: Run perft
        perft_bin = os.path.join(tmpdir, "perft_test")
        result = subprocess.run(
            [perft_bin, str(depth)],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Perft execution failed:\n{result.stdout}\n{result.stderr}"
            )

        # Parse the perft output: look for "perft: <number>"
        match = re.search(r"perft:\s*(\d+)", result.stdout)
        if not match:
            raise RuntimeError(
                f"Could not parse perft output:\n{result.stdout}"
            )
        return int(match.group(1))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def reference_perft_values():
    """Compute reference perft values once for the session."""
    return compute_reference_perft(max_depth=4)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCrownRBGExists:
    """Basic structural tests."""

    def test_file_exists(self):
        assert os.path.isfile(CROWN_RBG), (
            f"Expected RBG game file at {CROWN_RBG} but it does not exist."
        )

    def test_file_not_empty(self):
        assert os.path.getsize(CROWN_RBG) > 100, (
            f"{CROWN_RBG} exists but appears too small to be a valid game."
        )

    def test_contains_players(self):
        with open(CROWN_RBG) as f:
            content = f.read()
        assert "#players" in content, "Game file must declare #players"

    def test_contains_pieces(self):
        with open(CROWN_RBG) as f:
            content = f.read()
        assert "#pieces" in content, "Game file must declare #pieces"

    def test_contains_board(self):
        with open(CROWN_RBG) as f:
            content = f.read()
        assert "#board" in content, "Game file must declare #board"

    def test_contains_rules(self):
        with open(CROWN_RBG) as f:
            content = f.read()
        assert "#rules" in content, "Game file must declare #rules"


class TestCrownCompilation:
    """Test that the game compiles successfully."""

    def test_rbg2cpp_compilation(self):
        """The .rbg file must compile with rbg2cpp without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [RBG2CPP, "-Whide", "-o", "reasoner", os.path.abspath(CROWN_RBG)],
                capture_output=True, text=True, timeout=60,
                cwd=tmpdir
            )
            assert result.returncode == 0, (
                f"rbg2cpp failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )
            assert os.path.isfile(os.path.join(tmpdir, "reasoner.hpp")), (
                "rbg2cpp did not generate reasoner.hpp"
            )
            assert os.path.isfile(os.path.join(tmpdir, "reasoner.cpp")), (
                "rbg2cpp did not generate reasoner.cpp"
            )

    def test_cpp_compilation(self):
        """The generated C++ code must compile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                [RBG2CPP, "-Whide", "-o", "reasoner", os.path.abspath(CROWN_RBG)],
                capture_output=True, text=True, timeout=60, check=True,
                cwd=tmpdir
            )
            shutil.copy("/opt/rbg/rbg2cpp/test/perft.cpp", tmpdir)
            result = subprocess.run(
                ["g++", "-O3", "-std=c++23", "-c", "-o",
                 "reasoner.o", "reasoner.cpp"],
                capture_output=True, text=True, timeout=120,
                cwd=tmpdir
            )
            assert result.returncode == 0, (
                f"C++ compilation failed:\n{result.stderr}"
            )
            result = subprocess.run(
                ["g++", "-O3", "-std=c++23", "-o",
                 "perft_test", "reasoner.o", "perft.cpp"],
                capture_output=True, text=True, timeout=120,
                cwd=tmpdir
            )
            assert result.returncode == 0, (
                f"C++ linking failed:\n{result.stderr}"
            )


class TestCrownPerft:
    """Verify perft counts match the Python reference implementation."""

    def test_perft_depth_1(self, reference_perft_values):
        expected = reference_perft_values[1]
        actual = compile_and_perft(CROWN_RBG, 1)
        assert actual == expected, (
            f"perft(1) mismatch: got {actual}, expected {expected}"
        )

    def test_perft_depth_2(self, reference_perft_values):
        expected = reference_perft_values[2]
        actual = compile_and_perft(CROWN_RBG, 2)
        assert actual == expected, (
            f"perft(2) mismatch: got {actual}, expected {expected}"
        )

    def test_perft_depth_3(self, reference_perft_values):
        expected = reference_perft_values[3]
        actual = compile_and_perft(CROWN_RBG, 3)
        assert actual == expected, (
            f"perft(3) mismatch: got {actual}, expected {expected}"
        )

    def test_perft_depth_4(self, reference_perft_values):
        expected = reference_perft_values[4]
        actual = compile_and_perft(CROWN_RBG, 4)
        assert actual == expected, (
            f"perft(4) mismatch: got {actual}, expected {expected}"
        )


class TestReferenceConsistency:
    """Sanity-check the Python reference implementation."""

    def test_initial_move_count(self):
        """White should have exactly 10 legal moves from the initial position."""
        from reference_game import get_all_moves
        moves = get_all_moves(INITIAL_BOARD, WHITE)
        assert len(moves) == 10, (
            f"Expected 10 initial white moves, got {len(moves)}"
        )

    def test_perft_1_equals_initial_moves(self):
        """perft(1) must equal the number of initial legal moves."""
        from reference_game import get_all_moves
        moves = get_all_moves(INITIAL_BOARD, WHITE)
        p1 = perft(INITIAL_BOARD, WHITE, 1)
        assert p1 == len(moves), (
            f"perft(1)={p1} but initial move count={len(moves)}"
        )

    def test_perft_2_symmetry(self):
        """perft(2) should be 100 (10 white moves x 10 black responses each)."""
        p2 = perft(INITIAL_BOARD, WHITE, 2)
        assert p2 == 100, (
            f"perft(2)={p2}, expected 100 (symmetric opening)"
        )
