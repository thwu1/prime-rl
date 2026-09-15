#!/usr/bin/env python3
"""Search evaluation pipeline - computes IR metrics for TREC-format data.

Usage: python3 pipeline.py [--output FILE]

Computes nDCG@10, ERR@10, and MAP@10 for all retrieval systems found
in /app/data/*.run, using relevance judgments from /app/data/qrels.txt.
"""

import json
import math
import sys
import os
import argparse
from collections import defaultdict

# Configuration
MAX_GRADE = 4  # Maximum possible relevance grade
K_CUTOFF = 10  # Evaluation cutoff


def load_qrels(path):
    """Load TREC-format qrels file."""
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            qid = parts[0]
            docid = parts[2]
            grade = int(parts[3])
            qrels.setdefault(qid, {})
            qrels[qid][docid] = grade  # overwrites if seen before
    return qrels


def load_run(path):
    """Load TREC-format run file."""
    run = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 6:
                continue
            qid = parts[0]
            docid = parts[2]
            rank = int(parts[3])
            score = float(parts[4])
            run.setdefault(qid, []).append((docid, rank, score))
    for qid in run:
        run[qid].sort(key=lambda x: x[1])
    return run


def compute_ndcg(qrels_q, ranked, k=K_CUTOFF):
    """Compute nDCG@k with gain = 2^grade - 1."""
    dcg = 0.0
    for i in range(min(k, len(ranked))):
        g = qrels_q.get(ranked[i][0], 0)
        dcg += (2 ** g - 1) / math.log2(i + 2)
    # Ideal DCG: use the best possible ranking
    grades = list(qrels_q.values())
    idcg = 0.0
    for i in range(min(k, len(grades))):
        idcg += (2 ** grades[i] - 1) / math.log2(i + 2)
    return dcg / idcg if idcg > 0 else 0.0


def compute_err(qrels_q, ranked, k=K_CUTOFF):
    """Compute ERR@k using cascade browsing model.

    ERR = sum_{r=1}^{k} (1/r) * prod_{i=1}^{r-1}(1 - R_i) * R_r
    where R_i = (2^{grade_i} - 1) / 2^{max_grade}
    """
    val = 0.0
    p = 1.0
    for r in range(min(k, len(ranked))):
        g = qrels_q.get(ranked[r][0], 0)
        R = (2 ** g - 1) / (2 ** MAX_GRADE)
        val += (1.0 / (r + 1)) * p * R
        p *= (1 - R)
    return val


def compute_map(qrels_q, ranked, k=K_CUTOFF, threshold=1):
    """Compute MAP@k with binary relevance (grade >= threshold)."""
    R = sum(1 for g in qrels_q.values() if g >= threshold)
    if R == 0:
        return 0.0
    n_rel = 0
    s = 0.0
    for j in range(min(k, len(ranked))):
        g = qrels_q.get(ranked[j][0], 0)
        if g >= threshold:
            n_rel += 1
            s += n_rel / (j + 1)
    return s / k  # normalize by cutoff


def mean_metric(qrels, run, fn):
    """Compute mean of metric over all queries in qrels."""
    vals = []
    for qid in sorted(qrels):
        r = run.get(qid, [])
        vals.append(fn(qrels[qid], r))
    return sum(vals) / len(vals) if vals else 0.0


def rrf_fuse(runs_dict, k_param):
    """Reciprocal Rank Fusion across multiple systems."""
    fused = {}
    for sys_name, run in runs_dict.items():
        for qid in run:
            fused.setdefault(qid, {})
            for docid, rank, _ in run[qid]:
                fused[qid][docid] = fused[qid].get(docid, 0.0) + 1.0 / (k_param + rank)
    result = {}
    for qid in fused:
        docs = sorted(fused[qid].items(), key=lambda x: (-x[1], x[0]))
        result[qid] = [(d, i + 1, s) for i, (d, s) in enumerate(docs)]
    return result


def main():
    parser = argparse.ArgumentParser(description="Search evaluation pipeline")
    parser.add_argument("--output", default="/app/pipeline_output.json",
                        help="Output file path")
    args = parser.parse_args()

    # Load data
    qrels = load_qrels("/app/data/qrels.txt")

    # Find and load all run files
    run_files = sorted([f for f in os.listdir("/app/data/") if f.endswith(".run")])
    runs = {}
    for rf in run_files:
        sys_name = rf.replace(".run", "")
        runs[sys_name] = load_run(f"/app/data/{rf}")

    # Compute individual system metrics
    individual = {}
    for sys_name in sorted(runs):
        individual[sys_name] = {
            "ndcg@10": round(mean_metric(qrels, runs[sys_name], compute_ndcg), 6),
            "err@10": round(mean_metric(qrels, runs[sys_name], compute_err), 6),
            "map@10": round(mean_metric(qrels, runs[sys_name], compute_map), 6),
        }

    # RRF fusion with default k=60
    fused = rrf_fuse(runs, 60)
    fused_ndcg = mean_metric(qrels, fused, compute_ndcg)

    results = {
        "individual_metrics": individual,
        "rrf_fusion": {
            "k": 60,
            "ndcg@10": round(fused_ndcg, 6),
        }
    }

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
