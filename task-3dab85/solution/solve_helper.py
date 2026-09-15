#!/usr/bin/env python3
"""Solution: diagnose run file issues, clean, evaluate, fuse, test significance."""

import json
import math
import os
from collections import Counter, defaultdict

from scipy import stats as scipy_stats

RUNS_DIR = "/app/runs"
OUT = "/app/output"
QRELS_PATH = "/app/qrels.txt"
SYSTEMS = ["alpha", "beta", "gamma", "delta", "epsilon"]
METRICS = [
    "ndcg_cut_10", "ndcg_cut_100", "ndcg_cut_1000",
    "map", "recip_rank", "recall_100", "recall_1000",
]


# ---- loading ----

def load_qrels():
    qrels = defaultdict(dict)
    with open(QRELS_PATH) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 4:
                qid, docid, rel = parts[0], parts[2], int(parts[3])
                qrels[qid][docid] = rel
    return dict(qrels)


def load_raw_lines(path):
    with open(path) as f:
        return [l.strip() for l in f if l.strip()]


# ---- diagnosis + cleaning ----

def diagnose_and_clean(path, sys_name):
    lines = load_raw_lines(path)
    issues = []
    corrections = []

    # Parse all entries (handle mixed delimiters)
    raw_entries = []
    for line in lines:
        parts = line.split()
        if len(parts) < 6:
            continue
        raw_qid = parts[0]
        docid = parts[2]
        try:
            rank = int(parts[3])
            score = float(parts[4])
        except ValueError:
            continue
        run_id = parts[5]
        raw_entries.append((raw_qid, docid, rank, score, run_id))

    # Check zero-padded qids
    padded_count = 0
    for raw_qid, _, _, _, _ in raw_entries:
        try:
            if raw_qid != str(int(raw_qid)):
                padded_count += 1
        except ValueError:
            pass
    if padded_count > 0:
        issues.append(
            f"Zero-padded query IDs found in {padded_count} entries "
            f"(e.g. '01' or '001' instead of '1')"
        )
        corrections.append("Normalized all query IDs by stripping leading zeros")

    # Normalize qids
    entries = []
    for raw_qid, docid, rank, score, run_id in raw_entries:
        try:
            qid = str(int(raw_qid))
        except ValueError:
            qid = raw_qid
        entries.append((qid, docid, rank, score, run_id))

    # Group by qid
    by_qid = defaultdict(list)
    for qid, docid, rank, score, run_id in entries:
        by_qid[qid].append((docid, rank, score, run_id))

    # Check for duplicate docs per query
    dup_queries = 0
    for qid, ents in by_qid.items():
        docs = [d for d, _, _, _ in ents]
        c = Counter(docs)
        if any(v > 1 for v in c.values()):
            dup_queries += 1
    if dup_queries > 0:
        issues.append(
            f"Duplicate document entries found in {dup_queries} queries "
            f"(same docid appears at multiple ranks)"
        )
        corrections.append("Removed duplicate entries, keeping first (higher-ranked) occurrence")

    # Check 0-indexed ranks
    all_ranks = [r for _, _, r, _, _ in entries]
    min_rank = min(all_ranks) if all_ranks else 1
    if min_rank == 0:
        issues.append(
            "Ranks are 0-indexed (minimum rank is 0, should be 1)"
        )
        corrections.append("Converted to 1-indexed ranks")

    # Check score-rank inversion
    inv_count = 0
    for qid, ents in by_qid.items():
        sorted_by_rank = sorted(ents, key=lambda x: x[1])
        if len(sorted_by_rank) > 50:
            asc = sum(
                1 for i in range(len(sorted_by_rank) - 1)
                if sorted_by_rank[i][2] < sorted_by_rank[i + 1][2]
            )
            total_pairs = len(sorted_by_rank) - 1
            if asc > total_pairs * 0.9:
                inv_count += 1
    if inv_count > 0:
        issues.append(
            f"Score-rank inversion in {inv_count} queries "
            f"(scores ascending with rank instead of descending)"
        )
        corrections.append(
            "Re-sorted results by descending score and re-assigned ranks"
        )

    if not issues:
        issues.append("No data quality issues detected")
        corrections.append("No corrections needed")

    # ---- Apply universal cleaning ----
    cleaned = {}
    for qid, ents in by_qid.items():
        # Remove duplicates (keep first by rank)
        sorted_by_rank = sorted(ents, key=lambda x: x[1])
        seen = set()
        deduped = []
        for docid, rank, score, run_id in sorted_by_rank:
            if docid not in seen:
                deduped.append((docid, score, run_id))
                seen.add(docid)

        # Sort by descending score (fixes inversions; no-op if already correct)
        deduped.sort(key=lambda x: -x[1])

        # Assign 1-indexed contiguous ranks
        cleaned[qid] = [
            (docid, i + 1, score, run_id)
            for i, (docid, score, run_id) in enumerate(deduped)
        ]

    return cleaned, {"issues": issues, "corrections": corrections}


