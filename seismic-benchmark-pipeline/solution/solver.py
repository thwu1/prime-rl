#!/usr/bin/env python3
"""
Seismic dataset harmonization and benchmark evaluation solution.

Handles heterogeneous component orders (ZNE/ENZ), sampling rates (100/200 Hz),
computes SNR quality metrics, and implements the exact SeisBench benchmark
evaluation methodology.

"""

import numpy as np
import h5py
import json
import csv
import os
import sys
from scipy.signal import decimate
from sklearn.metrics import (
    precision_recall_curve,
    precision_recall_fscore_support,
    roc_auc_score,
    matthews_corrcoef,
)

RAW_DIR = "/app/raw_data"
OUTPUT_DIR = "/app/output"
TARGET_SR = 100
TARGET_CO = "ZNE"
BLOCK_SIZE = 50


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_csv_file(path):
    with open(path) as f:
        return list(csv.DictReader(f))


# ======================================================================
# Component order normalization
# ======================================================================

def normalize_component_order(waveform, source_order, target_order="ZNE"):
    """Reorder components from source_order to target_order."""
    if source_order == target_order:
        return waveform
    mapping = [source_order.index(c) for c in target_order]
    return waveform[mapping]


# ======================================================================
# Sampling rate harmonization
# ======================================================================

