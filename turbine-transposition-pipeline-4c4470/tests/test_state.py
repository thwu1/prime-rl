"""IEC 60193 model-to-prototype transposition verification tests."""
import json
import csv
import math
import os
import sqlite3
import pytest


_G = 9.80665


def _wp_interp(tbl, t, idx):
    """Linearly interpolate water property from sorted table."""
    if t <= tbl[0][0]:
        return tbl[0][idx]
    if t >= tbl[-1][0]:
        return tbl[-1][idx]
    for i in range(len(tbl) - 1):
        if tbl[i][0] <= t <= tbl[i + 1][0]:
            f = (t - tbl[i][0]) / (tbl[i + 1][0] - tbl[i][0])
            return tbl[i][idx] + f * (tbl[i + 1][idx] - tbl[i][idx])
    return tbl[-1][idx]


def _load_wp():
    rows = []
    with open('/app/data/water_properties.csv') as fh:
        for r in csv.DictReader(fh):
            rows.append((float(r['temp_C']),
                         float(r['density_kgm3']),
                         float(r['kinematic_viscosity_m2s']),
                         float(r['vapor_pressure_Pa'])))
    rows.sort(key=lambda x: x[0])
    return rows


def _load_cfg():
    with open('/app/data/site_config.json') as fh:
        return json.load(fh)


def _load_pts():
    pts = []
    with open('/app/data/model_tests.csv') as fh:
        for r in csv.DictReader(fh):
            pts.append({k: (int(r[k]) if k == 'point_id' else float(r[k]))
                        for k in r})
    return pts


def _baro(alt):
    return 101325.0 * (1.0 - 2.2557e-5 * alt) ** 5.2559


def _build_ref():
    wp = _load_wp()
    cfg = _load_cfg()
    pts = _load_pts()

    dm = cfg['model']['D_m']
    a1 = cfg['model']['A1_m2']
    a2 = cfg['model']['A2_m2']
    dz = cfg['model']['z1_minus_z2_m']
    lab_alt = cfg['model']['lab_altitude_m']
    hs = cfg['model']['submergence_m']

    dp = cfg['prototype']['D_m']
    ep = cfg['prototype']['E_Jkg']

    s_alt = cfg['site']['altitude_masl']
    s_tmp = cfg['site']['water_temp_C']
    z_tw = cfg['site']['z_tailwater_m']
    z_rf = cfg['site']['z_turbine_ref_m']

    fq = cfg['uncertainty']['f_Q_pct']
    fe = cfg['uncertainty']['f_E_pct']
    ft = cfg['uncertainty']['f_T_pct']
    fn = cfg['uncertainty']['f_n_pct']
    sc = cfg['sigma_critical']

    rho_p = _wp_interp(wp, s_tmp, 1)
    nu_p = _wp_interp(wp, s_tmp, 2)
    pv_p = _wp_interp(wp, s_tmp, 3)

    rep = dp * math.sqrt(2.0 * ep) / nu_p
    pa_lab = _baro(lab_alt)
    pa_site = _baro(s_alt)

    out = []
    for p in pts:
        tmp = p['water_temp_C']
        rho = _wp_interp(wp, tmp, 1)
        nu = _wp_interp(wp, tmp, 2)
        pv = _wp_interp(wp, tmp, 3)

        q = p['Q_ls'] / 1000.0
        n = p['n_rpm'] / 60.0
        p1 = p['p1_kPa'] * 1000.0
        p2 = p['p2_kPa'] * 1000.0
        torq = p['T_Nm']

        v1 = q / a1
        v2 = q / a2
        e = (p1 - p2) / rho + (v1 * v1 - v2 * v2) / 2.0 + _G * dz

        se = math.sqrt(e)
        ned = n * dm / se
        qed = q / (dm * dm * se)
        ted = torq / (rho * dm ** 3 * e)

        w = 2.0 * math.pi * n
        pm = torq * w
        em = pm / (rho * q * e)

        rem = dm * math.sqrt(2.0 * e) / nu
        de = (1.0 - em) * (1.0 - (rem / rep) ** 0.16)
        etp = em + de

        npse = (pa_lab - pv) / rho + _G * hs
        sig = npse / e

        feta = math.sqrt(ft ** 2 + fn ** 2 + fq ** 2 + fe ** 2)

        out.append({
            'point_id': p['point_id'], 'E_Jkg': e,
            'nED': ned, 'QED': qed, 'TED': ted,
            'eta_model': em, 'Re_model': rem, 'Re_prototype': rep,
            'delta_eta': de, 'eta_prototype': etp,
            'sigma_model': sig, 'f_eta_pct': feta
        })

    bep = max(out, key=lambda x: x['eta_prototype'])
    bp = next(p for p in pts if p['point_id'] == bep['point_id'])

    qm_b = bp['Q_ls'] / 1000.0
    nm_b = bp['n_rpm'] / 60.0
    em_b = bep['E_Jkg']

    sd = dp / dm
    se_ratio = math.sqrt(ep / em_b)

    qp = qm_b * sd * sd * se_ratio
    np_ = nm_b * (1.0 / sd) * se_ratio
    pp = rho_p * qp * ep * bep['eta_prototype']

    sp = ((pa_site - pv_p) / rho_p + _G * (z_tw - z_rf)) / ep
    sm = sp - sc

    return {
        'points': out,
        'bep': {
            'point_id': bep['point_id'],
            'eta_prototype': bep['eta_prototype'],
            'nED': bep['nED'], 'QED': bep['QED']
        },
        'prototype_bep': {
            'Q_m3s': qp, 'n_rpm': np_ * 60.0, 'P_MW': pp / 1e6
        },
        'cavitation': {
            'p_atm_Pa': pa_site, 'p_vapor_Pa': pv_p,
            'sigma_plant': sp, 'sigma_critical': sc,
            'safety_margin': sm, 'is_safe': sm >= 0.05
        }
    }


