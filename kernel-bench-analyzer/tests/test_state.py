"""
Tests for GPU Kernel Benchmark Pipeline Reconciliation.
Independently reconciles all data sources and verifies /app/report.json.
"""

import json
import csv
import sqlite3
import math
import os
import pytest
from math import comb


# ================================================================
# Reference data reconciliation logic
# ================================================================

def _load_and_reconcile_db():
    """Load DB samples, deduplicate by (problem_id, sample_id) preferring latest run."""
    conn = sqlite3.connect('/app/benchmarks.db')
    # Get all samples ordered by run_id DESC so latest comes first
    cursor = conn.execute("""
        SELECT s.problem_id, s.sample_id, s.compiled, s.correct, s.runtime_us, s.run_id
        FROM samples s
        ORDER BY s.run_id DESC
    """)
    seen = {}
    for row in cursor:
        pid, sid, compiled, correct, runtime, run_id = row
        key = (pid, sid)
        if key not in seen:
            seen[key] = {
                'sample_id': sid,
                'compiled': bool(compiled),
                'correctness': bool(correct),
                'runtime': runtime,  # may be None or negative
            }
    conn.close()

    # Group by problem_id
    results = {}
    for (pid, sid), sample in sorted(seen.items()):
        pid_str = str(pid)
        if pid_str not in results:
            results[pid_str] = []
        results[pid_str].append(sample)
    return results


def _load_legacy():
    """Load legacy JSON logs, convert units (ms→us), normalize field names."""
    legacy = {}
    legacy_dir = '/app/legacy'
    if not os.path.isdir(legacy_dir):
        return legacy

    for fname in sorted(os.listdir(legacy_dir)):
        if not fname.endswith('.json'):
            continue
        with open(os.path.join(legacy_dir, fname)) as f:
            data = json.load(f)

        unit = data.get('run_metadata', {}).get('timing_unit', 'microseconds')
        for pid_str, samples in data.get('results', {}).items():
            if pid_str in legacy:
                continue  # already loaded from an earlier file
            converted = []
            for s in samples:
                runtime_ms = s.get('exec_time_ms', -1.0)
                if unit == 'milliseconds' and runtime_ms > 0:
                    runtime_us = runtime_ms * 1000.0
                elif runtime_ms > 0:
                    runtime_us = runtime_ms
                else:
                    runtime_us = None  # unmeasured

                converted.append({
                    'sample_id': s['sample_id'],
                    'compiled': s.get('built', False),
                    'correctness': s.get('passed', False),
                    'runtime': runtime_us,
                })
            legacy[pid_str] = converted
    return legacy


def _load_catalog_with_errata():
    """Load catalog CSV and apply errata corrections."""
    catalog = []
    with open('/app/catalog/problems.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            catalog.append({
                'problem_id': int(row['problem_id']),
                'name': row['name'],
                'flops': int(row['flops']),
                'memory_bytes': int(row['memory_bytes']),
            })

    # Apply errata
    errata_path = '/app/catalog/errata.json'
    if os.path.exists(errata_path):
        with open(errata_path) as f:
            errata = json.load(f)
        corrections = {c['problem_id']: c for c in errata.get('corrections', [])}
        for prob in catalog:
            if prob['problem_id'] in corrections:
                c = corrections[prob['problem_id']]
                prob[c['field']] = c['corrected_value']
    return catalog


def _load_hardware():
    """Load hardware specs from TOML."""
    import tomllib
    with open('/app/hardware/system_info.toml', 'rb') as f:
        data = tomllib.load(f)
    return {
        'peak_fp32_tflops': data['gpu']['compute']['peak_fp32_tflops'],
        'memory_bandwidth_gb_s': data['gpu']['memory']['bandwidth_gb_s'],
    }


