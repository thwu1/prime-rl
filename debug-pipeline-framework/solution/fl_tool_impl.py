#!/usr/bin/env python3

"""
Spectrum-Based Fault Localization Tool with Root-Cause Clustering.

Collects per-test line-level coverage data, computes suspiciousness
scores using SBFL formulas (Ochiai, Tarantula, D*), clusters suspicious
lines by Jaccard similarity on their failure profiles, and outputs
ranked localization results.
"""
import subprocess
import json
import os
import sys
import math
import tempfile


# -------------------------------------------------------------------
# SBFL formulas
# -------------------------------------------------------------------

def compute_ochiai(ef, ep, nf, np_count):
    """Ochiai suspiciousness: ef / sqrt((ef+nf)*(ef+ep))."""
    if ef == 0:
        return 0.0
    denom = math.sqrt((ef + nf) * (ef + ep))
    return 0.0 if denom == 0 else ef / denom


def compute_tarantula(ef, ep, nf, np_count):
    """Tarantula suspiciousness: (ef/total_f) / ((ef/total_f)+(ep/total_p))."""
    if ef == 0:
        return 0.0
    total_failed = ef + nf
    total_passed = ep + np_count
    if total_failed == 0:
        return 0.0
    fail_rate = ef / total_failed
    pass_rate = (ep / total_passed) if total_passed > 0 else 0.0
    denom = fail_rate + pass_rate
    return 0.0 if denom == 0 else fail_rate / denom


def compute_dstar(ef, ep, nf, np_count, star=2):
    """D* suspiciousness: ef^star / (nf + ep)."""
    if ef == 0:
        return 0.0
    denom = nf + ep
    if denom == 0:
        return float('inf')
    return (ef ** star) / denom


# -------------------------------------------------------------------
# Root-cause clustering
# -------------------------------------------------------------------

def cluster_faults(coverage_matrix, rankings, threshold=0.6):
    """Group suspicious lines into root-cause clusters via Jaccard similarity.

    For each line with nonzero suspiciousness, compute its failing-test set
    from the coverage matrix. Build an undirected graph with edges between
    lines whose failing-test Jaccard >= threshold. Each connected component
    is a cluster.
    """
    tests = coverage_matrix['tests']

    # Collect all lines with score > 0
    suspicious = []
    for fpath, entries in rankings.get('rankings', {}).items():
        for entry in entries:
            if entry['score'] > 0:
                suspicious.append({
                    'file': fpath,
                    'line': entry['line'],
                    'score': entry['score'],
                })

    if not suspicious:
        return {
            "method": "jaccard",
            "threshold": threshold,
            "num_clusters": 0,
            "clusters": [],
        }

    # Compute failing-test set for each suspicious line
    failing_sets = []
    for s in suspicious:
        fail_set = set()
        for tid, tdata in tests.items():
            if not tdata['passed']:
                if s['line'] in tdata['covered_lines'].get(s['file'], []):
                    fail_set.add(tid)
        failing_sets.append(fail_set)

    # Build adjacency list (undirected graph, edges for Jaccard >= threshold)
    n = len(suspicious)
    adj = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if not failing_sets[i] or not failing_sets[j]:
                continue
            union = failing_sets[i] | failing_sets[j]
            inter = failing_sets[i] & failing_sets[j]
            jaccard = len(inter) / len(union)
            if jaccard >= threshold:
                adj[i].append(j)
                adj[j].append(i)

    # Find connected components via BFS
    visited = [False] * n
    clusters = []
    cluster_id = 0
    for start in range(n):
        if visited[start]:
            continue
        component = []
        queue = [start]
        visited[start] = True
        while queue:
            node = queue.pop(0)
            component.append(node)
            for neighbor in adj[node]:
                if not visited[neighbor]:
                    visited[neighbor] = True
                    queue.append(neighbor)

        cluster_lines = [suspicious[i] for i in component]
        cluster_failing = set()
        for i in component:
            cluster_failing.update(failing_sets[i])
        modules = sorted(set(l['file'] for l in cluster_lines))

        clusters.append({
            'id': cluster_id,
            'lines': sorted(cluster_lines, key=lambda x: -x['score']),
            'failing_tests': sorted(cluster_failing),
            'modules_involved': modules,
        })
        cluster_id += 1

    # Sort clusters by maximum suspiciousness descending
    clusters.sort(key=lambda c: -max(l['score'] for l in c['lines']))
    for i, c in enumerate(clusters):
        c['id'] = i

    return {
        "method": "jaccard",
        "threshold": threshold,
        "num_clusters": len(clusters),
        "clusters": clusters,
    }


# -------------------------------------------------------------------
# Coverage collection
# -------------------------------------------------------------------

def discover_tests(test_file):
    """Discover test node IDs via pytest --collect-only."""
    result = subprocess.run(
        ['python3', '-m', 'pytest', test_file,
         '--collect-only', '-q', '--no-header'],
        capture_output=True, text=True, cwd='/app'
    )
    tests = []
    for line in result.stdout.strip().split('\n'):
        line = line.strip()
        if '::' in line and not line.startswith((' ', '<')):
            # Strip trailing extra info if any
            if ' ' in line:
                line = line.split(' ')[0]
            tests.append(line)
    return tests


