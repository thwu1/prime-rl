
"""
Tests for the Optimal Touring solver pipeline.

Verifies: solver interface, tour feasibility, performance vs greedy baseline,
optimization model artifacts (LP files), and benchmark report schema.
"""

import json
import os
import re
import sys
import time

import pytest

sys.path.insert(0, '/app')

from game import evaluate_tour, greedy_solve

INSTANCES_DIR = '/app/instances'
MODELS_DIR = '/app/models'
REPORT_PATH = '/app/benchmark_report.json'


def load_instances():
    instances = {}
    for fname in sorted(os.listdir(INSTANCES_DIR)):
        if fname.endswith('.json'):
            with open(os.path.join(INSTANCES_DIR, fname)) as fh:
                instances[fname] = json.load(fh)
    return instances


def _import_solve():
    from solver import solve
    return solve


@pytest.fixture(scope="module")
def solver_results():
    """Run the solver on every instance (once) and cache results."""
    solve = _import_solve()
    instances = load_instances()
    results = {}
    for fname, sites_data in instances.items():
        t0 = time.time()
        tour = solve(sites_data)
        elapsed = time.time() - t0
        score = evaluate_tour(sites_data, tour)
        results[fname] = {'tour': tour, 'score': score, 'time': elapsed}
    return results


@pytest.fixture(scope="module")
def greedy_results():
    """Run the greedy baseline on every instance (once)."""
    instances = load_instances()
    results = {}
    for fname, sites_data in instances.items():
        tour = greedy_solve(sites_data)
        score = evaluate_tour(sites_data, tour)
        results[fname] = {'tour': tour, 'score': score}
    return results


class TestSolverBasics:
    """The solver module must be importable and return the right type."""

    def test_solver_importable(self):
        solve = _import_solve()
        assert callable(solve), "solver.solve must be callable"

    def test_returns_list(self, solver_results):
        for fname, res in solver_results.items():
            assert isinstance(res['tour'], list), (
                f"solve() must return a list for {fname}, got {type(res['tour'])}"
            )

    def test_list_contains_ints(self, solver_results):
        for fname, res in solver_results.items():
            for sid in res['tour']:
                assert isinstance(sid, int), (
                    f"Tour elements must be int for {fname}, got {type(sid)}"
                )


class TestFeasibility:
    """Every tour produced by the solver must satisfy all constraints."""

    def test_all_tours_feasible(self, solver_results):
        for fname, res in solver_results.items():
            assert res['score'] >= 0, (
                f"Infeasible tour for {fname} (score={res['score']}). "
                "Review constraint handling in evaluate_tour()."
            )

    def test_no_duplicate_visits(self, solver_results):
        for fname, res in solver_results.items():
            tour = res['tour']
            assert len(tour) == len(set(tour)), (
                f"Duplicate site visits detected in {fname}"
            )


class TestPerformance:
    """The solver must produce competitive scores within a time budget."""

    def test_nonzero_scores(self, solver_results):
        for fname, res in solver_results.items():
            assert res['score'] > 0, (
                f"Solver returned zero-value tour for {fname}"
            )

    def test_beats_greedy_aggregate(self, solver_results, greedy_results):
        total_solver = sum(max(r['score'], 0) for r in solver_results.values())
        total_greedy = sum(max(r['score'], 0) for r in greedy_results.values())

        if total_greedy == 0:
            assert total_solver > 200, (
                f"Solver total ({total_solver}) must exceed 200 "
                "when greedy scores zero"
            )
        else:
            assert total_solver >= total_greedy * 1.3, (
                f"Solver total ({total_solver}) must beat greedy total "
                f"({total_greedy}) by at least 30%.  "
                f"Ratio: {total_solver / total_greedy:.2f}x"
            )

    def test_time_limit(self, solver_results):
        for fname, res in solver_results.items():
            assert res['time'] < 45, (
                f"Solver took {res['time']:.1f}s on {fname} (limit 45s)"
            )


class TestModelArtifacts:
    """The solver must produce valid LP model files."""

    def test_models_directory_exists(self, solver_results):
        assert os.path.isdir(MODELS_DIR), (
            f"{MODELS_DIR} directory must exist with LP model files"
        )

    def test_lp_files_present(self, solver_results):
        instances = load_instances()
        lp_files = [f for f in os.listdir(MODELS_DIR) if f.endswith('.lp')]
        assert len(lp_files) >= len(instances), (
            f"Expected >= {len(instances)} LP files in {MODELS_DIR}, "
            f"found {len(lp_files)}"
        )

    def test_lp_files_valid_format(self, solver_results):
        lp_files = [f for f in os.listdir(MODELS_DIR) if f.endswith('.lp')]
        assert len(lp_files) > 0, "No LP files found"
        for lp_file in lp_files:
            path = os.path.join(MODELS_DIR, lp_file)
            with open(path) as fh:
                content = fh.read()
            has_objective = bool(
                re.search(r'(?i)(maximize|minimize)', content)
            )
            has_constraints = bool(
                re.search(r'(?i)subject\s+to', content)
            )
            has_int_decl = bool(
                re.search(r'(?i)(binary|integer|general)', content)
            )
            has_end = bool(
                re.search(r'(?i)^end\s*$', content, re.MULTILINE)
            )
            assert has_objective, (
                f"LP file {lp_file} missing objective (Maximize/Minimize)"
            )
            assert has_constraints, (
                f"LP file {lp_file} missing constraint section (Subject To)"
            )
            assert has_int_decl, (
                f"LP file {lp_file} missing variable declarations "
                "(Binary/Integer/General)"
            )
            assert has_end, (
                f"LP file {lp_file} missing End marker"
            )


class TestBenchmarkReport:
    """The benchmark report must exist with the required schema."""

    def test_report_exists(self):
        assert os.path.isfile(REPORT_PATH), (
            f"{REPORT_PATH} must exist (run python3 /app/evaluate.py)"
        )

    def test_report_valid_json(self):
        with open(REPORT_PATH) as fh:
            data = json.load(fh)
        assert isinstance(data, dict), "Report must be a JSON object"

    def test_report_instances_schema(self):
        with open(REPORT_PATH) as fh:
            data = json.load(fh)
        assert 'instances' in data, "Report missing 'instances' key"
        instances = data['instances']
        assert isinstance(instances, list), "'instances' must be an array"
        assert len(instances) >= 5, (
            f"Expected >= 5 instance entries, found {len(instances)}"
        )
        required_keys = {
            'name', 'solver_score', 'greedy_score',
            'ratio', 'time_sec', 'tour_length'
        }
        for inst in instances:
            missing = required_keys - set(inst.keys())
            assert not missing, (
                f"Instance entry for {inst.get('name', '?')} "
                f"missing keys: {missing}"
            )

    def test_report_aggregate_schema(self):
        with open(REPORT_PATH) as fh:
            data = json.load(fh)
        assert 'aggregate' in data, "Report missing 'aggregate' key"
        agg = data['aggregate']
        required_keys = {
            'total_solver', 'total_greedy', 'aggregate_ratio'
        }
        missing = required_keys - set(agg.keys())
        assert not missing, (
            f"Aggregate section missing keys: {missing}"
        )

    def test_report_aggregate_ratio_sufficient(self):
        with open(REPORT_PATH) as fh:
            data = json.load(fh)
        ratio = data['aggregate']['aggregate_ratio']
        assert ratio >= 1.3, (
            f"Report aggregate_ratio {ratio} < 1.3 required minimum"
        )
