#!/usr/bin/env python3
"""Search relevance evaluation pipeline."""
import json
import math
import os
import sqlite3

import yaml
import fusion


def load_config(config_path='/app/config.yaml'):
    """Load pipeline configuration."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_judgments(db_path):
    """Load relevance judgments from SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT query_id, doc_id, relevance FROM judgments")
    qrels = {}
    for qid, did, rel in cursor:
        qrels.setdefault(qid, {})[did] = rel
    conn.close()
    return qrels


def load_trec_run(filepath):
    """Parse TREC-format run file."""
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


def load_json_run(filepath):
    """Parse JSON-format run file."""
    with open(filepath) as f:
        data = json.load(f)
    runs = {}
    for qid, docs in data.items():
        runs[qid] = [(d['doc_id'], d['score']) for d in docs]
        runs[qid].sort(key=lambda x: -x[1])
    return runs


def load_system_runs(config):
    """Load all system runs based on configuration."""
    all_runs = {}
    system_order = []
    for sys_name, sys_config in config['systems'].items():
        filepath = os.path.join('/app', sys_config['file'])
        if sys_config['format'] == 'trec':
            all_runs[sys_name] = load_trec_run(filepath)
        elif sys_config['format'] == 'json':
            all_runs[sys_name] = load_json_run(filepath)
        system_order.append(sys_name)
    return all_runs, system_order


def ndcg_at_k(ranked_docs, qrels, k=10):
    """Normalized Discounted Cumulative Gain at k."""
    dcg = 0.0
    for i, doc_id in enumerate(ranked_docs[:k]):
        rel = qrels.get(doc_id, 0)
        gain = (2 ** rel) - 1
        discount = math.log(i + 2)
        dcg += gain / discount

    ideal_rels = sorted(qrels.values(), reverse=True)[:k]
    idcg = 0.0
    for i, rel in enumerate(ideal_rels):
        gain = (2 ** rel) - 1
        discount = math.log(i + 2)
        idcg += gain / discount

    return dcg / idcg if idcg > 0 else 0.0


def ap_at_k(ranked_docs, qrels, k=10):
    """Average Precision at k."""
    num_rel = 0
    sum_prec = 0.0
    for i, doc_id in enumerate(ranked_docs[:k]):
        if qrels.get(doc_id, 0) > 0:
            num_rel += 1
            sum_prec += num_rel / (i + 1)
    total_relevant = sum(1 for r in qrels.values() if r > 0)
    if total_relevant == 0:
        return 0.0
    return sum_prec / total_relevant


def mrr_score(ranked_docs, qrels):
    """Reciprocal rank of first relevant document."""
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


def grid_search_rrf(system_runs_list, qrels_by_query, query_ids, k_candidates):
    """Find the best RRF k parameter via grid search."""
    best_k, best_ndcg, best_metrics = None, -1, None
    for k in k_candidates:
        fused = fusion.rrf_fuse(system_runs_list, query_ids, k)
        metrics = eval_system(fused, qrels_by_query, query_ids)
        if metrics['ndcg@10'] > best_ndcg:
            best_k = k
            best_ndcg = metrics['ndcg@10']
            best_metrics = metrics
    return best_k, best_metrics


def grid_search_combsum(system_runs_list, qrels_by_query, query_ids, config):
    """Find the best CombSUM weights via grid search."""
    step = config['fusion']['combsum']['weight_step']
    lo, hi = config['fusion']['combsum']['weight_range']
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
                fused = fusion.combsum_fuse(system_runs_list, query_ids, weights)
                metrics = eval_system(fused, qrels_by_query, query_ids)
                if metrics['ndcg@10'] > best_ndcg:
                    best_weights = weights
                    best_ndcg = metrics['ndcg@10']
                    best_metrics = metrics
    return best_weights, best_metrics


def main():
    config = load_config()

    # Load relevance judgments
    db_path = os.path.join('/app', config['evaluation']['judgments_db'])
    qrels_by_query = load_judgments(db_path)
    query_ids = sorted(qrels_by_query.keys())

    # Load system runs
    all_runs, system_order = load_system_runs(config)

    # Evaluate individual systems
    individual_metrics = {}
    for sys_name in system_order:
        individual_metrics[sys_name] = eval_system(
            all_runs[sys_name], qrels_by_query, query_ids)

    # Prepare ordered runs list for fusion
    system_runs_list = [all_runs[s] for s in system_order]

    # RRF grid search
    k_candidates = config['fusion']['rrf']['k_candidates']
    best_rrf_k, rrf_metrics = grid_search_rrf(
        system_runs_list, qrels_by_query, query_ids, k_candidates)

    # CombSUM grid search
    best_cs_weights, combsum_metrics = grid_search_combsum(
        system_runs_list, qrels_by_query, query_ids, config)

    # CombMNZ (no tunable parameters)
    fused = fusion.combmnz_fuse(system_runs_list, query_ids)
    combmnz_metrics = eval_system(fused, qrels_by_query, query_ids)

    # Find best overall method
    all_methods = dict(individual_metrics)
    all_methods['rrf'] = rrf_metrics
    all_methods['combsum'] = combsum_metrics
    all_methods['combmnz'] = combmnz_metrics

    best_method = max(all_methods, key=lambda m: all_methods[m]['ndcg@10'])
    best_single = max(system_order,
                      key=lambda s: individual_metrics[s]['ndcg@10'])
    best_ndcg = all_methods[best_method]['ndcg@10']
    improvement = best_ndcg - individual_metrics[best_single]['ndcg@10']

    # Write results
    results = {
        'individual_systems': individual_metrics,
        'fusion_methods': {
            'rrf': {**rrf_metrics, 'best_k': best_rrf_k},
            'combsum': {**combsum_metrics, 'best_weights': best_cs_weights},
            'combmnz': combmnz_metrics
        },
        'best_method': best_method,
        'best_ndcg': best_ndcg,
        'improvement_over_best_single': improvement
    }

    output_path = os.path.join('/app', config['output'])
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {output_path}")
    print(f"Best method: {best_method} (nDCG@10 = {best_ndcg:.6f})")


if __name__ == '__main__':
    main()
