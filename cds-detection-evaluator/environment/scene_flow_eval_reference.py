"""Scene Flow Evaluation — Reference Implementation.

Adapted from Argoverse 2 scene flow evaluation (MIT License, Argo AI LLC).
This file defines the evaluation methodology for the LiDAR scene flow challenge.

Study this code carefully to understand:
- How scene flow metrics are computed (EPE, accuracy, angle error)
- How dynamic segmentation is evaluated (TP, FP, FN -> IoU)
- How metrics are broken down by class, motion, and distance
- How per-sweep metrics are aggregated into global results
- Which class/motion combinations are excluded

This file is provided as a reference for the evaluation methodology.
Do not attempt to import it directly as it has been adapted to be standalone.
"""

from collections import defaultdict
from enum import Enum
from typing import Any, Dict, Final, List, Tuple, Union

import numpy as np
import pandas as pd


# ────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────

SWEEP_PAIR_TIME_DELTA: Final = 0.1  # seconds between consecutive LiDAR sweeps

ACCURACY_RELAX_DISTANCE_THRESHOLD: Final = 0.1
ACCURACY_STRICT_DISTANCE_THRESHOLD: Final = 0.05

# Maps class names to the category_indices values that belong to each class
FOREGROUND_BACKGROUND_BREAKDOWN: Final = {
    "Background": [0],
    "Foreground": [1, 2, 3, 4],
}

# Class/motion combos matching this tuple are excluded from metric reporting
NO_FMT_INDICES: Final = ("Background", "Dynamic")

FLOW_COLUMNS: Final = ("flow_tx_m", "flow_ty_m", "flow_tz_m")

EPS: Final = 1e-10


# ────────────────────────────────────────────────────────────
# Metric type enumerations
# ────────────────────────────────────────────────────────────

class SceneFlowMetricType(str, Enum):
    EPE = "EPE"
    ACCURACY_STRICT = "ACCURACY_STRICT"
    ACCURACY_RELAX = "ACCURACY_RELAX"
    ANGLE_ERROR = "ANGLE_ERROR"


class SegmentationMetricType(str, Enum):
    TP = "TP"
    TN = "TN"
    FP = "FP"
    FN = "FN"


# ────────────────────────────────────────────────────────────
# Per-point metric computation
# ────────────────────────────────────────────────────────────

def compute_end_point_error(dts, gts):
    """Compute the end-point error between predictions and ground truth.

    Args:
        dts: (N,3) Array containing predicted flows.
        gts: (N,3) Array containing ground truth flows.

    Returns:
        (N,) The point-wise end-point error (L2 norm of the difference).
    """
    return np.linalg.norm(dts - gts, axis=-1).astype(np.float64)


def compute_accuracy(dts, gts, distance_threshold):
    """Compute the percent of inliers for a given threshold.

    A point is an inlier if either:
      - The absolute L2 flow error is below distance_threshold, OR
      - The relative error (L2 / ground_truth_magnitude) is below distance_threshold.

    The relative error uses EPS in the denominator for numerical stability
    when ground truth magnitude is near zero.

    Args:
        dts: (N,3) Array containing predicted flows.
        gts: (N,3) Array containing ground truth flows.
        distance_threshold: Inlier distance threshold.

    Returns:
        (N,) Pointwise inlier assignments (1.0 for inlier, 0.0 for outlier).
    """
    l2_norm = np.linalg.norm(dts - gts, axis=-1)
    gts_norm = np.linalg.norm(gts, axis=-1)
    relative_error = np.divide(l2_norm, gts_norm + EPS)
    abs_error_inlier = np.less(l2_norm, distance_threshold).astype(bool)
    relative_error_inlier = np.less(relative_error, distance_threshold).astype(bool)
    return np.logical_or(abs_error_inlier, relative_error_inlier).astype(np.float64)


def compute_accuracy_strict(dts, gts):
    """Compute accuracy with the strict threshold (0.05)."""
    return compute_accuracy(dts, gts, ACCURACY_STRICT_DISTANCE_THRESHOLD)


def compute_accuracy_relax(dts, gts):
    """Compute accuracy with the relaxed threshold (0.1)."""
    return compute_accuracy(dts, gts, ACCURACY_RELAX_DISTANCE_THRESHOLD)


