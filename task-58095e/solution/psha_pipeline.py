#!/usr/bin/env python3
"""
Multi-IMT PSHA Pipeline with Mixed Distance Metrics, Rupture Floating,
and Epistemic MFD Branching.

"""

import csv
import json
import math
import os
import subprocess
import xml.etree.ElementTree as ET


# ─── Math utilities ───

def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def haversine(lon1, lat1, lon2, lat2):
    R = 6371.0
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return R * 2.0 * math.asin(min(1.0, math.sqrt(a)))


def to_local_km(lon, lat, ref_lon, ref_lat):
    cos_ref = math.cos(math.radians(ref_lat))
    x = (lon - ref_lon) * 111.195 * cos_ref
    y = (lat - ref_lat) * 111.195
    return x, y


def pt_seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    qx = ax + t * dx
    qy = ay + t * dy
    return math.hypot(px - qx, py - qy)


def point_in_polygon(px, py, poly):
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


# ─── UTM to WGS84 via cs2cs ───

def utm_to_wgs84(easting, northing):
    result = subprocess.run(
        ['cs2cs', '-f', '%.10f',
         '+proj=utm', '+zone=10', '+datum=WGS84',
         '+to', '+proj=longlat', '+datum=WGS84'],
        input=f"{easting} {northing}\n",
        capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise RuntimeError(f"cs2cs failed: {result.stderr}")
    parts = result.stdout.strip().split()
    return float(parts[0]), float(parts[1])


# ─── Trace geometry ───

def trace_length_km(trace, ref_lon, ref_lat):
    tkm = [to_local_km(lon, lat, ref_lon, ref_lat) for lon, lat in trace]
    total = 0.0
    for i in range(len(tkm) - 1):
        total += math.hypot(tkm[i + 1][0] - tkm[i][0],
                            tkm[i + 1][1] - tkm[i][1])
    return total


def extract_sub_trace(trace, start_km, end_km, ref_lon, ref_lat):
    """Extract sub-trace at [start_km, end_km] along trace."""
    tkm = [to_local_km(lon, lat, ref_lon, ref_lat) for lon, lat in trace]
    cum = [0.0]
    for i in range(len(tkm) - 1):
        cum.append(cum[-1] + math.hypot(tkm[i + 1][0] - tkm[i][0],
                                         tkm[i + 1][1] - tkm[i][1]))

    def interp(d):
        for i in range(len(cum) - 1):
            if cum[i] <= d <= cum[i + 1] + 1e-9:
                seg = cum[i + 1] - cum[i]
                t = (d - cum[i]) / seg if seg > 1e-12 else 0.0
                return (trace[i][0] + t * (trace[i + 1][0] - trace[i][0]),
                        trace[i][1] + t * (trace[i + 1][1] - trace[i][1]))
        return trace[-1]

    result = [interp(start_km)]
    for i in range(1, len(trace) - 1):
        if start_km < cum[i] < end_km:
            result.append(trace[i])
    result.append(interp(end_km))
    return result


def wc94_length(mag):
    """Wells & Coppersmith 1994, all fault types, subsurface length (km)."""
    return 10.0 ** (-3.22 + 0.69 * mag)


# ─── Distance computation ───

def compute_rjb_fault(trace_lonlat, dip_deg, upper_depth, lower_depth,
                      site_lon, site_lat):
    trace_km = [to_local_km(lon, lat, site_lon, site_lat)
                for lon, lat in trace_lonlat]
    dip_rad = math.radians(dip_deg)

    if abs(dip_deg - 90.0) < 0.01:
        min_d = float('inf')
        for i in range(len(trace_km) - 1):
            d = pt_seg_dist(0, 0,
                            trace_km[i][0], trace_km[i][1],
                            trace_km[i + 1][0], trace_km[i + 1][1])
            min_d = min(min_d, d)
        return min_d

    sx = trace_km[-1][0] - trace_km[0][0]
    sy = trace_km[-1][1] - trace_km[0][1]
    slen = math.hypot(sx, sy)
    if slen < 1e-12:
        return float('inf')
    sux, suy = sx / slen, sy / slen
    pux, puy = suy, -sux

    upper_h = upper_depth / math.tan(dip_rad) if upper_depth > 0 else 0.0
    lower_h = lower_depth / math.tan(dip_rad)

    upper_edge = [(x + pux * upper_h, y + puy * upper_h)
                  for x, y in trace_km]
    lower_edge = [(x + pux * lower_h, y + puy * lower_h)
                  for x, y in reversed(trace_km)]
    polygon = upper_edge + lower_edge

    if point_in_polygon(0, 0, polygon):
        return 0.0

    min_d = float('inf')
    n = len(polygon)
    for i in range(n):
        j = (i + 1) % n
        d = pt_seg_dist(0, 0,
                        polygon[i][0], polygon[i][1],
                        polygon[j][0], polygon[j][1])
        min_d = min(min_d, d)
    return min_d


# ─── MFD discretization ───

def discretize_gr(a, b, mMin, mMax, dMag):
    mags, rates = [], []
    m = mMin
    while m <= mMax + dMag * 0.01:
        r = 10.0 ** (a - b * (m - dMag / 2)) - 10.0 ** (a - b * (m + dMag / 2))
        if r > 0:
            mags.append(round(m, 2))
            rates.append(r)
        m = round(m + dMag, 2)
    return mags, rates


# ─── GMM evaluation ───

def gmm_eval(M, dist, Vs30, ztor, gmm_model, imt):
    """Evaluate GMM with correct distance type and sigma model."""
    c = gmm_model['coefficients'][imt]
    R_eff = math.sqrt(dist ** 2 + c['h'] ** 2)
    mu = (c['c0'] + c['c1'] * (M - 6) + c['c2'] * (M - 6) ** 2 +
          c['c3'] * math.log(R_eff) +
          c['c_site'] * math.log(Vs30 / c['v_ref']))

    if 'c_ztor' in c:
        mu += c['c_ztor'] * math.log(ztor + 1)

    sig_model = gmm_model.get('sigmaModel', 'TOTAL')
    if sig_model == 'PARTITIONED':
        sigma = math.sqrt(c['tau'] ** 2 + c['phi'] ** 2)
    else:
        sigma = c['sigma']

    return mu, sigma


# ─── Exceedance probability ───

def p_exceed(iml, mu, sigma, trunc_level):
    eps = (math.log(iml) - mu) / sigma
    if eps >= trunc_level:
        return 0.0
    return (phi(trunc_level) - phi(eps)) / phi(trunc_level)


# ─── Bin edges and interpolation ───

def make_edges(mn, mx, delta):
    edges = []
    v = mn
    while v <= mx + delta * 0.01:
        edges.append(round(v, 4))
        v = round(v + delta, 4)
    return edges


def interp_iml(imls, haz, target_rate):
    ni = len(imls)
    for k in range(ni - 1):
        if haz[k] >= target_rate >= haz[k + 1]:
            if haz[k] > 0 and haz[k + 1] > 0:
                lr0 = math.log(haz[k])
                lr1 = math.log(haz[k + 1])
                li0 = math.log(imls[k])
                li1 = math.log(imls[k + 1])
                t = (math.log(target_rate) - lr0) / (lr1 - lr0)
                return math.exp(li0 + t * (li1 - li0))
            break
    if haz[0] <= target_rate:
        return imls[0]
    return imls[-1]


# ─── Model loading ───

def load_model():
    with open('/app/model/calc-config.json') as f:
        cc = json.load(f)
    with open('/app/model/active-crust/gmm-config.json') as f:
        gc = json.load(f)

    # Parse XML fault sources with epistemic MFD branches
    tree = ET.parse('/app/model/active-crust/fault/sources.xml')
    root = tree.getroot()
    faults = []
    for src in root.findall('Source'):
        geom = src.find('Geometry')
        trace_text = geom.find('Trace').text.strip()
        trace_pts = []
        for pt_str in trace_text.split():
            parts = pt_str.split(',')
            trace_pts.append((float(parts[0]), float(parts[1])))

        mfd_branches = []
        for mfd_el in src.findall('IncrementalMfd'):
            mfd = {'mfd_type': mfd_el.get('type')}
            w = float(mfd_el.get('weight', '1.0'))
            if mfd['mfd_type'] == 'GR':
                mfd['a_value'] = float(mfd_el.get('a'))
                mfd['b_value'] = float(mfd_el.get('b'))
                mfd['m_min'] = float(mfd_el.get('mMin'))
                mfd['m_max'] = float(mfd_el.get('mMax'))
                mfd['delta_m'] = float(mfd_el.get('dMag'))
            elif mfd['mfd_type'] == 'SINGLE':
                mfd['magnitude'] = float(mfd_el.get('m'))
                mfd['rate'] = float(mfd_el.get('rate'))
            mfd_branches.append((mfd, w))

        faults.append({
            'trace': trace_pts,
            'dip': float(geom.get('dip')),
            'upper_depth': float(geom.get('upperDepth')),
            'lower_depth': float(geom.get('lowerDepth')),
            'mfd_branches': mfd_branches,
        })

    # Parse UTM fault traces
    with open('/app/model/active-crust/fault/utm-traces.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            e1, n1 = float(row['easting_1']), float(row['northing_1'])
            e2, n2 = float(row['easting_2']), float(row['northing_2'])
            lon1, lat1 = utm_to_wgs84(e1, n1)
            lon2, lat2 = utm_to_wgs84(e2, n2)

            mfd = {'mfd_type': row['mfd_type']}
            if mfd['mfd_type'] == 'GR':
                mfd['a_value'] = float(row['a_value'])
                mfd['b_value'] = float(row['b_value'])
                mfd['m_min'] = float(row['m_min'])
                mfd['m_max'] = float(row['m_max'])
                mfd['delta_m'] = float(row['delta_m'])
            elif mfd['mfd_type'] == 'SINGLE':
                mfd['magnitude'] = float(row.get('magnitude', 0))
                mfd['rate'] = float(row.get('rate', 0))

            faults.append({
                'trace': [(lon1, lat1), (lon2, lat2)],
                'dip': float(row['dip']),
                'upper_depth': float(row['upper_depth_km']),
                'lower_depth': float(row['lower_depth_km']),
                'mfd_branches': [(mfd, 1.0)],
            })

    # Parse grid sources
    points = []
    with open('/app/model/active-crust/grid/rates.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            mfd = {'mfd_type': row['mfd_type']}
            if mfd['mfd_type'] == 'GR':
                mfd['a_value'] = float(row['a_value'])
                mfd['b_value'] = float(row['b_value'])
                mfd['m_min'] = float(row['m_min'])
                mfd['m_max'] = float(row['m_max'])
                mfd['delta_m'] = float(row['delta_m'])
            points.append({
                'lon': float(row['longitude']),
                'lat': float(row['latitude']),
                'depth': float(row['depth_km']),
                'mfd': mfd,
            })

    return cc, gc, faults, points


def main():
    cc, gc, faults, points = load_model()

    site_lon = cc['site']['longitude']
    site_lat = cc['site']['latitude']
    vs30 = cc['site']['vs30']
    trunc = cc['hazard']['truncationLevel']
    max_dist = cc['performance']['maxDistance']
    imts = cc['hazard']['imts']
    iml_map = cc['hazard']['customImls']
    gmms = gc['models']
    imt_periods = gc['imt_periods']

    floating = cc.get('model', {}).get('ruptureFloating', 'OFF')
    spacing = cc.get('model', {}).get('surfaceSpacing', 1.0)

    # Build entries: (mag, rate, rjb, rrup, ztor)
    entries = []

    for fault in faults:
        ztor = fault['upper_depth']

        for mfd, mfd_w in fault['mfd_branches']:
            if mfd['mfd_type'] == 'GR':
                mags, rates = discretize_gr(
                    mfd['a_value'], mfd['b_value'],
                    mfd['m_min'], mfd['m_max'], mfd['delta_m'])
            elif mfd['mfd_type'] == 'SINGLE':
                mags, rates = [mfd['magnitude']], [mfd['rate']]
            else:
                continue

            for m, r in zip(mags, rates):
                wr = r * mfd_w

                if floating == 'ALONG_STRIKE':
                    rup_len = wc94_length(m)
                    fault_len = trace_length_km(fault['trace'],
                                               site_lon, site_lat)

                    if rup_len >= fault_len:
                        rjb = compute_rjb_fault(
                            fault['trace'], fault['dip'],
                            fault['upper_depth'], fault['lower_depth'],
                            site_lon, site_lat)
                        if rjb <= max_dist:
                            rrup = math.sqrt(rjb ** 2 + ztor ** 2)
                            entries.append((m, wr, rjb, rrup, ztor))
                    else:
                        n_pos = max(1,
                                    int((fault_len - rup_len) / spacing) + 1)
                        sub_rate = wr / n_pos
                        for pi in range(n_pos):
                            start = pi * spacing
                            end = start + rup_len
                            if end > fault_len:
                                end = fault_len
                                start = fault_len - rup_len
                            st = extract_sub_trace(
                                fault['trace'], start, end,
                                site_lon, site_lat)
                            rjb = compute_rjb_fault(
                                st, fault['dip'],
                                fault['upper_depth'], fault['lower_depth'],
                                site_lon, site_lat)
                            if rjb <= max_dist:
                                rrup = math.sqrt(rjb ** 2 + ztor ** 2)
                                entries.append((m, sub_rate,
                                                rjb, rrup, ztor))
                else:
                    rjb = compute_rjb_fault(
                        fault['trace'], fault['dip'],
                        fault['upper_depth'], fault['lower_depth'],
                        site_lon, site_lat)
                    if rjb <= max_dist:
                        rrup = math.sqrt(rjb ** 2 + ztor ** 2)
                        entries.append((m, wr, rjb, rrup, ztor))

    for pt in points:
        rjb = haversine(pt['lon'], pt['lat'], site_lon, site_lat)
        if rjb > max_dist:
            continue
        depth = pt.get('depth', 0.0)
        rrup = math.sqrt(rjb ** 2 + depth ** 2)
        ztor = depth

        mfd = pt['mfd']
        if mfd['mfd_type'] == 'GR':
            mags, rates = discretize_gr(
                mfd['a_value'], mfd['b_value'],
                mfd['m_min'], mfd['m_max'], mfd['delta_m'])
        elif mfd['mfd_type'] == 'SINGLE':
            mags, rates = [mfd['magnitude']], [mfd['rate']]
        else:
            continue
        for m_val, r_val in zip(mags, rates):
            entries.append((m_val, r_val, rjb, rrup, ztor))

    # ─── Compute hazard curves for each IMT ───
    os.makedirs('/app/output', exist_ok=True)
    all_curves = {}

    for imt in imts:
        imls = iml_map[imt]
        ni = len(imls)
        haz = [0.0] * ni
        for mag, rate, rjb, rrup, ztor in entries:
            for g in gmms:
                dist_type = g.get('distanceType', 'R_JB')
                dist = rrup if dist_type == 'R_RUP' else rjb
                mu, sig = gmm_eval(mag, dist, vs30, ztor, g, imt)
                w = g['weight']
                for k, iml_val in enumerate(imls):
                    haz[k] += rate * p_exceed(iml_val, mu, sig, trunc) * w
        all_curves[imt] = (imls, haz)

    # Write hazard curves CSV
    with open('/app/output/hazard_curves.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['imt', 'iml', 'annual_rate', 'poisson_prob_50yr'])
        for imt in imts:
            imls, haz = all_curves[imt]
            for k, iml_val in enumerate(imls):
                prob = 1.0 - math.exp(-haz[k] * 50.0)
                writer.writerow([imt, f'{iml_val:.6g}',
                                 f'{haz[k]:.8e}', f'{prob:.8e}'])

    # ─── Uniform Hazard Spectrum ───
    rp = cc['disagg']['returnPeriod']
    target_rate = 1.0 / rp
    uhs_ordinates = []

    for imt in imts:
        period = imt_periods[imt]
        imls, haz = all_curves[imt]
        sa = interp_iml(imls, haz, target_rate)
        uhs_ordinates.append({'period': period, 'sa': round(sa, 6)})

    uhs_ordinates.sort(key=lambda x: x['period'])
    uhs_result = {
        'return_period': rp,
        'spectral_ordinates': uhs_ordinates,
    }
    with open('/app/output/uhs.json', 'w') as f:
        json.dump(uhs_result, f, indent=2)

    # ─── PGA Deaggregation ───
    pga_imls, pga_haz = all_curves['PGA']
    target_iml = interp_iml(pga_imls, pga_haz, target_rate)

    db = cc['disagg']['bins']
    m_edges = make_edges(db['mMin'], db['mMax'], db['\u0394m'])
    r_edges = make_edges(db['rMin'], db['rMax'], db['\u0394r'])
    e_edges = make_edges(db['\u03b5Min'], db['\u03b5Max'],
                         db['\u0394\u03b5'])

    nm = len(m_edges) - 1
    nr = len(r_edges) - 1
    ne = len(e_edges) - 1
    contrib = [[[0.0] * ne for _ in range(nr)] for _ in range(nm)]
    ln_timl = math.log(target_iml)

    for mag, rate, rjb, rrup, ztor in entries:
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
        for g in gmms:
            dist_type = g.get('distanceType', 'R_JB')
            dist = rrup if dist_type == 'R_RUP' else rjb
            mu, sig = gmm_eval(mag, dist, vs30, ztor, g, 'PGA')
            w = g['weight']
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

    deagg_result = {
        'target_iml': round(target_iml, 6),
        'return_period': rp,
        'mean_mag': round(mean_m, 4),
        'mean_dist': round(mean_r, 4),
        'mean_eps': round(mean_e, 4),
        'mode_mag': round((m_edges[mode_mi] + m_edges[mode_mi + 1]) / 2, 2),
        'mode_dist': round((r_edges[mode_ri] + r_edges[mode_ri + 1]) / 2, 2),
        'mode_eps': round((e_edges[mode_ei] + e_edges[mode_ei + 1]) / 2, 2),
    }

    with open('/app/output/deagg_pga.json', 'w') as f:
        json.dump(deagg_result, f, indent=2)

    print("PSHA pipeline complete.")
    for imt in imts:
        print(f"  {imt} hazard curve computed")
    print(f"  UHS at {rp}-yr return period: "
          + ", ".join(f"T={o['period']}s SA={o['sa']:.4f}g"
                      for o in uhs_ordinates))
    print(f"  PGA deagg target IML: {target_iml:.4f} g")


if __name__ == '__main__':
    main()
