"""
Multi-period PSHA verification tests.

Independent reference implementation that loads model data from heterogeneous
formats (namespaced XML, SQLite, GeoJSON, TOML) and computes reference hazard
curves, UHS, and deaggregation for comparison against agent output.
"""

import pytest
import csv
import os
import re
import math
import json
import sqlite3
import tomllib
import xml.etree.ElementTree as ET
from scipy.stats import norm


MODEL_DIR = '/app/model'
OUTPUT_DIR = '/app/output'

_NS = {
    's': 'urn:nshmp:sources:1.0',
    'mfd': 'urn:nshmp:mfd:1.0',
    'fault': 'urn:nshmp:fault:1.0',
}


# ---------------------------------------------------------------------------
# Model Loading
# ---------------------------------------------------------------------------

def _load_sources():
    tree = ET.parse(os.path.join(MODEL_DIR, 'sources.xml'))
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


def _load_gmm():
    conn = sqlite3.connect(os.path.join(MODEL_DIR, 'gmm.db'))
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


def _load_sites():
    with open(os.path.join(MODEL_DIR, 'sites.geojson')) as f:
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


def _load_config():
    with open(os.path.join(MODEL_DIR, 'config.toml'), 'rb') as f:
        return tomllib.load(f)


# ---------------------------------------------------------------------------
# Distance Computations
# ---------------------------------------------------------------------------

def _fdist(lon1, lat1, lon2, lat2):
    lm = (lat1 + lat2) / 2.0
    dx = (lon2 - lon1) * 111.0 * math.cos(math.radians(lm))
    dy = (lat2 - lat1) * 111.0
    return math.sqrt(dx * dx + dy * dy)


def _xy(lon, lat, rlon, rlat):
    return ((lon - rlon) * 111.0 * math.cos(math.radians(rlat)),
            (lat - rlat) * 111.0)


def _rrup_point(src_lon, src_lat, src_depth, site_lon, site_lat):
    r_epi = _fdist(src_lon, src_lat, site_lon, site_lat)
    return math.sqrt(r_epi ** 2 + src_depth ** 2)


def _rrup_3d(s_along, s_perp, rup_start, rup_end, dip_rad, ztor, zbot):
    sin_d = math.sin(dip_rad)
    cos_d = math.cos(dip_rad)
    W = (zbot - ztor) / sin_d if sin_d > 1e-10 else 1e6

    u_c = max(rup_start, min(rup_end, s_along))
    d_along_sq = (s_along - u_c) ** 2

    v_unc = cos_d * s_perp - sin_d * ztor
    v = max(0.0, min(W, v_unc))

    d_p = s_perp - v * cos_d
    d_z = ztor + v * sin_d
    return math.sqrt(d_along_sq + d_p ** 2 + d_z ** 2)


# ---------------------------------------------------------------------------
# GMM and Exceedance
# ---------------------------------------------------------------------------

def _gmm_eval(m, rrup, site, coeffs, mref, vref, z1ref):
    c = coeffs
    r_eff = math.sqrt(rrup ** 2 + c['h'] ** 2)
    z1_term = max(math.log(site['z1p0'] / z1ref), 0.0) if z1ref > 0 else 0.0
    return (c['c0']
            + c['c1'] * (m - mref)
            + c['c2'] * (m - mref) ** 2
            + c['c3'] * math.log(r_eff)
            + c['c_site'] * math.log(min(site['vs30'], vref) / vref)
            + c['c_basin'] * z1_term)


def _pe(ln_iml, mu, sigma, trunc):
    eps = (ln_iml - mu) / sigma
    if eps >= trunc:
        return 0.0
    return (norm.cdf(trunc) - norm.cdf(eps)) / norm.cdf(trunc)


# ---------------------------------------------------------------------------
# MFD and Rupture Scaling
# ---------------------------------------------------------------------------

def _gr(a, b, m_min, m_max, dm):
    ms, rs = [], []
    m = m_min
    while m <= m_max + dm * 0.001:
        r = 10.0 ** (a - b * (m - dm / 2.0)) - \
            10.0 ** (a - b * (m + dm / 2.0))
        ms.append(round(m, 4))
        rs.append(max(r, 0.0))
        m = round(m + dm, 4)
    return ms, rs


