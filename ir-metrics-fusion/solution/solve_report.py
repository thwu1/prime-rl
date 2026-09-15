#!/usr/bin/env python3

"""
Produce /app/report.json by:
1. Loading and evaluating passage ranking data with correct IR metrics
2. Converting run files to TREC format and running trec_eval for cross-validation
3. Implementing paired randomization significance tests
4. Grid-searching optimal RRF k parameter
5. Ranking all systems by nDCG@10
"""

import json
import math
import os
import random
import subprocess
import tempfile
from collections import defaultdict


# ============================================================
# Data loading
# ============================================================

def load_qrels(path):
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            qid = int(parts[0])
            pid = int(parts[2])
            grade = int(parts[3])
            if qid not in qrels:
                qrels[qid] = {}
            qrels[qid][pid] = grade
    return qrels


def load_run(path):
    entries = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            qid = int(parts[0])
            pid = int(parts[1])
            rank = int(parts[2])
            entries.append((qid, pid, rank))
    entries.sort(key=lambda x: (x[0], x[2]))
    run = defaultdict(list)
    for qid, pid, rank in entries:
        run[qid].append(pid)
    return dict(run)


# ============================================================
# Correct metric implementations
# ============================================================

def compute_mrr_at_k(qrels, run, k):
    """MRR@k: check ALL relevant passages, not just the first qrel entry."""
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
    """nDCG@k: use log2 (not natural log), sort ideal descending."""
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


def compute_ndcg_at_k_per_query(qrels, run, k):
    result = {}
    for qid in qrels:
        if qid not in run:
            result[qid] = 0.0
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
        result[qid] = dcg / idcg if idcg > 0 else 0.0
    return result


def compute_map_at_k(qrels, run, k):
    """MAP@k = mean over queries of AP@k = (1/R) * sum P(i)*rel(i)."""
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
    recall_sum = 0.0
    n_queries = len(qrels)
    for qid in qrels:
        if qid not in run:
            continue
        ranked_pids = run[qid][:k]
        rel_pids = set(qrels[qid].keys())
        found = len(set(ranked_pids) & rel_pids)
        recall_sum += found / len(rel_pids) if len(rel_pids) > 0 else 0.0
    return recall_sum / n_queries


def compute_p_at_k(qrels, run, k):
    p_sum = 0.0
    n_queries = len(qrels)
    for qid in qrels:
        if qid not in run:
            continue
        ranked_pids = run[qid][:k]
        rel_pids = set(qrels[qid].keys())
        found = len(set(ranked_pids) & rel_pids)
        p_sum += found / k
    return p_sum / n_queries


def evaluate_run(qrels, run, k=10):
    return {
        'MRR@10': compute_mrr_at_k(qrels, run, k),
        'nDCG@10': compute_ndcg_at_k(qrels, run, k),
        'MAP@10': compute_map_at_k(qrels, run, k),
        'Recall@10': compute_recall_at_k(qrels, run, k),
        'P@10': compute_p_at_k(qrels, run, k),
    }


# ============================================================
# Rank fusion
# ============================================================

def rrf_fusion(runs, k_param=60):
    """RRF: score(d) = sum_{r} 1/(k + rank_r(d)). Ties by ascending pid."""
    scores = defaultdict(lambda: defaultdict(float))
    for run in runs.values():
        for qid, pids in run.items():
            for rank, pid in enumerate(pids, 1):
                scores[qid][pid] += 1.0 / (k_param + rank)
    fused = {}
    for qid in scores:
        sorted_pids = sorted(scores[qid].items(),
                             key=lambda x: (-x[1], x[0]))
        fused[qid] = [pid for pid, _ in sorted_pids]
    return fused


def combsum_fusion(runs):
    """CombSUM: score = 1 - (rank-1)/max_rank, summed. Ties by ascending pid."""
    scores = defaultdict(lambda: defaultdict(float))
    for run in runs.values():
        for qid, pids in run.items():
            max_rank = len(pids)
            for rank, pid in enumerate(pids, 1):
                scores[qid][pid] += 1.0 - (rank - 1) / max_rank
    fused = {}
    for qid in scores:
        sorted_pids = sorted(scores[qid].items(),
                             key=lambda x: (-x[1], x[0]))
        fused[qid] = [pid for pid, _ in sorted_pids]
    return fused


# ============================================================
# Statistical significance
# ============================================================

