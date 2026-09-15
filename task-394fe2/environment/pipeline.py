#!/usr/bin/env python3
"""CRUMB retrieval evaluation pipeline.

Computes nDCG@10 and Recall@100 for passage-level retrieval runs
with document-level relevance judgments using MaxP aggregation.
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
    """Build passage-to-document mapping from corpus."""
    parent_map = {}
    for entry in load_jsonl(corpus_path):
        parent_map[entry["document_id"]] = entry["parent_id"]
    return parent_map


def load_qrels(qrels_path):
    """Load relevance judgments indexed by query ID."""
    qrels = {}
    for entry in load_jsonl(qrels_path):
        qid = entry["query_id"]
        qrels[qid] = {qr["id"]: qr["label"] for qr in entry["qrels"]}
    return qrels


def maxp_aggregate(run_path, parent_map):
    """Aggregate passage scores to document level via MaxP."""
    result = {}
    for entry in load_jsonl(run_path):
        qid = entry["query"]["id"]
        doc_scores = defaultdict(list)
        for item in entry["items"]:
            pid = parent_map.get(item["id"])
            if pid is None:
                # Skip passages without parent mapping
                continue
            doc_scores[pid].append(item["score"])
        # Aggregate to document level
        agg = {doc: min(scores) for doc, scores in doc_scores.items()}
        result[qid] = sorted(agg.items(), key=lambda x: (-x[1], x[0]))
    return result


def compute_ndcg(ranking, qrels, k):
    """Compute nDCG at cutoff k."""
    dcg = 0.0
    for i, (doc_id, _) in enumerate(ranking[:k]):
        rel = qrels.get(doc_id, 0)
        gain = rel
        dcg += gain / math.log2(i + 2)

    ideal = sorted(qrels.items(), key=lambda x: (-x[1], x[0]))
    idcg = 0.0
    for i, (_, rel) in enumerate(ideal[:k]):
        gain = rel
        idcg += gain / math.log2(i + 2)

    return 0.0 if idcg == 0 else dcg / idcg


def compute_recall(ranking, qrels, k):
    """Compute recall at cutoff k with binary relevance."""
    relevant = {d for d, r in qrels.items() if r >= 1}
    if not relevant:
        return 0.0
    return sum(1 for d, _ in ranking[:k] if d in relevant) / len(relevant)


def permutation_test(vals_a, vals_b, n_perm=10000):
    """Two-sided paired permutation test."""
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

    np.random.seed(42)

    for rn in run_names:
        run = maxp_aggregate(
            os.path.join(runs_dir, f"{rn}.jsonl"), parent_map
        )
        ndcgs = [
            compute_ndcg(run.get(q, []), qrels.get(q, {}), 10) for q in qids
        ]
        recalls = [
            compute_recall(run.get(q, []), qrels.get(q, {}), 100) for q in qids
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
    os.makedirs("/opt/crumb_eval/output", exist_ok=True)
    with open("/opt/crumb_eval/output/initial_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print("Results written to /opt/crumb_eval/output/initial_results.json")


if __name__ == "__main__":
    main()
