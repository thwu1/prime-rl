#!/usr/bin/env python3
"""Compute IoU (Intersection over Union) metric for cloud cover predictions."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PREDICTION_DIR = Path("/app/predictions")
LABEL_DIR = Path("/app/data/test_labels")


def compute_iou(prediction, ground_truth):
    """Compute IoU between two binary masks."""
    pred = prediction.astype(bool)
    truth = ground_truth.astype(bool)

    intersection = np.logical_and(pred, truth).sum()
    sum_pred = pred.sum()
    sum_truth = truth.sum()

    if sum_pred + sum_truth == 0:
        return 1.0  # Both empty masks => perfect agreement

    iou = intersection / (sum_pred + sum_truth + intersection)
    return float(iou)


def main():
    label_files = sorted(LABEL_DIR.glob("*.tif"))
    if not label_files:
        print("ERROR: No ground truth labels found in", LABEL_DIR)
        sys.exit(1)

    chip_scores = []

    for label_file in label_files:
        chip_id = label_file.stem
        pred_file = PREDICTION_DIR / "{}.tif".format(chip_id)

        if not pred_file.exists():
            print("  MISSING: {}".format(chip_id))
            chip_scores.append(0.0)
            continue

        pred = np.array(Image.open(pred_file))
        truth = np.array(Image.open(label_file))

        iou = compute_iou(pred, truth)
        chip_scores.append(iou)
        print("  {}: IoU = {:.4f}".format(chip_id, iou))

    if not chip_scores:
        print("ERROR: No predictions found")
        sys.exit(1)

    mean_iou = np.mean(chip_scores)
    print("\nMean IoU: {:.4f}".format(mean_iou))

    if mean_iou >= 0.70:
        print("RESULT: PASS (IoU >= 0.70)")
    else:
        print("RESULT: FAIL (IoU < 0.70)")
        sys.exit(1)


if __name__ == "__main__":
    main()
