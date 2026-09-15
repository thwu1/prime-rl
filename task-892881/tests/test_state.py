"""
Tests for GDL State Machine Engine with SWI-Prolog backend.

Verifies: (1) Prolog integration (swipl installed, .pl files present, engine
references swipl), and (2) correct GDL state machine protocol across three
games: switches (simple), tic-tac-toe (simultaneous moves), Connect Four
(alternating turns with gravity).

"""
import subprocess
import json
import os
import glob
import pytest

DATA_DIR = "/tmp/gdl_test_data"
os.makedirs(DATA_DIR, exist_ok=True)

_file_counter = 0


def _write_json(data, prefix="data"):
    global _file_counter
    _file_counter += 1
    path = os.path.join(DATA_DIR, f"{prefix}_{_file_counter}.json")
    with open(path, "w") as f:
        json.dump(data, f)
    return path


def run_engine(game, command, extra_args=None):
    cmd = ["python3", "/app/gdl_engine.py", f"/app/games/{game}", command]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (
        f"Engine failed: cmd={' '.join(cmd)}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    return result.stdout.strip()


# =========================================================================
# PROLOG INTEGRATION TESTS
# =========================================================================


class TestPrologIntegration:
    """Verify the engine delegates logical inference to SWI-Prolog."""

    def test_swipl_installed(self):
        """SWI-Prolog must be available in the environment."""
        result = subprocess.run(
            ["swipl", "--version"], capture_output=True, text=True
        )
        assert result.returncode == 0, "swipl is not installed"

    def test_prolog_source_exists(self):
        """At least one Prolog source file with inference code must exist."""
        pl_files = glob.glob("/app/*.pl")
        assert len(pl_files) > 0, "No .pl files found in /app/"
        total_size = sum(os.path.getsize(f) for f in pl_files)
        assert total_size > 200, "Prolog files must contain substantial inference code"

    def test_prolog_source_has_rules(self):
        """Prolog files must contain actual Prolog rules and declarations."""
        pl_files = glob.glob("/app/*.pl")
        combined = ""
        for f in pl_files:
            with open(f) as fh:
                combined += fh.read()
        assert ":-" in combined, "Prolog file must contain rules (:-)"
        has_dynamic = "dynamic" in combined
        has_findall = "findall" in combined or "setof" in combined
        assert has_dynamic or has_findall, (
            "Prolog file must use dynamic predicates or query predicates"
        )

    def test_engine_references_swipl(self):
        """The engine script must invoke swipl for Prolog-based inference."""
        with open("/app/gdl_engine.py") as f:
            source = f.read()
        assert "swipl" in source, "gdl_engine.py must invoke swipl"


# =========================================================================
# SWITCHES GAME TESTS
# =========================================================================

TTT_INITIAL = [f"(cell {i} {j} b)" for i in range(1, 4) for j in range(1, 4)] + [
    "(step 1)"
]


class TestSwitchesRoles:
    def test_roles(self):
        out = run_engine("switches.kif", "roles")
        assert json.loads(out) == ["player"]


class TestSwitchesInitial:
    def test_initial_state(self):
        out = run_engine("switches.kif", "initial")
        state = json.loads(out)
        assert sorted(state) == ["(step 1)", "(switch a off)", "(switch b off)"]


class TestSwitchesLegal:
    def test_legal_initial(self):
        sf = _write_json(["(step 1)", "(switch a off)", "(switch b off)"])
        out = run_engine(
            "switches.kif", "legal", ["--state", sf, "--role", "player"]
        )
        moves = json.loads(out)
        assert sorted(moves) == ["(flip a)", "(flip b)"]

    def test_legal_after_flip_a(self):
        """After flipping a, only flip b should be legal (a is already on)."""
        sf = _write_json(["(step 2)", "(switch a on)", "(switch b off)"])
        out = run_engine(
            "switches.kif", "legal", ["--state", sf, "--role", "player"]
        )
        moves = json.loads(out)
        assert "(flip b)" in moves
        assert "(flip a)" not in moves

    def test_noop_legal_when_both_on(self):
        """noop is only legal when both switches are on."""
        sf = _write_json(["(step 3)", "(switch a on)", "(switch b on)"])
        out = run_engine(
            "switches.kif", "legal", ["--state", sf, "--role", "player"]
        )
        moves = json.loads(out)
        assert "noop" in moves


class TestSwitchesNext:
    def test_flip_a(self):
        sf = _write_json(["(step 1)", "(switch a off)", "(switch b off)"])
        mf = _write_json({"player": "(flip a)"})
        out = run_engine("switches.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert sorted(state) == ["(step 2)", "(switch a on)", "(switch b off)"]

    def test_flip_b_after_a(self):
        sf = _write_json(["(step 2)", "(switch a on)", "(switch b off)"])
        mf = _write_json({"player": "(flip b)"})
        out = run_engine("switches.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert sorted(state) == ["(step 3)", "(switch a on)", "(switch b on)"]


class TestSwitchesTerminal:
    def test_not_terminal_initial(self):
        sf = _write_json(["(step 1)", "(switch a off)", "(switch b off)"])
        out = run_engine("switches.kif", "terminal", ["--state", sf])
        assert out == "false"

    def test_not_terminal_one_on(self):
        sf = _write_json(["(step 2)", "(switch a on)", "(switch b off)"])
        out = run_engine("switches.kif", "terminal", ["--state", sf])
        assert out == "false"

    def test_terminal_both_on(self):
        sf = _write_json(["(step 3)", "(switch a on)", "(switch b on)"])
        out = run_engine("switches.kif", "terminal", ["--state", sf])
        assert out == "true"

    def test_terminal_step_4(self):
        """Terminal at step 4 even if switches are off."""
        sf = _write_json(["(step 4)", "(switch a off)", "(switch b off)"])
        out = run_engine("switches.kif", "terminal", ["--state", sf])
        assert out == "true"


class TestSwitchesGoal:
    def test_goal_100_both_on(self):
        sf = _write_json(["(step 3)", "(switch a on)", "(switch b on)"])
        out = run_engine(
            "switches.kif", "goal", ["--state", sf, "--role", "player"]
        )
        assert out == "100"

    def test_goal_0_one_off(self):
        sf = _write_json(["(step 2)", "(switch a on)", "(switch b off)"])
        out = run_engine(
            "switches.kif", "goal", ["--state", sf, "--role", "player"]
        )
        assert out == "0"

    def test_goal_0_both_off(self):
        sf = _write_json(["(step 4)", "(switch a off)", "(switch b off)"])
        out = run_engine(
            "switches.kif", "goal", ["--state", sf, "--role", "player"]
        )
        assert out == "0"


class TestSwitchesSimulation:
    def test_full_win_sequence(self):
        """Play optimal: flip a, then flip b -> win in 2 moves."""
        # Step 1: flip a
        sf = _write_json(["(step 1)", "(switch a off)", "(switch b off)"])
        mf = _write_json({"player": "(flip a)"})
        out = run_engine("switches.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert sorted(state) == ["(step 2)", "(switch a on)", "(switch b off)"]

        # Verify not terminal yet
        sf = _write_json(state)
        out = run_engine("switches.kif", "terminal", ["--state", sf])
        assert out == "false"

        # Step 2: flip b
        mf = _write_json({"player": "(flip b)"})
        out = run_engine("switches.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert sorted(state) == ["(step 3)", "(switch a on)", "(switch b on)"]

        # Should be terminal with goal 100
        sf = _write_json(state)
        out = run_engine("switches.kif", "terminal", ["--state", sf])
        assert out == "true"
        out = run_engine(
            "switches.kif", "goal", ["--state", sf, "--role", "player"]
        )
        assert out == "100"


# =========================================================================
# TIC-TAC-TOE TESTS
# =========================================================================


class TestTTTRoles:
    def test_roles(self):
        out = run_engine("tictactoe.kif", "roles")
        roles = json.loads(out)
        assert sorted(roles) == ["oplayer", "xplayer"]


class TestTTTInitial:
    def test_initial_state(self):
        out = run_engine("tictactoe.kif", "initial")
        state = json.loads(out)
        assert len(state) == 10  # 9 cells + step
        assert "(step 1)" in state
        for i in range(1, 4):
            for j in range(1, 4):
                assert f"(cell {i} {j} b)" in state


class TestTTTLegal:
    def test_legal_xplayer_initial(self):
        sf = _write_json(TTT_INITIAL)
        out = run_engine(
            "tictactoe.kif", "legal", ["--state", sf, "--role", "xplayer"]
        )
        moves = json.loads(out)
        assert len(moves) == 9
        for i in range(1, 4):
            for j in range(1, 4):
                assert f"(mark {i} {j})" in moves

    def test_legal_oplayer_initial(self):
        sf = _write_json(TTT_INITIAL)
        out = run_engine(
            "tictactoe.kif", "legal", ["--state", sf, "--role", "oplayer"]
        )
        moves = json.loads(out)
        assert len(moves) == 9

    def test_legal_after_marks(self):
        """After two marks placed, 7 cells remain."""
        state = [
            "(cell 1 1 x)", "(cell 1 2 b)", "(cell 1 3 b)",
            "(cell 2 1 b)", "(cell 2 2 o)", "(cell 2 3 b)",
            "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 b)",
            "(step 2)",
        ]
        sf = _write_json(state)
        out = run_engine(
            "tictactoe.kif", "legal", ["--state", sf, "--role", "xplayer"]
        )
        moves = json.loads(out)
        assert len(moves) == 7
        assert "(mark 1 1)" not in moves  # already occupied
        assert "(mark 2 2)" not in moves  # already occupied


class TestTTTNext:
    def test_different_cells(self):
        """Both players mark different cells -> both placed."""
        sf = _write_json(TTT_INITIAL)
        mf = _write_json({"xplayer": "(mark 1 1)", "oplayer": "(mark 2 2)"})
        out = run_engine("tictactoe.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert "(cell 1 1 x)" in state
        assert "(cell 2 2 o)" in state
        assert "(step 2)" in state
        assert "(cell 1 2 b)" in state  # untouched cell stays blank
        assert len(state) == 10

    def test_same_cell_conflict(self):
        """Both players mark the same cell -> cell stays blank."""
        sf = _write_json(TTT_INITIAL)
        mf = _write_json({"xplayer": "(mark 1 1)", "oplayer": "(mark 1 1)"})
        out = run_engine("tictactoe.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert "(cell 1 1 b)" in state  # stays blank
        assert "(cell 1 1 x)" not in state
        assert "(cell 1 1 o)" not in state
        assert "(step 2)" in state

    def test_existing_marks_preserved(self):
        """Non-blank cells are preserved across transitions."""
        s = [
            "(cell 1 1 x)", "(cell 1 2 b)", "(cell 1 3 b)",
            "(cell 2 1 b)", "(cell 2 2 o)", "(cell 2 3 b)",
            "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 b)",
            "(step 2)",
        ]
        sf = _write_json(s)
        mf = _write_json({"xplayer": "(mark 1 2)", "oplayer": "(mark 3 3)"})
        out = run_engine("tictactoe.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert "(cell 1 1 x)" in state  # preserved
        assert "(cell 2 2 o)" in state  # preserved
        assert "(cell 1 2 x)" in state  # new x
        assert "(cell 3 3 o)" in state  # new o
        assert "(step 3)" in state


class TestTTTTerminal:
    def test_not_terminal_initial(self):
        sf = _write_json(TTT_INITIAL)
        out = run_engine("tictactoe.kif", "terminal", ["--state", sf])
        assert out == "false"

    def test_terminal_row_x(self):
        """X wins with a complete row."""
        state = [
            "(cell 1 1 x)", "(cell 1 2 x)", "(cell 1 3 x)",
            "(cell 2 1 o)", "(cell 2 2 o)", "(cell 2 3 b)",
            "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 b)",
            "(step 4)",
        ]
        sf = _write_json(state)
        out = run_engine("tictactoe.kif", "terminal", ["--state", sf])
        assert out == "true"

    def test_terminal_diagonal_x(self):
        """X wins on the main diagonal."""
        state = [
            "(cell 1 1 x)", "(cell 1 2 o)", "(cell 1 3 b)",
            "(cell 2 1 o)", "(cell 2 2 x)", "(cell 2 3 b)",
            "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 x)",
            "(step 4)",
        ]
        sf = _write_json(state)
        out = run_engine("tictactoe.kif", "terminal", ["--state", sf])
        assert out == "true"

    def test_terminal_step_7(self):
        """Game is terminal at step 7 regardless of board."""
        state = [
            "(cell 1 1 x)", "(cell 1 2 o)", "(cell 1 3 x)",
            "(cell 2 1 o)", "(cell 2 2 x)", "(cell 2 3 o)",
            "(cell 3 1 o)", "(cell 3 2 x)", "(cell 3 3 o)",
            "(step 7)",
        ]
        sf = _write_json(state)
        out = run_engine("tictactoe.kif", "terminal", ["--state", sf])
        assert out == "true"


class TestTTTGoal:
    def test_x_wins_row(self):
        state = [
            "(cell 1 1 x)", "(cell 1 2 x)", "(cell 1 3 x)",
            "(cell 2 1 o)", "(cell 2 2 o)", "(cell 2 3 b)",
            "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 b)",
            "(step 4)",
        ]
        sf = _write_json(state)
        out = run_engine(
            "tictactoe.kif", "goal", ["--state", sf, "--role", "xplayer"]
        )
        assert out == "100"
        out = run_engine(
            "tictactoe.kif", "goal", ["--state", sf, "--role", "oplayer"]
        )
        assert out == "0"

    def test_draw_at_step_7(self):
        """No lines for either player at step 7 -> both get 50."""
        state = [
            "(cell 1 1 x)", "(cell 1 2 o)", "(cell 1 3 x)",
            "(cell 2 1 o)", "(cell 2 2 x)", "(cell 2 3 o)",
            "(cell 3 1 o)", "(cell 3 2 x)", "(cell 3 3 o)",
            "(step 7)",
        ]
        sf = _write_json(state)
        out = run_engine(
            "tictactoe.kif", "goal", ["--state", sf, "--role", "xplayer"]
        )
        assert out == "50"
        out = run_engine(
            "tictactoe.kif", "goal", ["--state", sf, "--role", "oplayer"]
        )
        assert out == "50"

    def test_x_diagonal_win(self):
        state = [
            "(cell 1 1 x)", "(cell 1 2 o)", "(cell 1 3 b)",
            "(cell 2 1 o)", "(cell 2 2 x)", "(cell 2 3 b)",
            "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 x)",
            "(step 4)",
        ]
        sf = _write_json(state)
        out = run_engine(
            "tictactoe.kif", "goal", ["--state", sf, "--role", "xplayer"]
        )
        assert out == "100"
        out = run_engine(
            "tictactoe.kif", "goal", ["--state", sf, "--role", "oplayer"]
        )
        assert out == "0"


# =========================================================================
# CONNECT FOUR TESTS
# =========================================================================


class TestC4Roles:
    def test_roles(self):
        out = run_engine("connectfour.kif", "roles")
        roles = json.loads(out)
        assert sorted(roles) == ["black", "red"]


class TestC4Initial:
    def test_initial_state(self):
        out = run_engine("connectfour.kif", "initial")
        state = json.loads(out)
        assert state == ["(control red)"]


class TestC4Legal:
    def test_red_initial(self):
        """Red can drop in all 8 columns initially."""
        sf = _write_json(["(control red)"])
        out = run_engine(
            "connectfour.kif", "legal", ["--state", sf, "--role", "red"]
        )
        moves = json.loads(out)
        assert len(moves) == 8
        for i in range(1, 9):
            assert f"(drop {i})" in moves

    def test_black_initial_noop(self):
        """Black must noop when red has control."""
        sf = _write_json(["(control red)"])
        out = run_engine(
            "connectfour.kif", "legal", ["--state", sf, "--role", "black"]
        )
        moves = json.loads(out)
        assert moves == ["noop"]

    def test_black_drops_on_turn(self):
        """Black can drop when it has control."""
        sf = _write_json(["(cell 4 1 red)", "(control black)"])
        out = run_engine(
            "connectfour.kif", "legal", ["--state", sf, "--role", "black"]
        )
        moves = json.loads(out)
        assert len(moves) == 8
        for i in range(1, 9):
            assert f"(drop {i})" in moves


class TestC4Next:
    def test_red_drops_empty_column(self):
        """Dropping into empty column places piece at row 1."""
        sf = _write_json(["(control red)"])
        mf = _write_json({"red": "(drop 4)", "black": "noop"})
        out = run_engine("connectfour.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert sorted(state) == ["(cell 4 1 red)", "(control black)"]

    def test_gravity_stacking(self):
        """Dropping into occupied column stacks on top."""
        sf = _write_json(["(cell 4 1 red)", "(control black)"])
        mf = _write_json({"red": "noop", "black": "(drop 4)"})
        out = run_engine("connectfour.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert sorted(state) == [
            "(cell 4 1 red)", "(cell 4 2 black)", "(control red)"
        ]

    def test_gravity_triple_stack(self):
        """Third piece in same column goes to row 3."""
        sf = _write_json(
            ["(cell 4 1 red)", "(cell 4 2 black)", "(control red)"]
        )
        mf = _write_json({"red": "(drop 4)", "black": "noop"})
        out = run_engine("connectfour.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert "(cell 4 3 red)" in state
        assert "(cell 4 1 red)" in state
        assert "(cell 4 2 black)" in state

    def test_different_columns(self):
        """Drops in different columns are independent."""
        sf = _write_json(["(cell 4 1 red)", "(control black)"])
        mf = _write_json({"red": "noop", "black": "(drop 1)"})
        out = run_engine("connectfour.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert "(cell 1 1 black)" in state
        assert "(cell 4 1 red)" in state
        assert "(control red)" in state


class TestC4Terminal:
    def test_not_terminal_initial(self):
        sf = _write_json(["(control red)"])
        out = run_engine("connectfour.kif", "terminal", ["--state", sf])
        assert out == "false"

    def test_terminal_horizontal_line(self):
        """4 in a row horizontally is terminal."""
        state = [
            "(cell 1 1 red)", "(cell 2 1 red)",
            "(cell 3 1 red)", "(cell 4 1 red)",
            "(cell 5 1 black)", "(cell 6 1 black)", "(cell 7 1 black)",
            "(control black)",
        ]
        sf = _write_json(state)
        out = run_engine("connectfour.kif", "terminal", ["--state", sf])
        assert out == "true"

    def test_terminal_vertical_line(self):
        """4 in a row vertically is terminal."""
        state = [
            "(cell 1 1 red)", "(cell 1 2 red)",
            "(cell 1 3 red)", "(cell 1 4 red)",
            "(cell 2 1 black)", "(cell 2 2 black)", "(cell 2 3 black)",
            "(control black)",
        ]
        sf = _write_json(state)
        out = run_engine("connectfour.kif", "terminal", ["--state", sf])
        assert out == "true"

    def test_not_terminal_three_in_row(self):
        """3 in a row is NOT terminal."""
        state = [
            "(cell 1 1 red)", "(cell 2 1 red)", "(cell 3 1 red)",
            "(cell 4 1 black)", "(cell 5 1 black)",
            "(control red)",
        ]
        sf = _write_json(state)
        out = run_engine("connectfour.kif", "terminal", ["--state", sf])
        assert out == "false"


class TestC4Goal:
    def test_red_wins(self):
        state = [
            "(cell 1 1 red)", "(cell 2 1 red)",
            "(cell 3 1 red)", "(cell 4 1 red)",
            "(cell 5 1 black)", "(cell 6 1 black)", "(cell 7 1 black)",
            "(control black)",
        ]
        sf = _write_json(state)
        out = run_engine(
            "connectfour.kif", "goal", ["--state", sf, "--role", "red"]
        )
        assert out == "100"
        out = run_engine(
            "connectfour.kif", "goal", ["--state", sf, "--role", "black"]
        )
        assert out == "0"

    def test_in_progress_goal(self):
        """Mid-game with no lines and open board -> both get 0."""
        sf = _write_json(["(cell 4 1 red)", "(control black)"])
        out = run_engine(
            "connectfour.kif", "goal", ["--state", sf, "--role", "red"]
        )
        assert out == "0"
        out = run_engine(
            "connectfour.kif", "goal", ["--state", sf, "--role", "black"]
        )
        assert out == "0"


class TestC4MultiStep:
    def test_build_horizontal_win(self):
        """Simulate red building 4-in-a-row over multiple turns."""
        state = ["(control red)"]

        # Red drops col 1
        sf = _write_json(state)
        mf = _write_json({"red": "(drop 1)", "black": "noop"})
        out = run_engine("connectfour.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert "(cell 1 1 red)" in state
        assert "(control black)" in state

        # Black drops col 5
        sf = _write_json(state)
        mf = _write_json({"red": "noop", "black": "(drop 5)"})
        out = run_engine("connectfour.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert "(cell 5 1 black)" in state

        # Red drops col 2
        sf = _write_json(state)
        mf = _write_json({"red": "(drop 2)", "black": "noop"})
        out = run_engine("connectfour.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert "(cell 2 1 red)" in state

        # Black drops col 5 (stacks to row 2)
        sf = _write_json(state)
        mf = _write_json({"red": "noop", "black": "(drop 5)"})
        out = run_engine("connectfour.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert "(cell 5 2 black)" in state
        assert "(cell 5 1 black)" in state

        # Red drops col 3
        sf = _write_json(state)
        mf = _write_json({"red": "(drop 3)", "black": "noop"})
        out = run_engine("connectfour.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert "(cell 3 1 red)" in state

        # Not terminal yet (only 3 in row for red)
        sf = _write_json(state)
        out = run_engine("connectfour.kif", "terminal", ["--state", sf])
        assert out == "false"

        # Black drops col 5 (stacks to row 3)
        mf = _write_json({"red": "noop", "black": "(drop 5)"})
        out = run_engine("connectfour.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert "(cell 5 3 black)" in state

        # Red drops col 4 -> 4 in a row!
        sf = _write_json(state)
        mf = _write_json({"red": "(drop 4)", "black": "noop"})
        out = run_engine("connectfour.kif", "next", ["--state", sf, "--moves", mf])
        state = json.loads(out)
        assert "(cell 4 1 red)" in state

        # Now terminal
        sf = _write_json(state)
        out = run_engine("connectfour.kif", "terminal", ["--state", sf])
        assert out == "true"

        # Red wins
        out = run_engine(
            "connectfour.kif", "goal", ["--state", sf, "--role", "red"]
        )
        assert out == "100"
        out = run_engine(
            "connectfour.kif", "goal", ["--state", sf, "--role", "black"]
        )
        assert out == "0"
