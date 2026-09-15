"""
Verification tests for the constrained optimization solver and
benchmark pipeline (Makefile + sqlite3 + jq).
"""
import os
import sys
import json
import sqlite3 as sqlite3_mod
import pytest
import numpy as np


sys.path.insert(0, '/opt/optframework')
sys.path.insert(0, '/app')
from problems import Prob1, Prob2, Prob3, Prob4, Prob5
from optimizer import optimize

N_TRIALS = 500
FEASIBILITY_TOL = 1e-4
FEASIBILITY_THRESHOLD = 475  # 95% of 500

OBJECTIVE_THRESHOLDS = {
    'prob1': 0.5,
    'prob2': 10.0,
    'prob3': 1.0,
    'prob4': 5.0,
    'prob5': 25.0,
}

PROBLEM_MAP = {
    'prob1': Prob1,
    'prob2': Prob2,
    'prob3': Prob3,
    'prob4': Prob4,
    'prob5': Prob5,
}

_results_cache = {}


def _run_optimizer_on_problem(prob_cls):
    """Run optimizer across N_TRIALS seeds, return aggregated results."""
    feasible_count = 0
    fvals = []
    budget_violations = 0

    for seed in range(N_TRIALS):
        p = prob_cls()
        np.random.seed(seed)
        x0 = p.x0()

        try:
            xb = optimize(p.f, p.g, p.c, x0, p.n, p.count, p.prob)
        except Exception:
            fvals.append(float('inf'))
            continue

        if p.count() > p.n:
            budget_violations += 1
            fvals.append(float('inf'))
            continue

        if np.any(np.isnan(xb)) or np.any(np.isinf(xb)):
            fvals.append(float('inf'))
            continue

        p._reset()
        cv = p.c(xb)
        p._reset()
        fv = p.f(xb)

        if np.all(cv <= FEASIBILITY_TOL):
            feasible_count += 1

        if np.isfinite(fv):
            fvals.append(fv)
        else:
            fvals.append(float('inf'))

    finite_fvals = [v for v in fvals if np.isfinite(v)]
    mean_obj = np.mean(finite_fvals) if finite_fvals else float('inf')

    return {
        'feasible_count': feasible_count,
        'mean_objective': mean_obj,
        'budget_violations': budget_violations,
    }


def _get_results(prob_name):
    """Cached results to avoid re-running the same problem."""
    if prob_name not in _results_cache:
        _results_cache[prob_name] = _run_optimizer_on_problem(
            PROBLEM_MAP[prob_name])
    return _results_cache[prob_name]


# ---- Optimizer correctness tests ----

@pytest.mark.parametrize("prob_name", [
    'prob1', 'prob2', 'prob3', 'prob4', 'prob5'
])
def test_budget_compliance(prob_name):
    r = _get_results(prob_name)
    assert r['budget_violations'] == 0, (
        f"{prob_name}: evaluation budget exceeded on "
        f"{r['budget_violations']} out of {N_TRIALS} seeds"
    )


@pytest.mark.parametrize("prob_name", [
    'prob1', 'prob2', 'prob3', 'prob4', 'prob5'
])
def test_feasibility(prob_name):
    r = _get_results(prob_name)
    assert r['feasible_count'] >= FEASIBILITY_THRESHOLD, (
        f"{prob_name}: feasibility rate too low: "
        f"{r['feasible_count']}/{N_TRIALS} "
        f"(need >= {FEASIBILITY_THRESHOLD})"
    )


@pytest.mark.parametrize("prob_name", [
    'prob1', 'prob2', 'prob3', 'prob4', 'prob5'
])
def test_objective_quality(prob_name):
    r = _get_results(prob_name)
    threshold = OBJECTIVE_THRESHOLDS[prob_name]
    assert r['mean_objective'] <= threshold, (
        f"{prob_name}: mean objective too high: "
        f"{r['mean_objective']:.4f} (need <= {threshold})"
    )


# ---- Benchmark pipeline tests (Makefile + sqlite3 + jq) ----

def test_makefile_exists():
    """Verify Makefile exists at /app/Makefile."""
    assert os.path.isfile('/app/Makefile'), (
        "Makefile not found at /app/Makefile"
    )


def test_makefile_has_targets():
    """Verify Makefile declares benchmark, report, and all targets."""
    with open('/app/Makefile') as f:
        content = f.read()
    for target in ['benchmark', 'report', 'all']:
        assert target in content, (
            f"Makefile missing '{target}' target"
        )


def test_results_db_exists():
    """Verify results.db was generated."""
    assert os.path.isfile('/app/results.db'), (
        "results.db not found at /app/results.db"
    )


def test_results_db_schema():
    """Verify results.db has correct table and columns."""
    conn = sqlite3_mod.connect('/app/results.db')
    cursor = conn.execute("PRAGMA table_info(benchmark)")
    columns = {row[1]: row[2].upper() for row in cursor.fetchall()}
    conn.close()

    required = {
        'problem': 'TEXT',
        'seeds_total': 'INTEGER',
        'seeds_feasible': 'INTEGER',
        'mean_objective': 'REAL',
        'budget_violations': 'INTEGER',
    }
    for col, typ in required.items():
        assert col in columns, (
            f"benchmark table missing column '{col}'"
        )
        assert columns[col] == typ, (
            f"column '{col}' should be {typ}, got {columns[col]}"
        )


def test_results_db_data():
    """Verify results.db contains data for all 5 problems."""
    conn = sqlite3_mod.connect('/app/results.db')
    rows = conn.execute(
        "SELECT problem FROM benchmark ORDER BY problem"
    ).fetchall()
    conn.close()
    problems = [r[0] for r in rows]
    assert len(problems) == 5, (
        f"Expected 5 rows in benchmark table, got {len(problems)}"
    )
    assert problems == ['prob1', 'prob2', 'prob3', 'prob4', 'prob5'], (
        f"Unexpected problems: {problems}"
    )


def test_report_json_exists():
    """Verify report.json was generated."""
    assert os.path.isfile('/app/report.json'), (
        "report.json not found at /app/report.json"
    )


def test_report_json_structure():
    """Verify report.json has the required structure and fields."""
    with open('/app/report.json') as f:
        report = json.load(f)

    assert 'problems' in report, "report.json missing 'problems' key"
    assert 'overall_pass' in report, "report.json missing 'overall_pass' key"
    assert isinstance(report['problems'], list), (
        "'problems' must be a list"
    )
    assert len(report['problems']) == 5, (
        f"Expected 5 problems in report, got {len(report['problems'])}"
    )

    expected_names = {'prob1', 'prob2', 'prob3', 'prob4', 'prob5'}
    seen_names = set()
    for entry in report['problems']:
        for key in ['name', 'feasibility_rate', 'mean_objective',
                     'budget_violations', 'pass']:
            assert key in entry, (
                f"Problem entry missing key '{key}': {entry}"
            )
        assert isinstance(entry['name'], str)
        assert isinstance(entry['feasibility_rate'], (int, float))
        assert isinstance(entry['mean_objective'], (int, float))
        assert isinstance(entry['budget_violations'], int)
        assert isinstance(entry['pass'], bool)
        seen_names.add(entry['name'])

    assert seen_names == expected_names, (
        f"Problem names mismatch: {seen_names} != {expected_names}"
    )


def test_report_json_overall_pass():
    """Verify that overall_pass is true (optimizer + pipeline both work)."""
    with open('/app/report.json') as f:
        report = json.load(f)
    assert report['overall_pass'] is True, (
        "report.json overall_pass is not true"
    )
