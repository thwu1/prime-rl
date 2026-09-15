#!/usr/bin/env python3
"""
Tests for the Optimal Touring MIP + Local Search solver pipeline.

Validates both the GMPL model (touring.mod) and the Python solver (solver.py).

"""

import sys
import os
import subprocess
import importlib

sys.path.insert(0, '/app')

from game import generate_instance, evaluate_tour

SEEDS = [42, 137, 256, 401, 555, 789, 1024, 2048]
NUM_SITES = 60
MIN_SCORE_PER_INSTANCE = 800
AGGREGATE_THRESHOLD = 10000

# Cache solver results to avoid redundant computation across tests
_results_cache = {}


def _load_solver():
    """Import solver module, reloading if already cached."""
    if 'solver' in sys.modules:
        return importlib.reload(sys.modules['solver'])
    import solver
    return solver


def _get_result(seed):
    """Get cached solver result for a given seed, computing if needed."""
    if seed not in _results_cache:
        solver = _load_solver()
        instance = generate_instance(seed, NUM_SITES)
        tour = solver.solve(instance)
        value, valid, err = evaluate_tour(instance, tour)
        _results_cache[seed] = {
            'tour': tour, 'instance': instance,
            'value': value, 'valid': valid, 'err': err,
        }
    return _results_cache[seed]


# --- GMPL Model Tests ---

def test_gmpl_model_exists():
    """touring.mod must exist at /app/touring.mod."""
    assert os.path.exists('/app/touring.mod'), (
        "/app/touring.mod not found. Create a GMPL model for the touring MIP."
    )


def test_gmpl_model_structure():
    """touring.mod must contain a valid MIP formulation with required elements."""
    assert os.path.exists('/app/touring.mod'), "/app/touring.mod not found"
    with open('/app/touring.mod', 'r') as f:
        model = f.read()
    model_lower = model.lower()
    assert 'maximize' in model_lower or 'minimize' in model_lower, (
        "touring.mod must contain an optimization objective (maximize/minimize)"
    )
    assert 'binary' in model_lower or 'integer' in model_lower, (
        "touring.mod must declare integer or binary variables (MIP formulation)"
    )
    assert 'SITES' in model, (
        "touring.mod must reference set SITES for indexing site parameters"
    )
    assert 'solve' in model_lower, (
        "touring.mod must contain a solve statement"
    )


def test_gmpl_model_processable():
    """touring.mod must be processable by glpsol without errors on a small instance."""
    assert os.path.exists('/app/touring.mod'), "/app/touring.mod not found"
    dat = '\n'.join([
        'data;',
        'set SITES := 1 2 3;',
        'param avenue := 1 10, 2 20, 3 30;',
        'param street := 1 10, 2 10, 3 10;',
        'param duration := 1 30, 2 30, 3 30;',
        'param value := 1 100, 2 100, 3 100;',
        'param begin_min := 1 0, 2 40, 3 80;',
        'param end_min := 1 120, 2 180, 3 240;',
        'end;',
    ])
    dat_path = '/tmp/test_gmpl_check.dat'
    with open(dat_path, 'w') as f:
        f.write(dat)
    result = subprocess.run(
        ['glpsol', '--model', '/app/touring.mod', '--data', dat_path,
         '--tmlim', '15'],
        capture_output=True, text=True, timeout=30
    )
    combined = result.stdout + '\n' + result.stderr
    assert result.returncode == 0, (
        f"glpsol failed on touring.mod with test data:\n{combined[-600:]}"
    )


# --- Solver Tests ---

def test_solver_module_exists():
    """solver.py must exist at /app/solver.py and export a solve function."""
    assert os.path.exists('/app/solver.py'), (
        "/app/solver.py not found. Create it with a solve(sites_data) function."
    )
    solver = _load_solver()
    assert hasattr(solver, 'solve'), "solver.py must define a 'solve' function"
    assert callable(solver.solve), "'solve' must be callable"


def test_solver_returns_valid_tours():
    """solve() must return a valid tour (list of ints) for every test instance."""
    for seed in SEEDS:
        r = _get_result(seed)
        assert isinstance(r['tour'], list), (
            f"seed={seed}: solve() must return a list, got {type(r['tour']).__name__}"
        )
        assert len(r['tour']) > 0, f"seed={seed}: tour is empty"
        assert all(isinstance(x, int) for x in r['tour']), (
            f"seed={seed}: tour elements must be integers"
        )
        assert r['valid'], f"seed={seed}: invalid tour — {r['err']}"


def test_individual_scores():
    """Each instance must score at least MIN_SCORE_PER_INSTANCE."""
    for seed in SEEDS:
        r = _get_result(seed)
        assert r['valid'], f"seed={seed}: invalid tour — {r['err']}"
        assert r['value'] >= MIN_SCORE_PER_INSTANCE, (
            f"seed={seed}: score {r['value']} < minimum {MIN_SCORE_PER_INSTANCE}"
        )


def test_aggregate_score():
    """Aggregate score across all 8 instances must meet the threshold."""
    total = 0
    details = []
    for seed in SEEDS:
        r = _get_result(seed)
        assert r['valid'], f"seed={seed}: invalid tour — {r['err']}"
        total += r['value']
        details.append(f"seed={seed}: {r['value']}")
    detail_str = ", ".join(details)
    assert total >= AGGREGATE_THRESHOLD, (
        f"Aggregate score {total} < {AGGREGATE_THRESHOLD}. "
        f"Per-instance: [{detail_str}]"
    )
