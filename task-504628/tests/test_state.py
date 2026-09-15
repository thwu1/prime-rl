
import sys
import os
import subprocess
sys.path.insert(0, '/app')
import pytest
from gdl_reasoner import GDLReasoner


# ============================================================
# GDL Reasoner Tests — game state computation correctness
# ============================================================

class TestMazeGame:
    """Tests for the single-player maze puzzle game."""

    @pytest.fixture
    def reasoner(self):
        return GDLReasoner('/app/games/maze.kif')

    def test_roles(self, reasoner):
        assert reasoner.get_roles() == ['robot']

    def test_initial_state(self, reasoner):
        state = reasoner.get_initial_state()
        assert state == {'(cell a)', '(gold c)', '(step 1)'}

    def test_initial_legal_moves(self, reasoner):
        state = reasoner.get_initial_state()
        legal = reasoner.get_legal_moves(state)
        assert 'robot' in legal
        assert 'move' in legal['robot']
        assert 'grab' not in legal['robot']
        assert 'drop' not in legal['robot']

    def test_not_terminal_initially(self, reasoner):
        state = reasoner.get_initial_state()
        assert not reasoner.is_terminal(state)

    def test_move_transition(self, reasoner):
        state = reasoner.get_initial_state()
        state = reasoner.get_next_state(state, {'robot': 'move'})
        assert '(cell b)' in state
        assert '(gold c)' in state
        assert '(step 2)' in state
        assert len(state) == 3

    def test_grab_at_gold_location(self, reasoner):
        state = reasoner.get_initial_state()
        # move a->b, move b->c
        state = reasoner.get_next_state(state, {'robot': 'move'})
        state = reasoner.get_next_state(state, {'robot': 'move'})
        assert '(cell c)' in state and '(gold c)' in state
        # grab should be legal now
        legal = reasoner.get_legal_moves(state)
        assert 'grab' in legal['robot']
        state = reasoner.get_next_state(state, {'robot': 'grab'})
        assert '(gold i)' in state
        assert '(gold c)' not in state

    def test_full_simulation_to_goal(self, reasoner):
        """Simulate: move->move->grab->move->move->drop => terminal with goal 100."""
        state = reasoner.get_initial_state()
        moves_seq = ['move', 'move', 'grab', 'move', 'move', 'drop']
        for m in moves_seq:
            state = reasoner.get_next_state(state, {'robot': m})
        assert '(gold a)' in state
        assert '(cell a)' in state
        assert reasoner.is_terminal(state)
        goals = reasoner.get_goals(state)
        assert goals['robot'] == 100


