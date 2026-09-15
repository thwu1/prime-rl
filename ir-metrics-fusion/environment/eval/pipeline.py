#!/usr/bin/env python3
"""Evaluation pipeline: compute metrics for all runs + fused runs.

Loads qrels and ranking runs from /app/data/, computes MRR@10, nDCG@10,
MAP@10, and Recall@10 for each run, applies RRF and CombSUM fusion,
evaluates the fused runs, and writes all results to /app/results.json.
"""

import json
import sys

sys.path.insert(0, '/app/eval')

from metrics import (
    load_qrels, load_run,
    compute_mrr_at_k, compute_ndcg_at_k,
    compute_map_at_k, compute_recall_at_k,
)
from fusion import rrf_fusion, combsum_fusion

K = 10


def evaluate_run(qrels, run):
    return {
        'MRR@10': compute_mrr_at_k(qrels, run, K),
        'nDCG@10': compute_ndcg_at_k(qrels, run, K),
        'MAP@10': compute_map_at_k(qrels, run, K),
        'Recall@10': compute_recall_at_k(qrels, run, K),
    }


def main():
    qrels = load_qrels('/app/data/qrels.tsv')

    runs = {
        'bm25': load_run('/app/data/run_bm25.tsv'),
        'neural': load_run('/app/data/run_neural.tsv'),
        'tfidf': load_run('/app/data/run_tfidf.tsv'),
    }

    results = {}
    for name, run in runs.items():
        results[name] = evaluate_run(qrels, run)

    rrf_run = rrf_fusion(runs, k_param=60)
    combsum_run = combsum_fusion(runs)

    results['rrf'] = evaluate_run(qrels, rrf_run)
    results['combsum'] = evaluate_run(qrels, combsum_run)

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
