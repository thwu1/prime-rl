
import pytest
import subprocess
import json


def run_reasoner(game_file, command, *args):
    """Run the GDL reasoner with a command and return parsed JSON output."""
    cmd = ["python3", "/app/gdl_reasoner.py", game_file, command] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (
        f"Reasoner failed with exit code {result.returncode}.\n"
        f"Command: {' '.join(cmd)}\n"
        f"stderr: {result.stderr}\n"
        f"stdout: {result.stdout}"
    )
    return json.loads(result.stdout.strip())


# ==================== Maze Game Tests ====================

class TestMazeRoles:
    GAME = "/app/games/maze.kif"

    def test_roles(self):
        result = run_reasoner(self.GAME, "roles")
        assert result == ["robot"]


class TestMazeInitialState:
    GAME = "/app/games/maze.kif"

    def test_initial_state_contents(self):
        result = run_reasoner(self.GAME, "initial_state")
        result_set = set(result)
        assert "(cell a)" in result_set
        assert "(gold c)" in result_set
        assert "(step 1)" in result_set

    def test_initial_state_size(self):
        result = run_reasoner(self.GAME, "initial_state")
        assert len(result) == 3


class TestMazeLegalMoves:
    GAME = "/app/games/maze.kif"

    def test_initial_only_move(self):
        """At start, robot can only move (grab needs co-located gold, drop needs inventory)."""
        state = ["(cell a)", "(gold c)", "(step 1)"]
        result = run_reasoner(self.GAME, "legal_moves", "robot", json.dumps(state))
        assert result == ["move"]

    def test_grab_legal_when_colocated(self):
        """Grab becomes legal when robot and gold are at the same cell."""
        state = ["(cell c)", "(gold c)", "(step 3)"]
        result = run_reasoner(self.GAME, "legal_moves", "robot", json.dumps(state))
        assert "grab" in result
        assert "move" in result

    def test_drop_legal_when_holding(self):
        """Drop becomes legal when gold is in inventory."""
        state = ["(cell a)", "(gold i)", "(step 6)"]
        result = run_reasoner(self.GAME, "legal_moves", "robot", json.dumps(state))
        assert "drop" in result
        assert "move" in result


class TestMazeNextState:
    GAME = "/app/games/maze.kif"

    def test_move_a_to_b(self):
        """Moving from cell a goes to cell b (adjacent a b)."""
        state = ["(cell a)", "(gold c)", "(step 1)"]
        moves = {"robot": "move"}
        result = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps(moves))
        result_set = set(result)
        assert "(cell b)" in result_set
        assert "(gold c)" in result_set
        assert "(step 2)" in result_set
        assert len(result) == 3

    def test_grab_gold(self):
        """Grabbing gold at same location moves gold to inventory."""
        state = ["(cell c)", "(gold c)", "(step 3)"]
        moves = {"robot": "grab"}
        result = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps(moves))
        result_set = set(result)
        assert "(gold i)" in result_set
        assert "(cell c)" in result_set
        assert "(step 4)" in result_set
        assert len(result) == 3

    def test_drop_gold(self):
        """Dropping gold at current cell places gold there."""
        state = ["(cell a)", "(gold i)", "(step 6)"]
        moves = {"robot": "drop"}
        result = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps(moves))
        result_set = set(result)
        assert "(gold a)" in result_set
        assert "(cell a)" in result_set
        assert "(step 7)" in result_set


class TestMazeTerminal:
    GAME = "/app/games/maze.kif"

    def test_not_terminal_initial(self):
        state = ["(cell a)", "(gold c)", "(step 1)"]
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(state)) is False

    def test_terminal_gold_at_a(self):
        state = ["(cell a)", "(gold a)", "(step 7)"]
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(state)) is True

    def test_terminal_step_10(self):
        state = ["(cell b)", "(gold c)", "(step 10)"]
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(state)) is True