@pytest.fixture(scope='module')
def ref():
    return _build_ref()


@pytest.fixture(scope='module')
def sol():
    with open('/app/output/results.json') as fh:
        return json.load(fh)


def _sol_pt(sol, pid):
    for p in sol['points']:
        if p['point_id'] == pid:
            return p
    return None


def _rel(a, b):
    if b == 0:
        return abs(a)
    return abs(a - b) / abs(b)


# ── Structure ──────────────────────────────────────────────

class TestStructure:
    def test_output_file_exists(self):
        assert os.path.exists('/app/output/results.json')

    def test_transposer_exists(self):
        assert os.path.exists('/app/transposer.py')
        assert os.path.getsize('/app/transposer.py') > 500

    def test_valid_json(self, sol):
        assert isinstance(sol, dict)

    def test_has_points(self, sol):
        assert 'points' in sol
        assert len(sol['points']) == 12

    def test_has_bep(self, sol):
        assert 'bep' in sol
        for k in ('point_id', 'eta_prototype', 'nED', 'QED'):
            assert k in sol['bep'], f"bep missing key {k}"

    def test_has_prototype_bep(self, sol):
        assert 'prototype_bep' in sol
        for k in ('Q_m3s', 'n_rpm', 'P_MW'):
            assert k in sol['prototype_bep'], f"prototype_bep missing key {k}"

    def test_has_cavitation(self, sol):
        assert 'cavitation' in sol
        for k in ('p_atm_Pa', 'p_vapor_Pa', 'sigma_plant',
                   'sigma_critical', 'safety_margin', 'is_safe'):
            assert k in sol['cavitation'], f"cavitation missing key {k}"

    def test_point_fields(self, sol):
        required = {'point_id', 'E_Jkg', 'nED', 'QED', 'TED',
                     'eta_model', 'Re_model', 'Re_prototype',
                     'delta_eta', 'eta_prototype', 'sigma_model', 'f_eta_pct'}
        for pt in sol['points']:
            missing = required - set(pt.keys())
            assert not missing, f"Point {pt.get('point_id')}: missing {missing}"


