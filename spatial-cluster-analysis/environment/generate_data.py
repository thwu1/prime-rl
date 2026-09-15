#!/usr/bin/env python3
"""Generate geospatial data for spatial analysis pipeline task."""

import json
import csv
import os

NROWS = 6
NCOLS = 6
LON_MIN = -74.03
LAT_MAX = 40.03
CELL_SIZE = 0.01

VALUES = [
    [9, 10, 8, 5, 4, 5],
    [10, 9, 8, 4, 5, 6],
    [8, 8, 9, 5, 3, 4],
    [5, 6, 5, 2, 3, 2],
    [4, 5, 4, 3, 1, 2],
    [5, 4, 5, 2, 2, 1],
]

BAD_OBS_ZONES = [2, 9, 14, 21, 28, 33]


def main():
    os.makedirs("/app/data", exist_ok=True)

    features = []
    for r in range(NROWS):
        for c in range(NCOLS):
            zone_id = "Z{:02d}".format(r * NCOLS + c)
            x0 = round(LON_MIN + c * CELL_SIZE, 6)
            x1 = round(LON_MIN + (c + 1) * CELL_SIZE, 6)
            y0 = round(LAT_MAX - (r + 1) * CELL_SIZE, 6)
            y1 = round(LAT_MAX - r * CELL_SIZE, 6)
            coords = [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]
            features.append({
                "type": "Feature",
                "properties": {"zone_id": zone_id},
                "geometry": {"type": "Polygon", "coordinates": coords}
            })

    geojson = {"type": "FeatureCollection", "features": features}
    with open("/app/data/zones.geojson", "w") as f:
        json.dump(geojson, f, indent=2)

    rows = []
    obs_id = 1
    for r in range(NROWS):
        for c in range(NCOLS):
            base_val = VALUES[r][c]
            cx = round(LON_MIN + (c + 0.5) * CELL_SIZE, 6)
            cy = round(LAT_MAX - (r + 0.5) * CELL_SIZE, 6)
            for dx, dy, dv in [(-0.002, -0.002, -0.5),
                               (0.0, 0.0, 0.0),
                               (0.002, 0.002, 0.5)]:
                rows.append([
                    "O{:03d}".format(obs_id),
                    round(cx + dx, 6),
                    round(cy + dy, 6),
                    base_val + dv
                ])
                obs_id += 1

    for zone_idx in BAD_OBS_ZONES:
        r, c = divmod(zone_idx, NCOLS)
        cx = round(LON_MIN + (c + 0.5) * CELL_SIZE, 6)
        cy = round(LAT_MAX - (r + 0.5) * CELL_SIZE, 6)
        rows.append([
            "O{:03d}".format(obs_id),
            round(cx + 0.001, 6),
            round(cy - 0.001, 6),
            -9999.0
        ])
        obs_id += 1

    with open("/app/data/observations.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["obs_id", "longitude", "latitude", "value"])
        for row in rows:
            writer.writerow(row)

    print("Generated {} zones, {} observations".format(
        len(features), len(rows)))


if __name__ == "__main__":
    main()
