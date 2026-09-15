#!/usr/bin/env python3
"""
PSHA Hazard Curve Calculator with Deaggregation.
Reads source model from SQLite database and configuration from TOML.

"""

import json
import math
import csv
import os
import sqlite3
import tomllib


def phi(x):
    """Standard normal CDF via error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def haversine(lon1, lat1, lon2, lat2):
    """Great-circle distance in km between two geographic points."""
    R = 6371.0
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return R * 2.0 * math.asin(min(1.0, math.sqrt(a)))


def to_local_km(lon, lat, ref_lon, ref_lat):
    """Convert geographic coordinates to local Cartesian km."""
    cos_ref = math.cos(math.radians(ref_lat))
    x = (lon - ref_lon) * 111.195 * cos_ref
    y = (lat - ref_lat) * 111.195
    return x, y


def pt_seg_dist(px, py, ax, ay, bx, by):
    """Shortest distance from point to segment."""
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-12:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    qx = ax + t * dx
    qy = ay + t * dy
    return math.sqrt((px - qx) ** 2 + (py - qy) ** 2)


def point_in_polygon(px, py, poly):
    """Ray-casting point-in-polygon test."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and \
           (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def compute_rjb_fault(trace_lonlat, dip_deg, upper_depth, lower_depth,
                      site_lon, site_lat):
    """Compute Joyner-Boore distance for a fault source."""
    site_x, site_y = 0.0, 0.0
    trace_km = [to_local_km(lon, lat, site_lon, site_lat)
                for lon, lat in trace_lonlat]

    dip_rad = math.radians(dip_deg)

    if abs(dip_deg - 90.0) < 0.01:
        min_d = float('inf')
        for i in range(len(trace_km) - 1):
            d = pt_seg_dist(site_x, site_y,
                            trace_km[i][0], trace_km[i][1],
                            trace_km[i + 1][0], trace_km[i + 1][1])
            min_d = min(min_d, d)
        return min_d

    sx = trace_km[-1][0] - trace_km[0][0]
    sy = trace_km[-1][1] - trace_km[0][1]
    slen = math.sqrt(sx * sx + sy * sy)
    if slen < 1e-12:
        return float('inf')
    sux, suy = sx / slen, sy / slen
    pux, puy = suy, -sux

    upper_h = upper_depth / math.tan(dip_rad) if upper_depth > 0 else 0.0
    lower_h = lower_depth / math.tan(dip_rad)

    upper_edge = [(x + pux * upper_h, y + puy * upper_h) for x, y in trace_km]
    lower_edge = [(x + pux * lower_h, y + puy * lower_h)
                  for x, y in reversed(trace_km)]
    polygon = upper_edge + lower_edge

    if point_in_polygon(site_x, site_y, polygon):
        return 0.0

    min_d = float('inf')
    n = len(polygon)
    for i in range(n):
        j = (i + 1) % n
        d = pt_seg_dist(site_x, site_y,
                        polygon[i][0], polygon[i][1],
                        polygon[j][0], polygon[j][1])
        min_d = min(min_d, d)
    return min_d


def discretize_gr(a, b, mMin, mMax, dMag):
    """Discretize Gutenberg-Richter MFD into (magnitude, rate) pairs."""
    mags, rates = [], []
    m = mMin
    while m <= mMax + dMag * 0.01:
        r = 10.0 ** (a - b * (m - dMag / 2)) - 10.0 ** (a - b * (m + dMag / 2))
        if r > 0:
            mags.append(round(m, 2))
            rates.append(r)
        m = round(m + dMag, 2)
    return mags, rates


def gmm_eval(M, R_JB, Vs30, c):
    """Evaluate GMM: returns (mu_ln, sigma_ln) of ln(PGA)."""
    R_eff = math.sqrt(R_JB ** 2 + c['h_sq'])
    mu = (c['c0'] + c['c1'] * (M - 6) + c['c2'] * (M - 6) ** 2 +
          c['c3'] * math.log(R_eff) + c['c_site'] * math.log(Vs30 / c['v_ref']))
    return mu, c['sigma']


def p_exceed(iml, mu, sigma, trunc_level):
    """Exceedance probability with upper truncation."""
    eps = (math.log(iml) - mu) / sigma
    if eps >= trunc_level:
        return 0.0
    return (phi(trunc_level) - phi(eps)) / phi(trunc_level)


def make_edges(mn, mx, delta):
    """Generate bin edges from min to max with given step."""
    edges = []
    v = mn
    while v <= mx + delta * 0.01:
        edges.append(round(v, 4))
        v = round(v + delta, 4)
    return edges


