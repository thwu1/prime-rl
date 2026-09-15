#!/usr/bin/env python3
"""
Multi-period PSHA Calculator.

Reads heterogeneous model data (namespaced XML, SQLite, GeoJSON, TOML),
implements the full probabilistic seismic hazard analysis integral across
multiple spectral periods with 3D fault geometry and basin depth effects,
and writes hazard curves, uniform hazard spectra, and deaggregation output.
"""

import csv
import json
import math
import os
import re
import sqlite3
import tomllib
import xml.etree.ElementTree as ET
from scipy.stats import norm


# ---------------------------------------------------------------------------
# Model Loading
# ---------------------------------------------------------------------------

_NS = {
    's': 'urn:nshmp:sources:1.0',
    'mfd': 'urn:nshmp:mfd:1.0',
    'fault': 'urn:nshmp:fault:1.0',
}


def load_sources(model_dir):
    tree = ET.parse(os.path.join(model_dir, 'sources.xml'))
    root = tree.getroot()
    sources = []
    for elem in root.findall('s:source', _NS):
        stype = elem.get('type')
        gr = elem.find('mfd:gutenbergRichter', _NS)
        mfd = {
            'a': float(gr.get('a')),
            'b': float(gr.get('b')),
            'mMin': float(gr.get('mMin')),
            'mMax': float(gr.get('mMax')),
            'dMag': float(gr.get('dMag')),
        }
        ep = gr.find('mfd:mMaxEpistemic', _NS)
        if ep is not None:
            brs = []
            for br in ep.findall('mfd:branch', _NS):
                brs.append({'mMax': float(br.get('mMax')),
                            'weight': float(br.get('weight'))})
            mfd['mMaxEpistemic'] = {'branches': brs}

        src = {'id': elem.get('id'), 'type': stype, 'mfd': mfd}
        if stype == 'point':
            loc = elem.find('s:location', _NS)
            src['location'] = {
                'lon': float(loc.get('lon')),
                'lat': float(loc.get('lat')),
                'depth': float(loc.get('depth_km')),
            }
        elif stype == 'fault':
            trace_elem = elem.find('fault:trace', _NS)
            src['trace'] = [{'lon': float(v.get('lon')),
                             'lat': float(v.get('lat'))}
                            for v in trace_elem.findall('fault:vertex', _NS)]
            geom = elem.find('fault:geometry', _NS)
            src['geometry'] = {
                'dip': float(geom.get('dip')),
                'upperDepth': float(geom.get('upperDepth_km')),
                'lowerDepth': float(geom.get('lowerDepth_km')),
            }
            rs_elem = elem.find('fault:ruptureScaling', _NS)
            src['ruptureScaling'] = {'formula': rs_elem.get('formula')}
        sources.append(src)
    return sources


def load_gmm(model_dir):
    conn = sqlite3.connect(os.path.join(model_dir, 'gmm.db'))
    c = conn.cursor()

    meta = {}
    c.execute("SELECT key, value FROM metadata")
    for k, v in c.fetchall():
        meta[k] = v

    periods = {}
    c.execute("SELECT id, imt, period_sec FROM periods")
    for pid, imt, psec in c.fetchall():
        periods[imt] = {'id': pid, 'period_sec': psec}

    gmm = {'metadata': meta, 'periods': periods, 'models': {}}
    for imt, pinfo in periods.items():
        pid = pinfo['id']
        models = []
        c.execute("SELECT id, weight, sigma FROM branches WHERE period_id=?",
                  (pid,))
        for bid, w, sig in c.fetchall():
            coeffs = {}
            c.execute(
                "SELECT name, value FROM coefficients "
                "WHERE branch_id=? AND period_id=?", (bid, pid))
            for name, val in c.fetchall():
                coeffs[name] = val
            models.append({'id': bid, 'weight': w, 'sigma': sig,
                           'coefficients': coeffs})
        gmm['models'][imt] = models
    conn.close()
    return gmm


def load_sites(model_dir):
    with open(os.path.join(model_dir, 'sites.geojson')) as f:
        gj = json.load(f)
    sites = []
    for feat in gj['features']:
        coords = feat['geometry']['coordinates']
        props = feat['properties']
        sites.append({
            'name': props['name'],
            'lon': coords[0], 'lat': coords[1],
            'vs30': props['vs30'],
            'z1p0': props.get('z1p0', 0.05),
        })
    return sites