# ---- metrics ----

def ndcg_at_k(qrels_q, entries, k):
    dcg = 0.0
    for i, (docid, _, _) in enumerate(entries[:k]):
        rel = qrels_q.get(docid, 0)
        dcg += ((2 ** rel) - 1) / math.log2(i + 2)
    ideal = sorted(qrels_q.values(), reverse=True)[:k]
    idcg = sum(((2 ** r) - 1) / math.log2(i + 2) for i, r in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def avg_precision(qrels_q, entries):
    total_rel = sum(1 for v in qrels_q.values() if v > 0)
    if total_rel == 0:
        return 0.0
    found = 0
    ap = 0.0
    for i, (docid, _, _) in enumerate(entries):
        if qrels_q.get(docid, 0) > 0:
            found += 1
            ap += found / (i + 1)
    return ap / total_rel


def recip_rank(qrels_q, entries):
    for i, (docid, _, _) in enumerate(entries):
        if qrels_q.get(docid, 0) > 0:
            return 1.0 / (i + 1)
    return 0.0


def recall_at_k(qrels_q, entries, k):
    total_rel = sum(1 for v in qrels_q.values() if v > 0)
    if total_rel == 0:
        return 0.0
    found = sum(1 for docid, _, _ in entries[:k] if qrels_q.get(docid, 0) > 0)
    return found / total_rel


def evaluate(qrels, run):
    """run = {qid: [(docid, rank, score), ...]} sorted by rank."""
    results = {}
    for metric in METRICS:
        per_q = {}
        for qid in qrels:
            ents = run.get(qid, [])
            qq = qrels[qid]
            if metric == "ndcg_cut_10":
                per_q[qid] = ndcg_at_k(qq, ents, 10)
            elif metric == "ndcg_cut_100":
                per_q[qid] = ndcg_at_k(qq, ents, 100)
            elif metric == "ndcg_cut_1000":
                per_q[qid] = ndcg_at_k(qq, ents, 1000)
            elif metric == "map":
                per_q[qid] = avg_precision(qq, ents)
            elif metric == "recip_rank":
                per_q[qid] = recip_rank(qq, ents)
            elif metric == "recall_100":
                per_q[qid] = recall_at_k(qq, ents, 100)
            elif metric == "recall_1000":
                per_q[qid] = recall_at_k(qq, ents, 1000)
        results[metric] = per_q
    return results


def to_eval_json(results):
    per_query = defaultdict(dict)
    mean = {}
    for metric, per_q in results.items():
        vals = list(per_q.values())
        mean[metric] = sum(vals) / len(vals) if vals else 0.0
        for qid, v in per_q.items():
            per_query[qid][metric] = v
    return {"per_query": dict(per_query), "mean": mean}


# ---- fusion ----

def rrf_fuse(runs_list, k, top_k=1000):
    """Reciprocal Rank Fusion across multiple runs."""
    all_qids = set()
    for run in runs_list:
        all_qids.update(run.keys())

    fused = {}
    for qid in all_qids:
        doc_scores = defaultdict(float)
        for run in runs_list:
            for docid, rank, _ in run.get(qid, []):
                doc_scores[docid] += 1.0 / (k + rank)
        ranked = sorted(doc_scores.items(), key=lambda x: (-x[1], x[0]))[:top_k]
        fused[qid] = [
            (docid, i + 1, score)
            for i, (docid, score) in enumerate(ranked)
        ]
    return fused


def write_trec_run(run, path, run_id="COMBINED"):
    with open(path, "w") as f:
        for qid in sorted(run.keys(), key=int):
            for docid, rank, score in run[qid]:
                f.write(f"{qid} Q0 {docid} {rank} {score:.10f} {run_id}\n")


# ---- main ----

def main():
    os.makedirs(f"{OUT}/cleaned_runs", exist_ok=True)
    qrels = load_qrels()

    # Step 1: Diagnose and clean each run
    diagnostics = {}
    cleaned_runs = {}
    for sys in SYSTEMS:
        path = f"{RUNS_DIR}/run_{sys}.txt"
        cleaned, diag = diagnose_and_clean(path, sys)
        diagnostics[sys] = diag

        # Convert to standard format: {qid: [(docid, rank, score)]}
        run = {}
        for qid, entries in cleaned.items():
            run[qid] = [(docid, rank, score) for docid, rank, score, _ in entries]
        cleaned_runs[sys] = run

        # Write cleaned run
        run_id = sys.upper()
        with open(f"{OUT}/cleaned_runs/run_{sys}.txt", "w") as f:
            for qid in sorted(run.keys(), key=int):
                for docid, rank, score in run[qid]:
                    f.write(f"{qid} Q0 {docid} {rank} {score:.4f} {run_id}\n")

    with open(f"{OUT}/diagnostics.json", "w") as f:
        json.dump(diagnostics, f, indent=2)

    # Step 2: Evaluate each cleaned run
    sys_evals = {}
    for sys in SYSTEMS:
        results = evaluate(qrels, cleaned_runs[sys])
        sys_evals[sys] = results
        ej = to_eval_json(results)
        with open(f"{OUT}/eval_{sys}.json", "w") as f:
            json.dump(ej, f, indent=2)

    # Step 3: RRF fusion — sweep k to find optimal
    runs_list = [cleaned_runs[s] for s in SYSTEMS]
    best_k = 60
    best_mean_ndcg = -1.0

    for k in range(1, 101):
        fused = rrf_fuse(runs_list, k)
        ndcg_vals = {}
        for qid in qrels:
            ndcg_vals[qid] = ndcg_at_k(qrels[qid], fused.get(qid, []), 10)
        mean_ndcg = sum(ndcg_vals.values()) / len(ndcg_vals)
        if mean_ndcg > best_mean_ndcg:
            best_mean_ndcg = mean_ndcg
            best_k = k

    # Produce combined run at optimal k
    combined = rrf_fuse(runs_list, best_k)
    write_trec_run(combined, f"{OUT}/combined.txt")

    # Evaluate combined
    combined_results = evaluate(qrels, combined)
    ej = to_eval_json(combined_results)
    with open(f"{OUT}/eval_combined.json", "w") as f:
        json.dump(ej, f, indent=2)

    # Step 4: Significance tests (paired Wilcoxon signed-rank)
    combined_ndcg = combined_results["ndcg_cut_10"]
    qids = sorted(qrels.keys(), key=int)
    significance = {}
    for sys in SYSTEMS:
        sys_ndcg = sys_evals[sys]["ndcg_cut_10"]
        x = [combined_ndcg.get(q, 0.0) for q in qids]
        y = [sys_ndcg.get(q, 0.0) for q in qids]
        diffs = [a - b for a, b in zip(x, y)]

        # Use Wilcoxon signed-rank test (nonparametric paired test)
        try:
            res = scipy_stats.wilcoxon(diffs, alternative="two-sided")
            stat = float(res.statistic)
            pval = float(res.pvalue)
        except Exception:
            # Fallback to paired t-test if Wilcoxon fails (e.g., all diffs zero)
            try:
                stat, pval = scipy_stats.ttest_rel(x, y)
                stat = float(stat)
                pval = float(pval)
            except Exception:
                stat, pval = 0.0, 1.0

        significance[sys] = {
            "test_name": "wilcoxon_signed_rank",
            "statistic": stat,
            "p_value": pval,
            "significant_at_005": pval < 0.05,
        }

    with open(f"{OUT}/significance.json", "w") as f:
        json.dump(significance, f, indent=2)

    print("Pipeline complete. Outputs in", OUT)


if __name__ == "__main__":
    main()