def _load_baselines():
    with open('/app/baselines/pytorch_baseline.json') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reconciled():
    """Build the fully reconciled dataset."""
    db_results = _load_and_reconcile_db()
    legacy = _load_legacy()
    catalog = _load_catalog_with_errata()
    hw = _load_hardware()
    baselines = _load_baselines()

    # Merge: DB is authoritative for problems it covers; legacy fills gaps
    db_pids = set(db_results.keys())
    eval_results = dict(db_results)
    for pid_str, samples in legacy.items():
        if pid_str not in db_pids:
            eval_results[pid_str] = samples

    return {
        'eval_results': eval_results,
        'problem_catalog': catalog,
        'hardware_spec': hw,
        'baseline_timings': baselines,
    }


@pytest.fixture(scope="module")
def report():
    path = '/app/report.json'
    assert os.path.exists(path), f"Report not found at {path}"
    with open(path) as f:
        return json.load(f)


# ================================================================
# Helper functions for reference computations
# ================================================================

def _roofline_time_us(prob, hw):
    compute_us = prob['flops'] / (hw['peak_fp32_tflops'] * 1e6)
    memory_us = prob['memory_bytes'] / (hw['memory_bandwidth_gb_s'] * 1e3)
    return max(compute_us, memory_us)


def _bottleneck(prob, hw):
    compute_us = prob['flops'] / (hw['peak_fp32_tflops'] * 1e6)
    memory_us = prob['memory_bytes'] / (hw['memory_bandwidth_gb_s'] * 1e3)
    return 'compute_bound' if compute_us > memory_us else 'memory_bound'


def _get_greedy(pid, evals):
    samples = evals.get(str(pid), [])
    matches = [s for s in samples if s['sample_id'] == 0]
    return matches[0] if matches else None


def _valid_runtime(sample):
    """Check if a sample has a valid (positive, non-None) runtime."""
    r = sample.get('runtime')
    return r is not None and r > 0


def _ref_fast_p(data, threshold, exclude_pids=None):
    exclude = set(exclude_pids or [])
    catalog = [p for p in data['problem_catalog'] if p['problem_id'] not in exclude]
    total = len(catalog)
    if total == 0:
        return 0.0
    count = 0
    for prob in catalog:
        pid = str(prob['problem_id'])
        greedy = _get_greedy(prob['problem_id'], data['eval_results'])
        if greedy and greedy['correctness'] and _valid_runtime(greedy):
            su = data['baseline_timings'][pid]['mean_us'] / greedy['runtime']
            if su >= threshold:
                count += 1
    return count / total


def _ref_pass_at_k(data, k):
    values = []
    for prob in data['problem_catalog']:
        pid = str(prob['problem_id'])
        samples = data['eval_results'].get(pid, [])
        n = len(samples)
        c = sum(1 for s in samples if s['correctness'])
        if k > n:
            continue
        pk = 1.0 - comb(n - c, k) / comb(n, k)
        values.append(pk)
    return sum(values) / len(values) if values else 0.0


def _ref_geo_mean(data):
    log_speedups = []
    for prob in data['problem_catalog']:
        pid = str(prob['problem_id'])
        greedy = _get_greedy(prob['problem_id'], data['eval_results'])
        if greedy and greedy['correctness'] and _valid_runtime(greedy):
            su = data['baseline_timings'][pid]['mean_us'] / greedy['runtime']
            log_speedups.append(math.log(su))
    if not log_speedups:
        return 0.0
    return math.exp(sum(log_speedups) / len(log_speedups))


def _ref_anomalies(data):
    hw = data['hardware_spec']
    anomalies = []
    for prob in data['problem_catalog']:
        pid = str(prob['problem_id'])
        rt = _roofline_time_us(prob, hw)
        max_su = data['baseline_timings'][pid]['mean_us'] / rt
        samples = data['eval_results'].get(pid, [])
        for s in samples:
            if s['correctness'] and _valid_runtime(s):
                su = data['baseline_timings'][pid]['mean_us'] / s['runtime']
                if su > max_su:
                    anomalies.append(prob['problem_id'])
                    break
    return sorted(anomalies)


