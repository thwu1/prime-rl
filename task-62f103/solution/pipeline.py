#!/usr/bin/env python3
"""
Eurobench gait analysis PI computation pipeline with reliability assessment.

"""

import os
import re
import csv
import yaml
import numpy as np
from scipy.signal import butter, filtfilt


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_joint_angles(path):
    with open(path) as f:
        headers = [h.strip() for h in f.readline().split(";")]
        rows = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append([float(v.strip()) for v in line.split(";")])
    arr = np.array(rows)
    return {h: arr[:, i] for i, h in enumerate(headers)}


def load_gait_events(path):
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Gait event cleaning
# ---------------------------------------------------------------------------

def clean_events(events_list, min_interval=0.05, min_stride=0.4, max_stride=3.0):
    """Validate and clean gait event timestamps.

    Handles: temporal ordering errors, exact/near duplicates, phantom events.
    """
    events = sorted(events_list)

    # Remove duplicates and near-duplicates (sensor bounce)
    deduped = [events[0]]
    for i in range(1, len(events)):
        if events[i] - deduped[-1] >= min_interval:
            deduped.append(events[i])

    # Remove events creating physiologically impossible strides
    valid = [deduped[0]]
    for i in range(1, len(deduped)):
        stride = deduped[i] - valid[-1]
        if min_stride <= stride <= max_stride:
            valid.append(deduped[i])

    return valid


# ---------------------------------------------------------------------------
# Signal processing
# ---------------------------------------------------------------------------

def butterworth_lowpass(signal, cutoff_hz, fs, order=4):
    nyq = 0.5 * fs
    b, a = butter(order, cutoff_hz / nyq, btype="low")
    return filtfilt(b, a, signal)


def residual_analysis(signal, fs, order=4):
    """Determine optimal filter cutoff via Winter's residual analysis.

    Sweeps cutoff frequencies, computes RMS residuals, and finds the
    knee point using piecewise linear regression.
    """
    cutoff_range = np.arange(1.0, 25.0, 0.5)
    nyq = 0.5 * fs
    freqs = []
    resids = []

    for fc in cutoff_range:
        if fc >= nyq:
            break
        filtered = butterworth_lowpass(signal, fc, fs, order)
        residual = np.sqrt(np.mean((signal - filtered) ** 2))
        freqs.append(fc)
        resids.append(residual)

    freqs = np.array(freqs)
    resids = np.array(resids)

    # Find knee point via piecewise linear fit
    best_fc = 6.0  # fallback
    best_mse = float('inf')

    for i in range(2, len(freqs) - 2):
        x1, y1 = freqs[:i+1], resids[:i+1]
        x2, y2 = freqs[i:], resids[i:]

        m1 = np.polyfit(x1, y1, 1)
        m2 = np.polyfit(x2, y2, 1)

        r1 = y1 - np.polyval(m1, x1)
        r2 = y2 - np.polyval(m2, x2)

        mse = (np.sum(r1**2) + np.sum(r2**2)) / (len(r1) + len(r2))

        if mse < best_mse:
            best_mse = mse
            best_fc = freqs[i]

    return float(best_fc)


# ---------------------------------------------------------------------------
# Per-cycle metrics
# ---------------------------------------------------------------------------

def rom_per_cycle(signal, t, heel_strikes):
    roms = []
    n = len(heel_strikes)
    for i in range(1, n - 2):
        hs1, hs2 = heel_strikes[i], heel_strikes[i + 1]
        mask = (t >= hs1) & (t < hs2)
        if np.sum(mask) < 5:
            continue
        seg = signal[mask]
        roms.append(float(np.max(seg) - np.min(seg)))
    return roms


def stride_times(heel_strikes):
    n = len(heel_strikes)
    return [heel_strikes[i + 1] - heel_strikes[i] for i in range(1, n - 2)]


