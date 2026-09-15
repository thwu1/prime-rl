#!/usr/bin/env python3
"""Correct implementation of retrieval evaluation and fusion optimization.

Fixes:
1. TREC run format: dense.trec has rank/score columns swapped.
   Detection: column 3 contains decimals (scores), column 4 contains integers (ranks).
   Fix: read score from the correct column based on auto-detection.

2. Graded relevance: evaluate.py binarizes qrels (rel>0 -> 1) but nDCG requires
   actual relevance grades (0-3) for correct gain computation.
   Fix: pass raw integer relevance values to pytrec_eval.

Implements:
- RRF with configurable k
- CombSUM with min-max normalization
- CombMNZ with min-max normalization
- Weighted CombSUM with per-domain baseline nDCG@10 as model weights
- Per-domain fusion optimization selecting best method by nDCG@10
"""

import json
import os

import pytrec_eval


# ---------------------------------------------------------------------------
# Data loading (FIXED)
# ---------------------------------------------------------------------------

def load_trec_qrels(path):
    """Load TREC qrels with graded relevance (no binarization)."""
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            qid, docid, rel = parts[0], parts[2], int(parts[3])
            qrels.setdefault(qid, {})[docid] = rel
    return qrels


def load_trec_run(path):
    """Load TREC run with column format auto-detection.

    Standard format: qid Q0 docid rank score run_name
    Some files have columns 3 (rank) and 4 (score) swapped.
    Detection: if column 3 has decimal points and column 4 has integers,
    the columns are swapped and score should be read from column 3.
    """
    with open(path) as f:
        lines = [l.strip() for l in f if l.strip()]

    col3_vals = []
    col4_vals = []
    for line in lines[:60]:
        parts = line.split()
        if len(parts) >= 6:
            col3_vals.append(parts[3])
            col4_vals.append(parts[4])

    col3_has_decimals = sum(1 for v in col3_vals if '.' in v) > len(col3_vals) * 0.5
    col4_all_integers = all(v.replace('-', '').isdigit() for v in col4_vals)

    score_col = 3 if (col3_has_decimals and col4_all_integers) else 4

    results = {}
    for line in lines:
        parts = line.split()
        if len(parts) < 6:
            continue
        qid = parts[0]
        docid = parts[2]
        score = float(parts[score_col])
        results.setdefault(qid, {})[docid] = score
    return results


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_run(qrels, results, k_values=(5, 10)):
    """Compute metrics using pytrec_eval with graded relevance."""
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


# ---------------------------------------------------------------------------
# Fusion methods
# ---------------------------------------------------------------------------

def reciprocal_rank_fusion(runs, k=60):
    """RRF: score(d) = sum over runs of 1/(k + rank), rank is 1-indexed."""
    fused = {}
    for run in runs:
        for qid, scores in run.items():
            fused.setdefault(qid, {})
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            for rank_idx, (did, _) in enumerate(ranked):
                fused[qid].setdefault(did, 0.0)
                fused[qid][did] += 1.0 / (k + rank_idx + 1)
    return fused


def normalize_run(run):
    """Min-max normalize scores per query to [0, 1]."""
    normalized = {}
    for qid, scores in run.items():
        if not scores:
            normalized[qid] = {}
            continue
        vals = list(scores.values())
        min_s, max_s = min(vals), max(vals)
        rng = max_s - min_s
        if rng == 0:
            normalized[qid] = {did: 0.5 for did in scores}
        else:
            normalized[qid] = {did: (s - min_s) / rng for did, s in scores.items()}
    return normalized


def comb_sum(runs):
    """CombSUM: normalize each run then sum scores."""
    norm_runs = [normalize_run(r) for r in runs]
    fused = {}
    for run in norm_runs:
        for qid, scores in run.items():
            fused.setdefault(qid, {})
            for did, s in scores.items():
                fused[qid].setdefault(did, 0.0)
                fused[qid][did] += s
    return fused


def comb_mnz(runs):
    """CombMNZ: CombSUM * count of runs containing each document."""
    norm_runs = [normalize_run(r) for r in runs]
    fused = {}
    counts = {}
    for run in norm_runs:
        for qid, scores in run.items():
            fused.setdefault(qid, {})
            counts.setdefault(qid, {})
            for did, s in scores.items():
                fused[qid].setdefault(did, 0.0)
                fused[qid][did] += s
                counts[qid].setdefault(did, 0)
                counts[qid][did] += 1
    for qid in fused:
        for did in fused[qid]:
            fused[qid][did] *= counts[qid][did]
    return fused


