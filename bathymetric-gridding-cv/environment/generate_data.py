#!/usr/bin/env python3
"""Generate synthetic ship track bathymetry data for the gridding task."""
import math
import os
import random

random.seed(42)


def depth_model(lon, lat):
    """
    Synthetic ocean depth model (meters, negative = below sea level).
    Region: [245, 255, 20, 30]
    """
    # Base depth gradient: shelf (~-200m at lat=30) to deep ocean (~-4000m at lat=20)
    base = -200.0 - 380.0 * (30.0 - lat)

    # Continental slope steepening near lat=27
    slope_effect = 0.0
    if 25.5 < lat < 28.5:
        slope_effect = -500.0 * math.exp(-((lat - 27.0) / 0.7) ** 2)

    # Mid-ocean ridge running NW-SE
    ridge_center_lat = 24.0 + 0.3 * (lon - 245.0)
    ridge_effect = 800.0 * math.exp(-((lat - ridge_center_lat) / 1.5) ** 2)

    # Seamount 1 at (248.5, 23)
    r1 = math.sqrt((lon - 248.5) ** 2 + (lat - 23.0) ** 2)
    seamount1 = 1200.0 * math.exp(-(r1 / 0.8) ** 2)

    # Seamount 2 at (252, 25.5)
    r2 = math.sqrt((lon - 252.0) ** 2 + (lat - 25.5) ** 2)
    seamount2 = 900.0 * math.exp(-(r2 / 0.6) ** 2)

    # Fracture zone trough running NE-SW
    fz_dist = abs((lat - 21.5) - 0.6 * (lon - 245.5))
    fracture = -350.0 * math.exp(-(fz_dist / 0.35) ** 2)

    return base + slope_effect + ridge_effect + seamount1 + seamount2 + fracture


def generate_track(lons, lats, noise_std=50.0):
    """Generate observations along a ship track with Gaussian noise."""
    points = []
    for lon, lat in zip(lons, lats):
        if 245.0 <= lon <= 255.0 and 20.0 <= lat <= 30.0:
            depth = depth_model(lon, lat) + random.gauss(0, noise_std)
            points.append((lon, lat, depth))
    return points


def main():
    os.makedirs("/app/data", exist_ok=True)

    all_points = []

    # Track 1: E-W at lat ~24
    n = 160
    lons = [245.1 + 9.8 * i / (n - 1) for i in range(n)]
    lats = [24.0 + 0.3 * math.sin(2 * math.pi * i / n) for i in range(n)]
    all_points.extend(generate_track(lons, lats))

    # Track 2: E-W at lat ~26.5
    n = 145
    lons = [245.3 + 9.4 * i / (n - 1) for i in range(n)]
    lats = [26.5 + 0.25 * math.sin(3 * math.pi * i / n) for i in range(n)]
    all_points.extend(generate_track(lons, lats))

    # Track 3: E-W at lat ~22
    n = 130
    lons = [245.5 + 9.0 * i / (n - 1) for i in range(n)]
    lats = [22.0 + 0.2 * math.sin(2.5 * math.pi * i / n) for i in range(n)]
    all_points.extend(generate_track(lons, lats))

    # Track 4: NE-SW diagonal
    n = 170
    lons = [245.3 + 9.4 * i / (n - 1) for i in range(n)]
    lats = [20.3 + 9.4 * i / (n - 1) + 0.15 * math.sin(4 * math.pi * i / n)
            for i in range(n)]
    all_points.extend(generate_track(lons, lats))

    # Track 5: NW-SE diagonal
    n = 155
    lons = [245.4 + 9.2 * i / (n - 1) for i in range(n)]
    lats = [29.6 - 9.2 * i / (n - 1) + 0.1 * math.sin(5 * math.pi * i / n)
            for i in range(n)]
    all_points.extend(generate_track(lons, lats))

    # Track 6: N-S at lon ~249
    n = 125
    lons = [249.0 + 0.2 * math.sin(3 * math.pi * i / n) for i in range(n)]
    lats = [20.3 + 9.4 * i / (n - 1) for i in range(n)]
    all_points.extend(generate_track(lons, lats))

    # Track 7: N-S at lon ~252
    n = 115
    lons = [252.0 + 0.15 * math.sin(2 * math.pi * i / n) for i in range(n)]
    lats = [20.5 + 9.0 * i / (n - 1) for i in range(n)]
    all_points.extend(generate_track(lons, lats))

    with open("/app/data/ship_bathymetry.xyz", "w") as f:
        for lon, lat, depth in all_points:
            f.write(f"{lon:.6f}\t{lat:.6f}\t{depth:.2f}\n")

    print(f"Generated {len(all_points)} ship track observations")


if __name__ == "__main__":
    main()