def load_config(model_dir):
    with open(os.path.join(model_dir, 'config.toml'), 'rb') as f:
        return tomllib.load(f)


# ---------------------------------------------------------------------------
# Distance Computations
# ---------------------------------------------------------------------------

def flat_dist(lon1, lat1, lon2, lat2):
    lat_m = (lat1 + lat2) / 2.0
    dx = (lon2 - lon1) * 111.0 * math.cos(math.radians(lat_m))
    dy = (lat2 - lat1) * 111.0
    return math.sqrt(dx * dx + dy * dy)


def to_xy(lon, lat, ref_lon, ref_lat):
    dx = (lon - ref_lon) * 111.0 * math.cos(math.radians(ref_lat))
    dy = (lat - ref_lat) * 111.0
    return dx, dy


def rrup_point(src_lon, src_lat, src_depth, site_lon, site_lat):
    """Rrup for point source = hypocentral distance."""
    r_epi = flat_dist(src_lon, src_lat, site_lon, site_lat)
    return math.sqrt(r_epi ** 2 + src_depth ** 2)


def rrup_3d(s_along, s_perp, rup_start, rup_end, dip_rad, ztor, zbot):
    """Rrup from site to 3D rupture on a dipping fault plane.

    The rupture occupies [rup_start, rup_end] along strike and full
    width from ztor to zbot down-dip. The site is at (s_along, s_perp)
    in the fault-local coordinate system where s_perp > 0 is the
    hanging-wall side.
    """
    sin_d = math.sin(dip_rad)
    cos_d = math.cos(dip_rad)
    W = (zbot - ztor) / sin_d if sin_d > 1e-10 else 1e6

    # Along-strike clamping
    u_c = max(rup_start, min(rup_end, s_along))
    d_along_sq = (s_along - u_c) ** 2

    # Cross-section: closest point on fault plane line segment
    v_unc = cos_d * s_perp - sin_d * ztor
    v = max(0.0, min(W, v_unc))

    d_perp = s_perp - v * cos_d
    d_depth = ztor + v * sin_d
    return math.sqrt(d_along_sq + d_perp ** 2 + d_depth ** 2)


# ---------------------------------------------------------------------------
# GMM Evaluation
# ---------------------------------------------------------------------------

def eval_gmm(m, r_rup, site, coeffs, mref, vref, z1ref):
    """Evaluate ground motion model: returns ln(SA) in g."""
    c = coeffs
    r_eff = math.sqrt(r_rup ** 2 + c['h'] ** 2)
    z1_term = max(math.log(site['z1p0'] / z1ref), 0.0) if z1ref > 0 else 0.0
    return (c['c0']
            + c['c1'] * (m - mref)
            + c['c2'] * (m - mref) ** 2
            + c['c3'] * math.log(r_eff)
            + c['c_site'] * math.log(min(site['vs30'], vref) / vref)
            + c['c_basin'] * z1_term)


def exceed_prob(ln_iml, mu, sigma, trunc):
    """Upper-truncated exceedance probability."""
    eps = (ln_iml - mu) / sigma
    if eps >= trunc:
        return 0.0
    return (norm.cdf(trunc) - norm.cdf(eps)) / norm.cdf(trunc)


# ---------------------------------------------------------------------------
# MFD and Rupture Scaling
# ---------------------------------------------------------------------------

def gr_rates(a, b, m_min, m_max, d_mag):
    mags, rates = [], []
    m = m_min
    while m <= m_max + d_mag * 0.001:
        r = 10.0 ** (a - b * (m - d_mag / 2.0)) - \
            10.0 ** (a - b * (m + d_mag / 2.0))
        mags.append(round(m, 4))
        rates.append(max(r, 0.0))
        m = round(m + d_mag, 4)
    return mags, rates


def parse_rupture_scaling(formula):
    """Parse 'log10(L_km) = a + b * M' -> (a, b)."""
    m = re.search(r'=\s*([-\d.]+)\s*\+\s*([-\d.]+)\s*\*\s*M', formula)
    return float(m.group(1)), float(m.group(2))


# ---------------------------------------------------------------------------
# Fault Local Coordinates
# ---------------------------------------------------------------------------

