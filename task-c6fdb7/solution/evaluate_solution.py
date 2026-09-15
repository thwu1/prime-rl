#!/usr/bin/env python3
"""Complete IR evaluation pipeline — reference implementation that fixes all bugs."""

import csv
import gzip
import json
import math
import sqlite3

import numpy as np
import yaml


def load_spec(path='/app/config.yaml'):
    with open(path) as f:
        return yaml.safe_load(f)


def load_judgments(db_path):
    """Load and aggregate relevance judgments using expertise-weighted mean.

    FIX: The buggy pipeline does SELECT query_id, doc_id, relevance FROM judgments
    without aggregation — the last annotator row (crowd worker, always rates 3) wins
    via dict overwrite. The correct approach JOINs the annotators table and computes
    the weighted mean, rounded to the nearest integer.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("""
        SELECT j.query_id, j.doc_id,
               ROUND(SUM(j.relevance * a.weight) / SUM(a.weight)) as relevance
        FROM judgments j
        JOIN annotators a ON j.annotator_id = a.id
        GROUP BY j.query_id, j.doc_id
    """)
    qrels = {}
    for qid, did, rel in cursor:
        qrels.setdefault(qid, {})[did] = int(rel)
    conn.close()
    return qrels


def load_trec_run(filepath):
    """Parse standard TREC-format run file."""
    runs = {}
    with open(filepath) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 6:
                continue
            qid, doc_id, score = parts[0], parts[2], float(parts[4])
            runs.setdefault(qid, []).append((doc_id, score))
    for qid in runs:
        runs[qid].sort(key=lambda x: -x[1])
    return runs


def load_gzipped_json_run(filepath):
    """Parse gzipped JSON run file."""
    with gzip.open(filepath, 'rt') as f:
        data = json.load(f)
    runs = {}
    for qid, docs in data.items():
        runs[qid] = [(d['doc_id'], d['score']) for d in docs]
        runs[qid].sort(key=lambda x: -x[1])
    return runs


def load_csv_run(filepath):
    """Parse CSV run file with headers."""
    runs = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            qid = row['query_id']
            doc_id = row['doc_id']
            score = float(row['score'])
            runs.setdefault(qid, []).append((doc_id, score))
    for qid in runs:
        runs[qid].sort(key=lambda x: -x[1])
    return runs


def load_system_runs(spec):
    """Load all system runs based on spec configuration."""
    loaders = {
        'trec': load_trec_run,
        'gzipped_json': load_gzipped_json_run,
        'csv': load_csv_run,
    }
    all_runs = {}
    for sys_name, sys_config in spec['systems'].items():
        filepath = '/app/' + sys_config['file']
        fmt = sys_config['format']
        all_runs[sys_name] = loaders[fmt](filepath)
    return all_runs


# ---------------------------------------------------------------------------
# IR Metrics — all bugs fixed
# ---------------------------------------------------------------------------

def ndcg_at_k(ranked_docs, qrels, k=10):
    """Normalized Discounted Cumulative Gain at k.

    FIX: The buggy pipeline computes IDCG from retrieved documents only
    (retrieved_rels = [qrels.get(d,0) for d in ranked_docs[:k]]).
    The correct IDCG uses ALL qrels values sorted descending, truncated to k.
    """
    dcg = 0.0
    for i, doc_id in enumerate(ranked_docs[:k]):
        rel = qrels.get(doc_id, 0)
        gain = (2 ** rel) - 1
        discount = math.log2(i + 2)
        dcg += gain / discount

    ideal_rels = sorted(qrels.values(), reverse=True)[:k]
    idcg = 0.0
    for i, rel in enumerate(ideal_rels):
        gain = (2 ** rel) - 1
        discount = math.log2(i + 2)
        idcg += gain / discount

    return dcg / idcg if idcg > 0 else 0.0


def ap_at_k(ranked_docs, qrels, k=10):
    """Average Precision at k.

    FIX: The buggy pipeline divides by total_relevant. The correct denominator
    is min(total_relevant, k), following the Buckley-Voorhees convention for
    recall-limited evaluation at a cutoff.
    """
    num_rel = 0
    sum_prec = 0.0
    for i, doc_id in enumerate(ranked_docs[:k]):
        if qrels.get(doc_id, 0) > 0:
            num_rel += 1
            sum_prec += num_rel / (i + 1)
    total_relevant = sum(1 for r in qrels.values() if r > 0)
    if total_relevant == 0:
        return 0.0
    return sum_prec / min(total_relevant, k)


def mrr_score(ranked_docs, qrels):
    """Reciprocal Rank of first relevant document."""
    for i, doc_id in enumerate(ranked_docs):
        if qrels.get(doc_id, 0) > 0:
            return 1.0 / (i + 1)
    return 0.0


def precision_at_k(ranked_docs, qrels, k=10):
    """Fraction of top-k documents that are relevant."""
    return sum(1 for d in ranked_docs[:k] if qrels.get(d, 0) > 0) / k


def eval_system(runs, qrels_by_query, query_ids):
    """Compute mean metrics over all queries for a retrieval system."""
    metrics = {'ndcg@10': [], 'map@10': [], 'mrr': [], 'p@10': []}
    for qid in query_ids:
        if qid not in runs or qid not in qrels_by_query:
            continue
        ranked = [d for d, s in runs[qid]]
        qrels = qrels_by_query[qid]
        metrics['ndcg@10'].append(ndcg_at_k(ranked, qrels, 10))
        metrics['map@10'].append(ap_at_k(ranked, qrels, 10))
        metrics['mrr'].append(mrr_score(ranked, qrels))
        metrics['p@10'].append(precision_at_k(ranked, qrels, 10))
    n = len(metrics['ndcg@10'])
    if n == 0:
        return {k: 0.0 for k in metrics}
    return {k: sum(v) / n for k, v in metrics.items()}


# ---------------------------------------------------------------------------
# Rank Fusion Methods — all bugs fixed
# ---------------------------------------------------------------------------

def minmax_normalize(doc_scores):
    """Min-max normalize scores to [0, 1] per query."""
    if len(doc_scores) <= 1:
        return [(d, 1.0) for d, s in doc_scores]
    scores = [s for _, s in doc_scores]
    mn, mx = min(scores), max(scores)
    if mx == mn:
        return [(d, 1.0) for d, s in doc_scores]
    return [(d, (s - mn) / (mx - mn)) for d, s in doc_scores]


def rrf_fuse(system_runs_list, qids, k=60):
    """Reciprocal Rank Fusion with 1-based ranking.

    FIX: The buggy pipeline uses enumerate(sys_runs[qid]) which is 0-based.
    RRF requires 1-based ranking: score = 1/(k + rank) where rank starts at 1.
    """
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
    """CombSUM: weighted combination of min-max normalized scores.

    FIX: The buggy pipeline uses global min-max normalization across all queries.
    Correct CombSUM normalizes scores per-query so that score ranges are comparable
    within each query.
    """
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
    """CombMNZ: sum of normalized scores times count of systems returning doc."""
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


# ---------------------------------------------------------------------------
# Statistical Significance Testing — entirely missing from buggy pipeline
# ---------------------------------------------------------------------------

def paired_bootstrap_test(scores_a, scores_b, n_iter=10000, seed=42):
    """Paired bootstrap significance test (two-tailed)."""
    rng = np.random.RandomState(seed)
    n = len(scores_a)
    count_a_wins = 0
    for _ in range(n_iter):
        idx = rng.randint(0, n, size=n)
        a_mean = np.mean([scores_a[i] for i in idx])
        b_mean = np.mean([scores_b[i] for i in idx])
        if a_mean >= b_mean:
            count_a_wins += 1
    ratio = count_a_wins / n_iter
    p_value = 2.0 * min(ratio, 1.0 - ratio)
    return p_value


# ---------------------------------------------------------------------------
# Grid Search
# ---------------------------------------------------------------------------

def grid_search_rrf(system_runs_list, qrels_by_query, query_ids, k_candidates):
    """Find optimal RRF k parameter via grid search on nDCG@10."""
    best_k, best_ndcg, best_metrics = None, -1, None
    for k in k_candidates:
        fused = rrf_fuse(system_runs_list, query_ids, k)
        metrics = eval_system(fused, qrels_by_query, query_ids)
        if metrics['ndcg@10'] > best_ndcg:
            best_k = k
            best_ndcg = metrics['ndcg@10']
            best_metrics = metrics
    return best_k, best_metrics


def grid_search_combsum(system_runs_list, qrels_by_query, query_ids, spec):
    """Find optimal CombSUM weights via grid search on nDCG@10."""
    step = spec['fusion']['combsum']['weight_step']
    lo, hi = spec['fusion']['combsum']['weight_range']
    weight_options = []
    w = lo
    while w <= hi + 1e-9:
        weight_options.append(round(w, 2))
        w += step

    best_weights, best_ndcg, best_metrics = None, -1, None
    for w1 in weight_options:
        for w2 in weight_options:
            for w3 in weight_options:
                if w1 + w2 + w3 == 0:
                    continue
                weights = [w1, w2, w3]
                fused = combsum_fuse(system_runs_list, query_ids, weights)
                metrics = eval_system(fused, qrels_by_query, query_ids)
                if metrics['ndcg@10'] > best_ndcg:
                    best_weights = weights
                    best_ndcg = metrics['ndcg@10']
                    best_metrics = metrics
    return best_weights, best_metrics


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    spec = load_spec()

    # Load and aggregate relevance judgments
    db_path = '/app/' + spec['evaluation']['judgments_db']
    qrels_by_query = load_judgments(db_path)
    query_ids = sorted(qrels_by_query.keys())

    # Load system runs from heterogeneous formats
    all_runs = load_system_runs(spec)
    system_order = spec['fusion']['system_order']

    # Evaluate individual systems and collect per-query nDCG for significance
    individual_metrics = {}
    per_query_ndcg = {}
    for sys_name in system_order:
        individual_metrics[sys_name] = eval_system(
            all_runs[sys_name], qrels_by_query, query_ids)
        per_query_ndcg[sys_name] = []
        for qid in query_ids:
            if qid in all_runs[sys_name] and qid in qrels_by_query:
                ranked = [d for d, s in all_runs[sys_name][qid]]
                per_query_ndcg[sys_name].append(
                    ndcg_at_k(ranked, qrels_by_query[qid], 10))

    # Rank fusion
    system_runs_list = [all_runs[s] for s in system_order]

    # RRF grid search
    k_candidates = spec['fusion']['rrf']['k_candidates']
    best_rrf_k, rrf_metrics = grid_search_rrf(
        system_runs_list, qrels_by_query, query_ids, k_candidates)

    # CombSUM grid search
    best_cs_weights, combsum_metrics = grid_search_combsum(
        system_runs_list, qrels_by_query, query_ids, spec)

    # CombMNZ (no tunable parameters)
    fused = combmnz_fuse(system_runs_list, query_ids)
    combmnz_metrics = eval_system(fused, qrels_by_query, query_ids)

    # Identify best overall method
    all_methods = dict(individual_metrics)
    all_methods['rrf'] = rrf_metrics
    all_methods['combsum'] = combsum_metrics
    all_methods['combmnz'] = combmnz_metrics

    best_method = max(all_methods, key=lambda m: all_methods[m]['ndcg@10'])
    best_single = max(system_order,
                      key=lambda s: individual_metrics[s]['ndcg@10'])
    best_ndcg = all_methods[best_method]['ndcg@10']
    improvement = best_ndcg - individual_metrics[best_single]['ndcg@10']

    # Paired bootstrap significance tests between individual systems
    sig_spec = spec['significance']
    pairs = [('bm25', 'dense'), ('bm25', 'sparse'), ('dense', 'sparse')]
    significance_tests = {}
    for a, b in pairs:
        p = paired_bootstrap_test(
            per_query_ndcg[a], per_query_ndcg[b],
            n_iter=sig_spec['iterations'], seed=sig_spec['seed'])
        significance_tests[f'{a}_vs_{b}'] = {
            'p_value': p,
            'significant': p < sig_spec['alpha']
        }

    # Write report
    report = {
        'individual_systems': individual_metrics,
        'fusion_methods': {
            'rrf': {**rrf_metrics, 'best_k': best_rrf_k},
            'combsum': {**combsum_metrics, 'best_weights': best_cs_weights},
            'combmnz': combmnz_metrics
        },
        'best_method': best_method,
        'best_ndcg': best_ndcg,
        'improvement_over_best_single': improvement,
        'significance_tests': significance_tests
    }

    with open('/app/results.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Results written to /app/results.json")
    print(f"Best method: {best_method} (nDCG@10 = {best_ndcg:.6f})")


if __name__ == '__main__':
    main()
