#!/usr/bin/env python3
"""Audit GPU kernel benchmark evaluation results for reliability issues."""

import json
import math
import statistics


def load_data():
    with open('/app/eval_data/hardware.json') as f:
        hardware = json.load(f)
    with open('/app/eval_data/problems.json') as f:
        problems = json.load(f)
    with open('/app/eval_data/results.json') as f:
        results = json.load(f)
    return hardware, {p['problem_id']: p for p in problems}, results


def coefficient_of_variation(trials):
    if len(trials) < 2:
        return 0.0
    m = statistics.mean(trials)
    if m == 0:
        return float('inf')
    return statistics.stdev(trials) / m


def detect_bimodal(trials):
    """Detect bimodal distribution indicating cache contamination.

    Sorts trials by value and looks for a large relative gap that splits
    the data into two internally-consistent clusters. Returns the higher
    cluster (cold-cache values) if bimodal.
    """
    sorted_vals = sorted(trials)
    n = len(sorted_vals)
    if n < 5:
        return False, None, None

    best_gap_ratio = 0
    best_split = -1

    for i in range(2, n - 1):
        gap = sorted_vals[i] - sorted_vals[i - 1]
        lower_max = sorted_vals[i - 1]
        if lower_max > 0:
            ratio = gap / lower_max
            if ratio > best_gap_ratio:
                best_gap_ratio = ratio
                best_split = i

    if best_gap_ratio > 0.3 and best_split > 0:
        low_cluster = sorted_vals[:best_split]
        high_cluster = sorted_vals[best_split:]
        if len(low_cluster) >= 2 and len(high_cluster) >= 2:
            low_cv = coefficient_of_variation(low_cluster)
            high_cv = coefficient_of_variation(high_cluster)
            if low_cv < 0.15 and high_cv < 0.15:
                return True, low_cluster, high_cluster

    return False, None, None


def theoretical_min_time_us(problem, hw_config):
    """Compute roofline-model theoretical minimum execution time in microseconds."""
    precision = problem['default_precision']
    if precision == 'fp16':
        peak = hw_config['peak_flops_fp16']
    else:
        peak = hw_config['peak_flops_fp32']

    compute_time_s = problem['total_flops'] / peak
    memory_time_s = problem['total_memory_bytes'] / hw_config['memory_bandwidth_bytes_per_sec']
    return max(compute_time_s, memory_time_s) * 1e6


def standard_tolerance(precision):
    """Return the standard numerical tolerance for a given floating-point precision."""
    if precision in ('fp16', 'bf16'):
        return 1e-2
    return 1e-4


def main():
    hardware, problems, results = load_data()

    anomalies = []
    corrected_timings = {}

    for r in results:
        rid = r['result_id']
        trials = r.get('kernel_timing_trials_us')

        if trials is None:
            continue

        # 1. Check for bimodal distribution (cache artifact)
        is_bimodal, low_cluster, high_cluster = detect_bimodal(trials)
        if is_bimodal:
            cold_mean = statistics.mean(high_cluster)
            corrected_timings[rid] = cold_mean
            anomalies.append({
                'result_id': rid,
                'anomaly_type': 'cache_artifact',
                'recommendation': 'correct',
            })
            continue

        # 2. Check timing stability (coefficient of variation)
        cv = coefficient_of_variation(trials)
        if cv > 0.3:
            anomalies.append({
                'result_id': rid,
                'anomaly_type': 'timing_unstable',
                'recommendation': 'exclude',
            })
            continue

        # 3. Check against roofline bound (physically impossible speedup)
        problem = problems[r['problem_id']]
        hw = hardware[r['hardware']]
        t_min = theoretical_min_time_us(problem, hw)
        kernel_mean = statistics.mean(trials)

        if kernel_mean < t_min * 0.9:
            anomalies.append({
                'result_id': rid,
                'anomaly_type': 'exceeds_roofline',
                'recommendation': 'exclude',
            })
            continue

        # 4. Check tolerance vs precision consistency
        precision = r.get('precision', problem['default_precision'])
        expected_atol = standard_tolerance(precision)
        actual_atol = r.get('tolerance', {}).get('atol', expected_atol)

        if actual_atol > expected_atol * 5:
            anomalies.append({
                'result_id': rid,
                'anomaly_type': 'tolerance_mismatch',
                'recommendation': 'exclude',
            })
            continue

    # Compute corrected metrics per hardware
    excluded_ids = {a['result_id'] for a in anomalies if a['recommendation'] == 'exclude'}

    corrected_metrics = {}
    for hw_name in hardware:
        hw_results = [
            r for r in results
            if r['hardware'] == hw_name and r['result_id'] not in excluded_ids
        ]
        total = len(hw_results)

        fast_counts = {0.0: 0, 1.0: 0, 2.0: 0}

        for r in hw_results:
            if not r.get('correctness', False):
                continue

            trials = r.get('kernel_timing_trials_us')
            ref_trials = r.get('ref_timing_trials_us')
            if trials is None or ref_trials is None:
                continue

            rid = r['result_id']
            if rid in corrected_timings:
                kernel_mean = corrected_timings[rid]
            else:
                kernel_mean = statistics.mean(trials)

            ref_mean = statistics.mean(ref_trials)
            speedup = ref_mean / kernel_mean

            for t in fast_counts:
                if speedup >= t:
                    fast_counts[t] += 1

        corrected_metrics[hw_name] = {
            f'fast_{t:.1f}': fast_counts[t] / total if total > 0 else 0.0
            for t in fast_counts
        }

    excluded_count = len(excluded_ids)
    report = {
        'anomalies': anomalies,
        'corrected_metrics': corrected_metrics,
        'total_results': len(results),
        'clean_count': len(results) - excluded_count,
        'excluded_count': excluded_count,
    }

    with open('/app/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Audit complete: {len(anomalies)} anomalies found, {excluded_count} excluded.")
    print(f"Report written to /app/audit_report.json")


if __name__ == '__main__':
    main()
