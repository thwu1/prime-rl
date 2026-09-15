#!/usr/bin/env python3

"""
BioASQ Evaluation Audit Solution

1. Implements correct evaluation metrics per spec.md
2. Identifies 3 bugs in the organizer's evaluator
3. Determines ranking impact of each bug
4. Performs bootstrap confidence interval analysis on rankings
5. Queries historical database for anomaly detection
6. Updates historical DB with round 4 data and analytical SQL views
"""

import json
import math
import os
import glob
import sqlite3
import statistics
import numpy as np

GOLDEN_PATH = "/app/data/golden.json"
SUBMISSIONS_DIR = "/app/data/submissions"
HISTORICAL_DB = "/app/data/historical.db"
BUGGY_OUTPUT = "/app/evaluator/output.json"
OUTPUT_PATH = "/app/audit.json"
EPSILON = 1e-5
Z_THRESHOLD = 2.0


def load_json(path):
    with open(path) as f:
        return json.load(f)


def question_index(questions):
    return {q["id"]: q for q in questions}


# ──────────────────────────────────────────────────────────────────────────────
# Correct evaluation implementation
# ──────────────────────────────────────────────────────────────────────────────

def modified_ap(submitted_docs, golden_docs):
    golden_set = set(golden_docs)
    n_relevant = len(golden_set)
    if n_relevant == 0:
        return 0.0
    denominator = min(n_relevant, 10)
    cumulative = 0
    ap_sum = 0.0
    for rank, doc in enumerate(submitted_docs[:10], start=1):
        if doc in golden_set:
            cumulative += 1
            ap_sum += cumulative / rank
    return ap_sum / denominator


def evaluate_document_retrieval(golden_qs, system_qs):
    gidx = question_index(golden_qs)
    sidx = question_index(system_qs)
    aps = []
    for qid in gidx:
        golden_docs = gidx[qid].get("documents", [])
        submitted_docs = sidx.get(qid, {}).get("documents", [])
        aps.append(modified_ap(submitted_docs, golden_docs))
    n = len(aps)
    map_score = sum(aps) / n if n > 0 else 0.0
    # FIX: use natural log, not log10
    log_sum = sum(math.log(max(ap, EPSILON)) for ap in aps)
    gmap = math.exp(log_sum / n) if n > 0 else 0.0
    return map_score, gmap


def evaluate_yesno(golden_qs, system_qs):
    gidx = question_index(golden_qs)
    sidx = question_index(system_qs)
    yesno_qs = {qid: gq for qid, gq in gidx.items() if gq["type"] == "yesno"}
    correct = 0
    total = 0
    tp = {"yes": 0, "no": 0}
    fp = {"yes": 0, "no": 0}
    fn = {"yes": 0, "no": 0}
    for qid, gq in yesno_qs.items():
        gold = gq["exact_answer"].strip().lower()
        sq = sidx.get(qid, {})
        pred_raw = sq.get("exact_answer", "")
        pred = pred_raw.strip().lower() if isinstance(pred_raw, str) else ""
        total += 1
        if pred == gold:
            correct += 1
            tp[gold] += 1
        else:
            if pred in ("yes", "no"):
                fp[pred] += 1
            fn[gold] += 1
    accuracy = correct / total if total > 0 else 0.0
    f1s = []
    for cls in ("yes", "no"):
        p = tp[cls] / (tp[cls] + fp[cls]) if (tp[cls] + fp[cls]) > 0 else 0.0
        r = tp[cls] / (tp[cls] + fn[cls]) if (tp[cls] + fn[cls]) > 0 else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        f1s.append(f1)
    macro_f1 = sum(f1s) / len(f1s)
    return accuracy, macro_f1


def factoid_match(candidate, golden_answer_groups):
    cand_lower = str(candidate).strip().lower()
    for group in golden_answer_groups:
        for synonym in group:
            if cand_lower == synonym.strip().lower():
                return True
    return False


def evaluate_factoid(golden_qs, system_qs):
    gidx = question_index(golden_qs)
    sidx = question_index(system_qs)
    factoid_qs = {qid: gq for qid, gq in gidx.items() if gq["type"] == "factoid"}
    strict_correct = 0
    lenient_correct = 0
    rr_sum = 0.0
    total = len(factoid_qs)
    for qid, gq in factoid_qs.items():
        golden_ea = gq["exact_answer"]
        sq = sidx.get(qid, {})
        candidates = sq.get("exact_answer", [])
        if not isinstance(candidates, list):
            candidates = [candidates]
        candidates = candidates[:5]
        if not candidates:
            # FIX: still count in denominator as 0 reciprocal rank
            continue
        if factoid_match(candidates[0], golden_ea):
            strict_correct += 1
        for i, cand in enumerate(candidates):
            if factoid_match(cand, golden_ea):
                lenient_correct += 1
                rr_sum += 1.0 / (i + 1)
                break
    strict_acc = strict_correct / total if total > 0 else 0.0
    lenient_acc = lenient_correct / total if total > 0 else 0.0
    # FIX: divide by total, not by answered
    mrr = rr_sum / total if total > 0 else 0.0
    return strict_acc, lenient_acc, mrr


