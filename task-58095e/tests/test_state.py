"""
Multi-IMT PSHA Pipeline Verification Tests with Mixed Distance Metrics,
Rupture Floating, and Epistemic MFD Branching.

Runs the agent's pipeline and verifies output against a compact
reference implementation.

"""

import csv
import json
import math
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest


# ──────────────────────────────────────────────────────────────────────
# Math helpers
# ──────────────────────────────────────────────────────────────────────

def _phi(x):
    return 0.5 * (1.0 + math.erf(x / 1.4142135623730951))


def _haversine(lo1, la1, lo2, la2):
    r1, r2 = math.radians(la1), math.radians(la2)
    a = (math.sin(math.radians(la2 - la1) / 2) ** 2 +
         math.cos(r1) * math.cos(r2) *
         math.sin(math.radians(lo2 - lo1) / 2) ** 2)
    return 6371.0 * 2.0 * math.asin(min(1.0, math.sqrt(a)))


def _to_km(lon, lat, rlon, rlat):
    c = math.cos(math.radians(rlat))
    return (lon - rlon) * 111.195 * c, (lat - rlat) * 111.195


def _psd(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    ls = dx * dx + dy * dy
    if ls < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ls))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _pip(px, py, poly):
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


# ──────────────────────────────────────────────────────────────────────
# UTM Zone 10N -> WGS84 conversion (inverse Transverse Mercator)
# ──────────────────────────────────────────────────────────────────────

def _utm10n_to_wgs84(easting, northing):
    a = 6378137.0
    f = 1.0 / 298.257223563
    e2 = 2.0 * f - f * f
    e_p2 = e2 / (1.0 - e2)
    k0 = 0.9996
    lon0 = math.radians(-123.0)

    x = easting - 500000.0
    y = northing

    M = y / k0
    mu = M / (a * (1.0 - e2 / 4.0 - 3.0 * e2 ** 2 / 64.0
                    - 5.0 * e2 ** 3 / 256.0))
    e1 = (1.0 - math.sqrt(1.0 - e2)) / (1.0 + math.sqrt(1.0 - e2))
    phi1 = (mu
            + (3.0 * e1 / 2.0 - 27.0 * e1 ** 3 / 32.0) * math.sin(2.0 * mu)
            + (21.0 * e1 ** 2 / 16.0 - 55.0 * e1 ** 4 / 32.0)
            * math.sin(4.0 * mu)
            + (151.0 * e1 ** 3 / 96.0) * math.sin(6.0 * mu)
            + (1097.0 * e1 ** 4 / 512.0) * math.sin(8.0 * mu))
    sp = math.sin(phi1)
    cp = math.cos(phi1)
    tp = math.tan(phi1)
    N1 = a / math.sqrt(1.0 - e2 * sp * sp)
    T1 = tp * tp
    C1 = e_p2 * cp * cp
    R1 = a * (1.0 - e2) / (1.0 - e2 * sp * sp) ** 1.5
    D = x / (N1 * k0)
    lat = phi1 - (N1 * tp / R1) * (
        D ** 2 / 2.0
        - (5.0 + 3.0 * T1 + 10.0 * C1 - 4.0 * C1 ** 2
           - 9.0 * e_p2) * D ** 4 / 24.0
        + (61.0 + 90.0 * T1 + 298.0 * C1 + 45.0 * T1 ** 2
           - 252.0 * e_p2 - 3.0 * C1 ** 2) * D ** 6 / 720.0)
    lon = lon0 + (
        D - (1.0 + 2.0 * T1 + C1) * D ** 3 / 6.0
        + (5.0 - 2.0 * C1 + 28.0 * T1 - 3.0 * C1 ** 2
           + 8.0 * e_p2 + 24.0 * T1 ** 2) * D ** 5 / 120.0) / cp
    return math.degrees(lon), math.degrees(lat)


# ──────────────────────────────────────────────────────────────────────
# Trace geometry and rupture floating
# ──────────────────────────────────────────────────────────────────────

def _trace_length_km(trace, slon, slat):
    """Compute fault trace length in local km coordinates."""
    tkm = [_to_km(lo, la, slon, slat) for lo, la in trace]
    total = 0.0
    for i in range(len(tkm) - 1):
        total += math.hypot(tkm[i + 1][0] - tkm[i][0],
                            tkm[i + 1][1] - tkm[i][1])
    return total