def _parse_rs(formula):
    m = re.search(r'=\s*([-\d.]+)\s*\+\s*([-\d.]+)\s*\*\s*M', formula)
    return float(m.group(1)), float(m.group(2))


# ---------------------------------------------------------------------------
# PSHA Computation
# ---------------------------------------------------------------------------

def _fault_local_coords(src, site):
    tr = src['trace']
    rlon = (tr[0]['lon'] + tr[1]['lon']) / 2.0
    rlat = (tr[0]['lat'] + tr[1]['lat']) / 2.0
    ax, ay = _xy(tr[0]['lon'], tr[0]['lat'], rlon, rlat)
    bx, by = _xy(tr[1]['lon'], tr[1]['lat'], rlon, rlat)
    sx, sy = _xy(site['lon'], site['lat'], rlon, rlat)
    tdx, tdy = bx - ax, by - ay
    lt = math.sqrt(tdx ** 2 + tdy ** 2)
    if lt < 1e-6:
        return None
    skx, sky = tdx / lt, tdy / lt
    px, py = sky, -skx
    rx, ry = sx - ax, sy - ay
    return {
        's_along': rx * skx + ry * sky,
        's_perp': rx * px + ry * py,
        'lt': lt,
    }


def _compute_hazard(srcs, gmm_models, site, imls, trunc, sp,
                    mref, vref, z1ref):
    k = len(imls)
    ln_imls = [math.log(x) for x in imls]
    hz = [0.0] * k

    for s in srcs:
        if s['type'] == 'point':
            rrup = _rrup_point(
                s['location']['lon'], s['location']['lat'],
                s['location']['depth'], site['lon'], site['lat'])
            ms, rs = _gr(s['mfd']['a'], s['mfd']['b'],
                         s['mfd']['mMin'], s['mfd']['mMax'],
                         s['mfd']['dMag'])
            for g in gmm_models:
                wg = g['weight']
                for m, r in zip(ms, rs):
                    if r <= 0:
                        continue
                    mu = _gmm_eval(m, rrup, site, g['coefficients'],
                                   mref, vref, z1ref)
                    for i in range(k):
                        hz[i] += wg * r * _pe(ln_imls[i], mu,
                                              g['sigma'], trunc)

        elif s['type'] == 'fault':
            lc = _fault_local_coords(s, site)
            if lc is None:
                continue
            s_al, s_pp, lt = lc['s_along'], lc['s_perp'], lc['lt']
            dip_rad = math.radians(s['geometry']['dip'])
            ztor = s['geometry']['upperDepth']
            zbot = s['geometry']['lowerDepth']
            rs_a, rs_b = _parse_rs(s['ruptureScaling']['formula'])

            mfd = s['mfd']
            mbrs = mfd.get('mMaxEpistemic', {}).get(
                'branches', [{'mMax': mfd['mMax'], 'weight': 1.0}])

            for br in mbrs:
                wm = br['weight']
                ms, rs = _gr(mfd['a'], mfd['b'], mfd['mMin'],
                             br['mMax'], mfd['dMag'])
                for g in gmm_models:
                    wg = g['weight']
                    for m, r in zip(ms, rs):
                        if r <= 0:
                            continue
                        lr = 10.0 ** (rs_a + rs_b * m)
                        if lr >= lt:
                            rr = max(_rrup_3d(s_al, s_pp, 0, lt,
                                              dip_rad, ztor, zbot), 0.1)
                            mu = _gmm_eval(m, rr, site,
                                           g['coefficients'],
                                           mref, vref, z1ref)
                            for i in range(k):
                                hz[i] += wm * wg * r * _pe(
                                    ln_imls[i], mu, g['sigma'], trunc)
                        else:
                            np_ = max(1, int(math.ceil(
                                (lt - lr) / sp)) + 1)
                            rpp = r / np_
                            for j in range(np_):
                                off = (j * (lt - lr) / (np_ - 1)
                                       if np_ > 1 else 0.0)
                                rr = max(_rrup_3d(
                                    s_al, s_pp, off, off + lr,
                                    dip_rad, ztor, zbot), 0.1)
                                mu = _gmm_eval(m, rr, site,
                                               g['coefficients'],
                                               mref, vref, z1ref)
                                for i in range(k):
                                    hz[i] += wm * wg * rpp * _pe(
                                        ln_imls[i], mu, g['sigma'],
                                        trunc)
    return hz