def _ref_flaky(data):
    flaky = []
    for prob in data['problem_catalog']:
        pid = str(prob['problem_id'])
        samples = data['eval_results'].get(pid, [])
        n = len(samples)
        c = sum(1 for s in samples if s['correctness'])
        if 0 < c < n:
            flaky.append(prob['problem_id'])
    return sorted(flaky)


def _ref_difficulty_breakdown(data):
    hw = data['hardware_spec']
    groups = {'compute_bound': [], 'memory_bound': []}
    for prob in data['problem_catalog']:
        bt = _bottleneck(prob, hw)
        groups[bt].append(prob)

    result = {}
    for bt, probs in groups.items():
        total = len(probs)
        if total == 0:
            result[bt] = 0.0
            continue
        count = 0
        for prob in probs:
            pid = str(prob['problem_id'])
            greedy = _get_greedy(prob['problem_id'], data['eval_results'])
            if greedy and greedy['correctness'] and _valid_runtime(greedy):
                su = data['baseline_timings'][pid]['mean_us'] / greedy['runtime']
                if su >= 1.0:
                    count += 1
        result[bt] = count / total
    return result


# ================================================================
# Structure tests
# ================================================================

class TestReportStructure:
    def test_report_exists(self, report):
        assert report is not None

    def test_top_level_keys(self, report):
        required = ['fast_p', 'pass_at_k', 'geometric_mean_speedup',
                     'anomalies', 'corrected_fast_p', 'difficulty_breakdown',
                     'flaky_problems', 'per_problem']
        for key in required:
            assert key in report, f"Missing key: {key}"

    def test_fast_p_thresholds(self, report):
        for p in ['0.0', '0.5', '1.0', '1.5', '2.0']:
            assert p in report['fast_p'], f"Missing fast_p threshold: {p}"

    def test_corrected_fast_p_thresholds(self, report):
        for p in ['0.0', '0.5', '1.0', '1.5', '2.0']:
            assert p in report['corrected_fast_p']

    def test_pass_at_k_values(self, report):
        for k in ['1', '3', '5']:
            assert k in report['pass_at_k']

    def test_per_problem_count(self, report):
        assert len(report['per_problem']) == 15

    def test_per_problem_fields(self, report):
        required_fields = ['problem_id', 'name', 'num_compiled', 'num_correct',
                           'num_samples', 'greedy_speedup', 'best_speedup',
                           'is_anomalous', 'roofline_time_us',
                           'max_theoretical_speedup', 'bottleneck']
        for entry in report['per_problem']:
            for field in required_fields:
                assert field in entry, f"Missing '{field}' for problem {entry.get('problem_id', '?')}"

    def test_difficulty_breakdown_keys(self, report):
        assert 'compute_bound' in report['difficulty_breakdown']
        assert 'memory_bound' in report['difficulty_breakdown']


# ================================================================
# Data reconciliation verification — ensures all 15 problems present
# ================================================================

class TestReconciliation:
    def test_all_problems_covered(self, report):
        pids = sorted([e['problem_id'] for e in report['per_problem']])
        assert pids == list(range(1, 16)), f"Expected problems 1-15, got {pids}"

    def test_db_only_problems_present(self, report):
        """Problems 1-7 exist only in DB."""
        pids = {e['problem_id'] for e in report['per_problem']}
        for pid in range(1, 8):
            assert pid in pids

    def test_legacy_only_problems_present(self, report):
        """Problems 11-15 exist only in legacy logs."""
        pids = {e['problem_id'] for e in report['per_problem']}
        for pid in range(11, 16):
            assert pid in pids

    def test_sample_counts_are_five(self, report):
        """After dedup, each problem should have exactly 5 samples."""
        for entry in report['per_problem']:
            assert entry['num_samples'] == 5, (
                f"Problem {entry['problem_id']}: expected 5 samples, got {entry['num_samples']}"
            )

    def test_dedup_applied_to_problem1(self, report, reconciled):
        """Problem 1 has run2 duplicates — greedy runtime should reflect run2 data."""
        entry = [e for e in report['per_problem'] if e['problem_id'] == 1][0]
        # After dedup: greedy s0 runtime=12.5 (from run2), su=15.0/12.5=1.2
        expected_su = 15.0 / 12.5
        assert entry['greedy_speedup'] is not None
        assert abs(entry['greedy_speedup'] - expected_su) < 1e-4, (
            f"Problem 1 greedy_speedup should be {expected_su}, got {entry['greedy_speedup']}"
        )


