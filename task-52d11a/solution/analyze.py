#!/usr/bin/env python3

"""
Analyze extracted geomagnetic and orbital data for lag-correlation.

Reads:
  /app/geomag_extracted.csv  -- hourly geomag indices (from sqlite3 export)
  /app/omm_extracted.csv     -- epoch, mean_motion pairs (from jq export)

Writes:
  /app/results.json
"""

import csv
import json
import math
from datetime import datetime, timedelta
from collections import defaultdict

MU = 398600.4418  # km^3/s^2


def load_geomag(filepath):
    """Load geomag CSV exported from sqlite3."""
    records = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.strptime(row['utc_timestamp'], '%Y-%m-%dT%H:%M:%SZ')
            records[dt] = {
                'ap': float(row['ap_index']),
                'Dst': float(row['dst_index']),
                'AE': float(row['ae_index']),
            }
    return records


def load_omm(filepath):
    """Load OMM CSV exported via jq."""
    data = []
    with open(filepath) as f:
        reader = csv.reader(f)
        for row in reader:
            epoch_str = row[0].strip('"')
            mm = float(row[1])
            try:
                dt = datetime.strptime(epoch_str, '%Y-%m-%dT%H:%M:%S.%f')
            except ValueError:
                dt = datetime.strptime(epoch_str, '%Y-%m-%dT%H:%M:%S')
            data.append((dt, mm))
    return data


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


def pearson_r_squared(x, y):
    """Compute Pearson r-squared using pure Python."""
    n = len(x)
    if n < 5:
        return None
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)
    if var_x == 0 or var_y == 0:
        return None
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    r = cov / (var_x * var_y) ** 0.5
    return r * r


def main():
    # Load data
    geomag = load_geomag('/app/geomag_extracted.csv')
    omm_data = load_omm('/app/omm_extracted.csv')
    print(f"Geomag records: {len(geomag)}")
    print(f"OMM records: {len(omm_data)}")

    # Compute semi-major axes
    sma_data = [(epoch, compute_sma(mm)) for epoch, mm in omm_data]

    # Compute delta-a between consecutive epochs
    delta_a_data = []
    for i in range(1, len(sma_data)):
        epoch = sma_data[i][0]
        da = sma_data[i][1] - sma_data[i - 1][1]
        delta_a_data.append((epoch, da))

    # Filter to May 2024, exclude maneuvers (da >= 0)
    may_start = datetime(2024, 5, 1)
    may_end = datetime(2024, 6, 1)
    valid_data = [
        (epoch, da)
        for epoch, da in delta_a_data
        if may_start <= epoch < may_end and da < 0
    ]
    print(f"Valid May data points (non-maneuver): {len(valid_data)}")

    # Round to nearest hour and average within bins
    hourly_bins = defaultdict(list)
    for epoch, da in valid_data:
        hourly_bins[round_to_nearest_hour(epoch)].append(da)

    hourly_avg = {k: sum(v) / len(v) for k, v in hourly_bins.items()}
    sorted_hours = sorted(hourly_avg.keys())
    print(f"Hourly bins: {len(sorted_hours)}")

    # Build index time series
    index_ts = {}
    for name in ['ap', 'Dst', 'AE']:
        ts = {dt: rec[name] for dt, rec in geomag.items()}
        index_ts[name] = ts

    # Lag-correlation sweep
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

            r2 = pearson_r_squared(x_vals, y_vals)
            if r2 is not None and r2 > best['r2']:
                best = {'index': name, 'lag': lag, 'r2': r2, 'n': len(x_vals)}

    # Write results
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