class TestMazeGoal:
    GAME = "/app/games/maze.kif"

    def test_goal_win(self):
        state = ["(cell a)", "(gold a)", "(step 7)"]
        assert run_reasoner(self.GAME, "goal", "robot", json.dumps(state)) == 100

    def test_goal_lose(self):
        state = ["(cell b)", "(gold c)", "(step 10)"]
        assert run_reasoner(self.GAME, "goal", "robot", json.dumps(state)) == 0


# ==================== Tictictoe Game Tests ====================

class TestTictictoeRoles:
    GAME = "/app/games/tictictoe.kif"

    def test_roles(self):
        result = run_reasoner(self.GAME, "roles")
        assert sorted(result) == ["oplayer", "xplayer"]


class TestTictictoeInitialState:
    GAME = "/app/games/tictictoe.kif"

    def test_initial_state_cells(self):
        result = run_reasoner(self.GAME, "initial_state")
        result_set = set(result)
        for i in range(1, 4):
            for j in range(1, 4):
                assert f"(cell {i} {j} b)" in result_set

    def test_initial_state_step(self):
        result = run_reasoner(self.GAME, "initial_state")
        assert "(step 1)" in set(result)

    def test_initial_state_size(self):
        result = run_reasoner(self.GAME, "initial_state")
        assert len(result) == 10  # 9 cells + step


class TestTictictoeLegalMoves:
    GAME = "/app/games/tictictoe.kif"

    def test_both_players_can_mark_all(self):
        """Both players can mark any blank cell initially."""
        init = [f"(cell {i} {j} b)" for i in range(1, 4) for j in range(1, 4)] + ["(step 1)"]
        x_legal = run_reasoner(self.GAME, "legal_moves", "xplayer", json.dumps(init))
        o_legal = run_reasoner(self.GAME, "legal_moves", "oplayer", json.dumps(init))
        assert len(x_legal) == 9
        assert len(o_legal) == 9

    def test_specific_moves_present(self):
        init = [f"(cell {i} {j} b)" for i in range(1, 4) for j in range(1, 4)] + ["(step 1)"]
        x_legal = run_reasoner(self.GAME, "legal_moves", "xplayer", json.dumps(init))
        assert "(mark 1 1)" in x_legal
        assert "(mark 2 3)" in x_legal
        assert "(mark 3 3)" in x_legal

    def test_fewer_moves_with_filled_cells(self):
        """Filled cells reduce available moves."""
        state = [
            "(cell 1 1 x)", "(cell 1 2 b)", "(cell 1 3 b)",
            "(cell 2 1 b)", "(cell 2 2 o)", "(cell 2 3 b)",
            "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 b)",
            "(step 2)"
        ]
        x_legal = run_reasoner(self.GAME, "legal_moves", "xplayer", json.dumps(state))
        assert len(x_legal) == 7  # 9 - 2 filled
        assert "(mark 1 1)" not in x_legal
        assert "(mark 2 2)" not in x_legal