def evaluate_list(golden_qs, system_qs):
    gidx = question_index(golden_qs)
    sidx = question_index(system_qs)
    list_qs = {qid: gq for qid, gq in gidx.items() if gq["type"] == "list"}
    precisions = []
    recalls = []
    f1s = []
    for qid, gq in list_qs.items():
        golden_items = gq["exact_answer"]
        sq = sidx.get(qid, {})
        submitted = sq.get("exact_answer", [])
        if not isinstance(submitted, list):
            submitted = [submitted]
        n_submitted = len(submitted)
        n_golden = len(golden_items)
        n_correct = 0
        for item in submitted:
            item_lower = str(item).strip().lower()
            for golden_group in golden_items:
                if any(item_lower == syn.strip().lower() for syn in golden_group):
                    n_correct += 1
                    break
        # FIX: check ALL synonyms, not just primary
        n_found = 0
        for golden_group in golden_items:
            syns_lower = {syn.strip().lower() for syn in golden_group}
            if any(str(s).strip().lower() in syns_lower for s in submitted):
                n_found += 1
        precision = n_correct / n_submitted if n_submitted > 0 else 0.0
        recall = n_found / n_golden if n_golden > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)
    mean_p = sum(precisions) / len(precisions) if precisions else 0.0
    mean_r = sum(recalls) / len(recalls) if recalls else 0.0
    mean_f1 = sum(f1s) / len(f1s) if f1s else 0.0
    return mean_p, mean_r, mean_f1


def compute_ranking(system_results):
    systems = list(system_results.keys())
    metric_keys = [("yesno", "macro_f1"), ("factoid", "mrr"), ("list", "mean_f1")]
    rank_sums = {s: 0.0 for s in systems}
    for category, metric in metric_keys:
        values = [(s, system_results[s][category][metric]) for s in systems]
        values.sort(key=lambda x: -x[1])
        i = 0
        while i < len(values):
            j = i
            while j < len(values) and abs(values[j][1] - values[i][1]) < 1e-10:
                j += 1
            avg_rank = sum(range(i + 1, j + 1)) / (j - i)
            for k in range(i, j):
                rank_sums[values[k][0]] += avg_rank
            i = j
    n_metrics = len(metric_keys)
    avg_ranks = {s: rank_sums[s] / n_metrics for s in systems}
    ranking = sorted(systems, key=lambda s: avg_ranks[s])
    return [{"rank": i + 1, "system": s, "avg_rank": avg_ranks[s]} for i, s in enumerate(ranking)]


# ──────────────────────────────────────────────────────────────────────────────
# Bootstrap confidence interval analysis
# ──────────────────────────────────────────────────────────────────────────────

