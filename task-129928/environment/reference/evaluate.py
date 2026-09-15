#!/usr/bin/env python3
"""
PhysioNet Challenge 2026 — Model Evaluation Script

Evaluates a submitted model's predictions against the challenge cohort.

This script is provided as a reference for the official evaluation pipeline.
Participants should study this code to understand the expected output format
and the metrics being computed.

Output JSON structure:
{
    "cohort_summary": {
        "group_1": <int>,
        "group_2": <int>,
        "group_3": <int>
    },
    "overall_metrics": {
        "auroc": <float>,
        "auprc": <float>,
        "accuracy": <float>,
        "f1": <float>,
        "challenge_score_005": <float>,
        "challenge_score_020": <float>
    },
    "confidence_intervals": {
        "auroc": {"lower": <float>, "upper": <float>},
        "auprc": {"lower": <float>, "upper": <float>},
        "accuracy": {"lower": <float>, "upper": <float>},
        "f1": {"lower": <float>, "upper": <float>}
    },
    "site_metrics": {
        "<site_code>": {
            "n_group1": <int>,
            "n_group2": <int>,
            "auroc": <float>
        },
        ...
    }
}

Bootstrap confidence intervals:
    - 1000 iterations, seed 42, alpha 0.05 (95% CI)
    - Stratified by site: each bootstrap sample draws independently
      within each site to preserve site composition
    - Metrics: AUROC, AUPRC, accuracy, F1
    - Report 2.5th and 97.5th percentiles
    - Skip bootstrap samples where only one class is present

Site metrics:
    - Report per-site AUROC for all sites with scored patients
    - Include n_group1 and n_group2 counts per site
"""

import sys
import json
import numpy as np
import os

sys.path.insert(0, os.path.dirname(__file__))
from scoring import compute_challenge_score, compute_auc, compute_accuracy, compute_f_measure


def load_cohort(cohort_file):
    """Load cohort group assignments from CSV."""
    import csv
    groups = {}
    with open(cohort_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row['BDSPPatientID'].strip()
            groups[pid] = int(row['Group'])
    return groups


def load_predictions(predictions_file):
    """Load model predictions from CSV."""
    import csv
    preds = {}
    with open(predictions_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row['BDSPPatientID'].strip()
            preds[pid] = {
                'binary': int(row['Cognitive_Impairment']),
                'probability': float(row['Cognitive_Impairment_Probability']),
            }
    return preds


def evaluate_model(groups, predictions):
    """
    Evaluate model predictions using the official Challenge metrics.

    Only patients in Group 1 (positive) and Group 2 (negative) are scored.
    Group 3 patients are excluded from all metric calculations.
    """
    scored_pids = sorted([pid for pid, g in groups.items() if g in (1, 2)])

    if not scored_pids:
        raise ValueError("No scored patients found")

    labels = np.array([1 if groups[pid] == 1 else 0 for pid in scored_pids])
    probs = np.array([predictions[pid]['probability'] for pid in scored_pids])
    binary = np.array([predictions[pid]['binary'] for pid in scored_pids])

    auroc, auprc = compute_auc(labels, probs)
    accuracy = compute_accuracy(labels, binary)
    f1 = compute_f_measure(labels, binary)

    challenge_score_005 = compute_challenge_score(
        labels, probs, fraction_capacity=0.05
    )
    challenge_score_020 = compute_challenge_score(
        labels, probs, fraction_capacity=0.20
    )

    return {
        'auroc': float(auroc),
        'auprc': float(auprc),
        'accuracy': float(accuracy),
        'f1': float(f1),
        'challenge_score_005': float(challenge_score_005),
        'challenge_score_020': float(challenge_score_020),
    }


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <cohort_csv> <predictions_csv> <output_json>")
        sys.exit(1)

    cohort_file, predictions_file, output_file = sys.argv[1], sys.argv[2], sys.argv[3]
    groups = load_cohort(cohort_file)
    predictions = load_predictions(predictions_file)
    scores = evaluate_model(groups, predictions)

    with open(output_file, 'w') as f:
        json.dump(scores, f, indent=2)

    print("Evaluation complete:")
    for k, v in sorted(scores.items()):
        print(f"  {k}: {v:.6f}")
