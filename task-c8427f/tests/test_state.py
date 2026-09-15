"""Test suite for Sokoban puzzle forensics: analysis, solutions, dead positions.

"""

import sqlite3
import pytest
from collections import deque

DB_PATH = "/app/sokoban.db"

DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
MOVE_DIR = {
    'u': (-1, 0), 'd': (1, 0), 'l': (0, -1), 'r': (0, 1),
    'U': (-1, 0), 'D': (1, 0), 'L': (0, -1), 'R': (0, 1),
}


# ---------------------------------------------------------------------------
# Reference implementations
# ---------------------------------------------------------------------------

def parse_level(board_text):
    """Parse a Sokoban level from board text."""
    lines = board_text.rstrip('\n').split('\n')
    lines = [l for l in lines if l.strip() and not l.strip().startswith(';')]
    walls, boxes, goals = set(), set(), set()
    player = None
    for r, line in enumerate(lines):
        for c, ch in enumerate(line):
            p = (r, c)
            if ch == '#':
                walls.add(p)
            elif ch == '@':
                player = p
            elif ch == '+':
                player = p
                goals.add(p)
            elif ch == '$':
                boxes.add(p)
            elif ch == '*':
                boxes.add(p)
                goals.add(p)
            elif ch == '.':
                goals.add(p)
    assert player is not None, "No player found in level"
    return walls, boxes, goals, player


def flood_fill(start, walls, blocked=frozenset()):
    """BFS reachability from start, avoiding walls and blocked cells."""
    if not walls:
        return {start}
    bound_r = max(r for r, _ in walls) + 2
    bound_c = max(c for _, c in walls) + 2
    visited = {start}
    q = deque([start])
    while q:
        r, c = q.popleft()
        for dr, dc in DIRS:
            nr, nc = r + dr, c + dc
            np_ = (nr, nc)
            if 0 <= nr < bound_r and 0 <= nc < bound_c:
                if np_ not in walls and np_ not in blocked and np_ not in visited:
                    visited.add(np_)
                    q.append(np_)
    return visited


def compute_dead_squares_ref(walls, floor, goals):
    """Reference dead-square computation via reverse BFS from each goal.

    For each goal, simulate pulling a box backward to find all positions
    from which at least one goal is reachable. Floor cells never reached
    by any goal's reverse BFS are dead.
    """
    alive = set()
    for goal in goals:
        visited = {goal}
        q = deque([goal])
        while q:
            pos = q.popleft()
            alive.add(pos)
            for dr, dc in DIRS:
                # prev: where the box was before being pushed to pos
                prev = (pos[0] - dr, pos[1] - dc)
                # plyr: where the player stood to execute that push
                plyr = (pos[0] - 2 * dr, pos[1] - 2 * dc)
                if prev in floor and plyr in floor and prev not in visited:
                    visited.add(prev)
                    q.append(prev)
    return frozenset(p for p in floor if p not in alive)


def replay_moves(walls, boxes, goals, player, moves):
    """Replay a move string and return analysis results.

    Returns (all_legal, first_error_idx_or_None, error_type_or_None, all_on_goals).
    """
    boxes = set(boxes)
    pr, pc = player

    for i, ch in enumerate(moves):
        if ch not in MOVE_DIR:
            return False, i, "invalid_character", False
        dr, dc = MOVE_DIR[ch]
        nr, nc = pr + dr, pc + dc

        if ch in 'udlr':
            if (nr, nc) in walls:
                return False, i, "walk_into_wall", False
            if (nr, nc) in boxes:
                return False, i, "walk_into_box", False
            pr, pc = nr, nc
        else:
            if (nr, nc) not in boxes:
                return False, i, "push_no_box", False
            br, bc = nr + dr, nc + dc
            if (br, bc) in walls:
                return False, i, "push_into_wall", False
            if (br, bc) in boxes:
                return False, i, "push_into_box", False
            boxes.remove((nr, nc))
            boxes.add((br, bc))
            pr, pc = nr, nc

    return True, None, None, (boxes == goals)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    c = sqlite3.connect(DB_PATH)
    yield c
    c.close()


