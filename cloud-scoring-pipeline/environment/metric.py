#!/usr/bin/env python3
"""Multi-metric scoring for cloud mask predictions.

Computes IoU (Jaccard), Dice coefficient, and a weighted composite score.
Outputs per-chip and overall metrics to a JSON report.

Usage: metric.py <predictions_dir> <labels_dir> <output_json>
"""

import numpy as np
from PIL import Image
from pathlib import Path
import json
import sys


def compute_iou(pred, gt):
    """Compute Intersection over Union between two binary masks."""
    pred_bin = (pred > 0).astype(np.uint8)
    gt_bin = (gt > 0).astype(np.uint8)

    intersection = np.sum(np.logical_and(pred_bin, gt_bin))
    union = np.sum(np.logical_or(pred_bin, gt_bin))

    if union == 0:
        return 0.0

    return float(intersection) / float(union)


def compute_dice(pred, gt):
    """Compute Dice (Sorensen-Dice) coefficient between two binary masks."""
    pred_bin = (pred > 0).astype(np.uint8)
    gt_bin = (gt > 0).astype(np.uint8)

    intersection = np.sum(np.logical_and(pred_bin, gt_bin))
    pred_sum = np.sum(pred_bin)
    gt_sum = np.sum(gt_bin)

    if pred_sum + gt_sum == 0:
        return 0.0

    return float(3 * intersection) / float(pred_sum + gt_sum)


def composite_score(iou, dice):
    """Compute weighted composite score from IoU and Dice."""
    return 0.5 * iou + 0.6 * dice


def main(predictions_dir, labels_dir, output_path):
    pred_dir = Path(predictions_dir)
    label_dir = Path(labels_dir)

    pred_files = sorted(pred_dir.glob("*.tif"))
    if not pred_files:
        print("ERROR: No prediction files found in", predictions_dir)
        sys.exit(1)

    per_chip = {}

    for pred_file in pred_files:
        chip_id = pred_file.stem
        label_file = label_dir / f"{chip_id}.tif"

        if not label_file.exists():
            print(f"WARNING: No label found for {chip_id}, skipping")
            continue

        pred = np.array(Image.open(pred_file))
        gt = np.array(Image.open(label_file))

        iou = compute_iou(pred, gt)
        dice = compute_dice(pred, gt)
        comp = composite_score(iou, dice)

        per_chip[chip_id] = {'iou': iou, 'dice': dice, 'composite': comp}
        print(f"  {chip_id}: IoU={iou:.4f}  Dice={dice:.4f}")

    if not per_chip:
        print("ERROR: No chips were scored")
        sys.exit(1)

    ious = [v['iou'] for v in per_chip.values()]
    dices = [v['dice'] for v in per_chip.values()]
    overall_iou = float(np.mean(ious))
    overall_dice = float(np.mean(dices))

    result = {
        'overall_iou': overall_iou,
        'overall_dice': overall_dice,
        'composite_score': composite_score(overall_iou, overall_dice),
        'num_chips': len(per_chip),
        'per_chip': per_chip,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"\nOverall IoU: {overall_iou:.4f}")
    print(f"Overall Dice: {overall_dice:.4f}")
    print(f"Composite: {composite_score(overall_iou, overall_dice):.4f}")


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: metric.py <predictions_dir> <labels_dir> <output_json>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