def load_sources_from_db(db_path):
    """Load seismic source model from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Model metadata
    meta = {}
    for row in conn.execute("SELECT key, value FROM model_metadata"):
        meta[row['key']] = row['value']
    max_dist = float(meta['max_distance_km'])

    # GMMs
    gmms = []
    for gm in conn.execute("SELECT gmm_id, name, weight FROM gmm_tree"):
        coeffs = {}
        for cr in conn.execute(
            "SELECT coefficient_name, coefficient_value "
            "FROM gmm_coefficients WHERE gmm_id=?", (gm['gmm_id'],)
        ):
            coeffs[cr['coefficient_name']] = cr['coefficient_value']
        gmms.append({'name': gm['name'], 'weight': gm['weight'],
                     'coefficients': coeffs})

    # Fault sources
    faults = []
    for src in conn.execute(
        "SELECT source_id, name FROM sources WHERE source_type='fault'"
    ):
        sid = src['source_id']
        trace = [(r['longitude'], r['latitude']) for r in conn.execute(
            "SELECT longitude, latitude FROM fault_traces "
            "WHERE source_id=? ORDER BY point_order", (sid,)
        )]
        prop = conn.execute(
            "SELECT dip_degrees, rake_degrees, upper_depth_km, lower_depth_km "
            "FROM fault_properties WHERE source_id=?", (sid,)
        ).fetchone()
        mfd = conn.execute(
            "SELECT mfd_type, a_value, b_value, m_min, m_max, delta_m, "
            "magnitude, rate FROM mfd_parameters WHERE source_id=?", (sid,)
        ).fetchone()
        faults.append({
            'name': src['name'], 'trace': trace,
            'dip': prop['dip_degrees'],
            'upper_depth_km': prop['upper_depth_km'],
            'lower_depth_km': prop['lower_depth_km'],
            'mfd': dict(mfd),
        })

    # Point sources
    points = []
    for src in conn.execute(
        "SELECT source_id, name FROM sources WHERE source_type='point'"
    ):
        sid = src['source_id']
        loc = conn.execute(
            "SELECT longitude, latitude, depth_km "
            "FROM point_locations WHERE source_id=?", (sid,)
        ).fetchone()
        mfd = conn.execute(
            "SELECT mfd_type, a_value, b_value, m_min, m_max, delta_m, "
            "magnitude, rate FROM mfd_parameters WHERE source_id=?", (sid,)
        ).fetchone()
        points.append({
            'name': src['name'],
            'lon': loc['longitude'], 'lat': loc['latitude'],
            'mfd': dict(mfd),
        })

    conn.close()
    return faults, points, gmms, max_dist


def main():
    # Read configuration from TOML
    with open('/app/site-config.toml', 'rb') as f:
        cfg = tomllib.load(f)

    site_lon = cfg['site']['longitude']
    site_lat = cfg['site']['latitude']
    vs30 = cfg['site']['vs30']
    imls = cfg['hazard']['imls']
    trunc = cfg['hazard']['truncation_level']

    # Read source model from database
    faults, points, gmms, max_dist = load_sources_from_db('/app/hazard.db')

    # Collect source-magnitude entries
    entries = []

    for fault in faults:
        rjb = compute_rjb_fault(
            fault['trace'], fault['dip'],
            fault['upper_depth_km'], fault['lower_depth_km'],
            site_lon, site_lat)
        if rjb > max_dist:
            continue
        mfd = fault['mfd']
        if mfd['mfd_type'] == 'GR':
            mags, rates = discretize_gr(
                mfd['a_value'], mfd['b_value'],
                mfd['m_min'], mfd['m_max'], mfd['delta_m'])
        elif mfd['mfd_type'] == 'SINGLE':
            mags, rates = [mfd['magnitude']], [mfd['rate']]
        else:
            continue
        for m, r in zip(mags, rates):
            gvals = []
            for g in gmms:
                mu, sig = gmm_eval(m, rjb, vs30, g['coefficients'])
                gvals.append((mu, sig, g['weight']))
            entries.append((m, r, rjb, gvals))

    for pt in points:
        rjb = haversine(pt['lon'], pt['lat'], site_lon, site_lat)
        if rjb > max_dist:
            continue
        mfd = pt['mfd']
        if mfd['mfd_type'] == 'GR':
            mags, rates = discretize_gr(
                mfd['a_value'], mfd['b_value'],
                mfd['m_min'], mfd['m_max'], mfd['delta_m'])
        elif mfd['mfd_type'] == 'SINGLE':
            mags, rates = [mfd['magnitude']], [mfd['rate']]
        else:
            continue
        for m, r in zip(mags, rates):
            gvals = []
            for g in gmms:
                mu, sig = gmm_eval(m, rjb, vs30, g['coefficients'])
                gvals.append((mu, sig, g['weight']))
            entries.append((m, r, rjb, gvals))

    # Compute hazard curve
    n_imls = len(imls)
    haz = [0.0] * n_imls
    for mag, rate, rjb, gvals in entries:
        for mu, sig, w in gvals:
            for k, iml in enumerate(imls):
                haz[k] += rate * p_exceed(iml, mu, sig, trunc) * w

    # Write hazard curve
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/hazard_curve.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['iml', 'annual_rate', 'poisson_prob_50yr'])
        for k, iml in enumerate(imls):
            prob = 1.0 - math.exp(-haz[k] * 50.0)
            writer.writerow([f'{iml:.6g}', f'{haz[k]:.8e}', f'{prob:.8e}'])

    # --- Deaggregation ---
    dcfg = cfg['deagg']
    target_rate = 1.0 / dcfg['return_period']

    # Interpolate hazard curve (log-log) to find target IML
    target_iml = None
    for k in range(n_imls - 1):
        if haz[k] >= target_rate >= haz[k + 1]:
            if haz[k] > 0 and haz[k + 1] > 0:
                lr0 = math.log(haz[k])
                lr1 = math.log(haz[k + 1])
                li0 = math.log(imls[k])
                li1 = math.log(imls[k + 1])
                t = (math.log(target_rate) - lr0) / (lr1 - lr0)
                target_iml = math.exp(li0 + t * (li1 - li0))
            break

    if target_iml is None:
        if haz[0] <= target_rate:
            target_iml = imls[0]
        else:
            target_iml = imls[-1]

    # Build deaggregation bins
    m_edges = make_edges(dcfg['mag_bins']['min'],
                         dcfg['mag_bins']['max'],
                         dcfg['mag_bins']['delta'])
    r_edges = make_edges(dcfg['dist_bins']['min'],
                         dcfg['dist_bins']['max'],
                         dcfg['dist_bins']['delta'])
    e_edges = make_edges(dcfg['eps_bins']['min'],
                         dcfg['eps_bins']['max'],
                         dcfg['eps_bins']['delta'])

    nm = len(m_edges) - 1
    nr = len(r_edges) - 1
    ne = len(e_edges) - 1
    contrib = [[[0.0] * ne for _ in range(nr)] for _ in range(nm)]

    ln_timl = math.log(target_iml)

    for mag, rate, rjb, gvals in entries:
        mi = -1
        for i in range(nm):
            if m_edges[i] <= mag + 1e-9 and mag - 1e-9 < m_edges[i + 1]:
                mi = i
                break
        if mi < 0:
            continue

        ri = -1
        for i in range(nr):
            if r_edges[i] <= rjb + 1e-9 and rjb - 1e-9 < r_edges[i + 1]:
                ri = i
                break
        if ri < 0:
            continue

        for mu, sig, w in gvals:
            eps0 = (ln_timl - mu) / sig
            for ei in range(ne):
                elo = max(e_edges[ei], eps0)
                ehi = min(e_edges[ei + 1], trunc)
                if elo >= ehi:
                    continue
                p_bin = (phi(ehi) - phi(elo)) / phi(trunc)
                contrib[mi][ri][ei] += rate * p_bin * w

    total = sum(contrib[mi][ri][ei]
                for mi in range(nm) for ri in range(nr) for ei in range(ne))
    if total < 1e-30:
        total = 1.0

    mean_m = mean_r = mean_e = 0.0
    mode_val = 0.0
    mode_mi = mode_ri = mode_ei = 0

    for mi in range(nm):
        mc = (m_edges[mi] + m_edges[mi + 1]) / 2
        for ri in range(nr):
            rc = (r_edges[ri] + r_edges[ri + 1]) / 2
            for ei in range(ne):
                ec = (e_edges[ei] + e_edges[ei + 1]) / 2
                frac = contrib[mi][ri][ei] / total
                mean_m += mc * frac
                mean_r += rc * frac
                mean_e += ec * frac
                if contrib[mi][ri][ei] > mode_val:
                    mode_val = contrib[mi][ri][ei]
                    mode_mi, mode_ri, mode_ei = mi, ri, ei

    result = {
        'iml_at_return_period': round(target_iml, 6),
        'return_period': dcfg['return_period'],
        'target_annual_rate': target_rate,
        'total_contribution_rate': round(total, 10),
        'mean_mag': round(mean_m, 4),
        'mean_dist': round(mean_r, 4),
        'mean_eps': round(mean_e, 4),
        'mode_mag': round((m_edges[mode_mi] + m_edges[mode_mi + 1]) / 2, 2),
        'mode_dist': round((r_edges[mode_ri] + r_edges[mode_ri + 1]) / 2, 2),
        'mode_eps': round((e_edges[mode_ei] + e_edges[mode_ei + 1]) / 2, 2)
    }

    with open('/app/output/deagg_summary.json', 'w') as f:
        json.dump(result, f, indent=2)

    print("PSHA calculation complete.")
    print(f"  Hazard curve: /app/output/hazard_curve.csv")
    print(f"  Deagg summary: /app/output/deagg_summary.json")
    print(f"  Target IML at {dcfg['return_period']}-yr return period: "
          f"{target_iml:.4f} g")


if __name__ == '__main__':
    main()
