#!/usr/bin/env python3
"""ActEV18_AD-compatible activity detection scoring engine."""

import json
import os
from collections import defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment


def parse_sparse_signal(localization):
    """Parse ActEV sparse signal localization into intervals per file.

    Returns: {filename: [(start, end), ...]}
    """
    result = {}
    for filename, signal in localization.items():
        frames = sorted([(int(k), v) for k, v in signal.items()])
        intervals = []
        start = None
        for frame, val in frames:
            if val == 1 and start is None:
                start = frame
            elif val == 0 and start is not None:
                intervals.append((start, frame))
                start = None
        result[filename] = intervals
    return result


def signal_area(intervals):
    """Total frame count from a list of (start, end) intervals."""
    return sum(end - start for start, end in intervals)


def temporal_intersection(intervals_a, intervals_b):
    """Frame count of temporal intersection between two interval lists."""
    total = 0
    for a_start, a_end in intervals_a:
        for b_start, b_end in intervals_b:
            overlap_start = max(a_start, b_start)
            overlap_end = min(a_end, b_end)
            if overlap_start < overlap_end:
                total += overlap_end - overlap_start
    return total


def temporal_iou(intervals_a, intervals_b):
    """Temporal Intersection over Union."""
    inter = temporal_intersection(intervals_a, intervals_b)
    area_a = signal_area(intervals_a)
    area_b = signal_area(intervals_b)
    union = area_a + area_b - inter
    if union == 0:
        return 0.0
    return inter / union


def compute_file_durations(file_index):
    """Compute selected frame count per file from file index."""
    durations = {}
    for filename, info in file_index.items():
        selected = info["selected"]
        frames = sorted([(int(k), v) for k, v in selected.items()])
        total = 0
        start = None
        for frame, val in frames:
            if val == 1 and start is None:
                start = frame
            elif val == 0 and start is not None:
                total += frame - start
                start = None
        durations[filename] = total
    return durations


def compute_total_duration_minutes(file_index):
    """Total video duration across all files in minutes."""
    total_seconds = 0.0
    file_durations = compute_file_durations(file_index)
    for filename, num_frames in file_durations.items():
        framerate = file_index[filename]["framerate"]
        total_seconds += num_frames / framerate
    return total_seconds / 60.0


def score_activity(refs, syss, iou_threshold, total_minutes, file_index,
                   pmiss_targets, naudc_targets, collar, cost_miss, cost_fa):
    """Score a single activity and return metrics dict."""
    num_ref = len(refs)
    num_sys = len(syss)

    if num_ref == 0:
        return None

    # Parse localizations
    ref_locs = [parse_sparse_signal(r["localization"]) for r in refs]
    sys_locs = [parse_sparse_signal(s["localization"]) for s in syss]
    sys_confs = [s["presenceConf"] for s in syss]

    # Build IoU matrix
    iou_matrix = np.zeros((num_ref, num_sys))
    for i in range(num_ref):
        for j in range(num_sys):
            for fname in ref_locs[i]:
                if fname in sys_locs[j]:
                    val = temporal_iou(ref_locs[i][fname], sys_locs[j][fname])
                    iou_matrix[i, j] = max(iou_matrix[i, j], val)

    # Filter by IoU threshold (strictly greater)
    valid_pairs = iou_matrix > iou_threshold

    # Hungarian matching: minimize cost (negative IoU for valid, large for invalid)
    cost_matrix = np.full((num_ref, num_sys), 1e6)
    for i in range(num_ref):
        for j in range(num_sys):
            if valid_pairs[i, j]:
                cost_matrix[i, j] = -iou_matrix[i, j]

    matches = []
    if num_sys > 0:
        row_ind, col_ind = linear_sum_assignment(cost_matrix)
        for r, s in zip(row_ind, col_ind):
            if valid_pairs[r, s]:
                matches.append((r, s))

    matched_sys = set(s for _, s in matches)

    # --- DET curve sweep ---
    unique_confs = sorted(set(sys_confs), reverse=True)
    det_points = [(0.0, 1.0)]  # implicit start: no detections accepted

    for threshold in unique_confs:
        active_sys = {j for j in range(num_sys) if sys_confs[j] >= threshold}
        cd = sum(1 for _, s in matches if s in active_sys)
        md = num_ref - cd
        fa = sum(1 for j in active_sys if j not in matched_sys)
        p_miss = md / num_ref
        rfa = fa / total_minutes
        det_points.append((rfa, p_miss))

    # --- p_miss@RFA ---
    pmiss_at_rfa = {}
    for target in pmiss_targets:
        valid_pmiss = [pm for rfa, pm in det_points if rfa <= target]
        pmiss_at_rfa[target] = min(valid_pmiss) if valid_pmiss else 1.0

    # --- nAUDC via trapezoidal integration ---
    naudc_values = {}
    for target in naudc_targets:
        pts = [(rfa, pm) for rfa, pm in det_points if rfa <= target]
        area = 0.0
        for k in range(len(pts) - 1):
            dx = pts[k + 1][0] - pts[k][0]
            avg_y = (pts[k][1] + pts[k + 1][1]) / 2.0
            area += dx * avg_y
        naudc_values[target] = area / target if target > 0 else 0.0

    # --- N-MIDE ---
    file_durations = compute_file_durations(file_index)
    mide_values = []
    for r, s in matches:
        for fname in ref_locs[r]:
            if fname in sys_locs[s]:
                ref_intervals = ref_locs[r][fname]
                sys_intervals = sys_locs[s][fname]
                inter = temporal_intersection(ref_intervals, sys_intervals)
                ref_area = signal_area(ref_intervals)
                sys_area = signal_area(sys_intervals)
                t_miss = ref_area - inter
                t_fa = sys_area - inter
                file_dur = file_durations[fname]
                miss_rate = t_miss / ref_area if ref_area > 0 else 0.0
                non_ref = file_dur - ref_area
                fa_rate = t_fa / non_ref if non_ref > 0 else 0.0
                mide_values.append(cost_miss * miss_rate + cost_fa * fa_rate)
                break

    n_mide = float(np.mean(mide_values)) if mide_values else 0.0

    # Instance counts at lowest threshold (all detections active)
    num_correct = len(matches)
    num_missed = num_ref - num_correct
    num_false_alarm = num_sys - num_correct

    result = {
        "num_ref": num_ref,
        "num_sys": num_sys,
        "num_correct": num_correct,
        "num_missed": num_missed,
        "num_false_alarm": num_false_alarm,
        "n_mide": n_mide,
    }
    for target in pmiss_targets:
        result[f"p_miss_at_rfa_{target}"] = pmiss_at_rfa[target]
    for target in naudc_targets:
        result[f"naudc_at_rfa_{target}"] = naudc_values[target]

    return result


