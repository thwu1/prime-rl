#!/usr/bin/env python3
"""Evaluation pipeline for reasoning-intensive retrieval benchmark.

Evaluates multiple retrieval models on a graded-relevance benchmark,
then performs per-domain fusion optimization.
"""
import json
import os
import sys

sys.path.insert(0, "/app/src")
from trec_utils import load_trec_run, load_trec_qrels
from fusion import reciprocal_rank_fusion, comb_sum, comb_mnz, weighted_comb_sum
from utils import load_queries

import pytrec_eval


def build_qrels_for_eval(raw_qrels):
    """Prepare qrels for pytrec_eval evaluation.

    Converts relevance values to binary for consistent evaluation.
    """
    qrels = {}
    for qid, docs in raw_qrels.items():
        qrels[qid] = {}
        for did, rel in docs.items():
            # Use binary relevance: any positive relevance is treated as 1
            qrels[qid][did] = 1 if rel > 0 else 0
    return qrels


def evaluate_run(qrels, results, k_values=(5, 10)):
    """Compute standard IR metrics using pytrec_eval."""
    measures = set()
    measures.add("ndcg_cut." + ",".join(str(k) for k in k_values))
    measures.add("map_cut.10")
    measures.add("recip_rank")

    evaluator = pytrec_eval.RelevanceEvaluator(qrels, measures)
    scores = evaluator.evaluate(results)

    out = {}
    for k in k_values:
        vals = [scores[q][f"ndcg_cut_{k}"] for q in scores]
        out[f"nDCG@{k}"] = round(sum(vals) / len(vals), 5) if vals else 0.0
    vals = [scores[q]["map_cut_10"] for q in scores]
    out["MAP@10"] = round(sum(vals) / len(vals), 5) if vals else 0.0
    vals = [scores[q]["recip_rank"] for q in scores]
    out["MRR"] = round(sum(vals) / len(vals), 5) if vals else 0.0

    return out


def evaluate_per_domain(qrels, results, queries, k_values=(5, 10)):
    """Compute metrics broken down by domain."""
    domain_qids = {}
    for q in queries:
        domain_qids.setdefault(q["domain"], []).append(q["id"])

    per_domain = {}
    for domain, qids in domain_qids.items():
        d_qrels = {q: qrels[q] for q in qids if q in qrels}
        d_results = {q: results[q] for q in qids if q in results}
        if d_qrels and d_results:
            per_domain[domain] = evaluate_run(d_qrels, d_results, k_values)

    return per_domain


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    # Load data
    raw_qrels = load_trec_qrels(config["qrels_path"])
    queries = load_queries(config["queries_path"])

    # Prepare qrels for evaluation
    qrels = build_qrels_for_eval(raw_qrels)

    print(f"Loaded {len(queries)} queries, {len(qrels)} qrels entries")

    # Evaluate each model
    output = {"baseline_metrics": {}, "fusion_optimization": {}, "optimized_fusion": {}}
    runs = {}

    for model_name in config["models"]:
        run_path = os.path.join(config["runs_dir"], f"{model_name}.trec")
        run = load_trec_run(run_path)
        runs[model_name] = run

        overall = evaluate_run(qrels, run)
        per_domain = evaluate_per_domain(qrels, run, queries)

        output["baseline_metrics"][model_name] = {
            "overall": overall,
            "per_domain": per_domain,
        }
        print(f"  {model_name}: nDCG@10 = {overall.get('nDCG@10', 0):.4f}")

    # --- Fusion optimization ---
    # TODO: Implement fusion optimization using the methods in fusion.py.
    # Refer to config.json for parameters and the output schema for expected keys.

    output["fusion_optimization"] = {}
    output["optimized_fusion"] = {"overall": {}, "per_domain": {}}

    # Write results
    with open(config["output_path"], "w") as f:
        json.dump(output, f, indent=2)

    print(f"Results written to {config['output_path']}")


if __name__ == "__main__":
    main()