def fault_local_coords(src, site):
    """Set up fault-local coordinate system and project site."""
    tr = src['trace']
    rlon = (tr[0]['lon'] + tr[1]['lon']) / 2.0
    rlat = (tr[0]['lat'] + tr[1]['lat']) / 2.0
    ax, ay = to_xy(tr[0]['lon'], tr[0]['lat'], rlon, rlat)
    bx, by = to_xy(tr[1]['lon'], tr[1]['lat'], rlon, rlat)
    sx, sy = to_xy(site['lon'], site['lat'], rlon, rlat)

    tdx, tdy = bx - ax, by - ay
    lt = math.sqrt(tdx ** 2 + tdy ** 2)
    if lt < 1e-6:
        return None

    # Strike unit vector
    skx, sky = tdx / lt, tdy / lt
    # Perpendicular: 90 deg clockwise (right-hand rule -> dip direction)
    px, py = sky, -skx

    rx, ry = sx - ax, sy - ay
    return {
        's_along': rx * skx + ry * sky,
        's_perp': rx * px + ry * py,
        'lt': lt,
    }


# ---------------------------------------------------------------------------
# PSHA Computation
# ---------------------------------------------------------------------------

def compute_hazard(sources, gmm_models, site, imls, trunc, spacing,
                   mref, vref, z1ref):
    """Compute hazard curves for a single IMT at a single site."""
    ln_imls = [math.log(x) for x in imls]
    k = len(imls)
    hz = [0.0] * k

    for src in sources:
        if src['type'] == 'point':
            rr = rrup_point(
                src['location']['lon'], src['location']['lat'],
                src['location']['depth'], site['lon'], site['lat'])
            mags, rates = gr_rates(
                src['mfd']['a'], src['mfd']['b'],
                src['mfd']['mMin'], src['mfd']['mMax'],
                src['mfd']['dMag'])
            for g in gmm_models:
                wg = g['weight']
                for m, r in zip(mags, rates):
                    if r <= 0:
                        continue
                    mu = eval_gmm(m, rr, site, g['coefficients'],
                                  mref, vref, z1ref)
                    for i in range(k):
                        hz[i] += wg * r * exceed_prob(
                            ln_imls[i], mu, g['sigma'], trunc)

        elif src['type'] == 'fault':
            lc = fault_local_coords(src, site)
            if lc is None:
                continue
            s_al = lc['s_along']
            s_pp = lc['s_perp']
            lt = lc['lt']
            dip_rad = math.radians(src['geometry']['dip'])
            ztor = src['geometry']['upperDepth']
            zbot = src['geometry']['lowerDepth']
            rs_a, rs_b = parse_rupture_scaling(
                src['ruptureScaling']['formula'])

            mfd = src['mfd']
            mbranches = mfd.get('mMaxEpistemic', {}).get(
                'branches', [{'mMax': mfd['mMax'], 'weight': 1.0}])

            for br in mbranches:
                wm = br['weight']
                mags, rates = gr_rates(
                    mfd['a'], mfd['b'], mfd['mMin'],
                    br['mMax'], mfd['dMag'])

                for g in gmm_models:
                    wg = g['weight']
                    for m, r in zip(mags, rates):
                        if r <= 0:
                            continue
                        lr = 10.0 ** (rs_a + rs_b * m)

                        if lr >= lt:
                            rr = max(rrup_3d(
                                s_al, s_pp, 0, lt,
                                dip_rad, ztor, zbot), 0.1)
                            mu = eval_gmm(m, rr, site,
                                          g['coefficients'],
                                          mref, vref, z1ref)
                            for i in range(k):
                                hz[i] += wm * wg * r * exceed_prob(
                                    ln_imls[i], mu, g['sigma'], trunc)
                        else:
                            np_ = max(1, int(math.ceil(
                                (lt - lr) / spacing)) + 1)
                            rpp = r / np_
                            for j in range(np_):
                                off = (j * (lt - lr) / (np_ - 1)
                                       if np_ > 1 else 0.0)
                                rr = max(rrup_3d(
                                    s_al, s_pp, off, off + lr,
                                    dip_rad, ztor, zbot), 0.1)
                                mu = eval_gmm(m, rr, site,
                                              g['coefficients'],
                                              mref, vref, z1ref)
                                for i in range(k):
                                    hz[i] += wm * wg * rpp * exceed_prob(
                                        ln_imls[i], mu, g['sigma'],
                                        trunc)
    return hz