def main():
    data_dir = "/app/data"
    output_dir = "/app/output"

    with open(os.path.join(data_dir, "reference.json")) as f:
        reference = json.load(f)
    with open(os.path.join(data_dir, "system_output.json")) as f:
        system_output = json.load(f)
    with open(os.path.join(data_dir, "activity_index.json")) as f:
        activity_index = json.load(f)
    with open(os.path.join(data_dir, "file_index.json")) as f:
        file_index = json.load(f)
    with open(os.path.join(data_dir, "scoring_config.json")) as f:
        config = json.load(f)

    iou_threshold = config["iou_threshold"]
    pmiss_targets = config["p_miss_at_rfa_targets"]
    naudc_targets = config["naudc_at_rfa_targets"]
    collar = config["nmide_collar_size"]
    cost_miss = config["nmide_cost_miss"]
    cost_fa = config["nmide_cost_fa"]

    total_minutes = compute_total_duration_minutes(file_index)

    ref_by_activity = defaultdict(list)
    for inst in reference["activities"]:
        ref_by_activity[inst["activity"]].append(inst)

    sys_by_activity = defaultdict(list)
    for inst in system_output["activities"]:
        sys_by_activity[inst["activity"]].append(inst)

    by_activity = {}
    for activity in activity_index:
        refs = ref_by_activity.get(activity, [])
        syss = sys_by_activity.get(activity, [])
        result = score_activity(
            refs, syss, iou_threshold, total_minutes, file_index,
            pmiss_targets, naudc_targets, collar, cost_miss, cost_fa,
        )
        if result is not None:
            by_activity[activity] = result

    # Macro-average aggregation (float metrics only)
    aggregated = {}
    if by_activity:
        exclude = {"num_ref", "num_sys", "num_correct", "num_missed", "num_false_alarm"}
        float_keys = [k for k in list(by_activity.values())[0] if k not in exclude]
        for key in float_keys:
            vals = [by_activity[act][key] for act in by_activity]
            aggregated[key] = float(np.mean(vals))

    os.makedirs(output_dir, exist_ok=True)
    output = {"by_activity": by_activity, "aggregated": aggregated}
    with open(os.path.join(output_dir, "scores.json"), "w") as f:
        json.dump(output, f, indent=2)

    print("Scoring complete. Output written to /app/output/scores.json")


if __name__ == "__main__":
    main()
