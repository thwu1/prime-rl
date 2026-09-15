"""Tests for LLVM pass phase-ordering optimization results.

"""
import json
import os
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, '/app')
from count_ir import count_instructions

BENCHMARKS = [
    'bitmanip', 'crypto_hash', 'dsp_filter', 'graph_ops',
    'matrix_ops', 'poly_eval', 'sort_search',
]
MAX_PASSES = 25

FORBIDDEN_SHORTHANDS = {'O0', 'O1', 'O2', 'O3', 'Os', 'Oz'}


@pytest.fixture(scope='module')
def results():
    with open('/app/results.json') as f:
        return json.load(f)


# -- Structure tests --------------------------------------------------------

def test_results_file_exists():
    assert os.path.exists('/app/results.json'), "results.json not found"


def test_top_level_structure(results):
    assert 'benchmarks' in results, "Missing 'benchmarks' key"
    assert 'universal' in results, "Missing 'universal' key"
    assert isinstance(results['benchmarks'], dict)
    assert isinstance(results['universal'], dict)


# -- Per-benchmark tests ----------------------------------------------------

def test_bench_all_present(results):
    for b in BENCHMARKS:
        assert b in results['benchmarks'], f"Missing benchmark: {b}"


def test_bench_schema(results):
    for name, r in results['benchmarks'].items():
        assert isinstance(r.get('pass_sequence'), list), \
            f"{name}: pass_sequence must be a list"
        assert len(r['pass_sequence']) > 0, \
            f"{name}: pass_sequence must not be empty"
        assert isinstance(r.get('optimized_count'), int), \
            f"{name}: optimized_count must be int"
        assert isinstance(r.get('oz_count'), int), \
            f"{name}: oz_count must be int"
        assert isinstance(r.get('improvement_pct'), (int, float)), \
            f"{name}: improvement_pct must be numeric"


def test_bench_no_pipeline_shorthands(results):
    for name, r in results['benchmarks'].items():
        for p in r['pass_sequence']:
            assert p not in FORBIDDEN_SHORTHANDS, \
                f"{name}: pipeline shorthand '{p}' not allowed"
            assert 'default<' not in p, \
                f"{name}: pipeline shorthand 'default<...>' in '{p}'"


def test_bench_max_pass_length(results):
    for name, r in results['benchmarks'].items():
        assert len(r['pass_sequence']) <= MAX_PASSES, \
            f"{name}: {len(r['pass_sequence'])} passes exceeds limit of {MAX_PASSES}"


def test_bench_oz_baseline_correct(results):
    for name in BENCHMARKS:
        input_ll = f'/app/benchmarks/{name}.ll'
        with tempfile.NamedTemporaryFile(suffix='.ll', delete=False, dir='/tmp') as f:
            output = f.name
        try:
            ret = subprocess.run(
                ['opt', '-Oz', input_ll, '-S', '-o', output],
                capture_output=True, text=True, timeout=60
            )
            assert ret.returncode == 0, f"{name}: opt -Oz failed: {ret.stderr[:300]}"
            actual_oz = count_instructions(output)
            claimed_oz = results['benchmarks'][name]['oz_count']
            assert actual_oz == claimed_oz, \
                f"{name}: Oz count mismatch -- claimed {claimed_oz}, actual {actual_oz}"
        finally:
            if os.path.exists(output):
                os.unlink(output)


def test_bench_pass_sequences_produce_claimed_count(results):
    for name in BENCHMARKS:
        input_ll = f'/app/benchmarks/{name}.ll'
        passes = results['benchmarks'][name]['pass_sequence']
        passes_str = ','.join(passes)
        with tempfile.NamedTemporaryFile(suffix='.ll', delete=False, dir='/tmp') as f:
            output = f.name
        try:
            ret = subprocess.run(
                ['opt', f'-passes={passes_str}', input_ll, '-S', '-o', output],
                capture_output=True, text=True, timeout=60
            )
            assert ret.returncode == 0, \
                f"{name}: opt failed with passes '{passes_str}': {ret.stderr[:300]}"
            actual_count = count_instructions(output)
            claimed_count = results['benchmarks'][name]['optimized_count']
            assert actual_count == claimed_count, \
                f"{name}: optimized count mismatch -- claimed {claimed_count}, actual {actual_count}"
        finally:
            if os.path.exists(output):
                os.unlink(output)


