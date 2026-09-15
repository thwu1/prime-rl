#!/usr/bin/env python3
"""Solution: forensic audit of search evaluation pipeline with advanced analyses."""

import json
import math
import os
import subprocess
import shutil
from collections import defaultdict

MAX_GRADE = 3
K_CUTOFF = 10
SYSTEMS = ["bm25", "tfidf", "embedding", "sparse", "hybrid"]


# ---------------------------------------------------------------------------
# Core data loading (corrected implementations)
# ---------------------------------------------------------------------------

def load_qrels_correct(path):
    """Load qrels taking MAX grade for duplicate query-doc pairs."""
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
            qrels[qid][docid] = max(qrels[qid].get(docid, -1), grade)
    return qrels


def find_duplicate_qrels(path):
    """Find query-doc pairs appearing with conflicting grades."""
    seen = {}
    duplicates = set()
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            qid = parts[0]
            docid = parts[2]
            grade = int(parts[3])
            key = (qid, docid)
            if key in seen and seen[key] != grade:
                duplicates.add(key)
            seen[key] = grade
    return sorted(duplicates)


def count_invalid_clicks(path):
    """Count click entries with position <= 0."""
    count = 0
    with open(path) as f:
        f.readline()
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 4:
                continue
            pos = int(parts[2])
            if pos <= 0:
                count += 1
    return count


def load_run(path):
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


# ---------------------------------------------------------------------------
# Correct metric implementations
# ---------------------------------------------------------------------------

def compute_ndcg(qrels_q, ranked, k=K_CUTOFF):
    dcg = 0.0
    for i in range(min(k, len(ranked))):
        g = qrels_q.get(ranked[i][0], 0)
        dcg += (2 ** g - 1) / math.log2(i + 2)
    grades = sorted(qrels_q.values(), reverse=True)
    idcg = 0.0
    for i in range(min(k, len(grades))):
        idcg += (2 ** grades[i] - 1) / math.log2(i + 2)
    return dcg / idcg if idcg > 0 else 0.0


def compute_err(qrels_q, ranked, k=K_CUTOFF):
    val = 0.0
    p = 1.0
    for r in range(min(k, len(ranked))):
        g = qrels_q.get(ranked[r][0], 0)
        R = (2 ** g - 1) / (2 ** MAX_GRADE)
        val += (1.0 / (r + 1)) * p * R
        p *= (1 - R)
    return val


def compute_map(qrels_q, ranked, k=K_CUTOFF, threshold=1):
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
    return s / R


def mean_metric(qrels, run, fn):
    vals = []
    for qid in sorted(qrels):
        r = run.get(qid, [])
        vals.append(fn(qrels[qid], r))
    return sum(vals) / len(vals) if vals else 0.0


def mean_metric_category(qrels, run, fn, query_cats, category):
    vals = []
    for qid in sorted(qrels):
        if query_cats.get(qid) != category:
            continue
        r = run.get(qid, [])
        vals.append(fn(qrels[qid], r))
    return sum(vals) / len(vals) if vals else 0.0


def per_query_metric(qrels, run, fn):
    result = {}
    for qid in sorted(qrels):
        r = run.get(qid, [])
        result[qid] = fn(qrels[qid], r)
    return result


def rrf_fuse(runs_dict, k_param):
    fused = {}
    for sys_name in sorted(runs_dict):
        run = runs_dict[sys_name]
        for qid in run:
            fused.setdefault(qid, {})
            for docid, rank, _ in run[qid]:
                fused[qid][docid] = fused[qid].get(docid, 0.0) + 1.0 / (k_param + rank)
    result = {}
    for qid in fused:
        docs = sorted(fused[qid].items(), key=lambda x: (-x[1], x[0]))
        result[qid] = [(d, i + 1, s) for i, (d, s) in enumerate(docs)]
    return result


# ---------------------------------------------------------------------------
# Expert analysis: position-bias click model
# ---------------------------------------------------------------------------

