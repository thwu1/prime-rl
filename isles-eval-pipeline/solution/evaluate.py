#!/usr/bin/env python3

"""
ISLES-compatible segmentation evaluation pipeline.

Computes Dice, absolute volume difference, average symmetric surface distance,
95th percentile Hausdorff distance, lesion-wise F1, panoptic quality, and
instance count difference for paired NIfTI ground truth and prediction masks.
"""

import argparse
import json
import os
import sys

import nibabel as nib
import numpy as np
from scipy.ndimage import binary_erosion, generate_binary_structure
from scipy.ndimage import label as scipy_label
from scipy.spatial.distance import cdist


# ──────────────────────────────────────────────────────────────
# Voxel-level metrics
# ──────────────────────────────────────────────────────────────

def binarize(img):
    """Binarize a NIfTI image: values > 0.5 are positive."""
    data = img.get_fdata(dtype=np.float64)
    return (data > 0.5).astype(np.uint8)


def compute_dice(gt, pred):
    """Binary Dice similarity coefficient."""
    gt_bool = gt.astype(bool)
    pred_bool = pred.astype(bool)
    sum_gt = gt_bool.sum()
    sum_pred = pred_bool.sum()
    if sum_gt == 0 and sum_pred == 0:
        return 1.0
    intersection = np.logical_and(gt_bool, pred_bool).sum()
    return float(2.0 * intersection / (sum_gt + sum_pred))


def compute_voxel_volume_ml(affine):
    """Compute single-voxel volume in mL from the NIfTI affine matrix.

    Uses |det(M)| where M is the 3x3 upper-left submatrix, then
    converts mm^3 to mL by dividing by 1000.
    """
    M = affine[:3, :3]
    vol_mm3 = abs(np.linalg.det(M))
    return vol_mm3 / 1000.0


def compute_avd_ml(gt, pred, voxel_volume_ml):
    """Absolute volume difference in milliliters."""
    gt_vol = float(gt.astype(bool).sum()) * voxel_volume_ml
    pred_vol = float(pred.astype(bool).sum()) * voxel_volume_ml
    return abs(gt_vol - pred_vol)


# ──────────────────────────────────────────────────────────────
# Surface-distance metrics
# ──────────────────────────────────────────────────────────────

def extract_surface(mask):
    """Extract surface voxels (face-connected boundary) of a binary mask.

    A surface voxel is a positive voxel with at least one face-adjacent
    neighbor that is non-positive or outside the image bounds.
    """
    struct = generate_binary_structure(3, 1)  # 6-connected (face only)
    eroded = binary_erosion(mask.astype(bool), structure=struct, border_value=0)
    return mask.astype(bool) & ~eroded


def compute_surface_distances(gt, pred, affine):
    """Compute ASSD and HD95 in physical millimeters.

    Returns (assd, hd95). Returns (0, 0) if both masks are empty,
    (-1, -1) if exactly one mask is empty.
    """
    gt_sum = gt.astype(bool).sum()
    pred_sum = pred.astype(bool).sum()

    if gt_sum == 0 and pred_sum == 0:
        return 0.0, 0.0
    if gt_sum == 0 or pred_sum == 0:
        return -1.0, -1.0

    gt_surface = extract_surface(gt)
    pred_surface = extract_surface(pred)

    # Get voxel indices of surface voxels
    gt_coords = np.argwhere(gt_surface).astype(np.float64)   # Nx3
    pred_coords = np.argwhere(pred_surface).astype(np.float64)  # Mx3

    # Transform to physical coordinates using the full affine
    M = affine[:3, :3]
    t = affine[:3, 3]
    gt_phys = (M @ gt_coords.T).T + t      # Nx3
    pred_phys = (M @ pred_coords.T).T + t   # Mx3

    # Pairwise Euclidean distances in physical space
    D = cdist(gt_phys, pred_phys, metric='euclidean')

    gt_to_pred = D.min(axis=1)    # min dist for each GT surface voxel
    pred_to_gt = D.min(axis=0)    # min dist for each Pred surface voxel

    all_dists = np.concatenate([gt_to_pred, pred_to_gt])
    assd = float(all_dists.mean())
    hd95 = float(np.percentile(all_dists, 95))

    return assd, hd95


# ──────────────────────────────────────────────────────────────
# Instance-level metrics
# ──────────────────────────────────────────────────────────────

def get_instances(mask):
    """Label connected components using face-connectivity (6-connected 3D)."""
    labeled, num = scipy_label(mask.astype(bool))
    return labeled, int(num)


def compute_iou(mask_a, mask_b):
    """Intersection over Union of two binary masks."""
    intersection = np.logical_and(mask_a, mask_b).sum()
    union = np.logical_or(mask_a, mask_b).sum()
    if union == 0:
        return 0.0
    return float(intersection / union)


