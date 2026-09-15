#!/usr/bin/env python3
"""
IDRiD Evaluation Framework — evaluate.py (FIXED)
Scores predictions against ground truth for retinal imaging sub-challenges.

Fixes applied:
1. Segmentation: Added anchor point (recall=0, precision=1) to PR curve
2. Grading: combined_accuracy = fraction where BOTH grades correct (not average)
3. Localization: Euclidean distance (not Manhattan)

"""

import argparse
import csv
import json
import math
import os
import sys

import numpy as np
from PIL import Image


LESION_TYPES = ["MA", "HE", "SE", "EX"]
NUM_THRESHOLDS = 33
THRESHOLDS = [i / 32.0 for i in range(NUM_THRESHOLDS)]


def parse_args():
    parser = argparse.ArgumentParser(description="IDRiD Evaluation Framework")
    parser.add_argument("--task", required=True,
                        choices=["lesion_segmentation", "disease_grading", "localization"],
                        help="Sub-challenge task to evaluate")
    parser.add_argument("--predictions", required=True,
                        help="Path to predictions (directory for segmentation, CSV for grading/localization)")
    parser.add_argument("--ground-truth", required=True,
                        help="Path to ground truth (directory for segmentation, CSV for grading/localization)")
    parser.add_argument("--output-json", default="/app/results.json",
                        help="Path to output JSON file")
    return parser.parse_args()


def load_grayscale_image(path):
    img = Image.open(path).convert("L")
    return np.array(img, dtype=np.float32) / 255.0


def load_binary_mask(path):
    img = Image.open(path).convert("L")
    arr = np.array(img, dtype=np.float32)
    return arr > 127


def evaluate_lesion_segmentation(pred_dir, gt_dir):
    gt_files = {}
    for fname in os.listdir(gt_dir):
        if not fname.endswith(".png"):
            continue
        parts = fname.rsplit("_", 1)
        if len(parts) != 2:
            continue
        image_id = parts[0]
        lesion = parts[1].replace(".png", "")
        if lesion in LESION_TYPES:
            gt_files.setdefault(lesion, {})[image_id] = os.path.join(gt_dir, fname)

    pred_files = {}
    if os.path.isdir(pred_dir):
        for fname in os.listdir(pred_dir):
            if not fname.endswith(".png"):
                continue
            parts = fname.rsplit("_", 1)
            if len(parts) != 2:
                continue
            image_id = parts[0]
            lesion = parts[1].replace(".png", "")
            if lesion in LESION_TYPES:
                pred_files.setdefault(lesion, {})[image_id] = os.path.join(pred_dir, fname)

    for lesion in LESION_TYPES:
        for img_id in pred_files.get(lesion, {}):
            if img_id not in gt_files.get(lesion, {}):
                print(f"Error: prediction image ID '{img_id}' for lesion '{lesion}' "
                      f"not found in ground truth", file=sys.stderr)
                sys.exit(1)

    results = {}
    auprs = []

    for lesion in LESION_TYPES:
        gt_lesion = gt_files.get(lesion, {})
        pred_lesion = pred_files.get(lesion, {})

        if not gt_lesion:
            results[f"{lesion}_AUPR"] = 0.0
            auprs.append(0.0)
            continue

        all_gt_masks = {}
        total_gt_positive = 0
        for img_id, gt_path in gt_lesion.items():
            mask = load_binary_mask(gt_path)
            all_gt_masks[img_id] = mask
            total_gt_positive += mask.sum()

        if total_gt_positive == 0:
            results[f"{lesion}_AUPR"] = 0.0
            auprs.append(0.0)
            continue

        all_pred_imgs = {}
        for img_id in gt_lesion:
            if img_id in pred_lesion:
                all_pred_imgs[img_id] = load_grayscale_image(pred_lesion[img_id])
            else:
                shape = all_gt_masks[img_id].shape
                all_pred_imgs[img_id] = np.zeros(shape, dtype=np.float32)

        precisions = []
        recalls = []

        for threshold in THRESHOLDS:
            global_tp = 0
            global_fp = 0
            global_fn = 0

            for img_id in gt_lesion:
                gt_mask = all_gt_masks[img_id]
                pred_img = all_pred_imgs[img_id]

                if pred_img.shape != gt_mask.shape:
                    pred_pil = Image.fromarray((pred_img * 255).astype(np.uint8))
                    pred_pil = pred_pil.resize(
                        (gt_mask.shape[1], gt_mask.shape[0]), Image.NEAREST)
                    pred_img = np.array(pred_pil, dtype=np.float32) / 255.0

                pred_binary = pred_img >= threshold
                tp = np.sum(pred_binary & gt_mask)
                fp = np.sum(pred_binary & ~gt_mask)
                fn = np.sum(~pred_binary & gt_mask)

                global_tp += tp
                global_fp += fp
                global_fn += fn

            if global_tp + global_fp == 0:
                precision = 1.0
            else:
                precision = global_tp / (global_tp + global_fp)

            if global_tp + global_fn == 0:
                recall = 0.0
            else:
                recall = global_tp / (global_tp + global_fn)

            precisions.append(precision)
            recalls.append(recall)

        # FIX: Add anchor point at (recall=0, precision=1)
        recalls.insert(0, 0.0)
        precisions.insert(0, 1.0)

        pr_pairs = list(zip(recalls, precisions))
        pr_pairs.sort(key=lambda x: x[0])
        sorted_recalls = [p[0] for p in pr_pairs]
        sorted_precisions = [p[1] for p in pr_pairs]

        for idx in range(len(sorted_precisions) - 2, -1, -1):
            sorted_precisions[idx] = max(sorted_precisions[idx],
                                         sorted_precisions[idx + 1])

        aupr = float(np.trapz(sorted_precisions, sorted_recalls))
        aupr = max(0.0, min(1.0, aupr))
        results[f"{lesion}_AUPR"] = aupr
        auprs.append(aupr)

    results["mean_AUPR"] = float(np.mean(auprs))
    return results


