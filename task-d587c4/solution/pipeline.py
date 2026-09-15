#!/usr/bin/env python3
"""Cross-tool evaluation pipeline for passage ranking audit.

Runs both the fixed custom eval script and compiled trec_eval on all system
runs, populates SQLite with per-query scores, cross-validates results, and
produces the audit report JSON.
"""

import json
import bz2
import os
import random
import sqlite3
import subprocess
import tempfile
from itertools import combinations


def load_qrels(path):
    """Load qrels: qid\\t0\\tpid\\trel (any rel > 0 is relevant)."""
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 4:
                continue
            qid = int(parts[0])
            pid = int(parts[2])
            rel = int(parts[3])
            if rel > 0:
                if qid not in qrels:
                    qrels[qid] = []
                qrels[qid].append(pid)
    return qrels


def load_run_msmarco(path, compressed=False):
    """Load MS MARCO format: qid\\tpid\\trank (optionally bz2)."""
    opener = bz2.open if compressed else open
    mode = 'rt' if compressed else 'r'
    run = {}
    with opener(path, mode) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 3:
                continue
            qid = int(parts[0])
            pid = int(parts[1])
            rank = int(parts[2])
            if qid not in run:
                run[qid] = {}
            if pid not in run[qid] or rank < run[qid][pid]:
                run[qid][pid] = rank
    result = {}
    for qid in run:
        ranked = sorted(run[qid].items(), key=lambda x: x[1])
        result[qid] = [pid for pid, _ in ranked]
    return result


def load_run_trec(path):
    """Load TREC format: qid Q0 pid rank score runid."""
    run = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 4:
                parts = line.strip().split('\t')
            if len(parts) < 4:
                continue
            qid = int(parts[0])
            pid = int(parts[2])
            rank = int(parts[3])
            if qid not in run:
                run[qid] = {}
            if pid not in run[qid] or rank < run[qid][pid]:
                run[qid][pid] = rank
    result = {}
    for qid in run:
        ranked = sorted(run[qid].items(), key=lambda x: x[1])
        result[qid] = [pid for pid, _ in ranked]
    return result


def per_query_mrr(qrels, run, max_rank=10):
    """Compute per-query MRR@K scores."""
    scores = {}
    for qid in qrels:
        if qid in run:
            relevant = set(qrels[qid])
            score = 0.0
            for i, pid in enumerate(run[qid][:max_rank]):
                if pid in relevant:
                    score = 1.0 / (i + 1)
                    break
            scores[qid] = score
        else:
            scores[qid] = 0.0
    return scores


def mean_mrr(pq_scores):
    if not pq_scores:
        return 0.0
    return sum(pq_scores.values()) / len(pq_scores)


def msmarco_to_trec(msmarco_path, trec_path, run_name, compressed=False):
    """Convert MS MARCO format to TREC format for trec_eval ingestion."""
    opener = bz2.open if compressed else open
    mode = 'rt' if compressed else 'r'
    seen = {}
    with opener(msmarco_path, mode) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 3:
                continue
            qid = int(parts[0])
            pid = int(parts[1])
            rank = int(parts[2])
            key = (qid, pid)
            if key not in seen or rank < seen[key]:
                seen[key] = rank

    entries = sorted(seen.items(), key=lambda x: (x[0][0], x[1]))
    with open(trec_path, 'w') as f:
        for (qid, pid), rank in entries:
            score = 1000.0 / rank
            f.write("{} Q0 {} {} {:.4f} {}\n".format(qid, pid, rank, score, run_name))


