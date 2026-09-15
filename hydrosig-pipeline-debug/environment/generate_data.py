#!/usr/bin/env python3
"""Generate synthetic NHDPlus-like river network and gauge observation data.

Creates a realistic river network with topology issues requiring
cleaning, along with daily streamflow and precipitation data at
multiple gauge locations for hydrological analysis.

"""
import csv
import os
from datetime import date, timedelta

import numpy as np

np.random.seed(2024)

# ==============================================================
# 1. Network Data
# ==============================================================
#
#  Topology (upstream -> downstream):
#
#  2001 -> 2002 -> 2003 --\
#  1001 ------------------> 1002 --> 1003 --> 1004 --> 1005 (outlet)
#                                      ^        ^
#  3001 -> 3002 ----------------------/         |
#  5001 --\                                     |
#  4001 -> 4002 -> 4003 -----------------------/
#
#  6001: divergent from node 103 (divergence=2)
#  8001 -> 8002: tiny isolated network (totdasqkm < 1.0)
#  9001: coastline feature (fcode=56600)

headers = [
    'comid', 'tocomid', 'fromnode', 'tonode', 'lengthkm', 'slope',
    'totdasqkm', 'streamorde', 'divergence', 'terminalfl',
    'terminalpa', 'hydroseq', 'levelpathi', 'fcode',
]

rows = [
    # Main stem (tocomid provided)
    [1001, 1002, 101, 102, 5.2,  0.008, 12.5,  3, 0, 0, 1000, 100, 1000, 46006],
    [1002, 1003, 102, 103, 8.1,  0.005, 45.0,  4, 0, 0, 1000,  90, 1000, 46006],
    [1003, 1004, 103, 104, 6.3,  0.004, 68.0,  4, 0, 0, 1000,  80, 1000, 46006],
    [1004, 1005, 104, 105, 12.0, 0.003, 120.0, 5, 0, 0, 1000,  70, 1000, 46006],
    [1005,    0, 105, 106, 4.5,  0.002, 155.0, 5, 0, 1, 1000,  60, 1000, 46006],
    # North tributary (tocomid MISSING — must be derived from node topology)
    [2001, '',  201, 202, 3.1,  0.012, 5.0,   1, 0, 0, 1000, 130, 2000, 46006],
    [2002, '',  202, 203, 4.5,  0.009, 8.5,   2, 0, 0, 1000, 120, 2000, 46006],
    [2003, '',  203, 102, 7.2,  0.007, 15.0,  2, 0, 0, 1000, 110, 2000, 46006],
    # South tributary (tocomid MISSING)
    [3001, '',  301, 302, 2.8,  0.015, 3.5,   1, 0, 0, 1000, 140, 3000, 46006],
    [3002, '',  302, 103, 5.9,  0.010, 8.0,   2, 0, 0, 1000, 115, 3000, 46006],
    # East tributary (tocomid MISSING)
    [4001, '',  401, 402, 4.0,  0.011, 6.0,   1, 0, 0, 1000, 150, 4000, 46006],
    [4002, '',  402, 403, 6.1,  0.008, 14.0,  2, 0, 0, 1000, 125, 4000, 46006],
    [4003, '',  403, 104, 3.5,  0.006, 22.0,  2, 0, 0, 1000, 105, 4000, 46006],
    # Sub-tributary of east (tocomid MISSING)
    [5001, '',  501, 402, 2.5,  0.020, 3.0,   1, 0, 0, 1000, 160, 5000, 46006],
    # Divergent path (divergence=2)
    [6001, '',  103, 601, 1.2,  0.003, 68.0,  1, 2, 0, 1000,  78, 6000, 46006],
    # Isolated tiny network
    [8001, 8002, 801, 802, 0.3, 0.025, 0.3,   1, 0, 0, 8000, 200, 8000, 46006],
    [8002,    0, 802, 803, 0.2, 0.020, 0.5,   1, 0, 1, 8000, 190, 8000, 46006],
    # Coastline feature
    [9001, '',  901, 902, 2.0,  0.001, 50.0,  1, 0, 0, 9000, 300, 9000, 56600],
]

os.makedirs('/app/data', exist_ok=True)

with open('/app/data/network.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)

# ==============================================================
# 2. Gauge Observation Data
# ==============================================================

start = date(2010, 1, 1)
end = date(2019, 12, 31)
dates = []
d = start
while d <= end:
    dates.append(d.isoformat())
    d += timedelta(days=1)
n_days = len(dates)
t = np.arange(n_days, dtype=np.float64)

# Gauge parameters: two-store recession model
# af/as_ = fast/slow recession coefficients
# cf/cs = fast/slow input fractions
# ps = rain probability scale, pa = rain amount scale
gauge_params = {
    'gauge_A': {'comid': 2001, 'af': 0.82, 'as_': 0.975, 'cf': 0.25, 'cs': 0.04, 'ps': 1.00, 'pa': 6.0},
    'gauge_B': {'comid': 1002, 'af': 0.86, 'as_': 0.985, 'cf': 0.20, 'cs': 0.06, 'ps': 1.05, 'pa': 5.5},
    'gauge_C': {'comid': 4003, 'af': 0.84, 'as_': 0.990, 'cf': 0.18, 'cs': 0.08, 'ps': 0.95, 'pa': 7.0},
    'gauge_D': {'comid': 1004, 'af': 0.88, 'as_': 0.988, 'cf': 0.20, 'cs': 0.06, 'ps': 1.02, 'pa': 5.0},
    'gauge_E': {'comid': 1005, 'af': 0.90, 'as_': 0.992, 'cf': 0.18, 'cs': 0.07, 'ps': 1.00, 'pa': 5.5},
}

os.makedirs('/app/data/gauges', exist_ok=True)

for gid, params in gauge_params.items():
    # Generate INTERMITTENT precipitation (realistic dry periods)
    # Seasonal rain probability (higher in winter, lower in summer)
    rain_prob = 0.35 + 0.20 * np.cos(2 * np.pi * (t - 30) / 365.25)
    rain_prob *= params['ps']
    rain_prob = np.clip(rain_prob, 0.05, 0.75)

    rain_occurs = np.random.random(n_days) < rain_prob
    rain_amount = np.random.exponential(params['pa'], n_days)
    precip = rain_occurs.astype(float) * rain_amount

    # Generate streamflow via two-store recession model
    streamflow = np.zeros(n_days)
    fast = 1.5
    slow = 2.5
    for i in range(n_days):
        fast = params['af'] * fast + params['cf'] * precip[i]
        slow = params['as_'] * slow + params['cs'] * precip[i]
        streamflow[i] = fast + slow
        # Small multiplicative noise (0.5% to keep recessions clean)
        streamflow[i] *= (1.0 + 0.005 * np.random.randn())
        streamflow[i] = max(streamflow[i], 0.01)

    with open(f'/app/data/gauges/{gid}.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'streamflow_mm', 'precipitation_mm'])
        for dt, q, p in zip(dates, streamflow, precip):
            writer.writerow([dt, f'{q:.6f}', f'{p:.6f}'])

# ==============================================================
# 3. Gauge-to-Network Mapping
# ==============================================================

with open('/app/data/gauge_locations.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['gauge_id', 'comid'])
    for gid, params in gauge_params.items():
        writer.writerow([gid, params['comid']])

print(f"Generated network with {len(rows)} segments")
print(f"Generated {len(gauge_params)} gauge datasets ({n_days} days each)")
