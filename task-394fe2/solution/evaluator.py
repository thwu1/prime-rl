#!/usr/bin/env python3
"""Correct CRUMB retrieval evaluation pipeline.

Fixes all defects in the deployed pipeline.py:
1. MaxP uses max (not min) for passage-to-document aggregation
2. nDCG uses exponential gain: 2^rel - 1 (not linear)
3. Null parent_id resolved by extracting document prefix from passage ID
4. Qrel document IDs stripped of whitespace before matching
5. Numpy seed reset to 42 before each pairwise permutation test

"""
import json
import math
import os
from collections import defaultdict

import numpy as np

DATA_DIR = "/opt/crumb_eval/data"


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def build_parent_map(corpus_path):
    """Build passage-to-document mapping, resolving null parent_ids."""
    parent_map = {}
    for entry in load_jsonl(corpus_path):
        pid = entry["parent_id"]
        if pid is None:
            pid = entry["document_id"].split(":")[0]
        parent_map[entry["document_id"]] = pid
    return parent_map


def load_qrels(qrels_path):
    """Load qrels with whitespace normalization on document IDs."""
    qrels = {}
    for entry in load_jsonl(qrels_path):
        qid = entry["query_id"]
        qrels[qid] = {}
        for qr in entry["qrels"]:
            doc_id = qr["id"].strip()
            qrels[qid][doc_id] = qr["label"]
    return qrels


def maxp_aggregate(run_path, parent_map):
    """Aggregate passage scores to document level using MaxP (maximum)."""
    result = {}
    for entry in load_jsonl(run_path):
        qid = entry["query"]["id"]
        # Deduplicate passages: keep highest score per passage ID
        passage_scores = {}
        for item in entry["items"]:
            pid = item["id"]
            score = item["score"]
            if pid not in passage_scores or score > passage_scores[pid]:
                passage_scores[pid] = score
        # MaxP: max score per parent document
        doc_scores = defaultdict(float)
        for pid, score in passage_scores.items():
            parent = parent_map.get(pid, pid.split(":")[0])
            doc_scores[parent] = max(doc_scores[parent], score)
        result[qid] = sorted(doc_scores.items(), key=lambda x: (-x[1], x[0]))
    return result


def ndcg_at_k(ranking, qrels, k):
    """nDCG@k with exponential gain and log2 discount."""
    dcg = 0.0
    for i, (doc_id, _) in enumerate(ranking[:k]):
        rel = qrels.get(doc_id, 0)
        gain = 2 ** rel - 1
        dcg += gain / math.log2(i + 2)

    ideal = sorted(qrels.items(), key=lambda x: (-x[1], x[0]))
    idcg = 0.0
    for i, (_, rel) in enumerate(ideal[:k]):
        idcg += (2 ** rel - 1) / math.log2(i + 2)

    return 0.0 if idcg == 0 else dcg / idcg


def recall_at_k(ranking, qrels, k):
    """Binary recall at depth k."""
    relevant = {d for d, r in qrels.items() if r >= 1}
    if not relevant:
        return 0.0
    return sum(1 for d, _ in ranking[:k] if d in relevant) / len(relevant)


def permutation_test(vals_a, vals_b, n_perm=10000, seed=42):
    """Two-sided paired permutation test with seed reset per pair."""
    np.random.seed(seed)
    a, b = np.array(vals_a), np.array(vals_b)
    obs = np.mean(a) - np.mean(b)
    count = 0
    for _ in range(n_perm):
        mask = np.random.randint(0, 2, len(a)).astype(bool)
        pa = np.where(mask, b, a)
        pb = np.where(mask, a, b)
        if abs(np.mean(pa) - np.mean(pb)) >= abs(obs):
            count += 1
    return count / n_perm


def main():
    parent_map = build_parent_map(os.path.join(DATA_DIR, "corpus.jsonl"))
    qrels = load_qrels(os.path.join(DATA_DIR, "qrels.jsonl"))
    qids = sorted(qrels.keys())

    runs_dir = os.path.join(DATA_DIR, "runs")
    run_names = sorted(
        f[:-6] for f in os.listdir(runs_dir) if f.endswith(".jsonl")
    )

    metrics = {}
    pq_ndcg = {}

    for rn in run_names:
        run = maxp_aggregate(
            os.path.join(runs_dir, f"{rn}.jsonl"), parent_map
        )
        ndcgs = [
            ndcg_at_k(run.get(q, []), qrels.get(q, {}), 10) for q in qids
        ]
        recalls = [
            recall_at_k(run.get(q, []), qrels.get(q, {}), 100) for q in qids
        ]
        metrics[rn] = {
            "ndcg@10": round(sum(ndcgs) / len(ndcgs), 4),
            "recall@100": round(sum(recalls) / len(recalls), 4),
        }
        pq_ndcg[rn] = ndcgs

    sig = {}
    for i, ra in enumerate(run_names):
        for j, rb in enumerate(run_names):
            if i >= j:
                continue
            pv = permutation_test(pq_ndcg[ra], pq_ndcg[rb])
            sig[f"{ra}_vs_{rb}"] = {
                "p_value": round(pv, 4),
                "significant": pv < 0.05,
            }

    ranking = sorted(run_names, key=lambda r: -metrics[r]["ndcg@10"])

    output = {
        "per_run_metrics": metrics,
        "significance_matrix": sig,
        "ranking": ranking,
    }
    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)
    print("Correct results written to /app/results.json")


if __name__ == "__main__":
    main()