def _sub_trace(trace, start_km, end_km, slon, slat):
    """Extract sub-trace at [start_km, end_km] along trace in geographic coords."""
    tkm = [_to_km(lo, la, slon, slat) for lo, la in trace]
    cum = [0.0]
    for i in range(len(tkm) - 1):
        cum.append(cum[-1] + math.hypot(tkm[i + 1][0] - tkm[i][0],
                                         tkm[i + 1][1] - tkm[i][1]))

    def _interp(d):
        for i in range(len(cum) - 1):
            if cum[i] <= d <= cum[i + 1] + 1e-9:
                seg = cum[i + 1] - cum[i]
                t = (d - cum[i]) / seg if seg > 1e-12 else 0.0
                return (trace[i][0] + t * (trace[i + 1][0] - trace[i][0]),
                        trace[i][1] + t * (trace[i + 1][1] - trace[i][1]))
        return trace[-1]

    result = [_interp(start_km)]
    for i in range(1, len(trace) - 1):
        if start_km < cum[i] < end_km:
            result.append(trace[i])
    result.append(_interp(end_km))
    return result


def _wc94_length(mag):
    """Wells & Coppersmith 1994 subsurface rupture length (km), all types."""
    return 10.0 ** (-3.22 + 0.69 * mag)


# ──────────────────────────────────────────────────────────────────────
# Distance computations
# ──────────────────────────────────────────────────────────────────────

def _rjb_fault(trace, dip, ud, ld, slon, slat):
    tkm = [_to_km(lo, la, slon, slat) for lo, la in trace]
    dr = math.radians(dip)
    if abs(dip - 90.0) < 0.01:
        mn = float('inf')
        for i in range(len(tkm) - 1):
            mn = min(mn, _psd(0, 0, tkm[i][0], tkm[i][1],
                              tkm[i + 1][0], tkm[i + 1][1]))
        return mn
    sx = tkm[-1][0] - tkm[0][0]
    sy = tkm[-1][1] - tkm[0][1]
    sl = math.hypot(sx, sy)
    if sl < 1e-12:
        return float('inf')
    sux, suy = sx / sl, sy / sl
    pux, puy = suy, -sux
    uh = ud / math.tan(dr) if ud > 0 else 0.0
    lh = ld / math.tan(dr)
    ue = [(x + pux * uh, y + puy * uh) for x, y in tkm]
    le = [(x + pux * lh, y + puy * lh) for x, y in reversed(tkm)]
    poly = ue + le
    if _pip(0, 0, poly):
        return 0.0
    mn = float('inf')
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        mn = min(mn, _psd(0, 0, poly[i][0], poly[i][1],
                          poly[j][0], poly[j][1]))
    return mn


# ──────────────────────────────────────────────────────────────────────
# MFD discretization
# ──────────────────────────────────────────────────────────────────────

def _gr(a, b, mmin, mmax, dm):
    mags, rates = [], []
    m = mmin
    while m <= mmax + dm * 0.01:
        r = 10 ** (a - b * (m - dm / 2)) - 10 ** (a - b * (m + dm / 2))
        if r > 0:
            mags.append(round(m, 2))
            rates.append(r)
        m = round(m + dm, 2)
    return mags, rates


# ──────────────────────────────────────────────────────────────────────
# GMM evaluation
# ──────────────────────────────────────────────────────────────────────

def _gmm_eval(M, dist, vs, ztor, g, imt):
    """Evaluate a GMM. dist is the appropriate distance for this model."""
    c = g['coefficients'][imt]
    re = math.sqrt(dist ** 2 + c['h'] ** 2)
    mu = (c['c0'] + c['c1'] * (M - 6) + c['c2'] * (M - 6) ** 2 +
          c['c3'] * math.log(re) + c['c_site'] * math.log(vs / c['v_ref']))
    if 'c_ztor' in c:
        mu += c['c_ztor'] * math.log(ztor + 1)
    sig_model = g.get('sigmaModel', 'TOTAL')
    if sig_model == 'PARTITIONED':
        sig = math.sqrt(c['tau'] ** 2 + c['phi'] ** 2)
    else:
        sig = c['sigma']
    return mu, sig