def analyze_click_model(click_path):
    """Fit power-law position-bias model to click data."""
    pos_clicks = defaultdict(int)
    pos_imps = defaultdict(int)
    with open(click_path) as f:
        f.readline()
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 4:
                continue
            pos = int(parts[2])
            clicked = int(parts[3])
            if pos <= 0:
                continue
            pos_imps[pos] += 1
            pos_clicks[pos] += clicked
    ctr = {}
    for p in sorted(pos_imps):
        ctr[p] = pos_clicks[p] / pos_imps[p] if pos_imps[p] > 0 else 0.0

    # Fit power law via log-log OLS: log(CTR) = log(a) - b*log(p)
    xs = []
    ys = []
    for p, c in sorted(ctr.items()):
        if c > 0:
            xs.append(math.log(p))
            ys.append(math.log(c))
    if len(xs) < 2:
        return 0.0, 0.0
    n = len(xs)
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    y_mean = sy / n
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r_sq = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    exponent = -slope
    return exponent, r_sq


# ---------------------------------------------------------------------------
# Expert analysis: inter-metric concordance
# ---------------------------------------------------------------------------

def kendall_tau_a(values1, values2, keys):
    """Kendall tau-a between two orderings of items."""
    n = len(keys)
    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            a, b = keys[i], keys[j]
            d1 = values1[a] - values1[b]
            d2 = values2[a] - values2[b]
            prod = d1 * d2
            if prod > 0:
                concordant += 1
            elif prod < 0:
                discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total > 0 else 0.0


# ---------------------------------------------------------------------------
# Pipeline bug analysis
# ---------------------------------------------------------------------------