def step_times(hs_from, hs_to):
    steps = []
    j = 0
    n = len(hs_from)
    for i in range(1, n - 2):
        while j < len(hs_to) and hs_to[j] <= hs_from[i]:
            j += 1
        if j < len(hs_to):
            steps.append(hs_to[j] - hs_from[i])
    return steps


def stance_ratios(r_hs, r_to):
    ratios = []
    n = len(r_hs)
    for i in range(1, n - 2):
        stride = r_hs[i + 1] - r_hs[i]
        if i < len(r_to) and stride > 0:
            stance = r_to[i] - r_hs[i]
            ratios.append(stance / stride * 100.0)
    return ratios


# ---------------------------------------------------------------------------
# Aggregate helpers
# ---------------------------------------------------------------------------

def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def symmetry_index(vals_r, vals_l):
    mr, ml = np.mean(vals_r), np.mean(vals_l)
    denom = 0.5 * (mr + ml)
    if denom == 0:
        return 0.0
    return abs(mr - ml) / denom * 100.0


def compute_sal(cadence, avg_knee_rom, knee_sym, stride_cv):
    nc = clamp((cadence - 60.0) / 60.0, 0, 1)
    nr = clamp((avg_knee_rom - 20.0) / 50.0, 0, 1)
    ns = clamp(1.0 - knee_sym / 100.0, 0, 1)
    nv = clamp(1.0 - stride_cv / 0.20, 0, 1)
    return 0.30 * nc + 0.25 * nr + 0.25 * ns + 0.20 * nv


# ---------------------------------------------------------------------------
# ICC and reliability
# ---------------------------------------------------------------------------

def compute_icc_21(data_matrix):
    """ICC(2,1): two-way random effects, single measures, absolute agreement.

    data_matrix: shape (n, k) — n contexts (subject x condition), k runs.
    Returns (icc, ms_error).
    """
    n, k = data_matrix.shape
    grand_mean = np.mean(data_matrix)

    row_means = np.mean(data_matrix, axis=1)
    col_means = np.mean(data_matrix, axis=0)

    ss_rows = k * np.sum((row_means - grand_mean) ** 2)
    ss_cols = n * np.sum((col_means - grand_mean) ** 2)
    ss_total = np.sum((data_matrix - grand_mean) ** 2)
    ss_error = ss_total - ss_rows - ss_cols

    df_rows = n - 1
    df_cols = k - 1
    df_error = (n - 1) * (k - 1)

    ms_rows = ss_rows / df_rows if df_rows > 0 else 0
    ms_cols = ss_cols / df_cols if df_cols > 0 else 0
    ms_error = ss_error / df_error if df_error > 0 else 0

    numerator = ms_rows - ms_error
    denominator = ms_rows + (k - 1) * ms_error + k * (ms_cols - ms_error) / n

    if denominator <= 0:
        return 0.0, ms_error

    icc = numerator / denominator
    return max(0.0, min(1.0, icc)), ms_error


# ---------------------------------------------------------------------------
# Single-run processing
# ---------------------------------------------------------------------------

JOINT_COLS = [
    "hip_flexion_r", "hip_flexion_l",
    "knee_flexion_r", "knee_flexion_l",
    "ankle_flexion_r", "ankle_flexion_l",
]
FS = 100


