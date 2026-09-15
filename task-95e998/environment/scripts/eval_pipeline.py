#!/usr/bin/env python3
"""Evaluation pipeline for shared task submissions.

Computes nDCG@10, ERR@10, and MAP for retrieval system submissions
against relevance judgments. Outputs results to published_report.json.
"""

import json
import math
import os
from collections import defaultdict


def load_qrels(path):
    """Load TREC-format relevance judgments."""
    qrels = defaultdict(dict)
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 4:
                qid = parts[0]
                docid = parts[2]
                rel = int(parts[3])
                qrels[qid][docid] = rel
    return dict(qrels)


def load_run(path):
    """Load TREC-format run file, sorted by score descending."""
    run = defaultdict(list)
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 6:
                qid = parts[0]
                docid = parts[2]
                score = float(parts[4])
                run[qid].append((docid, score))
    for qid in run:
        run[qid].sort(key=lambda x: -x[1])
    return dict(run)


def ndcg(ranked_docs, judgments, k=10):
    """Normalized Discounted Cumulative Gain at k."""
    rels = [judgments.get(doc, 0) for doc, _ in ranked_docs[:k]]
    if not rels:
        return 0.0
    dcg = sum((2**r - 1) / math.log2(i + 2) for i, r in enumerate(rels))
    # Build ideal ranking from retrieved judged documents
    ideal_rels = sorted(
        [judgments[doc] for doc, _ in ranked_docs if doc in judgments],
        reverse=True,
    )
    idcg = sum(
        (2**r - 1) / math.log2(i + 2) for i, r in enumerate(ideal_rels[:k])
    )
    return dcg / idcg if idcg > 0 else 0.0


def err(ranked_docs, judgments, k=10):
    """Expected Reciprocal Rank at k."""
    if not judgments:
        return 0.0
    max_grade = max(judgments.values())
    if max_grade == 0:
        return 0.0
    e = 0.0
    p = 1.0
    for i, (doc, _) in enumerate(ranked_docs[:k]):
        rel = judgments.get(doc, 0)
        r_i = (2**rel - 1) / (2**max_grade)
        e += p * r_i / (i + 1)
        p *= (1 - r_i)
    return e


def avg_precision(ranked_docs, judgments):
    """Average Precision with binary relevance (grade >= 1)."""
    n_rel = sum(1 for doc, _ in ranked_docs if judgments.get(doc, 0) >= 1)
    if n_rel == 0:
        return 0.0
    ap = 0.0
    count = 0
    for i, (doc, _) in enumerate(ranked_docs):
        if judgments.get(doc, 0) >= 1:
            count += 1
            ap += count / (i + 1)
    return ap / n_rel


def evaluate():
    exp_dir = "/app/experiment"
    qrels = load_qrels(os.path.join(exp_dir, "qrels.txt"))
    query_ids = sorted(qrels.keys())

    systems = {}
    for fname in sorted(os.listdir(exp_dir)):
        if fname.endswith(".run"):
            sname = fname.replace(".run", "")
            systems[sname] = load_run(os.path.join(exp_dir, fname))

    report = {"systems": {}, "ranking": []}

    for sname in sorted(systems.keys()):
        run = systems[sname]
        pq = {}
        ndcg_list, err_list, ap_list = [], [], []

        for qid in query_ids:
            docs = run.get(qid, [])
            judg = qrels[qid]

            n = ndcg(docs, judg)
            e = err(docs, judg)
            a = avg_precision(docs, judg)

            ndcg_list.append(n)
            err_list.append(e)
            ap_list.append(a)

            pq[qid] = {
                "ndcg@10": round(n, 4),
                "err@10": round(e, 4),
                "ap": round(a, 4),
            }

        nq = len(query_ids)
        report["systems"][sname] = {
            "ndcg@10": round(sum(ndcg_list) / nq, 4),
            "err@10": round(sum(err_list) / nq, 4),
            "map": round(sum(ap_list) / nq, 4),
            "per_query": pq,
        }

    report["ranking"] = sorted(
        report["systems"].keys(),
        key=lambda s: -report["systems"][s]["ndcg@10"],
    )

    with open("/app/published_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Report written to /app/published_report.json")


if __name__ == "__main__":
    evaluate()