# ================================================================
# fast_p tests
# ================================================================

class TestFastP:
    @pytest.mark.parametrize("p", [0.0, 0.5, 1.0, 1.5, 2.0])
    def test_fast_p_value(self, report, reconciled, p):
        expected = _ref_fast_p(reconciled, p)
        actual = report['fast_p'][str(p)]
        assert abs(actual - expected) < 1e-6, (
            f"fast_p({p}): expected {expected:.6f}, got {actual:.6f}"
        )

    def test_fast_p_monotonicity(self, report):
        vals = [report['fast_p'][p] for p in ['0.0', '0.5', '1.0', '1.5', '2.0']]
        for i in range(len(vals) - 1):
            assert vals[i] >= vals[i + 1] - 1e-10

    def test_fast_p_bounds(self, report):
        for p in ['0.0', '0.5', '1.0', '1.5', '2.0']:
            assert 0.0 <= report['fast_p'][p] <= 1.0


# ================================================================
# pass@k tests
# ================================================================

class TestPassAtK:
    @pytest.mark.parametrize("k", [1, 3, 5])
    def test_pass_at_k_value(self, report, reconciled, k):
        expected = _ref_pass_at_k(reconciled, k)
        actual = report['pass_at_k'][str(k)]
        assert abs(actual - expected) < 1e-6, (
            f"pass@{k}: expected {expected:.6f}, got {actual:.6f}"
        )

    def test_pass_at_k_monotonicity(self, report):
        vals = [report['pass_at_k'][str(k)] for k in [1, 3, 5]]
        for i in range(len(vals) - 1):
            assert vals[i] <= vals[i + 1] + 1e-10

    def test_pass_at_k_bounds(self, report):
        for k in ['1', '3', '5']:
            assert 0.0 <= report['pass_at_k'][k] <= 1.0


# ================================================================
# geometric_mean_speedup tests
# ================================================================

class TestGeoMean:
    def test_geo_mean_value(self, report, reconciled):
        expected = _ref_geo_mean(reconciled)
        actual = report['geometric_mean_speedup']
        assert abs(actual - expected) < 0.01, (
            f"geo_mean: expected {expected:.4f}, got {actual:.4f}"
        )

    def test_geo_mean_positive(self, report):
        assert report['geometric_mean_speedup'] > 0


# ================================================================
# anomaly detection tests
# ================================================================

class TestAnomalies:
    def test_anomalies_exact(self, report, reconciled):
        expected = _ref_anomalies(reconciled)
        assert sorted(report['anomalies']) == expected

    def test_known_anomalies_present(self, report):
        """Problems 7, 9, 12 have speedups exceeding roofline limits."""
        for pid in [7, 9, 12]:
            assert pid in report['anomalies'], f"Problem {pid} should be anomalous"

    def test_known_non_anomalies_absent(self, report):
        for pid in [1, 2, 3, 4, 5, 6, 8, 10, 11, 13, 14, 15]:
            assert pid not in report['anomalies'], f"Problem {pid} should NOT be anomalous"

    def test_anomalies_sorted(self, report):
        assert report['anomalies'] == sorted(report['anomalies'])

    def test_errata_affects_anomalies(self, reconciled):
        """Verify errata corrections are necessary for correct anomaly detection.
        With wrong FLOPs for problem 8 (500M instead of 10M), the roofline
        would change, potentially changing anomaly status."""
        hw = reconciled['hardware_spec']
        # Problem 8 with correct flops=10M: roofline=19.617, max_su=2.294
        prob8 = [p for p in reconciled['problem_catalog'] if p['problem_id'] == 8][0]
        assert prob8['flops'] == 10000000, "Errata correction not applied to problem 8"
        rt = _roofline_time_us(prob8, hw)
        assert abs(rt - 19.617) < 0.1