class TestTicTacToe:
    """Tests for the simultaneous tic-tac-toe variant."""

    @pytest.fixture
    def reasoner(self):
        return GDLReasoner('/app/games/tictictoe.kif')

    def test_roles(self, reasoner):
        assert reasoner.get_roles() == ['oplayer', 'xplayer']

    def test_initial_state_size(self, reasoner):
        state = reasoner.get_initial_state()
        assert len(state) == 10  # 9 blank cells + step 1

    def test_initial_state_contents(self, reasoner):
        state = reasoner.get_initial_state()
        for r in range(1, 4):
            for c in range(1, 4):
                assert f'(cell {r} {c} b)' in state
        assert '(step 1)' in state

    def test_initial_legal_moves(self, reasoner):
        state = reasoner.get_initial_state()
        legal = reasoner.get_legal_moves(state)
        assert len(legal['xplayer']) == 9
        assert len(legal['oplayer']) == 9
        assert '(mark 1 1)' in legal['xplayer']
        assert '(mark 3 3)' in legal['oplayer']

    def test_simultaneous_move_different_cells(self, reasoner):
        state = reasoner.get_initial_state()
        state = reasoner.get_next_state(state, {
            'xplayer': '(mark 1 1)', 'oplayer': '(mark 3 3)'
        })
        assert '(cell 1 1 x)' in state
        assert '(cell 3 3 o)' in state
        assert '(cell 2 2 b)' in state
        assert '(step 2)' in state

    def test_simultaneous_move_same_cell_stays_blank(self, reasoner):
        """When both players mark the same cell, it stays blank."""
        state = reasoner.get_initial_state()
        state = reasoner.get_next_state(state, {
            'xplayer': '(mark 2 2)', 'oplayer': '(mark 2 2)'
        })
        assert '(cell 2 2 b)' in state
        assert '(cell 2 2 x)' not in state
        assert '(cell 2 2 o)' not in state

    def test_reduced_legal_moves_after_marks(self, reasoner):
        state = reasoner.get_initial_state()
        state = reasoner.get_next_state(state, {
            'xplayer': '(mark 1 1)', 'oplayer': '(mark 3 3)'
        })
        legal = reasoner.get_legal_moves(state)
        assert len(legal['xplayer']) == 7
        assert '(mark 1 1)' not in legal['xplayer']
        assert '(mark 3 3)' not in legal['xplayer']

    def test_x_wins_row(self, reasoner):
        """X wins by completing row 1 in 3 turns."""
        state = reasoner.get_initial_state()
        turns = [
            {'xplayer': '(mark 1 1)', 'oplayer': '(mark 2 1)'},
            {'xplayer': '(mark 1 2)', 'oplayer': '(mark 2 2)'},
            {'xplayer': '(mark 1 3)', 'oplayer': '(mark 3 1)'},
        ]
        for t in turns:
            state = reasoner.get_next_state(state, t)
        assert '(cell 1 1 x)' in state
        assert '(cell 1 2 x)' in state
        assert '(cell 1 3 x)' in state
        assert reasoner.is_terminal(state)
        goals = reasoner.get_goals(state)
        assert goals['xplayer'] == 100
        assert goals['oplayer'] == 0

    def test_not_terminal_after_one_turn(self, reasoner):
        state = reasoner.get_initial_state()
        state = reasoner.get_next_state(state, {
            'xplayer': '(mark 1 1)', 'oplayer': '(mark 3 3)'
        })
        assert not reasoner.is_terminal(state)


class TestConnectFour:
    """Tests for the Connect Four game."""

    @pytest.fixture
    def reasoner(self):
        return GDLReasoner('/app/games/connectfour.kif')

    def test_roles(self, reasoner):
        assert reasoner.get_roles() == ['black', 'red']

    def test_initial_state(self, reasoner):
        state = reasoner.get_initial_state()
        assert state == {'(control red)'}

    def test_initial_legal_moves(self, reasoner):
        state = reasoner.get_initial_state()
        legal = reasoner.get_legal_moves(state)
        assert len(legal['red']) == 8
        for col in range(1, 9):
            assert f'(drop {col})' in legal['red']
        assert legal['black'] == ['noop']

    def test_first_drop(self, reasoner):
        state = reasoner.get_initial_state()
        state = reasoner.get_next_state(state, {
            'red': '(drop 4)', 'black': 'noop'
        })
        assert '(cell 4 1 red)' in state
        assert '(control black)' in state
        assert '(control red)' not in state

    def test_gravity_stacking(self, reasoner):
        """Pieces stack: second drop in same column goes to row 2."""
        state = reasoner.get_initial_state()
        state = reasoner.get_next_state(state, {
            'red': '(drop 4)', 'black': 'noop'
        })
        state = reasoner.get_next_state(state, {
            'red': 'noop', 'black': '(drop 4)'
        })
        assert '(cell 4 1 red)' in state
        assert '(cell 4 2 black)' in state

    def test_control_alternates(self, reasoner):
        state = reasoner.get_initial_state()
        assert '(control red)' in state
        state = reasoner.get_next_state(state, {
            'red': '(drop 1)', 'black': 'noop'
        })
        assert '(control black)' in state
        state = reasoner.get_next_state(state, {
            'red': 'noop', 'black': '(drop 2)'
        })
        assert '(control red)' in state

    def test_not_terminal_initially(self, reasoner):
        state = reasoner.get_initial_state()
        assert not reasoner.is_terminal(state)

    def test_vertical_line_win(self, reasoner):
        """Red wins by stacking 4 in column 4."""
        state = reasoner.get_initial_state()
        moves = [
            {'red': '(drop 4)', 'black': 'noop'},
            {'red': 'noop', 'black': '(drop 5)'},
            {'red': '(drop 4)', 'black': 'noop'},
            {'red': 'noop', 'black': '(drop 5)'},
            {'red': '(drop 4)', 'black': 'noop'},
            {'red': 'noop', 'black': '(drop 5)'},
            {'red': '(drop 4)', 'black': 'noop'},
        ]
        for m in moves:
            state = reasoner.get_next_state(state, m)
        assert '(cell 4 1 red)' in state
        assert '(cell 4 2 red)' in state
        assert '(cell 4 3 red)' in state
        assert '(cell 4 4 red)' in state
        assert reasoner.is_terminal(state)
        goals = reasoner.get_goals(state)
        assert goals['red'] == 100
        assert goals['black'] == 0


