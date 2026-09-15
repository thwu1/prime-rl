#!/usr/bin/env python3

"""
Solution: Seismic network calibration with robust outlier detection.

Approach:
1. Explore data and discover ObsPy's TauP module for travel time computation.
2. Compute theoretical times for candidate 1D velocity models.
3. Detect outliers via iterative MAD-based robust estimation.
4. Select best-fitting model on clean data.
5. Estimate station corrections excluding outliers.
6. Compute azimuthal gap quality metrics.
"""

import json
import numpy as np
from obspy.taup import TauPyModel
from obspy.geodetics import locations2degrees, gps2dist_azimuth

# ---- Load data ----
with open("/app/data/stations.json") as f:
    stations = json.load(f)
with open("/app/data/events.json") as f:
    events = json.load(f)
with open("/app/data/observations.json") as f:
    observations = json.load(f)

# ---- Compute theoretical travel times for all candidate models ----
model_names = ["iasp91", "ak135", "prem"]
taup_models = {name: TauPyModel(model=name) for name in model_names}

# theoretical[model_name][obs_index] = predicted travel time
theoretical = {m: {} for m in model_names}

for model_name, model in taup_models.items():
    for i, obs in enumerate(observations):
        ev = events[obs["event_id"]]
        st = stations[obs["station"]]
        dist = float(locations2degrees(ev["lat"], ev["lon"], st["lat"], st["lon"]))
        try:
            arrivals = model.get_travel_times(
                source_depth_in_km=ev["depth_km"],
                distance_in_degree=dist,
                phase_list=[obs["phase"]]
            )
            if arrivals:
                theoretical[model_name][i] = float(arrivals[0].time)
        except Exception:
            continue


def compute_residuals(model_name, corrections=None):
    """Compute residuals for each observation, optionally applying corrections."""
    resids = []
    for i, obs in enumerate(observations):
        if i not in theoretical[model_name]:
            continue
        r = obs["arrival_time_sec"] - theoretical[model_name][i]
        if corrections and obs["station"] in corrections:
            r -= corrections[obs["station"]].get(obs["phase"], 0.0)
        resids.append((i, r))
    return resids


def mad_outlier_detection(resids, threshold=4.0):
    """Identify outliers using Median Absolute Deviation."""
    vals = np.array([r for _, r in resids])
    median_val = np.median(vals)
    mad = np.median(np.abs(vals - median_val))
    if mad < 0.01:
        mad = 0.01
    # 1.4826 converts MAD to standard deviation estimate for normal data
    scale = mad * 1.4826
    outlier_set = set()
    for idx, r in resids:
        if abs(r - median_val) > threshold * scale:
            outlier_set.add(idx)
    return outlier_set


def compute_station_corrections(model_name, outlier_set):
    """Compute mean residual per station per phase, excluding outliers."""
    corrections = {}
    for sta_name in stations:
        corrections[sta_name] = {}
        for phase in ["P", "S"]:
            resids = []
            for i, obs in enumerate(observations):
                if i in outlier_set or obs["station"] != sta_name or obs["phase"] != phase:
                    continue
                if i in theoretical[model_name]:
                    r = obs["arrival_time_sec"] - theoretical[model_name][i]
                    resids.append(r)
            corrections[sta_name][phase] = float(np.mean(resids)) if resids else 0.0
    return corrections


# ---- Iterative robust model selection and calibration ----
best_model = None
best_rms = float('inf')
best_outliers = set()
best_corrections = {}

for model_name in model_names:
    # Initial outlier detection from raw residuals
    raw_resids = compute_residuals(model_name)
    outlier_set = mad_outlier_detection(raw_resids, threshold=4.0)

    # Iterate: estimate corrections -> refine outliers -> re-estimate
    for _ in range(3):
        corrections = compute_station_corrections(model_name, outlier_set)
        corrected_resids = compute_residuals(model_name, corrections)
        outlier_set = mad_outlier_detection(corrected_resids, threshold=3.5)

    # Final corrections and RMS on clean data
    final_corrections = compute_station_corrections(model_name, outlier_set)
    clean_resids = []
    for i, obs in enumerate(observations):
        if i in outlier_set or i not in theoretical[model_name]:
            continue
        r = obs["arrival_time_sec"] - theoretical[model_name][i]
        r -= final_corrections[obs["station"]].get(obs["phase"], 0.0)
        clean_resids.append(r)

    rms = float(np.sqrt(np.mean(np.array(clean_resids) ** 2))) if clean_resids else float('inf')
    print(f"{model_name}: clean RMS={rms:.4f}, outliers={len(outlier_set)}")

    if rms < best_rms:
        best_rms = rms
        best_model = model_name
        best_outliers = outlier_set
        best_corrections = final_corrections

print(f"\nBest model: {best_model} (RMS={best_rms:.4f})")

# ---- Compute azimuthal gaps and quality classification ----
event_quality = {}
for ev_id, event in sorted(events.items()):
    event_stations = set()
    for obs in observations:
        if obs["event_id"] == ev_id:
            event_stations.add(obs["station"])

    azimuths = []
    for sta_name in sorted(event_stations):
        sta = stations[sta_name]
        _, az, _ = gps2dist_azimuth(
            event["lat"], event["lon"],
            sta["lat"], sta["lon"]
        )
        azimuths.append(az)

    azimuths_sorted = sorted(azimuths)
    if len(azimuths_sorted) < 2:
        gap = 360.0
    else:
        gaps = [
            azimuths_sorted[j + 1] - azimuths_sorted[j]
            for j in range(len(azimuths_sorted) - 1)
        ]
        gaps.append(360.0 - azimuths_sorted[-1] + azimuths_sorted[0])
        gap = max(gaps)

    if gap < 90:
        qc = "A"
    elif gap < 180:
        qc = "B"
    elif gap < 270:
        qc = "C"
    else:
        qc = "D"

    event_quality[ev_id] = {"azimuthal_gap": round(gap, 2), "quality_class": qc}

# ---- Write results ----
results = {
    "reference_model": best_model,
    "station_corrections": best_corrections,
    "outlier_indices": sorted(best_outliers),
    "clean_rms": round(best_rms, 6),
    "event_quality": event_quality,
}

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\nResults written to /app/results.json")
print(f"Station corrections: {json.dumps(best_corrections, indent=2)}")
print(f"Outliers ({len(best_outliers)}): {sorted(best_outliers)}")
