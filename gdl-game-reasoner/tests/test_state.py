
"""Tests for GDL Game Engine — verifies Python reasoner, Prolog compiler,
and maze optimal solution across three structurally different GDL games."""

import sys
import os
import json
import subprocess

import pytest

sys.path.insert(0, "/app")

from gdl_reasoner import GDLReasoner


# ======================== Fixtures ========================

@pytest.fixture
def ttt():
    return GDLReasoner.from_file("/app/games/tictictoe.kif")

@pytest.fixture
def c4():
    return GDLReasoner.from_file("/app/games/connectFour.kif")

@pytest.fixture
def maze():
    return GDLReasoner.from_file("/app/games/maze.kif")


# ======================== Role extraction ========================

def test_ttt_roles(ttt):
    roles = ttt.get_roles()
    assert set(roles) == {"xplayer", "oplayer"}
    assert len(roles) == 2

def test_c4_roles(c4):
    roles = c4.get_roles()
    assert set(roles) == {"red", "black"}
    assert len(roles) == 2

def test_maze_roles(maze):
    roles = maze.get_roles()
    assert roles == ["robot"]


# ======================== Initial state ========================

def test_ttt_initial(ttt):
    state = ttt.get_initial_state()
    assert len(state) == 10  # 9 blank cells + step 1
    assert "(cell 1 1 b)" in state
    assert "(cell 2 2 b)" in state
    assert "(cell 3 3 b)" in state
    assert "(step 1)" in state

def test_c4_initial(c4):
    state = c4.get_initial_state()
    assert "(control red)" in state
    assert len(state) == 1

def test_maze_initial(maze):
    state = maze.get_initial_state()
    assert "(cell a)" in state
    assert "(gold c)" in state
    assert "(step 1)" in state
    assert len(state) == 3


# ======================== Legal moves ========================

def test_ttt_legal_initial(ttt):
    state = ttt.get_initial_state()
    x_moves = ttt.get_legal_moves(state, "xplayer")
    o_moves = ttt.get_legal_moves(state, "oplayer")
    assert len(x_moves) == 9
    assert len(o_moves) == 9
    assert "(mark 1 1)" in x_moves
    assert "(mark 2 2)" in x_moves
    assert "(mark 3 3)" in x_moves

def test_maze_legal_initial(maze):
    state = maze.get_initial_state()
    moves = maze.get_legal_moves(state, "robot")
    assert "move" in moves
    assert "grab" not in moves  # robot at a, gold at c — different locations
    assert "drop" not in moves  # gold not in inventory

def test_c4_legal_initial(c4):
    state = c4.get_initial_state()
    red_moves = c4.get_legal_moves(state, "red")
    black_moves = c4.get_legal_moves(state, "black")
    # Red has control: can drop in any of 8 columns
    assert len(red_moves) == 8
    assert "(drop 1)" in red_moves
    assert "(drop 8)" in red_moves
    # Black must noop when red has control
    assert len(black_moves) == 1
    assert "noop" in black_moves


# ======================== State transitions ========================

def test_maze_move(maze):
    state = maze.get_initial_state()
    # Robot at a, adjacent a b -> moves to b
    nxt = maze.get_next_state(state, {"robot": "move"})
    assert "(cell b)" in nxt
    assert "(cell a)" not in nxt
    assert "(gold c)" in nxt
    assert "(step 2)" in nxt
    assert len(nxt) == 3

def test_c4_drop(c4):
    state = c4.get_initial_state()
    nxt = c4.get_next_state(state, {"red": "(drop 4)", "black": "noop"})
    assert "(cell 4 1 red)" in nxt
    assert "(control black)" in nxt
    assert "(control red)" not in nxt

def test_ttt_move(ttt):
    state = ttt.get_initial_state()
    nxt = ttt.get_next_state(state, {
        "xplayer": "(mark 2 2)",
        "oplayer": "(mark 1 1)"
    })
    assert "(cell 2 2 x)" in nxt
    assert "(cell 1 1 o)" in nxt
    assert "(step 2)" in nxt
    # Unaffected cells stay blank
    assert "(cell 1 2 b)" in nxt
    assert "(cell 3 3 b)" in nxt
    assert len(nxt) == 10


