#!/usr/bin/env python3
"""
Generate synthetic hierarchical time series data for the WSPL evaluation task.
Uses only the Python standard library (no external dependencies).
Uses a random seed so each Docker build produces unique data, preventing
memorization of expected answers.
"""
import random
import math
import json
import os
import csv

# Use a truly random seed so each build produces unique data
seed = int.from_bytes(os.urandom(8), 'big') % (2**32)
random.seed(seed)

# --- Configuration ---
REGIONS_MAP = {'North': ['N1', 'N2'], 'South': ['S1', 'S2'], 'West': ['W1', 'W2']}
REGION_ORDER = ['North', 'South', 'West']
CATEGORIES = ['A', 'B', 'C']
PRICES = {'A': 3.0, 'B': 7.0, 'C': 5.0}
N_HISTORY = 365
N_FORECAST = 28
QUANTILES = [0.005, 0.025, 0.165, 0.25, 0.5, 0.75, 0.835, 0.975, 0.995]

Z_SCORES = {
    0.005: -2.5758, 0.025: -1.9600, 0.165: -0.9741, 0.25: -0.6745,
    0.5: 0.0, 0.75: 0.6745, 0.835: 0.9741, 0.975: 1.9600, 0.995: 2.5758
}


def gauss(mu=0.0, sigma=1.0):
    return random.gauss(mu, sigma)


def mean_list(lst):
    return sum(lst) / len(lst) if lst else 0.0


def std_dev(lst):
    if len(lst) < 2:
        return 0.0
    m = mean_list(lst)
    return math.sqrt(sum((x - m) ** 2 for x in lst) / (len(lst) - 1))


# --- Bottom-level series ---
bottom_series = []
for region in REGION_ORDER:
    for store in REGIONS_MAP[region]:
        for cat in CATEGORIES:
            bottom_series.append(f"{store}_{cat}")

N_BOTTOM = len(bottom_series)

# --- Hierarchy definition ---
level_order = ['Total', 'Region', 'Store', 'Category', 'Region_Category', 'Store_Category']
levels = {}

levels['Total'] = {'Total': list(range(N_BOTTOM))}

levels['Region'] = {}
idx = 0
for region in REGION_ORDER:
    indices = []
    for store in REGIONS_MAP[region]:
        for cat in CATEGORIES:
            indices.append(idx)
            idx += 1
    levels['Region'][region] = indices

levels['Store'] = {}
idx = 0
for region in REGION_ORDER:
    for store in REGIONS_MAP[region]:
        indices = []
        for cat in CATEGORIES:
            indices.append(idx)
            idx += 1
        levels['Store'][store] = indices

levels['Category'] = {}
for cat in CATEGORIES:
    indices = [i for i, name in enumerate(bottom_series) if name.endswith(f"_{cat}")]
    levels['Category'][f"Cat_{cat}"] = indices

levels['Region_Category'] = {}
for region in REGION_ORDER:
    for cat in CATEGORIES:
        indices = []
        for store in REGIONS_MAP[region]:
            bi = bottom_series.index(f"{store}_{cat}")
            indices.append(bi)
        levels['Region_Category'][f"{region}_{cat}"] = indices

levels['Store_Category'] = {}
for i, name in enumerate(bottom_series):
    levels['Store_Category'][name] = [i]

# All series names
all_series_names = []
for level_name in level_order:
    for series_name in levels[level_name]:
        all_series_names.append(series_name)

# --- Generate time series ---
base_levels = [random.uniform(30, 200) for _ in range(N_BOTTOM)]
trends = [random.uniform(-0.02, 0.05) for _ in range(N_BOTTOM)]
weekly_amps = [random.uniform(5, 30) for _ in range(N_BOTTOM)]
noise_scales = [bl * 0.15 for bl in base_levels]

all_data = [[0.0] * (N_HISTORY + N_FORECAST) for _ in range(N_BOTTOM)]
for i in range(N_BOTTOM):
    for t in range(N_HISTORY + N_FORECAST):
        base = base_levels[i] + trends[i] * t
        weekly = weekly_amps[i] * math.sin(2 * math.pi * t / 7)
        noise = gauss(0, noise_scales[i])
        val = base + weekly + noise
        val = max(round(val), 0)
        all_data[i][t] = float(val)

history_bottom = [row[:N_HISTORY] for row in all_data]
actuals_bottom = [row[N_HISTORY:] for row in all_data]

# --- Compute history and actuals for all series ---
history_all = {}
actuals_all = {}
for level_name in level_order:
    for series_name, indices in levels[level_name].items():
        h = [0.0] * N_HISTORY
        a = [0.0] * N_FORECAST
        for bi in indices:
            for t in range(N_HISTORY):
                h[t] += history_bottom[bi][t]
            for t in range(N_FORECAST):
                a[t] += actuals_bottom[bi][t]
        history_all[series_name] = h
        actuals_all[series_name] = a

# --- Compute scale factors ---
scale_factors = {}
for series_name in all_series_names:
    hist = history_all[series_name]
    diffs = [abs(hist[t] - hist[t - 1]) for t in range(1, len(hist))]
    s = mean_list(diffs) if diffs else 1.0
    s = max(s, 1.0)
    scale_factors[series_name] = s

