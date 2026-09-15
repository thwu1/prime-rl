#!/usr/bin/env python3
"""Fire weather extreme analysis pipeline.

1. Compute CFFWIS indices for all stations using corrected cffwis.py
2. Extract annual FWI maxima per station
3. Fit GEV distributions and compute return levels
4. Optimize danger thresholds against fire occurrence data
5. Write results.json
"""


import csv
import json
import math
import sys
import importlib.util
from collections import defaultdict

import numpy as np
from scipy.stats import genextreme


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_csv_grouped(filepath, key_field='station_id'):
    data = defaultdict(list)
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = int(row[key_field])
            data[sid].append(row)
    return dict(data)


def compute_all_indices(cffwis, weather_file, output_file):
    """Run CFFWIS computation for all stations, write to CSV."""
    station_data = defaultdict(list)
    with open(weather_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = int(row['station_id'])
            station_data[sid].append({
                'date': row['date'],
                'lat': float(row['lat']),
                'tas': float(row['tas_degC']),
                'pr': float(row['pr_mm']),
                'hurs': float(row['hurs_pct']),
                'sfcWind': float(row['sfcWind_kmh']),
            })

    results = []

    for sid in sorted(station_data.keys()):
        sdata = station_data[sid]
        lat = sdata[0]['lat']
        n = len(sdata)

        temps = [d['tas'] for d in sdata]
        season = cffwis.fire_season_wf93(temps)

        dc = float('nan')
        dmc = float('nan')
        ffmc = float('nan')
        last_dc = float('nan')
        winter_pr = 0.0
        in_season = False

        for i in range(n):
            d = sdata[i]
            dt = d['date']
            month = int(dt.split('-')[1])

            prev_in_season = in_season
            in_season = season[i]

            if in_season and not prev_in_season:
                if not math.isnan(last_dc):
                    dc = cffwis.overwintering_dc(last_dc, winter_pr)
                else:
                    dc = cffwis.DC_START
                dmc = cffwis.DMC_START
                ffmc = cffwis.FFMC_START
                winter_pr = 0.0
            elif not in_season and prev_in_season:
                last_dc = dc
                winter_pr = d['pr']
                dc = float('nan')
                dmc = float('nan')
                ffmc = float('nan')
            elif not in_season:
                winter_pr += d['pr']

            if in_season:
                ffmc = cffwis.calc_ffmc(d['tas'], d['pr'], d['sfcWind'],
                                        d['hurs'], ffmc)
                dmc = cffwis.calc_dmc(d['tas'], d['pr'], d['hurs'],
                                      month, lat, dmc)
                dc = cffwis.calc_dc(d['tas'], d['pr'], month, lat, dc)
                isi = cffwis.calc_isi(d['sfcWind'], ffmc)
                bui = cffwis.calc_bui(dmc, dc)
                fwi = cffwis.calc_fwi(isi, bui)
                dsr = cffwis.calc_dsr(fwi)
            else:
                isi = float('nan')
                bui = float('nan')
                fwi = float('nan')
                dsr = float('nan')

            results.append({
                'date': dt,
                'station_id': sid,
                'DC': dc, 'DMC': dmc, 'FFMC': ffmc,
                'ISI': isi, 'BUI': bui, 'FWI': fwi,
                'DSR': dsr, 'season_mask': 1 if in_season else 0,
            })

    fieldnames = ['date', 'station_id', 'FFMC', 'DMC', 'DC',
                  'ISI', 'BUI', 'FWI', 'DSR', 'season_mask']
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            out_row = {}
            for k, v in r.items():
                if isinstance(v, float):
                    if math.isnan(v):
                        out_row[k] = ''
                    else:
                        out_row[k] = f'{v:.6f}'
                else:
                    out_row[k] = v
            writer.writerow(out_row)

    print(f"Wrote {len(results)} rows to {output_file}")


def extract_annual_maxima(fwi_output_file, min_season_days=30):
    """Extract annual FWI maxima per station from fire season days.

    Returns dict: {station_id: list of annual maxima}
    Years with fewer than min_season_days fire season days are excluded.
    """
    station_data = load_csv_grouped(fwi_output_file)
    annual_maxima = {}

    for sid, rows in station_data.items():
        # Group by year
        yearly = defaultdict(lambda: {'fwi_vals': [], 'season_days': 0})
        for row in rows:
            year = int(row['date'].split('-')[0])
            if int(row['season_mask']) == 1:
                fwi_str = row['FWI']
                if fwi_str != '':
                    fwi_val = float(fwi_str)
                    if not math.isnan(fwi_val):
                        yearly[year]['fwi_vals'].append(fwi_val)
                yearly[year]['season_days'] += 1

        maxima = []
        for year in sorted(yearly.keys()):
            ydata = yearly[year]
            if ydata['season_days'] >= min_season_days and ydata['fwi_vals']:
                maxima.append(max(ydata['fwi_vals']))

        annual_maxima[sid] = maxima

    return annual_maxima


def fit_gev(maxima):
    """Fit GEV distribution to annual maxima using MLE.

    Returns (shape_xi, location, scale) in standard parameterization.
    shape_xi = -c where c is scipy's shape parameter.
    """
    data = np.array(maxima)
    c, loc, scale = genextreme.fit(data)
    # Convert scipy's c to standard GEV shape xi = -c
    xi = -c
    return xi, loc, scale


def compute_return_levels(xi, mu, sigma, return_periods):
    """Compute return levels from GEV parameters.

    Return level z_T satisfies P(X > z_T) = 1/T.
    """
    c = -xi  # scipy parameterization
    levels = {}
    for T in return_periods:
        z = genextreme.isf(1.0 / T, c, loc=mu, scale=sigma)
        levels[str(T)] = float(z)
    return levels


def compute_contingency(fwi_values, fire_occurred, threshold):
    """Compute contingency table for binary classification.

    Returns (TP, FP, FN, TN).
    """
    tp = fp = fn = tn = 0
    for fwi, fire in zip(fwi_values, fire_occurred):
        predicted = 1 if fwi >= threshold else 0
        if predicted == 1 and fire == 1:
            tp += 1
        elif predicted == 1 and fire == 0:
            fp += 1
        elif predicted == 0 and fire == 1:
            fn += 1
        else:
            tn += 1
    return tp, fp, fn, tn


def compute_csi(tp, fp, fn):
    denom = tp + fn + fp
    return tp / denom if denom > 0 else 0.0


def compute_hss(tp, fp, fn, tn):
    num = 2.0 * (tp * tn - fn * fp)
    denom = (tp + fn) * (fn + tn) + (tp + fp) * (fp + tn)
    return num / denom if denom > 0 else 0.0


def compute_pod(tp, fn):
    denom = tp + fn
    return tp / denom if denom > 0 else 0.0


def compute_far(tp, fp):
    denom = tp + fp
    return fp / denom if denom > 0 else 0.0


def optimize_threshold(fwi_values, fire_occurred, n_candidates=200):
    """Find FWI threshold that maximizes CSI.

    Uses grid search over quantiles of FWI values.
    """
    if not fwi_values:
        return 0.0

    sorted_fwi = sorted(fwi_values)
    n = len(sorted_fwi)

    best_csi = -1.0
    best_threshold = sorted_fwi[n // 2]

    # Search over quantiles
    for i in range(n_candidates):
        idx = int(i * n / n_candidates)
        if idx >= n:
            idx = n - 1
        threshold = sorted_fwi[idx]

        tp, fp, fn, tn = compute_contingency(fwi_values, fire_occurred, threshold)
        csi = compute_csi(tp, fp, fn)

        if csi > best_csi:
            best_csi = csi
            best_threshold = threshold

    return best_threshold


def main():
    # Load corrected CFFWIS module
    cffwis = load_module('/app/cffwis.py', 'cffwis')

    # Step 1: Compute CFFWIS indices
    print("Computing CFFWIS indices...")
    compute_all_indices(cffwis, '/app/weather_data.csv', '/app/fwi_output.csv')

    # Step 2: Load outputs and fire data
    fwi_data = load_csv_grouped('/app/fwi_output.csv')
    fire_data = load_csv_grouped('/app/fire_events.csv')

    # Step 3: Extract annual maxima
    print("Extracting annual maxima...")
    annual_maxima = extract_annual_maxima('/app/fwi_output.csv')

    # Step 4: For each station, fit GEV + optimize thresholds
    results = {'stations': {}}

    for sid in sorted(fwi_data.keys()):
        print(f"Processing station {sid}...")
        maxima = annual_maxima[sid]

        if len(maxima) < 5:
            print(f"  Warning: only {len(maxima)} annual maxima, skipping GEV fit")
            continue

        # Fit GEV
        xi, mu, sigma = fit_gev(maxima)
        print(f"  GEV: xi={xi:.3f}, mu={mu:.2f}, sigma={sigma:.2f}")

        # Return levels
        return_levels = compute_return_levels(xi, mu, sigma, [20, 50, 100])
        print(f"  Return levels: {return_levels}")

        # Prepare fire season FWI + fire occurrence pairs
        fwi_rows = fwi_data[sid]
        fire_rows = fire_data[sid]
        season_fwi = []
        season_fire = []

        for i in range(len(fwi_rows)):
            if int(fwi_rows[i]['season_mask']) != 1:
                continue
            fwi_str = fwi_rows[i]['FWI']
            if fwi_str == '':
                continue
            fwi_val = float(fwi_str)
            if math.isnan(fwi_val):
                continue
            fire = int(fire_rows[i]['fire_occurred'])
            season_fwi.append(fwi_val)
            season_fire.append(fire)

        # Optimize threshold
        threshold = optimize_threshold(season_fwi, season_fire)
        print(f"  Optimal threshold: {threshold:.2f}")

        # Compute verification metrics at optimal threshold
        tp, fp, fn, tn = compute_contingency(season_fwi, season_fire, threshold)
        hss = compute_hss(tp, fp, fn, tn)
        pod = compute_pod(tp, fn)
        far = compute_far(tp, fp)
        csi = compute_csi(tp, fp, fn)
        print(f"  HSS={hss:.3f}, POD={pod:.3f}, FAR={far:.3f}, CSI={csi:.3f}")

        results['stations'][str(sid)] = {
            'gev_params': {
                'shape': round(xi, 6),
                'location': round(mu, 6),
                'scale': round(sigma, 6),
            },
            'return_levels': {
                k: round(v, 4) for k, v in return_levels.items()
            },
            'danger_threshold': round(threshold, 4),
            'verification': {
                'hss': round(hss, 6),
                'pod': round(pod, 6),
                'far': round(far, 6),
                'csi': round(csi, 6),
            },
        }

    # Write results
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Wrote results for {len(results['stations'])} stations to /app/results.json")


if __name__ == '__main__':
    main()
