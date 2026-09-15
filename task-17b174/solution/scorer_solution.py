#!/usr/bin/env python3
"""ActEV18_AD Activity Detection Scorer - Complete Implementation."""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment


def parse_sparse_signal(localization):
    """Convert sparse signal localization to frame intervals."""
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


def temporal_intersection(intervals_a, intervals_b):
    """Compute frame count of temporal intersection."""
    total = 0
    for a_start, a_end in intervals_a:
        for b_start, b_end in intervals_b:
            overlap_start = max(a_start, b_start)
            overlap_end = min(a_end, b_end)
            if overlap_start < overlap_end:
                total += overlap_end - overlap_start
    return total


def signal_area(intervals):
    """Compute total frame count from intervals."""
    return sum(end - start for start, end in intervals)


def temporal_iou(intervals_a, intervals_b):
    """Compute temporal IoU."""
    inter = temporal_intersection(intervals_a, intervals_b)
    area_a = signal_area(intervals_a)
    area_b = signal_area(intervals_b)
    union = area_a + area_b - inter
    if union == 0:
        return 0.0
    return inter / union


def compute_file_durations(file_index):
    """Compute selected frame count per file."""
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
    """Compute total evaluation duration in minutes."""
    total_seconds = 0.0
    file_durations = compute_file_durations(file_index)
    for filename, num_frames in file_durations.items():
        framerate = file_index[filename]["framerate"]
        total_seconds += num_frames / framerate
    return total_seconds / 60.0


def align_instances(ref_locs, sys_locs, iou_threshold):
    """Bipartite alignment via Hungarian algorithm."""
    num_ref = len(ref_locs)
    num_sys = len(sys_locs)

    if num_ref == 0 or num_sys == 0:
        return [], set()

    # Build IoU matrix
    iou_matrix = np.zeros((num_ref, num_sys))
    for i in range(num_ref):
        for j in range(num_sys):
            for fname in ref_locs[i]:
                if fname in sys_locs[j]:
                    val = temporal_iou(ref_locs[i][fname], sys_locs[j][fname])
                    iou_matrix[i, j] = max(iou_matrix[i, j], val)

    # Filter by threshold (strictly greater)
    valid_pairs = iou_matrix > iou_threshold

    # Cost matrix for Hungarian algorithm
    cost_matrix = np.full((num_ref, num_sys), 1e6)
    for i in range(num_ref):
        for j in range(num_sys):
            if valid_pairs[i, j]:
                cost_matrix[i, j] = -iou_matrix[i, j]

    row_ind, col_ind = linear_sum_assignment(cost_matrix)
    matches = []
    for r, s in zip(row_ind, col_ind):
        if valid_pairs[r, s]:
            matches.append((r, s))

    matched_sys = set(s for _, s in matches)
    return matches, matched_sys


def build_det_curve(matches, matched_sys, sys_confs, num_ref, num_sys,
                    total_duration_minutes):
    """Construct DET curve by sweeping confidence thresholds."""
    det_points = [(0.0, 1.0)]

    unique_confs = sorted(set(sys_confs), reverse=True)
    for threshold in unique_confs:
        active_sys = {j for j in range(num_sys) if sys_confs[j] >= threshold}
        cd = sum(1 for _, s in matches if s in active_sys)
        md = num_ref - cd
        fa = sum(1 for j in active_sys if j not in matched_sys)
        p_miss = md / num_ref
        rfa = fa / total_duration_minutes
        det_points.append((rfa, p_miss))

    return det_points


def compute_pmiss_at_rfa(det_points, targets):
    """Compute P_miss at RFA operating points."""
    result = {}
    for target in targets:
        valid_pmiss = [pm for rfa, pm in det_points if rfa <= target]
        result[target] = min(valid_pmiss) if valid_pmiss else 1.0
    return result


def compute_naudc(det_points, targets):
    """Compute normalized AUDC at RFA targets."""
    result = {}
    for target in targets:
        pts = [(rfa, pm) for rfa, pm in det_points if rfa <= target]
        area = 0.0
        for k in range(len(pts) - 1):
            dx = pts[k + 1][0] - pts[k][0]
            avg_y = (pts[k][1] + pts[k + 1][1]) / 2.0
            area += dx * avg_y
        result[target] = area / target if target > 0 else 0.0
    return result


def compute_nmide(matches, ref_locs, sys_locs, file_durations,
                  collar, cost_miss, cost_fa):
    """Compute N-MIDE with temporal collar support."""
    if not matches:
        return 0.0

    mide_values = []
    for r, s in matches:
        for fname in ref_locs[r]:
            if fname in sys_locs[s]:
                ref_intervals = ref_locs[r][fname]
                sys_intervals = sys_locs[s][fname]
                file_dur = file_durations[fname]

                # Construct collar-adjusted intervals
                core_intervals = []
                expanded_intervals = []
                for rs, re in ref_intervals:
                    # Core: shrink by collar on each side
                    cs, ce = rs + collar, re - collar
                    if ce > cs:
                        core_intervals.append((cs, ce))
                    # Expanded: grow by collar on each side
                    expanded_intervals.append((rs - collar, re + collar))

                # Miss: frames in core ref not covered by sys
                core_area = signal_area(core_intervals)
                if core_area > 0:
                    miss_inter = temporal_intersection(core_intervals,
                                                      sys_intervals)
                    miss_time = core_area - miss_inter
                    miss_rate = miss_time / core_area
                else:
                    miss_rate = 0.0

                # FA: frames in sys not covered by expanded ref
                expanded_area = signal_area(expanded_intervals)
                sys_area = signal_area(sys_intervals)
                fa_inter = temporal_intersection(sys_intervals,
                                                 expanded_intervals)
                fa_time = sys_area - fa_inter
                non_ref = file_dur - expanded_area
                fa_rate = fa_time / non_ref if non_ref > 0 else 0.0

                mide_values.append(cost_miss * miss_rate +
                                   cost_fa * fa_rate)
                break

    return float(np.mean(mide_values)) if mide_values else 0.0


