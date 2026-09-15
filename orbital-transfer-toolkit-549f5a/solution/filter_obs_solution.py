#!/usr/bin/env python3
"""Filter tracking observations — remove rejected entries and output clean JSON."""
import json
from datetime import datetime


def main():
    ref_epoch = datetime(2024, 1, 15, 0, 0, 0)
    observations = []

    with open("/app/mission_data/tracking_data.dat") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 6:
                continue

            epoch_str = parts[0].strip()
            station_id = parts[1].strip()
            range_km = float(parts[2].strip())
            az_deg = float(parts[3].strip())
            el_deg = float(parts[4].strip())
            quality = parts[5].strip()

            if quality != "A":
                continue

            if "." in epoch_str:
                dt = datetime.strptime(epoch_str, "%Y-%m-%dT%H:%M:%S.%f")
            else:
                dt = datetime.strptime(epoch_str, "%Y-%m-%dT%H:%M:%S")
            time_s = (dt - ref_epoch).total_seconds()

            observations.append(
                {
                    "time_s": time_s,
                    "station_id": station_id,
                    "range_km": range_km,
                    "azimuth_deg": az_deg,
                    "elevation_deg": el_deg,
                }
            )

    with open("/app/filtered_obs.json", "w") as f:
        json.dump(observations, f, indent=2)


if __name__ == "__main__":
    main()
