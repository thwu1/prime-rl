#!/usr/bin/env python3

"""
BioASQ Task B Evaluation Pipeline
Computes evaluation metrics for biomedical question answering systems.
"""

import json
import math
import os
import glob

GOLDEN_PATH = "/app/data/golden.json"
SUBMISSIONS_DIR = "/app/data/submissions"
OUTPUT_PATH = "/app/evaluator/output.json"
EPSILON = 1e-5


def load_json(path):
    with open(path) as f:
        return json.load(f)


def question_index(questions):
    return {q["id"]: q for q in questions}


# ──────────────────────────────────────────────────────────────────────────────
# Document Retrieval
# ──────────────────────────────────────────────────────────────────────────────

def modified_ap(submitted_docs, golden_docs):
    """BioASQ-modified Average Precision."""
    golden_set = set(golden_docs)
    n_relevant = len(golden_set)
    if n_relevant == 0:
        return 0.0

    denominator = min(n_relevant, 10)
    cumulative_relevant = 0
    ap_sum = 0.0

    for rank, doc in enumerate(submitted_docs[:10], start=1):
        if doc in golden_set:
            cumulative_relevant += 1
            ap_sum += cumulative_relevant / rank

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

    # GMAP with epsilon for zero values
    log_sum = sum(math.log10(max(ap, EPSILON)) for ap in aps)
    gmap = math.exp(log_sum / n) if n > 0 else 0.0

    return map_score, gmap


# ──────────────────────────────────────────────────────────────────────────────
# Yes/No Evaluation
# ──────────────────────────────────────────────────────────────────────────────

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

    f1_per_class = []
    for cls in ("yes", "no"):
        p = tp[cls] / (tp[cls] + fp[cls]) if (tp[cls] + fp[cls]) > 0 else 0.0
        r = tp[cls] / (tp[cls] + fn[cls]) if (tp[cls] + fn[cls]) > 0 else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        f1_per_class.append(f1)

    macro_f1 = sum(f1_per_class) / len(f1_per_class)

    return accuracy, macro_f1


# ──────────────────────────────────────────────────────────────────────────────
# Factoid Evaluation
# ──────────────────────────────────────────────────────────────────────────────

def factoid_match(candidate, golden_answer_groups):
    """Case-insensitive exact match against any synonym in any answer group."""
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
    answered = 0

    for qid, gq in factoid_qs.items():
        golden_ea = gq["exact_answer"]
        sq = sidx.get(qid, {})
        candidates = sq.get("exact_answer", [])
        if not isinstance(candidates, list):
            candidates = [candidates]
        candidates = candidates[:5]

        if not candidates:
            continue

        answered += 1

        if candidates and factoid_match(candidates[0], golden_ea):
            strict_correct += 1

        for i, cand in enumerate(candidates):
            if factoid_match(cand, golden_ea):
                lenient_correct += 1
                rr_sum += 1.0 / (i + 1)
                break

    strict_acc = strict_correct / total if total > 0 else 0.0
    lenient_acc = lenient_correct / total if total > 0 else 0.0
    mrr = rr_sum / answered if answered > 0 else 0.0

    return strict_acc, lenient_acc, mrr


# ──────────────────────────────────────────────────────────────────────────────
# List Evaluation
# ──────────────────────────────────────────────────────────────────────────────

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

        # Count correct submitted items
        n_correct = 0
        for item in submitted:
            item_lower = str(item).strip().lower()
            for golden_group in golden_items:
                if any(item_lower == syn.strip().lower() for syn in golden_group):
                    n_correct += 1
                    break

        # Count found golden items
        n_found = 0
        for golden_group in golden_items:
            primary_synonym = golden_group[0].strip().lower()
            if any(str(s).strip().lower() == primary_synonym for s in submitted):
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


# ──────────────────────────────────────────────────────────────────────────────
# Ranking
# ──────────────────────────────────────────────────────────────────────────────

def compute_ranking(system_results):
    """Rank systems by average rank across yn F1, factoid MRR, list F1."""
    systems = list(system_results.keys())
    metric_keys = [
        ("yesno", "macro_f1"),
        ("factoid", "mrr"),
        ("list", "mean_f1"),
    ]

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
    return [
        {"rank": i + 1, "system": s, "avg_rank": avg_ranks[s]}
        for i, s in enumerate(ranking)
    ]


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
        name = data.get(
            "system_name",
            os.path.basename(path).replace(".json", "").replace("system_", ""),
        )
        submissions[name] = data

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
            "factoid": {
                "strict_accuracy": strict_acc,
                "lenient_accuracy": lenient_acc,
                "mrr": mrr,
            },
            "list": {
                "mean_precision": mean_p,
                "mean_recall": mean_r,
                "mean_f1": mean_f1,
            },
        }

    ranking = compute_ranking(system_results)
    output = {"systems": system_results, "ranking": ranking}

    os.makedirs(os.path.dirname(OUTPUT_PATH) or ".", exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Evaluation complete. Results written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