def compute_instance_metrics(gt, pred, iou_threshold=0.2):
    """Compute lesion-wise F1, panoptic quality, and instance count difference."""
    gt_labeled, num_gt = get_instances(gt)
    pred_labeled, num_pred = get_instances(pred)

    icd = abs(num_pred - num_gt)

    # Both empty
    if num_gt == 0 and num_pred == 0:
        return {
            "lesion_f1": 1.0,
            "panoptic_quality": 1.0,
            "instance_count_diff": 0,
            "num_gt_instances": 0,
            "num_pred_instances": 0,
        }

    # One side empty
    if num_gt == 0 or num_pred == 0:
        return {
            "lesion_f1": 0.0,
            "panoptic_quality": 0.0,
            "instance_count_diff": icd,
            "num_gt_instances": num_gt,
            "num_pred_instances": num_pred,
        }

    # Build IoU matrix
    iou_matrix = np.zeros((num_gt, num_pred), dtype=np.float64)
    for i in range(num_gt):
        gt_mask_i = (gt_labeled == (i + 1))
        for j in range(num_pred):
            pred_mask_j = (pred_labeled == (j + 1))
            iou_matrix[i, j] = compute_iou(gt_mask_i, pred_mask_j)

    # Collect eligible pairs (IoU >= threshold), sort descending
    eligible = []
    for i in range(num_gt):
        for j in range(num_pred):
            if iou_matrix[i, j] >= iou_threshold:
                eligible.append((iou_matrix[i, j], i, j))
    eligible.sort(key=lambda x: x[0], reverse=True)

    # Greedy matching
    matched_gt = set()
    matched_pred = set()
    matched_ious = []
    for iou_val, i, j in eligible:
        if i not in matched_gt and j not in matched_pred:
            matched_gt.add(i)
            matched_pred.add(j)
            matched_ious.append(iou_val)

    tp = len(matched_ious)
    fp = num_pred - tp
    fn = num_gt - tp

    if tp == 0:
        f1 = 0.0
        pq = 0.0
    else:
        f1 = 2.0 * tp / (2.0 * tp + fp + fn)
        sq = float(np.mean(matched_ious))
        pq = sq * f1

    return {
        "lesion_f1": float(f1),
        "panoptic_quality": float(pq),
        "instance_count_diff": icd,
        "num_gt_instances": num_gt,
        "num_pred_instances": num_pred,
    }


# ──────────────────────────────────────────────────────────────
# Per-case evaluation
# ──────────────────────────────────────────────────────────────

def evaluate_pair(gt_path, pred_path):
    """Evaluate a single ground truth / prediction NIfTI pair."""
    gt_img = nib.load(gt_path)
    pred_img = nib.load(pred_path)

    gt_data = binarize(gt_img)
    pred_data = binarize(pred_img)

    affine = gt_img.affine
    voxel_vol_ml = compute_voxel_volume_ml(affine)

    dice = compute_dice(gt_data, pred_data)
    avd = compute_avd_ml(gt_data, pred_data, voxel_vol_ml)
    assd, hd95 = compute_surface_distances(gt_data, pred_data, affine)
    inst = compute_instance_metrics(gt_data, pred_data)

    return {
        "dice": dice,
        "avd_ml": avd,
        "assd_mm": assd,
        "hd95_mm": hd95,
        **inst,
    }


# ──────────────────────────────────────────────────────────────
# Main CLI
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ISLES-compatible segmentation evaluation pipeline"
    )
    parser.add_argument("--gt", required=True,
                        help="Directory containing ground truth NIfTI masks")
    parser.add_argument("--pred", required=True,
                        help="Directory containing prediction NIfTI masks")
    parser.add_argument("--output", required=True,
                        help="Path for the output JSON report")
    args = parser.parse_args()

    gt_files = sorted(
        f for f in os.listdir(args.gt)
        if f.endswith(".nii.gz") or f.endswith(".nii")
    )

    if not gt_files:
        print("No NIfTI files found in ground truth directory.", file=sys.stderr)
        sys.exit(1)

    per_case = {}
    for gt_file in gt_files:
        gt_path = os.path.join(args.gt, gt_file)
        pred_path = os.path.join(args.pred, gt_file)

        if not os.path.exists(pred_path):
            print(f"Warning: no prediction found for {gt_file}, skipping.",
                  file=sys.stderr)
            continue

        case_name = gt_file
        if case_name.endswith(".nii.gz"):
            case_name = case_name[:-7]
        elif case_name.endswith(".nii"):
            case_name = case_name[:-4]

        per_case[case_name] = evaluate_pair(gt_path, pred_path)

    # Compute aggregate metrics
    if per_case:
        aggregate = {
            "mean_dice": float(np.mean(
                [v["dice"] for v in per_case.values()]
            )),
            "mean_avd_ml": float(np.mean(
                [v["avd_ml"] for v in per_case.values()]
            )),
            "mean_lesion_f1": float(np.mean(
                [v["lesion_f1"] for v in per_case.values()]
            )),
            "mean_panoptic_quality": float(np.mean(
                [v["panoptic_quality"] for v in per_case.values()]
            )),
            "mean_instance_count_diff": float(np.mean(
                [v["instance_count_diff"] for v in per_case.values()]
            )),
        }

        # Surface distance averages exclude -1.0 (undefined) cases
        valid_assd = [v["assd_mm"] for v in per_case.values()
                      if v["assd_mm"] != -1.0]
        valid_hd95 = [v["hd95_mm"] for v in per_case.values()
                      if v["hd95_mm"] != -1.0]

        aggregate["mean_assd_mm"] = float(np.mean(valid_assd)) if valid_assd else 0.0
        aggregate["mean_hd95_mm"] = float(np.mean(valid_hd95)) if valid_hd95 else 0.0
    else:
        aggregate = {}

    results = {"per_case": per_case, "aggregate": aggregate}

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Evaluation complete. {len(per_case)} cases processed. "
          f"Results: {args.output}")


if __name__ == "__main__":
    main()
