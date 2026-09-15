"""
Pipeline module for evidence-answer alignment scoring.

Computes standard (unweighted) and weighted alignment precision/recall/F1.
"""
import numpy as np


def compute_alignment_scores(submission, gold_map):
    """
    Compute standard (unweighted) alignment P/R/F1.

    Each alignment pair is (answer_sentence_id, evidence_sentence_id).
    Standard scoring treats all correct alignment pairs equally.

    Args:
        submission: list of dicts with "case_id" and "prediction"
        gold_map: dict from build_alignment_gold()

    Returns:
        dict with micro/macro precision, recall, f1
    """
    case_metrics = []

    for case in submission:
        case_id = case["case_id"]
        gold_aligns = gold_map[case_id]["alignments"]

        predicted_aligns = set()
        for alignment in case["prediction"]:
            answer_id = alignment["answer_id"]
            for evidence_id in alignment["evidence_id"]:
                predicted_aligns.add((answer_id, evidence_id))

        tp = len(predicted_aligns & gold_aligns)
        p = tp / len(predicted_aligns) if predicted_aligns else 0.0
        r = tp / len(gold_aligns) if gold_aligns else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0

        case_metrics.append({
            "tp": tp,
            "pred_count": len(predicted_aligns),
            "gold_count": len(gold_aligns),
            "precision": p,
            "recall": r,
            "f1": f1,
        })

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
    }


def compute_weighted_alignment_scores(submission, gold_map, evidence_gold_map):
    """
    Compute weighted alignment P/R/F1 using evidence relevance tiers.

    Each gold alignment pair (answer_id, evidence_id) receives a weight
    based on the adjudicated relevance of the evidence sentence:
    - essential: weight 1.0
    - supplementary: weight 0.5

    Weighted precision = sum(weights of correct predictions) / |predicted pairs|
    Weighted recall = sum(weights of correct predictions) / sum(gold weights)

    Args:
        submission: list of dicts with "case_id" and "prediction"
        gold_map: dict from build_alignment_gold()
        evidence_gold_map: dict from adjudicate_annotations()

    Returns:
        dict with micro/macro weighted precision, recall, f1
    """
    # TODO: Not yet implemented
    return {
        "micro_precision": 0.0,
        "micro_recall": 0.0,
        "micro_f1": 0.0,
        "macro_precision": 0.0,
        "macro_recall": 0.0,
        "macro_f1": 0.0,
    }