class TestTictictoeNextState:
    GAME = "/app/games/tictictoe.kif"

    def test_different_cells_both_mark(self):
        """When players mark different cells, both marks appear."""
        init = [f"(cell {i} {j} b)" for i in range(1, 4) for j in range(1, 4)] + ["(step 1)"]
        moves = {"xplayer": "(mark 1 1)", "oplayer": "(mark 2 2)"}
        result = run_reasoner(self.GAME, "next_state", json.dumps(init), json.dumps(moves))
        result_set = set(result)
        assert "(cell 1 1 x)" in result_set
        assert "(cell 2 2 o)" in result_set
        assert "(step 2)" in result_set
        # Remaining cells stay blank
        assert "(cell 1 2 b)" in result_set
        assert "(cell 3 3 b)" in result_set

    def test_same_cell_stays_blank(self):
        """When both players mark the same cell, it stays blank."""
        init = [f"(cell {i} {j} b)" for i in range(1, 4) for j in range(1, 4)] + ["(step 1)"]
        moves = {"xplayer": "(mark 2 2)", "oplayer": "(mark 2 2)"}
        result = run_reasoner(self.GAME, "next_state", json.dumps(init), json.dumps(moves))
        result_set = set(result)
        assert "(cell 2 2 b)" in result_set
        # No x or o should appear at (2,2)
        assert "(cell 2 2 x)" not in result_set
        assert "(cell 2 2 o)" not in result_set
        # All cells remain blank
        for i in range(1, 4):
            for j in range(1, 4):
                assert f"(cell {i} {j} b)" in result_set
        assert len(result) == 10

    def test_existing_marks_persist(self):
        """Existing x/o marks persist across turns."""
        state = [
            "(cell 1 1 x)", "(cell 1 2 b)", "(cell 1 3 b)",
            "(cell 2 1 b)", "(cell 2 2 o)", "(cell 2 3 b)",
            "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 b)",
            "(step 2)"
        ]
        moves = {"xplayer": "(mark 1 2)", "oplayer": "(mark 3 3)"}
        result = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps(moves))
        result_set = set(result)
        # Previous marks persist
        assert "(cell 1 1 x)" in result_set
        assert "(cell 2 2 o)" in result_set
        # New marks appear
        assert "(cell 1 2 x)" in result_set
        assert "(cell 3 3 o)" in result_set
        assert "(step 3)" in result_set


class TestTictictoeTerminal:
    GAME = "/app/games/tictictoe.kif"

    def test_not_terminal_initial(self):
        init = [f"(cell {i} {j} b)" for i in range(1, 4) for j in range(1, 4)] + ["(step 1)"]
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(init)) is False

    def test_terminal_row_x(self):
        state = [
            "(cell 1 1 x)", "(cell 1 2 x)", "(cell 1 3 x)",
            "(cell 2 1 o)", "(cell 2 2 o)", "(cell 2 3 b)",
            "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 b)",
            "(step 4)"
        ]
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(state)) is True

    def test_terminal_diagonal_o(self):
        state = [
            "(cell 1 1 o)", "(cell 1 2 x)", "(cell 1 3 b)",
            "(cell 2 1 x)", "(cell 2 2 o)", "(cell 2 3 b)",
            "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 o)",
            "(step 5)"
        ]
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(state)) is True

    def test_terminal_step_7(self):
        state = [
            "(cell 1 1 x)", "(cell 1 2 o)", "(cell 1 3 x)",
            "(cell 2 1 o)", "(cell 2 2 x)", "(cell 2 3 o)",
            "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 b)",
            "(step 7)"
        ]
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(state)) is True


class TestTictictoeGoal:
    GAME = "/app/games/tictictoe.kif"

    def test_x_wins(self):
        state = [
            "(cell 1 1 x)", "(cell 1 2 x)", "(cell 1 3 x)",
            "(cell 2 1 o)", "(cell 2 2 o)", "(cell 2 3 b)",
            "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 b)",
            "(step 4)"
        ]
        assert run_reasoner(self.GAME, "goal", "xplayer", json.dumps(state)) == 100
        assert run_reasoner(self.GAME, "goal", "oplayer", json.dumps(state)) == 0

    def test_draw_at_step_7(self):
        """Draw when step 7 reached with no lines."""
        state = [
            "(cell 1 1 x)", "(cell 1 2 o)", "(cell 1 3 x)",
            "(cell 2 1 o)", "(cell 2 2 x)", "(cell 2 3 o)",
            "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 b)",
            "(step 7)"
        ]
        assert run_reasoner(self.GAME, "goal", "xplayer", json.dumps(state)) == 50
        assert run_reasoner(self.GAME, "goal", "oplayer", json.dumps(state)) == 50


# ==================== Connect Four Game Tests ====================

class TestConnectFourRoles:
    GAME = "/app/games/connectFour.kif"

    def test_roles(self):
        result = run_reasoner(self.GAME, "roles")
        assert sorted(result) == ["black", "red"]