def _interp(imls, rates, target):
    for i in range(len(rates) - 1):
        if rates[i] <= 0 or rates[i + 1] <= 0:
            continue
        if rates[i] >= target >= rates[i + 1]:
            f = ((math.log(target) - math.log(rates[i]))
                 / (math.log(rates[i + 1]) - math.log(rates[i])))
            return math.exp(math.log(imls[i])
                            + f * (math.log(imls[i + 1])
                                   - math.log(imls[i])))
    return imls[0] if target >= rates[0] else imls[-1]


# ---------------------------------------------------------------------------
# Deaggregation
# ---------------------------------------------------------------------------

def _compute_deagg(srcs, gmm_models, site, target_iml, trunc, sp,
                   dc, mref, vref, z1ref):
    ln_iml = math.log(target_iml)
    dm = dc['delta_m']
    dr = dc['delta_r']
    m0, m1 = dc['m_min'], dc['m_max']
    r0, r1 = dc['r_min'], dc['r_max']
    nm = int(round((m1 - m0) / dm))
    nr = int(round((r1 - r0) / dr))
    bins = [[0.0] * nr for _ in range(nm)]

    def _add(m, rrup, c):
        if c <= 0:
            return
        mi = int((m - m0) / dm)
        ri = int((rrup - r0) / dr)
        if 0 <= mi < nm and 0 <= ri < nr:
            bins[mi][ri] += c

    for s in srcs:
        if s['type'] == 'point':
            rrup = _rrup_point(
                s['location']['lon'], s['location']['lat'],
                s['location']['depth'], site['lon'], site['lat'])
            ms, rs = _gr(s['mfd']['a'], s['mfd']['b'],
                         s['mfd']['mMin'], s['mfd']['mMax'],
                         s['mfd']['dMag'])
            for g in gmm_models:
                for m, r in zip(ms, rs):
                    if r <= 0:
                        continue
                    mu = _gmm_eval(m, rrup, site, g['coefficients'],
                                   mref, vref, z1ref)
                    _add(m, rrup, g['weight'] * r * _pe(
                        ln_iml, mu, g['sigma'], trunc))

        elif s['type'] == 'fault':
            lc = _fault_local_coords(s, site)
            if lc is None:
                continue
            s_al, s_pp, lt = lc['s_along'], lc['s_perp'], lc['lt']
            dip_rad = math.radians(s['geometry']['dip'])
            ztor = s['geometry']['upperDepth']
            zbot = s['geometry']['lowerDepth']
            rs_a, rs_b = _parse_rs(s['ruptureScaling']['formula'])

            mfd = s['mfd']
            mbrs = mfd.get('mMaxEpistemic', {}).get(
                'branches', [{'mMax': mfd['mMax'], 'weight': 1.0}])

            for br in mbrs:
                wm = br['weight']
                ms, rs = _gr(mfd['a'], mfd['b'], mfd['mMin'],
                             br['mMax'], mfd['dMag'])
                for g in gmm_models:
                    wg = g['weight']
                    for m, r in zip(ms, rs):
                        if r <= 0:
                            continue
                        lr = 10.0 ** (rs_a + rs_b * m)
                        if lr >= lt:
                            rr = max(_rrup_3d(s_al, s_pp, 0, lt,
                                              dip_rad, ztor, zbot), 0.1)
                            mu = _gmm_eval(m, rr, site,
                                           g['coefficients'],
                                           mref, vref, z1ref)
                            _add(m, rr, wm * wg * r * _pe(
                                ln_iml, mu, g['sigma'], trunc))
                        else:
                            np_ = max(1, int(math.ceil(
                                (lt - lr) / sp)) + 1)
                            rpp = r / np_
                            for j in range(np_):
                                off = (j * (lt - lr) / (np_ - 1)
                                       if np_ > 1 else 0.0)
                                rr = max(_rrup_3d(
                                    s_al, s_pp, off, off + lr,
                                    dip_rad, ztor, zbot), 0.1)
                                mu = _gmm_eval(m, rr, site,
                                               g['coefficients'],
                                               mref, vref, z1ref)
                                _add(m, rr, wm * wg * rpp * _pe(
                                    ln_iml, mu, g['sigma'], trunc))

    total = sum(sum(row) for row in bins)
    if total <= 0:
        return None
    mm, mr = 0.0, 0.0
    mc, mi_, ri_ = 0.0, 0, 0
    for mi in range(nm):
        cm = m0 + (mi + 0.5) * dm
        for ri in range(nr):
            cr = r0 + (ri + 0.5) * dr
            cv = bins[mi][ri]
            mm += cm * cv
            mr += cr * cv
            if cv > mc:
                mc, mi_, ri_ = cv, mi, ri
    return {
        'mean_M': mm / total,
        'mean_R': mr / total,
        'mode_M': m0 + (mi_ + 0.5) * dm,
        'mode_R': r0 + (ri_ + 0.5) * dr,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def model():
    return {
        'sources': _load_sources(),
        'gmm': _load_gmm(),
        'sites': _load_sites(),
        'config': _load_config(),
    }


@pytest.fixture(scope='module')
def ref(model):
    srcs = model['sources']
    gmm = model['gmm']
    sites = model['sites']
    cfg = model['config']
    meta = gmm['metadata']

    mref = float(meta['Mref'])
    vref = float(meta['Vref'])
    z1ref = float(meta['z1p0_ref'])

    trunc = cfg['hazard']['truncation_level']
    sp = cfg['fault_discretization']['surface_spacing_km']
    rps = cfg['output']['return_periods']
    dc = cfg['deaggregation']

    imts = ['PGA', 'SA0P2', 'SA1P0']
    res = {}

    for imt in imts:
        imls = cfg['hazard']['imls'][imt]
        gm = gmm['models'][imt]
        res[imt] = {'imls': imls}
        for site in sites:
            hz = _compute_hazard(srcs, gm, site, imls, trunc, sp,
                                mref, vref, z1ref)
            rpv = {}
            for rp in rps:
                rpv[rp] = _interp(imls, hz, 1.0 / rp)
            res[imt][site['name']] = {'hazard': hz, 'rp_vals': rpv}

    res['uhs'] = {}
    for site in sites:
        res['uhs'][site['name']] = {}
        for rp in rps:
            uv = {}
            for imt in imts:
                uv[imt] = res[imt][site['name']]['rp_vals'][rp]
            res['uhs'][site['name']][rp] = uv

    deagg_imt = dc['imt']
    deagg_site = dc['site']
    deagg_rp = dc['return_period']
    gm = gmm['models'][deagg_imt]
    dimls = cfg['hazard']['imls'][deagg_imt]
    dhz = res[deagg_imt][deagg_site]['hazard']
    timl = _interp(dimls, dhz, 1.0 / deagg_rp)
    sobj = next(s for s in sites if s['name'] == deagg_site)
    res['deagg'] = _compute_deagg(srcs, gm, sobj, timl, trunc, sp,
                                  dc, mref, vref, z1ref)
    return res


# ---------------------------------------------------------------------------
# Output Parsing
# ---------------------------------------------------------------------------

def _read_hazard_csv(imt):
    path = os.path.join(OUTPUT_DIR, f'hazard_{imt}.csv')
    with open(path) as f:
        rd = csv.reader(f)
        header = next(rd)
        data = {}
        for row in rd:
            data[row[0].strip()] = [float(v) for v in row[1:]]
    return header, data


def _read_uhs_csv():
    path = os.path.join(OUTPUT_DIR, 'uhs.csv')
    with open(path) as f:
        rd = csv.reader(f)
        header = next(rd)
        data = {}
        for row in rd:
            site = row[0].strip()
            rp = int(float(row[1]))
            vals = {h.strip(): float(v) for h, v in zip(header[2:], row[2:])}
            if site not in data:
                data[site] = {}
            data[site][rp] = vals
    return data


def _read_deagg_csv():
    path = os.path.join(OUTPUT_DIR, 'deaggregation.csv')
    with open(path) as f:
        rd = csv.reader(f)
        next(rd)
        data = {}
        for row in rd:
            data[row[0].strip()] = float(row[1])
    return data


# ---------------------------------------------------------------------------
# Tests -- File Existence
# ---------------------------------------------------------------------------

class TestOutputFilesExist:
    def test_hazard_pga_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, 'hazard_PGA.csv'))

    def test_hazard_sa02_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, 'hazard_SA0P2.csv'))

    def test_hazard_sa10_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, 'hazard_SA1P0.csv'))

    def test_uhs_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, 'uhs.csv'))

    def test_deagg_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, 'deaggregation.csv'))


