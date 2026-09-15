#!/usr/bin/env python3
"""

Multi-Annotator Temporal Activity Detection Scorer
"""

import argparse
import csv
import json
import os
import sqlite3
import tomllib

import numpy as np
from scipy.optimize import linear_sum_assignment


def read_config(config_path):
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def read_database(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    videos = {}
    for row in conn.execute("SELECT id, filename, num_frames FROM videos"):
        videos[row["id"]] = {"filename": row["filename"], "num_frames": row["num_frames"]}

    activity_names = {}
    for row in conn.execute("SELECT id, name FROM activity_types"):
        activity_names[row["id"]] = row["name"]

    annotator_ids = []
    for row in conn.execute("SELECT id FROM annotators ORDER BY id"):
        annotator_ids.append(row["id"])

    annotations = []
    for row in conn.execute(
        "SELECT activity_type_id, video_id, annotator_id, start_frame, end_frame "
        "FROM reference_annotations"
    ):
        annotations.append({
            "activity": activity_names[row["activity_type_id"]],
            "file": videos[row["video_id"]]["filename"],
            "annotator_id": row["annotator_id"],
            "start_frame": row["start_frame"],
            "end_frame": row["end_frame"],
        })

    conn.close()
    return videos, sorted(set(activity_names.values())), annotator_ids, annotations


def read_detections(jsonl_path):
    detections = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            detections.append({
                "activity": obj["activity"],
                "file": obj["video"],
                "start_frame": obj["start"],
                "end_frame": obj["end"],
                "confidence": obj["score"],
            })
    return detections


def temporal_iou(r_start, r_end, s_start, s_end):
    inter_start = max(r_start, s_start)
    inter_end = min(r_end, s_end)
    if inter_start > inter_end:
        return 0.0
    intersection = inter_end - inter_start + 1
    union = max(r_end, s_end) - min(r_start, s_start) + 1
    return intersection / union


def merge_consensus_for_group(a1_anns, a2_anns, video_file, consensus_iou_threshold, include_singletons):
    """Merge annotations from two annotators for a single (activity, video)."""
    n1 = len(a1_anns)
    n2 = len(a2_anns)

    if n1 == 0 and n2 == 0:
        return []

    if n1 == 0 or n2 == 0:
        if include_singletons:
            all_anns = a1_anns + a2_anns
            return [{"file": video_file, "start_frame": a["start_frame"], "end_frame": a["end_frame"]}
                    for a in all_anns]
        return []

    # Build IoU matrix
    iou_mat = np.zeros((n1, n2))
    for i, a1 in enumerate(a1_anns):
        for j, a2 in enumerate(a2_anns):
            iou_mat[i, j] = temporal_iou(
                a1["start_frame"], a1["end_frame"],
                a2["start_frame"], a2["end_frame"],
            )

    # Maximize total IoU via Hungarian on negated matrix
    row_ind, col_ind = linear_sum_assignment(-iou_mat)

    matched_i = set()
    matched_j = set()
    consensus_refs = []

    for ri, ci in zip(row_ind, col_ind):
        if iou_mat[ri, ci] >= consensus_iou_threshold:
            matched_i.add(ri)
            matched_j.add(ci)
            a1 = a1_anns[ri]
            a2 = a2_anns[ci]
            cons_start = max(a1["start_frame"], a2["start_frame"])
            cons_end = min(a1["end_frame"], a2["end_frame"])
            consensus_refs.append({
                "file": video_file,
                "start_frame": cons_start,
                "end_frame": cons_end,
            })

    if include_singletons:
        for i in range(n1):
            if i not in matched_i:
                consensus_refs.append({
                    "file": video_file,
                    "start_frame": a1_anns[i]["start_frame"],
                    "end_frame": a1_anns[i]["end_frame"],
                })
        for j in range(n2):
            if j not in matched_j:
                consensus_refs.append({
                    "file": video_file,
                    "start_frame": a2_anns[j]["start_frame"],
                    "end_frame": a2_anns[j]["end_frame"],
                })

    return consensus_refs


def build_consensus_refs(annotations, activities, video_files, annotator_ids, config):
    """Build consensus references for all activity+video combinations."""
    consensus_cfg = config.get("consensus", {})
    consensus_enabled = consensus_cfg.get("enabled", False)

    if not consensus_enabled:
        return [{
            "activity": a["activity"],
            "file": a["file"],
            "start_frame": a["start_frame"],
            "end_frame": a["end_frame"],
        } for a in annotations]

    consensus_iou_threshold = consensus_cfg["consensus_iou_threshold"]
    include_singletons = consensus_cfg["include_singletons"]

    aids = sorted(annotator_ids)

    all_consensus = []
    for activity in activities:
        for vf in video_files:
            # Group by annotator
            by_annotator = {}
            for ann in annotations:
                if ann["activity"] == activity and ann["file"] == vf:
                    aid = ann["annotator_id"]
                    if aid not in by_annotator:
                        by_annotator[aid] = []
                    by_annotator[aid].append(ann)

            present_aids = sorted(by_annotator.keys())

            if len(present_aids) == 0:
                continue

            if len(present_aids) == 1:
                # Single annotator: all are singletons
                if include_singletons:
                    for a in by_annotator[present_aids[0]]:
                        all_consensus.append({
                            "activity": activity,
                            "file": vf,
                            "start_frame": a["start_frame"],
                            "end_frame": a["end_frame"],
                        })
                continue

            # Two annotators
            a1_anns = by_annotator.get(present_aids[0], [])
            a2_anns = by_annotator.get(present_aids[1], [])

            refs = merge_consensus_for_group(
                a1_anns, a2_anns, vf,
                consensus_iou_threshold, include_singletons,
            )
            for r in refs:
                r["activity"] = activity
            all_consensus.extend(refs)

    return all_consensus


def trapezoidal_area(points):
    area = 0.0
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        area += (x1 - x0) * (y0 + y1) / 2.0
    return area


def score_activity(refs, syss, total_frames, config):
    alignment_mode = config["evaluation"].get("alignment_mode", "iou")
    iou_threshold = config["evaluation"]["iou_threshold"]
    collar_frames = config["evaluation"].get("collar_frames", 30)
    pfa_max = config["evaluation"]["pfa_max"]
    c_miss = config["decision_cost"]["c_miss"]
    c_fa = config["decision_cost"]["c_fa"]
    p_target = config["decision_cost"]["p_target"]

    n_ref = len(refs)
    n_sys = len(syss)

    dcf_norm = min(c_miss * p_target, c_fa * (1.0 - p_target))

    # --- Zero-detection case ---
    if n_sys == 0:
        det_points = [[0.0, 1.0], [pfa_max, 1.0]]
        audc = 1.0 * pfa_max
        if n_ref == 0:
            min_ndcf = 0.0
        else:
            min_dcf = c_miss * p_target * 1.0
            min_ndcf = min_dcf / dcf_norm if dcf_norm > 0 else 1.0
        return {
            "nAUDC": 1.0 if n_ref > 0 else 0.0,
            "AUDC": audc if n_ref > 0 else 0.0,
            "tw_nAUDC": 1.0 if n_ref > 0 else 0.0,
            "tw_AUDC": audc if n_ref > 0 else 0.0,
            "MinNDCF": min_ndcf,
            "n_ref": n_ref, "n_sys": n_sys,
            "det_points": det_points if n_ref > 0 else [[0.0, 0.0], [pfa_max, 0.0]],
        }

    # --- Zero-reference case ---
    if n_ref == 0:
        det_points = [[0.0, 0.0]]
        fp = 0
        sorted_idx = sorted(range(n_sys), key=lambda j: -syss[j]["confidence"])
        for j in sorted_idx:
            fp += 1
            det_points.append([fp / total_frames, 0.0])
        if det_points[-1][0] < pfa_max:
            det_points.append([pfa_max, 0.0])
        return {
            "nAUDC": 0.0, "AUDC": 0.0,
            "tw_nAUDC": 0.0, "tw_AUDC": 0.0,
            "MinNDCF": 0.0,
            "n_ref": 0, "n_sys": n_sys,
            "det_points": det_points,
        }

    # --- Build alignment cost matrix ---
    cost_mat = np.full((n_ref, n_sys), 1e9)

    if alignment_mode == "iou":
        for i, r in enumerate(refs):
            for j, s in enumerate(syss):
                if r["file"] == s["file"]:
                    iou = temporal_iou(
                        r["start_frame"], r["end_frame"],
                        s["start_frame"], s["end_frame"],
                    )
                    if iou >= iou_threshold:
                        cost_mat[i, j] = 1.0 - iou
    elif alignment_mode == "collar":
        for i, r in enumerate(refs):
            for j, s in enumerate(syss):
                if r["file"] != s["file"]:
                    continue
                start_diff = abs(s["start_frame"] - r["start_frame"])
                end_diff = abs(s["end_frame"] - r["end_frame"])
                if start_diff <= collar_frames and end_diff <= collar_frames:
                    cost_mat[i, j] = max(start_diff, end_diff) / collar_frames
    else:
        raise ValueError(f"Unknown alignment mode: {alignment_mode}")

    row_ind, col_ind = linear_sum_assignment(cost_mat)

    matched_sys = {}
    for ri, si in zip(row_ind, col_ind):
        if cost_mat[ri, si] < 1e9:
            matched_sys[si] = ri

    # Sort by descending confidence; ties: TP before FP
    sorted_indices = sorted(
        range(n_sys),
        key=lambda j: (-syss[j]["confidence"], 0 if j in matched_sys else 1),
    )

    ref_weights = [r["end_frame"] - r["start_frame"] + 1 for r in refs]
    total_weight = sum(ref_weights)

    det_points = [[0.0, 1.0]]
    tw_det_points = [[0.0, 1.0]]

    tp = 0
    fp = 0
    matched_weight = 0

    # Include reject-all operating point for MinDCF
    op_points = [(1.0, 0.0)]

    for j in sorted_indices:
        if j in matched_sys:
            tp += 1
            matched_weight += ref_weights[matched_sys[j]]
        else:
            fp += 1

        pmiss = 1.0 - tp / n_ref
        pfa = fp / total_frames
        det_points.append([pfa, pmiss])

        tw_pmiss = 1.0 - matched_weight / total_weight
        tw_det_points.append([pfa, tw_pmiss])

        op_points.append((pmiss, pfa))

    if det_points[-1][0] < pfa_max:
        det_points.append([pfa_max, det_points[-1][1]])
    if tw_det_points[-1][0] < pfa_max:
        tw_det_points.append([pfa_max, tw_det_points[-1][1]])

    audc = trapezoidal_area(det_points)
    naudc = audc / pfa_max if pfa_max > 0 else 1.0

    tw_audc = trapezoidal_area(tw_det_points)
    tw_naudc = tw_audc / pfa_max if pfa_max > 0 else 1.0

    # MinNDCF
    min_dcf = float("inf")
    for pmiss_val, pfa_val in op_points:
        dcf = c_miss * p_target * pmiss_val + c_fa * (1.0 - p_target) * pfa_val
        if dcf < min_dcf:
            min_dcf = dcf

    min_ndcf = min_dcf / dcf_norm if dcf_norm > 0 else 0.0

    return {
        "nAUDC": naudc, "AUDC": audc,
        "tw_nAUDC": tw_naudc, "tw_AUDC": tw_audc,
        "MinNDCF": min_ndcf,
        "n_ref": n_ref, "n_sys": n_sys,
        "det_points": det_points,
    }


def main():
    parser = argparse.ArgumentParser(description="Multi-Annotator Temporal Activity Detection Scorer")
    parser.add_argument("--config", required=True, help="Path to TOML config file")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    args = parser.parse_args()

    config = read_config(args.config)
    db_path = config["data"]["database"]
    det_path = config["data"]["detections"]

    videos, activities, annotator_ids, annotations = read_database(db_path)
    detections = read_detections(det_path)

    total_frames = sum(v["num_frames"] for v in videos.values())
    video_files = sorted(set(v["filename"] for v in videos.values()))

    # Build consensus references
    consensus_refs = build_consensus_refs(annotations, activities, video_files, annotator_ids, config)

    os.makedirs(args.output_dir, exist_ok=True)

    results = {}
    det_curves = {}

    for activity in sorted(activities):
        act_refs = [r for r in consensus_refs if r["activity"] == activity]
        act_syss = [d for d in detections if d["activity"] == activity]

        res = score_activity(act_refs, act_syss, total_frames, config)
        results[activity] = res
        det_curves[activity] = {
            "points": [[round(p[0], 6), round(p[1], 6)] for p in res["det_points"]]
        }

    # scores_by_activity.csv
    with open(os.path.join(args.output_dir, "scores_by_activity.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["activity", "nAUDC", "AUDC", "tw_nAUDC", "tw_AUDC", "MinNDCF", "n_ref", "n_sys"])
        for act in sorted(results.keys()):
            r = results[act]
            writer.writerow([
                act,
                f"{r['nAUDC']:.6f}",
                f"{r['AUDC']:.6f}",
                f"{r['tw_nAUDC']:.6f}",
                f"{r['tw_AUDC']:.6f}",
                f"{r['MinNDCF']:.6f}",
                r["n_ref"],
                r["n_sys"],
            ])

    # scores_aggregated.csv
    n_acts = len(results)
    mean_naudc = sum(r["nAUDC"] for r in results.values()) / n_acts
    total_refs = sum(r["n_ref"] for r in results.values())
    if total_refs > 0:
        weighted_mean_naudc = (
            sum(r["nAUDC"] * r["n_ref"] for r in results.values()) / total_refs
        )
    else:
        weighted_mean_naudc = 0.0
    mean_tw_naudc = sum(r["tw_nAUDC"] for r in results.values()) / n_acts
    mean_min_ndcf = sum(r["MinNDCF"] for r in results.values()) / n_acts

    with open(os.path.join(args.output_dir, "scores_aggregated.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        writer.writerow(["mean_nAUDC", f"{mean_naudc:.6f}"])
        writer.writerow(["weighted_mean_nAUDC", f"{weighted_mean_naudc:.6f}"])
        writer.writerow(["mean_tw_nAUDC", f"{mean_tw_naudc:.6f}"])
        writer.writerow(["mean_MinNDCF", f"{mean_min_ndcf:.6f}"])

    # det_curves.json
    with open(os.path.join(args.output_dir, "det_curves.json"), "w") as f:
        json.dump(det_curves, f, indent=2)


if __name__ == "__main__":
    main()
