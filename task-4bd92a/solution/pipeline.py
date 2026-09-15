#!/usr/bin/env python3
"""
Reference solution for the SeisBench pick-benchmark evaluation pipeline task.
Implements evaluation target generation, prediction scoring, and metric computation
following the SeisBench pick-benchmark protocol.
"""

import numpy as np
import pandas as pd
import h5py
import json
import os
from sklearn.metrics import (
    precision_recall_curve,
    precision_recall_fscore_support,
    roc_auc_score,
)


def load_config():
    with open("/app/config.json") as f:
        return json.load(f)


def load_metadata():
    return pd.read_csv("/app/dataset/metadata.csv")


def get_arrivals(row, phase_dict, target_sr):
    """
    Extract all phase arrivals from a trace, convert to target sampling rate,
    and return sorted list of (sample_at_target_sr, phase_type, full_phase_label).
    """
    sr = row["trace_sampling_rate_hz"]
    npts_at_target = int(row["trace_npts"] * target_sr / sr)
    arrivals = []
    for col, phase_type in phase_dict.items():
        if col in row.index and pd.notna(row[col]):
            sample = int(row[col])
            sample_at_target = int(sample * target_sr / sr)
            if 0 <= sample_at_target < npts_at_target:
                # Extract the specific phase name from column:
                # e.g., "trace_Pg_arrival_sample" → "Pg"
                full_label = col.split("_")[1]
                arrivals.append((sample_at_target, phase_type, full_label))
    arrivals.sort()
    return arrivals


def select_window_containing(npts, windowlen, containing=None, bounds=(100, 100)):
    """
    Select a random window from a trace, optionally containing a specific sample.
    Matches the SeisBench pick-benchmark windowing algorithm.
    """
    if npts <= windowlen:
        return 0, npts

    if containing is None:
        start = np.random.randint(0, npts - windowlen + 1)
        return start, start + windowlen

    earliest_start = max(0, containing - windowlen + bounds[1])
    latest_start = min(npts - windowlen, containing - bounds[0])

    if latest_start <= earliest_start:
        return 0, npts

    start = np.random.randint(earliest_start, latest_start + 1)
    return start, start + windowlen


def generate_task1(metadata, phase_dict, target_sr, noise_before_events=True):
    """Generate earthquake detection evaluation targets (30-second windows)."""
    np.random.seed(42)
    windowlen = 30 * target_sr
    labels = []

    eval_data = metadata[metadata["split"].isin(["dev", "test"])].reset_index(drop=True)

    for idx in range(len(eval_data)):
        row = eval_data.iloc[idx]
        sr = row["trace_sampling_rate_hz"]
        npts_target = int(row["trace_npts"] * target_sr / sr)
        trace_split = row["split"]

        arrivals = get_arrivals(row, phase_dict, target_sr)

        if len(arrivals) == 0:
            # Noise-only trace
            start, end = select_window_containing(npts_target, windowlen)
            sample = {
                "trace_name": row["trace_name"],
                "trace_idx": idx,
                "trace_split": trace_split,
                "sampling_rate": target_sr,
                "start_sample": start,
                "end_sample": end,
                "trace_type": "noise",
            }
            labels.append(sample)
        else:
            first_arrival = arrivals[0][0]

            # Earthquake window containing first arrival
            start, end = select_window_containing(
                npts_target, windowlen, containing=first_arrival
            )
            if end - start <= windowlen:
                sample = {
                    "trace_name": row["trace_name"],
                    "trace_idx": idx,
                    "trace_split": trace_split,
                    "sampling_rate": target_sr,
                    "start_sample": start,
                    "end_sample": end,
                    "trace_type": "earthquake",
                }
                labels.append(sample)

            # Noise window before first arrival
            if noise_before_events and first_arrival > windowlen:
                start, end = select_window_containing(
                    min(npts_target, first_arrival), windowlen
                )
                if end - start <= windowlen:
                    sample = {
                        "trace_name": row["trace_name"],
                        "trace_idx": idx,
                        "trace_split": trace_split,
                        "sampling_rate": target_sr,
                        "start_sample": start,
                        "end_sample": end,
                        "trace_type": "noise",
                    }
                    labels.append(sample)

    df = pd.DataFrame(labels)
    # Filter out very short windows
    diff = df["end_sample"] - df["start_sample"]
    df = df[diff > 100]
    return df


