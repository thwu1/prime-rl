#!/usr/bin/env python3

"""
Solve the orbital decay correlation task.

Pipeline:
1. Parse format_spec.txt to understand geomag data layout
2. Parse geomag_2024.dat, handling fill values
3. Parse satellite_52140.tle, extract epochs and mean motions
4. Compute semi-major axis via Kepler's third law
5. Compute delta-a, filter to May 2024, exclude maneuvers
6. Round to nearest hour, average within bins
7. Lag-correlation sweep for ap, Dst, AE across 0-48 hours
8. Write best result to results.json
"""

import math
import json
from datetime import datetime, timedelta
from collections import defaultdict

import numpy as np

MU = 398600.4418  # km^3/s^2
DATA_DIR = "/app/data"


def parse_geomag(filepath):
    """Parse fixed-width geomagnetic data file.

    Returns dict of {datetime: {'ap': val, 'Dst': val, 'AE': val}} with fill
    values mapped to NaN.
    """
    records = {}
    with open(filepath) as f:
        for line in f:
            if len(line.strip()) < 60:
                continue
            year = int(line[0:4])
            doy = int(line[5:8])
            hour = int(line[9:11])

            # ap: columns 22-25 (0-indexed: 21:25), fill=9999
            ap_raw = int(line[21:25])
            ap_val = float('nan') if ap_raw == 9999 else float(ap_raw)

            # Dst: columns 27-31 (0-indexed: 26:31), fill=99999
            dst_raw = int(line[26:31])
            dst_val = float('nan') if dst_raw == 99999 else float(dst_raw)

            # AE: columns 33-37 (0-indexed: 32:37), fill=99999
            ae_raw = int(line[32:37])
            ae_val = float('nan') if ae_raw == 99999 else float(ae_raw)

            dt = datetime(year, 1, 1) + timedelta(days=doy - 1, hours=hour)
            records[dt] = {'ap': ap_val, 'Dst': dst_val, 'AE': ae_val}

    return records


def parse_tle(filepath):
    """Parse TLE file, extracting epoch and mean motion for each element set.

    Returns list of (epoch_datetime, mean_motion_revday).
    """
    with open(filepath) as f:
        lines = [l.strip() for l in f if l.strip()]

    results = []
    for i in range(0, len(lines), 2):
        line1 = lines[i]
        line2 = lines[i + 1]

        # Epoch from line 1: columns 19-32 (0-indexed: 18:32)
        epoch_yr = int(line1[18:20])
        epoch_day = float(line1[20:32])

        # Convert 2-digit year
        full_year = 2000 + epoch_yr if epoch_yr < 57 else 1900 + epoch_yr
        epoch_dt = datetime(full_year, 1, 1) + timedelta(days=epoch_day - 1)

        # Mean motion from line 2: columns 53-63 (0-indexed: 52:63)
        mean_motion = float(line2[52:63])

        results.append((epoch_dt, mean_motion))

    return results


def compute_sma(mean_motion_revday):
    """Compute semi-major axis from mean motion using Kepler's third law."""
    n_rad_s = mean_motion_revday * 2.0 * math.pi / 86400.0
    return (MU / n_rad_s ** 2) ** (1.0 / 3.0)


def round_to_nearest_hour(dt):
    """Round a datetime to the nearest hour."""
    rounded = dt.replace(minute=0, second=0, microsecond=0)
    if dt.minute >= 30:
        rounded += timedelta(hours=1)
    return rounded


def main():
    # Step 1: Parse geomagnetic data
    geomag = parse_geomag(f"{DATA_DIR}/geomag_2024.dat")
    print(f"Parsed {len(geomag)} geomag records")

    # Step 2: Parse TLE data
    tle_data = parse_tle(f"{DATA_DIR}/satellite_52140.tle")
    print(f"Parsed {len(tle_data)} TLE records")

    # Step 3: Compute semi-major axes
    sma_data = [(epoch, compute_sma(mm)) for epoch, mm in tle_data]

    # Step 4: Compute delta-a between consecutive TLEs
    delta_a_data = []
    for i in range(1, len(sma_data)):
        epoch = sma_data[i][0]
        da = sma_data[i][1] - sma_data[i - 1][1]
        delta_a_data.append((epoch, da))

    # Step 5: Filter to May 2024 and exclude maneuvers (da >= 0)
    may_start = datetime(2024, 5, 1)
    may_end = datetime(2024, 6, 1)

    valid_data = [
        (epoch, da)
        for epoch, da in delta_a_data
        if may_start <= epoch < may_end and da < 0
    ]
    print(f"Valid May data points (non-maneuver): {len(valid_data)}")

    # Step 6: Round to nearest hour and average
    hourly_bins = defaultdict(list)
    for epoch, da in valid_data:
        rounded = round_to_nearest_hour(epoch)
        hourly_bins[rounded].append(da)

    hourly_avg = {k: np.mean(v) for k, v in hourly_bins.items()}
    sorted_hours = sorted(hourly_avg.keys())
    print(f"Hourly bins: {len(sorted_hours)}")

    # Step 7: Build index time series (excluding fill values)
    index_ts = {}
    for name in ['ap', 'Dst', 'AE']:
        ts = {}
        for dt, rec in geomag.items():
            val = rec[name]
            if not math.isnan(val):
                ts[dt] = val
        index_ts[name] = ts

    # Step 8: Lag-correlation sweep
    best = {'index': None, 'lag': None, 'r2': -1.0, 'n': 0}

    for name in ['ap', 'Dst', 'AE']:
        ts = index_ts[name]
        for lag in range(49):
            x_vals = []
            y_vals = []
            for t in sorted_hours:
                shifted = t - timedelta(hours=lag)
                if shifted in ts:
                    x_vals.append(ts[shifted])
                    y_vals.append(hourly_avg[t])

            if len(x_vals) < 5:
                continue

            x = np.array(x_vals)
            y = np.array(y_vals)

            if np.std(x) == 0 or np.std(y) == 0:
                continue

            r = float(np.corrcoef(x, y)[0, 1])
            r2 = r * r

            if r2 > best['r2']:
                best = {'index': name, 'lag': lag, 'r2': r2, 'n': len(x_vals)}

    # Step 9: Write results
    result = {
        "best_index": best['index'],
        "best_lag_hours": best['lag'],
        "best_r_squared": round(best['r2'], 4),
        "n_data_points": best['n'],
    }

    with open("/app/results.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Results: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