def table_exists(conn, name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAnalysis:
    """Verify that the agent's attempt analysis matches reference replay."""

    @pytest.mark.parametrize("level_id", [1, 2, 3, 4])
    def test_analysis_correctness(self, conn, level_id):
        assert table_exists(conn, "analysis"), "Table 'analysis' does not exist"

        board = conn.execute(
            "SELECT board FROM levels WHERE id=?", (level_id,)
        ).fetchone()
        assert board is not None, f"Level {level_id} not found"
        board = board[0]

        attempt_row = conn.execute(
            "SELECT moves FROM attempts WHERE level_id=?", (level_id,)
        ).fetchone()
        assert attempt_row is not None, f"Attempt for level {level_id} not found"
        attempt_moves = attempt_row[0]

        agent_row = conn.execute(
            "SELECT attempt_valid, first_error_move, error_type FROM analysis WHERE level_id=?",
            (level_id,),
        ).fetchone()
        assert agent_row is not None, f"No analysis row for level {level_id}"
        agent_valid, agent_error_move, agent_error_type = agent_row

        # Compute expected analysis via reference replay
        walls, boxes, goals, player = parse_level(board)
        all_legal, err_idx, _, all_on_goals = replay_moves(
            walls, boxes, goals, player, attempt_moves
        )

        if all_legal and all_on_goals:
            exp_valid, exp_error_move = 1, None
        elif all_legal:
            exp_valid, exp_error_move = 0, None
        else:
            exp_valid, exp_error_move = 0, err_idx

        assert agent_valid == exp_valid, (
            f"Level {level_id}: expected attempt_valid={exp_valid}, got {agent_valid}"
        )
        assert agent_error_move == exp_error_move, (
            f"Level {level_id}: expected first_error_move={exp_error_move}, "
            f"got {agent_error_move}"
        )
        if exp_valid == 1:
            assert agent_error_type is None, (
                f"Level {level_id}: valid attempt should have NULL error_type, "
                f"got '{agent_error_type}'"
            )
        else:
            assert agent_error_type is not None and len(str(agent_error_type).strip()) > 0, (
                f"Level {level_id}: invalid attempt must have non-empty error_type"
            )


class TestSolutions:
    """Verify that agent-provided solutions are valid and complete."""

    @pytest.mark.parametrize("level_id", [1, 2, 3, 4])
    def test_solution_valid(self, conn, level_id):
        assert table_exists(conn, "solutions"), "Table 'solutions' does not exist"

        board = conn.execute(
            "SELECT board FROM levels WHERE id=?", (level_id,)
        ).fetchone()
        assert board is not None
        board = board[0]

        sol_row = conn.execute(
            "SELECT moves FROM solutions WHERE level_id=?", (level_id,)
        ).fetchone()
        assert sol_row is not None, f"No solution row for level {level_id}"
        moves = sol_row[0]
        assert len(moves) > 0, f"Empty solution for level {level_id}"

        walls, boxes, goals, player = parse_level(board)
        all_legal, err_idx, err_type, all_on_goals = replay_moves(
            walls, boxes, goals, player, moves
        )

        assert all_legal, (
            f"Level {level_id}: illegal move at index {err_idx}: {err_type}"
        )
        assert all_on_goals, (
            f"Level {level_id}: solution does not place all boxes on goals"
        )


class TestDeadPositions:
    """Verify that agent-computed dead positions match the reference set."""

    @pytest.mark.parametrize("level_id", [1, 2, 3, 4])
    def test_dead_positions_match(self, conn, level_id):
        assert table_exists(conn, "dead_positions"), \
            "Table 'dead_positions' does not exist"

        board = conn.execute(
            "SELECT board FROM levels WHERE id=?", (level_id,)
        ).fetchone()
        assert board is not None
        board = board[0]

        agent_dead = set(
            conn.execute(
                "SELECT row, col FROM dead_positions WHERE level_id=?",
                (level_id,),
            ).fetchall()
        )

        walls, boxes, goals, player = parse_level(board)
        floor = flood_fill(player, walls)
        ref_dead = set((r, c) for r, c in compute_dead_squares_ref(walls, floor, goals))

        missing = ref_dead - agent_dead
        extra = agent_dead - ref_dead

        assert not missing, (
            f"Level {level_id}: missing {len(missing)} dead position(s): "
            f"{sorted(missing)[:5]}"
        )
        assert not extra, (
            f"Level {level_id}: {len(extra)} extra dead position(s): "
            f"{sorted(extra)[:5]}"
        )
