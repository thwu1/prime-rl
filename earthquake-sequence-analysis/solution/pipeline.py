#!/usr/bin/env python3
"""Noto Peninsula earthquake sequence analysis pipeline.

Analyzes the 2024 Noto Peninsula, Japan M7.5 earthquake sequence from a
USGS FDSN GeoJSON catalog. Computes Gutenberg-Richter b-value via Aki-Utsu
MLE with Shi-Bolt uncertainty, completeness magnitude via Maximum Curvature,
Modified Omori Law aftershock decay parameters, Haversine interevent distances,
spatial density, foreshock analysis, aftershock zone dimensions, and seismic
energy budget.
"""

import json
import math
import sqlite3
import statistics
from pathlib import Path

EARTH_RADIUS_KM = 6371.0
NOTO_LAT_MIN = 36.5
NOTO_LAT_MAX = 38.5
NOTO_LON_MIN = 136.0
NOTO_LON_MAX = 138.5
BIN_WIDTH = 0.1
GRID_SIZE = 0.5


def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance in km using the Haversine formula."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_and_filter(catalog_path):
    """Load GeoJSON catalog and filter to Noto Peninsula bounding box."""
    with open(catalog_path) as f:
        data = json.load(f)

    events = []
    for feature in data["features"]:
        props = feature["properties"]
        coords = feature["geometry"]["coordinates"]
        lon, lat, depth = coords[0], coords[1], coords[2]

        if (
            NOTO_LAT_MIN <= lat <= NOTO_LAT_MAX
            and NOTO_LON_MIN <= lon <= NOTO_LON_MAX
        ):
            events.append(
                {
                    "id": feature["id"],
                    "time_ms": props["time"],
                    "latitude": lat,
                    "longitude": lon,
                    "depth_km": depth,
                    "magnitude": props["mag"],
                    "mag_type": props.get("magType", ""),
                    "place": props.get("place", ""),
                    "gap": props.get("gap"),
                    "dmin": props.get("dmin"),
                    "rms": props.get("rms"),
                    "sig": props.get("sig"),
                    "status": props.get("status", ""),
                    "tsunami": props.get("tsunami", 0),
                }
            )

    events.sort(key=lambda e: e["time_ms"])
    return events


def create_database(events, db_path):
    """Create normalized SQLite database with events and interevent distances."""
    if Path(db_path).exists():
        Path(db_path).unlink()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """CREATE TABLE events (
        id TEXT PRIMARY KEY,
        time_ms INTEGER,
        latitude REAL,
        longitude REAL,
        depth_km REAL,
        magnitude REAL,
        mag_type TEXT,
        place TEXT,
        gap REAL,
        dmin REAL,
        rms REAL,
        sig INTEGER,
        status TEXT,
        tsunami INTEGER
    )"""
    )

    cur.execute(
        """CREATE TABLE interevent_distances (
        event1_id TEXT,
        event2_id TEXT,
        distance_km REAL,
        time_diff_sec REAL
    )"""
    )

    for e in events:
        cur.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                e["id"], e["time_ms"], e["latitude"], e["longitude"],
                e["depth_km"], e["magnitude"], e["mag_type"], e["place"],
                e["gap"], e["dmin"], e["rms"], e["sig"],
                e["status"], e["tsunami"],
            ),
        )

    distances = []
    for i in range(len(events) - 1):
        e1, e2 = events[i], events[i + 1]
        dist = haversine(
            e1["latitude"], e1["longitude"], e2["latitude"], e2["longitude"]
        )
        time_diff = (e2["time_ms"] - e1["time_ms"]) / 1000.0
        cur.execute(
            "INSERT INTO interevent_distances VALUES (?,?,?,?)",
            (e1["id"], e2["id"], dist, time_diff),
        )
        distances.append(dist)

    conn.commit()
    conn.close()
    return distances


def compute_mc(magnitudes):
    """Completeness magnitude via Maximum Curvature method."""
    mag_min = round(math.floor(min(magnitudes) * 10) / 10.0, 1)
    mag_max = round(math.ceil(max(magnitudes) * 10) / 10.0, 1)

    bins = {}
    current = mag_min
    while current <= mag_max + 0.001:
        bins[round(current, 1)] = 0
        current += BIN_WIDTH

    for m in magnitudes:
        bv = round(math.floor(m * 10) / 10.0, 1)
        if bv in bins:
            bins[bv] += 1

    return max(bins, key=bins.get)