def generate_task23(metadata, phase_dict, target_sr):
    """Generate phase picking evaluation targets (10-second windows with isolated onsets)."""
    np.random.seed(42)
    windowlen = 10 * target_sr
    min_spacing = int(0.5 * target_sr)
    labels = []

    eval_data = metadata[metadata["split"].isin(["dev", "test"])].reset_index(drop=True)

    for idx in range(len(eval_data)):
        row = eval_data.iloc[idx]
        sr = row["trace_sampling_rate_hz"]
        npts_target = int(row["trace_npts"] * target_sr / sr)
        trace_split = row["split"]

        arrivals = get_arrivals(row, phase_dict, target_sr)

        if len(arrivals) == 0:
            continue

        for i, (onset, phase, full_phase) in enumerate(arrivals):
            # Compute isolation bounds
            if i == 0:
                onset_before = 0
            else:
                onset_before = int(arrivals[i - 1][0]) + min_spacing

            if i == len(arrivals) - 1:
                onset_after = float("inf")
            else:
                onset_after = int(arrivals[i + 1][0]) - min_spacing

            # Check if pick can be isolated
            if (onset_after - onset_before < windowlen or
                    onset_before > onset or onset_after < onset):
                continue

            onset_after_clamped = npts_target if np.isinf(onset_after) else min(int(onset_after), npts_target)

            # Window within isolation bounds
            start, end = select_window_containing(
                int(onset_after_clamped - onset_before),
                windowlen=windowlen,
                containing=onset - onset_before,
                bounds=(50, 50),
            )
            start += onset_before
            end += onset_before

            if end - start <= windowlen:
                sample = {
                    "trace_name": row["trace_name"],
                    "trace_idx": idx,
                    "trace_split": trace_split,
                    "sampling_rate": target_sr,
                    "start_sample": start,
                    "end_sample": end,
                    "phase_label": phase,
                    "full_phase_label": full_phase,
                    "phase_onset": onset,
                }
                labels.append(sample)

    df = pd.DataFrame(labels)
    if len(df) > 0:
        diff = df["end_sample"] - df["start_sample"]
        df = df[diff > 100]
    return df


def score_predictions(task1_targets, task23_targets, pred_file):
    """Score model predictions against evaluation targets."""
    task1_scored = task1_targets.copy()
    task23_scored = task23_targets.copy()

    with h5py.File(pred_file, "r") as f:
        preds_group = f["predictions"]

        # Score task 1: detection
        if len(task1_scored) > 0:
            scores = []
            for _, row in task1_scored.iterrows():
                pred = preds_group[row["trace_name"]][:]
                start = int(row["start_sample"])
                end = int(row["end_sample"])
                local_pred = pred[:, start:end]
                # Detection score: max(1 - Noise_channel) within window
                # Channel 0 = Noise
                score = float(np.max(1.0 - local_pred[0]))
                scores.append(score)
            task1_scored["score_detection"] = scores

        # Score task 23: phase discrimination and onset
        if len(task23_scored) > 0:
            score_p_or_s = []
            p_preds = []
            s_preds = []

            for _, row in task23_scored.iterrows():
                pred = preds_group[row["trace_name"]][:]
                start = int(row["start_sample"])
                end = int(row["end_sample"])
                local_pred = pred[:, start:end]

                # P/S discrimination: max(P) / max(S)
                # Channel 1 = P, Channel 2 = S
                max_p = float(np.max(local_pred[1]))
                max_s = float(np.max(local_pred[2]))
                ratio = max_p / max_s if max_s > 0 else float("inf")
                score_p_or_s.append(ratio)

                # Onset predictions: argmax within window + start
                p_preds.append(int(np.argmax(local_pred[1])) + start)
                s_preds.append(int(np.argmax(local_pred[2])) + start)

            task23_scored["score_p_or_s"] = score_p_or_s
            task23_scored["p_sample_pred"] = p_preds
            task23_scored["s_sample_pred"] = s_preds

    return task1_scored, task23_scored


