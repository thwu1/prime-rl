"""Composite Detection Score (CDS) — Reference Implementation.

Adapted from the Argoverse 2 3D object detection evaluation (MIT License, Argo AI LLC).
This file illustrates how the Composite Detection Score is computed in the
Argoverse 2 detection challenge. Study this methodology to understand the
composite scoring principle used as the basis for the scene flow ranking metric.

The detection challenge evaluates 3D object detections against ground truth
annotations. For each detection category, three types of true-positive errors
are computed:

  - ATE (Average Translation Error): Euclidean distance between detection and
    ground truth centers (meters). A position accuracy metric.
  - ASE (Average Scale Error): 1 - IoU after pose alignment. Measures how well
    the predicted bounding box size matches ground truth (unitless, in [0,1]).
  - AOE (Average Orientation Error): Angular distance between predicted and
    ground truth headings (radians, in [0, pi]).

CDS combines classification quality (mAP) with these error-based scores.
"""

import math
import numpy as np


# ────────────────────────────────────────────────────────────
# Normalization Constants for True Positive Errors
# ────────────────────────────────────────────────────────────
#
# Each TP error type is normalized by a threshold representing the maximum
# tolerable error for that metric. The choice of threshold depends on the
# physical domain and interpretation of each error type:

TP_THRESHOLD_M = 2.0           # ATE: max tolerable translation error = 2.0 meters
MAX_SCALE_ERROR = 1.0          # ASE: IoU-based, already in [0,1], max = 1.0
MAX_YAW_RAD_ERROR = math.pi    # AOE: max angular error = pi radians

TP_NORMALIZATION_TERMS = (TP_THRESHOLD_M, MAX_SCALE_ERROR, MAX_YAW_RAD_ERROR)


# ────────────────────────────────────────────────────────────
# Per-Category CDS Computation
# ────────────────────────────────────────────────────────────

def compute_cds_for_category(mean_average_precision, tp_errors):
    """Compute the Composite Detection Score for a single detection category.

    CDS combines a classification quality term with the mean of normalized,
    complemented true-positive error scores:

        For each error type i:
            score_i = max(0, 1 - error_i / normalization_threshold_i)

        CDS = classification_quality * mean(score_1, score_2, score_3)

    This multiplicative structure ensures that a model must BOTH detect objects
    correctly (high classification quality) AND estimate their properties
    accurately (low errors) to achieve a high composite score. A model with
    perfect estimation but 0% detection quality scores 0.

    Args:
        mean_average_precision: mAP for this category (float in [0, 1]).
            Measures how well the model detects and classifies objects.
        tp_errors: Array of [ATE, ASE, AOE] averaged over true positives.
            Each error measures a different aspect of estimation quality.

    Returns:
        CDS value in [0, 1].
    """
    # Convert errors to scores: score = 1 - error / threshold
    tp_scores = 1.0 - np.divide(tp_errors, np.array(TP_NORMALIZATION_TERMS))

    # Clamp scores to [0, 1] — errors exceeding their threshold yield score 0
    tp_scores = np.clip(tp_scores, 0.0, 1.0)

    # CDS = classification_quality * mean(error_scores)
    cds = float(mean_average_precision) * float(np.mean(tp_scores))
    return cds


# ────────────────────────────────────────────────────────────
# Dataset-Level Aggregation
# ────────────────────────────────────────────────────────────

def compute_summary_metrics(per_category_map, per_category_tp_errors):
    """Compute summary CDS across all categories.

    In the detection challenge, final metrics are computed per-category
    and then averaged:
        mAP   = mean(AP_cat1, AP_cat2, ...)
        mATE  = mean(ATE_cat1, ATE_cat2, ...)
        mASE  = mean(ASE_cat1, ASE_cat2, ...)
        mAOE  = mean(AOE_cat1, AOE_cat2, ...)
        CDS   = mAP * mean(1 - mATE/tau_ate, 1 - mASE/tau_ase, 1 - mAOE/tau_aoe)

    Args:
        per_category_map: Dict of category -> average precision.
        per_category_tp_errors: Dict of category -> [ATE, ASE, AOE] array.

    Returns:
        Dict with summary metrics.
    """
    categories = list(per_category_map.keys())
    mean_ap = float(np.mean([per_category_map[c] for c in categories]))

    mean_tp_errors = np.mean(
        [per_category_tp_errors[c] for c in categories], axis=0
    )

    # Compute mean TP scores
    mean_tp_scores = np.clip(
        1.0 - np.divide(mean_tp_errors, np.array(TP_NORMALIZATION_TERMS)),
        0.0, 1.0
    )

    cds = mean_ap * float(np.mean(mean_tp_scores))

    return {
        "mAP": mean_ap,
        "mATE": float(mean_tp_errors[0]),
        "mASE": float(mean_tp_errors[1]),
        "mAOE": float(mean_tp_errors[2]),
        "CDS": cds,
    }


# ────────────────────────────────────────────────────────────
# Design Pattern Summary
# ────────────────────────────────────────────────────────────
#
# The CDS follows this general pattern:
#
#   composite = quality_term * mean(component_scores)
#
# Where:
#   quality_term: [0,1] measure of classification/detection ability
#   component_scores: Each is max(0, 1 - error/threshold) for error metrics,
#                     or used directly for metrics already in [0,1]
#
# The three component scores contribute with equal weight.
#
# To adapt this pattern to a different evaluation domain:
#   1. Identify the classification/quality metric (analogous to mAP)
#   2. Identify the error metrics and their domains
#   3. Choose normalization thresholds matching each metric's physical meaning
#      (e.g., translation errors use distance thresholds, angular errors use
#       radian thresholds)
#   4. Handle metrics that are already scores (higher=better) differently
#      from error metrics (lower=better)
#   5. Group related metrics if needed to maintain exactly 3 components