def test_bench_improvement_formula_consistent(results):
    for name in BENCHMARKS:
        r = results['benchmarks'][name]
        if r['oz_count'] == 0:
            continue
        expected_pct = (r['oz_count'] - r['optimized_count']) / r['oz_count'] * 100
        assert abs(r['improvement_pct'] - expected_pct) < 0.1, \
            f"{name}: improvement_pct {r['improvement_pct']} != expected {expected_pct:.4f}"


def test_bench_average_improvement_meets_threshold(results):
    improvements = [results['benchmarks'][name]['improvement_pct']
                    for name in BENCHMARKS]
    avg = sum(improvements) / len(improvements)
    assert avg >= 2.0, \
        f"Per-benchmark average improvement {avg:.2f}% is below the 2.0% threshold"


# -- Universal sequence tests -----------------------------------------------

def test_universal_structure(results):
    u = results['universal']
    assert 'pass_sequence' in u, "universal missing 'pass_sequence'"
    assert 'results' in u, "universal missing 'results'"
    assert isinstance(u['pass_sequence'], list)
    assert isinstance(u['results'], dict)


def test_universal_all_benchmarks_present(results):
    for b in BENCHMARKS:
        assert b in results['universal']['results'], \
            f"Universal results missing benchmark: {b}"


def test_universal_schema(results):
    for name, r in results['universal']['results'].items():
        assert isinstance(r.get('optimized_count'), int), \
            f"universal/{name}: optimized_count must be int"
        assert isinstance(r.get('oz_count'), int), \
            f"universal/{name}: oz_count must be int"
        assert isinstance(r.get('improvement_pct'), (int, float)), \
            f"universal/{name}: improvement_pct must be numeric"


def test_universal_no_pipeline_shorthands(results):
    for p in results['universal']['pass_sequence']:
        assert p not in FORBIDDEN_SHORTHANDS, \
            f"Universal: pipeline shorthand '{p}' not allowed"
        assert 'default<' not in p, \
            f"Universal: pipeline shorthand 'default<...>' in '{p}'"


def test_universal_max_pass_length(results):
    seq = results['universal']['pass_sequence']
    assert len(seq) > 0, "Universal pass_sequence must not be empty"
    assert len(seq) <= MAX_PASSES, \
        f"Universal: {len(seq)} passes exceeds limit of {MAX_PASSES}"


def test_universal_counts_correct(results):
    uni_passes = results['universal']['pass_sequence']
    passes_str = ','.join(uni_passes)
    for name in BENCHMARKS:
        input_ll = f'/app/benchmarks/{name}.ll'
        with tempfile.NamedTemporaryFile(suffix='.ll', delete=False, dir='/tmp') as f:
            output = f.name
        try:
            ret = subprocess.run(
                ['opt', f'-passes={passes_str}', input_ll, '-S', '-o', output],
                capture_output=True, text=True, timeout=60
            )
            assert ret.returncode == 0, \
                f"universal/{name}: opt failed: {ret.stderr[:300]}"
            actual_count = count_instructions(output)
            claimed_count = results['universal']['results'][name]['optimized_count']
            assert actual_count == claimed_count, \
                f"universal/{name}: count mismatch -- claimed {claimed_count}, actual {actual_count}"
        finally:
            if os.path.exists(output):
                os.unlink(output)


def test_universal_oz_baseline_consistent(results):
    for name in BENCHMARKS:
        bench_oz = results['benchmarks'][name]['oz_count']
        uni_oz = results['universal']['results'][name]['oz_count']
        assert bench_oz == uni_oz, \
            f"{name}: Oz count differs between benchmarks ({bench_oz}) and universal ({uni_oz})"


def test_universal_improvement_formula_consistent(results):
    for name in BENCHMARKS:
        r = results['universal']['results'][name]
        if r['oz_count'] == 0:
            continue
        expected_pct = (r['oz_count'] - r['optimized_count']) / r['oz_count'] * 100
        assert abs(r['improvement_pct'] - expected_pct) < 0.1, \
            f"universal/{name}: improvement_pct {r['improvement_pct']} != expected {expected_pct:.4f}"


def test_universal_no_regression(results):
    for name in BENCHMARKS:
        imp = results['universal']['results'][name]['improvement_pct']
        assert imp >= -0.01, \
            f"universal/{name}: regression detected -- improvement_pct = {imp:.4f}"


def test_universal_average_meets_threshold(results):
    improvements = [results['universal']['results'][name]['improvement_pct']
                    for name in BENCHMARKS]
    avg = sum(improvements) / len(improvements)
    assert avg >= 0.5, \
        f"Universal average improvement {avg:.2f}% is below the 0.5% threshold"