def compute_b_value(magnitudes, mc):
    """Gutenberg-Richter b-value via Aki-Utsu Maximum Likelihood Estimation."""
    filtered = [m for m in magnitudes if m >= mc]
    if len(filtered) < 2:
        return 1.0
    m_mean = statistics.mean(filtered)
    denominator = m_mean - (mc - BIN_WIDTH / 2)
    if denominator <= 0:
        return 1.0
    return math.log10(math.e) / denominator


def compute_b_uncertainty(magnitudes, mc, b_value):
    """Shi & Bolt (1982) b-value uncertainty: db = 2.30 * b^2 * sigma / sqrt(N)."""
    filtered = [m for m in magnitudes if m >= mc]
    n = len(filtered)
    if n < 3:
        return 0.0
    sigma = statistics.stdev(filtered)
    return 2.30 * b_value ** 2 * sigma / math.sqrt(n)


def compute_omori(events, mainshock_time):
    """Fit Modified Omori Law n(t) = K*(t+c)^(-p) to aftershock rates."""
    from scipy.optimize import curve_fit

    aftershock_hours = [
        (e["time_ms"] - mainshock_time) / 3600000.0
        for e in events
        if e["time_ms"] > mainshock_time
    ]

    if len(aftershock_hours) < 3:
        return {"K": 1.0, "c": 0.5, "p": 1.0}

    max_t = max(aftershock_hours)
    n_bins = max(1, int(math.ceil(max_t)))
    bin_counts = [0] * n_bins
    for t in aftershock_hours:
        idx = min(int(t), n_bins - 1)
        bin_counts[idx] += 1

    t_centers = []
    rates = []
    for i in range(n_bins):
        if bin_counts[i] > 0:
            t_centers.append(i + 0.5)
            rates.append(float(bin_counts[i]))

    if len(t_centers) < 3:
        return {"K": rates[0] if rates else 1.0, "c": 0.5, "p": 1.0}

    def omori_model(t, k, c, p):
        return k * (t + c) ** (-p)

    try:
        popt, _ = curve_fit(
            omori_model,
            t_centers,
            rates,
            p0=[max(rates), 0.5, 1.0],
            bounds=([0.01, 0.001, 0.1], [1e6, 100, 5.0]),
            maxfev=10000,
        )
        return {"K": float(popt[0]), "c": float(popt[1]), "p": float(popt[2])}
    except Exception:
        return {"K": float(max(rates)), "c": 0.5, "p": 1.0}


def compute_spatial_density(events):
    """Event density on a 0.5-degree grid."""
    grid = {}
    for e in events:
        lat_bin = math.floor(e["latitude"] / GRID_SIZE) * GRID_SIZE
        lon_bin = math.floor(e["longitude"] / GRID_SIZE) * GRID_SIZE
        key = (lat_bin, lon_bin)
        grid[key] = grid.get(key, 0) + 1

    densest = max(grid, key=grid.get)
    return {
        "grid_cell_lat_min": densest[0],
        "grid_cell_lon_min": densest[1],
        "count": grid[densest],
    }


def compute_aftershock_zone_length(aftershocks):
    """Maximum pairwise Haversine distance among aftershock epicenters."""
    max_dist = 0.0
    for i in range(len(aftershocks)):
        for j in range(i + 1, len(aftershocks)):
            d = haversine(
                aftershocks[i]["latitude"], aftershocks[i]["longitude"],
                aftershocks[j]["latitude"], aftershocks[j]["longitude"],
            )
            if d > max_dist:
                max_dist = d
    return max_dist


def compute_energy(magnitude):
    """Gutenberg-Richter energy-magnitude relation: log10(E) = 1.5*M + 4.8 (Joules)."""
    return 10 ** (1.5 * magnitude + 4.8)


