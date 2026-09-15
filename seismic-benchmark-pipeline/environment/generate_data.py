#!/usr/bin/env python3
"""Generate synthetic raw seismic data with heterogeneous recording parameters.

Stations have different sampling rates (100 Hz / 200 Hz) and component orderings
(ZNE / ENZ) to simulate a realistic multi-instrument network.
"""

import numpy as np
import json
import os
import csv

np.random.seed(42)

N_EVENTS = 150
N_NOISE = 50
N_STATIONS = 10
TRACE_LENGTH_S = 30

RAW_DIR = "/app/raw_data"
os.makedirs(f"{RAW_DIR}/waveforms", exist_ok=True)
os.makedirs(f"{RAW_DIR}/predictions", exist_ok=True)

# ============================================================
# Events (monotonically increasing origin times)
# ============================================================
events = []
for i in range(N_EVENTS):
    base_day = i * 2 + 1
    month = (base_day - 1) // 30 + 1
    if month > 12:
        month = 12
    day_of_month = ((base_day - 1) % 30) + 1
    if month == 2 and day_of_month > 28:
        day_of_month = 28
    hour = int(np.random.randint(0, 24))
    minute = int(np.random.randint(0, 60))
    second = int(np.random.randint(0, 60))
    ms = int(np.random.randint(0, 1000))
    events.append({
        "event_id": f"ev{i:04d}",
        "latitude": round(float(46.0 + np.random.uniform(-2, 2)), 4),
        "longitude": round(float(8.0 + np.random.uniform(-2, 2)), 4),
        "depth_km": round(float(np.random.uniform(1, 30)), 2),
        "magnitude": round(float(np.random.uniform(1.0, 5.0)), 2),
        "origin_time": f"2020-{month:02d}-{day_of_month:02d}T{hour:02d}:{minute:02d}:{second:02d}.{ms:03d}Z"
    })
events.sort(key=lambda x: x["origin_time"])

# ============================================================
# Stations — heterogeneous sampling rates and component orders
# ============================================================
stations = []
for i in range(N_STATIONS):
    if i < 5:
        sr = 100
        co = "ZNE"
    else:
        sr = 200
        co = "ENZ"
    stations.append({
        "network": "CH",
        "station": f"STA{i:02d}",
        "latitude": round(float(46.0 + np.random.uniform(-3, 3)), 4),
        "longitude": round(float(8.0 + np.random.uniform(-3, 3)), 4),
        "elevation_m": round(float(np.random.uniform(200, 2000)), 1),
        "sampling_rate_hz": sr,
        "component_order": co
    })

# ============================================================
# Waveforms and analyst picks
# ============================================================
waveforms_info = []
picks_data = []

