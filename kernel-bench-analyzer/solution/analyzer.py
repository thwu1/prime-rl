#!/usr/bin/env python3
"""
GPU Kernel Benchmark Evaluation Analyzer — Full reconciliation pipeline.

Reconciles data from SQLite DB, legacy JSON logs, CSV catalog with errata,
TOML hardware specs, and JSON baselines to produce /app/report.json.
"""

import json
import csv
import sqlite3
import math
import os
import tomllib
from math import comb


def load_and_dedup_db():
    """Load DB samples, deduplicate by (problem_id, sample_id) preferring latest run_id."""
    conn = sqlite3.connect('/app/benchmarks.db')
    cursor = conn.execute("""
        SELECT problem_id, sample_id, compiled, correct, runtime_us, run_id
        FROM samples
        ORDER BY run_id DESC
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
                'runtime': runtime,
            }
    conn.close()

    results = {}
    for (pid, sid), sample in sorted(seen.items()):
        pid_str = str(pid)
        if pid_str not in results:
            results[pid_str] = []
        results[pid_str].append(sample)
    return results


def load_legacy():
    """Load legacy JSON logs, convert ms→us, normalize field names."""
    legacy = {}
    legacy_dir = '/app/legacy'
    for fname in sorted(os.listdir(legacy_dir)):
        if not fname.endswith('.json'):
            continue
        with open(os.path.join(legacy_dir, fname)) as f:
            data = json.load(f)

        unit = data.get('run_metadata', {}).get('timing_unit', 'microseconds')
        for pid_str, samples in data.get('results', {}).items():
            if pid_str in legacy:
                continue
            converted = []
            for s in samples:
                rt_ms = s.get('exec_time_ms', -1.0)
                if unit == 'milliseconds' and rt_ms > 0:
                    rt_us = rt_ms * 1000.0
                elif rt_ms > 0:
                    rt_us = rt_ms
                else:
                    rt_us = None

                converted.append({
                    'sample_id': s['sample_id'],
                    'compiled': s.get('built', False),
                    'correctness': s.get('passed', False),
                    'runtime': rt_us,
                })
            legacy[pid_str] = converted
    return legacy


def load_catalog_with_errata():
    """Load CSV catalog and apply errata corrections."""
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

    with open('/app/catalog/errata.json') as f:
        errata = json.load(f)
    corrections = {c['problem_id']: c for c in errata.get('corrections', [])}
    for prob in catalog:
        if prob['problem_id'] in corrections:
            c = corrections[prob['problem_id']]
            prob[c['field']] = c['corrected_value']
    return catalog


def load_hardware():
    with open('/app/hardware/system_info.toml', 'rb') as f:
        data = tomllib.load(f)
    return {
        'peak_fp32_tflops': data['gpu']['compute']['peak_fp32_tflops'],
        'memory_bandwidth_gb_s': data['gpu']['memory']['bandwidth_gb_s'],
    }


def load_baselines():
    with open('/app/baselines/pytorch_baseline.json') as f:
        return json.load(f)


def valid_runtime(sample):
    r = sample.get('runtime')
    return r is not None and r > 0


def roofline_time_us(prob, hw):
    compute_us = prob['flops'] / (hw['peak_fp32_tflops'] * 1e6)
    memory_us = prob['memory_bytes'] / (hw['memory_bandwidth_gb_s'] * 1e3)
    return max(compute_us, memory_us)


def bottleneck_type(prob, hw):
    compute_us = prob['flops'] / (hw['peak_fp32_tflops'] * 1e6)
    memory_us = prob['memory_bytes'] / (hw['memory_bandwidth_gb_s'] * 1e3)
    return 'compute_bound' if compute_us > memory_us else 'memory_bound'


def get_greedy(pid, evals):
    samples = evals.get(str(pid), [])
    matches = [s for s in samples if s['sample_id'] == 0]
    return matches[0] if matches else None


def compute_fast_p(data, thresholds, exclude_pids=None):
    exclude = set(exclude_pids or [])
    problems = [p for p in data['problem_catalog'] if p['problem_id'] not in exclude]
    total = len(problems)
    if total == 0:
        return {str(t): 0.0 for t in thresholds}

    results = {}
    for t in thresholds:
        count = 0
        for prob in problems:
            pid = str(prob['problem_id'])
            greedy = get_greedy(prob['problem_id'], data['eval_results'])
            if greedy and greedy['correctness'] and valid_runtime(greedy):
                su = data['baseline_timings'][pid]['mean_us'] / greedy['runtime']
                if su >= t:
                    count += 1
        results[str(t)] = count / total
    return results


def compute_pass_at_k(data, k_values):
    results = {}
    for k in k_values:
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
        results[str(k)] = sum(values) / len(values) if values else 0.0
    return results


def compute_geo_mean(data):
    log_speedups = []
    for prob in data['problem_catalog']:
        pid = str(prob['problem_id'])
        greedy = get_greedy(prob['problem_id'], data['eval_results'])
        if greedy and greedy['correctness'] and valid_runtime(greedy):
            su = data['baseline_timings'][pid]['mean_us'] / greedy['runtime']
            log_speedups.append(math.log(su))
    if not log_speedups:
        return 0.0
    return math.exp(sum(log_speedups) / len(log_speedups))


def detect_anomalies(data):
    hw = data['hardware_spec']
    anomalies = []
    for prob in data['problem_catalog']:
        pid = str(prob['problem_id'])
        rt = roofline_time_us(prob, hw)
        max_su = data['baseline_timings'][pid]['mean_us'] / rt
        samples = data['eval_results'].get(pid, [])
        for s in samples:
            if s['correctness'] and valid_runtime(s):
                su = data['baseline_timings'][pid]['mean_us'] / s['runtime']
                if su > max_su:
                    anomalies.append(prob['problem_id'])
                    break
    return sorted(anomalies)


def detect_flaky(data):
    flaky = []
    for prob in data['problem_catalog']:
        pid = str(prob['problem_id'])
        samples = data['eval_results'].get(pid, [])
        n = len(samples)
        c = sum(1 for s in samples if s['correctness'])
        if 0 < c < n:
            flaky.append(prob['problem_id'])
    return sorted(flaky)


def compute_difficulty_breakdown(data):
    hw = data['hardware_spec']
    groups = {'compute_bound': [], 'memory_bound': []}
    for prob in data['problem_catalog']:
        bt = bottleneck_type(prob, hw)
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
            greedy = get_greedy(prob['problem_id'], data['eval_results'])
            if greedy and greedy['correctness'] and valid_runtime(greedy):
                su = data['baseline_timings'][pid]['mean_us'] / greedy['runtime']
                if su >= 1.0:
                    count += 1
        result[bt] = count / total
    return result


def build_per_problem(data, anomalies):
    hw = data['hardware_spec']
    anomaly_set = set(anomalies)
    per_problem = []

    for prob in data['problem_catalog']:
        pid = str(prob['problem_id'])
        rt = roofline_time_us(prob, hw)
        max_su = data['baseline_timings'][pid]['mean_us'] / rt
        bt = bottleneck_type(prob, hw)

        samples = data['eval_results'].get(pid, [])
        num_compiled = sum(1 for s in samples if s['compiled'])
        num_correct = sum(1 for s in samples if s['correctness'])

        greedy = get_greedy(prob['problem_id'], data['eval_results'])
        greedy_su = None
        if greedy and greedy['correctness'] and valid_runtime(greedy):
            greedy_su = data['baseline_timings'][pid]['mean_us'] / greedy['runtime']

        correct_runtimes = [s['runtime'] for s in samples
                            if s['correctness'] and valid_runtime(s)]
        best_su = None
        if correct_runtimes:
            best_su = data['baseline_timings'][pid]['mean_us'] / min(correct_runtimes)

        per_problem.append({
            'problem_id': prob['problem_id'],
            'name': prob['name'],
            'num_compiled': num_compiled,
            'num_correct': num_correct,
            'num_samples': len(samples),
            'greedy_speedup': greedy_su,
            'best_speedup': best_su,
            'is_anomalous': prob['problem_id'] in anomaly_set,
            'roofline_time_us': rt,
            'max_theoretical_speedup': max_su,
            'bottleneck': bt,
        })
    return per_problem


def main():
    # Load and reconcile all data sources
    db_results = load_and_dedup_db()
    legacy = load_legacy()
    catalog = load_catalog_with_errata()
    hw = load_hardware()
    baselines = load_baselines()

    # Merge: DB is authoritative; legacy fills gaps for problems not in DB
    db_pids = set(db_results.keys())
    eval_results = dict(db_results)
    for pid_str, samples in legacy.items():
        if pid_str not in db_pids:
            eval_results[pid_str] = samples

    data = {
        'eval_results': eval_results,
        'problem_catalog': catalog,
        'hardware_spec': hw,
        'baseline_timings': baselines,
    }

    thresholds = [0.0, 0.5, 1.0, 1.5, 2.0]
    anomalies = detect_anomalies(data)

    report = {
        'fast_p': compute_fast_p(data, thresholds),
        'pass_at_k': compute_pass_at_k(data, [1, 3, 5]),
        'geometric_mean_speedup': compute_geo_mean(data),
        'anomalies': anomalies,
        'corrected_fast_p': compute_fast_p(data, thresholds, exclude_pids=anomalies),
        'difficulty_breakdown': compute_difficulty_breakdown(data),
        'flaky_problems': detect_flaky(data),
        'per_problem': build_per_problem(data, anomalies),
    }

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("Report written to /app/report.json")


if __name__ == '__main__':
    main()