def compute_angle_error(dts, gts):
    """Compute the angle error in space-time between predicted and GT flow.

    The 3D flow vectors are augmented to 4D by appending SWEEP_PAIR_TIME_DELTA
    as the fourth component: (fx, fy, fz) -> (fx, fy, fz, dt).
    Both vectors are normalized to unit length.
    The angle error is arccos(clamp(dot_product, -1, 1)) in radians.

    Args:
        dts: (N,3) Array containing predicted flows.
        gts: (N,3) Array containing ground truth flows.

    Returns:
        (N,) Pointwise angle errors in radians.
    """
    dts_space_time = np.pad(
        dts, ((0, 0), (0, 1)), constant_values=SWEEP_PAIR_TIME_DELTA
    )
    gts_space_time = np.pad(
        gts, ((0, 0), (0, 1)), constant_values=SWEEP_PAIR_TIME_DELTA
    )
    dts_unit = dts_space_time / np.linalg.norm(dts_space_time, axis=-1, keepdims=True)
    gts_unit = gts_space_time / np.linalg.norm(gts_space_time, axis=-1, keepdims=True)
    dot_product = np.einsum("bd,bd->b", dts_unit, gts_unit)
    clipped = np.clip(dot_product, -1.0, 1.0)
    return np.arccos(clipped).astype(np.float64)


def compute_true_positives(dts, gts):
    """TP: predicted dynamic AND ground truth dynamic."""
    return int(np.logical_and(dts, gts).sum())


def compute_false_positives(dts, gts):
    """FP: predicted dynamic AND ground truth static."""
    return int(np.logical_and(dts, ~gts).sum())


def compute_false_negatives(dts, gts):
    """FN: predicted static AND ground truth dynamic."""
    return int(np.logical_and(~dts, gts).sum())


# ────────────────────────────────────────────────────────────
# Per-sweep evaluation
# ────────────────────────────────────────────────────────────

def compute_metrics(
    pred_flow, pred_dynamic, gts, category_indices,
    is_dynamic, is_close, is_valid, metric_categories,
):
    """Compute all metrics for a single sweep pair.

    Only evaluates points where is_valid is True. Metrics are broken down
    by all combinations of (Class, Motion, Distance). Each breakdown
    subset stores the mean of each flow metric and the segmentation counts.

    Args:
        pred_flow: (N,3) Predicted flow vectors.
        pred_dynamic: (N,) Predicted dynamic labels.
        gts: (N,3) Ground truth flow vectors.
        category_indices: (N,) Integer class labels for each point.
        is_dynamic: (N,) Ground truth dynamic labels.
        is_close: (N,) True if point is within the spatial proximity box.
        is_valid: (N,) True if the flow annotation is valid for evaluation.
        metric_categories: Dict mapping class names to lists of category indices.

    Returns:
        Dict of lists (one row per subset) suitable for DataFrame construction.
    """
    pred_flow = pred_flow[is_valid].astype(np.float64)
    pred_dynamic = pred_dynamic[is_valid].astype(bool)
    gts = gts[is_valid].astype(np.float64)
    category_indices = category_indices[is_valid].astype(int)
    is_dynamic = is_dynamic[is_valid].astype(bool)
    is_close = is_close[is_valid].astype(bool)

    results = defaultdict(list)

    for cls_name, cat_idxs in metric_categories.items():
        cat_mask = category_indices == cat_idxs[0]
        for i in cat_idxs[1:]:
            cat_mask = np.logical_or(cat_mask, category_indices == i)

        for motion, m_mask in [("Dynamic", is_dynamic), ("Static", ~is_dynamic)]:
            for distance, d_mask in [("Close", is_close), ("Far", ~is_close)]:
                mask = cat_mask & m_mask & d_mask
                subset_size = mask.sum().item()

                results["Class"].append(cls_name)
                results["Motion"].append(motion)
                results["Distance"].append(distance)
                results["Count"].append(subset_size)

                if subset_size > 0:
                    sub_pred = pred_flow[mask]
                    sub_gt = gts[mask]
                    results[SceneFlowMetricType.EPE].append(
                        compute_end_point_error(sub_pred, sub_gt).mean()
                    )
                    results[SceneFlowMetricType.ACCURACY_STRICT].append(
                        compute_accuracy_strict(sub_pred, sub_gt).mean()
                    )
                    results[SceneFlowMetricType.ACCURACY_RELAX].append(
                        compute_accuracy_relax(sub_pred, sub_gt).mean()
                    )
                    results[SceneFlowMetricType.ANGLE_ERROR].append(
                        compute_angle_error(sub_pred, sub_gt).mean()
                    )
                    results[SegmentationMetricType.TP].append(
                        compute_true_positives(pred_dynamic[mask], is_dynamic[mask])
                    )
                    results[SegmentationMetricType.FP].append(
                        compute_false_positives(pred_dynamic[mask], is_dynamic[mask])
                    )
                    results[SegmentationMetricType.FN].append(
                        compute_false_negatives(pred_dynamic[mask], is_dynamic[mask])
                    )
                else:
                    for mt in SceneFlowMetricType:
                        results[mt].append(np.nan)
                    for st in [SegmentationMetricType.TP, SegmentationMetricType.FP,
                               SegmentationMetricType.FN]:
                        results[st].append(0)
    return results