def interp_log_log(imls, rates, target_rate):
    """Log-log interpolation of hazard curve to find IML at target rate."""
    for i in range(len(rates) - 1):
        if rates[i] <= 0 or rates[i + 1] <= 0:
            continue
        if rates[i] >= target_rate >= rates[i + 1]:
            f = ((math.log(target_rate) - math.log(rates[i]))
                 / (math.log(rates[i + 1]) - math.log(rates[i])))
            return math.exp(math.log(imls[i])
                            + f * (math.log(imls[i + 1])
                                   - math.log(imls[i])))
    return imls[0] if target_rate >= rates[0] else imls[-1]


# ---------------------------------------------------------------------------
# Deaggregation
# ---------------------------------------------------------------------------

def compute_deagg(sources, gmm_models, site, target_iml, trunc, spacing,
                  dcfg, mref, vref, z1ref):
    """Magnitude-distance deaggregation for a single IMT."""
    ln_iml = math.log(target_iml)
    dm = dcfg['delta_m']
    dr = dcfg['delta_r']
    m0, m1 = dcfg['m_min'], dcfg['m_max']
    r0, r1 = dcfg['r_min'], dcfg['r_max']
    nm = int(round((m1 - m0) / dm))
    nr = int(round((r1 - r0) / dr))
    bins = [[0.0] * nr for _ in range(nm)]

    def add_bin(m, rrup, contrib):
        if contrib <= 0:
            return
        mi = int((m - m0) / dm)
        ri = int((rrup - r0) / dr)
        if 0 <= mi < nm and 0 <= ri < nr:
            bins[mi][ri] += contrib

    for src in sources:
        if src['type'] == 'point':
            rr = rrup_point(
                src['location']['lon'], src['location']['lat'],
                src['location']['depth'], site['lon'], site['lat'])
            mags, rates = gr_rates(
                src['mfd']['a'], src['mfd']['b'],
                src['mfd']['mMin'], src['mfd']['mMax'],
                src['mfd']['dMag'])
            for g in gmm_models:
                for m, r in zip(mags, rates):
                    if r <= 0:
                        continue
                    mu = eval_gmm(m, rr, site, g['coefficients'],
                                  mref, vref, z1ref)
                    p = exceed_prob(ln_iml, mu, g['sigma'], trunc)
                    add_bin(m, rr, g['weight'] * r * p)

        elif src['type'] == 'fault':
            lc = fault_local_coords(src, site)
            if lc is None:
                continue
            s_al = lc['s_along']
            s_pp = lc['s_perp']
            lt = lc['lt']
            dip_rad = math.radians(src['geometry']['dip'])
            ztor = src['geometry']['upperDepth']
            zbot = src['geometry']['lowerDepth']
            rs_a, rs_b = parse_rupture_scaling(
                src['ruptureScaling']['formula'])

            mfd = src['mfd']
            mbranches = mfd.get('mMaxEpistemic', {}).get(
                'branches', [{'mMax': mfd['mMax'], 'weight': 1.0}])

            for br in mbranches:
                wm = br['weight']
                mags, rates = gr_rates(
                    mfd['a'], mfd['b'], mfd['mMin'],
                    br['mMax'], mfd['dMag'])
                for g in gmm_models:
                    wg = g['weight']
                    for m, r in zip(mags, rates):
                        if r <= 0:
                            continue
                        lr = 10.0 ** (rs_a + rs_b * m)
                        if lr >= lt:
                            rr = max(rrup_3d(
                                s_al, s_pp, 0, lt,
                                dip_rad, ztor, zbot), 0.1)
                            mu = eval_gmm(m, rr, site,
                                          g['coefficients'],
                                          mref, vref, z1ref)
                            p = exceed_prob(ln_iml, mu, g['sigma'], trunc)
                            add_bin(m, rr, wm * wg * r * p)
                        else:
                            np_ = max(1, int(math.ceil(
                                (lt - lr) / spacing)) + 1)
                            rpp = r / np_
                            for j in range(np_):
                                off = (j * (lt - lr) / (np_ - 1)
                                       if np_ > 1 else 0.0)
                                rr = max(rrup_3d(
                                    s_al, s_pp, off, off + lr,
                                    dip_rad, ztor, zbot), 0.1)
                                mu = eval_gmm(m, rr, site,
                                              g['coefficients'],
                                              mref, vref, z1ref)
                                p = exceed_prob(ln_iml, mu, g['sigma'],
                                                trunc)
                                add_bin(m, rr, wm * wg * rpp * p)

    total = sum(sum(row) for row in bins)
    if total <= 0:
        return None
    mm, mr = 0.0, 0.0
    mc, mode_mi, mode_ri = 0.0, 0, 0
    for mi in range(nm):
        cm = m0 + (mi + 0.5) * dm
        for ri in range(nr):
            cr = r0 + (ri + 0.5) * dr
            cv = bins[mi][ri]
            mm += cm * cv
            mr += cr * cv
            if cv > mc:
                mc, mode_mi, mode_ri = cv, mi, ri
    return {
        'mean_M': round(mm / total, 4),
        'mean_R': round(mr / total, 4),
        'mode_M': round(m0 + (mode_mi + 0.5) * dm, 4),
        'mode_R': round(r0 + (mode_ri + 0.5) * dr, 4),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    model_dir = '/app/model'
    sources = load_sources(model_dir)
    gmm = load_gmm(model_dir)
    sites = load_sites(model_dir)
    cfg = load_config(model_dir)

    meta = gmm['metadata']
    mref = float(meta['Mref'])
    vref = float(meta['Vref'])
    z1ref = float(meta['z1p0_ref'])

    trunc = cfg['hazard']['truncation_level']
    spacing = cfg['fault_discretization']['surface_spacing_km']
    return_periods = cfg['output']['return_periods']
    out_dir = cfg['output']['directory']
    dcfg = cfg['deaggregation']

    os.makedirs(out_dir, exist_ok=True)

    imts = list(cfg['hazard']['imls'].keys())
    all_hazard = {}

    for imt in imts:
        imls = cfg['hazard']['imls'][imt]
        gm_models = gmm['models'][imt]
        all_hazard[imt] = {}

        for site in sites:
            hz = compute_hazard(sources, gm_models, site, imls, trunc,
                                spacing, mref, vref, z1ref)
            all_hazard[imt][site['name']] = hz

        with open(os.path.join(out_dir, f'hazard_{imt}.csv'), 'w',
                  newline='') as f:
            w = csv.writer(f)
            w.writerow(['site'] + [str(x) for x in imls])
            for site in sites:
                row = [site['name']] + \
                      [f'{v:.6e}' for v in all_hazard[imt][site['name']]]
                w.writerow(row)

    # Uniform Hazard Spectrum
    with open(os.path.join(out_dir, 'uhs.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['site', 'return_period'] + imts)
        for site in sites:
            for rp in return_periods:
                row = [site['name'], rp]
                for imt in imts:
                    imls = cfg['hazard']['imls'][imt]
                    hz = all_hazard[imt][site['name']]
                    sa = interp_log_log(imls, hz, 1.0 / rp)
                    row.append(f'{sa:.6f}')
                w.writerow(row)

    # Deaggregation
    deagg_imt = dcfg['imt']
    deagg_site_name = dcfg['site']
    deagg_rp = dcfg['return_period']
    deagg_imls = cfg['hazard']['imls'][deagg_imt]
    deagg_hz = all_hazard[deagg_imt][deagg_site_name]
    target_iml = interp_log_log(deagg_imls, deagg_hz, 1.0 / deagg_rp)
    site_obj = next(s for s in sites if s['name'] == deagg_site_name)
    deagg_models = gmm['models'][deagg_imt]
    deagg = compute_deagg(sources, deagg_models, site_obj, target_iml,
                          trunc, spacing, dcfg, mref, vref, z1ref)

    with open(os.path.join(out_dir, 'deaggregation.csv'), 'w',
              newline='') as f:
        w = csv.writer(f)
        w.writerow(['metric', 'value'])
        if deagg:
            w.writerow(['mean_M', f'{deagg["mean_M"]:.4f}'])
            w.writerow(['mean_R', f'{deagg["mean_R"]:.4f}'])
            w.writerow(['mode_M', f'{deagg["mode_M"]:.4f}'])
            w.writerow(['mode_R', f'{deagg["mode_R"]:.4f}'])

    print("Multi-period PSHA calculation complete.")
    print(f"Output: {out_dir}/")


if __name__ == '__main__':
    main()
