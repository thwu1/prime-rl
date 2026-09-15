#!/usr/bin/env python3
"""
Generate synthetic seismic observations for depth determination task.
Computes theoretical travel times using ObsPy TauP for a deep earthquake
observed at multiple global seismic network stations.
"""
import json
from obspy.taup import TauPyModel
from obspy.geodetics import gps2dist_azimuth, kilometers2degrees
from obspy import UTCDateTime

# Event parameters
DEPTH = 237.0
EVENT_LAT = 38.322
EVENT_LON = 142.369
ORIGIN_TIME = UTCDateTime("2024-01-15T12:30:45.000000Z")
MODEL_NAME = "iasp91"

# Global seismic network stations (real coordinates)
STATIONS = {
    "MAJO": {"lat": 36.5457, "lon": 138.2041},
    "MDJ":  {"lat": 44.6160, "lon": 129.5917},
    "INCN": {"lat": 37.4776, "lon": 126.6249},
    "BJT":  {"lat": 40.0183, "lon": 116.1679},
    "ULN":  {"lat": 47.8651, "lon": 107.0532},
    "AAK":  {"lat": 42.6390, "lon": 74.4940},
    "ARU":  {"lat": 56.4302, "lon": 58.5625},
    "OBN":  {"lat": 55.1146, "lon": 36.5674},
}

# Candidate phases (TauP will only return those that exist at each distance)
CANDIDATE_PHASES = ["P", "pP", "sP", "PP", "S", "sS", "SS", "PcP", "ScP", "ScS"]

model = TauPyModel(model=MODEL_NAME)

observations = {
    "event": {
        "latitude": EVENT_LAT,
        "longitude": EVENT_LON,
        "origin_time": str(ORIGIN_TIME),
    },
    "stations": {},
}

for sta_name, sta_coords in sorted(STATIONS.items()):
    dist_m, az, baz = gps2dist_azimuth(
        EVENT_LAT, EVENT_LON, sta_coords["lat"], sta_coords["lon"]
    )
    dist_deg = kilometers2degrees(dist_m / 1000.0)

    arrivals = model.get_travel_times(
        source_depth_in_km=DEPTH,
        distance_in_degree=dist_deg,
        phase_list=CANDIDATE_PHASES
    )

    # Take only first arrival of each phase name (avoid triplications)
    seen_phases = set()
    arrival_list = []
    for arr in sorted(arrivals, key=lambda a: a.time):
        if arr.name not in seen_phases:
            seen_phases.add(arr.name)
            abs_time = ORIGIN_TIME + arr.time
            arrival_list.append(str(abs_time))

    arrival_list.sort()

    observations["stations"][sta_name] = {
        "latitude": sta_coords["lat"],
        "longitude": sta_coords["lon"],
        "arrivals": arrival_list,
    }

with open("/app/observations.json", "w") as f:
    json.dump(observations, f, indent=2)

print(f"Generated observations for {len(STATIONS)} stations")
for sta in sorted(observations["stations"]):
    n = len(observations["stations"][sta]["arrivals"])
    print(f"  {sta}: {n} arrivals")
