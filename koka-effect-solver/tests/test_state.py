"""
Tests for algebraic effect handler engine, N-Queens solver, and handler composition.
"""

import subprocess
import sys
import importlib
import importlib.util
import os

KNOWN_QUEENS = {
    1: (1, [[1]]),
    4: (2, [[2, 4, 1, 3], [3, 1, 4, 2]]),
    5: (10, [1, 3, 5, 2, 4]),       # first solution only
    6: (4, [2, 4, 6, 1, 3, 5]),
    7: (40, [1, 3, 5, 7, 2, 4, 6]),
    8: (92, [1, 5, 8, 6, 3, 7, 2, 4]),
}


def _validate_queens_solution(solution, n):
    """Verify a single queens placement is valid."""
    assert isinstance(solution, list), f"Solution must be a list, got {type(solution)}"
    assert len(solution) == n, f"Solution has {len(solution)} queens, expected {n}"
    for val in solution:
        assert isinstance(val, int), f"Row position must be int, got {type(val)}: {val}"
        assert 1 <= val <= n, f"Row {val} out of range [1,{n}]"
    for i in range(n):
        for j in range(i + 1, n):
            assert solution[i] != solution[j], (
                f"Row conflict: cols {i+1} and {j+1} both at row {solution[i]}"
            )
            assert abs(solution[i] - solution[j]) != abs(i - j), (
                f"Diagonal conflict: ({solution[i]},{i+1}) and ({solution[j]},{j+1})"
            )


def _load_module(name):
    """Import a module from /app."""
    if '/app' not in sys.path:
        sys.path.insert(0, '/app')
    if name in sys.modules:
        importlib.reload(sys.modules[name])
    else:
        __import__(name)
    return sys.modules[name]


# ── Oracle tool tests ──────────────────────────────────────────────

def test_oracle_binary_exists():
    """Oracle binary is present and executable."""
    path = '/app/reference/effects_oracle'
    assert os.path.isfile(path), f"{path} not found"
    assert os.access(path, os.X_OK), f"{path} is not executable"


