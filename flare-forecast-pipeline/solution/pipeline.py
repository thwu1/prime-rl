#!/usr/bin/env python3
"""
Solar flare catalog spatial analysis pipeline.
Reconciles coordinates, converts to Carrington frame, produces analysis outputs.
"""

import pandas as pd
import numpy as np
import json
import os
import warnings

warnings.filterwarnings('ignore')

from astropy.time import Time


# =============================================
# Utilities
# =============================================

GOES_BASES = {'A': 1e-8, 'B': 1e-7, 'C': 1e-6, 'M': 1e-5, 'X': 1e-4}


def parse_location_ssw(loc_str):
    """Parse SSW location string like 'N24E77' to (lat, lon) in HGS.
    Convention: north positive, west positive."""
    if pd.isna(loc_str):
        return np.nan, np.nan
    s = str(loc_str).strip()
    if len(s) < 6:
        return np.nan, np.nan
    try:
        ns = s[0]
        lat_deg = int(s[1:3])
        ew = s[3]
        lon_deg = int(s[4:6])
        lat = float(lat_deg if ns == 'N' else -lat_deg)
        lon = float(lon_deg if ew == 'W' else -lon_deg)
        return lat, lon
    except (ValueError, IndexError):
        return np.nan, np.nan


def parse_goes_flux(cls_str):
    """Parse GOES class string (e.g. 'M3.5') to peak flux in W/m^2."""
    s = str(cls_str).strip()
    letter = s[0].upper()
    try:
        subclass = float(s[1:])
    except ValueError:
        subclass = 1.0
    return subclass * GOES_BASES.get(letter, 0)


def compute_jd(timestamps):
    """Convert pandas Timestamps to Julian Dates using astropy."""
    t = Time(timestamps.values.astype('datetime64[ns]'))
    return t.jd


def compute_carrington(jd):
    """Compute Carrington rotation number (float) and L0 from Julian Dates.
    CR = (JD - 2398167.4) / 27.2753 + 1
    L0 = 360 * (ceil(CR) - CR)  [Carrington longitude of central meridian]
    """
    cr = (jd - 2398167.4) / 27.2753 + 1.0
    l0 = 360.0 * (np.ceil(cr) - cr)
    return cr, l0