def evaluate_disease_grading(pred_csv, gt_csv):
    gt_data = {}
    with open(gt_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gt_data[row["image_id"]] = {
                "DR_grade": int(row["DR_grade"]),
                "DME_grade": int(row["DME_grade"]),
            }

    pred_data = {}
    with open(pred_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            img_id = row["image_id"]
            if img_id not in gt_data:
                print(f"Error: prediction image ID '{img_id}' not found in ground truth",
                      file=sys.stderr)
                sys.exit(1)
            pred_data[img_id] = {
                "DR_grade": int(row["DR_grade"]),
                "DME_grade": int(row["DME_grade"]),
            }

    n = len(gt_data)
    dr_correct = 0
    dme_correct = 0
    combined_correct = 0

    for img_id, gt in gt_data.items():
        if img_id in pred_data:
            pred = pred_data[img_id]
            dr_ok = pred["DR_grade"] == gt["DR_grade"]
            dme_ok = pred["DME_grade"] == gt["DME_grade"]
        else:
            dr_ok = False
            dme_ok = False

        if dr_ok:
            dr_correct += 1
        if dme_ok:
            dme_correct += 1
        # FIX: combined = both correct simultaneously, not average
        if dr_ok and dme_ok:
            combined_correct += 1

    return {
        "DR_accuracy": dr_correct / n,
        "DME_accuracy": dme_correct / n,
        "combined_accuracy": combined_correct / n,
    }


def evaluate_localization(pred_csv, gt_csv):
    gt_data = {}
    with open(gt_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gt_data[row["image_id"]] = {
                "OD_x": float(row["OD_x"]),
                "OD_y": float(row["OD_y"]),
                "fovea_x": float(row["fovea_x"]),
                "fovea_y": float(row["fovea_y"]),
            }

    pred_data = {}
    with open(pred_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            img_id = row["image_id"]
            if img_id not in gt_data:
                print(f"Error: prediction image ID '{img_id}' not found in ground truth",
                      file=sys.stderr)
                sys.exit(1)
            pred_data[img_id] = {
                "OD_x": float(row["OD_x"]),
                "OD_y": float(row["OD_y"]),
                "fovea_x": float(row["fovea_x"]),
                "fovea_y": float(row["fovea_y"]),
            }

    od_dists = []
    fovea_dists = []

    for img_id, gt in gt_data.items():
        if img_id in pred_data:
            pred = pred_data[img_id]
            # FIX: Euclidean distance, not Manhattan
            od_dist = math.sqrt(
                (pred["OD_x"] - gt["OD_x"]) ** 2 +
                (pred["OD_y"] - gt["OD_y"]) ** 2
            )
            fovea_dist = math.sqrt(
                (pred["fovea_x"] - gt["fovea_x"]) ** 2 +
                (pred["fovea_y"] - gt["fovea_y"]) ** 2
            )
        else:
            od_dist = math.sqrt(gt["OD_x"] ** 2 + gt["OD_y"] ** 2)
            fovea_dist = math.sqrt(gt["fovea_x"] ** 2 + gt["fovea_y"] ** 2)

        od_dists.append(od_dist)
        fovea_dists.append(fovea_dist)

    return {
        "OD_mean_euclidean": float(np.mean(od_dists)) if od_dists else 0.0,
        "fovea_mean_euclidean": float(np.mean(fovea_dists)) if fovea_dists else 0.0,
    }


def main():
    args = parse_args()

    if args.task == "lesion_segmentation":
        results = evaluate_lesion_segmentation(args.predictions, args.ground_truth)
    elif args.task == "disease_grading":
        results = evaluate_disease_grading(args.predictions, args.ground_truth)
    elif args.task == "localization":
        results = evaluate_localization(args.predictions, args.ground_truth)
    else:
        print(f"Error: unknown task '{args.task}'", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.output_json)), exist_ok=True)
    with open(args.output_json, "w") as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
