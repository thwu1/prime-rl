#!/usr/bin/env python3
"""Solution: TREC evaluation campaign audit.

Builds trec_eval from source, evaluates all submissions, detects data quality
issues, pool exploitation, plagiarism, and produces a comprehensive audit.
"""

import json
import math
import os
import subprocess
from collections import defaultdict

CAMPAIGN = '/app/campaign'
TREC_EVAL_DIR = '/app/trec_eval'
TREC_EVAL_BIN = f'{TREC_EVAL_DIR}/trec_eval'
QRELS_PATH = f'{CAMPAIGN}/qrels'
OUTPUT = '/app/output/audit.json'


def build_trec_eval():
    """Compile trec_eval from source."""
    subprocess.run(['make', '-C', TREC_EVAL_DIR, '-s'],
                   capture_output=True, check=True)


def run_trec_eval(run_path, metrics=None):
    """Run trec_eval and parse output."""
    if metrics is None:
        metrics = ['map', 'ndcg_cut.10', 'P.5']
    cmd = [TREC_EVAL_BIN]
    for m in metrics:
        cmd.extend(['-m', m])
    cmd.extend([QRELS_PATH, run_path])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    parsed = {}
    for line in result.stdout.strip().split('\n'):
        parts = line.split()
        if len(parts) == 3 and parts[1] == 'all':
            parsed[parts[0]] = float(parts[2])
    return parsed


def load_qrels():
    qrels = defaultdict(dict)
    with open(QRELS_PATH) as fh:
        for line in fh:
            parts = line.strip().split()
            if len(parts) >= 4:
                qrels[parts[0]][parts[2]] = int(parts[3])
    return dict(qrels)


def load_run_clean(path):
    """Parse a clean TREC run file."""
    run = defaultdict(list)
    with open(path) as fh:
        for line in fh:
            parts = line.strip().split()
            if len(parts) >= 6:
                try:
                    score = float(parts[4])
                    if math.isfinite(score):
                        run[parts[0]].append((parts[2], score))
                except ValueError:
                    pass
    for qid in run:
        run[qid].sort(key=lambda x: (-x[1], x[0]))
    return dict(run)


def check_integrity(path, valid_qids):
    """Check a run file for integrity issues."""
    issues = defaultdict(int)
    seen = defaultdict(set)

    with open(path) as fh:
        for line in fh:
            parts = line.strip().split()

            if len(parts) < 6:
                issues['missing_fields'] += 1
                continue

            qid = parts[0]
            doc_id = parts[2]
            score_str = parts[4]

            if qid not in valid_qids:
                issues['phantom_queries'] += 1
                continue

            try:
                score = float(score_str)
                if not math.isfinite(score):
                    issues['invalid_scores'] += 1
                    continue
            except (ValueError, OverflowError):
                issues['invalid_scores'] += 1
                continue

            if doc_id in seen[qid]:
                issues['duplicate_docs'] += 1
                continue
            seen[qid].add(doc_id)

    return dict(issues)


def compute_judged_rate(run, qrels):
    total = 0
    judged = 0
    for qid, docs in run.items():
        for doc_id, _ in docs:
            total += 1
            if qid in qrels and doc_id in qrels[qid]:
                judged += 1
    return judged / total if total else 0.0


def compute_top50_overlap(run_a, run_b, qrels):
    overlaps = []
    for qid in sorted(qrels):
        docs_a = set(d for d, _ in run_a.get(qid, [])[:50])
        docs_b = set(d for d, _ in run_b.get(qid, [])[:50])
        if docs_a and docs_b:
            overlaps.append(len(docs_a & docs_b) / 50.0)
    return sum(overlaps) / len(overlaps) if overlaps else 0.0


def main():
    os.makedirs('/app/output', exist_ok=True)

    # Step 1: Build trec_eval
    build_trec_eval()

    # Step 2: Load data
    qrels = load_qrels()
    valid_qids = set(qrels.keys())

    # Find all run files
    run_files = sorted([
        f for f in os.listdir(CAMPAIGN)
        if f.startswith('sys_') and f.endswith('.txt')
    ])
    run_ids = [f.replace('.txt', '') for f in run_files]

    # Step 3: Check integrity of each run
    disqualified = {}
    clean_runs = []
    for run_id, run_file in zip(run_ids, run_files):
        path = f'{CAMPAIGN}/{run_file}'
        issues = check_integrity(path, valid_qids)
        if issues:
            total = sum(issues.values())
            types = ', '.join(issues.keys())
            disqualified[run_id] = (
                f'data quality: {total} errors across {types}'
            )
        else:
            clean_runs.append(run_id)

    # Step 4: Load clean runs and compute judged rates to detect pool bias
    runs_data = {}
    judged_rates = {}
    for run_id in clean_runs:
        path = f'{CAMPAIGN}/{run_id}.txt'
        runs_data[run_id] = load_run_clean(path)
        judged_rates[run_id] = compute_judged_rate(runs_data[run_id], qrels)

    # Identify pool exploiter (anomalously high judged rate)
    pool_exploiter = max(judged_rates, key=judged_rates.get)
    pool_exploiter_rate = judged_rates[pool_exploiter]
    other_rates = [r for rid, r in judged_rates.items() if rid != pool_exploiter]
    if pool_exploiter_rate > max(other_rates) + 0.05:
        disqualified[pool_exploiter] = (
            f'evaluation bias: judged-document rate {pool_exploiter_rate:.4f} '
            f'anomalously exceeds other submissions'
        )
        clean_runs.remove(pool_exploiter)

    # Step 5: Detect submission copying via pairwise overlap analysis
    best_overlap = -1
    copy_pair = (None, None)
    for i, r1 in enumerate(clean_runs):
        for r2 in clean_runs[i + 1:]:
            overlap = compute_top50_overlap(
                runs_data[r1], runs_data[r2], qrels)
            if overlap > best_overlap:
                best_overlap = overlap
                copy_pair = (r1, r2)

    if best_overlap > 0.70:
        # Determine which is the copy (lower MAP)
        map_a = run_trec_eval(
            f'{CAMPAIGN}/{copy_pair[0]}.txt', ['map']).get('map', 0)
        map_b = run_trec_eval(
            f'{CAMPAIGN}/{copy_pair[1]}.txt', ['map']).get('map', 0)
        if map_a >= map_b:
            suspect = copy_pair[1]
        else:
            suspect = copy_pair[0]
        disqualified[suspect] = (
            f'submission copying: {best_overlap:.4f} mean document overlap '
            f'with another submission'
        )
        if suspect in clean_runs:
            clean_runs.remove(suspect)

    # Step 6: Determine valid runs and compute metrics
    valid_runs = sorted(clean_runs)

    metrics = {}
    for run_id in valid_runs:
        path = f'{CAMPAIGN}/{run_id}.txt'
        te_output = run_trec_eval(path)
        metrics[run_id] = {
            'map': round(te_output.get('map', 0), 6),
            'ndcg_cut_10': round(te_output.get('ndcg_cut_10', 0), 6),
            'P_5': round(te_output.get('P_5', 0), 6),
        }

    # Step 7: Ranking by MAP
    ranking = sorted(valid_runs, key=lambda r: -metrics[r]['map'])

    # Write output
    audit = {
        'disqualified': disqualified,
        'valid_runs': valid_runs,
        'metrics': metrics,
        'ranking': ranking,
    }

    with open(OUTPUT, 'w') as fh:
        json.dump(audit, fh, indent=2)

    print(f'Audit complete. Output written to {OUTPUT}')


if __name__ == '__main__':
    main()
