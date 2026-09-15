#!/usr/bin/env python3
"""Tests for the ad placement solver."""

import subprocess
import os
import glob

THRESHOLD = 0.75
SOLVER_PATH = '/app/solver.py'
SCORER_PATH = '/app/scorer.py'
TEST_CASES_DIR = '/app/test_cases'


def _get_test_cases():
    cases = sorted(glob.glob(os.path.join(TEST_CASES_DIR, 'input_*.txt')))
    assert len(cases) >= 5, (
        f"Expected >= 5 test cases in {TEST_CASES_DIR}, found {len(cases)}"
    )
    return cases


def _run_solver(input_file):
    """Run the solver on a single test case and return its stdout."""
    with open(input_file) as f:
        data = f.read()
    result = subprocess.run(
        ['python3', SOLVER_PATH],
        input=data, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"Solver failed on {os.path.basename(input_file)} "
        f"(exit {result.returncode}): {result.stderr[:500]}"
    )
    return result.stdout


def _score(input_file, output_file):
    """Score a solver output. Returns satisfaction float."""
    result = subprocess.run(
        ['python3', SCORER_PATH, input_file, output_file],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"Scoring error on {os.path.basename(input_file)}: "
        f"{result.stdout.strip()}"
    )
    for line in result.stdout.strip().split('\n'):
        if line.startswith('Satisfaction:'):
            return float(line.split(':')[1].strip())
    raise ValueError(f"Could not parse scorer output: {result.stdout}")


def test_solver_exists():
    """Solver file must exist at the expected path."""
    assert os.path.exists(SOLVER_PATH), (
        f"Solver not found at {SOLVER_PATH}. "
        "Create a Python script that reads input from stdin and writes "
        "output to stdout."
    )


def test_output_format():
    """Solver output must have correct format: N lines of 4 integers."""
    cases = _get_test_cases()
    input_file = cases[0]
    output = _run_solver(input_file)

    with open(input_file) as f:
        n = int(f.readline().strip())

    lines = [l for l in output.strip().split('\n') if l.strip()]
    assert len(lines) == n, f"Expected {n} output lines, got {len(lines)}"
    for i, line in enumerate(lines):
        parts = line.split()
        assert len(parts) == 4, (
            f"Line {i}: expected 4 integers, got {len(parts)} values"
        )
        a, b, c, d = [int(p) for p in parts]
        assert 0 <= a < c <= 10000, f"Line {i}: invalid x-range [{a}, {c}]"
        assert 0 <= b < d <= 10000, f"Line {i}: invalid y-range [{b}, {d}]"


def test_average_satisfaction_above_threshold():
    """Average satisfaction across all test cases must meet the threshold."""
    cases = _get_test_cases()
    scores = []

    for inp in cases:
        solver_output = _run_solver(inp)
        out_file = inp.replace('input_', 'output_')
        with open(out_file, 'w') as f:
            f.write(solver_output)
        scores.append(_score(inp, out_file))

    avg = sum(scores) / len(scores)
    detail = ', '.join(f'{s:.4f}' for s in scores)
    assert avg >= THRESHOLD, (
        f"Average satisfaction {avg:.4f} < {THRESHOLD}. "
        f"Per-case scores: [{detail}]"
    )
