#!/usr/bin/env python3
"""Compute weighted Cohen's kappa combined with per-class recall.

The final score is the geometric mean of Cohen's kappa and
class-weighted recall, providing a balanced measure of both
overall agreement and per-class classification quality.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PREDICTION_DIR = Path("/app/output/predictions")
LABEL_DIR = Path("/app/data/labels")
N_CLASSES = 4
CLASS_WEIGHTS = {0: 0.15, 1: 0.30, 2: 0.25, 3: 0.30}
MIN_SCORE = 0.80


def build_confusion_matrix(y_true, y_pred, n_classes):
    """Build N x N confusion matrix."""
    cm = np.zeros((n_classes, n_classes), dtype=np.int64)
    for t, p in zip(y_true.ravel(), y_pred.ravel()):
        if 0 <= t < n_classes and 0 <= p < n_classes:
            cm[int(t), int(p)] += 1
    return cm


def compute_score(cm, weights):
    """Compute geometric mean of Cohen's kappa and weighted recall."""
    n = cm.sum()
    if n == 0:
        return 0.0

    p_o = float(np.diag(cm).sum()) / n
    row_sums = cm.sum(axis=1).astype(float)
    col_sums = cm.sum(axis=0).astype(float)
    p_e = float((row_sums * col_sums).sum()) / (n * n)

    kappa = (p_o - p_e) / p_e

    per_class_recall = np.zeros(cm.shape[0])
    for i in range(cm.shape[0]):
        if row_sums[i] > 0:
            per_class_recall[i] = float(cm[i, i]) / row_sums[i]

    weighted_recall = sum(
        weights.get(i, 0.0) * per_class_recall[i]
        for i in range(cm.shape[0])
    )

    if kappa > 0 and weighted_recall > 0:
        score = float(np.sqrt(kappa * weighted_recall))
    else:
        score = 0.0

    return score


def main():
    if not LABEL_DIR.exists():
        print("ERROR: Ground truth labels not found at {}".format(LABEL_DIR))
        sys.exit(1)

    label_files = sorted(LABEL_DIR.glob("*.tif"))
    if not label_files:
        print("ERROR: No label files found in {}".format(LABEL_DIR))
        sys.exit(1)

    all_true = []
    all_pred = []

    for label_file in label_files:
        chip_id = label_file.stem
        pred_file = PREDICTION_DIR / "{}.tif".format(chip_id)

        if not pred_file.exists():
            print("  MISSING prediction for {}".format(chip_id))
            continue

        truth = np.array(Image.open(label_file))
        pred = np.array(Image.open(pred_file))
        all_true.append(truth.ravel())
        all_pred.append(pred.ravel())

    if not all_true:
        print("ERROR: No matching prediction/label pairs")
        sys.exit(1)

    y_true = np.concatenate(all_true)
    y_pred = np.concatenate(all_pred)

    cm = build_confusion_matrix(y_true, y_pred, N_CLASSES)
    score = compute_score(cm, CLASS_WEIGHTS)

    print("\nConfusion Matrix:")
    for i in range(N_CLASSES):
        print("  {}".format(cm[i]))

    print("\nCombined Score: {:.4f}".format(score))
    print("Threshold: {:.2f}".format(MIN_SCORE))

    if score >= MIN_SCORE:
        print("RESULT: PASS")
    else:
        print("RESULT: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