# ================================================================
# corrected_fast_p tests
# ================================================================

class TestCorrectedFastP:
    @pytest.mark.parametrize("p", [0.0, 0.5, 1.0, 1.5, 2.0])
    def test_corrected_fast_p_value(self, report, reconciled, p):
        anomalies = set(_ref_anomalies(reconciled))
        expected = _ref_fast_p(reconciled, p, exclude_pids=anomalies)
        actual = report['corrected_fast_p'][str(p)]
        assert abs(actual - expected) < 1e-6, (
            f"corrected_fast_p({p}): expected {expected:.6f}, got {actual:.6f}"
        )


# ================================================================
# difficulty_breakdown tests
# ================================================================

class TestDifficultyBreakdown:
    def test_compute_bound(self, report, reconciled):
        expected = _ref_difficulty_breakdown(reconciled)
        actual = report['difficulty_breakdown']['compute_bound']
        assert abs(actual - expected['compute_bound']) < 1e-6

    def test_memory_bound(self, report, reconciled):
        expected = _ref_difficulty_breakdown(reconciled)
        actual = report['difficulty_breakdown']['memory_bound']
        assert abs(actual - expected['memory_bound']) < 1e-6

    def test_values_in_range(self, report):
        for bt in ['compute_bound', 'memory_bound']:
            v = report['difficulty_breakdown'][bt]
            assert 0.0 <= v <= 1.0


# ================================================================
# flaky_problems tests
# ================================================================

class TestFlakyProblems:
    def test_flaky_exact(self, report, reconciled):
        expected = _ref_flaky(reconciled)
        assert sorted(report['flaky_problems']) == expected

    def test_flaky_sorted(self, report):
        assert report['flaky_problems'] == sorted(report['flaky_problems'])


# ================================================================
# per_problem detail tests
# ================================================================