class TestConnectFourInitialState:
    GAME = "/app/games/connectFour.kif"

    def test_initial_state(self):
        result = run_reasoner(self.GAME, "initial_state")
        assert result == ["(control red)"]


class TestConnectFourLegalMoves:
    GAME = "/app/games/connectFour.kif"

    def test_red_can_drop_all_columns(self):
        state = ["(control red)"]
        result = run_reasoner(self.GAME, "legal_moves", "red", json.dumps(state))
        drops = sorted([m for m in result if m.startswith("(drop")])
        assert len(drops) == 8
        assert "(drop 1)" in drops
        assert "(drop 8)" in drops

    def test_red_cannot_noop(self):
        state = ["(control red)"]
        result = run_reasoner(self.GAME, "legal_moves", "red", json.dumps(state))
        assert "noop" not in result

    def test_black_only_noop_on_red_turn(self):
        state = ["(control red)"]
        result = run_reasoner(self.GAME, "legal_moves", "black", json.dumps(state))
        assert result == ["noop"]


class TestConnectFourNextState:
    GAME = "/app/games/connectFour.kif"

    def test_first_drop(self):
        """First drop in column lands at row 1."""
        state = ["(control red)"]
        moves = {"red": "(drop 1)", "black": "noop"}
        result = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps(moves))
        result_set = set(result)
        assert "(cell 1 1 red)" in result_set
        assert "(control black)" in result_set
        assert len(result) == 2

    def test_gravity_stacking(self):
        """Second piece in same column stacks on top of existing piece."""
        state = ["(cell 1 1 red)", "(control black)"]
        moves = {"red": "noop", "black": "(drop 1)"}
        result = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps(moves))
        result_set = set(result)
        assert "(cell 1 1 red)" in result_set
        assert "(cell 1 2 black)" in result_set
        assert "(control red)" in result_set
        assert len(result) == 3

    def test_different_columns(self):
        """Pieces in different columns are independent."""
        state = ["(cell 1 1 red)", "(control black)"]
        moves = {"red": "noop", "black": "(drop 3)"}
        result = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps(moves))
        result_set = set(result)
        assert "(cell 1 1 red)" in result_set
        assert "(cell 3 1 black)" in result_set
        assert "(control red)" in result_set


class TestConnectFourTerminal:
    GAME = "/app/games/connectFour.kif"

    def test_not_terminal_initial(self):
        state = ["(control red)"]
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(state)) is False

    def test_not_terminal_three_in_row(self):
        state = [
            "(cell 1 1 red)", "(cell 2 1 red)", "(cell 3 1 red)",
            "(cell 1 2 black)", "(cell 2 2 black)",
            "(control black)"
        ]
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(state)) is False

    def test_terminal_horizontal(self):
        state = [
            "(cell 1 1 red)", "(cell 2 1 red)", "(cell 3 1 red)", "(cell 4 1 red)",
            "(cell 1 2 black)", "(cell 2 2 black)", "(cell 3 2 black)",
            "(control black)"
        ]
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(state)) is True

    def test_terminal_vertical(self):
        state = [
            "(cell 1 1 red)", "(cell 1 2 red)", "(cell 1 3 red)", "(cell 1 4 red)",
            "(cell 2 1 black)", "(cell 2 2 black)", "(cell 2 3 black)",
            "(control black)"
        ]
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(state)) is True


class TestConnectFourGoal:
    GAME = "/app/games/connectFour.kif"

    def test_red_wins(self):
        state = [
            "(cell 1 1 red)", "(cell 2 1 red)", "(cell 3 1 red)", "(cell 4 1 red)",
            "(cell 1 2 black)", "(cell 2 2 black)", "(cell 3 2 black)",
            "(control black)"
        ]
        assert run_reasoner(self.GAME, "goal", "red", json.dumps(state)) == 100
        assert run_reasoner(self.GAME, "goal", "black", json.dumps(state)) == 0


# ==================== Simple Mutex Game Tests ====================