# ── Specific Hydraulic Energy ──────────────────────────────

class TestEnergy:
    def test_E_values(self, sol, ref):
        for rp in ref['points']:
            sp = _sol_pt(sol, rp['point_id'])
            assert sp is not None, f"Missing point {rp['point_id']}"
            assert _rel(sp['E_Jkg'], rp['E_Jkg']) < 0.001, \
                f"Pt {rp['point_id']}: E {sp['E_Jkg']:.4f} vs ref {rp['E_Jkg']:.4f}"

    def test_E_positive(self, sol):
        for pt in sol['points']:
            assert pt['E_Jkg'] > 100, f"Pt {pt['point_id']}: E unreasonably low"

    def test_E_range(self, sol):
        for pt in sol['points']:
            assert 200 < pt['E_Jkg'] < 600, \
                f"Pt {pt['point_id']}: E={pt['E_Jkg']:.1f} outside expected range"


# ── Dimensionless Coefficients ─────────────────────────────

class TestDimensionless:
    def test_nED(self, sol, ref):
        for rp in ref['points']:
            sp = _sol_pt(sol, rp['point_id'])
            assert _rel(sp['nED'], rp['nED']) < 0.001, \
                f"Pt {rp['point_id']}: nED {sp['nED']:.6f} vs {rp['nED']:.6f}"

    def test_QED(self, sol, ref):
        for rp in ref['points']:
            sp = _sol_pt(sol, rp['point_id'])
            assert _rel(sp['QED'], rp['QED']) < 0.001, \
                f"Pt {rp['point_id']}: QED {sp['QED']:.6f} vs {rp['QED']:.6f}"

    def test_TED(self, sol, ref):
        for rp in ref['points']:
            sp = _sol_pt(sol, rp['point_id'])
            assert _rel(sp['TED'], rp['TED']) < 0.001, \
                f"Pt {rp['point_id']}: TED {sp['TED']:.6f} vs {rp['TED']:.6f}"

    def test_nED_range(self, sol):
        for pt in sol['points']:
            assert 0.3 < pt['nED'] < 0.8, f"Pt {pt['point_id']}: nED out of range"

    def test_QED_range(self, sol):
        for pt in sol['points']:
            assert 0.01 < pt['QED'] < 0.15, f"Pt {pt['point_id']}: QED out of range"


# ── Model Efficiency ──────────────────────────────────────

class TestEfficiency:
    def test_eta_model(self, sol, ref):
        for rp in ref['points']:
            sp = _sol_pt(sol, rp['point_id'])
            assert _rel(sp['eta_model'], rp['eta_model']) < 0.001, \
                f"Pt {rp['point_id']}: eta_M {sp['eta_model']:.6f} vs {rp['eta_model']:.6f}"

    def test_eta_model_physical_range(self, sol):
        for pt in sol['points']:
            assert 0.5 < pt['eta_model'] < 1.0, \
                f"Pt {pt['point_id']}: eta_M={pt['eta_model']:.4f} outside physical range"


# ── Reynolds Numbers ──────────────────────────────────────

class TestReynolds:
    def test_Re_model(self, sol, ref):
        for rp in ref['points']:
            sp = _sol_pt(sol, rp['point_id'])
            assert _rel(sp['Re_model'], rp['Re_model']) < 0.005, \
                f"Pt {rp['point_id']}: Re_M {sp['Re_model']:.0f} vs {rp['Re_model']:.0f}"

    def test_Re_prototype_uniform(self, sol, ref):
        rep_ref = ref['points'][0]['Re_prototype']
        for pt in sol['points']:
            assert _rel(pt['Re_prototype'], rep_ref) < 0.005, \
                f"Pt {pt['point_id']}: Re_P {pt['Re_prototype']:.0f} vs {rep_ref:.0f}"

    def test_Re_model_above_threshold(self, sol):
        for pt in sol['points']:
            assert pt['Re_model'] > 5e6, \
                f"Pt {pt['point_id']}: Re_M too low for Francis model test"

    def test_Re_prototype_gt_model(self, sol):
        for pt in sol['points']:
            assert pt['Re_prototype'] > pt['Re_model'], \
                f"Pt {pt['point_id']}: Re_P should exceed Re_M"