# ---------------------------------------------------------------------------
# Tests -- Hazard Curve Format
# ---------------------------------------------------------------------------

class TestHazardCurvesFormat:
    @pytest.mark.parametrize("imt", ["PGA", "SA0P2", "SA1P0"])
    def test_header_length(self, model, imt):
        header, _ = _read_hazard_csv(imt)
        imls = model['config']['hazard']['imls'][imt]
        assert len(header) == len(imls) + 1, \
            f"{imt} header has {len(header)} cols, expected {len(imls) + 1}"

    @pytest.mark.parametrize("imt", ["PGA", "SA0P2", "SA1P0"])
    def test_all_sites_present(self, model, imt):
        _, data = _read_hazard_csv(imt)
        for site in model['sites']:
            assert site['name'] in data, f"Missing {site['name']} in {imt}"

    @pytest.mark.parametrize("imt", ["PGA", "SA0P2", "SA1P0"])
    def test_correct_num_values(self, model, imt):
        _, data = _read_hazard_csv(imt)
        n = len(model['config']['hazard']['imls'][imt])
        for name, vals in data.items():
            assert len(vals) == n, \
                f"{name} {imt}: {len(vals)} values, expected {n}"

    @pytest.mark.parametrize("imt", ["PGA", "SA0P2", "SA1P0"])
    def test_monotonicity(self, imt):
        _, data = _read_hazard_csv(imt)
        for name, rates in data.items():
            for i in range(len(rates) - 1):
                assert rates[i] >= rates[i + 1] - 1e-10, \
                    f"Non-monotonic at {name} {imt} idx {i}: " \
                    f"{rates[i]:.6e} < {rates[i+1]:.6e}"

    @pytest.mark.parametrize("imt", ["PGA", "SA0P2", "SA1P0"])
    def test_non_negative(self, imt):
        _, data = _read_hazard_csv(imt)
        for name, rates in data.items():
            for i, r in enumerate(rates):
                assert r >= -1e-12, \
                    f"Negative rate at {name} {imt} idx {i}: {r:.6e}"

    @pytest.mark.parametrize("imt", ["PGA", "SA0P2", "SA1P0"])
    def test_first_rate_positive(self, imt):
        _, data = _read_hazard_csv(imt)
        for name, rates in data.items():
            assert rates[0] > 1e-4, \
                f"Rate at lowest IML too small for {name} {imt}: " \
                f"{rates[0]:.6e}"


