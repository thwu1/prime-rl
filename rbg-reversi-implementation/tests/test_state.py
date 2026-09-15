"""
Tests for 6x6 Reversi RBG game description.
Verifies the agent's /app/reversi6x6.rbg produces correct perft counts
by comparing against an independent Python reference implementation.
"""

import subprocess
import os
import re
import pytest

# ============================================================
# Reference 6x6 Reversi implementation (ground truth)
# ============================================================

EMPTY = 0
BLACK = 1
WHITE = 2
SIZE = 6

DIRECTIONS = [(-1, -1), (-1, 0), (-1, 1),
              (0, -1),           (0, 1),
              (1, -1),  (1, 0),  (1, 1)]


def make_initial_board():
    board = [[EMPTY] * SIZE for _ in range(SIZE)]
    mid = SIZE // 2
    board[mid - 1][mid - 1] = WHITE
    board[mid - 1][mid] = BLACK
    board[mid][mid - 1] = BLACK
    board[mid][mid] = WHITE
    return board


def _flips_in_dir(board, r, c, dr, dc, player, opponent):
    """Check whether placing player at (r,c) brackets opponent pieces in direction (dr,dc)."""
    nr, nc = r + dr, c + dc
    found_opponent = False
    while 0 <= nr < SIZE and 0 <= nc < SIZE:
        if board[nr][nc] == opponent:
            found_opponent = True
            nr += dr
            nc += dc
        elif board[nr][nc] == player:
            return found_opponent
        else:
            return False
    return False


def get_legal_moves(board, player):
    opponent = 3 - player
    moves = []
    for r in range(SIZE):
        for c in range(SIZE):
            if board[r][c] != EMPTY:
                continue
            for dr, dc in DIRECTIONS:
                if _flips_in_dir(board, r, c, dr, dc, player, opponent):
                    moves.append((r, c))
                    break
    return moves


def apply_move(board, r, c, player):
    opponent = 3 - player
    new_board = [row[:] for row in board]
    new_board[r][c] = player
    for dr, dc in DIRECTIONS:
        if _flips_in_dir(board, r, c, dr, dc, player, opponent):
            nr, nc = r + dr, c + dc
            while new_board[nr][nc] == opponent:
                new_board[nr][nc] = player
                nr += dr
                nc += dc
    return new_board


def perft(board, current_player, depth):
    """
    RBG-style perft for Reversi.

    Semantics (matching rbg2cpp perft behaviour):
    - Each player move (including a forced pass) decrements depth.
    - KEEPER game-end checks do NOT affect depth (transparent).
    - A position at depth == 0 is a leaf and counts as 1.
    - A game that terminates (KEEPER finds no moves for either player)
      at depth > 0 is NOT counted as a leaf.
    """
    if depth == 0:
        return 1

    other = 3 - current_player
    moves = get_legal_moves(board, current_player)

    if not moves:
        # Player must pass (no legal placements).
        other_moves = get_legal_moves(board, other)
        if not other_moves:
            # Neither player can move -> KEEPER terminates the game.
            # The pass consumed one depth unit: terminal at depth-1.
            return 1 if depth == 1 else 0
        # Pass: depth decrements, board unchanged, turn passes.
        return perft(board, other, depth - 1)

    total = 0
    for r, c in moves:
        new_board = apply_move(board, r, c, current_player)
        # KEEPER game-end check after the move:
        new_other = get_legal_moves(new_board, other)
        new_current = get_legal_moves(new_board, current_player)
        if not new_other and not new_current:
            # Game terminates at depth-1.
            if depth == 1:
                total += 1
        else:
            total += perft(new_board, other, depth - 1)
    return total


def compute_reference_perfts(max_depth=4):
    board = make_initial_board()
    return {d: perft(board, BLACK, d) for d in range(1, max_depth + 1)}


# ============================================================
# RBG compilation + perft binary builder
# ============================================================

