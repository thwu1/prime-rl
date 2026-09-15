"""

SameGame solver validation tests.
Replays move sequences produced by /app/solver.py on a reference engine
and checks legality and score thresholds.
"""
import os
import pytest

BOARDS = [f"/app/boards/board_{i}.txt" for i in range(5)]
MOVES_FILES = [f"/tmp/moves_{i}.txt" for i in range(5)]
TOTAL_THRESHOLD = 10000
PER_BOARD_THRESHOLD = 1000
NUM_BOARDS = 5
ROWS = 15
COLS = 15


# ---------------------------------------------------------------------------
# Inline SameGame engine for tamper-proof validation
# ---------------------------------------------------------------------------
class SameGame:
    def __init__(self, grid):
        self.grid = [list(row) for row in grid]
        self.score = 0

    @classmethod
    def from_file(cls, filename):
        with open(filename) as f:
            lines = [line.strip() for line in f if line.strip()]
        grid = []
        for line in reversed(lines):
            grid.append([int(x) for x in line.split()])
        return cls(grid)

    def _find_group(self, col, row):
        color = self.grid[row][col]
        if color < 0:
            return []
        visited = set()
        stack = [(col, row)]
        group = []
        while stack:
            c, r = stack.pop()
            if (c, r) in visited:
                continue
            if not (0 <= c < COLS and 0 <= r < ROWS):
                continue
            if self.grid[r][c] != color:
                continue
            visited.add((c, r))
            group.append((c, r))
            for dc, dr in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                stack.append((c + dc, r + dr))
        return group

    def is_valid_move(self, col, row):
        if not (0 <= col < COLS and 0 <= row < ROWS):
            return False
        if self.grid[row][col] < 0:
            return False
        return len(self._find_group(col, row)) >= 2

    def apply_move(self, col, row):
        group = self._find_group(col, row)
        n = len(group)
        assert n >= 2, f"Invalid move ({col}, {row}): group size {n}"

        self.score += (n - 2) ** 2

        for c, r in group:
            self.grid[r][c] = -1

        # Gravity
        for c in range(COLS):
            filled = [self.grid[r][c] for r in range(ROWS) if self.grid[r][c] >= 0]
            for r in range(ROWS):
                self.grid[r][c] = filled[r] if r < len(filled) else -1

        # Column collapse
        non_empty = [c for c in range(COLS) if self.grid[0][c] >= 0]
        new_grid = [[-1] * COLS for _ in range(ROWS)]
        for new_c, old_c in enumerate(non_empty):
            for r in range(ROWS):
                new_grid[r][new_c] = self.grid[r][old_c]
        self.grid = new_grid

    def is_cleared(self):
        return self.grid[0][0] < 0

    def final_score(self):
        return self.score + (1000 if self.is_cleared() else 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_moves(filename):
    if not os.path.exists(filename):
        return None
    moves = []
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                moves.append((int(parts[0]), int(parts[1])))
    return moves


def replay_board(board_idx):
    """Replay moves on board, return (game, moves_list)."""
    moves = load_moves(MOVES_FILES[board_idx])
    assert moves is not None, (
        f"Move file {MOVES_FILES[board_idx]} not found — solver may have crashed or timed out"
    )
    game = SameGame.from_file(BOARDS[board_idx])
    for i, (col, row) in enumerate(moves):
        assert game.is_valid_move(col, row), (
            f"Board {board_idx}, move {i}: ({col}, {row}) is not a valid move"
        )
        game.apply_move(col, row)
    return game, moves


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_solver_exists():
    """The agent must have created /app/solver.py."""
    assert os.path.exists("/app/solver.py"), "Solver not found at /app/solver.py"


@pytest.mark.parametrize("board_idx", range(NUM_BOARDS))
def test_moves_produced(board_idx):
    """Solver must produce at least one move per board."""
    moves = load_moves(MOVES_FILES[board_idx])
    assert moves is not None and len(moves) > 0, (
        f"No moves produced for board {board_idx}"
    )


@pytest.mark.parametrize("board_idx", range(NUM_BOARDS))
def test_moves_valid(board_idx):
    """Every move in the sequence must be legal on the current board state."""
    replay_board(board_idx)  # asserts inside


@pytest.mark.parametrize("board_idx", range(NUM_BOARDS))
def test_per_board_score(board_idx):
    """Each board must meet the minimum individual score threshold."""
    game, _ = replay_board(board_idx)
    score = game.final_score()
    assert score >= PER_BOARD_THRESHOLD, (
        f"Board {board_idx}: score {score} < threshold {PER_BOARD_THRESHOLD}"
    )


def test_total_score():
    """Combined score across all boards must meet the total threshold."""
    total = 0
    for i in range(NUM_BOARDS):
        game, _ = replay_board(i)
        total += game.final_score()
    assert total >= TOTAL_THRESHOLD, (
        f"Total score {total} < threshold {TOTAL_THRESHOLD}"
    )