# ---------------------------------------------------------------------------
# Tests -- Hazard Curve Values
# ---------------------------------------------------------------------------

class TestHazardCurveValues:
    @pytest.mark.parametrize("imt", ["PGA", "SA0P2", "SA1P0"])
    @pytest.mark.parametrize("site_name", ["Site_A", "Site_B", "Site_C"])
    def test_values(self, ref, imt, site_name):
        _, data = _read_hazard_csv(imt)
        r = ref[imt][site_name]['hazard']
        a = data[site_name]
        for i in range(len(r)):
            if r[i] > 1e-8:
                err = abs(a[i] - r[i]) / r[i]
                assert err < 0.05, \
                    f"{site_name} {imt} idx {i}: agent={a[i]:.6e} " \
                    f"ref={r[i]:.6e} err={err:.4f}"

    def test_site_a_highest_pga(self):
        """Site_A is closest to the major strike-slip fault."""
        _, data = _read_hazard_csv('PGA')
        assert data['Site_A'][10] > data['Site_B'][10], \
            "Site_A should have higher PGA hazard than Site_B at 0.4g"
        assert data['Site_A'][10] > data['Site_C'][10], \
            "Site_A should have higher PGA hazard than Site_C at 0.4g"


# ---------------------------------------------------------------------------
# Tests -- UHS
# ---------------------------------------------------------------------------