def process_run(data_dir, subj, cond, run, out_dir, cutoff_hz):
    prefix = f"subject_{subj}_cond_{cond}_run_{run}"

    angles = load_joint_angles(os.path.join(data_dir, f"{prefix}_jointAngles.csv"))
    events = load_gait_events(os.path.join(data_dir, f"{prefix}_gaitEvents.yaml"))
    t = angles["time"]

    # Clean gait events
    r_hs = clean_events(events["r_heel_strike"])
    l_hs = clean_events(events["l_heel_strike"])
    r_to = clean_events(events["r_toe_off"])

    # Filter
    filtered = {}
    for col in JOINT_COLS:
        filtered[col] = butterworth_lowpass(angles[col], cutoff_hz, FS)

    # Per-cycle PIs — right side keyed by right HS
    hip_rom_r = rom_per_cycle(filtered["hip_flexion_r"], t, r_hs)
    knee_rom_r = rom_per_cycle(filtered["knee_flexion_r"], t, r_hs)
    ankle_rom_r = rom_per_cycle(filtered["ankle_flexion_r"], t, r_hs)

    # Left side keyed by left HS
    hip_rom_l = rom_per_cycle(filtered["hip_flexion_l"], t, l_hs)
    knee_rom_l = rom_per_cycle(filtered["knee_flexion_l"], t, l_hs)
    ankle_rom_l = rom_per_cycle(filtered["ankle_flexion_l"], t, l_hs)

    st = stride_times(r_hs)
    st_r = step_times(r_hs, l_hs)
    st_l = step_times(l_hs, r_hs)
    sr = stance_ratios(r_hs, r_to)

    mean_stride = float(np.mean(st))
    cadence = 120.0 / mean_stride
    cv = float(np.std(st) / mean_stride)
    k_sym = float(symmetry_index(knee_rom_r, knee_rom_l))
    s_sym = float(symmetry_index(st_r, st_l)) if st_r and st_l else 0.0
    avg_knee = (float(np.mean(knee_rom_r)) + float(np.mean(knee_rom_l))) / 2.0
    sal = compute_sal(cadence, avg_knee, k_sym, cv)

    result = {
        "hip_rom_r": {"mean": float(np.mean(hip_rom_r)), "std": float(np.std(hip_rom_r))},
        "hip_rom_l": {"mean": float(np.mean(hip_rom_l)), "std": float(np.std(hip_rom_l))},
        "knee_rom_r": {"mean": float(np.mean(knee_rom_r)), "std": float(np.std(knee_rom_r))},
        "knee_rom_l": {"mean": float(np.mean(knee_rom_l)), "std": float(np.std(knee_rom_l))},
        "ankle_rom_r": {"mean": float(np.mean(ankle_rom_r)), "std": float(np.std(ankle_rom_r))},
        "ankle_rom_l": {"mean": float(np.mean(ankle_rom_l)), "std": float(np.std(ankle_rom_l))},
        "stride_time": {"mean": mean_stride, "std": float(np.std(st))},
        "step_time_r": {"mean": float(np.mean(st_r)), "std": float(np.std(st_r))},
        "step_time_l": {"mean": float(np.mean(st_l)), "std": float(np.std(st_l))},
        "stance_ratio_r": {"mean": float(np.mean(sr)), "std": float(np.std(sr))},
        "cadence": float(cadence),
        "stride_time_cv": cv,
        "knee_rom_symmetry": k_sym,
        "step_time_symmetry": s_sym,
    }

    out_path = os.path.join(out_dir, f"{prefix}_pi.yaml")
    with open(out_path, "w") as f:
        yaml.dump(result, f, default_flow_style=False)

    return result, sal


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    data_dir = "/app/data"
    out_dir = "/app/output"
    os.makedirs(out_dir, exist_ok=True)

    # Discover runs
    pat = re.compile(r"subject_(\d+)_cond_(\d+)_run_(\d+)_jointAngles\.csv")
    runs = sorted(
        (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        for f in os.listdir(data_dir)
        if (m := pat.match(f))
    )

    # Determine optimal filter cutoff via residual analysis
    first_subj, first_cond, first_run = runs[0]
    first_prefix = f"subject_{first_subj}_cond_{first_cond}_run_{first_run}"
    first_angles = load_joint_angles(
        os.path.join(data_dir, f"{first_prefix}_jointAngles.csv")
    )
    cutoff_hz = residual_analysis(first_angles["knee_flexion_r"], FS)
    print(f"Determined optimal filter cutoff: {cutoff_hz:.1f} Hz")

    all_results = {}
    sal_rows = []
    for subj, cond, run in runs:
        result, sal = process_run(data_dir, subj, cond, run, out_dir, cutoff_hz)
        all_results[(subj, cond, run)] = result
        sal_rows.append((subj, cond, run, sal))

    # --- SAL scores CSV ---
    with open(os.path.join(out_dir, "sal_scores.csv"), "w", newline="") as f:
        f.write("subject;condition;run;sal_score\n")
        for subj, cond, run, sal in sal_rows:
            f.write(f"{subj};{cond};{run};{sal:.6f}\n")

    # --- Condition comparison CSV ---
    metrics = ["cadence", "knee_rom_r", "knee_rom_l", "stride_time_cv",
               "knee_rom_symmetry"]
    with open(os.path.join(out_dir, "condition_comparison.csv"), "w",
              newline="") as f:
        f.write("metric;cond_1_mean;cond_1_std;cond_2_mean;cond_2_std;"
                "pct_change;direction\n")
        for metric in metrics:
            c1, c2 = [], []
            for (subj, cond, run), res in all_results.items():
                val = (res[metric] if isinstance(res[metric], (int, float))
                       else res[metric]["mean"])
                (c1 if cond == 1 else c2).append(val)
            m1, s1 = np.mean(c1), np.std(c1)
            m2, s2 = np.mean(c2), np.std(c2)
            pct = (m2 - m1) / m1 * 100 if m1 != 0 else 0.0
            direction = ("increased" if pct > 5
                         else ("decreased" if pct < -5 else "unchanged"))
            f.write(f"{metric};{m1:.6f};{s1:.6f};{m2:.6f};{s2:.6f};"
                    f"{pct:.4f};{direction}\n")

    # --- Reliability analysis ---
    contexts = sorted(set((s, c) for s, c, r in runs))
    n_runs = max(r for s, c, r in runs)

    reliability_metrics = [
        "knee_rom_r", "knee_rom_l", "hip_rom_r", "hip_rom_l",
        "ankle_rom_r", "ankle_rom_l", "stride_time", "cadence",
        "stride_time_cv", "knee_rom_symmetry",
    ]

    reliability_rows = []
    for metric in reliability_metrics:
        matrix = np.zeros((len(contexts), n_runs))
        for i, (subj, cond) in enumerate(contexts):
            for j in range(n_runs):
                run = j + 1
                res = all_results.get((subj, cond, run))
                if res is None:
                    continue
                val = (res[metric] if isinstance(res[metric], (int, float))
                       else res[metric]["mean"])
                matrix[i, j] = val

        icc, ms_error = compute_icc_21(matrix)
        sem = np.sqrt(ms_error)
        mdc95 = sem * 1.96 * np.sqrt(2)

        if icc >= 0.90:
            quality = "excellent"
        elif icc >= 0.75:
            quality = "good"
        elif icc >= 0.50:
            quality = "moderate"
        else:
            quality = "poor"

        reliability_rows.append({
            "metric": metric,
            "icc": icc,
            "sem": sem,
            "mdc95": mdc95,
            "quality_level": quality,
        })

    # Write reliability report
    with open(os.path.join(out_dir, "reliability_report.csv"), "w",
              newline="") as f:
        f.write("metric;icc;sem;mdc95\n")
        for row in reliability_rows:
            f.write(f"{row['metric']};{row['icc']:.6f};"
                    f"{row['sem']:.6f};{row['mdc95']:.6f}\n")

    # Write quality classification
    with open(os.path.join(out_dir, "quality_classification.csv"), "w",
              newline="") as f:
        f.write("metric;icc;quality_level\n")
        for row in reliability_rows:
            f.write(f"{row['metric']};{row['icc']:.6f};"
                    f"{row['quality_level']}\n")

    # --- Pipeline entry point ---
    script = "#!/bin/bash\npython3 /app/pipeline.py\n"
    with open("/app/run_pipeline.sh", "w") as f:
        f.write(script)
    os.chmod("/app/run_pipeline.sh", 0o755)

    print("Pipeline complete. Results in /app/output/")


if __name__ == "__main__":
    main()
