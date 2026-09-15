#!/usr/bin/env python3

"""Fix bugs in metrics.py and implement missing functions in metrics.py and fusion.py."""

METRICS_PY = "/app/eval/metrics.py"
FUSION_PY = "/app/eval/fusion.py"


def fix_metrics():
    """Rewrite metrics.py with corrected MRR, nDCG, and implemented MAP, Recall."""
    content = '''\
"""IR evaluation metrics module.

Provides standard information retrieval metrics for passage ranking evaluation.
All metrics operate on:
- qrels: dict mapping qid (int) -> {pid (int): relevance_grade (int)}
- run: dict mapping qid (int) -> [pid1, pid2, ...] (list of ints ordered by rank)

Relevance grades: 0 = not relevant, 1 = marginally relevant,
2 = relevant, 3 = highly relevant.
"""

import math
from collections import defaultdict


def load_qrels(path):
    """Load TREC-format qrels file."""
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\\t')
            qid = int(parts[0])
            pid = int(parts[2])
            grade = int(parts[3])
            if qid not in qrels:
                qrels[qid] = {}
            qrels[qid][pid] = grade
    return qrels


def load_run(path):
    """Load a ranking run file."""
    entries = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\\t')
            qid = int(parts[0])
            pid = int(parts[1])
            rank = int(parts[2])
            entries.append((qid, pid, rank))
    entries.sort(key=lambda x: (x[0], x[2]))
    run = defaultdict(list)
    for qid, pid, rank in entries:
        run[qid].append(pid)
    return dict(run)


def compute_mrr_at_k(qrels, run, k):
    """Compute Mean Reciprocal Rank at k.

    FIX: Check ALL relevant passage IDs, not just the first one.
    The original code only checked qrels[qid].keys()[0] with ==.
    Must use `in` with the full set of relevant PIDs.
    """
    rr_sum = 0.0
    n_queries = len(qrels)
    for qid in qrels:
        if qid not in run:
            continue
        ranked_pids = run[qid]
        rel_pids = set(qrels[qid].keys())
        for i in range(min(k, len(ranked_pids))):
            if ranked_pids[i] in rel_pids:
                rr_sum += 1.0 / (i + 1)
                break
    return rr_sum / n_queries


def compute_ndcg_at_k(qrels, run, k):
    """Compute Normalized Discounted Cumulative Gain at k.

    FIX 1: Use math.log2 instead of math.log (natural log).
    FIX 2: Sort ideal relevance grades in descending order (reverse=True).
    """
    ndcg_sum = 0.0
    n_queries = len(qrels)
    for qid in qrels:
        if qid not in run:
            continue
        ranked_pids = run[qid]

        dcg = 0.0
        for i in range(min(k, len(ranked_pids))):
            pid = ranked_pids[i]
            rel = qrels[qid].get(pid, 0)
            dcg += (2 ** rel - 1) / math.log2(i + 2)

        ideal_rels = sorted(qrels[qid].values(), reverse=True)
        idcg = 0.0
        for i in range(min(k, len(ideal_rels))):
            idcg += (2 ** ideal_rels[i] - 1) / math.log2(i + 2)

        if idcg > 0:
            ndcg_sum += dcg / idcg

    return ndcg_sum / n_queries


def compute_map_at_k(qrels, run, k):
    """Compute Mean Average Precision at k.

    AP@k = (1/R) * sum_{i=1}^{k} P(i) * rel(i)
    where R = total relevant docs, P(i) = precision at position i,
    rel(i) = 1 if doc at position i is relevant.
    """
    ap_sum = 0.0
    n_queries = len(qrels)
    for qid in qrels:
        if qid not in run:
            continue
        ranked_pids = run[qid]
        rel_pids = set(qrels[qid].keys())

        num_rel_found = 0
        precision_sum = 0.0
        for i in range(min(k, len(ranked_pids))):
            if ranked_pids[i] in rel_pids:
                num_rel_found += 1
                precision_sum += num_rel_found / (i + 1)

        total_rel = len(rel_pids)
        if total_rel > 0:
            ap_sum += precision_sum / total_rel

    return ap_sum / n_queries


def compute_recall_at_k(qrels, run, k):
    """Compute Recall at k, averaged across queries."""
    recall_sum = 0.0
    n_queries = len(qrels)
    for qid in qrels:
        if qid not in run:
            continue
        ranked_pids = run[qid][:k]
        rel_pids = set(qrels[qid].keys())

        found = len(set(ranked_pids) & rel_pids)
        recall_sum += found / len(rel_pids)

    return recall_sum / n_queries
'''
    with open(METRICS_PY, 'w') as f:
        f.write(content)
    print("Fixed metrics.py")


def implement_fusion():
    """Write complete fusion.py with RRF and CombSUM."""
    content = '''\
"""Rank fusion methods for combining multiple retrieval runs."""

from collections import defaultdict


def rrf_fusion(runs, k_param=60):
    """Reciprocal Rank Fusion (Cormack et al., 2009).

    score(d) = sum_{r in runs} 1 / (k_param + rank_r(d))
    """
    scores = defaultdict(lambda: defaultdict(float))
    for run in runs.values():
        for qid, pids in run.items():
            for rank, pid in enumerate(pids, 1):
                scores[qid][pid] += 1.0 / (k_param + rank)

    fused = {}
    for qid in scores:
        sorted_pids = sorted(scores[qid].items(), key=lambda x: (-x[1], x[0]))
        fused[qid] = [pid for pid, _ in sorted_pids]
    return fused


def combsum_fusion(runs):
    """CombSUM fusion using min-max normalized rank-based scores.

    score = 1 - (rank - 1) / max_rank, summed across runs.
    """
    scores = defaultdict(lambda: defaultdict(float))
    for run in runs.values():
        for qid, pids in run.items():
            max_rank = len(pids)
            for rank, pid in enumerate(pids, 1):
                scores[qid][pid] += 1.0 - (rank - 1) / max_rank

    fused = {}
    for qid in scores:
        sorted_pids = sorted(scores[qid].items(), key=lambda x: (-x[1], x[0]))
        fused[qid] = [pid for pid, _ in sorted_pids]
    return fused
'''
    with open(FUSION_PY, 'w') as f:
        f.write(content)
    print("Implemented fusion.py")


if __name__ == '__main__':
    fix_metrics()
    implement_fusion()