# ============================================================
# Prolog Compilation Tests — swipl tool interop validation
# ============================================================

class TestPrologCompilation:
    """Tests that GDL-to-Prolog translation produces valid, queryable Prolog."""

    @pytest.fixture(autouse=True)
    def compile_all(self):
        from gdl_to_prolog import compile_to_prolog
        os.makedirs('/app/prolog', exist_ok=True)
        compile_to_prolog('/app/games/maze.kif', '/app/prolog/maze.pl')
        compile_to_prolog('/app/games/tictictoe.kif', '/app/prolog/tictictoe.pl')
        compile_to_prolog('/app/games/connectfour.kif', '/app/prolog/connectfour.pl')

    def _swipl(self, pl_file, goal):
        result = subprocess.run(
            ['swipl', '-g', goal, '-l', pl_file],
            capture_output=True, text=True, timeout=30
        )
        return result

    def test_maze_prolog_loads_without_error(self):
        r = self._swipl('/app/prolog/maze.pl', 'halt')
        assert r.returncode == 0, f'swipl failed to load maze.pl: {r.stderr}'

    def test_tictictoe_prolog_loads_without_error(self):
        r = self._swipl('/app/prolog/tictictoe.pl', 'halt')
        assert r.returncode == 0, f'swipl failed to load tictictoe.pl: {r.stderr}'

    def test_connectfour_prolog_loads_without_error(self):
        r = self._swipl('/app/prolog/connectfour.pl', 'halt')
        assert r.returncode == 0, f'swipl failed to load connectfour.pl: {r.stderr}'

    def test_maze_prolog_roles_query(self):
        r = self._swipl('/app/prolog/maze.pl',
            "findall(R, role(R), Rs), sort(Rs, S), write(S), halt")
        assert r.returncode == 0, f'query failed: {r.stderr}'
        assert 'robot' in r.stdout

    def test_maze_prolog_init_query(self):
        r = self._swipl('/app/prolog/maze.pl',
            "findall(P, init(P), Ps), write(Ps), halt")
        assert r.returncode == 0, f'query failed: {r.stderr}'
        assert 'cell(a)' in r.stdout
        assert 'gold(c)' in r.stdout
        assert 'step(1)' in r.stdout

    def test_maze_prolog_legal_crossval(self):
        """Cross-validate: Prolog legal moves match Python reasoner for maze init."""
        r = self._swipl('/app/prolog/maze.pl',
            "assert(true(cell(a))), assert(true(gold(c))), assert(true(step(1))), "
            "findall(M, legal(robot, M), Ms), sort(Ms, S), write(S), halt")
        assert r.returncode == 0, f'query failed: {r.stderr}'
        assert 'move' in r.stdout
        # grab requires robot at gold location (a != c), so not legal
        assert 'grab' not in r.stdout

    def test_connectfour_prolog_roles_query(self):
        r = self._swipl('/app/prolog/connectfour.pl',
            "findall(R, role(R), Rs), sort(Rs, S), write(S), halt")
        assert r.returncode == 0, f'query failed: {r.stderr}'
        assert 'black' in r.stdout
        assert 'red' in r.stdout

    def test_connectfour_prolog_legal_count_crossval(self):
        """Cross-validate: red has 8 legal drops in Connect Four initial state."""
        r = self._swipl('/app/prolog/connectfour.pl',
            "assert(true(control(red))), "
            "findall(M, legal(red, M), Ms), length(Ms, N), write(N), halt")
        assert r.returncode == 0, f'query failed: {r.stderr}'
        assert r.stdout.strip() == '8', f'Expected 8 legal moves, got: {r.stdout.strip()}'

    def test_tictictoe_prolog_legal_count_crossval(self):
        """Cross-validate: each player has 9 legal marks in tictictoe initial state."""
        assertions = ', '.join(
            f'assert(true(cell({r},{c},b)))' for r in range(1, 4) for c in range(1, 4)
        )
        r = self._swipl('/app/prolog/tictictoe.pl',
            f"{assertions}, assert(true(step(1))), "
            "findall(M, legal(xplayer, M), Ms), length(Ms, N), write(N), halt")
        assert r.returncode == 0, f'query failed: {r.stderr}'
        assert r.stdout.strip() == '9', f'Expected 9 legal moves, got: {r.stdout.strip()}'