# ── Step-Up and Prototype Efficiency ──────────────────────

class TestStepUp:
    def test_delta_eta(self, sol, ref):
        for rp in ref['points']:
            sp = _sol_pt(sol, rp['point_id'])
            assert abs(sp['delta_eta'] - rp['delta_eta']) < 0.001, \
                f"Pt {rp['point_id']}: deta {sp['delta_eta']:.6f} vs {rp['delta_eta']:.6f}"

    def test_eta_prototype(self, sol, ref):
        for rp in ref['points']:
            sp = _sol_pt(sol, rp['point_id'])
            assert _rel(sp['eta_prototype'], rp['eta_prototype']) < 0.001, \
                f"Pt {rp['point_id']}: eta_P {sp['eta_prototype']:.6f} vs {rp['eta_prototype']:.6f}"

    def test_delta_eta_positive(self, sol):
        for pt in sol['points']:
            assert pt['delta_eta'] > 0, \
                f"Pt {pt['point_id']}: delta_eta must be positive (prototype Re > model Re)"

    def test_eta_P_exceeds_eta_M(self, sol):
        for pt in sol['points']:
            assert pt['eta_prototype'] > pt['eta_model'], \
                f"Pt {pt['point_id']}: eta_P should exceed eta_M after step-up"


# ── BEP Identification ────────────────────────────────────

class TestBEP:
    def test_bep_point_id(self, sol, ref):
        assert sol['bep']['point_id'] == ref['bep']['point_id'], \
            f"BEP point_id: {sol['bep']['point_id']} vs expected {ref['bep']['point_id']}"

    def test_bep_is_global_max(self, sol):
        bep_eta = sol['bep']['eta_prototype']
        for pt in sol['points']:
            assert pt['eta_prototype'] <= bep_eta + 1e-9, \
                f"Pt {pt['point_id']} eta_P={pt['eta_prototype']:.6f} exceeds BEP={bep_eta:.6f}"

    def test_bep_eta_consistent(self, sol):
        bep_pt = _sol_pt(sol, sol['bep']['point_id'])
        assert bep_pt is not None
        assert abs(bep_pt['eta_prototype'] - sol['bep']['eta_prototype']) < 1e-9

    def test_bep_nED_consistent(self, sol):
        bep_pt = _sol_pt(sol, sol['bep']['point_id'])
        assert abs(bep_pt['nED'] - sol['bep']['nED']) < 1e-9

    def test_bep_QED_consistent(self, sol):
        bep_pt = _sol_pt(sol, sol['bep']['point_id'])
        assert abs(bep_pt['QED'] - sol['bep']['QED']) < 1e-9


# ── Prototype Transposition ────────────────────────────────

class TestPrototype:
    def test_Q_prototype(self, sol, ref):
        assert _rel(sol['prototype_bep']['Q_m3s'],
                     ref['prototype_bep']['Q_m3s']) < 0.002, \
            f"Q_P: {sol['prototype_bep']['Q_m3s']:.4f} vs {ref['prototype_bep']['Q_m3s']:.4f}"

    def test_n_prototype(self, sol, ref):
        assert _rel(sol['prototype_bep']['n_rpm'],
                     ref['prototype_bep']['n_rpm']) < 0.002, \
            f"n_P: {sol['prototype_bep']['n_rpm']:.4f} vs {ref['prototype_bep']['n_rpm']:.4f}"

    def test_P_prototype(self, sol, ref):
        assert _rel(sol['prototype_bep']['P_MW'],
                     ref['prototype_bep']['P_MW']) < 0.005, \
            f"P_P: {sol['prototype_bep']['P_MW']:.4f} vs {ref['prototype_bep']['P_MW']:.4f}"

    def test_Q_prototype_physical(self, sol):
        assert 10 < sol['prototype_bep']['Q_m3s'] < 100, \
            "Prototype discharge outside physical range for this turbine class"

    def test_n_prototype_physical(self, sol):
        assert 100 < sol['prototype_bep']['n_rpm'] < 500, \
            "Prototype speed outside physical range"

    def test_P_prototype_physical(self, sol):
        assert 10 < sol['prototype_bep']['P_MW'] < 100, \
            "Prototype power outside physical range"