# ────────────────────────────────────────────────────────────
# Dataset-level aggregation
# ────────────────────────────────────────────────────────────

def results_to_dict(frame):
    """Convert per-sweep results DataFrame to whole-dataset summary metrics.

    Uses count-weighted averaging across sweeps:
        weighted_avg = sum(metric_i * count_i) / sum(count_i)

    This produces per-(Class, Motion, Distance) metrics, per-(Class, Motion)
    metrics, Dynamic IoU, and EPE 3-Way Average.

    Args:
        frame: DataFrame with columns [Class, Motion, Distance, Count, EPE,
               ACCURACY_STRICT, ACCURACY_RELAX, ANGLE_ERROR, TP, FP, FN].

    Returns:
        Dict mapping metric path strings to float values.
        Format: "MetricName/Class/Motion[/Distance]" -> value
        Plus "Dynamic IoU" and "EPE 3-Way Average" summary keys.
    """
    output = {}
    grouped = frame.groupby(["Class", "Motion", "Distance"])

    def weighted_average(x, metric_type):
        total = x["Count"].sum()
        if total == 0:
            return np.nan
        return (x[metric_type.value] * x["Count"]).sum() / total

    # Per (Class, Motion, Distance)
    for metric_type in SceneFlowMetricType:
        avg = grouped.apply(lambda x, m=metric_type: weighted_average(x, m))
        for segment in avg.index.to_list():
            if segment[:2] == NO_FMT_INDICES:
                continue
            metric_type_str = (
                metric_type.value.title().replace("_", " ")
                if metric_type != SceneFlowMetricType.EPE
                else metric_type.value
            )
            name = metric_type_str + "/" + "/".join(str(s) for s in segment)
            output[name] = avg.loc[segment]

    # Per (Class, Motion) — aggregated across distances
    grouped_cm = frame.groupby(["Class", "Motion"])
    for metric_type in SceneFlowMetricType:
        avg_nodist = grouped_cm.apply(
            lambda x, m=metric_type: weighted_average(x, m)
        )
        for segment in avg_nodist.index.to_list():
            if segment[:2] == NO_FMT_INDICES:
                continue
            metric_type_str = (
                metric_type.value.title().replace("_", " ")
                if metric_type != SceneFlowMetricType.EPE
                else metric_type.value
            )
            name = metric_type_str + "/" + "/".join(str(s) for s in segment)
            output[name] = avg_nodist.loc[segment]

    # Dynamic IoU: TP / (TP + FP + FN) across all subsets
    output["Dynamic IoU"] = frame["TP"].sum() / (
        frame["TP"].sum() + frame["FP"].sum() + frame["FN"].sum()
    )

    # EPE 3-Way Average: mean of EPE over three class/motion groups
    output["EPE 3-Way Average"] = (
        output["EPE/Foreground/Dynamic"]
        + output["EPE/Foreground/Static"]
        + output["EPE/Background/Static"]
    ) / 3

    return output