# ============================================================
# State Graph Tests — Graphviz DOT/SVG tool interop validation
# ============================================================

class TestStateGraph:
    """Tests that state graph produces valid DOT compilable to SVG."""

    def test_maze_dot_file_created(self):
        from state_graph import generate_state_graph
        generate_state_graph('/app/games/maze.kif', '/app/graphs/maze.dot', max_depth=3)
        assert os.path.exists('/app/graphs/maze.dot'), 'DOT file not created'

    def test_maze_dot_valid_graphviz(self):
        """DOT file must be compilable by the graphviz dot command."""
        from state_graph import generate_state_graph
        generate_state_graph('/app/games/maze.kif', '/app/graphs/maze.dot', max_depth=3)
        result = subprocess.run(
            ['dot', '-Tsvg', '/app/graphs/maze.dot', '-o', '/tmp/maze_valid.svg'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f'dot command failed: {result.stderr}'

    def test_maze_dot_has_digraph_structure(self):
        from state_graph import generate_state_graph
        generate_state_graph('/app/games/maze.kif', '/app/graphs/maze.dot', max_depth=3)
        with open('/app/graphs/maze.dot') as f:
            content = f.read()
        assert 'digraph' in content, 'DOT must declare a digraph'
        edge_lines = [l for l in content.split('\n') if '->' in l]
        node_lines = [l for l in content.split('\n')
                      if 'label=' in l and '->' not in l]
        assert len(node_lines) >= 4, (
            f'Maze depth-3 should have at least 4 state nodes, found {len(node_lines)}'
        )
        assert len(edge_lines) >= 3, (
            f'Maze depth-3 should have at least 3 edges, found {len(edge_lines)}'
        )

    def test_maze_svg_rendered(self):
        """render_svg must produce a valid SVG file from a DOT file."""
        from state_graph import generate_state_graph, render_svg
        generate_state_graph('/app/games/maze.kif', '/app/graphs/maze.dot', max_depth=3)
        render_svg('/app/graphs/maze.dot', '/app/graphs/maze.svg')
        assert os.path.exists('/app/graphs/maze.svg'), 'SVG file not created'
        with open('/app/graphs/maze.svg') as f:
            svg_content = f.read()
        assert '<svg' in svg_content, 'Output file does not contain SVG markup'

    def test_connectfour_dot_valid(self):
        """Connect Four DOT (depth 1) must be compilable by dot."""
        from state_graph import generate_state_graph
        generate_state_graph(
            '/app/games/connectfour.kif', '/app/graphs/cf.dot', max_depth=1
        )
        assert os.path.exists('/app/graphs/cf.dot')
        result = subprocess.run(
            ['dot', '-Tsvg', '/app/graphs/cf.dot', '-o', '/tmp/cf_valid.svg'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f'dot command failed: {result.stderr}'