# ======================== Terminal detection ========================

def test_ttt_not_terminal_initial(ttt):
    assert not ttt.is_terminal(ttt.get_initial_state())

def test_c4_not_terminal_initial(c4):
    assert not c4.is_terminal(c4.get_initial_state())

def test_maze_not_terminal_initial(maze):
    assert not maze.is_terminal(maze.get_initial_state())

def test_ttt_terminal_line(ttt):
    state = frozenset({
        "(cell 1 1 x)", "(cell 1 2 x)", "(cell 1 3 x)",
        "(cell 2 1 o)", "(cell 2 2 o)", "(cell 2 3 b)",
        "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 b)",
        "(step 5)"
    })
    assert ttt.is_terminal(state)

def test_maze_terminal_step(maze):
    state = frozenset({"(cell d)", "(gold c)", "(step 10)"})
    assert maze.is_terminal(state)

def test_maze_terminal_gold(maze):
    state = frozenset({"(cell a)", "(gold a)", "(step 5)"})
    assert maze.is_terminal(state)


# ======================== Goal computation ========================

def test_ttt_goal_x_wins(ttt):
    state = frozenset({
        "(cell 1 1 x)", "(cell 1 2 x)", "(cell 1 3 x)",
        "(cell 2 1 o)", "(cell 2 2 o)", "(cell 2 3 b)",
        "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 b)",
        "(step 5)"
    })
    assert ttt.get_goal(state, "xplayer") == 100
    assert ttt.get_goal(state, "oplayer") == 0

def test_maze_goal_success(maze):
    state = frozenset({"(cell a)", "(gold a)", "(step 5)"})
    assert maze.get_goal(state, "robot") == 100

def test_maze_goal_failure(maze):
    state = frozenset({"(cell d)", "(gold c)", "(step 10)"})
    assert maze.get_goal(state, "robot") == 0


# ======================== Multi-step simulation ========================

def test_maze_full_simulation(maze):
    """Simulate: move(a->b), move(b->c), grab, move(c->d), move(d->a), drop
    -> gold at a -> terminal -> goal 100"""
    state = maze.get_initial_state()

    # Step 1: move a -> b
    state = maze.get_next_state(state, {"robot": "move"})
    assert "(cell b)" in state
    assert not maze.is_terminal(state)

    # Step 2: move b -> c
    state = maze.get_next_state(state, {"robot": "move"})
    assert "(cell c)" in state

    # Grab should now be legal (robot at c, gold at c)
    moves = maze.get_legal_moves(state, "robot")
    assert "grab" in moves

    # Step 3: grab
    state = maze.get_next_state(state, {"robot": "grab"})
    assert "(gold i)" in state
    assert "(gold c)" not in state

    # Step 4: move c -> d
    state = maze.get_next_state(state, {"robot": "move"})
    assert "(cell d)" in state
    assert "(gold i)" in state

    # Step 5: move d -> a
    state = maze.get_next_state(state, {"robot": "move"})
    assert "(cell a)" in state
    assert "(gold i)" in state

    # Drop should now be legal
    moves = maze.get_legal_moves(state, "robot")
    assert "drop" in moves

    # Step 6: drop
    state = maze.get_next_state(state, {"robot": "drop"})
    assert "(gold a)" in state
    assert maze.is_terminal(state)
    assert maze.get_goal(state, "robot") == 100

def test_c4_multi_step(c4):
    """Play 3 moves in Connect Four: red col 1, black col 1, red col 2."""
    state = c4.get_initial_state()

    # Red drops column 1 (row 1, empty column)
    state = c4.get_next_state(state, {"red": "(drop 1)", "black": "noop"})
    assert "(cell 1 1 red)" in state
    assert "(control black)" in state

    # Black drops column 1 (stacks on top -> row 2)
    state = c4.get_next_state(state, {"red": "noop", "black": "(drop 1)"})
    assert "(cell 1 1 red)" in state  # persists
    assert "(cell 1 2 black)" in state
    assert "(control red)" in state

    # Red drops column 2 (row 1, empty column)
    state = c4.get_next_state(state, {"red": "(drop 2)", "black": "noop"})
    assert "(cell 2 1 red)" in state
    assert "(cell 1 1 red)" in state  # still persists
    assert "(cell 1 2 black)" in state  # still persists