def resample_trace(waveform, source_sr, target_sr):
    """Resample waveform from source_sr to target_sr using anti-aliased decimation."""
    if source_sr == target_sr:
        return waveform
    factor = int(source_sr / target_sr)
    if source_sr % target_sr != 0:
        raise ValueError(f"Non-integer decimation factor: {source_sr}/{target_sr}")
    result = np.zeros(
        (waveform.shape[0], waveform.shape[1] // factor), dtype=waveform.dtype)
    for ch in range(waveform.shape[0]):
        result[ch] = decimate(
            waveform[ch].astype(np.float64), factor, zero_phase=True
        ).astype(waveform.dtype)
    return result


# ======================================================================
# SNR computation
# ======================================================================

def compute_snr_db(z_component, p_sample, s_sample):
    """Compute SNR in dB using pre-P noise and P-to-S signal on Z component."""
    if p_sample < 10 or s_sample <= p_sample:
        return 0.0
    noise = z_component[:p_sample].astype(np.float64)
    signal = z_component[p_sample:s_sample].astype(np.float64)
    if len(noise) < 5 or len(signal) < 5:
        return 0.0
    noise_power = np.mean(noise ** 2)
    signal_power = np.mean(signal ** 2)
    if noise_power == 0:
        return 50.0
    return float(10 * np.log10(signal_power / noise_power))


def quality_tier(snr_db):
    if snr_db >= 10:
        return "A"
    elif snr_db >= 5:
        return "B"
    else:
        return "C"


# ======================================================================
# Part 1: Build SeisBench-format dataset
# ======================================================================

def build_dataset():
    os.makedirs(f"{OUTPUT_DIR}/dataset", exist_ok=True)

    events = load_json(f"{RAW_DIR}/events.json")
    stations_list = load_json(f"{RAW_DIR}/stations.json")
    winfo = load_json(f"{RAW_DIR}/waveforms_info.json")
    picks = load_json(f"{RAW_DIR}/picks.json")
    split_map = load_json(f"{RAW_DIR}/split_assignment.json")

    event_map = {e["event_id"]: e for e in events}
    station_map = {s["station"]: s for s in stations_list}
    pick_map = {p["trace_id"]: p for p in picks}

    # Validate station data structure
    print(f"Loaded {len(stations_list)} stations, {len(winfo)} waveforms")
    for s in stations_list:
        if "sampling_rate_hz" not in s:
            print(f"ERROR: Station keys are: {list(s.keys())}", file=sys.stderr)
            raise KeyError(f"Station '{s.get('station', '?')}' missing 'sampling_rate_hz'. Keys: {list(s.keys())}")
        if "component_order" not in s:
            raise KeyError(f"Station '{s.get('station', '?')}' missing 'component_order'. Keys: {list(s.keys())}")

    meta_rows = []
    processed_waveforms = {}

    for w in winfo:
        sta = station_map[w["station"]]
        src_sr = sta["sampling_rate_hz"]
        src_co = sta["component_order"]

        # Load raw waveform
        raw_wf = np.load(f"{RAW_DIR}/waveforms/{w['trace_id']}.npy")

        # Normalize component order to ZNE
        wf = normalize_component_order(raw_wf, src_co, TARGET_CO)

        # Resample to target rate
        wf = resample_trace(wf, src_sr, TARGET_SR)

        processed_waveforms[w["trace_id"]] = wf
        sr_ratio = src_sr / TARGET_SR

        row = {
            "trace_id_raw": w["trace_id"],
            "split": split_map[w["trace_id"]],
            "trace_sampling_rate_hz": TARGET_SR,
            "trace_npts": wf.shape[1],
        }

        if w["is_earthquake"] and w["event_id"]:
            ev = event_map[w["event_id"]]
            row.update({
                "source_id": ev["event_id"],
                "source_origin_time": ev["origin_time"],
                "source_latitude_deg": ev["latitude"],
                "source_longitude_deg": ev["longitude"],
                "source_depth_km": ev["depth_km"],
                "source_magnitude": ev["magnitude"],
                "source_type": "earthquake",
            })
        else:
            row.update({
                "source_id": "",
                "source_origin_time": "",
                "source_latitude_deg": "",
                "source_longitude_deg": "",
                "source_depth_km": "",
                "source_magnitude": "",
                "source_type": "noise",
            })

        row.update({
            "station_network_code": sta["network"],
            "station_code": sta["station"],
            "station_latitude_deg": sta["latitude"],
            "station_longitude_deg": sta["longitude"],
            "station_elevation_m": sta["elevation_m"],
        })

        if w["trace_id"] in pick_map:
            p = pick_map[w["trace_id"]]
            adj_p = int(round(p["p_arrival_sample"] / sr_ratio))
            adj_s = int(round(p["s_arrival_sample"] / sr_ratio))
            row.update({
                "trace_p_arrival_sample": adj_p,
                "trace_s_arrival_sample": adj_s,
                "trace_p_status": "manual",
                "trace_s_status": "manual",
                "path_p_travel_s": round(adj_p / TARGET_SR, 4),
                "path_s_travel_s": round(adj_s / TARGET_SR, 4),
            })

            snr = compute_snr_db(wf[0], adj_p, adj_s)
            row["trace_snr_db"] = round(snr, 2)
            row["trace_quality"] = quality_tier(snr)
        else:
            row.update({
                "trace_p_arrival_sample": "",
                "trace_s_arrival_sample": "",
                "trace_p_status": "",
                "trace_s_status": "",
                "path_p_travel_s": "",
                "path_s_travel_s": "",
                "trace_snr_db": "",
                "trace_quality": "",
            })

        meta_rows.append(row)

    # Group by split and create trace blocks
    split_groups = {"train": [], "dev": [], "test": []}
    for i, row in enumerate(meta_rows):
        split_groups[row["split"]].append((i, row))

    block_counter = 0
    with h5py.File(f"{OUTPUT_DIR}/dataset/waveforms.hdf5", "w") as f:
        df = f.create_group("data_format")
        df.create_dataset("dimension_order", data="NCW")
        df.create_dataset("component_order", data="ZNE")
        df.create_dataset("sampling_rate", data=float(TARGET_SR))
        data_grp = f.create_group("data")

        for split_name in ["train", "dev", "test"]:
            items = split_groups[split_name]
            for blk_start in range(0, len(items), BLOCK_SIZE):
                blk_items = items[blk_start:blk_start + BLOCK_SIZE]
                block_name = f"block{block_counter:03d}"

                waveforms = []
                for within_idx, (orig_idx, row) in enumerate(blk_items):
                    wf = processed_waveforms[row["trace_id_raw"]]
                    waveforms.append(wf)
                    meta_rows[orig_idx]["trace_name"] = \
                        f"{block_name}${within_idx}"

                block_arr = np.stack(waveforms, axis=0)  # (N, C, W)
                data_grp.create_dataset(block_name, data=block_arr)
                block_counter += 1

    # Write metadata.csv
    columns = [
        "trace_name", "split",
        "source_id", "source_origin_time", "source_latitude_deg",
        "source_longitude_deg", "source_depth_km", "source_magnitude",
        "source_type",
        "station_network_code", "station_code", "station_latitude_deg",
        "station_longitude_deg", "station_elevation_m",
        "trace_sampling_rate_hz", "trace_npts",
        "trace_p_arrival_sample", "trace_s_arrival_sample",
        "trace_p_status", "trace_s_status",
        "path_p_travel_s", "path_s_travel_s",
        "trace_snr_db", "trace_quality",
    ]
    with open(f"{OUTPUT_DIR}/dataset/metadata.csv", "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(meta_rows)

    # Quality report
    eq_rows = [r for r in meta_rows if r.get("source_type") == "earthquake"]
    snr_values = [float(r["trace_snr_db"]) for r in eq_rows
                  if r["trace_snr_db"] != ""]

    tier_counts = {
        "train": {"A": 0, "B": 0, "C": 0},
        "dev": {"A": 0, "B": 0, "C": 0},
        "test": {"A": 0, "B": 0, "C": 0},
    }
    for r in eq_rows:
        if r["trace_quality"] in ("A", "B", "C"):
            tier_counts[r["split"]][r["trace_quality"]] += 1

    quality_report = {
        "tier_counts": tier_counts,
        "snr_statistics": {
            "mean_db": round(float(np.mean(snr_values)), 2),
            "median_db": round(float(np.median(snr_values)), 2),
            "min_db": round(float(np.min(snr_values)), 2),
            "max_db": round(float(np.max(snr_values)), 2),
        },
    }
    with open(f"{OUTPUT_DIR}/quality_report.json", "w") as f:
        json.dump(quality_report, f, indent=2)

    print(f"Dataset: {block_counter} blocks, {len(meta_rows)} traces")


# ======================================================================
# Part 2: Benchmark evaluation (exact SeisBench methodology)
# ======================================================================

def compute_metrics():
    task1_dev = load_csv_file(f"{RAW_DIR}/predictions/task1_dev.csv")
    task1_test = load_csv_file(f"{RAW_DIR}/predictions/task1_test.csv")
    task23_dev = load_csv_file(f"{RAW_DIR}/predictions/task23_dev.csv")
    task23_test = load_csv_file(f"{RAW_DIR}/predictions/task23_test.csv")

    results = {}

    # ---- Task 1: Detection ----
    dev_scores = np.array([float(r["score_detection"]) for r in task1_dev])
    dev_labels = np.array([int(r["true_label"]) for r in task1_dev])
    test_scores = np.array([float(r["score_detection"]) for r in task1_test])
    test_labels = np.array([int(r["true_label"]) for r in task1_test])

    # F1 threshold via precision-recall curve (all unique thresholds)
    prec, recall, thresholds = precision_recall_curve(dev_labels, dev_scores)
    f1 = 2 * prec * recall / (prec + recall)
    opt_idx = np.nanargmax(f1)
    opt_thr = thresholds[opt_idx]

    t_prec, t_recall, t_f1, _ = precision_recall_fscore_support(
        test_labels, test_scores > opt_thr, average="binary")
    t_auc = roc_auc_score(test_labels, test_scores)

    results["det_precision"] = round(float(t_prec), 6)
    results["det_recall"] = round(float(t_recall), 6)
    results["det_f1"] = round(float(t_f1), 6)
    results["det_auc"] = round(float(t_auc), 6)

    # ---- Task 2: Phase classification ----
    dev_scores2 = np.array([float(r["score_p_or_s"]) for r in task23_dev])
    dev_labels2 = np.array(
        [1 if r["phase_label"] == "P" else 0 for r in task23_dev])
    test_scores2 = np.array([float(r["score_p_or_s"]) for r in task23_test])
    test_labels2 = np.array(
        [1 if r["phase_label"] == "P" else 0 for r in task23_test])

    # F1 threshold via P-R curve
    prec2, recall2, thr2 = precision_recall_curve(dev_labels2, dev_scores2)
    f1_2 = 2 * prec2 * recall2 / (prec2 + recall2)
    opt_idx2 = np.nanargmax(f1_2)
    opt_thr2 = thr2[opt_idx2]

    cp, cr, cf, _ = precision_recall_fscore_support(
        test_labels2, test_scores2 > opt_thr2, average="binary")
    results["cls_precision"] = round(float(cp), 6)
    results["cls_recall"] = round(float(cr), 6)
    results["cls_f1"] = round(float(cf), 6)

    # MCC with separate threshold optimization (50 quantile candidates)
    sorted_dev = np.sort(dev_scores2)
    mcc_thrs = sorted_dev[np.linspace(0, len(sorted_dev) - 1, 50, dtype=int)]
    mccs = [matthews_corrcoef(dev_labels2, dev_scores2 > t) for t in mcc_thrs]
    mcc_thr = mcc_thrs[np.argmax(mccs)]
    test_mcc = matthews_corrcoef(test_labels2, test_scores2 > mcc_thr)
    results["cls_mcc"] = round(float(test_mcc), 6)

    # ---- Task 3: Onset timing (RMSE, per-entry sampling rate) ----
    for phase in ["P", "S"]:
        phase_rows = [r for r in task23_test if r["phase_label"] == phase]
        pred_col = "p_sample_pred" if phase == "P" else "s_sample_pred"

        diffs = np.array([
            (float(r[pred_col]) - float(r["phase_onset"]))
            / float(r["sampling_rate"])
            for r in phase_rows
        ])

        prefix = phase.lower()
        results[f"{prefix}_mean_s"] = round(float(np.mean(diffs)), 6)
        results[f"{prefix}_std_s"] = round(
            float(np.sqrt(np.mean(diffs ** 2))), 6)  # RMSE
        results[f"{prefix}_mae_s"] = round(
            float(np.mean(np.abs(diffs))), 6)

    return results


# ======================================================================
# Main
# ======================================================================

def main():
    build_dataset()
    results = compute_metrics()

    with open(f"{OUTPUT_DIR}/results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results.keys()))
        writer.writeheader()
        writer.writerow(results)

    print("Results:")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