def paired_permutation_test(scores_a, scores_b,
                            n_permutations=10000, seed=42):
    qids = sorted(set(scores_a.keys()) & set(scores_b.keys()))
    diffs = [scores_a[qid] - scores_b[qid] for qid in qids]
    observed_delta = sum(diffs) / len(diffs)
    rng = random.Random(seed)
    count = 0
    for _ in range(n_permutations):
        perm_diffs = [d * (1 if rng.random() > 0.5 else -1) for d in diffs]
        perm_delta = sum(perm_diffs) / len(perm_diffs)
        if abs(perm_delta) >= abs(observed_delta):
            count += 1
    return observed_delta, count / n_permutations


# ============================================================
# trec_eval cross-validation
# ============================================================

def convert_run_to_trec(run_path, output_path, tag):
    with open(run_path) as f_in, open(output_path, 'w') as f_out:
        for line in f_in:
            parts = line.strip().split('\t')
            qid, pid, rank = parts[0], parts[1], int(parts[2])
            score = 1000 - rank + 1
            f_out.write(f"{qid} Q0 {pid} {rank} {score} {tag}\n")


def run_trec_eval_ndcg(qrels_path, run_path):
    result = subprocess.run(
        ['trec_eval', '-m', 'ndcg_cut.10', qrels_path, run_path],
        capture_output=True, text=True
    )
    for line in result.stdout.strip().split('\n'):
        parts = line.split()
        if len(parts) >= 3 and 'ndcg_cut_10' in parts[0]:
            return float(parts[2])
    raise ValueError(f"Failed to parse trec_eval output: {result.stdout}\n"
                     f"stderr: {result.stderr}")


# ============================================================
# Main pipeline
# ============================================================

def main():
    data_dir = '/app/data'
    qrels = load_qrels(f'{data_dir}/qrels.tsv')
    runs = {
        'bm25': load_run(f'{data_dir}/run_bm25.tsv'),
        'neural': load_run(f'{data_dir}/run_neural.tsv'),
        'tfidf': load_run(f'{data_dir}/run_tfidf.tsv'),
    }

    report = {}

    # --- System metrics ---
    report['systems'] = {}
    for name, run in runs.items():
        report['systems'][name] = evaluate_run(qrels, run)

    # --- trec_eval cross-validation ---
    tmpdir = tempfile.mkdtemp()
    trec_eval_ndcg = {}
    for name in ['bm25', 'neural', 'tfidf']:
        trec_path = os.path.join(tmpdir, f'{name}.trec')
        convert_run_to_trec(f'{data_dir}/run_{name}.tsv', trec_path, name)
        trec_eval_ndcg[name] = run_trec_eval_ndcg(
            f'{data_dir}/qrels.tsv', trec_path)
    report['trec_eval_ndcg'] = trec_eval_ndcg

    # --- Pairwise significance ---
    per_query_ndcg = {}
    for name, run in runs.items():
        per_query_ndcg[name] = compute_ndcg_at_k_per_query(qrels, run, 10)

    sig_results = {}
    for a, b in [('bm25', 'neural'), ('bm25', 'tfidf'), ('neural', 'tfidf')]:
        delta, p_val = paired_permutation_test(
            per_query_ndcg[a], per_query_ndcg[b])
        sig_results[f'{a}_vs_{b}'] = {
            'delta': delta,
            'p_value': p_val,
            'significant_at_005': p_val < 0.05,
        }
    report['pairwise_significance'] = sig_results

    # --- Fusion optimization (RRF k grid search) ---
    k_values = [1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    grid_results = {}
    best_k = None
    best_ndcg = -1.0
    for k in k_values:
        fused = rrf_fusion(runs, k_param=k)
        ndcg = compute_ndcg_at_k(qrels, fused, 10)
        grid_results[str(k)] = ndcg
        if ndcg > best_ndcg:
            best_ndcg = ndcg
            best_k = k

    report['fusion_optimization'] = {
        'best_k': best_k,
        'best_ndcg_10': best_ndcg,
        'grid_results': grid_results,
    }

    # Evaluate best RRF and CombSUM
    best_rrf_run = rrf_fusion(runs, k_param=best_k)
    combsum_run = combsum_fusion(runs)
    report['systems']['rrf_optimal'] = evaluate_run(qrels, best_rrf_run)
    report['systems']['combsum'] = evaluate_run(qrels, combsum_run)

    # --- Final ranking by nDCG@10 descending ---
    all_ndcg = {name: m['nDCG@10'] for name, m in report['systems'].items()}
    report['final_ranking'] = sorted(
        all_ndcg.keys(), key=lambda x: all_ndcg[x], reverse=True)

    # Write output
    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("Report written to /app/report.json")
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