# ── Cavitation Analysis ────────────────────────────────────

class TestCavitation:
    def test_p_atm(self, sol, ref):
        assert _rel(sol['cavitation']['p_atm_Pa'],
                     ref['cavitation']['p_atm_Pa']) < 0.001

    def test_p_vapor(self, sol, ref):
        assert _rel(sol['cavitation']['p_vapor_Pa'],
                     ref['cavitation']['p_vapor_Pa']) < 0.001

    def test_sigma_plant(self, sol, ref):
        assert abs(sol['cavitation']['sigma_plant'] -
                    ref['cavitation']['sigma_plant']) < 0.001, \
            f"sigma_plant: {sol['cavitation']['sigma_plant']:.6f} vs {ref['cavitation']['sigma_plant']:.6f}"

    def test_sigma_critical_passthrough(self, sol):
        assert abs(sol['cavitation']['sigma_critical'] - 0.08) < 1e-9

    def test_safety_margin(self, sol, ref):
        assert abs(sol['cavitation']['safety_margin'] -
                    ref['cavitation']['safety_margin']) < 0.001

    def test_is_safe(self, sol, ref):
        assert sol['cavitation']['is_safe'] == ref['cavitation']['is_safe'], \
            f"is_safe: {sol['cavitation']['is_safe']} vs expected {ref['cavitation']['is_safe']}"

    def test_sigma_model_positive(self, sol):
        for pt in sol['points']:
            assert pt['sigma_model'] > 0, \
                f"Pt {pt['point_id']}: sigma_model must be positive"

    def test_sigma_model_range(self, sol):
        for pt in sol['points']:
            assert 0.1 < pt['sigma_model'] < 1.0, \
                f"Pt {pt['point_id']}: sigma_model={pt['sigma_model']:.4f} outside expected range"

    def test_sigma_model_values(self, sol, ref):
        for rp in ref['points']:
            sp = _sol_pt(sol, rp['point_id'])
            assert abs(sp['sigma_model'] - rp['sigma_model']) < 0.002, \
                f"Pt {rp['point_id']}: sigma {sp['sigma_model']:.6f} vs {rp['sigma_model']:.6f}"


# ── Uncertainty Propagation ────────────────────────────────

class TestUncertainty:
    def test_f_eta_values(self, sol, ref):
        for rp in ref['points']:
            sp = _sol_pt(sol, rp['point_id'])
            assert abs(sp['f_eta_pct'] - rp['f_eta_pct']) < 0.01, \
                f"Pt {rp['point_id']}: f_eta {sp['f_eta_pct']:.4f} vs {rp['f_eta_pct']:.4f}"

    def test_f_eta_positive(self, sol):
        for pt in sol['points']:
            assert pt['f_eta_pct'] > 0, f"Pt {pt['point_id']}: f_eta must be positive"

    def test_f_eta_reasonable(self, sol):
        for pt in sol['points']:
            assert pt['f_eta_pct'] < 1.0, \
                f"Pt {pt['point_id']}: f_eta={pt['f_eta_pct']:.4f}% too large"


# ── Cross-Consistency ──────────────────────────────────────