class TestSimpleMutexRoles:
    GAME = "/app/games/simpleMutex.kif"

    def test_roles(self):
        result = run_reasoner(self.GAME, "roles")
        assert result == ["robot"]


class TestSimpleMutexInitialState:
    GAME = "/app/games/simpleMutex.kif"

    def test_initial_state(self):
        result = run_reasoner(self.GAME, "initial_state")
        assert set(result) == {"h1", "t1"}


class TestSimpleMutexLegalMoves:
    GAME = "/app/games/simpleMutex.kif"

    def test_initial_legal(self):
        """From h1 with likely=true, actions a, b, c are legal."""
        state = ["h1", "t1"]
        result = run_reasoner(self.GAME, "legal_moves", "robot", json.dumps(state))
        assert sorted(result) == ["a", "b", "c"]


class TestSimpleMutexNextState:
    GAME = "/app/games/simpleMutex.kif"

    def test_action_b_from_initial(self):
        """Action b from h1 produces h3 (and derived mutex state)."""
        state = ["h1", "t1"]
        moves = {"robot": "b"}
        result = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps(moves))
        result_set = set(result)
        assert "h3" in result_set
        assert "m1" in result_set
        assert "m4" in result_set
        assert "m6" in result_set
        assert "t2" in result_set
        assert len(result) == 5

    def test_action_a_from_initial(self):
        """Action a from h1 produces h2."""
        state = ["h1", "t1"]
        moves = {"robot": "a"}
        result = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps(moves))
        assert "h2" in set(result)
        assert "h3" not in set(result)


class TestSimpleMutexTerminal:
    GAME = "/app/games/simpleMutex.kif"

    def test_not_terminal_initial(self):
        state = ["h1", "t1"]
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(state)) is False

    def test_terminal_h3(self):
        """h3 with likely=true is terminal."""
        state = ["h3", "m1", "m4", "m6", "t2"]
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(state)) is True


class TestSimpleMutexGoal:
    GAME = "/app/games/simpleMutex.kif"

    def test_goal_win(self):
        state = ["h3", "m1", "m4", "m6", "t2"]
        assert run_reasoner(self.GAME, "goal", "robot", json.dumps(state)) == 100

    def test_goal_lose(self):
        state = ["h8", "m2", "m4", "m6", "t2"]
        assert run_reasoner(self.GAME, "goal", "robot", json.dumps(state)) == 0


# ==================== Full Playthrough Test ====================

class TestMazePlaythrough:
    """Verify end-to-end consistency by playing through the maze to win."""
    GAME = "/app/games/maze.kif"

    def test_full_game(self):
        # Start
        state = run_reasoner(self.GAME, "initial_state")
        assert not run_reasoner(self.GAME, "is_terminal", json.dumps(state))

        # Move a->b
        state = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps({"robot": "move"}))
        assert "(cell b)" in set(state)

        # Move b->c
        state = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps({"robot": "move"}))
        assert "(cell c)" in set(state)

        # Grab gold at c
        legal = run_reasoner(self.GAME, "legal_moves", "robot", json.dumps(state))
        assert "grab" in legal
        state = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps({"robot": "grab"}))
        assert "(gold i)" in set(state)

        # Move c->d
        state = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps({"robot": "move"}))
        assert "(cell d)" in set(state)

        # Move d->a
        state = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps({"robot": "move"}))
        assert "(cell a)" in set(state)

        # Drop gold at a
        legal = run_reasoner(self.GAME, "legal_moves", "robot", json.dumps(state))
        assert "drop" in legal
        state = run_reasoner(self.GAME, "next_state", json.dumps(state), json.dumps({"robot": "drop"}))
        assert "(gold a)" in set(state)

        # Should be terminal with goal 100
        assert run_reasoner(self.GAME, "is_terminal", json.dumps(state))
        assert run_reasoner(self.GAME, "goal", "robot", json.dumps(state)) == 100