def run_trec_eval(qrels_path, run_path, cutoff=10):
    """Run trec_eval and return per-query scores and overall MRR."""
    result = subprocess.run(
        ['/app/trec_eval_src/trec_eval', '-q', '-m',
         'recip_rank.{}'.format(cutoff), qrels_path, run_path],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError("trec_eval failed: " + result.stderr)

    per_query = {}
    overall = None
    for line in result.stdout.strip().split('\n'):
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        topic = parts[1].strip()
        value = float(parts[2].strip())
        if topic == 'all':
            overall = value
        else:
            per_query[int(topic)] = value

    return per_query, overall


def bootstrap_ci(pq_scores, n_iter, seed, confidence=0.95):
    """Compute bootstrap confidence interval for MRR."""
    rng = random.Random(seed)
    qids = sorted(pq_scores.keys())
    scores = [pq_scores[qid] for qid in qids]
    n = len(scores)
    means = []
    for _ in range(n_iter):
        sample = [scores[rng.randint(0, n - 1)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    alpha = 1 - confidence
    lower = means[int(n_iter * (alpha / 2))]
    upper = means[int(n_iter * (1 - alpha / 2))]
    return lower, upper


def paired_bootstrap_test(scores_a, scores_b, n_iter, seed):
    """Paired bootstrap resampling significance test (two-sided)."""
    rng = random.Random(seed)
    qids = sorted(set(scores_a.keys()) & set(scores_b.keys()))
    n = len(qids)
    deltas = [scores_a[qid] - scores_b[qid] for qid in qids]
    observed = sum(deltas) / n
    count = 0
    for _ in range(n_iter):
        sample = [deltas[rng.randint(0, n - 1)] for _ in range(n)]
        boot_mean = sum(sample) / n
        if observed >= 0 and boot_mean <= 0:
            count += 1
        elif observed < 0 and boot_mean >= 0:
            count += 1
    p = min(2.0 * count / n_iter, 1.0)
    return p, observed


def main():
    with open('/app/config.json') as f:
        config = json.load(f)

    n_iter = config['bootstrap']['n_iterations']
    boot_seed = config['bootstrap']['seed']
    qrels_path = config['qrels_path']
    threshold = config.get('disagreement_threshold', 1e-6)

    qrels = load_qrels(qrels_path)

    # Convert MS MARCO runs to TREC format for trec_eval
    os.makedirs('/tmp/trec_runs', exist_ok=True)
    trec_run_paths = {}
    for name, info in config['runs'].items():
        path = info['path']
        fmt = info['format']
        if fmt == 'trec':
            trec_run_paths[name] = path
        elif fmt == 'msmarco_bz2':
            trec_path = '/tmp/trec_runs/{}.trec'.format(name)
            msmarco_to_trec(path, trec_path, name.upper(), compressed=True)
            trec_run_paths[name] = trec_path
        else:
            trec_path = '/tmp/trec_runs/{}.trec'.format(name)
            msmarco_to_trec(path, trec_path, name.upper(), compressed=False)
            trec_run_paths[name] = trec_path

    db = sqlite3.connect('/app/results.db')

    systems = {}
    custom_pq = {}
    cross_tool = []

    for name, info in config['runs'].items():
        path = info['path']
        fmt = info['format']

        # Load run using appropriate format handler
        if fmt == 'trec':
            run = load_run_trec(path)
        elif fmt == 'msmarco_bz2':
            run = load_run_msmarco(path, compressed=True)
        else:
            run = load_run_msmarco(path, compressed=False)

        # Custom eval: compute per-query MRR using Python
        pq = per_query_mrr(qrels, run)
        custom_pq[name] = pq
        custom_mrr = mean_mrr(pq)

        # trec_eval: run compiled binary
        te_pq, te_mrr = run_trec_eval(qrels_path, trec_run_paths[name])

        # Store per-query scores in SQLite
        for qid, score in pq.items():
            db.execute(
                "INSERT OR REPLACE INTO per_query_scores VALUES (?, ?, ?, ?, ?)",
                (name, qid, 'custom', 'recip_rank', score)
            )
        for qid, score in te_pq.items():
            db.execute(
                "INSERT OR REPLACE INTO per_query_scores VALUES (?, ?, ?, ?, ?)",
                (name, qid, 'trec_eval', 'recip_rank', score)
            )

        # Store summary
        db.execute(
            "INSERT OR REPLACE INTO summary VALUES (?, ?, ?, ?, ?)",
            (name, 'custom', 'recip_rank', custom_mrr, len(pq))
        )
        db.execute(
            "INSERT OR REPLACE INTO summary VALUES (?, ?, ?, ?, ?)",
            (name, 'trec_eval', 'recip_rank', te_mrr, len(te_pq))
        )

        # Cross-tool comparison
        match = abs(custom_mrr - te_mrr) < threshold
        cross_tool.append({
            'system': name,
            'custom_mrr': round(custom_mrr, 6),
            'trec_eval_mrr': round(te_mrr, 6),
            'match': match,
        })

        # Identify per-query disagreements
        common_qids = set(pq.keys()) & set(te_pq.keys())
        for qid in common_qids:
            delta = abs(pq[qid] - te_pq[qid])
            if delta > threshold:
                db.execute(
                    "INSERT INTO disagreements VALUES (?, ?, ?, ?, ?, ?)",
                    (name, qid, pq[qid], te_pq[qid], delta, 'resolved')
                )

        # Bootstrap CI
        ci_lo, ci_hi = bootstrap_ci(pq, n_iter, boot_seed)

        systems[name] = {
            'name': name,
            'mrr_at_10': round(custom_mrr, 6),
            'queries_ranked': len(run),
            'ci_95_lower': round(ci_lo, 6),
            'ci_95_upper': round(ci_hi, 6),
        }

    db.commit()

    # Sort systems by MRR descending
    sorted_systems = sorted(systems.values(),
                            key=lambda x: x['mrr_at_10'], reverse=True)

    # Pairwise significance
    pairs = []
    names = sorted(systems.keys())
    for a, b in combinations(names, 2):
        p, delta = paired_bootstrap_test(custom_pq[a], custom_pq[b],
                                          n_iter, boot_seed)
        pairs.append({
            'system_a': a,
            'system_b': b,
            'delta_mrr': round(delta, 6),
            'p_value': round(p, 4),
            'significant_at_005': p < 0.05,
        })

    # Produce audit report
    report = {
        'systems': sorted_systems,
        'pairwise_significance': pairs,
        'cross_tool_validation': cross_tool,
    }

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    db.close()

    print("Audit report written to /app/output/audit_report.json")
    for s in sorted_systems:
        print("  {}: MRR@10={:.4f} [{:.4f}, {:.4f}]".format(
            s['name'], s['mrr_at_10'], s['ci_95_lower'], s['ci_95_upper']))
    print("\nCross-tool validation:")
    for ct in cross_tool:
        print("  {}: custom={:.6f} trec_eval={:.6f} match={}".format(
            ct['system'], ct['custom_mrr'], ct['trec_eval_mrr'], ct['match']))


if __name__ == '__main__':
    main()