class TestConsistency:
    def test_points_ordered_by_id(self, sol):
        ids = [p['point_id'] for p in sol['points']]
        assert len(set(ids)) == 12, "Not all 12 unique point IDs present"

    def test_eta_prototype_ordering_plausible(self, sol):
        """BEP should be near GVO=75% based on the data design."""
        bep_id = sol['bep']['point_id']
        assert 5 <= bep_id <= 8, \
            f"BEP at point {bep_id} — expected in GVO=75% range (5-8)"

    def test_higher_speed_higher_E(self, sol):
        """Within same GVO, higher speed points should have higher E
        (because pressures increase with speed in the test data)."""
        gvo_groups = {}
        for pt in sol['points']:
            gvo = None
            if pt['point_id'] <= 4:
                gvo = 55
            elif pt['point_id'] <= 8:
                gvo = 75
            else:
                gvo = 90
            gvo_groups.setdefault(gvo, []).append(pt)
        for gvo, pts in gvo_groups.items():
            pts_sorted = sorted(pts, key=lambda x: x['point_id'])
            for i in range(len(pts_sorted) - 1):
                assert pts_sorted[i]['E_Jkg'] < pts_sorted[i + 1]['E_Jkg'], \
                    f"GVO={gvo}: E should increase with speed"


# ── Hill Chart (gnuplot SVG) ──────────────────────────────

class TestHillChart:
    def test_svg_file_exists(self):
        assert os.path.exists('/app/output/hill_chart.svg'), \
            "hill_chart.svg not found"

    def test_svg_minimum_size(self):
        size = os.path.getsize('/app/output/hill_chart.svg')
        assert size > 1000, f"SVG too small ({size} bytes), likely empty or stub"

    def test_svg_valid_structure(self):
        with open('/app/output/hill_chart.svg') as fh:
            content = fh.read()
        assert '<svg' in content, "Missing <svg root element"
        assert '</svg>' in content, "Missing </svg> closing tag"

    def test_svg_gnuplot_provenance(self):
        with open('/app/output/hill_chart.svg') as fh:
            content = fh.read()
        low = content.lower()
        assert 'gnuplot' in low, \
            "SVG lacks gnuplot provenance — must be generated by gnuplot"

    def test_svg_has_graphical_content(self):
        with open('/app/output/hill_chart.svg') as fh:
            content = fh.read()
        has_path = '<path' in content or '<circle' in content or '<rect' in content
        has_line = '<line' in content or '<polyline' in content
        assert has_path or has_line, \
            "SVG has no graphical elements (path/circle/rect/line)"


# ── SQLite Results Database ───────────────────────────────

class TestSQLiteDatabase:
    def test_db_file_exists(self):
        assert os.path.exists('/app/output/results.db'), \
            "results.db not found"

    def test_operating_points_table_exists(self):
        conn = sqlite3.connect('/app/output/results.db')
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='operating_points'")
        assert cur.fetchone() is not None, "Table 'operating_points' missing"
        conn.close()

    def test_operating_points_row_count(self):
        conn = sqlite3.connect('/app/output/results.db')
        cur = conn.execute("SELECT COUNT(*) FROM operating_points")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 12, f"operating_points has {count} rows, expected 12"

    def test_operating_points_columns(self):
        conn = sqlite3.connect('/app/output/results.db')
        cur = conn.execute("PRAGMA table_info(operating_points)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        required = {'point_id', 'E_Jkg', 'nED', 'QED', 'TED',
                     'eta_model', 'Re_model', 'Re_prototype',
                     'delta_eta', 'eta_prototype', 'sigma_model', 'f_eta_pct'}
        missing = required - cols
        assert not missing, f"operating_points missing columns: {missing}"

    def test_bep_summary_table_exists(self):
        conn = sqlite3.connect('/app/output/results.db')
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bep_summary'")
        assert cur.fetchone() is not None, "Table 'bep_summary' missing"
        conn.close()

    def test_bep_summary_row_count(self):
        conn = sqlite3.connect('/app/output/results.db')
        cur = conn.execute("SELECT COUNT(*) FROM bep_summary")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 1, f"bep_summary has {count} rows, expected 1"

    def test_bep_summary_columns(self):
        conn = sqlite3.connect('/app/output/results.db')
        cur = conn.execute("PRAGMA table_info(bep_summary)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        required = {'point_id', 'eta_prototype', 'nED', 'QED',
                     'Q_m3s', 'n_rpm', 'P_MW'}
        missing = required - cols
        assert not missing, f"bep_summary missing columns: {missing}"

    def test_cavitation_table_exists(self):
        conn = sqlite3.connect('/app/output/results.db')
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cavitation'")
        assert cur.fetchone() is not None, "Table 'cavitation' missing"
        conn.close()

    def test_cavitation_row_count(self):
        conn = sqlite3.connect('/app/output/results.db')
        cur = conn.execute("SELECT COUNT(*) FROM cavitation")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 1, f"cavitation has {count} rows, expected 1"

    def test_cavitation_columns(self):
        conn = sqlite3.connect('/app/output/results.db')
        cur = conn.execute("PRAGMA table_info(cavitation)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        required = {'p_atm_Pa', 'p_vapor_Pa', 'sigma_plant',
                     'sigma_critical', 'safety_margin', 'is_safe'}
        missing = required - cols
        assert not missing, f"cavitation missing columns: {missing}"


