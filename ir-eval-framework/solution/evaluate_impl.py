#!/usr/bin/env python3
"""Comprehensive IR evaluation framework for MS MARCO-style passage ranking.

Computes MRR@10, NDCG@10, MAP@50, Recall@50 for multiple system run files,
with robust input handling, summary statistics, and pairwise significance tests.
"""

import argparse
import json
import math
import os
import statistics
import sys
from collections import defaultdict

from scipy.stats import ttest_rel


def load_qrels(path):
    """Load TREC-format qrels: qid<tab>0<tab>pid<tab>1."""
    qrels = defaultdict(set)
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 3:
                try:
                    qid = int(parts[0])
                    pid = int(parts[2])
                    qrels[qid].add(pid)
                except ValueError:
                    continue
    return dict(qrels)


def load_run(path):
    """Load MS MARCO run file with robust error handling.

    Returns (qid_to_ranking, warnings) where qid_to_ranking maps each query
    to an ordered list of passage IDs (sorted by ascending rank).
    """
    qid_to_entries = defaultdict(list)
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
                qid_to_entries[qid].append((rank, pid))
            except (ValueError, IndexError):
                n_skipped += 1

    # Deduplicate: keep entry with lowest rank for each (qid, pid)
    qid_to_ranking = {}
    for qid, entries in qid_to_entries.items():
        pid_best = {}
        for rank, pid in entries:
            if pid in pid_best:
                dup_count += 1
                if rank < pid_best[pid]:
                    pid_best[pid] = rank
            else:
                pid_best[pid] = rank
        sorted_pids = [pid for pid, _ in sorted(pid_best.items(), key=lambda x: x[1])]
        qid_to_ranking[qid] = sorted_pids

    if n_skipped > 0:
        warnings.append(f"Skipped {n_skipped} malformed lines")
    if dup_count > 0:
        warnings.append(f"Found {dup_count} duplicate passage IDs (kept lowest rank)")

    return qid_to_ranking, warnings


# ---------- Metric functions ----------

def mrr_at_k(ranking, relevant, k=10):
    """Mean Reciprocal Rank contribution for a single query."""
    for i, pid in enumerate(ranking[:k]):
        if pid in relevant:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(ranking, relevant, k=10):
    """NDCG@K with binary relevance and log2(rank+1) discount."""
    dcg = sum(1.0 / math.log2(i + 2) for i, p in enumerate(ranking[:k]) if p in relevant)
    n_rel = len(relevant)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(n_rel, k)))
    return dcg / idcg if idcg > 0 else 0.0


def ap_at_k(ranking, relevant, k=50):
    """Average Precision at K (denominator = total relevant docs)."""
    total_rel = len(relevant)
    if total_rel == 0:
        return 0.0
    found = 0
    score = 0.0
    for i, pid in enumerate(ranking[:k]):
        if pid in relevant:
            found += 1
            score += found / (i + 1)
    return score / total_rel


def recall_at_k(ranking, relevant, k=50):
    """Recall at K."""
    total_rel = len(relevant)
    if total_rel == 0:
        return 0.0
    return sum(1 for p in ranking[:k] if p in relevant) / total_rel


# ---------- Main evaluation ----------

def evaluate_system(qid_to_ranking, qrels):
    """Compute all metrics for one system on the shared query set."""
    common_qids = sorted(set(qrels.keys()) & set(qid_to_ranking.keys()))
    if not common_qids:
        return None

    mrrs, ndcgs, aps, recalls = [], [], [], []
    for qid in common_qids:
        r = qid_to_ranking[qid]
        rel = qrels[qid]
        mrrs.append(mrr_at_k(r, rel, 10))
        ndcgs.append(ndcg_at_k(r, rel, 10))
        aps.append(ap_at_k(r, rel, 50))
        recalls.append(recall_at_k(r, rel, 50))

    n = len(common_qids)
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
        '_per_query_mrr': dict(zip(common_qids, mrrs)),
    }


def main():
    parser = argparse.ArgumentParser(description='IR Evaluation Framework')
    parser.add_argument('--qrels', required=True, help='Path to qrels file')
    parser.add_argument('--runs', required=True, help='Path to runs directory')
    parser.add_argument('--output', required=True, help='Output JSON path')
    args = parser.parse_args()

    qrels = load_qrels(args.qrels)

    # Evaluate each system
    system_results = {}
    system_per_query = {}

    for fname in sorted(os.listdir(args.runs)):
        if not fname.endswith('.tsv'):
            continue
        sys_name = fname[:-4]
        qid_to_ranking, warnings = load_run(os.path.join(args.runs, fname))
        metrics = evaluate_system(qid_to_ranking, qrels)
        if metrics is None:
            continue

        per_query = metrics.pop('_per_query_mrr')
        metrics['warnings'] = warnings
        system_results[sys_name] = metrics
        system_per_query[sys_name] = per_query

    # Leaderboard sorted by MRR@10 descending
    leaderboard = sorted(
        system_results.keys(),
        key=lambda s: system_results[s]['mrr@10'],
        reverse=True
    )

    # Pairwise paired t-tests on per-query MRR@10
    pairwise = {}
    systems_sorted = sorted(system_results.keys())
    for i in range(len(systems_sorted)):
        for j in range(i + 1, len(systems_sorted)):
            sa, sb = systems_sorted[i], systems_sorted[j]
            shared = sorted(
                set(system_per_query[sa].keys()) & set(system_per_query[sb].keys())
            )
            a_scores = [system_per_query[sa][q] for q in shared]
            b_scores = [system_per_query[sb][q] for q in shared]
            t_stat, p_val = ttest_rel(a_scores, b_scores)
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
    print(f"Leaderboard: {leaderboard}")
    print(f"Results written to {args.output}")


if __name__ == '__main__':
    main()
