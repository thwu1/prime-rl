
import json
import os
import math
import csv
import re
import pytest


class KuRef:
    """Compact reference implementation of Kudryavtsev model for test verification."""

    def __init__(self, params_file):
        self.p = {}
        with open(params_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.p[row['Texture']] = {
                    'BD': float(row['Bulk_Density']),
                    'HC': float(row['Heat_Capacity']),
                    'TCT': float(row['Thermal_Conductivity_Thawed']),
                    'TCF': float(row['Thermal_Conductivity_Frozen']),
                }

    def compute(self, Ta, Aa, Hsn, rho_sn, vwc, pc, ps, pi_, pp, Hvgf, Hvgt, Dvf, Dvt):
        # Step 1: Snow
        Ksn = (rho_sn / 1000.0) ** 2 * 3.233 - 1.01 * (rho_sn / 1000.0) + 0.138
        Csn = 2090.0

        # Step 2: Soil
        P = self.p
        BD = P['Silt']['BD'] * pi_ + P['Sand']['BD'] * ps + P['Clay']['BD'] * pc + P['Peat']['BD'] * pp
        HC = P['Silt']['HC'] * pi_ + P['Sand']['HC'] * ps + P['Clay']['HC'] * pc + P['Peat']['HC'] * pp
        Ct = HC * BD + 4190.0 * vwc
        Cf = HC * BD + 2025.0 * vwc
        Kt_s = P['Silt']['TCT'] ** pi_ * P['Sand']['TCT'] ** ps * P['Clay']['TCT'] ** pc * P['Peat']['TCT'] ** pp
        Kf_s = P['Silt']['TCF'] ** pi_ * P['Sand']['TCF'] ** ps * P['Clay']['TCF'] ** pc * P['Peat']['TCF'] ** pp
        Kt = Kt_s ** (1.0 - vwc) * 0.54 ** vwc
        Kf = Kf_s ** (1.0 - vwc) * 2.35 ** vwc

        # Step 3: Seasons (clamp ratio to avoid math domain error)
        tau = 365.0 * 24.0 * 3600.0
        ta_ratio = max(-1.0 + 1e-12, min(1.0 - 1e-12, Ta / Aa))
        tau1 = tau * (0.5 - math.asin(ta_ratio) / math.pi)
        tau2 = tau - tau1

        # Step 4: Latent heat
        L = 3.34e8 * vwc

        # Step 5: Snow effect
        alpha = Ksn / (rho_sn * Csn)
        dTsn = Aa * (1.0 - math.exp(-Hsn * math.sqrt(math.pi / (tau * alpha))))
        dAsn = 2.0 / math.pi * dTsn
        Tvg = Ta + dTsn
        Avg = Aa - dAsn

        # Step 6: Vegetation effect
        dA1 = 0.0
        if Hvgf > 0 and tau1 > 0:
            dA1 = (Avg - Tvg) * (1.0 - math.exp(-Hvgf * math.sqrt(math.pi / (Dvf * 2.0 * tau1))))
        dA2 = 0.0
        if Hvgt > 0 and tau2 > 0:
            dA2 = (Avg + Tvg) * (1.0 - math.exp(-Hvgt * math.sqrt(math.pi / (Dvt * 2.0 * tau2))))
        dAv = (dA1 * tau1 + dA2 * tau2) / tau
        dTv = (dA1 * tau1 - dA2 * tau2) / tau * (2.0 / math.pi)
        Tgs = Tvg + dTv
        Ags = Avg - dAv

        # Step 7: TTOP (clamp r to avoid math domain error)
        if Ags <= 0:
            Ags = 1e-12
        r = Tgs / Ags
        r_c = max(-1.0 + 1e-12, min(1.0 - 1e-12, r))
        N = 0.5 * Tgs * (Kf + Kt) + Ags * (Kt - Kf) / math.pi * (r_c * math.asin(r_c) + math.sqrt(1.0 - r_c * r_c))
        Kstar = Kf if N <= 0 else Kt
        Tps = N / Kstar

        # Step 8: ALT
        if N > 0:
            return Tps, None, N
        C, K = Cf, Kf
        at = abs(Tps)
        if Ags <= at:
            return Tps, 0.0, N
        LC = L / (2.0 * C)
        Aps = (Ags - at) / math.log((Ags + LC) / (at + LC)) - LC
        s1 = math.sqrt(K * tau * C / math.pi)
        s2 = math.sqrt(K * tau / (math.pi * C))
        Zn = 2.0 * (Ags - at) * s1
        Zd = 2.0 * Aps * C + L
        Zc = Zn / Zd
        inn = (2.0 * Aps * C * Zc + L * Zc) * L * s2
        ind = 2.0 * Ags * C * Zc + L * Zc + Zd * s2
        Zal = (Zn + inn / ind) / Zd
        return Tps, Zal, N


def _load_sites():
    sites = []
    with open('/app/data/sites.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sites.append(row)
    return sites


def _load_targets():
    targets = []
    with open('/app/data/calibration_targets.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            targets.append(row)
    return targets


def _ref():
    return KuRef('/app/data/thermal_params.csv')


def _compute_ref_site(ref, s):
    return ref.compute(
        float(s['Ta']), float(s['Aa']), float(s['Hsn']), float(s['rho_sn']),
        float(s['vwc']), float(s['p_clay']), float(s['p_sand']),
        float(s['p_silt']), float(s['p_peat']),
        float(s['Hvgf']), float(s['Hvgt']), float(s['Dvf']), float(s['Dvt']),
    )


def _parse_borehole_obs():
    """Parse the PANGAEA borehole observation file independently."""
    boreholes = {}
    with open('/app/data/borehole_obs.tsv', encoding='utf-8') as f:
        in_comment = False
        header = None
        for line in f:
            line = line.rstrip('\n')
            if line.startswith('/*'):
                in_comment = True
                continue
            if in_comment:
                if '*/' in line:
                    in_comment = False
                continue
            if header is None:
                header = line.split('\t')
                continue
            fields = line.split('\t')
            event = fields[0]
            year_cols = {}
            for i, col_name in enumerate(header):
                m = re.match(r'MAGT\s*\[.*?\]\s*\((\d{4})\)', col_name)
                if m:
                    year = int(m.group(1))
                    val = fields[i].strip() if i < len(fields) else ''
                    if val != '':
                        year_cols[year] = float(val)
            boreholes[event] = year_cols
    return boreholes


def _ols_trend(year_vals):
    """Compute OLS slope from dict {year: value}. Returns slope per year."""
    if len(year_vals) < 5:
        return None
    years = sorted(year_vals.keys())
    n = len(years)
    x = [float(y) for y in years]
    vals = [year_vals[y] for y in years]
    x_mean = sum(x) / n
    y_mean = sum(vals) / n
    ss_xy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, vals))
    ss_xx = sum((xi - x_mean) ** 2 for xi in x)
    if ss_xx == 0:
        return 0.0
    return ss_xy / ss_xx


def _load_borehole_map():
    mapping = {}
    with open('/app/data/site_borehole_map.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            mapping[row['site_name']] = row['borehole_event']
    return mapping


def _load_param_uncertainties():
    uncertainties = {}
    with open('/app/data/param_uncertainties.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            uncertainties[row['param']] = float(row['abs_std'])
    return uncertainties


def _compute_ref_jacobians(ref, site, uncertainties):
    """Compute reference Jacobians and propagated uncertainties for one site."""
    param_names = sorted(uncertainties.keys())

    base_kw = {
        'Ta': float(site['Ta']), 'Aa': float(site['Aa']),
        'Hsn': float(site['Hsn']), 'rho_sn': float(site['rho_sn']),
        'vwc': float(site['vwc']),
    }
    fixed = [
        float(site['p_clay']), float(site['p_sand']),
        float(site['p_silt']), float(site['p_peat']),
        float(site['Hvgf']), float(site['Hvgt']),
        float(site['Dvf']), float(site['Dvt']),
    ]

    base_Tps, base_ALT, _ = ref.compute(
        base_kw['Ta'], base_kw['Aa'], base_kw['Hsn'],
        base_kw['rho_sn'], base_kw['vwc'], *fixed
    )

    jac_TTOP = {}
    jac_ALT = {}

    for param in param_names:
        p_val = base_kw[param]
        h = max(abs(p_val) * 1e-4, 1e-6)

        plus_kw = dict(base_kw)
        plus_kw[param] = p_val + h
        Tps_p, ALT_p, _ = ref.compute(
            plus_kw['Ta'], plus_kw['Aa'], plus_kw['Hsn'],
            plus_kw['rho_sn'], plus_kw['vwc'], *fixed
        )

        minus_kw = dict(base_kw)
        minus_kw[param] = p_val - h
        Tps_m, ALT_m, _ = ref.compute(
            minus_kw['Ta'], minus_kw['Aa'], minus_kw['Hsn'],
            minus_kw['rho_sn'], minus_kw['vwc'], *fixed
        )

        jac_TTOP[param] = (Tps_p - Tps_m) / (2.0 * h)

        if ALT_p is not None and ALT_m is not None:
            jac_ALT[param] = (ALT_p - ALT_m) / (2.0 * h)
        elif ALT_p is not None and base_ALT is not None:
            jac_ALT[param] = (ALT_p - base_ALT) / h
        elif ALT_m is not None and base_ALT is not None:
            jac_ALT[param] = (base_ALT - ALT_m) / h
        else:
            jac_ALT[param] = 0.0

    sigma_TTOP = math.sqrt(sum(
        (jac_TTOP[p] * uncertainties[p]) ** 2 for p in param_names
    ))
    if base_ALT is not None:
        sigma_ALT = math.sqrt(sum(
            (jac_ALT[p] * uncertainties[p]) ** 2 for p in param_names
        ))
    else:
        sigma_ALT = None

    contributions = {p: abs(jac_TTOP[p] * uncertainties[p]) for p in param_names}
    dominant = max(contributions, key=contributions.get)

    return {
        'jac_TTOP': jac_TTOP,
        'jac_ALT': jac_ALT,
        'sigma_TTOP': sigma_TTOP,
        'sigma_ALT': sigma_ALT,
        'dominant_param': dominant,
        'base_ALT': base_ALT,
    }


# ======================== Forward Tests ========================

class TestForwardStructure:
    def test_output_file_exists(self):
        assert os.path.exists('/app/output/forward_results.json'), \
            "forward_results.json not found"

    def test_valid_json(self):
        with open('/app/output/forward_results.json') as f:
            data = json.load(f)
        assert 'sites' in data, "Missing 'sites' key"

    def test_correct_site_count(self):
        with open('/app/output/forward_results.json') as f:
            data = json.load(f)
        sites = _load_sites()
        assert len(data['sites']) == len(sites), \
            f"Expected {len(sites)} sites, got {len(data['sites'])}"

    def test_required_fields(self):
        with open('/app/output/forward_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            assert 'name' in s, "Missing 'name' field"
            assert 'Tps' in s, f"Missing 'Tps' for {s.get('name')}"
            assert 'ALT' in s, f"Missing 'ALT' for {s.get('name')}"
            assert 'regime' in s, f"Missing 'regime' for {s.get('name')}"
            assert s['regime'] in ('permafrost', 'seasonal_frost'), \
                f"Invalid regime '{s['regime']}' for {s['name']}"


class TestForwardValues:
    def test_ttop_accuracy(self):
        ref = _ref()
        sites = _load_sites()
        with open('/app/output/forward_results.json') as f:
            data = json.load(f)
        result_map = {s['name']: s for s in data['sites']}
        for s in sites:
            name = s['name']
            assert name in result_map, f"Site {name} missing from output"
            ref_Tps, ref_ALT, ref_N = _compute_ref_site(ref, s)
            got_Tps = result_map[name]['Tps']
            assert abs(got_Tps - ref_Tps) < 0.05, \
                f"TTOP mismatch for {name}: got {got_Tps:.4f}, expected {ref_Tps:.4f}"

    def test_alt_accuracy(self):
        ref = _ref()
        sites = _load_sites()
        with open('/app/output/forward_results.json') as f:
            data = json.load(f)
        result_map = {s['name']: s for s in data['sites']}
        for s in sites:
            name = s['name']
            ref_Tps, ref_ALT, ref_N = _compute_ref_site(ref, s)
            got = result_map[name]
            if ref_ALT is None:
                assert got['ALT'] is None, \
                    f"ALT should be null for seasonal frost site {name}"
            else:
                assert got['ALT'] is not None, \
                    f"ALT should not be null for permafrost site {name}"
                assert abs(got['ALT'] - ref_ALT) < 0.005, \
                    f"ALT mismatch for {name}: got {got['ALT']:.4f}, expected {ref_ALT:.4f}"

    def test_regime_classification(self):
        ref = _ref()
        sites = _load_sites()
        with open('/app/output/forward_results.json') as f:
            data = json.load(f)
        result_map = {s['name']: s for s in data['sites']}
        for s in sites:
            name = s['name']
            _, _, ref_N = _compute_ref_site(ref, s)
            expected_regime = 'permafrost' if ref_N <= 0 else 'seasonal_frost'
            assert result_map[name]['regime'] == expected_regime, \
                f"Regime mismatch for {name}: got {result_map[name]['regime']}, expected {expected_regime}"

    def test_seasonal_frost_alt_is_null(self):
        with open('/app/output/forward_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            if s['regime'] == 'seasonal_frost':
                assert s['ALT'] is None, \
                    f"ALT must be null for seasonal frost site {s['name']}"

    def test_permafrost_alt_is_positive(self):
        with open('/app/output/forward_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            if s['regime'] == 'permafrost':
                assert s['ALT'] is not None and s['ALT'] > 0, \
                    f"ALT must be positive for permafrost site {s['name']}"


# ======================== Calibration Tests ========================

class TestCalibrationStructure:
    def test_output_file_exists(self):
        assert os.path.exists('/app/output/calibration_results.json'), \
            "calibration_results.json not found"

    def test_correct_target_count(self):
        targets = _load_targets()
        with open('/app/output/calibration_results.json') as f:
            data = json.load(f)
        assert len(data['sites']) == len(targets), \
            f"Expected {len(targets)} calibration results, got {len(data['sites'])}"

    def test_required_fields(self):
        with open('/app/output/calibration_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            for field in ('name', 'p_clay', 'p_sand', 'p_silt', 'p_peat',
                          'predicted_ALT', 'observed_ALT', 'residual'):
                assert field in s, f"Missing field '{field}' for {s.get('name', '?')}"


class TestCalibrationValues:
    def test_fractions_non_negative(self):
        with open('/app/output/calibration_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            for frac_name in ('p_clay', 'p_sand', 'p_silt', 'p_peat'):
                assert s[frac_name] >= -1e-6, \
                    f"Negative {frac_name}={s[frac_name]} for {s['name']}"

    def test_fractions_sum_to_one(self):
        with open('/app/output/calibration_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            total = s['p_clay'] + s['p_sand'] + s['p_silt'] + s['p_peat']
            assert abs(total - 1.0) < 1e-4, \
                f"Fractions sum to {total} for {s['name']}, expected 1.0"

    def test_residuals_small(self):
        with open('/app/output/calibration_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            assert s['residual'] < 0.01, \
                f"Residual {s['residual']} too large for {s['name']} (must be < 0.01)"

    def test_calibration_reproduces_observed(self):
        """Run reference model with calibrated fractions; check ALT matches observed."""
        ref = _ref()
        targets = _load_targets()
        with open('/app/output/calibration_results.json') as f:
            data = json.load(f)

        target_map = {t['name']: t for t in targets}
        for s in data['sites']:
            t = target_map[s['name']]
            ref_Tps, ref_ALT, ref_N = ref.compute(
                float(t['Ta']), float(t['Aa']), float(t['Hsn']), float(t['rho_sn']),
                float(t['vwc']),
                s['p_clay'], s['p_sand'], s['p_silt'], s['p_peat'],
                float(t['Hvgf']), float(t['Hvgt']), float(t['Dvf']), float(t['Dvt']),
            )
            assert ref_ALT is not None, \
                f"Calibrated fractions give seasonal frost for {s['name']}"
            assert abs(ref_ALT - float(t['observed_ALT'])) < 0.01, \
                f"Reference ALT {ref_ALT:.4f} != observed {t['observed_ALT']} for {s['name']}"


# ======================== Sensitivity Tests ========================

class TestSensitivityStructure:
    def test_output_file_exists(self):
        assert os.path.exists('/app/output/sensitivity_results.json'), \
            "sensitivity_results.json not found"

    def test_only_permafrost_sites(self):
        ref = _ref()
        sites = _load_sites()
        pf_names = set()
        for s in sites:
            _, _, N = _compute_ref_site(ref, s)
            if N <= 0:
                pf_names.add(s['name'])

        with open('/app/output/sensitivity_results.json') as f:
            data = json.load(f)
        result_names = {s['name'] for s in data['sites']}
        assert result_names == pf_names, \
            f"Expected permafrost sites {pf_names}, got {result_names}"

    def test_required_fields(self):
        with open('/app/output/sensitivity_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            assert 'name' in s
            assert 'delta_Ta_critical' in s, f"Missing delta_Ta_critical for {s.get('name')}"
            assert 'current_Tps' in s, f"Missing current_Tps for {s.get('name')}"


class TestSensitivityValues:
    def test_thresholds_positive(self):
        with open('/app/output/sensitivity_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            assert s['delta_Ta_critical'] > 0, \
                f"Non-positive threshold {s['delta_Ta_critical']} for {s['name']}"

    def test_threshold_boundary(self):
        """Verify that at delta-eps the site is still permafrost and at delta+eps it is not."""
        ref = _ref()
        sites = _load_sites()
        site_map = {s['name']: s for s in sites}

        with open('/app/output/sensitivity_results.json') as f:
            data = json.load(f)

        eps = 0.25
        for s in data['sites']:
            site = site_map[s['name']]
            delta = s['delta_Ta_critical']

            # Below threshold: should still be permafrost
            Ta_below = float(site['Ta']) + delta - eps
            _, _, N_below = ref.compute(
                Ta_below, float(site['Aa']), float(site['Hsn']),
                float(site['rho_sn']), float(site['vwc']),
                float(site['p_clay']), float(site['p_sand']),
                float(site['p_silt']), float(site['p_peat']),
                float(site['Hvgf']), float(site['Hvgt']),
                float(site['Dvf']), float(site['Dvt']),
            )

            # Above threshold: should be seasonal frost
            Ta_above = float(site['Ta']) + delta + eps
            _, _, N_above = ref.compute(
                Ta_above, float(site['Aa']), float(site['Hsn']),
                float(site['rho_sn']), float(site['vwc']),
                float(site['p_clay']), float(site['p_sand']),
                float(site['p_silt']), float(site['p_peat']),
                float(site['Hvgf']), float(site['Hvgt']),
                float(site['Dvf']), float(site['Dvt']),
            )

            assert N_below <= 0, \
                f"{s['name']}: should be PF at delta-eps={delta-eps:.2f}, N={N_below:.4f}"
            assert N_above > 0, \
                f"{s['name']}: should be SF at delta+eps={delta+eps:.2f}, N={N_above:.4f}"

    def test_current_tps_consistency(self):
        """Check current_Tps matches forward results."""
        with open('/app/output/forward_results.json') as f:
            fwd = json.load(f)
        with open('/app/output/sensitivity_results.json') as f:
            sens = json.load(f)

        fwd_map = {s['name']: s['Tps'] for s in fwd['sites']}
        for s in sens['sites']:
            assert abs(s['current_Tps'] - fwd_map[s['name']]) < 0.05, \
                f"current_Tps mismatch for {s['name']}"


# ======================== Projection Tests ========================

class TestProjectionStructure:
    def test_output_file_exists(self):
        assert os.path.exists('/app/output/projection_results.json'), \
            "projection_results.json not found"

    def test_valid_json(self):
        with open('/app/output/projection_results.json') as f:
            data = json.load(f)
        assert 'sites' in data, "Missing 'sites' key"

    def test_correct_site_count(self):
        mapping = _load_borehole_map()
        with open('/app/output/projection_results.json') as f:
            data = json.load(f)
        assert len(data['sites']) == len(mapping), \
            f"Expected {len(mapping)} projection results, got {len(data['sites'])}"

    def test_only_mapped_sites(self):
        mapping = _load_borehole_map()
        with open('/app/output/projection_results.json') as f:
            data = json.load(f)
        result_names = {s['name'] for s in data['sites']}
        expected_names = set(mapping.keys())
        assert result_names == expected_names, \
            f"Expected sites {expected_names}, got {result_names}"

    def test_required_fields(self):
        with open('/app/output/projection_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            for field in ('name', 'borehole_id', 'warming_trend_decade',
                          'delta_Ta_critical', 'years_to_loss'):
                assert field in s, f"Missing field '{field}' for {s.get('name', '?')}"

    def test_borehole_ids_match_mapping(self):
        mapping = _load_borehole_map()
        with open('/app/output/projection_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            expected_id = mapping[s['name']]
            assert s['borehole_id'] == expected_id, \
                f"Borehole ID mismatch for {s['name']}: got {s['borehole_id']}, expected {expected_id}"


class TestProjectionValues:
    def test_warming_trends_accuracy(self):
        """Verify warming trends against reference OLS computation."""
        boreholes = _parse_borehole_obs()
        mapping = _load_borehole_map()
        with open('/app/output/projection_results.json') as f:
            data = json.load(f)

        result_map = {s['name']: s for s in data['sites']}
        for site_name, bh_event in mapping.items():
            year_vals = boreholes.get(bh_event, {})
            ref_slope = _ols_trend(year_vals)
            got = result_map[site_name]

            if ref_slope is None:
                assert got['warming_trend_decade'] is None, \
                    f"Expected null trend for {site_name} (< 5 valid measurements)"
            else:
                ref_trend_decade = ref_slope * 10.0
                assert got['warming_trend_decade'] is not None, \
                    f"Expected non-null trend for {site_name}"
                assert abs(got['warming_trend_decade'] - ref_trend_decade) < 0.01, \
                    f"Trend mismatch for {site_name}: got {got['warming_trend_decade']:.4f}, " \
                    f"expected {ref_trend_decade:.4f}"

    def test_insufficient_data_gives_null(self):
        """Boreholes with < 5 valid measurements must produce null trend and years_to_loss."""
        boreholes = _parse_borehole_obs()
        mapping = _load_borehole_map()
        with open('/app/output/projection_results.json') as f:
            data = json.load(f)

        result_map = {s['name']: s for s in data['sites']}
        for site_name, bh_event in mapping.items():
            year_vals = boreholes.get(bh_event, {})
            if len(year_vals) < 5:
                got = result_map[site_name]
                assert got['warming_trend_decade'] is None, \
                    f"{site_name}: expected null trend (only {len(year_vals)} valid measurements)"
                assert got['years_to_loss'] is None, \
                    f"{site_name}: expected null years_to_loss when trend is null"

    def test_seasonal_frost_gives_null_delta(self):
        """Seasonal frost sites must have null delta_Ta_critical and years_to_loss."""
        ref = _ref()
        sites = _load_sites()
        site_regimes = {}
        for s in sites:
            _, _, N = _compute_ref_site(ref, s)
            site_regimes[s['name']] = 'permafrost' if N <= 0 else 'seasonal_frost'

        with open('/app/output/projection_results.json') as f:
            data = json.load(f)

        for s in data['sites']:
            if site_regimes.get(s['name']) == 'seasonal_frost':
                assert s['delta_Ta_critical'] is None, \
                    f"{s['name']}: seasonal frost must have null delta_Ta_critical"
                assert s['years_to_loss'] is None, \
                    f"{s['name']}: seasonal frost must have null years_to_loss"

    def test_years_to_loss_computation(self):
        """Verify years_to_loss = delta_Ta_critical / trend_per_year for valid permafrost sites."""
        boreholes = _parse_borehole_obs()
        mapping = _load_borehole_map()
        ref = _ref()
        sites = _load_sites()
        site_regimes = {}
        for s in sites:
            _, _, N = _compute_ref_site(ref, s)
            site_regimes[s['name']] = 'permafrost' if N <= 0 else 'seasonal_frost'

        with open('/app/output/projection_results.json') as f:
            data = json.load(f)
        with open('/app/output/sensitivity_results.json') as f:
            sens = json.load(f)

        sens_map = {s['name']: s['delta_Ta_critical'] for s in sens['sites']}
        result_map = {s['name']: s for s in data['sites']}

        for site_name, bh_event in mapping.items():
            year_vals = boreholes.get(bh_event, {})
            ref_slope = _ols_trend(year_vals)
            got = result_map[site_name]
            regime = site_regimes.get(site_name, 'seasonal_frost')

            if regime == 'permafrost' and ref_slope is not None and ref_slope > 0:
                delta_crit = sens_map.get(site_name)
                if delta_crit is not None:
                    expected_years = delta_crit / ref_slope
                    assert got['years_to_loss'] is not None, \
                        f"{site_name}: expected non-null years_to_loss"
                    assert abs(got['years_to_loss'] - expected_years) < 1.0, \
                        f"{site_name}: years_to_loss mismatch: got {got['years_to_loss']:.1f}, " \
                        f"expected {expected_years:.1f}"

    def test_permafrost_delta_matches_sensitivity(self):
        """Verify delta_Ta_critical in projection matches sensitivity output."""
        with open('/app/output/sensitivity_results.json') as f:
            sens = json.load(f)
        with open('/app/output/projection_results.json') as f:
            proj = json.load(f)

        sens_map = {s['name']: s['delta_Ta_critical'] for s in sens['sites']}
        for s in proj['sites']:
            if s['delta_Ta_critical'] is not None:
                expected = sens_map.get(s['name'])
                assert expected is not None, \
                    f"{s['name']}: has delta_Ta_critical but not in sensitivity results"
                assert abs(s['delta_Ta_critical'] - expected) < 0.02, \
                    f"{s['name']}: delta_Ta_critical mismatch: " \
                    f"got {s['delta_Ta_critical']:.4f}, expected {expected:.4f}"

    def test_positive_trends_all_warming(self):
        """All boreholes with sufficient data should show warming (positive trend)."""
        with open('/app/output/projection_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            if s['warming_trend_decade'] is not None:
                assert s['warming_trend_decade'] > 0, \
                    f"{s['name']}: expected positive warming trend, got {s['warming_trend_decade']}"


# ======================== Uncertainty Tests ========================

class TestUncertaintyStructure:
    def test_output_file_exists(self):
        assert os.path.exists('/app/output/uncertainty_results.json'), \
            "uncertainty_results.json not found"

    def test_valid_json(self):
        with open('/app/output/uncertainty_results.json') as f:
            data = json.load(f)
        assert 'sites' in data, "Missing 'sites' key"

    def test_only_permafrost_sites(self):
        ref = _ref()
        sites = _load_sites()
        pf_names = set()
        for s in sites:
            _, _, N = _compute_ref_site(ref, s)
            if N <= 0:
                pf_names.add(s['name'])

        with open('/app/output/uncertainty_results.json') as f:
            data = json.load(f)
        result_names = {s['name'] for s in data['sites']}
        assert result_names == pf_names, \
            f"Expected permafrost sites {pf_names}, got {result_names}"

    def test_required_fields(self):
        with open('/app/output/uncertainty_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            for field in ('name', 'sigma_TTOP', 'sigma_ALT', 'dominant_param',
                          'vulnerability_index', 'jacobian_TTOP', 'jacobian_ALT'):
                assert field in s, f"Missing field '{field}' for {s.get('name', '?')}"

    def test_jacobian_keys(self):
        """Each Jacobian dict must contain entries for all uncertain parameters."""
        uncertainties = _load_param_uncertainties()
        param_names = sorted(uncertainties.keys())
        with open('/app/output/uncertainty_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            for p in param_names:
                assert p in s['jacobian_TTOP'], \
                    f"Missing '{p}' in jacobian_TTOP for {s['name']}"
                assert p in s['jacobian_ALT'], \
                    f"Missing '{p}' in jacobian_ALT for {s['name']}"


class TestUncertaintyValues:
    def test_sigma_ttop_accuracy(self):
        """Verify propagated TTOP uncertainty against reference computation."""
        ref = _ref()
        sites = _load_sites()
        uncertainties = _load_param_uncertainties()
        with open('/app/output/uncertainty_results.json') as f:
            data = json.load(f)

        result_map = {s['name']: s for s in data['sites']}
        for s in sites:
            name = s['name']
            if name not in result_map:
                continue
            ref_result = _compute_ref_jacobians(ref, s, uncertainties)
            got = result_map[name]['sigma_TTOP']
            expected = ref_result['sigma_TTOP']
            tol = max(0.005, abs(expected) * 0.05)
            assert abs(got - expected) < tol, \
                f"sigma_TTOP mismatch for {name}: got {got:.6f}, expected {expected:.6f}"

    def test_sigma_alt_accuracy(self):
        """Verify propagated ALT uncertainty against reference computation."""
        ref = _ref()
        sites = _load_sites()
        uncertainties = _load_param_uncertainties()
        with open('/app/output/uncertainty_results.json') as f:
            data = json.load(f)

        result_map = {s['name']: s for s in data['sites']}
        for s in sites:
            name = s['name']
            if name not in result_map:
                continue
            ref_result = _compute_ref_jacobians(ref, s, uncertainties)
            got = result_map[name]
            if ref_result['sigma_ALT'] is None:
                assert got['sigma_ALT'] is None, \
                    f"Expected null sigma_ALT for {name}"
            else:
                assert got['sigma_ALT'] is not None, \
                    f"Expected non-null sigma_ALT for {name}"
                tol = max(0.005, abs(ref_result['sigma_ALT']) * 0.05)
                assert abs(got['sigma_ALT'] - ref_result['sigma_ALT']) < tol, \
                    f"sigma_ALT mismatch for {name}: got {got['sigma_ALT']:.6f}, " \
                    f"expected {ref_result['sigma_ALT']:.6f}"

    def test_dominant_param(self):
        """Verify the dominant uncertainty contributor matches reference."""
        ref = _ref()
        sites = _load_sites()
        uncertainties = _load_param_uncertainties()
        with open('/app/output/uncertainty_results.json') as f:
            data = json.load(f)

        result_map = {s['name']: s for s in data['sites']}
        for s in sites:
            name = s['name']
            if name not in result_map:
                continue
            ref_result = _compute_ref_jacobians(ref, s, uncertainties)
            assert result_map[name]['dominant_param'] == ref_result['dominant_param'], \
                f"Dominant param mismatch for {name}: got {result_map[name]['dominant_param']}, " \
                f"expected {ref_result['dominant_param']}"

    def test_vulnerability_index_consistency(self):
        """Verify vulnerability_index = sigma_TTOP / delta_Ta_critical."""
        with open('/app/output/uncertainty_results.json') as f:
            unc = json.load(f)
        with open('/app/output/sensitivity_results.json') as f:
            sens = json.load(f)

        sens_map = {s['name']: s['delta_Ta_critical'] for s in sens['sites']}
        for s in unc['sites']:
            delta_crit = sens_map[s['name']]
            expected = s['sigma_TTOP'] / delta_crit
            assert abs(s['vulnerability_index'] - expected) < 0.01, \
                f"Vulnerability index mismatch for {s['name']}: " \
                f"got {s['vulnerability_index']:.6f}, expected {expected:.6f}"

    def test_jacobian_ttop_accuracy(self):
        """Verify individual TTOP Jacobian entries against reference."""
        ref = _ref()
        sites = _load_sites()
        uncertainties = _load_param_uncertainties()
        param_names = sorted(uncertainties.keys())
        with open('/app/output/uncertainty_results.json') as f:
            data = json.load(f)

        result_map = {s['name']: s for s in data['sites']}
        for s in sites:
            name = s['name']
            if name not in result_map:
                continue
            ref_result = _compute_ref_jacobians(ref, s, uncertainties)
            for p in param_names:
                got = result_map[name]['jacobian_TTOP'][p]
                expected = ref_result['jac_TTOP'][p]
                tol = max(1e-4, abs(expected) * 0.02)
                assert abs(got - expected) < tol, \
                    f"Jacobian TTOP[{p}] mismatch for {name}: " \
                    f"got {got:.8f}, expected {expected:.8f}"

    def test_jacobian_alt_values(self):
        """Verify individual ALT Jacobian entries against reference."""
        ref = _ref()
        sites = _load_sites()
        uncertainties = _load_param_uncertainties()
        param_names = sorted(uncertainties.keys())
        with open('/app/output/uncertainty_results.json') as f:
            data = json.load(f)

        result_map = {s['name']: s for s in data['sites']}
        for s in sites:
            name = s['name']
            if name not in result_map:
                continue
            ref_result = _compute_ref_jacobians(ref, s, uncertainties)
            for p in param_names:
                got = result_map[name]['jacobian_ALT'][p]
                expected = ref_result['jac_ALT'][p]
                tol = max(1e-4, abs(expected) * 0.05)
                assert abs(got - expected) < tol, \
                    f"Jacobian ALT[{p}] mismatch for {name}: " \
                    f"got {got:.8f}, expected {expected:.8f}"

    def test_sigma_ttop_positive(self):
        """Propagated TTOP uncertainty must be positive for all sites."""
        with open('/app/output/uncertainty_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            assert s['sigma_TTOP'] > 0, \
                f"sigma_TTOP should be positive for {s['name']}"

    def test_vulnerability_positive(self):
        """Vulnerability index must be positive for all permafrost sites."""
        with open('/app/output/uncertainty_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            assert s['vulnerability_index'] > 0, \
                f"vulnerability_index should be positive for {s['name']}"

    def test_dominant_param_is_valid(self):
        """Dominant parameter must be one of the uncertain parameters."""
        uncertainties = _load_param_uncertainties()
        valid_params = set(uncertainties.keys())
        with open('/app/output/uncertainty_results.json') as f:
            data = json.load(f)
        for s in data['sites']:
            assert s['dominant_param'] in valid_params, \
                f"Invalid dominant_param '{s['dominant_param']}' for {s['name']}"
