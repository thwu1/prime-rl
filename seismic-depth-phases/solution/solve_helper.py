#!/usr/bin/env python3

"""
Solve the seismic event depth determination and phase identification problem.

Strategy:
1. Read observation data (station locations, unlabeled arrival times)
2. Compute epicentral distances using Vincenty geodesic calculation
3. Grid search over depth (1-700 km, 1 km steps) using TauP iasp91 model
4. At each depth, compute theoretical travel times for candidate phases
5. Use Hungarian algorithm (scipy.optimize.linear_sum_assignment) to optimally
   match observed arrivals to theoretical phases minimizing total squared residual
6. Select the depth with minimum total RMS residual
7. Output results with phase labels and residuals
"""

import json
import math
import sys

from obspy.taup import TauPyModel
from obspy.geodetics import gps2dist_azimuth, kilometers2degrees
from obspy import UTCDateTime
from scipy.optimize import linear_sum_assignment
import numpy as np


def load_observations(path="/app/observations.json"):
    with open(path) as f:
        return json.load(f)


def compute_distance_deg(lat1, lon1, lat2, lon2):
    """Compute epicentral distance in degrees using WGS84."""
    dist_m, _, _ = gps2dist_azimuth(lat1, lon1, lat2, lon2)
    return kilometers2degrees(dist_m / 1000.0)


def match_arrivals_to_phases(observed_travel_times, theoretical_phases, max_residual=30.0):
    """
    Use Hungarian algorithm to match observed arrival travel times
    to theoretical phase travel times, minimizing total squared residual.

    observed_travel_times: list of float (seconds after origin)
    theoretical_phases: list of (phase_name, travel_time_seconds)
    max_residual: penalty for unmatched arrivals

    Returns: list of (obs_tt, phase_name, residual) for matched pairs,
             and total squared residual
    """
    n_obs = len(observed_travel_times)
    n_theo = len(theoretical_phases)

    if n_obs == 0 or n_theo == 0:
        return [], float("inf")

    # Build cost matrix: rows=observed, cols=theoretical
    # If n_obs != n_theo, pad with high-cost dummy entries
    size = max(n_obs, n_theo)
    cost = np.full((size, size), max_residual ** 2)

    for i in range(n_obs):
        for j in range(n_theo):
            residual = observed_travel_times[i] - theoretical_phases[j][1]
            cost[i, j] = residual ** 2

    row_ind, col_ind = linear_sum_assignment(cost)

    matches = []
    total_sq = 0.0
    for r, c in zip(row_ind, col_ind):
        if r < n_obs and c < n_theo:
            residual = observed_travel_times[r] - theoretical_phases[c][1]
            if abs(residual) < max_residual:
                matches.append((observed_travel_times[r], theoretical_phases[c][0], residual))
                total_sq += residual ** 2

    return matches, total_sq


