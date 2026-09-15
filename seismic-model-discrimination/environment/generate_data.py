#!/usr/bin/env python3
"""
Generate synthetic seismic travel time observation data with injected outliers.
Produces a dataset for the network calibration task.
"""
import json
import os
import numpy as np

np.random.seed(42)

# --- Global station network (8 stations) ---
stations = {
    "ANMO": {"lat": 34.946, "lon": -106.457},
    "HRV":  {"lat": 42.506, "lon": -71.558},
    "PAB":  {"lat": 39.545, "lon": -4.350},
    "KONO": {"lat": 59.649, "lon": 9.598},
    "MAJO": {"lat": 36.546, "lon": 138.204},
    "CTAO": {"lat": -20.088, "lon": 146.254},
    "LPAZ": {"lat": -16.288, "lon": -68.131},
    "NWAO": {"lat": -32.927, "lon": 117.239},
}

# --- Teleseismic earthquakes (6 events) ---
events = {
    "ev0": {"lat": -30.0,  "lon": -71.5,  "depth_km": 50.0},
    "ev1": {"lat": 5.0,    "lon": 95.0,   "depth_km": 100.0},
    "ev2": {"lat": 38.5,   "lon": 39.5,   "depth_km": 15.0},
    "ev3": {"lat": 55.0,   "lon": -160.0, "depth_km": 30.0},
    "ev4": {"lat": -20.5,  "lon": -175.0, "depth_km": 200.0},
    "ev5": {"lat": 35.0,   "lon": 52.0,   "depth_km": 65.0},
}

# --- True station timing biases (unknown to solver) ---
true_station_corrections = {
    "ANMO": {"P": 0.35,  "S": 0.62},
    "HRV":  {"P": -0.22, "S": -0.38},
    "PAB":  {"P": -0.41, "S": -0.73},
    "KONO": {"P": 0.48,  "S": 0.85},
    "MAJO": {"P": -0.28, "S": -0.50},
    "CTAO": {"P": 0.18,  "S": 0.32},
    "LPAZ": {"P": 0.55,  "S": 0.97},
    "NWAO": {"P": -0.15, "S": -0.27},
}

NOISE_SIGMA = 0.15  # seconds

from obspy.taup import TauPyModel
from obspy.geodetics import locations2degrees

model = TauPyModel(model="ak135")

observations = []
for ev_id, event in sorted(events.items()):
    for sta_name, sta_coords in sorted(stations.items()):
        dist_deg = float(locations2degrees(
            event["lat"], event["lon"],
            sta_coords["lat"], sta_coords["lon"]
        ))

        # Only use teleseismic distance range
        if dist_deg < 25.0 or dist_deg > 95.0:
            continue

        for phase in ["P", "S"]:
            try:
                arrivals = model.get_travel_times(
                    source_depth_in_km=event["depth_km"],
                    distance_in_degree=dist_deg,
                    phase_list=[phase]
                )
                if not arrivals:
                    continue

                true_time = float(arrivals[0].time)
                correction = true_station_corrections[sta_name][phase]
                noise = float(np.random.normal(0, NOISE_SIGMA))
                observed_time = true_time + correction + noise

                observations.append({
                    "event_id": ev_id,
                    "station": sta_name,
                    "phase": phase,
                    "arrival_time_sec": round(observed_time, 4),
                })
            except Exception:
                continue

# Inject outliers: ~8% of observations get gross timing errors (5-15 seconds)
n_obs = len(observations)
n_outliers = max(5, int(n_obs * 0.08))
outlier_indices = sorted(
    np.random.choice(n_obs, size=n_outliers, replace=False).tolist()
)

for idx in outlier_indices:
    sign = np.random.choice([-1, 1])
    offset = sign * np.random.uniform(5.0, 15.0)
    observations[idx]["arrival_time_sec"] = round(
        observations[idx]["arrival_time_sec"] + offset, 4
    )

# --- Write output files ---
os.makedirs("/app/data", exist_ok=True)

with open("/app/data/stations.json", "w") as f:
    json.dump(stations, f, indent=2)

with open("/app/data/events.json", "w") as f:
    json.dump(events, f, indent=2)

with open("/app/data/observations.json", "w") as f:
    json.dump(observations, f, indent=2)

print(f"Generated {n_obs} observations, {n_outliers} outliers at indices: {outlier_indices}")
