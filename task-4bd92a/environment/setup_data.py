#!/usr/bin/env python3
"""Generate synthetic SeisBench-format dataset for the evaluation pipeline task."""
import numpy as np
import pandas as pd
import h5py
import json
import os

np.random.seed(42)

DATA_DIR = "/app/dataset"
PRED_DIR = "/app/predictions"
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PRED_DIR, exist_ok=True)
os.makedirs("/app/output", exist_ok=True)

TARGET_SR = 100
DEFAULT_NPTS = 12000  # 120 seconds at 100 Hz

PHASE_DICT = {
    "trace_p_arrival_sample": "P",
    "trace_pP_arrival_sample": "P",
    "trace_P_arrival_sample": "P",
    "trace_Pg_arrival_sample": "P",
    "trace_Pn_arrival_sample": "P",
    "trace_s_arrival_sample": "S",
    "trace_S_arrival_sample": "S",
    "trace_Sg_arrival_sample": "S",
    "trace_Sn_arrival_sample": "S",
}

PHASE_COLS = list(PHASE_DICT.keys())

rows = []
tid = 0


def add_trace(split, sr=100, npts=None, comp="ZNE", **phase_arrivals):
    global tid
    if npts is None:
        npts = int(DEFAULT_NPTS * sr / TARGET_SR)
    row = {
        "trace_name": "trace_{:04d}".format(tid),
        "trace_npts": npts,
        "trace_sampling_rate_hz": sr,
        "trace_component_order": comp,
        "split": split,
        "source_magnitude": round(float(np.random.uniform(1.0, 6.0)), 1),
        "station_code": "STA{:02d}".format(np.random.randint(1, 20)),
    }
    for col in PHASE_COLS:
        row[col] = phase_arrivals.get(col, np.nan)
    rows.append(row)
    tid += 1
    return row["trace_name"]


# ===== Category 1: Standard P+S at 100Hz =====
dev_p = [3500, 4200, 2800, 3100, 4800, 3600, 2500, 3900]
dev_s_off = [1500, 2000, 800, 1200, 1000, 1800, 2500, 1400]
for p, so in zip(dev_p, dev_s_off):
    add_trace("dev", trace_p_arrival_sample=p, trace_s_arrival_sample=p + so)

test_p = [3300, 4100, 2700, 3400, 4600, 3700, 2900, 4000]
test_s_off = [1400, 1800, 900, 1100, 1300, 1600, 2200, 1500]
for p, so in zip(test_p, test_s_off):
    add_trace("test", trace_p_arrival_sample=p, trace_s_arrival_sample=p + so)

for _ in range(15):
    p = int(np.random.randint(2500, 5000))
    s = p + int(np.random.randint(500, 2500))
    add_trace("train", trace_p_arrival_sample=p, trace_s_arrival_sample=s)

# ===== Category 2: Variant phase types Pg/Sg/Pn/Sn =====
add_trace("dev", trace_Pg_arrival_sample=3200, trace_Sg_arrival_sample=4800)
add_trace("dev", trace_Pg_arrival_sample=3800, trace_Sn_arrival_sample=5500)
add_trace("dev", trace_Pn_arrival_sample=4000, trace_Sg_arrival_sample=6000)

add_trace("test", trace_Pg_arrival_sample=3500, trace_Sg_arrival_sample=5200)
add_trace("test", trace_P_arrival_sample=3900, trace_S_arrival_sample=5800)
add_trace("test", trace_Pn_arrival_sample=3100, trace_Sn_arrival_sample=4600)

# ===== Category 3: Two distinct P-type arrivals (well separated) =====
add_trace(
    "dev",
    trace_Pg_arrival_sample=3000,
    trace_pP_arrival_sample=3500,
    trace_s_arrival_sample=5500,
)
add_trace(
    "test",
    trace_Pg_arrival_sample=2800,
    trace_pP_arrival_sample=3400,
    trace_Sg_arrival_sample=5800,
)

# ===== Category 4: Close P-S spacing (< 50 samples = 0.5s) =====
add_trace("dev", trace_p_arrival_sample=4000, trace_s_arrival_sample=4030)
add_trace("test", trace_p_arrival_sample=3500, trace_s_arrival_sample=3520)

# ===== Category 5: Noise-only traces =====
add_trace("dev")
add_trace("dev")
add_trace("test")
add_trace("test")

# ===== Category 6: P-only traces =====
add_trace("dev", trace_p_arrival_sample=3500)
add_trace("test", trace_p_arrival_sample=4200)

# ===== Category 7: Different sampling rates =====
# 50 Hz: P@1750 (= 3500 @100Hz), S@2750 (= 5500 @100Hz)
add_trace(
    "dev",
    sr=50,
    npts=6000,
    trace_p_arrival_sample=1750,
    trace_s_arrival_sample=2750,
)
# 200 Hz: P@7000 (= 3500 @100Hz), S@12000 (= 6000 @100Hz)
add_trace(
    "test",
    sr=200,
    npts=24000,
    trace_p_arrival_sample=7000,
    trace_s_arrival_sample=12000,
)