def solve():
    obs = load_observations()

    event_lat = obs["event"]["latitude"]
    event_lon = obs["event"]["longitude"]
    origin_time = UTCDateTime(obs["event"]["origin_time"])

    model = TauPyModel(model="iasp91")

    candidate_phases = ["P", "pP", "sP", "PP", "S", "sS", "SS", "PcP", "ScP", "ScS"]

    # Precompute station distances and observed travel times
    station_data = {}
    for sta_name, sta_info in obs["stations"].items():
        dist_deg = compute_distance_deg(
            event_lat, event_lon, sta_info["latitude"], sta_info["longitude"]
        )
        # Convert absolute arrival times to travel times (seconds after origin)
        obs_travel_times = []
        for t_str in sta_info["arrivals"]:
            t = UTCDateTime(t_str)
            obs_travel_times.append(t - origin_time)
        obs_travel_times.sort()

        station_data[sta_name] = {
            "distance_deg": dist_deg,
            "obs_travel_times": obs_travel_times,
            "arrival_strings": sorted(sta_info["arrivals"]),
            "latitude": sta_info["latitude"],
            "longitude": sta_info["longitude"],
        }

    # Grid search over depth
    print("Starting depth grid search (1-700 km)...")
    best_depth = None
    best_rms = float("inf")
    best_matches = None

    # Coarse search first (5 km steps)
    coarse_depths = list(range(1, 701, 5))
    coarse_results = []

    for depth in coarse_depths:
        total_sq = 0.0
        total_n = 0
        all_matches = {}

        for sta_name, sd in station_data.items():
            try:
                arrivals = model.get_travel_times(
                    source_depth_in_km=depth,
                    distance_in_degree=sd["distance_deg"],
                    phase_list=candidate_phases,
                )
            except Exception:
                continue

            # First arrival of each phase
            seen = set()
            theo_phases = []
            for arr in sorted(arrivals, key=lambda a: a.time):
                if arr.name not in seen:
                    seen.add(arr.name)
                    theo_phases.append((arr.name, arr.time))

            matches, sq = match_arrivals_to_phases(sd["obs_travel_times"], theo_phases)
            all_matches[sta_name] = matches
            total_sq += sq
            total_n += len(matches)

        if total_n > 0:
            rms = math.sqrt(total_sq / total_n)
        else:
            rms = float("inf")

        coarse_results.append((depth, rms))

        if rms < best_rms:
            best_rms = rms
            best_depth = depth
            best_matches = all_matches

    print(f"Coarse search best: depth={best_depth} km, RMS={best_rms:.4f} s")

    # Fine search around best coarse depth (1 km steps)
    fine_start = max(1, best_depth - 10)
    fine_end = min(700, best_depth + 10)

    for depth in range(fine_start, fine_end + 1):
        total_sq = 0.0
        total_n = 0
        all_matches = {}

        for sta_name, sd in station_data.items():
            try:
                arrivals = model.get_travel_times(
                    source_depth_in_km=depth,
                    distance_in_degree=sd["distance_deg"],
                    phase_list=candidate_phases,
                )
            except Exception:
                continue

            seen = set()
            theo_phases = []
            for arr in sorted(arrivals, key=lambda a: a.time):
                if arr.name not in seen:
                    seen.add(arr.name)
                    theo_phases.append((arr.name, arr.time))

            matches, sq = match_arrivals_to_phases(sd["obs_travel_times"], theo_phases)
            all_matches[sta_name] = matches
            total_sq += sq
            total_n += len(matches)

        if total_n > 0:
            rms = math.sqrt(total_sq / total_n)
        else:
            rms = float("inf")

        if rms < best_rms:
            best_rms = rms
            best_depth = depth
            best_matches = all_matches

    print(f"Fine search best: depth={best_depth} km, RMS={best_rms:.6f} s")

    # Build output
    results = {
        "depth_km": float(best_depth),
        "velocity_model": "iasp91",
        "stations": {},
        "total_rms_residual_sec": round(best_rms, 6),
    }

    for sta_name, sd in sorted(station_data.items()):
        arrivals_out = []
        if sta_name in best_matches:
            for obs_tt, phase, residual in sorted(best_matches[sta_name], key=lambda x: x[0]):
                abs_time = origin_time + obs_tt
                arrivals_out.append({
                    "time": str(abs_time),
                    "phase": phase,
                    "residual_sec": round(residual, 6),
                })

        results["stations"][sta_name] = {
            "distance_deg": round(sd["distance_deg"], 4),
            "arrivals": arrivals_out,
        }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to /app/results.json")
    print(f"Optimal depth: {best_depth} km")
    print(f"Total RMS residual: {best_rms:.6f} s")
    print(f"Stations processed: {len(results['stations'])}")
    for sta in sorted(results["stations"]):
        n = len(results["stations"][sta]["arrivals"])
        print(f"  {sta}: {n} phases identified")


if __name__ == "__main__":
    solve()
