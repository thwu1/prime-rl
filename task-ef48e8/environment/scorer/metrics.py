"""
Metrics module for clinical evidence evaluation.

Computes precision/recall/F1 for evidence identification (strict and lenient)
and inter-annotator agreement.
"""
import numpy as np
from itertools import combinations


def compute_prf(predicted, gold):
    """Compute precision, recall, and F1 for two sets."""
    if len(predicted) == 0 and len(gold) == 0:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if len(predicted) == 0 or len(gold) == 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    tp = len(predicted & gold)
    p = tp / len(predicted)
    r = tp / len(gold)
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return {"precision": p, "recall": r, "f1": f1}


def compute_evidence_scores(submission, gold_map):
    """
    Compute strict and lenient evidence identification scores.

    Strict: predictions scored against essential-only gold evidence.
    Lenient: supplementary predictions are not penalized. Supplementary-only
    sentences are removed from the prediction set before scoring against
    the essential-only (strict) gold.

    Args:
        submission: list of dicts with "case_id" and "prediction" (list of sent IDs)
        gold_map: output of adjudicate_annotations

    Returns:
        dict with "strict" and "lenient" sub-dicts, each containing
        micro/macro metrics and per_case raw data for bootstrap.
    """
    strict_case_metrics = []
    lenient_case_metrics = []

    for case in submission:
        case_id = case["case_id"]
        predicted = set(case["prediction"])
        gold = gold_map[case_id]

        strict_gold = gold["strict_evidence"]
        lenient_gold = gold["lenient_evidence"]

        # Strict scoring: predictions vs essential-only gold
        strict_result = compute_prf(predicted, strict_gold)
        strict_tp = len(predicted & strict_gold)
        strict_case_metrics.append({
            "tp": strict_tp,
            "pred_count": len(predicted),
            "gold_count": len(strict_gold),
            **strict_result,
        })

        # Lenient scoring: evaluate predictions against the full evidence set
        lenient_result = compute_prf(predicted, lenient_gold)
        lenient_tp = len(predicted & lenient_gold)
        lenient_case_metrics.append({
            "tp": lenient_tp,
            "pred_count": len(predicted),
            "gold_count": len(lenient_gold),
            **lenient_result,
        })

    def aggregate(case_metrics):
        micro_tp = sum(m["tp"] for m in case_metrics)
        micro_pred = sum(m["pred_count"] for m in case_metrics)
        micro_gold = sum(m["gold_count"] for m in case_metrics)

        micro_p = micro_tp / micro_pred if micro_pred > 0 else 0.0
        micro_r = micro_tp / micro_gold if micro_gold > 0 else 0.0
        micro_f1 = (
            2 * micro_p * micro_r / (micro_p + micro_r)
            if (micro_p + micro_r) > 0
            else 0.0
        )

        return {
            "micro_precision": micro_p,
            "micro_recall": micro_r,
            "micro_f1": micro_f1,
            "macro_precision": float(np.mean([m["precision"] for m in case_metrics])),
            "macro_recall": float(np.mean([m["recall"] for m in case_metrics])),
            "macro_f1": float(np.mean([m["f1"] for m in case_metrics])),
            "per_case": case_metrics,
        }

    return {
        "strict": aggregate(strict_case_metrics),
        "lenient": aggregate(lenient_case_metrics),
    }


def compute_iaa(cases):
    """
    Compute inter-annotator agreement using averaged pairwise Cohen's kappa.

    Computes Cohen's kappa for each pair of annotators across all cases
    and returns the mean kappa value.

    Args:
        cases: list of case dicts with annotator data

    Returns:
        float: averaged pairwise Cohen's kappa
    """
    # Collect all annotator names across all cases
    ann_names = set()
    for case in cases:
        ann_names.update(case["annotators"].keys())
    ann_names = sorted(ann_names)

    if len(ann_names) < 2:
        return 0.0

    kappas = []
    for ann1, ann2 in combinations(ann_names, 2):
        labels1 = []
        labels2 = []

        for case in cases:
            annotators = case["annotators"]
            ann1_map = {
                item["sentence_id"]: item["relevance"]
                for item in annotators.get(ann1, [])
            }
            ann2_map = {
                item["sentence_id"]: item["relevance"]
                for item in annotators.get(ann2, [])
            }

            for sent in case["note_sentences"]:
                sid = sent["id"]
                l1 = ann1_map.get(sid)
                l2 = ann2_map.get(sid)
                if l1 is not None and l2 is not None:
                    labels1.append(l1)
                    labels2.append(l2)

        if labels1:
            kappa = _cohens_kappa(labels1, labels2)
            kappas.append(kappa)

    return float(sum(kappas) / len(kappas)) if kappas else 0.0


def _cohens_kappa(labels1, labels2):
    """Compute Cohen's kappa for two lists of categorical labels."""
    categories = sorted(set(labels1) | set(labels2))
    n = len(labels1)
    if n == 0:
        return 0.0

    # Build confusion matrix
    conf = {c1: {c2: 0 for c2 in categories} for c1 in categories}
    for l1, l2 in zip(labels1, labels2):
        conf[l1][l2] += 1

    # Observed agreement
    po = sum(conf[c][c] for c in categories) / n

    # Expected agreement (chance)
    pe = 0.0
    for c in categories:
        row_sum = sum(conf[c].values()) / n
        col_sum = sum(conf[r][c] for r in categories) / n
        pe += row_sum * col_sum

    if pe >= 1.0:
        return 1.0 if po >= 1.0 else 0.0

    return (po - pe) / (1 - pe)
