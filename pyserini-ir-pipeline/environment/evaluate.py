#!/usr/bin/env python3
"""
Compute TREC-style evaluation metrics: MAP, nDCG@10, Recall@1000.

Usage:
  python3 evaluate.py --qrels QRELS --run RUN [-c]

Options:
  --qrels   Path to TREC qrels file (qid iter docid relevance)
  --run     Path to TREC run file (qid Q0 docid rank score tag)
  -c        Complete evaluation: queries in qrels with no results score 0
"""

import argparse
import math
import sys


def load_qrels(path):
    """Load TREC qrels file. Format: qid iter docid relevance"""
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 4:
                qid, docid, rel = parts[0], parts[2], int(parts[3])
                qrels.setdefault(qid, {})[docid] = rel
    return qrels


def load_run(path):
    """Load TREC run file. Format: qid Q0 docid rank score tag"""
    run = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 6:
                qid = parts[0]
                docid = parts[2]
                rank = int(parts[3])
                score = float(parts[4])
                run.setdefault(qid, []).append((docid, rank, score))
    for qid in run:
        run[qid].sort(key=lambda x: x[1])
    return run


def compute_metrics(qrels, run, complete=True):
    """Compute MAP, nDCG@10, Recall@1000 over all judged queries."""
    if complete:
        eval_qids = sorted(qrels.keys())
    else:
        eval_qids = sorted(set(qrels.keys()) & set(run.keys()))

    aps, ndcgs, recalls = [], [], []

    for qid in eval_qids:
        qrel = qrels.get(qid, {})
        ranked = run.get(qid, [])
        rel_docs = {d: r for d, r in qrel.items() if r > 0}
        num_rel = len(rel_docs)

        # --- Average Precision ---
        if num_rel == 0:
            aps.append(0.0)
        else:
            hits = 0
            psum = 0.0
            for i, (docid, _, _) in enumerate(ranked, 1):
                if docid in rel_docs:
                    hits += 1
                    psum += hits / i
            aps.append(psum / num_rel)

        # --- nDCG@10 ---
        dcg = 0.0
        for i, (docid, _, _) in enumerate(ranked[:10]):
            r = qrel.get(docid, 0)
            if r > 0:
                dcg += (2 ** r - 1) / math.log2(i + 2)
        ideal_rels = sorted(qrel.values(), reverse=True)[:10]
        idcg = sum(
            (2 ** r - 1) / math.log2(i + 2)
            for i, r in enumerate(ideal_rels) if r > 0
        )
        ndcgs.append(dcg / idcg if idcg > 0 else 0.0)

        # --- Recall@1000 ---
        if num_rel == 0:
            recalls.append(0.0)
        else:
            found = sum(1 for docid, _, _ in ranked[:1000] if docid in rel_docs)
            recalls.append(found / num_rel)

    n = len(eval_qids)
    return {
        'map': sum(aps) / n if n else 0.0,
        'ndcg_cut_10': sum(ndcgs) / n if n else 0.0,
        'recall_1000': sum(recalls) / n if n else 0.0,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Compute TREC evaluation metrics (MAP, nDCG@10, Recall@1000)')
    parser.add_argument('--qrels', required=True,
                        help='Path to TREC qrels file')
    parser.add_argument('--run', required=True,
                        help='Path to TREC run file')
    parser.add_argument('-c', action='store_true',
                        help='Complete evaluation (score missing queries as 0)')
    args = parser.parse_args()

    qrels = load_qrels(args.qrels)
    run = load_run(args.run)
    metrics = compute_metrics(qrels, run, complete=args.c)

    for name in ['map', 'ndcg_cut_10', 'recall_1000']:
        print(f"{name:<25s}all\t{metrics[name]:.4f}")


if __name__ == '__main__':
    main()