def compute_bootstrap(golden_qs, submissions, B=1000, seed=42):
    """Question-level bootstrap resampling for ranking confidence intervals."""
    gidx = question_index(golden_qs)
    sub_indices = {name: question_index(sub["questions"])
                   for name, sub in submissions.items()}

    yesno_qids = sorted([qid for qid, q in gidx.items() if q["type"] == "yesno"])
    factoid_qids = sorted([qid for qid, q in gidx.items() if q["type"] == "factoid"])
    list_qids = sorted([qid for qid, q in gidx.items() if q["type"] == "list"])

    systems = sorted(submissions.keys())
    rng = np.random.default_rng(seed)

    rank_records = {s: [] for s in systems}

    for _ in range(B):
        yn_sample = rng.choice(yesno_qids, size=len(yesno_qids), replace=True).tolist()
        f_sample = rng.choice(factoid_qids, size=len(factoid_qids), replace=True).tolist()
        l_sample = rng.choice(list_qids, size=len(list_qids), replace=True).tolist()

        boot_metrics = {}
        for s in systems:
            sidx = sub_indices[s]

            # Yesno macro_F1: recompute per-class TP/FP/FN from resampled multiset
            tp = {"yes": 0, "no": 0}
            fp = {"yes": 0, "no": 0}
            fn = {"yes": 0, "no": 0}
            for qid in yn_sample:
                gq = gidx[qid]
                gold = gq["exact_answer"].strip().lower()
                sq = sidx.get(qid, {})
                pred_raw = sq.get("exact_answer", "")
                pred = pred_raw.strip().lower() if isinstance(pred_raw, str) else ""
                if pred == gold:
                    tp[gold] += 1
                else:
                    if pred in ("yes", "no"):
                        fp[pred] += 1
                    fn[gold] += 1
            f1s = []
            for cls in ("yes", "no"):
                p = tp[cls] / (tp[cls] + fp[cls]) if (tp[cls] + fp[cls]) > 0 else 0.0
                r = tp[cls] / (tp[cls] + fn[cls]) if (tp[cls] + fn[cls]) > 0 else 0.0
                f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
                f1s.append(f1)
            yn_f1 = sum(f1s) / len(f1s)

            # Factoid MRR from resampled questions
            rr_sum = 0.0
            total_f = len(f_sample)
            for qid in f_sample:
                gq = gidx[qid]
                golden_ea = gq["exact_answer"]
                sq = sidx.get(qid, {})
                candidates = sq.get("exact_answer", [])
                if not isinstance(candidates, list):
                    candidates = [candidates]
                candidates = candidates[:5]
                for i, cand in enumerate(candidates):
                    if factoid_match(cand, golden_ea):
                        rr_sum += 1.0 / (i + 1)
                        break
            f_mrr = rr_sum / total_f if total_f > 0 else 0.0

            # List mean_F1 from resampled questions
            l_f1s = []
            for qid in l_sample:
                gq = gidx[qid]
                golden_items = gq["exact_answer"]
                sq = sidx.get(qid, {})
                submitted = sq.get("exact_answer", [])
                if not isinstance(submitted, list):
                    submitted = [submitted]
                n_submitted = len(submitted)
                n_golden = len(golden_items)
                n_correct = 0
                for item in submitted:
                    item_lower = str(item).strip().lower()
                    for golden_group in golden_items:
                        if any(item_lower == syn.strip().lower() for syn in golden_group):
                            n_correct += 1
                            break
                n_found = 0
                for golden_group in golden_items:
                    syns_lower = {syn.strip().lower() for syn in golden_group}
                    if any(str(si).strip().lower() in syns_lower for si in submitted):
                        n_found += 1
                precision = n_correct / n_submitted if n_submitted > 0 else 0.0
                recall = n_found / n_golden if n_golden > 0 else 0.0
                f1_q = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
                l_f1s.append(f1_q)
            l_f1 = sum(l_f1s) / len(l_f1s) if l_f1s else 0.0

            boot_metrics[s] = {"yesno_macro_f1": yn_f1,
                               "factoid_mrr": f_mrr,
                               "list_mean_f1": l_f1}

        # Compute ranking from resampled metrics
        metric_keys_b = ["yesno_macro_f1", "factoid_mrr", "list_mean_f1"]
        rank_sums_b = {s: 0.0 for s in systems}
        for mk in metric_keys_b:
            values = [(s, boot_metrics[s][mk]) for s in systems]
            values.sort(key=lambda x: -x[1])
            i = 0
            while i < len(values):
                j = i
                while j < len(values) and abs(values[j][1] - values[i][1]) < 1e-10:
                    j += 1
                avg_r = sum(range(i + 1, j + 1)) / (j - i)
                for k in range(i, j):
                    rank_sums_b[values[k][0]] += avg_r
                i = j
        avg_ranks = {s: rank_sums_b[s] / 3 for s in systems}
        ranked = sorted(systems, key=lambda s: avg_ranks[s])

        # Assign final ranks with ties
        i = 0
        while i < len(ranked):
            j = i
            while j < len(ranked) and abs(avg_ranks[ranked[j]] - avg_ranks[ranked[i]]) < 1e-10:
                j += 1
            tied_rank = sum(range(i + 1, j + 1)) / (j - i)
            for k in range(i, j):
                rank_records[ranked[k]].append(tied_rank)
            i = j

    result = {}
    for s in systems:
        ranks = np.array(rank_records[s])
        result[s] = {
            "rank_ci_lower": float(np.percentile(ranks, 2.5)),
            "rank_ci_upper": float(np.percentile(ranks, 97.5)),
            "prob_rank_1": float(np.mean(ranks == 1.0)),
        }
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Historical anomaly detection
# ──────────────────────────────────────────────────────────────────────────────

