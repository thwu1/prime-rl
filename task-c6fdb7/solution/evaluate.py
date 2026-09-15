#!/usr/bin/env python3
"""Search rank fusion evaluation pipeline — reference implementation."""

import json
import math
import os


def parse_run_file(filepath):
    """Parse TREC run file into {qid: [(doc_id, score), ...]} sorted by score desc."""
    runs = {}
    with open(filepath) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 6:
                continue
            qid, _, doc_id, rank, score, _ = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
            runs.setdefault(qid, []).append((doc_id, float(score)))
    for qid in runs:
        runs[qid].sort(key=lambda x: -x[1])
    return runs


def ndcg_at_k(ranked_docs, qrels, k=10):
    """Normalized Discounted Cumulative Gain at k."""
    dcg = 0.0
    for i, doc_id in enumerate(ranked_docs[:k]):
        rel = qrels.get(doc_id, 0)
        gain = (2 ** rel) - 1
        discount = math.log2(i + 2)  # rank 1 -> log2(2)
        dcg += gain / discount

    ideal_rels = sorted(qrels.values(), reverse=True)[:k]
    idcg = 0.0
    for i, rel in enumerate(ideal_rels):
        gain = (2 ** rel) - 1
        discount = math.log2(i + 2)
        idcg += gain / discount

    return dcg / idcg if idcg > 0 else 0.0


def ap_at_k(ranked_docs, qrels, k=10):
    """Average Precision at k for a single query."""
    num_rel_found = 0
    sum_precision = 0.0
    for i, doc_id in enumerate(ranked_docs[:k]):
        rel = qrels.get(doc_id, 0)
        if rel > 0:
            num_rel_found += 1
            sum_precision += num_rel_found / (i + 1)
    total_relevant = sum(1 for r in qrels.values() if r > 0)
    if total_relevant == 0:
        return 0.0
    return sum_precision / min(total_relevant, k)


def mrr_score(ranked_docs, qrels):
    """Mean Reciprocal Rank — reciprocal of rank of first relevant doc."""
    for i, doc_id in enumerate(ranked_docs):
        if qrels.get(doc_id, 0) > 0:
            return 1.0 / (i + 1)
    return 0.0


def precision_at_k(ranked_docs, qrels, k=10):
    """Precision at k."""
    return sum(1 for d in ranked_docs[:k] if qrels.get(d, 0) > 0) / k


def eval_system(runs, queries):
    """Compute mean metrics over all queries for a set of runs."""
    metrics = {'ndcg@10': [], 'map@10': [], 'mrr': [], 'p@10': []}
    for q in queries:
        qid, qrels = q['id'], q['qrels']
        if qid not in runs:
            continue
        ranked = [d for d, s in runs[qid]]
        metrics['ndcg@10'].append(ndcg_at_k(ranked, qrels, 10))
        metrics['map@10'].append(ap_at_k(ranked, qrels, 10))
        metrics['mrr'].append(mrr_score(ranked, qrels))
        metrics['p@10'].append(precision_at_k(ranked, qrels, 10))
    n = len(metrics['ndcg@10'])
    return {k: sum(v) / n for k, v in metrics.items()}


def minmax_normalize(doc_scores):
    """Min-max normalize a list of (doc_id, score) pairs to [0, 1]."""
    if len(doc_scores) <= 1:
        return [(d, 1.0) for d, s in doc_scores]
    scores = [s for _, s in doc_scores]
    mn, mx = min(scores), max(scores)
    if mx == mn:
        return [(d, 1.0) for d, s in doc_scores]
    return [(d, (s - mn) / (mx - mn)) for d, s in doc_scores]


def rrf_fuse(system_runs_list, qids, k=60):
    """Reciprocal Rank Fusion."""
    fused = {}
    for qid in qids:
        scores = {}
        for sys_runs in system_runs_list:
            if qid not in sys_runs:
                continue
            for rank, (doc_id, _) in enumerate(sys_runs[qid], 1):
                scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank)
        fused[qid] = sorted(scores.items(), key=lambda x: -x[1])
    return fused