def compute_metrics(task1_scored, task23_scored, target_sr):
    """Compute benchmark metrics following pick-benchmark protocol."""
    metrics = {}

    # ---- Task 1: Detection ----
    if len(task1_scored) > 0 and "score_detection" in task1_scored.columns:
        task1_scored = task1_scored.copy()
        task1_scored["trace_type_bin"] = (
            task1_scored["trace_type"] == "earthquake"
        ).astype(int)

        dev_data = task1_scored[task1_scored["trace_split"] == "dev"]
        test_data = task1_scored[task1_scored["trace_split"] == "test"]

        # Dev: find F1-optimal threshold
        if len(dev_data) > 0 and dev_data["trace_type_bin"].nunique() > 1:
            prec, recall, thr = precision_recall_curve(
                dev_data["trace_type_bin"], dev_data["score_detection"]
            )
            f1 = 2 * prec * recall / (prec + recall + 1e-10)
            opt_idx = np.nanargmax(f1)
            opt_thr = float(thr[opt_idx])

            metrics["dev_det_precision"] = float(prec[opt_idx])
            metrics["dev_det_recall"] = float(recall[opt_idx])
            metrics["dev_det_f1"] = float(f1[opt_idx])
            metrics["det_threshold"] = opt_thr
            metrics["dev_det_auc"] = float(
                roc_auc_score(dev_data["trace_type_bin"], dev_data["score_detection"])
            )

        # Test: evaluate with dev-optimized threshold
        if len(test_data) > 0 and test_data["trace_type_bin"].nunique() > 1:
            det_thr = metrics.get("det_threshold", 0.5)
            prec, recall, f1, _ = precision_recall_fscore_support(
                test_data["trace_type_bin"],
                (test_data["score_detection"] > det_thr).astype(int),
                average="binary",
            )
            metrics["test_det_precision"] = float(prec)
            metrics["test_det_recall"] = float(recall)
            metrics["test_det_f1"] = float(f1)
            metrics["test_det_auc"] = float(
                roc_auc_score(
                    test_data["trace_type_bin"], test_data["score_detection"]
                )
            )

    # ---- Task 2: Phase discrimination ----
    if len(task23_scored) > 0 and "score_p_or_s" in task23_scored.columns:
        task23_scored = task23_scored.copy()
        task23_scored["phase_label_bin"] = (
            task23_scored["phase_label"] == "P"
        ).astype(int)

        dev_data = task23_scored[task23_scored["trace_split"] == "dev"]
        test_data = task23_scored[task23_scored["trace_split"] == "test"]

        # Clip extreme values
        dev_restricted = dev_data[
            ~np.isnan(dev_data["score_p_or_s"]) & ~np.isinf(dev_data["score_p_or_s"])
        ].copy()
        test_restricted = test_data[
            ~np.isnan(test_data["score_p_or_s"])
            & ~np.isinf(test_data["score_p_or_s"])
        ].copy()

        dev_restricted["score_p_or_s"] = np.clip(
            dev_restricted["score_p_or_s"].values, -1e100, 1e100
        )
        test_restricted["score_p_or_s"] = np.clip(
            test_restricted["score_p_or_s"].values, -1e100, 1e100
        )

        if (
            len(dev_restricted) > 0
            and dev_restricted["phase_label_bin"].nunique() > 1
        ):
            prec, recall, thr = precision_recall_curve(
                dev_restricted["phase_label_bin"],
                dev_restricted["score_p_or_s"],
            )
            f1 = 2 * prec * recall / (prec + recall + 1e-10)
            opt_idx = np.nanargmax(f1)
            opt_thr = float(thr[opt_idx])

            metrics["dev_phase_precision"] = float(prec[opt_idx])
            metrics["dev_phase_recall"] = float(recall[opt_idx])
            metrics["dev_phase_f1"] = float(f1[opt_idx])
            metrics["phase_threshold"] = opt_thr

        if (
            len(test_restricted) > 0
            and test_restricted["phase_label_bin"].nunique() > 1
        ):
            phase_thr = metrics.get("phase_threshold", 1.0)
            prec, recall, f1, _ = precision_recall_fscore_support(
                test_restricted["phase_label_bin"],
                (test_restricted["score_p_or_s"] > phase_thr).astype(int),
                average="binary",
            )
            metrics["test_phase_precision"] = float(prec)
            metrics["test_phase_recall"] = float(recall)
            metrics["test_phase_f1"] = float(f1)

        # ---- Task 3: Onset timing ----
        for split_name, pred_data in [("dev", dev_data), ("test", test_data)]:
            for phase in ["P", "S"]:
                phase_data = pred_data[pred_data["phase_label"] == phase]
                if len(phase_data) == 0:
                    continue

                pred_col = "{}_sample_pred".format(phase.lower())
                if pred_col not in phase_data.columns:
                    continue

                diff = (
                    phase_data[pred_col] - phase_data["phase_onset"]
                ) / phase_data["sampling_rate"]

                metrics["{0}_{1}_mean_s".format(split_name, phase)] = float(
                    np.mean(diff)
                )
                metrics["{0}_{1}_std_s".format(split_name, phase)] = float(
                    np.sqrt(np.mean(diff**2))
                )
                metrics["{0}_{1}_mae_s".format(split_name, phase)] = float(
                    np.mean(np.abs(diff))
                )

    return metrics


def main():
    config = load_config()
    metadata = load_metadata()
    phase_dict = config["phase_dict"]
    target_sr = config["target_sampling_rate"]

    # Generate evaluation targets
    task1 = generate_task1(
        metadata,
        phase_dict,
        target_sr,
        noise_before_events=config.get("noise_before_events", True),
    )
    task23 = generate_task23(metadata, phase_dict, target_sr)

    # Save targets
    os.makedirs("/app/output", exist_ok=True)
    task1.to_csv("/app/output/task1_targets.csv", index=False)
    task23.to_csv("/app/output/task23_targets.csv", index=False)

    print("Task 1 targets: {} rows".format(len(task1)))
    print("Task 23 targets: {} rows".format(len(task23)))

    # Score predictions
    task1_scored, task23_scored = score_predictions(
        task1, task23, "/app/predictions/model_output.hdf5"
    )

    # Compute metrics
    metrics = compute_metrics(task1_scored, task23_scored, target_sr)

    with open("/app/output/metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    print("Metrics:")
    for k, v in sorted(metrics.items()):
        print("  {}: {:.4f}".format(k, v))


if __name__ == "__main__":
    main()