def weighted_comb_sum(runs, model_weights):
    """Weighted CombSUM: normalize, weight by model performance, then sum."""
    norm_runs = [normalize_run(r) for r in runs]
    fused = {}
    for i, run in enumerate(norm_runs):
        w = model_weights[i]
        for qid, scores in run.items():
            fused.setdefault(qid, {})
            for did, s in scores.items():
                fused[qid].setdefault(did, 0.0)
                fused[qid][did] += w * s
    return fused


def domain_ndcg10(qrels, fused, qids):
    """Compute mean nDCG@10 for a set of query IDs."""
    d_qrels = {q: qrels[q] for q in qids if q in qrels}
    d_results = {q: fused[q] for q in qids if q in fused}
    if not d_qrels or not d_results:
        return 0.0
    evaluator = pytrec_eval.RelevanceEvaluator(d_qrels, {"ndcg_cut.10"})
    scores = evaluator.evaluate(d_results)
    vals = [scores[q]["ndcg_cut_10"] for q in scores]
    return sum(vals) / len(vals) if vals else 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    # FIXED: load qrels with graded relevance (no binarization)
    qrels = load_trec_qrels(config["qrels_path"])

    queries = []
    with open(config["queries_path"]) as f:
        for line in f:
            if line.strip():
                queries.append(json.loads(line))

    print(f"Loaded {len(queries)} queries")

    # FIXED: load runs with column auto-detection
    runs = {}
    for model in config["models"]:
        run_path = os.path.join(config["runs_dir"], f"{model}.trec")
        runs[model] = load_trec_run(run_path)

    # --- Baseline evaluation ---
    output = {"baseline_metrics": {}, "fusion_optimization": {}, "optimized_fusion": {}}

    for model, run in runs.items():
        overall = evaluate_run(qrels, run)
        per_domain = evaluate_per_domain(qrels, run, queries)
        output["baseline_metrics"][model] = {
            "overall": overall,
            "per_domain": per_domain,
        }
        print(f"  {model}: nDCG@10 = {overall['nDCG@10']:.4f}")

    # --- Fusion optimization ---
    domain_qids = {}
    for q in queries:
        domain_qids.setdefault(q["domain"], []).append(q["id"])

    run_list = [runs[m] for m in config["models"]]

    for domain, qids in domain_qids.items():
        domain_results = {}

        # RRF variants
        for k in config["fusion"]["rrf_k_values"]:
            fused = reciprocal_rank_fusion(run_list, k=k)
            mean_ndcg = domain_ndcg10(qrels, fused, qids)
            domain_results[f"rrf_k{k}"] = round(mean_ndcg, 5)

        # CombSUM
        fused = comb_sum(run_list)
        domain_results["combsum"] = round(domain_ndcg10(qrels, fused, qids), 5)

        # CombMNZ
        fused = comb_mnz(run_list)
        domain_results["combmnz"] = round(domain_ndcg10(qrels, fused, qids), 5)

        # Weighted CombSUM — weights are per-domain baseline nDCG@10
        weights = [output["baseline_metrics"][m]["per_domain"][domain]["nDCG@10"]
                   for m in config["models"]]
        fused = weighted_comb_sum(run_list, weights)
        domain_results["weighted_combsum"] = round(domain_ndcg10(qrels, fused, qids), 5)

        best_method = max(domain_results, key=domain_results.get)
        output["fusion_optimization"][domain] = {
            "best_method": best_method,
            "best_ndcg10": domain_results[best_method],
            "all_methods": domain_results,
        }
        print(f"  {domain}: best = {best_method} "
              f"(nDCG@10 = {domain_results[best_method]:.4f})")

    # --- Apply optimized fusion ---
    combined_fused = {}
    for domain, qids in domain_qids.items():
        best = output["fusion_optimization"][domain]["best_method"]
        if best.startswith("rrf_k"):
            k = int(best.replace("rrf_k", ""))
            fused = reciprocal_rank_fusion(run_list, k=k)
        elif best == "combsum":
            fused = comb_sum(run_list)
        elif best == "combmnz":
            fused = comb_mnz(run_list)
        elif best == "weighted_combsum":
            weights = [output["baseline_metrics"][m]["per_domain"][domain]["nDCG@10"]
                       for m in config["models"]]
            fused = weighted_comb_sum(run_list, weights)
        else:
            raise ValueError(f"Unknown fusion method: {best}")

        for qid in qids:
            if qid in fused:
                combined_fused[qid] = fused[qid]

    output["optimized_fusion"] = {
        "overall": evaluate_run(qrels, combined_fused),
        "per_domain": evaluate_per_domain(qrels, combined_fused, queries),
    }

    # Write results
    with open(config["output_path"], "w") as f:
        json.dump(output, f, indent=2)

    print(f"Results written to {config['output_path']}")


if __name__ == "__main__":
    main()