def combsum_fuse(system_runs_list, qids, weights):
    """CombSUM with per-system weights and min-max normalization."""
    fused = {}
    for qid in qids:
        scores = {}
        for idx, sys_runs in enumerate(system_runs_list):
            if qid not in sys_runs:
                continue
            normed = minmax_normalize(sys_runs[qid])
            w = weights[idx]
            for doc_id, nscore in normed:
                scores[doc_id] = scores.get(doc_id, 0) + w * nscore
        fused[qid] = sorted(scores.items(), key=lambda x: -x[1])
    return fused


def combmnz_fuse(system_runs_list, qids):
    """CombMNZ: sum of normalized scores * count of systems returning the doc."""
    fused = {}
    for qid in qids:
        scores = {}
        counts = {}
        for sys_runs in system_runs_list:
            if qid not in sys_runs:
                continue
            normed = minmax_normalize(sys_runs[qid])
            for doc_id, nscore in normed:
                scores[doc_id] = scores.get(doc_id, 0) + nscore
                counts[doc_id] = counts.get(doc_id, 0) + 1
        fused[qid] = sorted(
            [(d, scores[d] * counts[d]) for d in scores],
            key=lambda x: -x[1]
        )
    return fused


def main():
    # Load data
    with open('/app/data/queries.json') as f:
        queries = json.load(f)

    bm25 = parse_run_file('/app/data/runs/bm25.run')
    dense = parse_run_file('/app/data/runs/dense.run')
    sparse = parse_run_file('/app/data/runs/sparse.run')

    system_runs_list = [bm25, dense, sparse]
    qids = [q['id'] for q in queries]

    # Evaluate individual systems
    bm25_metrics = eval_system(bm25, queries)
    dense_metrics = eval_system(dense, queries)
    sparse_metrics = eval_system(sparse, queries)

    # RRF grid search
    rrf_k_values = [1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    best_rrf_k, best_rrf_ndcg, best_rrf_metrics = None, -1, None
    for k in rrf_k_values:
        fused = rrf_fuse(system_runs_list, qids, k)
        metrics = eval_system(fused, queries)
        if metrics['ndcg@10'] > best_rrf_ndcg:
            best_rrf_k = k
            best_rrf_ndcg = metrics['ndcg@10']
            best_rrf_metrics = metrics

    # CombSUM grid search
    weight_options = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    best_cs_weights, best_cs_ndcg, best_cs_metrics = None, -1, None
    for w1 in weight_options:
        for w2 in weight_options:
            for w3 in weight_options:
                if w1 + w2 + w3 == 0:
                    continue
                weights = [w1, w2, w3]
                fused = combsum_fuse(system_runs_list, qids, weights)
                metrics = eval_system(fused, queries)
                if metrics['ndcg@10'] > best_cs_ndcg:
                    best_cs_weights = weights
                    best_cs_ndcg = metrics['ndcg@10']
                    best_cs_metrics = metrics

    # CombMNZ
    fused = combmnz_fuse(system_runs_list, qids)
    combmnz_metrics = eval_system(fused, queries)

    # Find best overall
    all_methods = {
        'bm25': bm25_metrics, 'dense': dense_metrics, 'sparse': sparse_metrics,
        'rrf': best_rrf_metrics, 'combsum': best_cs_metrics, 'combmnz': combmnz_metrics
    }
    best_method = max(all_methods, key=lambda m: all_methods[m]['ndcg@10'])
    best_single = max(['bm25', 'dense', 'sparse'],
                      key=lambda m: all_methods[m]['ndcg@10'])
    improvement = all_methods[best_method]['ndcg@10'] - all_methods[best_single]['ndcg@10']

    # Write results
    results = {
        'individual_systems': {
            'bm25': bm25_metrics,
            'dense': dense_metrics,
            'sparse': sparse_metrics
        },
        'fusion_methods': {
            'rrf': {**best_rrf_metrics, 'best_k': best_rrf_k},
            'combsum': {**best_cs_metrics, 'best_weights': best_cs_weights},
            'combmnz': combmnz_metrics
        },
        'best_method': best_method,
        'best_ndcg': all_methods[best_method]['ndcg@10'],
        'improvement_over_best_single': improvement
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Results written to /app/results.json")
    print(f"Best method: {best_method} (nDCG@10 = {all_methods[best_method]['ndcg@10']:.6f})")


if __name__ == '__main__':
    main()