for i, event in enumerate(events):
    n_recs = int(np.random.randint(2, 4))
    station_indices = np.random.choice(N_STATIONS, n_recs, replace=False).tolist()

    # Signal amplitude controls SNR diversity
    if i < 50:
        sig_mult = float(np.random.uniform(0.3, 1.0))     # low SNR
    elif i < 100:
        sig_mult = float(np.random.uniform(1.5, 3.5))     # medium SNR
    else:
        sig_mult = float(np.random.uniform(5.0, 10.0))    # high SNR

    for si in station_indices:
        station = stations[si]
        trace_id = f"{event['event_id']}_{station['station']}"
        sr = station["sampling_rate_hz"]
        co = station["component_order"]
        n_samples = sr * TRACE_LENGTH_S

        waveform = (np.random.randn(3, n_samples) * 0.1).astype(np.float32)

        # P/S arrivals at native sampling rate
        p_sample = int(np.random.randint(int(sr * 5), int(sr * 15)))
        s_sample = int(p_sample + np.random.randint(int(sr * 2), int(sr * 8)))

        sig_len = min(int(sr * 5), n_samples - max(p_sample, s_sample))
        if sig_len > 0:
            t = np.arange(sig_len)
            freq_scale = sr / 100.0
            p_sig = (np.exp(-0.01 * t / freq_scale) *
                     np.sin(2 * np.pi * 5 * t / sr)).astype(np.float32)
            s_sig = (np.exp(-0.008 * t / freq_scale) *
                     np.sin(2 * np.pi * 3 * t / sr)).astype(np.float32)

            if co == "ZNE":
                # Z=0, N=1, E=2
                waveform[0, p_sample:p_sample + sig_len] += p_sig * sig_mult
                waveform[1, s_sample:s_sample + sig_len] += s_sig * sig_mult
                waveform[2, s_sample:s_sample + sig_len] += s_sig * sig_mult
            else:
                # ENZ: E=0, N=1, Z=2
                waveform[2, p_sample:p_sample + sig_len] += p_sig * sig_mult
                waveform[1, s_sample:s_sample + sig_len] += s_sig * sig_mult
                waveform[0, s_sample:s_sample + sig_len] += s_sig * sig_mult

        np.save(f"{RAW_DIR}/waveforms/{trace_id}.npy", waveform)

        waveforms_info.append({
            "trace_id": trace_id,
            "event_id": event["event_id"],
            "station": station["station"],
            "network": station["network"],
            "is_earthquake": True
        })
        picks_data.append({
            "trace_id": trace_id,
            "p_arrival_sample": p_sample,
            "s_arrival_sample": s_sample,
            "sampling_rate_hz": sr
        })

# Noise traces
for i in range(N_NOISE):
    si = int(np.random.randint(0, N_STATIONS))
    station = stations[si]
    trace_id = f"noise{i:04d}_{station['station']}"
    sr = station["sampling_rate_hz"]
    n_samples = sr * TRACE_LENGTH_S
    waveform = (np.random.randn(3, n_samples) * 0.1).astype(np.float32)
    np.save(f"{RAW_DIR}/waveforms/{trace_id}.npy", waveform)
    waveforms_info.append({
        "trace_id": trace_id,
        "event_id": None,
        "station": station["station"],
        "network": station["network"],
        "is_earthquake": False
    })

# ============================================================
# Temporal split assignment
# ============================================================
event_ids = [e["event_id"] for e in events]
n_train = int(N_EVENTS * 0.6)   # 90
n_dev = int(N_EVENTS * 0.2)     # 30

train_events = set(event_ids[:n_train])
dev_events = set(event_ids[n_train:n_train + n_dev])
test_events = set(event_ids[n_train + n_dev:])

noise_traces = [w for w in waveforms_info if not w["is_earthquake"]]
np.random.shuffle(noise_traces)
n_nd = len(noise_traces) // 3
n_nt = len(noise_traces) // 3
noise_dev_ids = set(t["trace_id"] for t in noise_traces[:n_nd])
noise_test_ids = set(t["trace_id"] for t in noise_traces[n_nd:n_nd + n_nt])

split_map = {}
for w in waveforms_info:
    if w["is_earthquake"]:
        if w["event_id"] in train_events:
            split_map[w["trace_id"]] = "train"
        elif w["event_id"] in dev_events:
            split_map[w["trace_id"]] = "dev"
        else:
            split_map[w["trace_id"]] = "test"
    else:
        if w["trace_id"] in noise_dev_ids:
            split_map[w["trace_id"]] = "dev"
        elif w["trace_id"] in noise_test_ids:
            split_map[w["trace_id"]] = "test"
        else:
            split_map[w["trace_id"]] = "train"