# ===== Category 8: Arrivals near boundaries =====
add_trace("test", trace_p_arrival_sample=200, trace_s_arrival_sample=8000)
add_trace("test", trace_p_arrival_sample=3000, trace_s_arrival_sample=11800)

# ===== Build metadata =====
metadata = pd.DataFrame(rows)
metadata.to_csv("{}/metadata.csv".format(DATA_DIR), index=False)
print("Generated {} traces".format(len(metadata)))
print("Splits: {}".format(metadata["split"].value_counts().to_dict()))

# ===== Generate waveforms with Ricker wavelets at arrivals =====


def make_ricker(f0=5.0, sr=100, hw=50):
    t = np.arange(-hw, hw + 1, dtype=np.float32) / sr
    return (1 - 2 * (np.pi * f0 * t) ** 2) * np.exp(-((np.pi * f0 * t) ** 2))


wavelet = make_ricker()
HW = 50

with h5py.File("{}/waveforms.hdf5".format(DATA_DIR), "w") as f:
    dg = f.create_group("data")
    fg = f.create_group("data_format")
    fg.attrs["dimension_order"] = "CW"
    fg.attrs["component_order"] = "ZNE"

    for _, row in metadata.iterrows():
        npts = int(row["trace_npts"])
        nc = len(row["trace_component_order"])
        wf = np.random.randn(nc, npts).astype(np.float32) * 0.05

        for col in PHASE_COLS:
            v = row.get(col)
            if pd.notna(v):
                s = int(v)
                lo = max(0, s - HW)
                hi = min(npts, s + HW + 1)
                wlo = max(0, HW - s)
                whi = wlo + (hi - lo)
                for c in range(nc):
                    amp = float(np.random.uniform(0.5, 2.0))
                    wf[c, lo:hi] += amp * wavelet[wlo:whi]

        dg.create_dataset(row["trace_name"], data=wf)

# ===== Generate model predictions =====
# Simulates PhaseNet-style output: (3, npts_at_target_sr)
# Channel layout: [Noise, P, S]

with h5py.File("{}/model_output.hdf5".format(PRED_DIR), "w") as f:
    pg = f.create_group("predictions")

    for _, row in metadata.iterrows():
        sr = int(row["trace_sampling_rate_hz"])
        npts = int(row["trace_npts"])
        pred_npts = int(npts * TARGET_SR / sr)

        preds = np.zeros((3, pred_npts), dtype=np.float32)
        preds[0, :] = 0.85
        preds[1, :] = 0.075
        preds[2, :] = 0.075

        sigma = 25.0
        x = np.arange(pred_npts, dtype=np.float32)

        for col in PHASE_COLS:
            v = row.get(col)
            if pd.notna(v):
                sample_at_target = int(int(v) * TARGET_SR / sr)
                phase = PHASE_DICT[col]
                peak = np.exp(
                    -0.5 * ((x - sample_at_target) / sigma) ** 2
                ).astype(np.float32)

                if phase == "P":
                    preds[1] = np.maximum(preds[1], peak * 0.93)
                else:
                    preds[2] = np.maximum(preds[2], peak * 0.93)

        preds[0] = np.maximum(0.02, 1.0 - preds[1] - preds[2])

        noise = np.random.randn(*preds.shape).astype(np.float32) * 0.008
        preds = np.clip(preds + noise, 0.001, 0.999)
        total = preds.sum(axis=0, keepdims=True)
        preds = preds / total

        pg.create_dataset(row["trace_name"], data=preds)

# ===== Save config =====
config = {
    "phase_dict": PHASE_DICT,
    "target_sampling_rate": TARGET_SR,
    "task1_window_seconds": 30,
    "task23_window_seconds": 10,
    "min_phase_spacing_seconds": 0.5,
    "noise_before_events": True,
    "prediction_channels": ["Noise", "P", "S"],
    "scoring": {
        "detection_score": "max(1 - prediction[Noise_channel]) within the evaluation window",
        "phase_discrimination_score": "max(prediction[P_channel]) / max(prediction[S_channel]) within the window; high values indicate P-wave, low values indicate S-wave",
        "p_onset_prediction": "argmax(prediction[P_channel]) within window, reported as absolute sample position (add start_sample)",
        "s_onset_prediction": "argmax(prediction[S_channel]) within window, reported as absolute sample position (add start_sample)",
    },
    "metrics_protocol": {
        "detection": "Use sklearn precision_recall_curve on dev set to find F1-optimal threshold, then evaluate precision/recall/F1 on test set using that threshold. Also compute AUC on both sets.",
        "phase_discrimination": "Use sklearn precision_recall_curve on dev set score_p_or_s values (treating P=positive class) to find F1-optimal threshold, then evaluate on test set.",
        "onset_timing": "For each phase (P, S) separately, compute (predicted_onset - true_onset) / sampling_rate to get error in seconds. Report mean, std (sqrt of mean squared error), and MAE for dev and test sets.",
    },
}

with open("/app/config.json", "w") as f:
    json.dump(config, f, indent=2)

print("Setup complete.")
