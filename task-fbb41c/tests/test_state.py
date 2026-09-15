
import sys
import os
import subprocess
import json

sys.path.insert(0, '/app')

import pytest


# ---------------------------------------------------------------------------
# Fixtures — transpile games once per session, build query engines per test
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def ttt_pl():
    from gdl_transpiler import transpile
    pl = '/tmp/test_ttt.pl'
    transpile('/app/games/ticTacToe.kif', pl)
    return pl


@pytest.fixture(scope='session')
def c4_pl():
    from gdl_transpiler import transpile
    pl = '/tmp/test_c4.pl'
    transpile('/app/games/connectFour.kif', pl)
    return pl


@pytest.fixture(scope='session')
def bt_pl():
    from gdl_transpiler import transpile
    pl = '/tmp/test_bt.pl'
    transpile('/app/games/breakthrough.kif', pl)
    return pl


@pytest.fixture
def ttt(ttt_pl):
    from gdl_query import GdlQueryEngine
    return GdlQueryEngine(ttt_pl)


@pytest.fixture
def c4(c4_pl):
    from gdl_query import GdlQueryEngine
    return GdlQueryEngine(c4_pl)


@pytest.fixture
def bt(bt_pl):
    from gdl_query import GdlQueryEngine
    return GdlQueryEngine(bt_pl)


@pytest.fixture(scope='session')
def c4_exploration(c4_pl):
    """Run game tree exploration once for all visualization tests."""
    from game_explorer import explore_and_visualize
    prefix = '/tmp/test_c4_explore'
    explore_and_visualize(
        c4_pl, 1,
        prefix + '.dot', prefix + '.svg', prefix + '.json',
    )
    return prefix


# ---------------------------------------------------------------------------
# Transpilation validity — swipl must load each .pl without errors
# ---------------------------------------------------------------------------