def analyze_pipeline_bugs():
    bugs = []
    bugs.append({
        "function_name": "load_qrels",
        "description": (
            "Overwrites grade for duplicate query-doc pairs instead of "
            "taking the maximum grade as specified by data conventions"
        )
    })
    bugs.append({
        "function_name": "compute_ndcg",
        "description": (
            "IDCG computation uses unsorted grade list instead of sorting "
            "grades in descending order, producing incorrect normalization"
        )
    })
    bugs.append({
        "function_name": "compute_err",
        "description": (
            "Uses MAX_GRADE=4 but actual relevance grades range 0-3; "
            "satisfaction probabilities R_i = (2^g - 1) / 2^MAX_GRADE "
            "are computed with wrong denominator"
        )
    })
    bugs.append({
        "function_name": "compute_map",
        "description": (
            "Divides accumulated precision by cutoff k instead of total "
            "number of relevant documents R"
        )
    })
    return bugs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Step 1: Loading and deduplicating data...")
    qrels = load_qrels_correct("/app/data/qrels.txt")
    runs = {}
    for sn in SYSTEMS:
        runs[sn] = load_run(f"/app/data/{sn}.run")
    with open("/app/data/query_taxonomy.json") as f:
        query_cats = json.load(f)

    print("Step 2: Running trec_eval for reference comparison...")
    trec_eval_path = shutil.which("trec_eval")
    if trec_eval_path:
        for sn in SYSTEMS:
            result = subprocess.run(
                [trec_eval_path, "-m", "ndcg_cut.10", "-m", "map_cut.10",
                 "/app/data/qrels.txt", f"/app/data/{sn}.run"],
                capture_output=True, text=True
            )
            print(f"  trec_eval {sn}:")
            for line in result.stdout.strip().split("\n"):
                print(f"    {line}")

    print("Step 3: Analyzing pipeline bugs...")
    bugs = analyze_pipeline_bugs()
    for bug in bugs:
        print(f"  Found bug in {bug['function_name']}: {bug['description']}")

    print("Step 4: Finding data quality issues...")
    duplicates = find_duplicate_qrels("/app/data/qrels.txt")
    invalid_clicks = count_invalid_clicks("/app/data/clicks.tsv")
    print(f"  Duplicate qrels: {len(duplicates)} pairs")
    print(f"  Invalid click entries: {invalid_clicks}")

    print("Step 5: Computing corrected metrics...")
    corrected = {}
    for sn in SYSTEMS:
        corrected[sn] = {
            "ndcg@10": round(mean_metric(qrels, runs[sn], compute_ndcg), 6),
            "err@10": round(mean_metric(qrels, runs[sn], compute_err), 6),
            "map@10": round(mean_metric(qrels, runs[sn], compute_map), 6),
        }
        print(f"  {sn}: {corrected[sn]}")

    print("Step 6: Computing per-category best systems...")
    categories = sorted(set(query_cats.values()))
    category_best = {}
    for cat in categories:
        best_sys = None
        best_ndcg = -1.0
        for sn in SYSTEMS:
            ndcg = mean_metric_category(qrels, runs[sn], compute_ndcg, query_cats, cat)
            if ndcg > best_ndcg:
                best_ndcg = ndcg
                best_sys = sn
        category_best[cat] = best_sys
        print(f"  {cat}: {best_sys} (nDCG@10={best_ndcg:.6f})")

    print("Step 7: Optimizing RRF fusion (k=1..100)...")
    best_k, best_ndcg_fused = 1, -1.0
    for k in range(1, 101):
        fused = rrf_fuse(runs, k)
        n = mean_metric(qrels, fused, compute_ndcg)
        if n > best_ndcg_fused:
            best_ndcg_fused = n
            best_k = k
    print(f"  Optimal k={best_k}, nDCG@10={best_ndcg_fused:.6f}")

    print("Step 8: Fitting position-bias click model...")
    exponent, r_squared = analyze_click_model("/app/data/clicks.tsv")
    print(f"  Power-law exponent b={exponent:.4f}, R²={r_squared:.4f}")

    print("Step 9: Computing inter-metric concordance...")
    ndcg_vals = {s: corrected[s]["ndcg@10"] for s in SYSTEMS}
    err_vals = {s: corrected[s]["err@10"] for s in SYSTEMS}
    map_vals = {s: corrected[s]["map@10"] for s in SYSTEMS}
    keys = sorted(SYSTEMS)
    tau_ne = kendall_tau_a(ndcg_vals, err_vals, keys)
    tau_nm = kendall_tau_a(ndcg_vals, map_vals, keys)
    tau_em = kendall_tau_a(err_vals, map_vals, keys)
    print(f"  nDCG-ERR tau={tau_ne:.4f}, nDCG-MAP tau={tau_nm:.4f}, ERR-MAP tau={tau_em:.4f}")

    print("Step 10: Computing oracle per-query system selection...")
    pq = {}
    for sn in SYSTEMS:
        pq[sn] = per_query_metric(qrels, runs[sn], compute_ndcg)
    best_single_sys = None
    best_single_ndcg = -1.0
    for sn in SYSTEMS:
        n = mean_metric(qrels, runs[sn], compute_ndcg)
        if n > best_single_ndcg:
            best_single_ndcg = n
            best_single_sys = sn
    oracle_vals = []
    for qid in sorted(qrels):
        oracle_vals.append(max(pq[sn][qid] for sn in SYSTEMS))
    oracle_ndcg = sum(oracle_vals) / len(oracle_vals) if oracle_vals else 0.0
    improvement_pct = (oracle_ndcg - best_single_ndcg) / best_single_ndcg * 100.0 \
        if best_single_ndcg > 0 else 0.0
    print(f"  Best single: {best_single_sys} (nDCG={best_single_ndcg:.6f})")
    print(f"  Oracle nDCG={oracle_ndcg:.6f}, improvement={improvement_pct:.2f}%")

    report = {
        "pipeline_bugs": bugs,
        "data_issues": {
            "duplicate_qrels": [[q, d] for q, d in duplicates],
            "invalid_click_count": invalid_clicks,
        },
        "corrected_metrics": corrected,
        "category_best_system": category_best,
        "fusion": {
            "optimal_k": best_k,
            "fused_ndcg@10": round(best_ndcg_fused, 6),
        },
        "click_model": {
            "power_law_exponent": round(exponent, 6),
            "r_squared": round(r_squared, 6),
        },
        "metric_concordance": {
            "ndcg_err_tau": round(tau_ne, 6),
            "ndcg_map_tau": round(tau_nm, 6),
            "err_map_tau": round(tau_em, 6),
        },
        "oracle_analysis": {
            "best_single_system": best_single_sys,
            "best_single_ndcg": round(best_single_ndcg, 6),
            "oracle_ndcg": round(oracle_ndcg, 6),
            "oracle_improvement_pct": round(improvement_pct, 4),
        }
    }

    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("\nAudit report written to /app/audit_report.json")


if __name__ == "__main__":
    main()
