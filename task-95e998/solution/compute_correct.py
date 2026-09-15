#!/usr/bin/env python3

"""Compute correct IR evaluation metrics for the experiment.

Fixes three methodology errors in eval_pipeline.py:
1. IDCG must use ALL judged documents from qrels, not just retrieved ones.
2. MAP denominator must be total relevant in qrels, not just retrieved relevant.
3. ERR must use the global maximum relevance grade, not per-query max.

Uses standard methodology matching trec_eval/ir_measures:
  - Unjudged documents treated as relevance 0
  - nDCG@10: gain = 2^rel - 1, discount = log2(rank+1)
  - MAP: binary relevance (rel >= 1)
  - ERR@10: Chapelle et al. 2009 cascade model
"""

import json
import math
import os
from collections import defaultdict


def load_qrels(path):
    qrels = defaultdict(dict)
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 4:
                qrels[parts[0]][parts[2]] = int(parts[3])
    return dict(qrels)


def load_run(path):
    run = defaultdict(list)
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 6:
                run[parts[0]].append((parts[2], float(parts[4])))
    for qid in run:
        run[qid].sort(key=lambda x: -x[1])
    return dict(run)


def compute_ndcg(ranked, judgments, k=10):
    """nDCG@10 with IDCG from ALL qrels documents."""
    rels = [judgments.get(doc, 0) for doc, _ in ranked[:k]]
    dcg = sum((2**r - 1) / math.log2(i + 2) for i, r in enumerate(rels))
    # IDCG from all judged documents in qrels (not just retrieved)
    ideal = sorted(judgments.values(), reverse=True)
    idcg = sum((2**r - 1) / math.log2(i + 2) for i, r in enumerate(ideal[:k]))
    return dcg / idcg if idcg > 0 else 0.0


def compute_err(ranked, judgments, k=10, global_max_rel=3):
    """ERR@10 with global max relevance grade."""
    e = 0.0
    p = 1.0
    for i, (doc, _) in enumerate(ranked[:k]):
        rel = judgments.get(doc, 0)
        r_i = (2**rel - 1) / (2**global_max_rel)
        e += p * r_i / (i + 1)
        p *= (1 - r_i)
    return e


def compute_ap(ranked, judgments):
    """AP with denominator = total relevant in qrels."""
    total_rel = sum(1 for r in judgments.values() if r >= 1)
    if total_rel == 0:
        return 0.0
    ap = 0.0
    count = 0
    for i, (doc, _) in enumerate(ranked):
        if judgments.get(doc, 0) >= 1:
            count += 1
            ap += count / (i + 1)
    return ap / total_rel


def main():
    qrels = load_qrels("/app/experiment/qrels.txt")
    global_max_rel = max(r for j in qrels.values() for r in j.values())
    query_ids = sorted(qrels.keys())

    systems = {}
    for f in sorted(os.listdir("/app/experiment")):
        if f.endswith(".run"):
            systems[f[:-4]] = load_run(os.path.join("/app/experiment", f))

    report = {"systems": {}, "ranking": []}

    for sname in sorted(systems):
        run = systems[sname]
        pq = {}
        nvals, evals, avals = [], [], []

        for qid in query_ids:
            docs = run.get(qid, [])
            judg = qrels[qid]
            n = compute_ndcg(docs, judg)
            e = compute_err(docs, judg, global_max_rel=global_max_rel)
            a = compute_ap(docs, judg)
            nvals.append(n)
            evals.append(e)
            avals.append(a)
            pq[qid] = {
                "ndcg@10": round(n, 4),
                "err@10": round(e, 4),
                "ap": round(a, 4),
            }

        nq = len(query_ids)
        report["systems"][sname] = {
            "ndcg@10": round(sum(nvals) / nq, 4),
            "err@10": round(sum(evals) / nq, 4),
            "map": round(sum(avals) / nq, 4),
            "per_query": pq,
        }

    report["ranking"] = sorted(
        report["systems"], key=lambda s: -report["systems"][s]["ndcg@10"]
    )

    with open("/app/corrected_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Corrected report written to /app/corrected_report.json")


if __name__ == "__main__":
    main()
