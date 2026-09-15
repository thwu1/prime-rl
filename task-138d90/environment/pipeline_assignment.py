"""Detection-to-ground-truth assignment for evaluation.

Implements greedy matching of detections to ground truth annotations
based on 3D center distance and confidence score ordering.
"""

import math


def compute_center_distance(a, b):
    """3D Euclidean distance between object centers."""
    return math.sqrt(
        (a['tx'] - b['tx'])**2 +
        (a['ty'] - b['ty'])**2 +
        (a['tz'] - b['tz'])**2
    )


def greedy_assign(sweep_dts, sweep_gts, threshold):
    """Assign detections to ground truth using greedy matching.

    Processes detections sorted by confidence score. Each detection
    is matched to the closest unmatched ground truth within the
    distance threshold. Higher-confidence detections are processed
    first to ensure they claim matches before lower-confidence ones.

    Args:
        sweep_dts: List of detection dicts with 'score', 'tx', 'ty', 'tz'.
        sweep_gts: List of ground truth dicts with 'tx', 'ty', 'tz'.
        threshold: Maximum center distance for a valid match (meters).

    Returns:
        Dict mapping detection index to matched ground truth index.
    """
    if not sweep_dts or not sweep_gts:
        return {}

    dt_indices = sorted(range(len(sweep_dts)),
                        key=lambda i: sweep_dts[i]['score'])

    matched_gts = set()
    assignments = {}

    for dt_idx in dt_indices:
        dt = sweep_dts[dt_idx]
        best_dist = float('inf')
        best_gt_idx = -1

        for gt_idx in range(len(sweep_gts)):
            if gt_idx in matched_gts:
                continue
            dist = compute_center_distance(dt, sweep_gts[gt_idx])
            if dist < threshold and dist < best_dist:
                best_dist = dist
                best_gt_idx = gt_idx

        if best_gt_idx >= 0:
            assignments[dt_idx] = best_gt_idx
            matched_gts.add(best_gt_idx)

    return assignments