def write_scores_by_activity_csv(by_activity, output_path,
                                 pmiss_targets, naudc_targets):
    """Write per-activity scores to CSV."""
    sorted_pmiss = sorted(pmiss_targets)
    sorted_naudc = sorted(naudc_targets)

    fieldnames = ["activity", "num_ref", "num_sys", "num_correct",
                  "num_missed", "num_false_alarm"]
    for t in sorted_pmiss:
        fieldnames.append(f"p_miss_at_rfa_{t}")
    for t in sorted_naudc:
        fieldnames.append(f"naudc_at_rfa_{t}")
    fieldnames.append("n_mide")

    int_fields = {"num_ref", "num_sys", "num_correct",
                  "num_missed", "num_false_alarm"}

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for activity in sorted(by_activity.keys()):
            metrics = by_activity[activity]
            row = []
            for field in fieldnames:
                if field == "activity":
                    row.append(activity)
                elif field in int_fields:
                    row.append(str(metrics[field]))
                else:
                    row.append(f"{metrics[field]:.5f}")
            writer.writerow(row)


def write_scores_aggregated_csv(aggregated, output_path):
    """Write aggregated scores to CSV."""
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for metric in sorted(aggregated.keys()):
            writer.writerow([metric, f"{aggregated[metric]:.5f}"])


def score_activity(refs, syss, iou_threshold, total_minutes, file_index,
                   file_durations, pmiss_targets, naudc_targets,
                   collar, cost_miss, cost_fa):
    """Score a single activity."""
    num_ref = len(refs)
    num_sys = len(syss)

    if num_ref == 0:
        return None

    ref_locs = [parse_sparse_signal(r["localization"]) for r in refs]
    sys_locs = [parse_sparse_signal(s["localization"]) for s in syss]
    sys_confs = [s["presenceConf"] for s in syss]

    matches, matched_sys = align_instances(ref_locs, sys_locs, iou_threshold)

    det_points = build_det_curve(matches, matched_sys, sys_confs,
                                num_ref, num_sys, total_minutes)

    pmiss_at_rfa = compute_pmiss_at_rfa(det_points, pmiss_targets)
    naudc_values = compute_naudc(det_points, naudc_targets)
    n_mide = compute_nmide(matches, ref_locs, sys_locs, file_durations,
                           collar, cost_miss, cost_fa)

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
    for t in pmiss_targets:
        result[f"p_miss_at_rfa_{t}"] = pmiss_at_rfa[t]
    for t in naudc_targets:
        result[f"naudc_at_rfa_{t}"] = naudc_values[t]

    return result


def main():
    parser = argparse.ArgumentParser(
        description="ActEV18_AD Activity Detection Scorer")
    parser.add_argument("--reference", required=True)
    parser.add_argument("--system-output", required=True)
    parser.add_argument("--activity-index", required=True)
    parser.add_argument("--file-index", required=True)
    parser.add_argument("--scoring-parameters", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    with open(args.reference) as f:
        reference = json.load(f)
    with open(args.system_output) as f:
        system_output = json.load(f)
    with open(args.activity_index) as f:
        activity_index = json.load(f)
    with open(args.file_index) as f:
        file_index = json.load(f)
    with open(args.scoring_parameters) as f:
        params = json.load(f)

    iou_threshold = params["iou_threshold"]
    pmiss_targets = params["p_miss_at_rfa_targets"]
    naudc_targets = params["naudc_at_rfa_targets"]
    collar = params["nmide_collar_size"]
    cost_miss = params["nmide_cost_miss"]
    cost_fa = params["nmide_cost_fa"]

    total_minutes = compute_total_duration_minutes(file_index)
    file_durations = compute_file_durations(file_index)

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
            file_durations, pmiss_targets, naudc_targets,
            collar, cost_miss, cost_fa,
        )
        if result is not None:
            by_activity[activity] = result

    # Macro-average aggregation
    aggregated = {}
    if by_activity:
        exclude = {"num_ref", "num_sys", "num_correct",
                   "num_missed", "num_false_alarm"}
        float_keys = [k for k in list(by_activity.values())[0]
                      if k not in exclude]
        for key in float_keys:
            vals = [by_activity[act][key] for act in by_activity]
            aggregated[key] = float(np.mean(vals))

    os.makedirs(args.output_dir, exist_ok=True)
    write_scores_by_activity_csv(
        by_activity,
        os.path.join(args.output_dir, "scores_by_activity.csv"),
        pmiss_targets, naudc_targets,
    )
    write_scores_aggregated_csv(
        aggregated,
        os.path.join(args.output_dir, "scores_aggregated.csv"),
    )
    print("Scoring complete.")


if __name__ == "__main__":
    main()