def main():
    catalog_path = "/app/data/catalog.json"
    db_path = "/app/noto_seismic.db"
    analysis_path = "/app/analysis.json"

    # Load and filter
    events = load_and_filter(catalog_path)
    print(f"Loaded {len(events)} Noto Peninsula events")

    # Create database
    distances = create_database(events, db_path)
    print(f"Database created at {db_path}")

    # Mainshock (largest magnitude event)
    mainshock = max(events, key=lambda e: e["magnitude"])
    print(f"Mainshock: {mainshock['id']} M{mainshock['magnitude']}")

    # Largest aftershock (largest mag event after mainshock)
    aftershocks = [e for e in events if e["time_ms"] > mainshock["time_ms"]]
    largest_aftershock = max(aftershocks, key=lambda e: e["magnitude"])
    print(f"Largest aftershock: {largest_aftershock['id']} M{largest_aftershock['magnitude']}")

    # Bath's law
    bath_delta = mainshock["magnitude"] - largest_aftershock["magnitude"]

    # Foreshock count
    foreshock_count = sum(1 for e in events if e["time_ms"] < mainshock["time_ms"])
    print(f"Foreshock count: {foreshock_count}")

    # Magnitudes
    magnitudes = [e["magnitude"] for e in events]

    # Completeness magnitude
    mc = compute_mc(magnitudes)
    print(f"Mc = {mc}")

    # Gutenberg-Richter b-value
    b_value = compute_b_value(magnitudes, mc)
    print(f"b-value = {b_value:.4f}")

    # b-value uncertainty (Shi & Bolt, 1982)
    b_uncertainty = compute_b_uncertainty(magnitudes, mc, b_value)
    print(f"b-value uncertainty = {b_uncertainty:.4f}")

    # a-value
    n_above_mc = len([m for m in magnitudes if m >= mc])
    a_value = math.log10(n_above_mc)
    print(f"a-value = {a_value:.4f}")

    # Omori parameters
    omori = compute_omori(events, mainshock["time_ms"])
    print(f"Omori: K={omori['K']:.2f}, c={omori['c']:.4f}, p={omori['p']:.4f}")

    # Aftershock zone length
    zone_length = compute_aftershock_zone_length(aftershocks)
    print(f"Aftershock zone length: {zone_length:.2f} km")

    # Energy budget
    total_energy = sum(compute_energy(e["magnitude"]) for e in events)
    mainshock_energy = compute_energy(mainshock["magnitude"])
    mainshock_energy_fraction = mainshock_energy / total_energy
    print(f"Total energy: {total_energy:.3e} J")
    print(f"Mainshock energy fraction: {mainshock_energy_fraction:.4f}")

    # Distance statistics
    median_dist = statistics.median(distances) if distances else 0.0
    mean_dist = statistics.mean(distances) if distances else 0.0
    print(f"Interevent distances: median={median_dist:.2f} km, mean={mean_dist:.2f} km")

    # Spatial density
    spatial = compute_spatial_density(events)
    print(
        f"Densest grid cell: ({spatial['grid_cell_lat_min']}, "
        f"{spatial['grid_cell_lon_min']}), count={spatial['count']}"
    )

    # Build output
    def event_dict(e):
        return {
            "id": e["id"],
            "magnitude": e["magnitude"],
            "latitude": e["latitude"],
            "longitude": e["longitude"],
            "depth_km": e["depth_km"],
            "time_ms": e["time_ms"],
        }

    analysis = {
        "event_count": len(events),
        "mainshock": event_dict(mainshock),
        "largest_aftershock": event_dict(largest_aftershock),
        "bath_law_delta": bath_delta,
        "foreshock_count": foreshock_count,
        "mc": mc,
        "b_value": b_value,
        "b_value_uncertainty": b_uncertainty,
        "a_value": a_value,
        "omori": omori,
        "aftershock_zone_length_km": zone_length,
        "total_energy_joules": total_energy,
        "mainshock_energy_fraction": mainshock_energy_fraction,
        "median_interevent_distance_km": median_dist,
        "mean_interevent_distance_km": mean_dist,
        "spatial_density": spatial,
    }

    with open(analysis_path, "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"\nAnalysis written to {analysis_path}")


if __name__ == "__main__":
    main()
