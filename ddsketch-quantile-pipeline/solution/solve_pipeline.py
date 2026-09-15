#!/usr/bin/env python3
"""
Complete solution: fix pipeline bugs, implement SLO evaluation,
benchmark configurations with p99-focused analysis, identify
Pareto-optimal, generate evaluation report.
"""

import csv
import json
import math
import os
import sqlite3
import subprocess
import sys
from collections import defaultdict

import yaml

# ============================================================
# Phase 1: Fix the three pipeline bugs
# ============================================================

# Bug 1: aggregator.py — merge uses max() for overlapping bucket keys.
# Independent host sketches represent separate observations whose counts
# must be SUMMED. Using max() discards most data, causing merged counts
# to be ~1/N of the true total and all quantiles to fall through to max_val.
with open('/app/pipeline/aggregator.py') as f:
    code = f.read()
code = code.replace(
    'target.store[key] = max(target.store[key], cnt)',
    'target.store[key] = target.store[key] + cnt'
)
with open('/app/pipeline/aggregator.py', 'w') as f:
    f.write(code)
print("Fixed aggregator.py: merge now sums bucket counts")

# Bug 2: sketch_engine.py — CollapsingQuantileSketch._collapse() removes
# the HIGHEST-key buckets instead of the LOWEST. This destroys tail-end
# resolution needed for p95/p99. Correct: collapse from the bottom,
# sacrificing low-quantile accuracy to preserve tail precision.
with open('/app/pipeline/sketch_engine.py') as f:
    code = f.read()
old_collapse = (
    '            hi_key = keys[-1]\n'
    '            next_key = keys[-2]\n'
    '            self.store[next_key] += self.store[hi_key]\n'
    '            del self.store[hi_key]'
)
new_collapse = (
    '            lo_key = keys[0]\n'
    '            next_key = keys[1]\n'
    '            self.store[next_key] += self.store[lo_key]\n'
    '            del self.store[lo_key]'
)
code = code.replace(old_collapse, new_collapse)
with open('/app/pipeline/sketch_engine.py', 'w') as f:
    f.write(code)
print("Fixed sketch_engine.py: collapse now removes lowest-key buckets")

# Bug 3: reporter.py — anomaly detection uses absolute difference instead
# of relative change. The threshold (0.5) represents a 50% relative change,
# but abs(current - previous) is in raw milliseconds. Normal inter-window
# variation of a few ms exceeds 0.5, creating false positives everywhere.
with open('/app/pipeline/reporter.py') as f:
    code = f.read()
code = code.replace(
    'change = abs(current - previous)',
    'change = abs(current - previous) / previous if previous > 0 else 0.0'
)
with open('/app/pipeline/reporter.py', 'w') as f:
    f.write(code)
print("Fixed reporter.py: anomaly detection now uses relative change")

# ============================================================
# Phase 2: Run the fixed pipeline
# ============================================================

print("\nRunning fixed pipeline...")
result = subprocess.run(
    [sys.executable, '/app/pipeline/run_pipeline.py'],
    capture_output=True, text=True, cwd='/app'
)
print(result.stdout)
if result.returncode != 0:
    print("Pipeline FAILED:", result.stderr)
    sys.exit(1)

# ============================================================
# Phase 3: Load configuration and pipeline output
# ============================================================

with open('/app/config.yaml') as f:
    config = yaml.safe_load(f)

with open('/app/output/report.json') as f:
    pipeline_report = json.load(f)

# Load raw data for exact quantile computation
data_dir = config['data']['input_dir']
window_data = defaultdict(list)
for fname in sorted(os.listdir(data_dir)):
    if not fname.endswith('.csv'):
        continue
    with open(os.path.join(data_dir, fname)) as f:
        reader = csv.DictReader(f)
        for row in reader:
            wid = int(row['window_id'])
            lat = float(row['latency_ms'])
            window_data[wid].append(lat)

num_windows = len(pipeline_report['windows'])
quantile_levels = config['quantiles']