WORK_DIR = "/tmp/rbg_perft_test"
RBG2CPP = "/app/rbg/rbg2cpp/bin/rbg2cpp"
PERFT_SRC = "/app/rbg/rbg2cpp/test/perft.cpp"
RBG_FILE = "/app/reversi6x6.rbg"


def _build_perft_binary():
    """Compile the agent's .rbg file and link the perft test. Returns binary path."""
    os.makedirs(WORK_DIR, exist_ok=True)

    # 1. Compile .rbg -> reasoner.{hpp,cpp}
    r = subprocess.run(
        [RBG2CPP, "-o", "reasoner", RBG_FILE],
        cwd=WORK_DIR, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, (
        f"rbg2cpp compilation failed (exit {r.returncode}):\n"
        f"--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"
    )

    # 2. Build perft binary
    steps = [
        ["g++", "-std=c++23", "-O2", "-c", "reasoner.cpp", "-o", "reasoner.o"],
        ["g++", "-std=c++23", "-O2", "-I" + WORK_DIR, "-c", PERFT_SRC, "-o", "perft.o"],
        ["g++", "-std=c++23", "-O2", "reasoner.o", "perft.o", "-o", "perft_test"],
    ]
    for cmd in steps:
        r = subprocess.run(
            cmd, cwd=WORK_DIR, capture_output=True, text=True, timeout=120,
        )
        assert r.returncode == 0, (
            f"Build step failed ({' '.join(cmd)}):\n"
            f"--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"
        )

    return os.path.join(WORK_DIR, "perft_test")


def _run_perft(binary, depth):
    """Run the compiled perft binary at a given depth and return the leaf count."""
    r = subprocess.run(
        [binary, str(depth)],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"perft_test exited {r.returncode}:\n{r.stdout}\n{r.stderr}"
    m = re.search(r"perft:\s*(\d+)", r.stdout)
    assert m, f"Could not parse perft count from output:\n{r.stdout}"
    return int(m.group(1))


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def perft_binary():
    """Build the perft binary once for all tests in this module."""
    return _build_perft_binary()


@pytest.fixture(scope="module")
def reference():
    """Compute reference perft values once."""
    return compute_reference_perfts(4)


# ============================================================
# Tests
# ============================================================

class TestRBGFileExists:
    def test_file_exists(self):
        assert os.path.isfile(RBG_FILE), f"{RBG_FILE} not found"


class TestCompilation:
    def test_rbg2cpp_compiles(self):
        """The .rbg file must compile to C++ without errors."""
        os.makedirs(WORK_DIR, exist_ok=True)
        r = subprocess.run(
            [RBG2CPP, "-o", "reasoner", RBG_FILE],
            cwd=WORK_DIR, capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, f"rbg2cpp failed:\n{r.stderr}"

    def test_cpp_builds(self, perft_binary):
        """The generated C++ code must compile and link successfully."""
        assert os.path.isfile(perft_binary), "perft_test binary not created"


class TestPerftValues:
    def test_perft_depth_1(self, perft_binary, reference):
        actual = _run_perft(perft_binary, 1)
        expected = reference[1]
        assert actual == expected, (
            f"Perft depth 1 mismatch: got {actual}, expected {expected}"
        )

    def test_perft_depth_2(self, perft_binary, reference):
        actual = _run_perft(perft_binary, 2)
        expected = reference[2]
        assert actual == expected, (
            f"Perft depth 2 mismatch: got {actual}, expected {expected}"
        )

    def test_perft_depth_3(self, perft_binary, reference):
        actual = _run_perft(perft_binary, 3)
        expected = reference[3]
        assert actual == expected, (
            f"Perft depth 3 mismatch: got {actual}, expected {expected}"
        )

    def test_perft_depth_4(self, perft_binary, reference):
        actual = _run_perft(perft_binary, 4)
        expected = reference[4]
        assert actual == expected, (
            f"Perft depth 4 mismatch: got {actual}, expected {expected}"
        )