def test_transpile_ttt_valid(ttt_pl):
    r = subprocess.run(
        ['swipl', '-l', ttt_pl, '-g', 'halt'],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0, f"swipl failed: {r.stderr}"


def test_transpile_c4_valid(c4_pl):
    r = subprocess.run(
        ['swipl', '-l', c4_pl, '-g', 'halt'],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0, f"swipl failed: {r.stderr}"


def test_transpile_bt_valid(bt_pl):
    r = subprocess.run(
        ['swipl', '-l', bt_pl, '-g', 'halt'],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0, f"swipl failed: {r.stderr}"


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

def test_roles_ttt(ttt):
    roles = ttt.get_roles()
    assert set(roles) == {"xplayer", "oplayer"}
    assert len(roles) == 2


def test_roles_c4(c4):
    roles = c4.get_roles()
    assert set(roles) == {"red", "black"}
    assert len(roles) == 2


def test_roles_bt(bt):
    roles = bt.get_roles()
    assert set(roles) == {"white", "black"}
    assert len(roles) == 2


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

def test_initial_state_ttt(ttt):
    state = ttt.get_initial_state()
    assert len(state) == 10
    for r in range(1, 4):
        for c in range(1, 4):
            assert ("cell", str(r), str(c), "b") in state
    assert ("step", "1") in state


def test_initial_state_c4(c4):
    state = c4.get_initial_state()
    assert state == frozenset({("control", "red")})


def test_initial_state_bt(bt):
    state = bt.get_initial_state()
    assert len(state) == 33
    for x in range(1, 9):
        assert ("cellHolds", str(x), "1", "white") in state
        assert ("cellHolds", str(x), "2", "white") in state
        assert ("cellHolds", str(x), "7", "black") in state
        assert ("cellHolds", str(x), "8", "black") in state
    assert ("control", "white") in state


# ---------------------------------------------------------------------------
# Legal moves
# ---------------------------------------------------------------------------

def test_legal_moves_ttt_initial(ttt):
    state = ttt.get_initial_state()
    x_moves = ttt.get_legal_moves(state, "xplayer")
    o_moves = ttt.get_legal_moves(state, "oplayer")
    assert len(x_moves) == 9
    assert len(o_moves) == 9
    assert ("mark", "1", "1") in x_moves
    assert ("mark", "3", "3") in x_moves
    assert ("mark", "2", "2") in o_moves


def test_legal_moves_c4_initial(c4):
    state = c4.get_initial_state()
    red_moves = c4.get_legal_moves(state, "red")
    black_moves = c4.get_legal_moves(state, "black")
    assert len(red_moves) == 8
    for col in range(1, 9):
        assert ("drop", str(col)) in red_moves
    assert black_moves == {("noop",)}


def test_legal_moves_bt_initial(bt):
    state = bt.get_initial_state()
    white_moves = bt.get_legal_moves(state, "white")
    black_moves = bt.get_legal_moves(state, "black")
    # 8 forward from row 2 + 7 diag-right + 7 diag-left = 22
    assert len(white_moves) == 22
    assert ("move", "1", "2", "1", "3") in white_moves
    assert ("move", "1", "2", "2", "3") in white_moves
    assert ("move", "8", "2", "7", "3") in white_moves
    assert black_moves == {("noop",)}


# ---------------------------------------------------------------------------
# Next state
# ---------------------------------------------------------------------------

def test_next_state_ttt(ttt):
    state = ttt.get_initial_state()
    moves = {"xplayer": ("mark", "1", "1"), "oplayer": ("mark", "2", "2")}
    ns = ttt.get_next_state(state, moves)
    assert len(ns) == 10
    assert ("cell", "1", "1", "x") in ns
    assert ("cell", "2", "2", "o") in ns
    assert ("step", "2") in ns
    for r, c in [(1, 2), (1, 3), (2, 1), (2, 3), (3, 1), (3, 2), (3, 3)]:
        assert ("cell", str(r), str(c), "b") in ns


def test_next_state_c4_first_drop(c4):
    state = c4.get_initial_state()
    moves = {"red": ("drop", "4"), "black": ("noop",)}
    ns = c4.get_next_state(state, moves)
    assert len(ns) == 2
    assert ("cell", "4", "1", "red") in ns
    assert ("control", "black") in ns


def test_next_state_c4_stacking(c4):
    state = frozenset({("cell", "4", "1", "red"), ("control", "black")})
    moves = {"red": ("noop",), "black": ("drop", "4")}
    ns = c4.get_next_state(state, moves)
    assert len(ns) == 3
    assert ("cell", "4", "1", "red") in ns
    assert ("cell", "4", "2", "black") in ns
    assert ("control", "red") in ns


def test_next_state_bt_move(bt):
    state = bt.get_initial_state()
    moves = {"white": ("move", "3", "2", "3", "3"), "black": ("noop",)}
    ns = bt.get_next_state(state, moves)
    assert len(ns) == 33
    assert ("cellHolds", "3", "3", "white") in ns
    assert ("cellHolds", "3", "2", "white") not in ns
    assert ("control", "black") in ns
    for x in range(1, 9):
        assert ("cellHolds", str(x), "1", "white") in ns


# ---------------------------------------------------------------------------
# Terminal detection
# ---------------------------------------------------------------------------

def test_not_terminal_c4(c4):
    assert not c4.is_terminal(c4.get_initial_state())


def test_not_terminal_ttt(ttt):
    assert not ttt.is_terminal(ttt.get_initial_state())


def test_not_terminal_bt(bt):
    assert not bt.is_terminal(bt.get_initial_state())


def test_terminal_c4_vertical_line(c4):
    state = frozenset({
        ("cell", "1", "1", "red"), ("cell", "1", "2", "red"),
        ("cell", "1", "3", "red"), ("cell", "1", "4", "red"),
        ("cell", "2", "1", "black"), ("cell", "2", "2", "black"),
        ("cell", "2", "3", "black"),
        ("control", "black"),
    })
    assert c4.is_terminal(state)


# ---------------------------------------------------------------------------
# Goal values
# ---------------------------------------------------------------------------

def test_goal_c4_red_wins(c4):
    state = frozenset({
        ("cell", "1", "1", "red"), ("cell", "1", "2", "red"),
        ("cell", "1", "3", "red"), ("cell", "1", "4", "red"),
        ("cell", "2", "1", "black"), ("cell", "2", "2", "black"),
        ("cell", "2", "3", "black"),
        ("control", "black"),
    })
    assert c4.get_goal(state, "red") == 100
    assert c4.get_goal(state, "black") == 0


# ---------------------------------------------------------------------------
# Full playthrough
# ---------------------------------------------------------------------------

def test_ttt_playthrough_x_wins(ttt):
    s = ttt.get_initial_state()
    s = ttt.get_next_state(s, {
        "xplayer": ("mark", "1", "1"), "oplayer": ("mark", "2", "1"),
    })
    assert not ttt.is_terminal(s)
    s = ttt.get_next_state(s, {
        "xplayer": ("mark", "1", "2"), "oplayer": ("mark", "3", "1"),
    })
    assert not ttt.is_terminal(s)
    s = ttt.get_next_state(s, {
        "xplayer": ("mark", "1", "3"), "oplayer": ("mark", "3", "2"),
    })
    assert ttt.is_terminal(s)
    assert ttt.get_goal(s, "xplayer") == 100
    assert ttt.get_goal(s, "oplayer") == 0


# ---------------------------------------------------------------------------
# Edge case: simultaneous same-cell mark in TicTacToe
# ---------------------------------------------------------------------------

def test_ttt_simultaneous_same_cell(ttt):
    s = ttt.get_initial_state()
    moves = {"xplayer": ("mark", "2", "2"), "oplayer": ("mark", "2", "2")}
    ns = ttt.get_next_state(s, moves)
    assert ("cell", "2", "2", "b") in ns
    assert len(ns) == 10


# ---------------------------------------------------------------------------
# DOT / SVG / Graphviz visualization
# ---------------------------------------------------------------------------

def test_dot_file_valid(c4_exploration):
    dot_path = c4_exploration + '.dot'
    assert os.path.exists(dot_path)
    r = subprocess.run(
        ['dot', '-Tsvg', '-o', '/dev/null', dot_path],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0, f"dot validation failed: {r.stderr}"


def test_svg_generated(c4_exploration):
    svg_path = c4_exploration + '.svg'
    assert os.path.exists(svg_path), "SVG not generated"
    assert os.path.getsize(svg_path) > 100, "SVG too small"


# ---------------------------------------------------------------------------
# Analysis JSON (Connect Four depth 1)
# ---------------------------------------------------------------------------

def test_analysis_json_structure(c4_exploration):
    json_path = c4_exploration + '.json'
    assert os.path.exists(json_path)
    with open(json_path) as f:
        analysis = json.load(f)
    assert set(analysis['roles']) == {'red', 'black'}
    assert analysis['total_states'] == 9
    assert analysis['total_transitions'] == 8
    assert analysis['depth'] == 1
    assert analysis['terminal_states_found'] == 0
    assert analysis['branching_factor'] == 8.0
