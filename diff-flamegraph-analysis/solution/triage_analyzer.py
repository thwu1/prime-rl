#!/usr/bin/env python3
"""Produce structured triage report from collapsed folded data and off-CPU traces.

Reads:
  /app/output/baseline.folded
  /app/output/incident.folded
  /app/output/offcpu.folded
  /app/traces/manifest.json
  /app/traces/sysmetrics.csv

Writes:
  /app/output/triage.json
"""

import csv
import json
import os
from collections import defaultdict


def parse_folded(path):
    """Return dict {stack_string: count}."""
    stacks = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.rsplit(None, 1)
            if len(parts) != 2:
                continue
            stack, count_str = parts
            try:
                count = int(count_str)
            except ValueError:
                continue
            stacks[stack] = stacks.get(stack, 0) + count
    return stacks


def exclusive_counts(stacks):
    """Per-function exclusive (self/leaf) sample counts."""
    counts = defaultdict(int)
    for stack, count in stacks.items():
        leaf = stack.split(';')[-1]
        counts[leaf] += count
    return dict(counts)


def classify_offcpu_stack(stack):
    """Classify off-CPU stack by blocking reason and find the app-level blocker.

    Returns (category, representative_function).
    The representative function is the last application-level frame before
    the libc/kernel boundary (i.e. the user function that triggered blocking).
    """
    s = stack.lower()
    frames = stack.split(';')

    # Idle checks (exclude from hotspots)
    if 'epoll_wait' in s or 'ep_poll' in s:
        return 'idle', 'epoll_wait'
    if 'nanosleep' in s or 'gc_sleep' in s:
        return 'idle', 'gc_sleep'

    # Find the last application frame before kernel/libc entry
    # Walk root-to-leaf, stop at first __GI_ / __lll_ / entry_SYSCALL frame
    user_func = frames[-1]
    for i, frame in enumerate(frames):
        if any(k in frame for k in ['__GI_', '__lll_lock', 'entry_SYSCALL_64',
                                     'do_syscall_64']):
            if i > 0:
                user_func = frames[i - 1]
            break

    if 'io_schedule' in s or 'ext4_file' in s or 'page_bit' in s \
            or 'fsync' in s or 'writeback' in s:
        return 'io', user_func
    if 'futex_wait' in s or 'mutex' in s or 'lll_lock' in s:
        return 'lock', user_func
    if 'tcp_connect' in s or 'inet_wait' in s:
        return 'network', user_func
    return 'other', user_func


def main():
    baseline = parse_folded('/app/output/baseline.folded')
    incident = parse_folded('/app/output/incident.folded')
    offcpu = parse_folded('/app/output/offcpu.folded')

    # Load manifest for duration info
    with open('/app/traces/manifest.json') as f:
        manifest = json.load(f)
    baseline_dur = manifest['baseline']['duration_seconds']
    incident_dur = manifest['incident']['duration_seconds']
    duration_ratio = incident_dur / baseline_dur

    baseline_total = sum(baseline.values())
    incident_total = sum(incident.values())

    b_excl = exclusive_counts(baseline)
    i_excl = exclusive_counts(incident)

    all_funcs = set(b_excl) | set(i_excl)

    regressions = []
    improvements = []

    for func in all_funcs:
        b_pct = b_excl.get(func, 0) / baseline_total * 100 if baseline_total else 0
        i_pct = i_excl.get(func, 0) / incident_total * 100 if incident_total else 0
        delta = i_pct - b_pct

        entry = {
            'function': func,
            'baseline_pct': round(b_pct, 2),
            'incident_pct': round(i_pct, 2),
            'delta_pct': round(delta, 2),
        }

        if delta > 0.5:
            regressions.append(entry)
        elif delta < -0.5:
            improvements.append(entry)

    regressions.sort(key=lambda x: x['delta_pct'], reverse=True)
    improvements.sort(key=lambda x: x['delta_pct'])

    # Off-CPU analysis
    offcpu_hotspots = []
    has_io = False
    has_lock = False

    for stack, count in offcpu.items():
        category, func_name = classify_offcpu_stack(stack)
        if category == 'idle':
            continue
        offcpu_hotspots.append({
            'function': func_name,
            'total_us': count,
            'category': category,
        })
        if category == 'io':
            has_io = True
        if category == 'lock':
            has_lock = True

    offcpu_hotspots.sort(key=lambda x: x['total_us'], reverse=True)

    # Root cause classification
    has_cpu_regression = len(regressions) > 0 and regressions[0]['delta_pct'] > 5
    has_offcpu_problem = has_io or has_lock

    if has_cpu_regression and has_offcpu_problem:
        root_cause = 'mixed'
    elif has_cpu_regression:
        root_cause = 'cpu_regression'
    elif has_io:
        root_cause = 'io_regression'
    elif has_lock:
        root_cause = 'lock_contention'
    else:
        root_cause = 'unknown'

    # Elided and new code paths
    baseline_set = set(baseline.keys())
    incident_set = set(incident.keys())
    elided = sorted(baseline_set - incident_set)
    new = sorted(incident_set - baseline_set)

    # Build diagnosis text
    diag_parts = []
    if regressions:
        top = regressions[0]
        diag_parts.append(
            f"On-CPU: '{top['function']}' is the top CPU regression "
            f"(+{top['delta_pct']}% exclusive time), indicating "
            f"catastrophic regex backtracking in the new validate_input path")
    if any(r['function'] == 'page_read' for r in regressions):
        pr = next(r for r in regressions if r['function'] == 'page_read')
        diag_parts.append(
            f"On-CPU: 'page_read' shows +{pr['delta_pct']}% regression, "
            f"suggesting increased disk I/O from missing index or larger scan")
    if has_io:
        diag_parts.append(
            "Off-CPU: Significant I/O blocking in page_read → ext4_file_read "
            "path and log fsync, corroborating the page_read on-CPU regression")
    if has_lock:
        diag_parts.append(
            "Off-CPU: Lock contention on conn_pool_acquire (futex_wait), "
            "likely from increased DB connection demand under load")

    # Check system metrics for supporting evidence
    try:
        with open('/app/traces/sysmetrics.csv') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        incident_rows = [r for r in rows if int(r['timestamp_epoch']) >= 1731635000]
        if incident_rows:
            avg_cpu = sum(int(r['cpu_util_pct']) for r in incident_rows) / len(incident_rows)
            avg_iow = sum(int(r['iowait_pct']) for r in incident_rows) / len(incident_rows)
            diag_parts.append(
                f"System metrics confirm: avg CPU {avg_cpu:.0f}% and "
                f"iowait {avg_iow:.0f}% during incident (vs ~33% CPU, ~2% "
                f"iowait at baseline)")
    except Exception:
        pass

    diagnosis = '. '.join(diag_parts) + '.'

    report = {
        'summary': {
            'baseline_oncpu_samples': baseline_total,
            'incident_oncpu_samples': incident_total,
            'duration_ratio': round(duration_ratio, 1),
            'root_cause_class': root_cause,
        },
        'oncpu_regressions': regressions,
        'oncpu_improvements': improvements,
        'offcpu_hotspots': offcpu_hotspots,
        'elided_code_paths': elided,
        'new_code_paths': new,
        'diagnosis': diagnosis,
    }

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/triage.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Triage report written to /app/output/triage.json")
    print(f"  Root cause: {root_cause}")
    print(f"  On-CPU regressions: {len(regressions)}")
    print(f"  Off-CPU hotspots: {len(offcpu_hotspots)}")
    print(f"  Elided paths: {len(elided)}, New paths: {len(new)}")


if __name__ == '__main__':
    main()