class TestPerProblem:
    def test_correct_counts(self, report, reconciled):
        evals = reconciled['eval_results']
        for entry in report['per_problem']:
            pid = str(entry['problem_id'])
            samples = evals.get(pid, [])
            assert entry['num_compiled'] == sum(1 for s in samples if s['compiled']), (
                f"Problem {pid}: wrong compiled count"
            )
            assert entry['num_correct'] == sum(1 for s in samples if s['correctness']), (
                f"Problem {pid}: wrong correct count"
            )
            assert entry['num_samples'] == len(samples), (
                f"Problem {pid}: wrong sample count"
            )

    def test_null_speedups_when_no_correct(self, report):
        for entry in report['per_problem']:
            if entry['num_correct'] == 0:
                assert entry['greedy_speedup'] is None
                assert entry['best_speedup'] is None

    def test_best_ge_greedy(self, report):
        for entry in report['per_problem']:
            if entry['greedy_speedup'] is not None and entry['best_speedup'] is not None:
                assert entry['best_speedup'] >= entry['greedy_speedup'] - 1e-10

    def test_anomaly_flags_consistent(self, report):
        anomaly_set = set(report['anomalies'])
        for entry in report['per_problem']:
            expected = entry['problem_id'] in anomaly_set
            assert entry['is_anomalous'] == expected

    def test_bottleneck_values(self, report):
        for entry in report['per_problem']:
            assert entry['bottleneck'] in ('compute_bound', 'memory_bound')

    def test_bottleneck_classification(self, report, reconciled):
        hw = reconciled['hardware_spec']
        catalog = {p['problem_id']: p for p in reconciled['problem_catalog']}
        for entry in report['per_problem']:
            prob = catalog[entry['problem_id']]
            expected_bt = _bottleneck(prob, hw)
            assert entry['bottleneck'] == expected_bt, (
                f"Problem {entry['problem_id']}: expected {expected_bt}, got {entry['bottleneck']}"
            )

    def test_roofline_values(self, report, reconciled):
        hw = reconciled['hardware_spec']
        catalog = {p['problem_id']: p for p in reconciled['problem_catalog']}
        baselines = reconciled['baseline_timings']
        for entry in report['per_problem']:
            prob = catalog[entry['problem_id']]
            pid = str(entry['problem_id'])
            expected_rt = _roofline_time_us(prob, hw)
            expected_max = baselines[pid]['mean_us'] / expected_rt
            assert abs(entry['roofline_time_us'] - expected_rt) < 0.01, (
                f"Problem {pid}: roofline_time_us off"
            )
            assert abs(entry['max_theoretical_speedup'] - expected_max) < 0.001, (
                f"Problem {pid}: max_theoretical_speedup off"
            )

    def test_greedy_speedup_values(self, report, reconciled):
        baselines = reconciled['baseline_timings']
        evals = reconciled['eval_results']
        for entry in report['per_problem']:
            pid = str(entry['problem_id'])
            greedy = _get_greedy(entry['problem_id'], evals)
            if greedy and greedy['correctness'] and _valid_runtime(greedy):
                expected = baselines[pid]['mean_us'] / greedy['runtime']
                assert entry['greedy_speedup'] is not None
                assert abs(entry['greedy_speedup'] - expected) < 1e-4, (
                    f"Problem {pid}: greedy_speedup mismatch"
                )
            else:
                assert entry['greedy_speedup'] is None, (
                    f"Problem {pid}: greedy_speedup should be null"
                )

    def test_best_speedup_values(self, report, reconciled):
        baselines = reconciled['baseline_timings']
        evals = reconciled['eval_results']
        for entry in report['per_problem']:
            pid = str(entry['problem_id'])
            samples = evals.get(pid, [])
            correct_runtimes = [s['runtime'] for s in samples
                                if s['correctness'] and _valid_runtime(s)]
            if correct_runtimes:
                expected = baselines[pid]['mean_us'] / min(correct_runtimes)
                assert entry['best_speedup'] is not None
                assert abs(entry['best_speedup'] - expected) < 1e-4, (
                    f"Problem {pid}: best_speedup mismatch"
                )
            else:
                assert entry['best_speedup'] is None

    def test_data_quality_handling(self, report):
        """Problem 6 has a corrupt negative runtime on a correct sample.
        num_correct should still count it (correct=True), but speedup
        calculations should exclude it."""
        p6 = [e for e in report['per_problem'] if e['problem_id'] == 6][0]
        assert p6['num_correct'] == 5, "Problem 6: all 5 samples are correct"
        # best_speedup should use min of valid runtimes only (340, 345, 350, 360)
        expected_best = 400.0 / 340.0
        assert p6['best_speedup'] is not None
        assert abs(p6['best_speedup'] - expected_best) < 1e-4

    def test_null_runtime_handling(self, report):
        """Problem 1 s2 and problem 8 s1 have NULL runtimes but are correct.
        They should count toward num_correct but not affect speedup."""
        p1 = [e for e in report['per_problem'] if e['problem_id'] == 1][0]
        assert p1['num_correct'] == 4, "Problem 1: 4 correct (including NULL-runtime s2)"

        p8 = [e for e in report['per_problem'] if e['problem_id'] == 8][0]
        assert p8['num_correct'] == 4, "Problem 8: 4 correct (including NULL-runtime s1)"