def test_oracle_list():
    """Oracle responds to --list with known scenarios."""
    result = subprocess.run(
        ['/app/reference/effects_oracle', '--list'],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"oracle --list failed: {result.stderr}"
    scenarios = set(result.stdout.strip().split('\n'))
    for s in ['queens', 'choice-xor', 'state-choice', 'choice-state', 'compose-triple']:
        assert s in scenarios, f"Scenario '{s}' missing from oracle --list"


def test_oracle_queens():
    """Oracle queens scenario matches known values."""
    result = subprocess.run(
        ['/app/reference/effects_oracle', 'queens', '8'],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"oracle queens 8 failed: {result.stderr}"
    lines = result.stdout.strip().split('\n')
    assert 'count:92' in lines, f"Expected count:92, got: {lines}"
    assert 'first:1,5,8,6,3,7,2,4' in lines, f"Expected first solution, got: {lines}"


# ── Output format test ──────────────────────────────────────────────

def test_solver_output():
    """Solver prints correct output when run directly."""
    result = subprocess.run(
        [sys.executable, '/app/solver.py'],
        capture_output=True, text=True, timeout=120, cwd='/app',
    )
    assert result.returncode == 0, f"solver.py failed:\n{result.stderr}"
    lines = result.stdout.strip().split('\n')
    assert len(lines) >= 4, f"Expected >=4 lines, got {len(lines)}:\n{result.stdout}"
    assert lines[0] == "queens(5): 10 solutions", f"Wrong line 0: {lines[0]}"
    assert lines[1] == "first: 1,3,5,2,4", f"Wrong line 1: {lines[1]}"
    assert lines[2] == "queens(8): 92 solutions", f"Wrong line 2: {lines[2]}"
    assert lines[3] == "first: 1,5,8,6,3,7,2,4", f"Wrong line 3: {lines[3]}"


# ── Correctness tests for various N ─────────────────────────────────

def test_queens_1():
    """Trivial base case."""
    solver = _load_module('solver')
    solutions = solver.solve_queens(1)
    assert len(solutions) == 1
    assert solutions[0] == [1]


def test_queens_4():
    """4-queens: 2 solutions."""
    solver = _load_module('solver')
    solutions = solver.solve_queens(4)
    assert len(solutions) == 2, f"Expected 2 solutions, got {len(solutions)}"
    for s in solutions:
        _validate_queens_solution(s, 4)
    assert solutions[0] == [2, 4, 1, 3], f"First wrong: {solutions[0]}"
    assert solutions[1] == [3, 1, 4, 2], f"Second wrong: {solutions[1]}"


def test_queens_5():
    """5-queens: 10 solutions, first = [1,3,5,2,4]."""
    solver = _load_module('solver')
    solutions = solver.solve_queens(5)
    assert len(solutions) == 10, f"Expected 10, got {len(solutions)}"
    for s in solutions:
        _validate_queens_solution(s, 5)
    assert solutions[0] == [1, 3, 5, 2, 4]


def test_queens_6():
    """6-queens: 4 solutions, first = [2,4,6,1,3,5]."""
    solver = _load_module('solver')
    solutions = solver.solve_queens(6)
    assert len(solutions) == 4, f"Expected 4, got {len(solutions)}"
    for s in solutions:
        _validate_queens_solution(s, 6)
    assert solutions[0] == [2, 4, 6, 1, 3, 5], f"First wrong: {solutions[0]}"


def test_queens_7():
    """7-queens: 40 solutions, first = [1,3,5,7,2,4,6]."""
    solver = _load_module('solver')
    solutions = solver.solve_queens(7)
    assert len(solutions) == 40, f"Expected 40, got {len(solutions)}"
    for s in solutions:
        _validate_queens_solution(s, 7)
    assert solutions[0] == [1, 3, 5, 7, 2, 4, 6], f"First wrong: {solutions[0]}"


def test_queens_8():
    """8-queens: 92 solutions, first = [1,5,8,6,3,7,2,4]."""
    solver = _load_module('solver')
    solutions = solver.solve_queens(8)
    assert len(solutions) == 92, f"Expected 92, got {len(solutions)}"
    for s in solutions:
        _validate_queens_solution(s, 8)
    assert solutions[0] == [1, 5, 8, 6, 3, 7, 2, 4], f"First wrong: {solutions[0]}"


def test_no_solutions_for_3():
    """3-queens has 0 solutions — verifies failure handling."""
    solver = _load_module('solver')
    solutions = solver.solve_queens(3)
    assert len(solutions) == 0, f"3-queens should have 0 solutions, got {len(solutions)}"


def test_no_solutions_for_2():
    """2-queens has 0 solutions."""
    solver = _load_module('solver')
    solutions = solver.solve_queens(2)
    assert len(solutions) == 0, f"2-queens should have 0 solutions, got {len(solutions)}"


# ── Structural / anti-hardcode tests ────────────────────────────────

def test_effects_library_exists():
    """effects.py is a real algebraic-effect implementation, not a stub."""
    path = '/app/effects.py'
    assert os.path.isfile(path), f"{path} not found"
    with open(path) as f:
        source = f.read()
    assert len(source) > 300, "effects.py is suspiciously short"
    lower = source.lower()
    hits = sum(
        1 for kw in [
            'choose', 'fail', 'effect', 'resume', 'continu',
            'handler', 'branch', 'backtrack', 'replay',
            'multi', 'shot', 'state', 'composition',
        ]
        if kw in lower
    )
    assert hits >= 4, (
        f"effects.py lacks algebraic-effect vocabulary ({hits} keywords found)"
    )


# ── Handler composition tests ──────────────────────────────────────

def test_choice_xor():
    """choice-all(xor): multi-shot resume with boolean XOR."""
    programs = _load_module('programs')
    result = programs.choice_xor()
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert result == [False, True, True, False], f"Wrong result: {result}"


def test_state_choice():
    """pstate(0) { choice-all { surprising() } } — shared state."""
    programs = _load_module('programs')
    result = programs.state_choice()
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
    results_list, final_state = result
    assert results_list == [False, False, True, True, False], (
        f"Wrong results: {results_list}"
    )
    assert final_state == 2, f"Wrong final state: {final_state}"


def test_choice_state():
    """choice-all { pstate(0) { surprising() } } — local state."""
    programs = _load_module('programs')
    result = programs.choice_state()
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert result == [(False, 1), (False, 1)], f"Wrong result: {result}"


def test_compose_triple_shared():
    """reader(10) { pstate(0) { choice-all { triple() } } } — shared state."""
    programs = _load_module('programs')
    result = programs.compose_triple_shared()
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
    results_list, final_state = result
    assert results_list == [0, 20], f"Wrong results: {results_list}"
    assert final_state == 20, f"Wrong final state: {final_state}"


def test_compose_triple_local():
    """reader(10) { choice-all { pstate(0) { triple() } } } — local state."""
    programs = _load_module('programs')
    result = programs.compose_triple_local()
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert result == [(0, 10), (10, 10)], f"Wrong result: {result}"


def test_programs_module_exists():
    """programs.py exists and has the required functions."""
    path = '/app/programs.py'
    assert os.path.isfile(path), f"{path} not found"
    programs = _load_module('programs')
    for fn_name in ['choice_xor', 'state_choice', 'choice_state',
                     'compose_triple_shared', 'compose_triple_local']:
        assert hasattr(programs, fn_name), f"programs.py missing function: {fn_name}"
        assert callable(getattr(programs, fn_name)), f"{fn_name} is not callable"
