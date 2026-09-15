#!/usr/bin/env python3
"""Generate comparison report for conDecay vs varDecay snow model runs."""

import json
import numpy as np
import netCDF4 as nc

DT = 3600.0


def compute_config_stats(output_path):
    """Compute summary statistics for a single configuration output."""
    ds = nc.Dataset(output_path, 'r')
    swe = ds.variables['scalarSWE'][:, 0]
    albedo = ds.variables['scalarSnowAlbedo'][:, 0]
    rain_melt = ds.variables['scalarRainPlusMelt'][:, 0]
    sublim = ds.variables['scalarSnowSublimation'][:, 0]
    ds.close()

    snow_mask = swe > 0.1

    return {
        'peak_swe_kg_m2': float(np.max(swe)),
        'peak_swe_timestep': int(np.argmax(swe)),
        'total_melt_kg_m2': float(np.sum(rain_melt) * DT),
        'mean_snow_albedo': float(np.mean(albedo[snow_mask])) if np.any(snow_mask) else 0.0,
        'snow_covered_hours': int(np.sum(snow_mask)),
        'total_sublimation_kg_m2': float(np.sum(sublim) * DT),
    }


def find_melt_onset(output_path):
    """Find first timestep where SWE begins sustained decrease.

    Sustained decrease: SWE drops > 0.5 kg/m2 over next 24 hours
    while SWE > 1.0 kg/m2.
    """
    ds = nc.Dataset(output_path, 'r')
    swe = ds.variables['scalarSWE'][:, 0]
    ds.close()

    for i in range(len(swe) - 24):
        if swe[i] > 1.0 and (swe[i] - swe[i + 24]) > 0.5:
            return i
    return len(swe) - 1


def main():
    con_path = '/app/output/conDecay_output.nc'
    var_path = '/app/output/varDecay_output.nc'

    con_stats = compute_config_stats(con_path)
    var_stats = compute_config_stats(var_path)

    # Compute divergence metrics
    ds_con = nc.Dataset(con_path, 'r')
    ds_var = nc.Dataset(var_path, 'r')
    swe_con = ds_con.variables['scalarSWE'][:, 0]
    swe_var = ds_var.variables['scalarSWE'][:, 0]
    alb_con = ds_con.variables['scalarSnowAlbedo'][:, 0]
    alb_var = ds_var.variables['scalarSnowAlbedo'][:, 0]
    ds_con.close()
    ds_var.close()

    onset_con = find_melt_onset(con_path)
    onset_var = find_melt_onset(var_path)

    report = {
        'conDecay': con_stats,
        'varDecay': var_stats,
        'divergence': {
            'max_swe_difference_kg_m2': float(np.max(np.abs(swe_con - swe_var))),
            'max_albedo_difference': float(np.max(np.abs(alb_con - alb_var))),
            'melt_onset_difference_hours': int(onset_con - onset_var),
        }
    }

    with open('/app/comparison_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("Written /app/comparison_report.json")


if __name__ == '__main__':
    main()