# ======================== Negation and board analysis ========================

def test_c4_board_not_terminal(c4):
    """Sparse board: no line, board open -> not terminal."""
    state = frozenset({
        "(cell 1 1 red)", "(cell 2 1 black)",
        "(cell 3 1 red)", "(control black)"
    })
    assert not c4.is_terminal(state)

def test_c4_terminal_line(c4):
    """Red has 4 in a row horizontally -> terminal, red wins."""
    state = frozenset({
        "(cell 1 1 red)", "(cell 2 1 red)",
        "(cell 3 1 red)", "(cell 4 1 red)",
        "(cell 5 1 black)", "(cell 6 1 black)",
        "(cell 7 1 black)",
        "(control black)"
    })
    assert c4.is_terminal(state)
    assert c4.get_goal(state, "red") == 100
    assert c4.get_goal(state, "black") == 0

def test_c4_goal_in_progress(c4):
    """Mid-game with no lines and open board -> goal 0 for both."""
    state = frozenset({
        "(cell 1 1 red)", "(cell 2 1 black)",
        "(control red)"
    })
    assert c4.get_goal(state, "red") == 0
    assert c4.get_goal(state, "black") == 0


# ======================== Simultaneous moves ========================

def test_ttt_simultaneous_conflict(ttt):
    """When both players mark the same cell, it stays blank."""
    state = ttt.get_initial_state()
    nxt = ttt.get_next_state(state, {
        "xplayer": "(mark 2 2)",
        "oplayer": "(mark 2 2)"
    })
    assert "(cell 2 2 b)" in nxt
    assert "(cell 2 2 x)" not in nxt
    assert "(cell 2 2 o)" not in nxt
    assert "(step 2)" in nxt

def test_ttt_draw(ttt):
    """At step 7 with no lines: terminal with draw (goal 50 each)."""
    state = frozenset({
        "(cell 1 1 x)", "(cell 1 2 o)", "(cell 1 3 x)",
        "(cell 2 1 o)", "(cell 2 2 x)", "(cell 2 3 o)",
        "(cell 3 1 b)", "(cell 3 2 b)", "(cell 3 3 b)",
        "(step 7)"
    })
    assert ttt.is_terminal(state)
    assert ttt.get_goal(state, "xplayer") == 50
    assert ttt.get_goal(state, "oplayer") == 50


# ======================== Legal moves change with state ========================

def test_maze_grab_becomes_legal(maze):
    """After moving to the gold location, grab becomes legal."""
    state = frozenset({"(cell c)", "(gold c)", "(step 3)"})
    moves = maze.get_legal_moves(state, "robot")
    assert "grab" in moves
    assert "move" in moves

def test_maze_drop_becomes_legal(maze):
    """With gold in inventory, drop becomes legal."""
    state = frozenset({"(cell a)", "(gold i)", "(step 6)"})
    moves = maze.get_legal_moves(state, "robot")
    assert "drop" in moves
    assert "move" in moves
    assert "grab" not in moves


# ======================== Prolog compilation helpers ========================

_PL_CACHE = {}