# --- Compute weights ---
weights = {}
for level_name in level_order:
    level_weights = {}
    total_dollar = 0.0
    for series_name, indices in levels[level_name].items():
        dollar_val = 0.0
        for bi in indices:
            cat = bottom_series[bi].split('_')[1]
            price = PRICES[cat]
            dollar_val += price * mean_list(history_bottom[bi][-28:])
        level_weights[series_name] = dollar_val
        total_dollar += dollar_val
    for sn in level_weights:
        level_weights[sn] /= total_dollar
    weights[level_name] = level_weights

# --- Generate base quantile forecasts (incoherent) ---
base_forecasts = {}

# Bottom level: reasonably calibrated forecasts
for i, name in enumerate(bottom_series):
    recent_mean = mean_list(history_bottom[i][-28:])
    diffs_last7 = [history_bottom[i][-7 + t + 1] - history_bottom[i][-7 + t] for t in range(6)]
    trend_val = mean_list(diffs_last7)

    point_forecast = [0.0] * N_FORECAST
    for h in range(N_FORECAST):
        pf = recent_mean + trend_val * (h + 1) * 0.3
        noise = gauss(0, recent_mean * 0.1)
        point_forecast[h] = max(pf + noise, 0)

    hist_last56 = history_bottom[i][-56:]
    spread = std_dev(hist_last56)
    if spread < recent_mean * 0.2:
        spread = recent_mean * 0.2

    qf = {}
    for q in QUANTILES:
        z = Z_SCORES[q]
        qf[q] = [max(point_forecast[h] + z * spread * 1.2, 0) for h in range(N_FORECAST)]
    base_forecasts[name] = qf

# Upper levels: independently generated (incoherent) with deliberate miscalibration
for level_name in ['Total', 'Region', 'Store', 'Category', 'Region_Category']:
    for series_name, indices in levels[level_name].items():
        hist = history_all[series_name]
        recent_mean = mean_list(hist[-28:])
        diffs_last7 = [hist[-7 + t + 1] - hist[-7 + t] for t in range(6)]
        trend_val = mean_list(diffs_last7)

        point_forecast = [0.0] * N_FORECAST
        for h in range(N_FORECAST):
            pf = recent_mean + trend_val * (h + 1) * 0.3
            noise = gauss(0, recent_mean * 0.08)
            point_forecast[h] = max(pf + noise, 0)

        hist_last56 = hist[-56:]
        spread = std_dev(hist_last56)
        if spread < recent_mean * 0.2:
            spread = recent_mean * 0.2

        qf = {}
        for q in QUANTILES:
            z = Z_SCORES[q]
            # Deliberate miscalibration: wider intervals than needed
            miscalib = 1.0 + random.uniform(0.15, 0.6)
            qf[q] = [max(point_forecast[h] + z * spread * miscalib, 0) for h in range(N_FORECAST)]
        base_forecasts[series_name] = qf

# --- Save data files ---
output_dir = "/app/data"
os.makedirs(output_dir, exist_ok=True)

# hierarchy.json
hierarchy_json = {
    "level_order": level_order,
    "bottom_series": bottom_series,
    "levels": {k: {sk: sv for sk, sv in v.items()} for k, v in levels.items()},
    "regions": {k: v for k, v in REGIONS_MAP.items()},
    "categories": CATEGORIES,
    "prices": PRICES,
    "quantiles": QUANTILES
}
with open(os.path.join(output_dir, "hierarchy.json"), 'w') as f:
    json.dump(hierarchy_json, f, indent=2)

# history.csv
with open(os.path.join(output_dir, "history.csv"), 'w', newline='') as f:
    writer = csv.writer(f)
    header = ['series_name'] + [f'd_{d + 1}' for d in range(N_HISTORY)]
    writer.writerow(header)
    for series_name in all_series_names:
        row = [series_name] + [int(x) for x in history_all[series_name]]
        writer.writerow(row)

# actuals.csv
with open(os.path.join(output_dir, "actuals.csv"), 'w', newline='') as f:
    writer = csv.writer(f)
    header = ['series_name'] + [f'h_{h + 1}' for h in range(N_FORECAST)]
    writer.writerow(header)
    for series_name in all_series_names:
        row = [series_name] + [int(x) for x in actuals_all[series_name]]
        writer.writerow(row)

# base_forecasts.csv
with open(os.path.join(output_dir, "base_forecasts.csv"), 'w', newline='') as f:
    writer = csv.writer(f)
    header = ['series_name', 'quantile'] + [f'h_{h + 1}' for h in range(N_FORECAST)]
    writer.writerow(header)
    for series_name in all_series_names:
        for q in QUANTILES:
            row = [series_name, f"{q:.3f}"] + [f"{x:.4f}" for x in base_forecasts[series_name][q]]
            writer.writerow(row)

# weights.json
weights_out = {}
for level_name in level_order:
    weights_out[level_name] = {k: round(v, 10) for k, v in weights[level_name].items()}
with open(os.path.join(output_dir, "weights.json"), 'w') as f:
    json.dump(weights_out, f, indent=2)

print(f"Data generated with seed {seed}: {os.listdir(output_dir)}")