def main():
    print("Loading catalog...")
    df = pd.read_csv('/app/data/flare_catalog.csv')
    df['event_starttime'] = pd.to_datetime(df['event_starttime'])
    n_total = len(df)
    print(f"  {n_total} events loaded")

    # =============================================
    # 1. Coordinate audit - discover quality issues
    # =============================================
    print("\n=== Coordinate Audit ===")

    has_stony = df['lat_stony'].notna() & df['lon_stony'].notna()
    has_ssw_num = df['lat_ssw'].notna() & df['lon_ssw'].notna()
    has_loc_str = df['location_ssw'].notna() & (df['location_ssw'].astype(str).str.len() >= 6)

    # Parse location strings to get reference coordinates
    parsed = df['location_ssw'].apply(parse_location_ssw)
    ref_lat = np.array([p[0] for p in parsed], dtype=float)
    ref_lon = np.array([p[1] for p in parsed], dtype=float)
    has_ref = np.isfinite(ref_lat) & np.isfinite(ref_lon)

    # Detect systematic column swap by comparing numeric columns with parsed reference
    issues = []

    valid_ssw = has_ssw_num.values & has_ref
    if valid_ssw.sum() > 100:
        lat_ssw_v = df.loc[valid_ssw, 'lat_ssw'].values
        lon_ssw_v = df.loc[valid_ssw, 'lon_ssw'].values
        rl = ref_lat[valid_ssw]
        rn = ref_lon[valid_ssw]

        err_correct = np.nanmean(np.abs(lat_ssw_v - rl) + np.abs(lon_ssw_v - rn))
        err_swapped = np.nanmean(np.abs(lat_ssw_v - rn) + np.abs(lon_ssw_v - rl))
        ssw_swapped = err_swapped < err_correct
        print(f"  SSW swap test: err_correct={err_correct:.2f}, err_swapped={err_swapped:.2f}")
    else:
        ssw_swapped = False

    valid_stony = has_stony.values & has_ref
    if valid_stony.sum() > 50:
        lat_st_v = df.loc[valid_stony, 'lat_stony'].values
        lon_st_v = df.loc[valid_stony, 'lon_stony'].values
        rl_st = ref_lat[valid_stony]
        rn_st = ref_lon[valid_stony]
        err_c_st = np.nanmean(np.abs(lat_st_v - rl_st) + np.abs(lon_st_v - rn_st))
        err_s_st = np.nanmean(np.abs(lat_st_v - rn_st) + np.abs(lon_st_v - rl_st))
        stony_swapped = err_s_st < err_c_st
        print(f"  Stony swap test: err_correct={err_c_st:.2f}, err_swapped={err_s_st:.2f}")
    else:
        stony_swapped = ssw_swapped

    if ssw_swapped:
        issues.append(
            "lat_ssw and lon_ssw columns contain swapped values: "
            "lat_ssw holds heliographic longitude, lon_ssw holds latitude"
        )
    if stony_swapped:
        issues.append(
            "lat_stony and lon_stony columns contain swapped values: "
            "lat_stony holds heliographic longitude, lon_stony holds latitude"
        )

    has_any = has_stony | has_ssw_num | has_loc_str
    events_no_coords = int((~has_any).sum())
    if events_no_coords > 0:
        issues.append(f"{events_no_coords} events have no position data from any source")

    audit = {
        "total_events": n_total,
        "events_with_any_coords": int(has_any.sum()),
        "events_no_coords": events_no_coords,
        "data_quality_issues": issues
    }

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/coordinate_audit.json', 'w') as f:
        json.dump(audit, f, indent=2)
    print(f"  Audit: {len(issues)} issues found")

    # =============================================
    # 2. Reconcile coordinates
    # =============================================
    print("\n=== Coordinate Reconciliation ===")

    hgs_lat = np.full(n_total, np.nan)
    hgs_lon = np.full(n_total, np.nan)
    coord_source = np.full(n_total, 'none', dtype=object)

    # Priority 1: parsed location strings (direct reference)
    m1 = has_ref
    hgs_lat[m1] = ref_lat[m1]
    hgs_lon[m1] = ref_lon[m1]
    coord_source[m1] = 'location_ssw_parsed'

    # Priority 2: Stony coordinates (swap-corrected if needed)
    still_missing = np.isnan(hgs_lat)
    m2 = still_missing & has_stony.values
    if stony_swapped:
        hgs_lat[m2] = df.loc[m2, 'lon_stony'].values
        hgs_lon[m2] = df.loc[m2, 'lat_stony'].values
    else:
        hgs_lat[m2] = df.loc[m2, 'lat_stony'].values
        hgs_lon[m2] = df.loc[m2, 'lon_stony'].values
    coord_source[m2] = 'stony_corrected'

    # Priority 3: SSW numeric (swap-corrected if needed)
    still_missing = np.isnan(hgs_lat)
    m3 = still_missing & has_ssw_num.values
    if ssw_swapped:
        hgs_lat[m3] = df.loc[m3, 'lon_ssw'].values
        hgs_lon[m3] = df.loc[m3, 'lat_ssw'].values
    else:
        hgs_lat[m3] = df.loc[m3, 'lat_ssw'].values
        hgs_lon[m3] = df.loc[m3, 'lon_ssw'].values
    coord_source[m3] = 'ssw_numeric_corrected'

    df['hgs_lat'] = hgs_lat
    df['hgs_lon'] = hgs_lon
    df['coord_source'] = coord_source
    df['has_coords'] = np.isfinite(hgs_lat)
    print(f"  Coords recovered: {df['has_coords'].sum()} / {n_total}")

    # =============================================
    # 3. Carrington coordinates
    # =============================================
    print("\n=== Carrington Conversion ===")

    jd = compute_jd(df['event_starttime'])
    cr_float, l0_values = compute_carrington(jd)
    cr_int = np.floor(cr_float).astype(int)

    hgc_lon = np.where(np.isfinite(hgs_lon), (hgs_lon + l0_values) % 360.0, np.nan)
    hgc_lat = hgs_lat.copy()

    df['hgc_lat'] = hgc_lat
    df['hgc_lon'] = hgc_lon
    df['carrington_rotation'] = cr_int

    out_cols = ['event_starttime', 'fl_goescls', 'ar_noaanum',
                'hgs_lat', 'hgs_lon', 'hgc_lat', 'hgc_lon',
                'carrington_rotation', 'coord_source', 'has_coords']
    df[out_cols].to_csv('/app/output/corrected_catalog.csv', index=False)
    print(f"  CR range: {cr_int.min()} - {cr_int.max()}")

    # =============================================
    # 4. Rotation profile
    # =============================================
    print("\n=== Rotation Profile ===")

    df['goes_letter'] = df['fl_goescls'].str[0].str.upper()
    df['goes_flux'] = df['fl_goescls'].apply(parse_goes_flux)

    rot_groups = df.groupby('carrington_rotation')
    rotation_data = []
    for cr, grp in rot_groups:
        cc = grp['goes_letter'].value_counts()

        valid_lons = grp.loc[grp['has_coords'], 'hgc_lon'].dropna()
        if len(valid_lons) > 0:
            bins = np.arange(0, 391, 30)
            hist, _ = np.histogram(valid_lons, bins=bins)
            peak_idx = int(np.argmax(hist))
            peak_lon = float((bins[peak_idx] + bins[peak_idx + 1]) / 2.0)
        else:
            peak_lon = np.nan

        rotation_data.append({
            'carrington_rotation': int(cr),
            'total_flares': len(grp),
            'a_class': int(cc.get('A', 0)),
            'b_class': int(cc.get('B', 0)),
            'c_class': int(cc.get('C', 0)),
            'm_class': int(cc.get('M', 0)),
            'x_class': int(cc.get('X', 0)),
            'total_goes_flux': float(grp['goes_flux'].sum()),
            'peak_activity_longitude': peak_lon
        })

    rot_df = pd.DataFrame(rotation_data)
    rot_df.to_csv('/app/output/rotation_profile.csv', index=False)
    print(f"  {len(rot_df)} rotations")

    # =============================================
    # 5. Geoeffective events
    # =============================================
    print("\n=== Geoeffective Events ===")

    mx_mask = df['goes_letter'].isin(['M', 'X']) & df['has_coords']
    mx_df = df[mx_mask].copy()

    lat_rad = np.radians(mx_df['hgs_lat'].values)
    lon_rad = np.radians(mx_df['hgs_lon'].values)
    cos_theta = np.cos(lat_rad) * np.cos(lon_rad)
    cos_theta = np.clip(cos_theta, -1.0, 1.0)
    angular_dist = np.degrees(np.arccos(cos_theta))
    geo_score = np.clip(cos_theta, 0.0, 1.0)

    mx_out = mx_df[['event_starttime', 'fl_goescls', 'ar_noaanum',
                      'hgs_lat', 'hgs_lon', 'hgc_lat', 'hgc_lon']].copy()
    mx_out['angular_distance_deg'] = angular_dist
    mx_out['geo_score'] = geo_score
    mx_out.to_csv('/app/output/geoeffective_events.csv', index=False)
    print(f"  {len(mx_out)} M/X events with coordinates")

    # =============================================
    # 6. AR summary
    # =============================================
    print("\n=== AR Summary ===")

    has_ar = df['ar_noaanum'].notna() & (df['ar_noaanum'] > 0)
    ar_df = df[has_ar].copy()
    ar_groups = ar_df.groupby('ar_noaanum')

    ar_data = []
    for ar_num, grp in ar_groups:
        cc = grp['goes_letter'].value_counts()
        valid_hgc = grp.loc[grp['has_coords'], 'hgc_lon'].dropna()

        ar_data.append({
            'ar_noaanum': int(ar_num),
            'total_flares': len(grp),
            'c_class': int(cc.get('C', 0)),
            'm_class': int(cc.get('M', 0)),
            'x_class': int(cc.get('X', 0)),
            'total_goes_flux': float(grp['goes_flux'].sum()),
            'mean_hgc_lon': float(valid_hgc.mean()) if len(valid_hgc) > 0 else np.nan,
            'first_seen': str(grp['event_starttime'].min()),
            'last_seen': str(grp['event_starttime'].max())
        })

    ar_summary = pd.DataFrame(ar_data)
    ar_summary.to_csv('/app/output/ar_summary.csv', index=False)
    print(f"  {len(ar_summary)} active regions")

    print("\n=== Pipeline complete ===")


if __name__ == '__main__':
    main()