def detect_anomalies(corrected_systems):
    conn = sqlite3.connect(HISTORICAL_DB)
    c = conn.cursor()

    # Use only original rounds (1-3) for computing historical stats
    c.execute("""
        SELECT DISTINCT s.system_name FROM systems s
        JOIN results r ON s.system_id = r.system_id
        WHERE r.round_id <= 3
    """)
    historical_systems = {row[0] for row in c.fetchall()}

    ranking_metrics = ["yesno_macro_f1", "factoid_mrr", "list_mean_f1"]
    metric_map = {
        "yesno_macro_f1": ("yesno", "macro_f1"),
        "factoid_mrr": ("factoid", "mrr"),
        "list_mean_f1": ("list", "mean_f1"),
    }

    anomalies = []
    for sys_name in corrected_systems:
        if sys_name not in historical_systems:
            continue
        for metric_name in ranking_metrics:
            c.execute("""
                SELECT r.metric_value FROM results r
                JOIN systems s ON r.system_id = s.system_id
                WHERE s.system_name = ? AND r.metric_name = ?
                AND r.round_id <= 3
                ORDER BY r.round_id
            """, (sys_name, metric_name))
            hist_values = [row[0] for row in c.fetchall()]
            if len(hist_values) < 2:
                continue
            hist_mean = statistics.mean(hist_values)
            hist_std = statistics.stdev(hist_values)
            if hist_std < 1e-10:
                continue
            cat, met = metric_map[metric_name]
            current_val = corrected_systems[sys_name][cat][met]
            z_score = (current_val - hist_mean) / hist_std
            if abs(z_score) > Z_THRESHOLD:
                anomalies.append({
                    "system": sys_name,
                    "metric": metric_name,
                    "current_value": round(current_val, 6),
                    "historical_mean": round(hist_mean, 6),
                    "z_score": round(z_score, 4),
                })

    conn.close()
    return anomalies


# ──────────────────────────────────────────────────────────────────────────────
# Historical DB update
# ──────────────────────────────────────────────────────────────────────────────

