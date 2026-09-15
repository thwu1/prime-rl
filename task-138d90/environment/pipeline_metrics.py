"""Metric computation for the evaluation pipeline.

Computes Average Precision, True Positive error metrics (ATE, ASE, AOE),
and Composite Detection Score (CDS) per the evaluation protocol.
"""

import math
import numpy as np


def compute_average_precision(tp_flags, num_gts, num_recall_samples=101):
    """Compute Average Precision with VOC-style precision interpolation.

    Uses configurable recall sampling with monotonic precision envelope to
    prevent artificial AP deflation from precision oscillations.

    Args:
        tp_flags: Boolean numpy array, True for true positives
                  (sorted by descending detection score).
        num_gts: Total number of ground truth annotations.
        num_recall_samples: Number of equally-spaced recall points in [0,1].

    Returns:
        Average Precision value in [0, 1].
    """
    if len(tp_flags) == 0 or num_gts == 0:
        return 0.0

    cum_tp = np.cumsum(tp_flags).astype(float)
    cum_fp = np.cumsum(~tp_flags).astype(float)

    precision = cum_tp / (cum_tp + cum_fp + 1e-10)
    recall = cum_tp / num_gts

    # Apply VOC monotonic precision envelope
    precision = np.maximum.accumulate(precision)

    # Interpolate at equally-spaced recall points
    recall_interp = np.linspace(0, 1, num_recall_samples, endpoint=True)
    precision_interp = np.interp(recall_interp, recall, precision, right=0)

    return float(np.mean(precision_interp))


def compute_orientation_error(yaw_dt, yaw_gt):
    """Compute angular error between two heading angles.

    Handles the full range of heading angles in [-pi, pi].

    Args:
        yaw_dt: Detection heading angle in radians.
        yaw_gt: Ground truth heading angle in radians.

    Returns:
        Angular error in [0, pi].
    """
    return abs(yaw_dt - yaw_gt)


def compute_scale_error(dt, gt):
    """Compute scale error as 1 - axis-aligned dimension IoU.

    IoU is computed as the product of min/max ratios for length,
    width, and height dimensions.
    """
    dims_dt = np.array([dt['length'], dt['width'], dt['height']])
    dims_gt = np.array([gt['length'], gt['width'], gt['height']])
    iou = float(np.prod(np.minimum(dims_dt, dims_gt) /
                         np.maximum(dims_dt, dims_gt)))
    return 1.0 - iou


def compute_composite_score(ap, ate, ase, aoe, tp_norms):
    """Compute Composite Detection Score (CDS).

    CDS combines detection performance (AP) with localization quality.
    TP measures are the clamped complements of normalized errors.

    Args:
        ap: Average Precision value.
        ate: Average Translation Error.
        ase: Average Scale Error.
        aoe: Average Orientation Error.
        tp_norms: Dict with normalization constants {ATE, ASE, AOE}.

    Returns:
        CDS value.
    """
    atm = max(0.0, 1.0 - ate / tp_norms['ATE'])
    asm = max(0.0, 1.0 - ase / tp_norms['ASE'])
    aom = max(0.0, 1.0 - aoe / tp_norms['AOE'])

    tp_score = atm + asm + aom
    return ap * tp_score