def _compile_to_prolog(kif_path):
    """Compile a KIF file to Prolog and return the .pl path (cached)."""
    if kif_path not in _PL_CACHE:
        pl_path = f"/tmp/gdl_{os.path.basename(kif_path).replace('.kif', '.pl')}"
        result = subprocess.run(
            ["python3", "/app/gdl2prolog.py", kif_path, pl_path],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"gdl2prolog.py failed: {result.stderr}"
        assert os.path.exists(pl_path), f"Output file {pl_path} not created"
        _PL_CACHE[kif_path] = pl_path
    return _PL_CACHE[kif_path]


def _swipl(pl_path, query):
    """Run a SWI-Prolog query and return stdout."""
    result = subprocess.run(
        ["swipl", "-g", query, pl_path],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"swipl failed (rc={result.returncode}): {result.stderr}"
    return result.stdout.strip()


# ======================== Prolog compilation: roles ========================

def test_prolog_maze_roles():
    pl = _compile_to_prolog("/app/games/maze.kif")
    out = _swipl(pl, "findall(X, role(X), L), sort(L, S), write(S), nl, halt")
    assert "robot" in out

def test_prolog_c4_roles():
    pl = _compile_to_prolog("/app/games/connectFour.kif")
    out = _swipl(pl, "findall(X, role(X), L), sort(L, S), write(S), nl, halt")
    assert "red" in out
    assert "black" in out

def test_prolog_ttt_roles():
    pl = _compile_to_prolog("/app/games/tictictoe.kif")
    out = _swipl(pl, "findall(X, role(X), L), sort(L, S), write(S), nl, halt")
    assert "xplayer" in out
    assert "oplayer" in out


# ======================== Prolog compilation: initial state ========================

def test_prolog_maze_init():
    pl = _compile_to_prolog("/app/games/maze.kif")
    out = _swipl(pl, "findall(X, init(X), L), sort(L, S), write(S), nl, halt")
    assert "cell(a)" in out
    assert "gold(c)" in out
    assert "step(1)" in out

def test_prolog_c4_init():
    pl = _compile_to_prolog("/app/games/connectFour.kif")
    out = _swipl(pl, "findall(X, init(X), L), sort(L, S), write(S), nl, halt")
    assert "control(red)" in out


# ======================== Prolog compilation: legal moves ========================

def test_prolog_maze_legal():
    pl = _compile_to_prolog("/app/games/maze.kif")
    query = (
        "assert(true(cell(a))), assert(true(gold(c))), assert(true(step(1))), "
        "findall(M, legal(robot, M), L), sort(L, S), write(S), nl, halt"
    )
    out = _swipl(pl, query)
    assert "move" in out
    assert "grab" not in out

def test_prolog_c4_legal_count():
    pl = _compile_to_prolog("/app/games/connectFour.kif")
    query = (
        "assert(true(control(red))), "
        "findall(M, legal(red, M), L), sort(L, S), length(S, N), write(N), nl, halt"
    )
    out = _swipl(pl, query)
    assert out == "8"


# ======================== Prolog compilation: terminal ========================

def test_prolog_maze_terminal():
    pl = _compile_to_prolog("/app/games/maze.kif")
    query = (
        "assert(true(cell(d))), assert(true(gold(c))), assert(true(step(10))), "
        "(terminal -> write(yes) ; write(no)), nl, halt"
    )
    out = _swipl(pl, query)
    assert "yes" in out

def test_prolog_maze_goal():
    pl = _compile_to_prolog("/app/games/maze.kif")
    query = (
        "assert(true(cell(a))), assert(true(gold(a))), assert(true(step(5))), "
        "findall(V, goal(robot, V), L), write(L), nl, halt"
    )
    out = _swipl(pl, query)
    assert "100" in out


# ======================== Maze solution ========================

def test_maze_solution_structure():
    path = "/app/maze_solution.json"
    assert os.path.exists(path), "maze_solution.json not found"
    with open(path) as f:
        sol = json.load(f)
    assert "actions" in sol
    assert "final_goal" in sol
    assert "total_steps" in sol
    assert sol["final_goal"] == 100
    assert isinstance(sol["actions"], list)
    assert sol["total_steps"] == len(sol["actions"])

def test_maze_solution_optimal():
    """Verify the solution is valid and optimal (6 steps)."""
    with open("/app/maze_solution.json") as f:
        sol = json.load(f)

    assert sol["total_steps"] == 6, f"Solution has {sol['total_steps']} steps, optimal is 6"

    # Replay the solution to verify correctness
    r = GDLReasoner.from_file("/app/games/maze.kif")
    state = r.get_initial_state()

    for i, action in enumerate(sol["actions"]):
        assert not r.is_terminal(state), f"Terminal before action {i}: {action}"
        legal = r.get_legal_moves(state, "robot")
        assert action in legal, f"Action '{action}' not legal at step {i}; legal: {legal}"
        state = r.get_next_state(state, {"robot": action})

    assert r.is_terminal(state), "Not terminal after all actions"
    assert r.get_goal(state, "robot") == 100, f"Goal {r.get_goal(state, 'robot')} != 100"