# ── JSON ↔ SQLite Cross-Consistency ───────────────────────

class TestCrossFormat:
    def test_operating_points_E_consistency(self, sol):
        conn = sqlite3.connect('/app/output/results.db')
        conn.row_factory = sqlite3.Row
        db_rows = conn.execute(
            "SELECT * FROM operating_points ORDER BY point_id").fetchall()
        conn.close()
        json_pts = sorted(sol['points'], key=lambda x: x['point_id'])
        assert len(db_rows) == len(json_pts)
        for db_r, jp in zip(db_rows, json_pts):
            assert db_r['point_id'] == jp['point_id']
            assert _rel(db_r['E_Jkg'], jp['E_Jkg']) < 1e-6, \
                f"Pt {jp['point_id']}: DB E_Jkg != JSON E_Jkg"

    def test_operating_points_eta_consistency(self, sol):
        conn = sqlite3.connect('/app/output/results.db')
        conn.row_factory = sqlite3.Row
        db_rows = conn.execute(
            "SELECT * FROM operating_points ORDER BY point_id").fetchall()
        conn.close()
        json_pts = sorted(sol['points'], key=lambda x: x['point_id'])
        for db_r, jp in zip(db_rows, json_pts):
            assert _rel(db_r['eta_model'], jp['eta_model']) < 1e-6, \
                f"Pt {jp['point_id']}: DB eta_model != JSON"
            assert _rel(db_r['eta_prototype'], jp['eta_prototype']) < 1e-6, \
                f"Pt {jp['point_id']}: DB eta_prototype != JSON"

    def test_bep_summary_consistency(self, sol):
        conn = sqlite3.connect('/app/output/results.db')
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM bep_summary").fetchone()
        conn.close()
        assert row['point_id'] == sol['bep']['point_id']
        assert _rel(row['eta_prototype'], sol['bep']['eta_prototype']) < 1e-6
        assert _rel(row['Q_m3s'], sol['prototype_bep']['Q_m3s']) < 1e-6
        assert _rel(row['P_MW'], sol['prototype_bep']['P_MW']) < 1e-6

    def test_cavitation_consistency(self, sol):
        conn = sqlite3.connect('/app/output/results.db')
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM cavitation").fetchone()
        conn.close()
        assert _rel(row['sigma_plant'], sol['cavitation']['sigma_plant']) < 1e-6
        assert _rel(row['safety_margin'], sol['cavitation']['safety_margin']) < 1e-6
        expected_safe = 1 if sol['cavitation']['is_safe'] else 0
        assert row['is_safe'] == expected_safe, \
            f"DB is_safe={row['is_safe']} vs JSON is_safe={sol['cavitation']['is_safe']}"