def update_historical_db(system_results):
    """Insert round 4 data and create analytical SQL views."""
    conn = sqlite3.connect(HISTORICAL_DB)
    c = conn.cursor()

    # Insert round 4
    c.execute("INSERT OR IGNORE INTO rounds VALUES (4, 'BioASQ Round 4')")

    # Get max existing system_id
    c.execute("SELECT MAX(system_id) FROM systems")
    max_id = c.fetchone()[0] or 0

    # Register all systems (add delta/epsilon if not present)
    for sys_name in sorted(system_results.keys()):
        c.execute("SELECT system_id FROM systems WHERE system_name = ?", (sys_name,))
        row = c.fetchone()
        if row is None:
            max_id += 1
            c.execute("INSERT INTO systems VALUES (?, ?)", (max_id, sys_name))

    # Insert round 4 results for all systems
    metric_map = {
        "yesno_macro_f1": ("yesno", "macro_f1"),
        "factoid_mrr": ("factoid", "mrr"),
        "list_mean_f1": ("list", "mean_f1"),
        "map": ("document_retrieval", "map"),
        "gmap": ("document_retrieval", "gmap"),
    }

    for sys_name in system_results:
        c.execute("SELECT system_id FROM systems WHERE system_name = ?", (sys_name,))
        sys_id = c.fetchone()[0]
        for metric_name, (cat, met) in metric_map.items():
            value = system_results[sys_name][cat][met]
            c.execute(
                "INSERT OR REPLACE INTO results VALUES (4, ?, ?, ?)",
                (sys_id, metric_name, value)
            )

    # Create v_metric_trends view with LAG window function
    c.execute("DROP VIEW IF EXISTS v_metric_trends")
    c.execute("""
        CREATE VIEW v_metric_trends AS
        SELECT
            s.system_name,
            r.round_id,
            r.round_name,
            res.metric_name,
            res.metric_value,
            LAG(res.metric_value) OVER (
                PARTITION BY s.system_name, res.metric_name
                ORDER BY r.round_id
            ) AS prev_value,
            res.metric_value - LAG(res.metric_value) OVER (
                PARTITION BY s.system_name, res.metric_name
                ORDER BY r.round_id
            ) AS delta
        FROM results res
        JOIN systems s ON res.system_id = s.system_id
        JOIN rounds r ON res.round_id = r.round_id
    """)

    # Create v_current_anomalies view with CTE-based sample std
    c.execute("DROP VIEW IF EXISTS v_current_anomalies")
    c.execute("""
        CREATE VIEW v_current_anomalies AS
        WITH max_round AS (
            SELECT MAX(round_id) AS rid FROM rounds
        ),
        hist AS (
            SELECT
                res.system_id,
                res.metric_name,
                AVG(res.metric_value) AS hist_mean,
                COUNT(res.metric_value) AS n,
                CASE
                    WHEN COUNT(res.metric_value) > 1 THEN
                        SQRT(
                            (SUM(res.metric_value * res.metric_value)
                             - SUM(res.metric_value) * SUM(res.metric_value)
                               / COUNT(res.metric_value))
                            / (COUNT(res.metric_value) - 1)
                        )
                    ELSE NULL
                END AS hist_std
            FROM results res, max_round m
            WHERE res.round_id < m.rid
            GROUP BY res.system_id, res.metric_name
        ),
        curr AS (
            SELECT res.system_id, res.metric_name,
                   res.metric_value AS current_value
            FROM results res, max_round m
            WHERE res.round_id = m.rid
        )
        SELECT
            s.system_name,
            c.metric_name,
            c.current_value,
            h.hist_mean,
            h.hist_std,
            CASE
                WHEN h.hist_std IS NOT NULL AND h.hist_std > 1e-10 THEN
                    (c.current_value - h.hist_mean) / h.hist_std
                ELSE NULL
            END AS z_score
        FROM curr c
        JOIN hist h ON c.system_id = h.system_id
                   AND c.metric_name = h.metric_name
        JOIN systems s ON c.system_id = s.system_id
        WHERE h.hist_std IS NOT NULL AND h.hist_std > 1e-10
    """)

    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    golden = load_json(GOLDEN_PATH)
    golden_qs = golden["questions"]

    submission_files = sorted(glob.glob(os.path.join(SUBMISSIONS_DIR, "system_*.json")))
    submissions = {}
    for path in submission_files:
        data = load_json(path)
        name = data.get("system_name",
                        os.path.basename(path).replace(".json", "").replace("system_", ""))
        submissions[name] = data

    # Compute corrected results
    system_results = {}
    for sys_name, sub_data in submissions.items():
        sys_qs = sub_data["questions"]
        map_score, gmap = evaluate_document_retrieval(golden_qs, sys_qs)
        accuracy, macro_f1 = evaluate_yesno(golden_qs, sys_qs)
        strict_acc, lenient_acc, mrr = evaluate_factoid(golden_qs, sys_qs)
        mean_p, mean_r, mean_f1 = evaluate_list(golden_qs, sys_qs)
        system_results[sys_name] = {
            "document_retrieval": {"map": map_score, "gmap": gmap},
            "yesno": {"accuracy": accuracy, "macro_f1": macro_f1},
            "factoid": {"strict_accuracy": strict_acc, "lenient_accuracy": lenient_acc,
                        "mrr": mrr},
            "list": {"mean_precision": mean_p, "mean_recall": mean_r, "mean_f1": mean_f1},
        }

    ranking = compute_ranking(system_results)

    # Identify bugs
    bugs = [
        {
            "id": "BUG-1",
            "description": "GMAP computation uses math.log10 (base-10 logarithm) instead "
                           "of math.log (natural logarithm). The specification defines GMAP "
                           "using the natural logarithm: GMAP = exp(mean(ln(AP'))). Using "
                           "log10 produces incorrect GMAP values.",
            "affected_metric": "gmap",
            "ranking_impact": False,
        },
        {
            "id": "BUG-2",
            "description": "Factoid MRR denominator only counts questions the system "
                           "answered, instead of all factoid questions. When a system "
                           "submits an empty candidate list, the buggy code skips it "
                           "entirely. The spec says MRR denominator is the total number "
                           "of factoid questions regardless of how many were answered.",
            "affected_metric": "factoid_mrr",
            "ranking_impact": True,
        },
        {
            "id": "BUG-3",
            "description": "List recall computation only checks the first synonym in "
                           "each golden item's synonym group, instead of checking all "
                           "synonyms. This penalizes systems that use alternative "
                           "nomenclature. The spec says a golden item is found if a "
                           "submitted item matches ANY of its synonyms.",
            "affected_metric": "list_mean_recall / list_mean_f1",
            "ranking_impact": True,
        },
    ]

    # Historical anomalies (computed BEFORE inserting round 4)
    anomalies = detect_anomalies(system_results)

    # Bootstrap confidence intervals
    bootstrap_analysis = compute_bootstrap(golden_qs, submissions)

    # Update historical DB with round 4 and create views
    update_historical_db(system_results)

    # Build audit report
    audit = {
        "corrected_results": system_results,
        "corrected_ranking": ranking,
        "bugs": bugs,
        "bootstrap_analysis": bootstrap_analysis,
        "historical_anomalies": anomalies,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(audit, f, indent=2)

    print(f"Audit complete. Report written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