def _pex(iml, mu, sig, tr):
    e = (math.log(iml) - mu) / sig
    if e >= tr:
        return 0.0
    return (_phi(tr) - _phi(e)) / _phi(tr)


# ──────────────────────────────────────────────────────────────────────
# Bin edges and interpolation
# ──────────────────────────────────────────────────────────────────────

def _edges(mn, mx, d):
    out = []
    v = mn
    while v <= mx + d * 0.01:
        out.append(round(v, 4))
        v = round(v + d, 4)
    return out


def _interp_iml(imls, haz, target_rate):
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


# ──────────────────────────────────────────────────────────────────────
# Model loading
# ──────────────────────────────────────────────────────────────────────

def _load_model():
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
            'ud': float(geom.get('upperDepth')),
            'ld': float(geom.get('lowerDepth')),
            'mfd_branches': mfd_branches,
        })

    # Parse UTM fault trace
    with open('/app/model/active-crust/fault/utm-traces.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            e1 = float(row['easting_1'])
            n1 = float(row['northing_1'])
            e2 = float(row['easting_2'])
            n2 = float(row['northing_2'])
            lon1, lat1 = _utm10n_to_wgs84(e1, n1)
            lon2, lat2 = _utm10n_to_wgs84(e2, n2)
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
                'ud': float(row['upper_depth_km']),
                'ld': float(row['lower_depth_km']),
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


# ──────────────────────────────────────────────────────────────────────
# Reference computation
# ──────────────────────────────────────────────────────────────────────

def compute_reference():
    cc, gc, faults, points = _load_model()

    slon = cc['site']['longitude']
    slat = cc['site']['latitude']
    vs = cc['site']['vs30']
    trunc = cc['hazard']['truncationLevel']
    maxd = cc['performance']['maxDistance']
    imts = cc['hazard']['imts']
    iml_map = cc['hazard']['customImls']
    gmms = gc['models']
    imt_periods = gc['imt_periods']

    floating = cc.get('model', {}).get('ruptureFloating', 'OFF')
    spacing = cc.get('model', {}).get('surfaceSpacing', 1.0)

    # Build entries: (mag, rate, rjb, rrup, ztor)
    entries = []

    for f in faults:
        ztor = f['ud']

        for mfd, mfd_w in f['mfd_branches']:
            if mfd['mfd_type'] == 'GR':
                ms, rs = _gr(mfd['a_value'], mfd['b_value'],
                             mfd['m_min'], mfd['m_max'], mfd['delta_m'])
            elif mfd['mfd_type'] == 'SINGLE':
                ms, rs = [mfd['magnitude']], [mfd['rate']]
            else:
                continue

            for m, r in zip(ms, rs):
                wr = r * mfd_w

                if floating == 'ALONG_STRIKE':
                    rup_len = _wc94_length(m)
                    fault_len = _trace_length_km(f['trace'], slon, slat)

                    if rup_len >= fault_len:
                        rjb = _rjb_fault(f['trace'], f['dip'],
                                         f['ud'], f['ld'], slon, slat)
                        if rjb <= maxd:
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
                            st = _sub_trace(f['trace'], start, end,
                                            slon, slat)
                            rjb = _rjb_fault(st, f['dip'],
                                             f['ud'], f['ld'], slon, slat)
                            if rjb <= maxd:
                                rrup = math.sqrt(rjb ** 2 + ztor ** 2)
                                entries.append((m, sub_rate, rjb, rrup, ztor))
                else:
                    rjb = _rjb_fault(f['trace'], f['dip'],
                                     f['ud'], f['ld'], slon, slat)
                    if rjb <= maxd:
                        rrup = math.sqrt(rjb ** 2 + ztor ** 2)
                        entries.append((m, wr, rjb, rrup, ztor))

    for p in points:
        rjb = _haversine(p['lon'], p['lat'], slon, slat)
        if rjb > maxd:
            continue
        depth = p.get('depth', 0.0)
        rrup = math.sqrt(rjb ** 2 + depth ** 2)
        ztor = depth

        mfd = p['mfd']
        if mfd['mfd_type'] == 'GR':
            ms, rs = _gr(mfd['a_value'], mfd['b_value'],
                         mfd['m_min'], mfd['m_max'], mfd['delta_m'])
        elif mfd['mfd_type'] == 'SINGLE':
            ms, rs = [mfd['magnitude']], [mfd['rate']]
        else:
            continue
        for mv, rv in zip(ms, rs):
            entries.append((mv, rv, rjb, rrup, ztor))

    # Compute hazard curves for each IMT
    ref_curves = {}
    for imt in imts:
        imls = iml_map[imt]
        ni = len(imls)
        haz = [0.0] * ni
        for mag, rate, rjb, rrup, ztor in entries:
            for g in gmms:
                dist_type = g.get('distanceType', 'R_JB')
                dist = rrup if dist_type == 'R_RUP' else rjb
                mu, sig = _gmm_eval(mag, dist, vs, ztor, g, imt)
                w = g['weight']
                for k, iml_val in enumerate(imls):
                    haz[k] += rate * _pex(iml_val, mu, sig, trunc) * w
        ref_curves[imt] = (imls, haz)

    # UHS
    rp = cc['disagg']['returnPeriod']
    target_rate = 1.0 / rp
    uhs = []
    for imt in imts:
        period = imt_periods[imt]
        imls, haz = ref_curves[imt]
        sa = _interp_iml(imls, haz, target_rate)
        uhs.append({'period': period, 'sa': sa})
    uhs.sort(key=lambda x: x['period'])

    # PGA deaggregation
    pga_imls, pga_haz = ref_curves['PGA']
    target_iml = _interp_iml(pga_imls, pga_haz, target_rate)

    db = cc['disagg']['bins']
    me = _edges(db['mMin'], db['mMax'], db['\u0394m'])
    re = _edges(db['rMin'], db['rMax'], db['\u0394r'])
    ee = _edges(db['\u03b5Min'], db['\u03b5Max'], db['\u0394\u03b5'])
    nm, nr, ne = len(me) - 1, len(re) - 1, len(ee) - 1
    cb = [[[0.0] * ne for _ in range(nr)] for _ in range(nm)]
    lnt = math.log(target_iml)

    for mag, rate, rjb, rrup, ztor in entries:
        mi = -1
        for i in range(nm):
            if me[i] <= mag + 1e-9 and mag - 1e-9 < me[i + 1]:
                mi = i
                break
        if mi < 0:
            continue
        ri = -1
        for i in range(nr):
            if re[i] <= rjb + 1e-9 and rjb - 1e-9 < re[i + 1]:
                ri = i
                break
        if ri < 0:
            continue
        for g in gmms:
            dist_type = g.get('distanceType', 'R_JB')
            dist = rrup if dist_type == 'R_RUP' else rjb
            mu, sig = _gmm_eval(mag, dist, vs, ztor, g, 'PGA')
            w = g['weight']
            e0 = (lnt - mu) / sig
            for ei in range(ne):
                elo = max(ee[ei], e0)
                ehi = min(ee[ei + 1], trunc)
                if elo >= ehi:
                    continue
                pb = (_phi(ehi) - _phi(elo)) / _phi(trunc)
                cb[mi][ri][ei] += rate * pb * w

    tot = sum(cb[mi][ri][ei]
              for mi in range(nm) for ri in range(nr) for ei in range(ne))
    if tot < 1e-30:
        tot = 1.0

    mm = md = mep = 0.0
    mv = 0.0
    mmi = mri = mei = 0
    for mi in range(nm):
        mc = (me[mi] + me[mi + 1]) / 2
        for ri in range(nr):
            rc = (re[ri] + re[ri + 1]) / 2
            for ei in range(ne):
                ec = (ee[ei] + ee[ei + 1]) / 2
                fr = cb[mi][ri][ei] / tot
                mm += mc * fr
                md += rc * fr
                mep += ec * fr
                if cb[mi][ri][ei] > mv:
                    mv = cb[mi][ri][ei]
                    mmi, mri, mei = mi, ri, ei

    deagg = {
        'target_iml': target_iml,
        'return_period': rp,
        'mean_mag': mm,
        'mean_dist': md,
        'mean_eps': mep,
        'mode_mag': (me[mmi] + me[mmi + 1]) / 2,
        'mode_dist': (re[mri] + re[mri + 1]) / 2,
        'mode_eps': (ee[mei] + ee[mei + 1]) / 2,
    }

    return ref_curves, uhs, deagg


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture(scope='session', autouse=True)
def run_pipeline():
    if os.path.exists('/app/output'):
        shutil.rmtree('/app/output')
    result = subprocess.run(
        ['python3', '/app/psha_pipeline.py'],
        capture_output=True, text=True, timeout=120, cwd='/app')
    assert result.returncode == 0, \
        f"psha_pipeline.py failed (exit {result.returncode}):\n{result.stderr}"


@pytest.fixture(scope='session')
def agent_curves():
    path = '/app/output/hazard_curves.csv'
    assert os.path.exists(path), "hazard_curves.csv not found"
    data = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            imt = row['imt']
            if imt not in data:
                data[imt] = []
            data[imt].append({
                'iml': float(row['iml']),
                'annual_rate': float(row['annual_rate']),
                'poisson_prob_50yr': float(row['poisson_prob_50yr']),
            })
    return data


@pytest.fixture(scope='session')
def agent_uhs():
    path = '/app/output/uhs.json'
    assert os.path.exists(path), "uhs.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope='session')
def agent_deagg():
    path = '/app/output/deagg_pga.json'
    assert os.path.exists(path), "deagg_pga.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope='session')
def reference():
    return compute_reference()


# ──────────────────────────────────────────────────────────────────────
# Tests: Output File Structure
# ──────────────────────────────────────────────────────────────────────

class TestOutputFiles:
    def test_hazard_csv_exists(self):
        assert os.path.isfile('/app/output/hazard_curves.csv')

    def test_uhs_json_exists(self):
        assert os.path.isfile('/app/output/uhs.json')

    def test_deagg_json_exists(self):
        assert os.path.isfile('/app/output/deagg_pga.json')

    def test_hazard_csv_columns(self, agent_curves):
        assert len(agent_curves) > 0
        for imt, rows in agent_curves.items():
            assert len(rows) > 0
            assert 'iml' in rows[0]
            assert 'annual_rate' in rows[0]
            assert 'poisson_prob_50yr' in rows[0]

    def test_hazard_csv_imts_present(self, agent_curves):
        expected = {'PGA', 'SA0P2', 'SA1P0'}
        assert set(agent_curves.keys()) == expected, \
            f"Expected IMTs {expected}, got {set(agent_curves.keys())}"

    def test_hazard_csv_row_counts(self, agent_curves):
        with open('/app/model/calc-config.json') as f:
            cc = json.load(f)
        for imt, rows in agent_curves.items():
            expected_n = len(cc['hazard']['customImls'][imt])
            assert len(rows) == expected_n, \
                f"{imt}: expected {expected_n} rows, got {len(rows)}"

    def test_uhs_structure(self, agent_uhs):
        assert 'return_period' in agent_uhs
        assert 'spectral_ordinates' in agent_uhs
        assert isinstance(agent_uhs['spectral_ordinates'], list)
        assert len(agent_uhs['spectral_ordinates']) == 3

    def test_uhs_periods(self, agent_uhs):
        periods = sorted(o['period'] for o in agent_uhs['spectral_ordinates'])
        assert periods == [0.0, 0.2, 1.0], \
            f"Expected periods [0.0, 0.2, 1.0], got {periods}"

    def test_deagg_keys(self, agent_deagg):
        required = ['target_iml', 'return_period', 'mean_mag', 'mean_dist',
                     'mean_eps', 'mode_mag', 'mode_dist', 'mode_eps']
        for key in required:
            assert key in agent_deagg, f"Missing key: {key}"


# ──────────────────────────────────────────────────────────────────────
# Tests: Hazard Curves (per IMT)
# ──────────────────────────────────────────────────────────────────────

class TestHazardCurves:
    @pytest.mark.parametrize("imt", ["PGA", "SA0P2", "SA1P0"])
    def test_monotonically_decreasing(self, agent_curves, imt):
        rows = agent_curves[imt]
        rates = [r['annual_rate'] for r in rows]
        for i in range(len(rates) - 1):
            assert rates[i] >= rates[i + 1] - 1e-15, \
                f"{imt} not monotonic at index {i}: {rates[i]} < {rates[i+1]}"

    @pytest.mark.parametrize("imt", ["PGA", "SA0P2", "SA1P0"])
    def test_positive_rates(self, agent_curves, imt):
        for row in agent_curves[imt]:
            assert row['annual_rate'] >= 0

    @pytest.mark.parametrize("imt", ["PGA", "SA0P2", "SA1P0"])
    def test_poisson_conversion(self, agent_curves, imt):
        for row in agent_curves[imt]:
            expected_p = 1.0 - math.exp(-row['annual_rate'] * 50.0)
            rel_err = abs(row['poisson_prob_50yr'] - expected_p) / \
                max(expected_p, 1e-15)
            assert rel_err < 0.001, \
                f"{imt} Poisson mismatch at IML={row['iml']}: " \
                f"got {row['poisson_prob_50yr']}, expected {expected_p}"

    @pytest.mark.parametrize("imt", ["PGA", "SA0P2", "SA1P0"])
    def test_values_match_reference(self, agent_curves, reference, imt):
        ref_curves, _, _ = reference
        ref_imls, ref_haz = ref_curves[imt]
        agent_rates = {round(r['iml'], 6): r['annual_rate']
                       for r in agent_curves[imt]}
        mismatches = []
        for k, iml in enumerate(ref_imls):
            iml_key = round(iml, 6)
            if iml_key not in agent_rates:
                mismatches.append(f"IML {iml} missing from {imt} output")
                continue
            agent_val = agent_rates[iml_key]
            ref_val = ref_haz[k]
            if ref_val < 1e-12:
                if agent_val > 1e-6:
                    mismatches.append(
                        f"{imt} IML={iml}: agent={agent_val:.4e}, "
                        f"ref={ref_val:.4e}")
                continue
            rel_err = abs(agent_val - ref_val) / ref_val
            if rel_err > 0.05:
                mismatches.append(
                    f"{imt} IML={iml}: agent={agent_val:.4e}, "
                    f"ref={ref_val:.4e}, err={rel_err:.1%}")
        assert not mismatches, \
            "Hazard curve mismatches:\n" + "\n".join(mismatches)

    @pytest.mark.parametrize("imt", ["PGA", "SA0P2", "SA1P0"])
    def test_highest_rate_at_lowest_iml(self, agent_curves, imt):
        rates = [r['annual_rate'] for r in agent_curves[imt]]
        assert rates[0] == max(rates)


# ──────────────────────────────────────────────────────────────────────
# Tests: Uniform Hazard Spectrum
# ──────────────────────────────────────────────────────────────────────

class TestUHS:
    def test_sa_positive(self, agent_uhs):
        for o in agent_uhs['spectral_ordinates']:
            assert o['sa'] > 0, \
                f"SA at period {o['period']} is non-positive: {o['sa']}"

    def test_return_period(self, agent_uhs):
        assert agent_uhs['return_period'] == 2475

    def test_uhs_values_match_reference(self, agent_uhs, reference):
        _, ref_uhs, _ = reference
        ref_by_period = {round(o['period'], 2): o['sa'] for o in ref_uhs}
        agent_by_period = {round(o['period'], 2): o['sa']
                           for o in agent_uhs['spectral_ordinates']}
        mismatches = []
        for p, ref_sa in ref_by_period.items():
            if p not in agent_by_period:
                mismatches.append(f"Period {p} missing from UHS")
                continue
            agent_sa = agent_by_period[p]
            if ref_sa > 0:
                rel_err = abs(agent_sa - ref_sa) / ref_sa
                if rel_err > 0.10:
                    mismatches.append(
                        f"Period {p}: agent={agent_sa:.4f}, "
                        f"ref={ref_sa:.4f}, err={rel_err:.1%}")
        assert not mismatches, \
            "UHS mismatches:\n" + "\n".join(mismatches)

    def test_short_period_amplification(self, agent_uhs):
        by_p = {round(o['period'], 2): o['sa']
                for o in agent_uhs['spectral_ordinates']}
        if 0.0 in by_p and 0.2 in by_p:
            assert by_p[0.2] >= by_p[0.0] * 0.5, \
                f"SA(0.2s)={by_p[0.2]} implausibly low vs PGA={by_p[0.0]}"

    def test_long_period_decay(self, agent_uhs):
        by_p = {round(o['period'], 2): o['sa']
                for o in agent_uhs['spectral_ordinates']}
        if 0.2 in by_p and 1.0 in by_p:
            assert by_p[1.0] < by_p[0.2] * 3.0, \
                f"SA(1.0s)={by_p[1.0]} implausibly high vs " \
                f"SA(0.2s)={by_p[0.2]}"


# ──────────────────────────────────────────────────────────────────────
# Tests: Deaggregation
# ──────────────────────────────────────────────────────────────────────

class TestDeaggregation:
    def test_mean_mag_range(self, agent_deagg):
        assert 4.5 <= agent_deagg['mean_mag'] <= 8.5, \
            f"mean_mag={agent_deagg['mean_mag']} out of range"

    def test_mean_dist_positive(self, agent_deagg):
        assert agent_deagg['mean_dist'] >= 0.0

    def test_mean_eps_range(self, agent_deagg):
        assert -3.0 <= agent_deagg['mean_eps'] <= 3.0, \
            f"mean_eps={agent_deagg['mean_eps']} out of range"

    def test_mode_mag_range(self, agent_deagg):
        assert 4.5 <= agent_deagg['mode_mag'] <= 8.5

    def test_mode_dist_range(self, agent_deagg):
        assert 0.0 <= agent_deagg['mode_dist'] <= 200.0

    def test_mode_eps_range(self, agent_deagg):
        assert -3.0 <= agent_deagg['mode_eps'] <= 3.0

    def test_target_iml_positive(self, agent_deagg):
        assert agent_deagg['target_iml'] > 0

    def test_deagg_mean_mag_matches_ref(self, agent_deagg, reference):
        _, _, ref_d = reference
        diff = abs(agent_deagg['mean_mag'] - ref_d['mean_mag'])
        assert diff < 0.3, \
            f"mean_mag: agent={agent_deagg['mean_mag']:.3f}, " \
            f"ref={ref_d['mean_mag']:.3f}, diff={diff:.3f}"

    def test_deagg_mean_dist_matches_ref(self, agent_deagg, reference):
        _, _, ref_d = reference
        ref_val = ref_d['mean_dist']
        agent_val = agent_deagg['mean_dist']
        if ref_val > 1.0:
            rel_err = abs(agent_val - ref_val) / ref_val
            assert rel_err < 0.25, \
                f"mean_dist: agent={agent_val:.2f}, ref={ref_val:.2f}, " \
                f"err={rel_err:.1%}"
        else:
            assert abs(agent_val - ref_val) < 5.0

    def test_deagg_mean_eps_matches_ref(self, agent_deagg, reference):
        _, _, ref_d = reference
        diff = abs(agent_deagg['mean_eps'] - ref_d['mean_eps'])
        assert diff < 0.5, \
            f"mean_eps: agent={agent_deagg['mean_eps']:.3f}, " \
            f"ref={ref_d['mean_eps']:.3f}, diff={diff:.3f}"

    def test_deagg_target_iml_matches_ref(self, agent_deagg, reference):
        _, _, ref_d = reference
        ref_iml = ref_d['target_iml']
        agent_iml = agent_deagg['target_iml']
        if ref_iml > 0:
            rel_err = abs(agent_iml - ref_iml) / ref_iml
            assert rel_err < 0.10, \
                f"target IML: agent={agent_iml:.4f}, ref={ref_iml:.4f}, " \
                f"err={rel_err:.1%}"

    def test_deagg_mode_mag_matches_ref(self, agent_deagg, reference):
        _, _, ref_d = reference
        diff = abs(agent_deagg['mode_mag'] - ref_d['mode_mag'])
        assert diff < 0.5, \
            f"mode_mag: agent={agent_deagg['mode_mag']:.2f}, " \
            f"ref={ref_d['mode_mag']:.2f}"

    def test_deagg_mode_dist_matches_ref(self, agent_deagg, reference):
        _, _, ref_d = reference
        diff = abs(agent_deagg['mode_dist'] - ref_d['mode_dist'])
        assert diff < 15.0, \
            f"mode_dist: agent={agent_deagg['mode_dist']:.2f}, " \
            f"ref={ref_d['mode_dist']:.2f}"