def run_test_with_coverage(test_id, source_dir):
    """Run a single test under coverage, return (passed, covered_lines)."""
    cov_file = tempfile.mktemp(prefix='.cov_', dir='/tmp')
    env = os.environ.copy()
    env['COVERAGE_FILE'] = cov_file

    result = subprocess.run(
        ['python3', '-m', 'coverage', 'run', '--source', source_dir,
         '-m', 'pytest', test_id, '-x', '--tb=no', '-q', '--no-header'],
        capture_output=True, text=True, env=env, cwd='/app'
    )
    passed = result.returncode == 0

    json_file = cov_file + '.json'
    subprocess.run(
        ['python3', '-m', 'coverage', 'json', '-o', json_file],
        capture_output=True, text=True, env=env, cwd='/app'
    )

    covered_lines = {}
    try:
        with open(json_file) as f:
            cov_data = json.load(f)
        for fpath, data in cov_data.get('files', {}).items():
            rel = os.path.relpath(fpath, '/app')
            lines = data.get('executed_lines', [])
            if lines:
                covered_lines[rel] = sorted(lines)
    except (json.JSONDecodeError, FileNotFoundError):
        pass
    finally:
        for p in [cov_file, json_file]:
            try:
                os.unlink(p)
            except OSError:
                pass

    return passed, covered_lines


def collect_coverage(source_dir, test_file):
    """Collect per-test coverage and return a coverage matrix dict."""
    tests = discover_tests(test_file)
    matrix = {"tests": {}}

    for test_id in tests:
        short = test_id.split('::', 1)[1] if '::' in test_id else test_id
        passed, lines = run_test_with_coverage(test_id, source_dir)
        matrix["tests"][short] = {
            "passed": passed,
            "covered_lines": lines,
        }
        tag = "PASS" if passed else "FAIL"
        print(f"  [{tag}] {short}")

    return matrix


# -------------------------------------------------------------------
# Fault localization
# -------------------------------------------------------------------

def localize_faults(coverage_matrix, formula='ochiai'):
    """Compute per-line suspiciousness from coverage matrix."""
    tests = coverage_matrix['tests']

    # Collect all covered files and lines
    all_lines = {}
    for tdata in tests.values():
        for fpath, lines in tdata['covered_lines'].items():
            if fpath not in all_lines:
                all_lines[fpath] = set()
            all_lines[fpath].update(lines)

    total_failed = sum(1 for t in tests.values() if not t['passed'])
    total_passed = sum(1 for t in tests.values() if t['passed'])

    fn = {
        'ochiai': compute_ochiai,
        'tarantula': compute_tarantula,
        'dstar': compute_dstar,
    }[formula]

    rankings = {}
    for fpath, lines in all_lines.items():
        entries = []
        for line in sorted(lines):
            ef = ep = 0
            for tdata in tests.values():
                if line in tdata['covered_lines'].get(fpath, []):
                    if tdata['passed']:
                        ep += 1
                    else:
                        ef += 1
            nf = total_failed - ef
            np_c = total_passed - ep
            score = fn(ef, ep, nf, np_c)
            if score != float('inf'):
                score = round(score, 10)
            entries.append({
                'line': line,
                'score': score,
                'ef': ef,
                'ep': ep,
                'nf': nf,
                'np': np_c,
            })
        entries.sort(key=lambda x: (-x['score'] if x['score'] != float('inf')
                                     else -1e30, x['line']))
        rankings[fpath] = entries

    return {'formula': formula, 'rankings': rankings}


# -------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='SBFL Fault Localization')
    p.add_argument('--source', default='/app/pipeweave')
    p.add_argument('--test-file', default='/app/test_suite.py')
    p.add_argument('--formula', default='ochiai')
    p.add_argument('--coverage-out', default='/app/coverage_matrix.json')
    p.add_argument('--results-out', default='/app/fl_results.json')
    p.add_argument('--clusters-out', default='/app/fault_clusters.json')
    p.add_argument('--threshold', type=float, default=0.6)
    args = p.parse_args()

    print("Collecting per-test coverage...")
    matrix = collect_coverage(args.source, args.test_file)
    with open(args.coverage_out, 'w') as f:
        json.dump(matrix, f, indent=2)

    n_pass = sum(1 for t in matrix['tests'].values() if t['passed'])
    n_fail = sum(1 for t in matrix['tests'].values() if not t['passed'])
    print(f"\n{n_pass} passed, {n_fail} failed\n")

    print(f"Computing {args.formula} suspiciousness...")
    results = localize_faults(matrix, args.formula)
    with open(args.results_out, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nClustering faults (Jaccard threshold={args.threshold})...")
    clusters = cluster_faults(matrix, results, threshold=args.threshold)
    with open(args.clusters_out, 'w') as f:
        json.dump(clusters, f, indent=2)

    print(f"Found {clusters['num_clusters']} root-cause clusters\n")

    print(f"Top-5 suspicious lines per file:")
    for fpath, entries in results['rankings'].items():
        print(f"\n  {fpath}:")
        for e in entries[:5]:
            s = f"{e['score']:.4f}" if e['score'] != float('inf') else "inf"
            print(f"    L{e['line']:4d}  score={s}  "
                  f"(ef={e['ef']}, ep={e['ep']}, "
                  f"nf={e['nf']}, np={e['np']})")

    print(f"\nCoverage matrix: {args.coverage_out}")
    print(f"Results:         {args.results_out}")
    print(f"Clusters:        {args.clusters_out}")