def exact_quantile(data, q):
    sorted_data = sorted(data)
    n = len(sorted_data)
    rank = int(math.ceil(q * n))
    return sorted_data[min(rank - 1, n - 1)]


# Pre-compute exact quantiles for all windows
exact_qs = {}
for wid in range(num_windows):
    exact_qs[wid] = {}
    for q in quantile_levels:
        exact_qs[wid][q] = exact_quantile(window_data[wid], q)

# ============================================================
# Phase 4: SLO Compliance Evaluation
# ============================================================

target_p99 = config['slo']['target_p99_ms']
ewma_decay = config['slo']['ewma_decay']

slo_windows = {}
breach_windows = []
ewma = 1.0
compliant_count = 0

for wid in range(num_windows):
    wid_str = str(wid)
    p99 = pipeline_report['windows'][wid_str]['quantiles']['0.99']
    compliant = p99 <= target_p99

    if compliant:
        compliant_count += 1
        breach_severity = 0.0
        indicator = 1.0
    else:
        breach_severity = (p99 - target_p99) / target_p99
        breach_windows.append(wid)
        indicator = 0.0

    ewma = ewma_decay * indicator + (1.0 - ewma_decay) * ewma

    slo_windows[wid_str] = {
        "p99": round(p99, 4),
        "compliant": compliant,
        "breach_severity": round(breach_severity, 4),
        "ewma_score": round(ewma, 4)
    }

overall_pct = round(100.0 * compliant_count / num_windows, 2)

slo_evaluation = {
    "target_p99_ms": target_p99,
    "ewma_decay": ewma_decay,
    "overall_compliance_pct": overall_pct,
    "windows": slo_windows,
    "breach_windows": breach_windows
}

print("SLO compliance: {}%, breaches: {}".format(overall_pct, breach_windows))

# ============================================================
# Phase 5: Configuration Benchmark with p99-focused analysis
# ============================================================

# Import the now-fixed pipeline modules
sys.path.insert(0, '/app/pipeline')
from sketch_engine import CollapsingQuantileSketch
from data_loader import load_host_data
from aggregator import merge_sketches

alpha_values = config['benchmark']['alpha_values']
max_buckets_values = config['benchmark']['max_buckets_values']
host_data = load_host_data(data_dir)

benchmark_results = []

print("\nBenchmarking {} configurations...".format(
    len(alpha_values) * len(max_buckets_values)))

for alpha in alpha_values:
    for mb in max_buckets_values:
        win_sketches = {}
        max_b_used = 0

        for host, windows in sorted(host_data.items()):
            for wid, latencies in sorted(windows.items()):
                host_sketch = CollapsingQuantileSketch(alpha, mb)
                for lat in latencies:
                    host_sketch.add(lat)

                if wid not in win_sketches:
                    win_sketches[wid] = CollapsingQuantileSketch(alpha, mb)

                merge_sketches(win_sketches[wid], host_sketch)
                b = win_sketches[wid].num_buckets()
                if b > max_b_used:
                    max_b_used = b

        # Compute relative errors vs exact quantiles, tracking p99 separately
        all_errors = []
        p99_errors = []
        for wid in range(num_windows):
            for q in quantile_levels:
                exact = exact_qs[wid][q]
                estimated = win_sketches[wid].quantile(q)
                if exact > 0:
                    rel_err = abs(estimated - exact) / exact
                    all_errors.append(rel_err)
                    if q == 0.99:
                        p99_errors.append(rel_err)

        max_err = max(all_errors) if all_errors else 0.0
        mean_err = sum(all_errors) / len(all_errors) if all_errors else 0.0
        p99_max_err = max(p99_errors) if p99_errors else 0.0

        benchmark_results.append({
            "alpha": alpha,
            "max_buckets": mb,
            "max_relative_error": round(max_err, 6),
            "mean_relative_error": round(mean_err, 6),
            "memory_buckets": max_b_used,
            "p99_max_relative_error": round(p99_max_err, 6),
        })

        print("  alpha={}, max_buckets={}: max_err={:.6f}, p99_max_err={:.6f}, memory={}".format(
            alpha, mb, max_err, p99_max_err, max_b_used))

