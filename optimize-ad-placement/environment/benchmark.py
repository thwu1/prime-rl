#!/usr/bin/env python3
"""Benchmark runner: evaluates a solver on all test cases, stores results
in an SQLite database for analysis, and outputs a JSON summary."""

import subprocess
import glob
import os
import sys
import json
import sqlite3
import time
import argparse
import math


def case_metadata(input_file):
    """Compute distribution metadata for a test case."""
    with open(input_file) as f:
        lines = f.read().strip().split('\n')
    n = int(lines[0])
    coords, areas = [], []
    for i in range(1, n + 1):
        parts = lines[i].split()
        coords.append((int(parts[0]), int(parts[1])))
        areas.append(int(parts[2]))

    mean_a = sum(areas) / n
    var_a = sum((a - mean_a) ** 2 for a in areas) / n
    cv = math.sqrt(var_a) / mean_a if mean_a > 0 else 0

    mean_x = sum(c[0] for c in coords) / n
    mean_y = sum(c[1] for c in coords) / n
    spread = math.sqrt(
        sum((c[0] - mean_x) ** 2 + (c[1] - mean_y) ** 2 for c in coords) / n
    )

    max_a = max(areas)
    x_vals = [c[0] for c in coords]
    y_vals = [c[1] for c in coords]
    x_range = max(x_vals) - min(x_vals)
    y_range = max(y_vals) - min(y_vals)

    if max_a > 20000000:
        dtype = 'extreme_areas'
    elif spread < 2500:
        dtype = 'clustered'
    elif x_range < 200:
        dtype = 'near_collinear'
    elif x_range < 5000 or y_range < 5000:
        dtype = 'half_plane'
    else:
        dtype = 'uniform'

    return n, dtype, round(cv, 4), round(spread, 2), round(max_a / 1e8 * 100, 2)


def main():
    ap = argparse.ArgumentParser(
        description='Benchmark solver and track results in SQLite')
    ap.add_argument('--solver', default='/app/solver.py',
                    help='Path to solver script')
    ap.add_argument('--db', default='/app/results.db',
                    help='Path to SQLite database')
    ap.add_argument('--tag', default='default',
                    help='Tag for this benchmark run')
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS case_metadata (
            case_id TEXT PRIMARY KEY,
            n INTEGER,
            distribution_type TEXT,
            area_cv REAL,
            spatial_spread REAL,
            max_area_pct REAL
        );
        CREATE TABLE IF NOT EXISTS runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            solver TEXT,
            tag TEXT,
            case_id TEXT,
            score REAL,
            runtime_ms REAL,
            ts TEXT DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    db.commit()

    cases = sorted(glob.glob('/app/test_cases/input_*.txt'))
    if not cases:
        print(json.dumps({'error': 'No test cases found'}))
        sys.exit(1)

    # Populate / refresh case metadata
    for inp in cases:
        cid = os.path.basename(inp).replace('input_', '').replace('.txt', '')
        n, dt, cv, sp, ma = case_metadata(inp)
        db.execute(
            'INSERT OR REPLACE INTO case_metadata VALUES(?,?,?,?,?,?)',
            (cid, n, dt, cv, sp, ma))
    db.commit()

    solver_name = os.path.basename(args.solver)
    results = []

    for inp in cases:
        cid = os.path.basename(inp).replace('input_', '').replace('.txt', '')
        with open(inp) as f:
            data = f.read()

        t0 = time.time()
        try:
            r = subprocess.run(
                ['python3', args.solver], input=data,
                capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            db.execute(
                'INSERT INTO runs(solver,tag,case_id,score,runtime_ms) '
                'VALUES(?,?,?,?,?)',
                (solver_name, args.tag, cid, 0.0, 120000))
            results.append({
                'case_id': cid, 'score': 0.0,
                'runtime_ms': 120000, 'error': 'timeout'})
            continue

        ms = round((time.time() - t0) * 1000, 1)

        if r.returncode != 0:
            db.execute(
                'INSERT INTO runs(solver,tag,case_id,score,runtime_ms) '
                'VALUES(?,?,?,?,?)',
                (solver_name, args.tag, cid, 0.0, ms))
            results.append({
                'case_id': cid, 'score': 0.0,
                'runtime_ms': ms, 'error': r.stderr[:300]})
            continue

        out_file = inp.replace('input_', 'output_')
        with open(out_file, 'w') as f:
            f.write(r.stdout)

        r2 = subprocess.run(
            ['python3', '/app/scorer.py', inp, out_file],
            capture_output=True, text=True, timeout=30)

        sc = 0.0
        if r2.returncode == 0:
            for line in r2.stdout.strip().split('\n'):
                if 'Satisfaction:' in line:
                    sc = float(line.split(':')[1].strip())

        db.execute(
            'INSERT INTO runs(solver,tag,case_id,score,runtime_ms) '
            'VALUES(?,?,?,?,?)',
            (solver_name, args.tag, cid, sc, ms))
        results.append({'case_id': cid, 'score': sc, 'runtime_ms': ms})

    db.commit()
    db.close()

    scores = [r['score'] for r in results]
    summary = {
        'solver': solver_name,
        'tag': args.tag,
        'num_cases': len(results),
        'avg_score': round(sum(scores) / len(scores), 6) if scores else 0,
        'min_score': round(min(scores), 6) if scores else 0,
        'max_score': round(max(scores), 6) if scores else 0,
        'cases': results
    }
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
