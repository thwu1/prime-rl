#!/usr/bin/env python3

"""IR Evaluation Engine: computes nDCG@10, ERR@10, MAP with condensed list
evaluation and paired bootstrap significance testing."""

import json
import math
import os
import random
from collections import defaultdict


def parse_qrels(path):
    """Parse TREC qrels file. Returns {qid: {docid: rel_grade}}."""
    qrels = defaultdict(dict)
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 4:
                qid, _, did, rel = parts[0], parts[1], parts[2], int(parts[3])
                qrels[qid][did] = rel
    return dict(qrels)


def parse_run(path):
    """Parse TREC run file. Returns {qid: [(docid, score)]} sorted by score desc."""
    run = defaultdict(list)
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 6:
                qid, did, score = parts[0], parts[2], float(parts[4])
                run[qid].append((did, score))
    # Sort each query's results by score descending
    for qid in run:
        run[qid].sort(key=lambda x: -x[1])
    return dict(run)


def condensed_list(ranked_docs, judgments):
    """Remove unjudged documents, preserving order. Returns [(doc, rel)]."""
    return [(doc, judgments[doc]) for doc, _ in ranked_docs if doc in judgments]


def compute_dcg(rels, k):
    """DCG@k: gain = 2^rel - 1, discount = log2(i+1), 1-indexed."""
    return sum((2**rel - 1) / math.log2(i + 2) for i, rel in enumerate(rels[:k]))


def compute_ndcg(ranked_docs, judgments, k=10):
    """nDCG@k with condensed list evaluation."""
    condensed = condensed_list(ranked_docs, judgments)
    if not condensed:
        return 0.0
    rels = [rel for _, rel in condensed]
    dcg = compute_dcg(rels, k)
    # IDCG uses all judged docs for the query
    ideal_rels = sorted(judgments.values(), reverse=True)
    idcg = compute_dcg(ideal_rels, k)
    return dcg / idcg if idcg > 0 else 0.0


def compute_err(ranked_docs, judgments, k=10, max_rel=None):
    """ERR@k with condensed list evaluation."""
    condensed = condensed_list(ranked_docs, judgments)
    if not condensed:
        return 0.0
    err = 0.0
    prob_stop_before = 1.0
    for i, (_, rel) in enumerate(condensed[:k]):
        r_i = (2**rel - 1) / (2**max_rel)
        err += prob_stop_before * r_i / (i + 1)
        prob_stop_before *= (1 - r_i)
    return err


def compute_ap(ranked_docs, judgments):
    """Average Precision with condensed list. Binary: rel >= 1."""
    condensed = condensed_list(ranked_docs, judgments)
    total_rel = sum(1 for r in judgments.values() if r >= 1)
    if total_rel == 0:
        return 0.0
    ap = 0.0
    num_rel_seen = 0
    for i, (_, rel) in enumerate(condensed):
        if rel >= 1:
            num_rel_seen += 1
            ap += num_rel_seen / (i + 1)
    return ap / total_rel


def paired_bootstrap(scores_a, scores_b, n_bootstrap=10000, seed=42):
    """Two-sided paired bootstrap resampling test. Returns p-value."""
    rng = random.Random(seed)
    n = len(scores_a)
    observed_diff = sum(scores_a) / n - sum(scores_b) / n

    count = 0
    for _ in range(n_bootstrap):
        indices = [rng.randint(0, n - 1) for _ in range(n)]
        boot_diff = (sum(scores_a[i] for i in indices) / n
                     - sum(scores_b[i] for i in indices) / n)
        if observed_diff >= 0 and boot_diff <= 0:
            count += 1
        elif observed_diff < 0 and boot_diff >= 0:
            count += 1

    return count / n_bootstrap


def main():
    exp_dir = "/app/experiment"
    qrels = parse_qrels(os.path.join(exp_dir, "qrels.txt"))

    # Determine max_rel across entire qrels
    max_rel = max(rel for judgments in qrels.values() for rel in judgments.values())

    # Parse all run files
    system_names = []
    system_runs = {}
    for fname in sorted(os.listdir(exp_dir)):
        if fname.endswith(".run"):
            sys_name = fname.replace(".run", "")
            system_names.append(sys_name)
            system_runs[sys_name] = parse_run(os.path.join(exp_dir, fname))

    # All query IDs from qrels
    all_qids = sorted(qrels.keys())

    # Compute metrics for each system
    results = {"systems": {}, "significance": {}, "ranking": []}
    per_query_ndcg = {}

    for sys_name in system_names:
        run = system_runs[sys_name]
        sys_results = {"ndcg@10": 0.0, "err@10": 0.0, "map": 0.0, "per_query": {}}

        ndcg_scores = []
        err_scores = []
        ap_scores = []

        for qid in all_qids:
            ranked = run.get(qid, [])
            judgments = qrels[qid]

            ndcg = compute_ndcg(ranked, judgments, k=10)
            err = compute_err(ranked, judgments, k=10, max_rel=max_rel)
            ap = compute_ap(ranked, judgments)

            ndcg_scores.append(ndcg)
            err_scores.append(err)
            ap_scores.append(ap)

            sys_results["per_query"][qid] = {
                "ndcg@10": round(ndcg, 4),
                "err@10": round(err, 4),
                "ap": round(ap, 4),
            }

        n_queries = len(all_qids)
        sys_results["ndcg@10"] = round(sum(ndcg_scores) / n_queries, 4)
        sys_results["err@10"] = round(sum(err_scores) / n_queries, 4)
        sys_results["map"] = round(sum(ap_scores) / n_queries, 4)

        results["systems"][sys_name] = sys_results
        per_query_ndcg[sys_name] = ndcg_scores

    # Pairwise significance testing with Bonferroni correction
    n_comparisons = len(system_names) * (len(system_names) - 1) // 2
    alpha_corrected = 0.05 / n_comparisons

    for i in range(len(system_names)):
        for j in range(i + 1, len(system_names)):
            sys_a, sys_b = system_names[i], system_names[j]
            p = paired_bootstrap(per_query_ndcg[sys_a], per_query_ndcg[sys_b])
            key = f"{sys_a}-{sys_b}"
            results["significance"][key] = {
                "metric": "ndcg@10",
                "p_value": round(p, 4),
                "significant_after_correction": p < alpha_corrected,
            }

    # Ranking by nDCG@10 descending
    results["ranking"] = sorted(
        system_names, key=lambda s: -results["systems"][s]["ndcg@10"]
    )

    # Write output
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