# ============================================================
# Prediction CSVs
# ============================================================
# Task 1 — detection
for split_name, event_set, noise_set in [
    ("dev", dev_events, noise_dev_ids),
    ("test", test_events, noise_test_ids)
]:
    rows = []
    for w in waveforms_info:
        if w["is_earthquake"] and w["event_id"] in event_set:
            score = float(np.clip(np.random.normal(0.82, 0.15), 0.01, 0.99))
            rows.append({"trace_name": w["trace_id"],
                         "score_detection": round(score, 4),
                         "true_label": 1})
        elif not w["is_earthquake"] and w["trace_id"] in noise_set:
            score = float(np.clip(np.random.normal(0.18, 0.15), 0.01, 0.99))
            rows.append({"trace_name": w["trace_id"],
                         "score_detection": round(score, 4),
                         "true_label": 0})
    with open(f"{RAW_DIR}/predictions/task1_{split_name}.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "trace_name", "score_detection", "true_label"])
        writer.writeheader()
        writer.writerows(rows)

# Task 23 — phase picking and onset timing
pick_map = {p["trace_id"]: p for p in picks_data}
for split_name, event_set in [("dev", dev_events), ("test", test_events)]:
    rows = []
    for w in waveforms_info:
        if not w["is_earthquake"] or w["event_id"] not in event_set:
            continue
        pick = pick_map[w["trace_id"]]
        p_sample = pick["p_arrival_sample"]
        s_sample = pick["s_arrival_sample"]
        sr = pick["sampling_rate_hz"]

        # P row (with positive bias in prediction)
        p_pred_offset = int(np.random.normal(8, 5))
        score_p = float(np.clip(np.random.normal(0.88, 0.10), 0.01, 0.99))
        rows.append({
            "trace_name": w["trace_id"],
            "phase_label": "P",
            "score_p_or_s": round(score_p, 4),
            "p_sample_pred": p_sample + p_pred_offset,
            "s_sample_pred": s_sample + int(np.random.normal(10, 8)),
            "phase_onset": p_sample,
            "sampling_rate": sr
        })

        # S row (with positive bias in prediction)
        s_pred_offset = int(np.random.normal(10, 8))
        score_s = float(np.clip(np.random.normal(0.12, 0.10), 0.01, 0.99))
        rows.append({
            "trace_name": w["trace_id"],
            "phase_label": "S",
            "score_p_or_s": round(score_s, 4),
            "p_sample_pred": p_sample + int(np.random.normal(8, 5)),
            "s_sample_pred": s_sample + s_pred_offset,
            "phase_onset": s_sample,
            "sampling_rate": sr
        })

    with open(f"{RAW_DIR}/predictions/task23_{split_name}.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "trace_name", "phase_label", "score_p_or_s",
            "p_sample_pred", "s_sample_pred", "phase_onset", "sampling_rate"
        ])
        writer.writeheader()
        writer.writerows(rows)

# ============================================================
# Save JSON metadata
# ============================================================
for fname, data in [
    ("events.json", events),
    ("stations.json", stations),
    ("waveforms_info.json", waveforms_info),
    ("picks.json", picks_data),
    ("split_assignment.json", split_map)
]:
    with open(f"{RAW_DIR}/{fname}", "w") as f:
        json.dump(data, f, indent=2)

# ============================================================
# Validate generated data
# ============================================================
with open(f"{RAW_DIR}/stations.json") as f:
    check_stations = json.load(f)
station_names = set()
for s in check_stations:
    assert "sampling_rate_hz" in s, f"Station {s.get('station','?')} missing sampling_rate_hz, keys: {list(s.keys())}"
    assert "component_order" in s, f"Station {s.get('station','?')} missing component_order, keys: {list(s.keys())}"
    assert "station" in s, f"Station entry missing 'station' key: {list(s.keys())}"
    station_names.add(s["station"])

with open(f"{RAW_DIR}/waveforms_info.json") as f:
    check_winfo = json.load(f)
for w in check_winfo:
    assert w["station"] in station_names, f"Waveform {w['trace_id']} references unknown station {w['station']}"

eq_count = sum(1 for w in check_winfo if w["is_earthquake"])
print(f"Generated {eq_count} earthquake + {N_NOISE} noise = {len(check_winfo)} total")
print(f"Train: {sum(1 for v in split_map.values() if v == 'train')}, "
      f"Dev: {sum(1 for v in split_map.values() if v == 'dev')}, "
      f"Test: {sum(1 for v in split_map.values() if v == 'test')}")
print(f"Validation passed: {len(check_stations)} stations OK, {len(check_winfo)} waveforms linked")