# ============================================================
# Phase 6: Store benchmark results in SQLite
# ============================================================

db_path = config['data']['benchmark_db']
os.makedirs(os.path.dirname(db_path), exist_ok=True)

conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute('DROP TABLE IF EXISTS benchmark')
cur.execute('''CREATE TABLE benchmark (
    alpha REAL,
    max_buckets INTEGER,
    max_relative_error REAL,
    mean_relative_error REAL,
    memory_buckets INTEGER,
    p99_max_relative_error REAL,
    PRIMARY KEY (alpha, max_buckets)
)''')

for r in benchmark_results:
    cur.execute(
        'INSERT INTO benchmark '
        '(alpha, max_buckets, max_relative_error, mean_relative_error, '
        'memory_buckets, p99_max_relative_error) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (r['alpha'], r['max_buckets'], r['max_relative_error'],
         r['mean_relative_error'], r['memory_buckets'],
         r['p99_max_relative_error'])
    )
conn.commit()

# ============================================================
# Phase 7: Find Pareto-optimal configurations (p99-focused)
# ============================================================
# Pareto analysis uses (p99_max_relative_error, memory_buckets) because
# tail-quantile accuracy is the primary optimization target for latency
# monitoring. DDSketch's low-end collapsing preserves p99 accuracy even
# when overall max_relative_error is elevated by low-quantile degradation.

cur.execute('''
    SELECT b1.alpha, b1.max_buckets, b1.p99_max_relative_error, b1.memory_buckets
    FROM benchmark b1
    WHERE NOT EXISTS (
        SELECT 1 FROM benchmark b2
        WHERE b2.p99_max_relative_error <= b1.p99_max_relative_error
          AND b2.memory_buckets <= b1.memory_buckets
          AND (b2.p99_max_relative_error < b1.p99_max_relative_error
               OR b2.memory_buckets < b1.memory_buckets)
    )
    ORDER BY b1.memory_buckets, b1.p99_max_relative_error
''')

pareto_rows = cur.fetchall()
pareto_optimal = [{"alpha": r[0], "max_buckets": int(r[1])} for r in pareto_rows]

# Recommendation: Pareto-optimal config with lowest p99_max_relative_error
best = min(pareto_rows, key=lambda r: r[2])
recommendation = {
    "alpha": best[0],
    "max_buckets": int(best[1]),
    "reason": "Lowest p99 maximum relative error ({:.6f}) among Pareto-optimal "
              "configurations on (p99_max_relative_error, memory_buckets) dimensions, "
              "using {} memory buckets. Tail-quantile accuracy prioritized for "
              "latency SLO compliance.".format(best[2], best[3])
}

conn.close()

print("\nPareto-optimal (p99 vs memory): {} configs".format(len(pareto_optimal)))
for p in pareto_optimal:
    print("  alpha={}, max_buckets={}".format(p["alpha"], p["max_buckets"]))
print("Recommendation: alpha={}, max_buckets={}".format(
    recommendation['alpha'], recommendation['max_buckets']))

# ============================================================
# Phase 8: Generate evaluation report
# ============================================================

evaluation = {
    "pipeline_report": pipeline_report,
    "slo_evaluation": slo_evaluation,
    "benchmark": {
        "configurations_tested": len(benchmark_results),
        "results": benchmark_results,
        "pareto_optimal": pareto_optimal,
        "recommendation": recommendation
    }
}

eval_path = config['data']['evaluation_path']
os.makedirs(os.path.dirname(eval_path), exist_ok=True)
with open(eval_path, 'w') as f:
    json.dump(evaluation, f, indent=2)

print("\nEvaluation report written to {}".format(eval_path))
