#!/usr/bin/env python3
"""IR Evaluation Pipeline for MS MARCO Passage Ranking.

Evaluates multiple retrieval systems computing MRR@10, NDCG@10, MAP@50,
Recall@50, per-query statistics, and pairwise significance testing.
"""

import argparse
import json
import math
import os
import statistics
from collections import defaultdict

from scipy.stats import ttest_ind


def load_qrels(path):
    """Load relevance judgments in TREC format (qid iter pid rel)."""
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 4:
                continue
            try:
                qid = int(parts[0])
                pid = int(parts[2])
                rel = int(parts[3])
                if rel > 0:
                    qrels[qid] = {pid}
            except ValueError:
                continue
    return qrels


def load_run(path):
    """Load run file with error handling."""
    entries = defaultdict(list)
    warnings = []
    n_skipped = 0
    dup_count = 0

    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 3:
                n_skipped += 1
                continue
            try:
                qid = int(parts[0])
                pid = int(parts[1])
                rank = int(parts[2])
                if rank < 1:
                    n_skipped += 1
                    continue
                entries[qid].append((rank, pid))
            except (ValueError, IndexError):
                n_skipped += 1

    rankings = {}
    for qid, elist in entries.items():
        best = {}
        for rank, pid in elist:
            if pid in best:
                dup_count += 1
                if rank > best[pid]:
                    best[pid] = rank
            else:
                best[pid] = rank
        rankings[qid] = [p for p, _ in sorted(best.items(), key=lambda x: x[1])]

    if n_skipped > 0:
        warnings.append(f"Skipped {n_skipped} malformed lines")
    if dup_count > 0:
        warnings.append(f"Found {dup_count} duplicate passage IDs (resolved)")

    return rankings, warnings


def mrr_at_k(ranking, relevant, k=10):
    """Reciprocal rank of first relevant document within top-k."""
    for i, pid in enumerate(ranking[:k]):
        if pid in relevant:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(ranking, relevant, k=10):
    """Normalized Discounted Cumulative Gain at k with binary relevance."""
    dcg = sum(1.0 / math.log(i + 2) for i, p in enumerate(ranking[:k]) if p in relevant)
    n_rel = len(relevant)
    idcg = sum(1.0 / math.log(i + 2) for i in range(min(n_rel, k)))
    return dcg / idcg if idcg > 0 else 0.0


def ap_at_k(ranking, relevant, k=50):
    """Average Precision at k."""
    total_rel = len(relevant)
    if total_rel == 0:
        return 0.0
    denom = min(total_rel, k)
    found = 0
    score = 0.0
    for i, pid in enumerate(ranking[:k]):
        if pid in relevant:
            found += 1
            score += found / (i + 1)
    return score / denom


def recall_at_k(ranking, relevant, k=50):
    """Recall at k."""
    total_rel = len(relevant)
    if total_rel == 0:
        return 0.0
    return sum(1 for p in ranking[:k] if p in relevant) / total_rel


def evaluate_system(rankings, qrels):
    """Compute all metrics for one system on the shared query set."""
    common = sorted(set(qrels) & set(rankings))
    if not common:
        return None
    mrrs, ndcgs, aps, recalls = [], [], [], []
    for qid in common:
        r = rankings[qid]
        rel = qrels[qid]
        mrrs.append(mrr_at_k(r, rel, 10))
        ndcgs.append(ndcg_at_k(r, rel, 10))
        aps.append(ap_at_k(r, rel, 50))
        recalls.append(recall_at_k(r, rel, 50))
    n = len(common)
    mrr_mean = sum(mrrs) / n
    return {
        'mrr@10': mrr_mean,
        'ndcg@10': sum(ndcgs) / n,
        'map@50': sum(aps) / n,
        'recall@50': sum(recalls) / n,
        'num_queries_evaluated': n,
        'mrr_stats': {
            'mean': mrr_mean,
            'median': statistics.median(mrrs),
            'std_dev': statistics.pstdev(mrrs),
        },
        '_per_query_mrr': dict(zip(common, mrrs)),
    }


def main():
    parser = argparse.ArgumentParser(description='IR Evaluation Pipeline')
    parser.add_argument('--qrels', required=True, help='Path to qrels file')
    parser.add_argument('--runs', required=True, help='Path to runs directory')
    parser.add_argument('--output', required=True, help='Output JSON path')
    args = parser.parse_args()

    qrels = load_qrels(args.qrels)

    system_results = {}
    system_pq = {}

    for fname in sorted(os.listdir(args.runs)):
        if not fname.endswith('.tsv'):
            continue
        name = fname[:-4]
        rankings, warnings = load_run(os.path.join(args.runs, fname))
        metrics = evaluate_system(rankings, qrels)
        if metrics is None:
            continue
        pq = metrics.pop('_per_query_mrr')
        metrics['warnings'] = warnings
        system_results[name] = metrics
        system_pq[name] = pq

    leaderboard = sorted(
        system_results.keys(),
        key=lambda s: system_results[s]['mrr@10'],
        reverse=True
    )

    pairwise = {}
    systems = sorted(system_results.keys())
    for i in range(len(systems)):
        for j in range(i + 1, len(systems)):
            sa, sb = systems[i], systems[j]
            shared = sorted(set(system_pq[sa]) & set(system_pq[sb]))
            a_vals = [system_pq[sa][q] for q in shared]
            b_vals = [system_pq[sb][q] for q in shared]
            t_stat, p_val = ttest_ind(a_vals, b_vals)
            pairwise[f"{sa}::{sb}"] = {
                't_statistic': float(t_stat),
                'p_value': float(p_val),
                'significant_at_005': bool(p_val < 0.05),
            }

    output = {
        'systems': system_results,
        'leaderboard': leaderboard,
        'pairwise_tests': pairwise,
    }

    with open(args.output, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Evaluation complete. {len(system_results)} systems evaluated.")


if __name__ == '__main__':
    main()
