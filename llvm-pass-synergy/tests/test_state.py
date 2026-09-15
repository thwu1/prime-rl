"""
Tests for LLVM Pass Sequence Optimizer task.
Verifies that the optimizer produces correct, competitive, and adaptive results.
"""

import json
import os
import sys

sys.path.insert(0, '/app')
from instcount import get_instruction_count

BENCHMARKS_DIR = '/app/benchmarks'
RESULTS_FILE = '/app/results.json'
BENCHMARK_NAMES = [
    'redundant_compute', 'control_flow', 'loop_heavy',
    'memory_access', 'mixed_ops'
]


def _load_results():
    with open(RESULTS_FILE) as f:
        return json.load(f)


class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.isfile(RESULTS_FILE), \
            f"results.json not found at {RESULTS_FILE}"

    def test_results_has_benchmarks_key(self):
        results = _load_results()
        assert 'benchmarks' in results, \
            "results.json missing 'benchmarks' key"

    def test_all_benchmarks_present(self):
        results = _load_results()
        benchmarks = results['benchmarks']
        for name in BENCHMARK_NAMES:
            assert name in benchmarks, \
                f"Benchmark '{name}' missing from results"

    def test_results_fields_complete(self):
        results = _load_results()
        required = ['original_count', 'oz_count', 'optimized_count', 'pass_sequence']
        for name, data in results['benchmarks'].items():
            for field in required:
                assert field in data, \
                    f"Benchmark '{name}' missing field '{field}'"
            assert isinstance(data['original_count'], int), \
                f"{name}: original_count must be int"
            assert isinstance(data['oz_count'], int), \
                f"{name}: oz_count must be int"
            assert isinstance(data['optimized_count'], int), \
                f"{name}: optimized_count must be int"
            assert isinstance(data['pass_sequence'], str), \
                f"{name}: pass_sequence must be str"
            assert len(data['pass_sequence']) > 0, \
                f"{name}: pass_sequence is empty"


class TestOptimizerExists:
    def test_optimizer_file_exists(self):
        assert os.path.isfile('/app/optimizer.py'), \
            "optimizer.py not found at /app/optimizer.py"

    def test_optimizer_references_synergy(self):
        with open('/app/optimizer.py') as f:
            code = f.read()
        assert 'synergy' in code.lower() or 'synergy_pairs' in code.lower(), \
            "optimizer.py does not appear to use synergy data"


class TestPassSequenceValidity:
    def test_sequences_dont_crash_opt(self):
        results = _load_results()
        for name, data in results['benchmarks'].items():
            ll_file = os.path.join(BENCHMARKS_DIR, f'{name}.ll')
            passes = data['pass_sequence']
            count = get_instruction_count(ll_file, passes)
            assert count is not None, \
                f"opt crashed with pass sequence for '{name}': {passes}"

    def test_sequences_nontrivial(self):
        results = _load_results()
        for name, data in results['benchmarks'].items():
            passes = data['pass_sequence'].split(',')
            assert len(passes) >= 3, \
                f"'{name}': pass sequence has only {len(passes)} passes, need >= 3"


class TestInstructionCountAccuracy:
    def test_original_counts_match(self):
        results = _load_results()
        for name, data in results['benchmarks'].items():
            ll_file = os.path.join(BENCHMARKS_DIR, f'{name}.ll')
            actual = get_instruction_count(ll_file)
            claimed = data['original_count']
            assert abs(actual - claimed) <= 2, \
                f"'{name}': original count mismatch: " \
                f"actual={actual}, claimed={claimed}"

    def test_oz_counts_match(self):
        results = _load_results()
        for name, data in results['benchmarks'].items():
            ll_file = os.path.join(BENCHMARKS_DIR, f'{name}.ll')
            actual = get_instruction_count(ll_file, '-Oz')
            claimed = data['oz_count']
            assert abs(actual - claimed) <= 2, \
                f"'{name}': -Oz count mismatch: " \
                f"actual={actual}, claimed={claimed}"

    def test_optimized_counts_match(self):
        results = _load_results()
        for name, data in results['benchmarks'].items():
            ll_file = os.path.join(BENCHMARKS_DIR, f'{name}.ll')
            actual = get_instruction_count(ll_file, data['pass_sequence'])
            claimed = data['optimized_count']
            assert abs(actual - claimed) <= 2, \
                f"'{name}': optimized count mismatch: " \
                f"actual={actual}, claimed={claimed}"


class TestOptimizationQuality:
    def test_improves_over_unoptimized(self):
        results = _load_results()
        for name, data in results['benchmarks'].items():
            assert data['optimized_count'] < data['original_count'], \
                f"'{name}': optimized ({data['optimized_count']}) " \
                f"not better than original ({data['original_count']})"

    def test_competitive_with_oz(self):
        """At least 3 of 5 benchmarks within 10% of -Oz."""
        results = _load_results()
        competitive = 0
        details = []
        for name, data in results['benchmarks'].items():
            oz = data['oz_count']
            opt = data['optimized_count']
            threshold = int(oz * 1.10) + 1
            is_competitive = opt <= threshold
            details.append(f"{name}: opt={opt}, oz={oz}, "
                           f"threshold={threshold}, ok={is_competitive}")
            if is_competitive:
                competitive += 1
        total = len(results['benchmarks'])
        assert competitive >= 3, \
            f"Only {competitive}/{total} benchmarks competitive " \
            f"with -Oz (within 10%): " + "; ".join(details)

    def test_adaptive_sequences(self):
        """Different benchmarks should get different pass sequences."""
        results = _load_results()
        sequences = [data['pass_sequence']
                     for data in results['benchmarks'].values()]
        unique = len(set(sequences))
        assert unique >= 3, \
            f"Only {unique} unique sequences across {len(sequences)} " \
            f"benchmarks; need at least 3 different sequences"