class TestUHS:
    def test_format(self, model):
        data = _read_uhs_csv()
        rps = model['config']['output']['return_periods']
        for site in model['sites']:
            assert site['name'] in data, f"Missing {site['name']} in UHS"
            for rp in rps:
                assert rp in data[site['name']], \
                    f"Missing rp={rp} for {site['name']}"
                for imt in ['PGA', 'SA0P2', 'SA1P0']:
                    assert imt in data[site['name']][rp], \
                        f"Missing {imt} for {site['name']} rp={rp}"

    @pytest.mark.parametrize("site_name", ["Site_A", "Site_B", "Site_C"])
    @pytest.mark.parametrize("rp", [475, 2475])
    def test_uhs_values(self, ref, site_name, rp):
        data = _read_uhs_csv()
        for imt in ['PGA', 'SA0P2', 'SA1P0']:
            rv = ref['uhs'][site_name][rp][imt]
            av = data[site_name][rp][imt]
            err = abs(av - rv) / rv if rv > 1e-8 else abs(av - rv)
            assert err < 0.10, \
                f"UHS {site_name} rp={rp} {imt}: " \
                f"agent={av:.6f} ref={rv:.6f} err={err:.4f}"

    def test_longer_rp_higher(self):
        data = _read_uhs_csv()
        for sn in ['Site_A', 'Site_B', 'Site_C']:
            for imt in ['PGA', 'SA0P2', 'SA1P0']:
                assert data[sn][2475][imt] > data[sn][475][imt], \
                    f"{sn} {imt}: 2475yr should exceed 475yr"

    def test_sa02_exceeds_pga(self):
        """SA(0.2s) should exceed PGA in UHS (short-period amplification)."""
        data = _read_uhs_csv()
        for sn in ['Site_A', 'Site_B', 'Site_C']:
            for rp in [475, 2475]:
                assert data[sn][rp]['SA0P2'] > data[sn][rp]['PGA'], \
                    f"{sn} rp={rp}: SA0P2 should exceed PGA in UHS"


# ---------------------------------------------------------------------------
# Tests -- Deaggregation
# ---------------------------------------------------------------------------

class TestDeaggregation:
    def test_format(self):
        data = _read_deagg_csv()
        for key in ['mean_M', 'mean_R', 'mode_M', 'mode_R']:
            assert key in data, f"Missing deagg metric: {key}"

    def test_physical_ranges(self):
        data = _read_deagg_csv()
        assert 5.0 <= data['mean_M'] <= 8.0, \
            f"mean_M out of range: {data['mean_M']}"
        assert 0.0 <= data['mean_R'] <= 300.0, \
            f"mean_R out of range: {data['mean_R']}"
        assert 5.0 <= data['mode_M'] <= 8.0, \
            f"mode_M out of range: {data['mode_M']}"
        assert 0.0 <= data['mode_R'] <= 300.0, \
            f"mode_R out of range: {data['mode_R']}"

    def test_values(self, ref):
        data = _read_deagg_csv()
        r = ref['deagg']
        assert r is not None, "Reference deagg returned None"
        assert abs(data['mean_M'] - r['mean_M']) < 0.3, \
            f"mean_M: agent={data['mean_M']:.4f} ref={r['mean_M']:.4f}"
        assert abs(data['mean_R'] - r['mean_R']) < 15.0, \
            f"mean_R: agent={data['mean_R']:.4f} ref={r['mean_R']:.4f}"
        assert abs(data['mode_M'] - r['mode_M']) < 0.3, \
            f"mode_M: agent={data['mode_M']:.4f} ref={r['mode_M']:.4f}"
        assert abs(data['mode_R'] - r['mode_R']) < 15.0, \
            f"mode_R: agent={data['mode_R']:.4f} ref={r['mode_R']:.4f}"
