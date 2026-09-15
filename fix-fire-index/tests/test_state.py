"""Verification tests for CFFWIS bug fixes and extreme value analysis pipeline.

Tests independently verify:
1. CFFWIS function correctness (bugs fixed)
2. FWI output structure and representative values
3. Results JSON structure and physical bounds
4. GEV fitting self-consistency
5. Verification metric validity and skill
"""

import csv
import importlib.util
import json
import math
import os

import pytest


# =========================================================================
# Reference CFFWIS implementations (correct equations)
# =========================================================================

REF_DAY_LENGTHS = [
    [11.5, 10.5, 9.2, 7.9, 6.8, 6.2, 6.5, 7.4, 8.7, 10.0, 11.2, 11.8],
    [10.1, 9.6, 9.1, 8.5, 8.1, 7.8, 7.9, 8.3, 8.9, 9.4, 9.9, 10.2],
    [9.0] * 12,
    [7.9, 8.4, 8.9, 9.5, 9.9, 10.2, 10.1, 9.7, 9.1, 8.6, 8.1, 7.8],
    [6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0],
]

REF_DAY_LENGTH_FACTORS = [
    [6.4, 5.0, 2.4, 0.4, -1.6, -1.6, -1.6, -1.6, -1.6, 0.9, 3.8, 5.8],
    [1.39] * 12,
    [-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6],
]


def ref_day_length(lat, month):
    if -30 > lat >= -90:
        return REF_DAY_LENGTHS[0][month - 1]
    elif -15 > lat >= -30:
        return REF_DAY_LENGTHS[1][month - 1]
    elif 15 > lat >= -15:
        return 9.0
    elif 30 > lat >= 15:
        return REF_DAY_LENGTHS[3][month - 1]
    elif 90 >= lat >= 30:
        return REF_DAY_LENGTHS[4][month - 1]
    raise ValueError(f"Invalid latitude: {lat}")


def ref_day_length_factor(lat, month):
    if -15 > lat >= -90:
        return REF_DAY_LENGTH_FACTORS[0][month - 1]
    elif 15 > lat >= -15:
        return 1.39
    elif 90 >= lat >= 15:
        return REF_DAY_LENGTH_FACTORS[2][month - 1]
    raise ValueError(f"Invalid latitude: {lat}")


def ref_ffmc(t, p, w, h, ffmc0):
    """Reference FFMC (Eqs. 1-10)."""
    mo = (147.2 * (101.0 - ffmc0)) / (59.5 + ffmc0)
    if p > 0.5:
        rf = p - 0.5
        if mo > 150.0:
            mo = (mo + 42.5 * rf * math.exp(-100.0 / (251.0 - mo)) *
                  (1.0 - math.exp(-6.93 / rf)) +
                  0.0015 * (mo - 150.0) ** 2 * math.sqrt(rf))
        else:
            mo = (mo + 42.5 * rf * math.exp(-100.0 / (251.0 - mo)) *
                  (1.0 - math.exp(-6.93 / rf)))
        mo = min(mo, 250.0)
    ed = (0.942 * h ** 0.679 + 11.0 * math.exp((h - 100.0) / 10.0) +
          0.18 * (21.1 - t) * (1.0 - 1.0 / math.exp(0.1150 * h)))
    if mo < ed:
        ew = (0.618 * h ** 0.753 + 10.0 * math.exp((h - 100.0) / 10.0) +
              0.18 * (21.1 - t) * (1.0 - 1.0 / math.exp(0.115 * h)))
        if mo < ew:
            kl = (0.424 * (1.0 - ((100.0 - h) / 100.0) ** 1.7) +
                  0.0694 * math.sqrt(w) * (1.0 - ((100.0 - h) / 100.0) ** 8))
            kw = kl * 0.581 * math.exp(0.0365 * t)
            m = ew - (ew - mo) / 10.0 ** kw
        else:
            m = mo
    elif mo == ed:
        m = mo
    else:
        kl = (0.424 * (1.0 - (h / 100.0) ** 1.7) +
              0.0694 * math.sqrt(w) * (1.0 - (h / 100.0) ** 8))
        kw = kl * 0.581 * math.exp(0.0365 * t)
        m = ed + (mo - ed) / 10.0 ** kw
    ffmc = (59.5 * (250.0 - m)) / (147.2 + m)
    return max(0.0, min(101.0, ffmc))


def ref_dmc(t, p, h, month, lat, dmc0):
    """Reference DMC (Eqs. 11-17). Uses natural log in Eq.15."""
    if math.isnan(dmc0):
        return float('nan')
    dl = ref_day_length(lat, month)
    if t < -1.1:
        rk = 0.0
    else:
        rk = 1.894 * (t + 1.1) * (100.0 - h) * dl * 0.0001
    if p > 1.5:
        ra = p
        rw = 0.92 * ra - 1.27
        wmi = 20.0 + 280.0 / math.exp(0.023 * dmc0)
        if dmc0 <= 33.0:
            b = 100.0 / (0.5 + 0.3 * dmc0)
        elif dmc0 <= 65.0:
            b = 14.0 - 1.3 * math.log(dmc0)
        else:
            b = 6.2 * math.log(dmc0) - 17.2
        wmr = wmi + (1000.0 * rw) / (48.77 + b * rw)
        pr_val = 43.43 * (5.6348 - math.log(wmr - 20.0))
    else:
        pr_val = dmc0
    pr_val = max(pr_val, 0.0)
    dmc = pr_val + rk
    return max(dmc, 0.0)


def ref_dc(t, p, month, lat, dc0):
    """Reference DC (Eqs. 18-22). Divisor is 400 in Eq.19."""
    fl = ref_day_length_factor(lat, month)
    t_eff = max(t, -2.8)
    pe = (0.36 * (t_eff + 2.8) + fl) / 2.0
    pe = max(pe, 0.0)
    if p > 2.8:
        ra = p
        rw = 0.83 * ra - 1.27
        smi = 800.0 * math.exp(-dc0 / 400.0)
        dr = dc0 - 400.0 * math.log(1.0 + (3.937 * rw) / smi)
        if dr > 0.0:
            dc = dr + pe
        elif math.isnan(dc0):
            dc = float('nan')
        else:
            dc = pe
    else:
        dc = dc0 + pe
    return dc


def ref_isi(ws, ffmc):
    """Reference ISI (Eqs. 25-26). Wind in km/h, no conversion."""
    mo = 147.2 * (101.0 - ffmc) / (59.5 + ffmc)
    ff = 19.1152 * math.exp(mo * -0.1386) * (1.0 + mo ** 5.31 / 49300000.0)
    return ff * math.exp(0.05039 * ws)


def ref_bui(dmc, dc):
    """Reference BUI (Eq. 27)."""
    if dmc == 0 and dc == 0:
        return 0.0
    if dmc <= 0.4 * dc:
        return (0.8 * dc * dmc) / (dmc + 0.4 * dc)
    else:
        return max(0.0, dmc - (1.0 - 0.8 * dc / (dmc + 0.4 * dc)) *
                   (0.92 + (0.0114 * dmc) ** 1.7))


def ref_fwi(isi, bui):
    """Reference FWI (Eqs. 28-30)."""
    if bui <= 80.0:
        fwi = 0.1 * isi * (0.626 * bui ** 0.809 + 2.0)
    else:
        fwi = 0.1 * isi * (1000.0 / (25.0 + 108.64 / math.exp(0.023 * bui)))
    if fwi > 1.0:
        fwi = math.exp(2.72 * (0.434 * math.log(fwi)) ** 0.647)
    return fwi


def ref_dsr(fwi):
    return 0.0272 * fwi ** 1.77


def ref_fire_season_wf93(temps, start_thresh=12.0, end_thresh=5.0, n_days=3):
    n = len(temps)
    mask = [False] * n
    for i in range(n_days + 1, n):
        window = temps[i - n_days:i]
        start_up = all(t > start_thresh for t in window)
        shut_down = all(t < end_thresh for t in window)
        mask[i] = (mask[i - 1] or start_up) and not shut_down
    return mask


def ref_overwintering_dc(last_dc, winter_precip, a=0.75, b=0.75, min_dc=15.0):
    if math.isnan(last_dc) or math.isnan(winter_precip):
        return float('nan')
    qf = 800.0 * math.exp(-last_dc / 400.0)
    qs = a * qf + b * (3.94 * winter_precip)
    if qs <= 0:
        return min_dc
    dcs = 400.0 * math.log(800.0 / qs)
    return max(dcs, min_dc)


# =========================================================================
# Helpers
# =========================================================================

def load_cffwis_module():
    """Import the agent's cffwis.py from /app/."""
    spec = importlib.util.spec_from_file_location("cffwis", "/app/cffwis.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_csv(filepath):
    data = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = int(row['station_id'])
            if sid not in data:
                data[sid] = []
            data[sid].append(row)
    return data


def parse_float(s):
    if s == '' or s is None:
        return float('nan')
    return float(s)


# =========================================================================
# Test: CFFWIS Function Correctness (Bug Detection)
# =========================================================================

class TestDCFunction:
    """Verify DC uses exp(-dc0/400), not exp(-dc0/4000)."""

    def test_dc_rain_response_high_dc(self):
        """DC at 600 should decrease substantially with 20mm rain."""
        mod = load_cffwis_module()
        result = mod.calc_dc(t=20.0, p=20.0, month=7, lat=45.0, dc0=600.0)
        expected = ref_dc(t=20.0, p=20.0, month=7, lat=45.0, dc0=600.0)
        assert abs(result - expected) < 1.0, \
            f"DC(600, 20mm rain): expected {expected:.1f}, got {result:.1f}. " \
            f"Check Eq.19 divisor (should be 400, not 4000)."

    def test_dc_rain_response_moderate_dc(self):
        """DC at 300 should decrease with 15mm rain."""
        mod = load_cffwis_module()
        result = mod.calc_dc(t=18.0, p=15.0, month=6, lat=55.0, dc0=300.0)
        expected = ref_dc(t=18.0, p=15.0, month=6, lat=55.0, dc0=300.0)
        assert abs(result - expected) < 1.0, \
            f"DC(300, 15mm rain): expected {expected:.1f}, got {result:.1f}"

    def test_dc_no_rain(self):
        """DC without rain should only increase by potential evapotranspiration."""
        mod = load_cffwis_module()
        result = mod.calc_dc(t=25.0, p=0.0, month=7, lat=45.0, dc0=200.0)
        expected = ref_dc(t=25.0, p=0.0, month=7, lat=45.0, dc0=200.0)
        assert abs(result - expected) < 0.01, \
            f"DC dry day: expected {expected:.2f}, got {result:.2f}"


class TestISIFunction:
    """Verify ISI uses wind speed directly in km/h (no /3.6 conversion)."""

    def test_isi_standard_conditions(self):
        """ISI with W=20 km/h, FFMC=85."""
        mod = load_cffwis_module()
        result = mod.calc_isi(ws=20.0, ffmc=85.0)
        expected = ref_isi(ws=20.0, ffmc=85.0)
        assert abs(result - expected) < 0.05, \
            f"ISI(W=20, FFMC=85): expected {expected:.3f}, got {result:.3f}. " \
            f"Check Eq.26 — wind is already in km/h, no /3.6 conversion."

    def test_isi_high_wind(self):
        """ISI sensitivity to wind should match reference at W=30 km/h."""
        mod = load_cffwis_module()
        result = mod.calc_isi(ws=30.0, ffmc=90.0)
        expected = ref_isi(ws=30.0, ffmc=90.0)
        assert abs(result - expected) < 0.1, \
            f"ISI(W=30, FFMC=90): expected {expected:.3f}, got {result:.3f}"

    def test_isi_wind_ratio(self):
        """ISI ratio between W=20 and W=10 should be exp(0.05039*10) ≈ 1.655."""
        mod = load_cffwis_module()
        isi_20 = mod.calc_isi(ws=20.0, ffmc=85.0)
        isi_10 = mod.calc_isi(ws=10.0, ffmc=85.0)
        ratio = isi_20 / isi_10 if isi_10 > 0 else float('inf')
        expected_ratio = math.exp(0.05039 * 10.0)
        assert abs(ratio - expected_ratio) < 0.01, \
            f"ISI wind ratio: expected {expected_ratio:.3f}, got {ratio:.3f}"


class TestDMCFunction:
    """Verify DMC Eq.15 uses natural log, not log10."""

    def test_dmc_rain_effect(self):
        """DMC with moderate rain should match natural-log computation."""
        mod = load_cffwis_module()
        result = mod.calc_dmc(t=20.0, p=10.0, h=60.0, month=6,
                              lat=45.0, dmc0=50.0)
        expected = ref_dmc(t=20.0, p=10.0, h=60.0, month=6,
                           lat=45.0, dmc0=50.0)
        assert abs(result - expected) < 0.5, \
            f"DMC(rain=10mm, dmc0=50): expected {expected:.2f}, got {result:.2f}. " \
            f"Check Eq.15 — should use ln (natural log), not log10."

    def test_dmc_heavy_rain(self):
        """DMC after heavy rain (25mm) starting from dmc0=80."""
        mod = load_cffwis_module()
        result = mod.calc_dmc(t=22.0, p=25.0, h=55.0, month=7,
                              lat=55.0, dmc0=80.0)
        expected = ref_dmc(t=22.0, p=25.0, h=55.0, month=7,
                           lat=55.0, dmc0=80.0)
        assert abs(result - expected) < 0.5, \
            f"DMC(rain=25mm, dmc0=80): expected {expected:.2f}, got {result:.2f}"

    def test_dmc_no_rain(self):
        """DMC without rain should only increase by drying rate."""
        mod = load_cffwis_module()
        result = mod.calc_dmc(t=25.0, p=0.0, h=50.0, month=7,
                              lat=45.0, dmc0=30.0)
        expected = ref_dmc(t=25.0, p=0.0, h=50.0, month=7,
                           lat=45.0, dmc0=30.0)
        assert abs(result - expected) < 0.01, \
            f"DMC dry day: expected {expected:.2f}, got {result:.2f}"


class TestOtherFunctions:
    """Verify non-buggy functions are correct."""

    def test_ffmc(self):
        mod = load_cffwis_module()
        result = mod.calc_ffmc(t=20.0, p=2.0, w=15.0, h=60.0, ffmc0=85.0)
        expected = ref_ffmc(t=20.0, p=2.0, w=15.0, h=60.0, ffmc0=85.0)
        assert abs(result - expected) < 0.01

    def test_bui(self):
        mod = load_cffwis_module()
        result = mod.calc_bui(dmc=30.0, dc=200.0)
        expected = ref_bui(dmc=30.0, dc=200.0)
        assert abs(result - expected) < 0.01

    def test_fwi(self):
        mod = load_cffwis_module()
        result = mod.calc_fwi(isi=5.0, bui=50.0)
        expected = ref_fwi(isi=5.0, bui=50.0)
        assert abs(result - expected) < 0.01

    def test_overwintering(self):
        mod = load_cffwis_module()
        result = mod.overwintering_dc(100.0, 30.0)
        expected = ref_overwintering_dc(100.0, 30.0)
        assert abs(result - expected) < 0.5


# =========================================================================
# Test: FWI Output Structure and Correctness
# =========================================================================

class TestFWIOutput:
    """Verify fwi_output.csv exists with correct structure and values."""

    def test_output_exists(self):
        assert os.path.exists('/app/fwi_output.csv'), \
            "fwi_output.csv not found"

    def test_output_columns(self):
        with open('/app/fwi_output.csv') as f:
            reader = csv.DictReader(f)
            expected = {'date', 'station_id', 'DC', 'DMC', 'FFMC',
                        'ISI', 'BUI', 'FWI', 'DSR', 'season_mask'}
            assert set(reader.fieldnames) == expected

    def test_all_stations_present(self):
        output = load_csv('/app/fwi_output.csv')
        assert set(output.keys()) == {0, 1, 2, 3, 4}

    def test_station_row_count(self):
        """Each station should have ~10957 rows (30 years)."""
        output = load_csv('/app/fwi_output.csv')
        for sid in output:
            n = len(output[sid])
            assert 10950 <= n <= 10970, \
                f"Station {sid}: expected ~10957 rows, got {n}"

    def test_fwi_first_season_correctness(self):
        """Recompute first 10 fire season days for station 0."""
        inp = load_csv('/app/weather_data.csv')
        out = load_csv('/app/fwi_output.csv')

        station = 0
        in_rows = inp[station]
        out_rows = out[station]

        first_season = None
        for i, row in enumerate(out_rows):
            if int(row['season_mask']) == 1:
                first_season = i
                break
        assert first_season is not None, "No fire season found for station 0"

        ffmc, dmc, dc = 85.0, 6.0, 15.0
        lat = float(in_rows[0]['lat'])
        n_checked = 0

        for i in range(first_season, min(first_season + 10, len(in_rows))):
            if int(out_rows[i]['season_mask']) != 1:
                break
            t = float(in_rows[i]['tas_degC'])
            p = float(in_rows[i]['pr_mm'])
            w = float(in_rows[i]['sfcWind_kmh'])
            h = float(in_rows[i]['hurs_pct'])
            month = int(in_rows[i]['date'].split('-')[1])

            ffmc = ref_ffmc(t, p, w, h, ffmc)
            dmc = ref_dmc(t, p, h, month, lat, dmc)
            dc = ref_dc(t, p, month, lat, dc)
            isi = ref_isi(w, ffmc)
            bui = ref_bui(dmc, dc)
            fwi = ref_fwi(isi, bui)

            out_fwi = parse_float(out_rows[i]['FWI'])
            assert abs(fwi - out_fwi) < 0.1, \
                f"FWI mismatch at day {i}: expected {fwi:.3f}, got {out_fwi:.3f}"
            n_checked += 1

        assert n_checked >= 5, f"Only checked {n_checked} days"

    def test_nan_outside_season(self):
        """Indices should be empty outside fire season."""
        out = load_csv('/app/fwi_output.csv')
        codes = ['FFMC', 'DMC', 'DC', 'ISI', 'BUI', 'FWI', 'DSR']
        for sid in [0, 1]:
            out_rows = out[sid]
            for i in range(len(out_rows)):
                if int(out_rows[i]['season_mask']) == 0:
                    for code in codes:
                        val = out_rows[i][code]
                        assert val == '' or math.isnan(float(val)), \
                            f"{code} not empty outside season at station {sid} day {i}"


# =========================================================================
# Test: Results JSON Structure
# =========================================================================

class TestResultsStructure:
    """Verify results.json exists with correct structure."""

    def test_results_exists(self):
        assert os.path.exists('/app/results.json'), \
            "results.json not found"

    def test_results_top_level(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        assert 'stations' in data, "Missing 'stations' key"
        stations = data['stations']
        expected_ids = {'0', '1', '2', '3', '4'}
        assert set(stations.keys()) == expected_ids, \
            f"Expected station IDs {expected_ids}, got {set(stations.keys())}"

    def test_station_fields(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        required_fields = {'gev_params', 'return_levels',
                           'danger_threshold', 'verification'}
        for sid, sdata in data['stations'].items():
            assert required_fields.issubset(set(sdata.keys())), \
                f"Station {sid} missing fields: " \
                f"{required_fields - set(sdata.keys())}"

    def test_gev_params_fields(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        for sid, sdata in data['stations'].items():
            gev = sdata['gev_params']
            for key in ['shape', 'location', 'scale']:
                assert key in gev, \
                    f"Station {sid} gev_params missing '{key}'"
                assert isinstance(gev[key], (int, float)), \
                    f"Station {sid} gev_params['{key}'] not numeric"

    def test_return_levels_fields(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        for sid, sdata in data['stations'].items():
            rl = sdata['return_levels']
            for key in ['20', '50', '100']:
                assert key in rl, \
                    f"Station {sid} return_levels missing '{key}'"

    def test_verification_fields(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        for sid, sdata in data['stations'].items():
            v = sdata['verification']
            for key in ['hss', 'pod', 'far', 'csi']:
                assert key in v, \
                    f"Station {sid} verification missing '{key}'"


# =========================================================================
# Test: GEV Parameter Physical Bounds
# =========================================================================

class TestGEVParameters:
    """Verify GEV parameters are physically reasonable."""

    def test_scale_positive(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        for sid, sdata in data['stations'].items():
            sigma = sdata['gev_params']['scale']
            assert sigma > 0, \
                f"Station {sid}: GEV scale must be positive, got {sigma}"

    def test_location_positive(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        for sid, sdata in data['stations'].items():
            mu = sdata['gev_params']['location']
            assert mu > 0, \
                f"Station {sid}: GEV location should be positive for FWI maxima, got {mu}"

    def test_shape_bounded(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        for sid, sdata in data['stations'].items():
            xi = sdata['gev_params']['shape']
            assert -2.0 < xi < 2.0, \
                f"Station {sid}: GEV shape {xi} outside reasonable range"

    def test_return_level_ordering(self):
        """Return levels must increase with return period."""
        with open('/app/results.json') as f:
            data = json.load(f)
        for sid, sdata in data['stations'].items():
            rl = sdata['return_levels']
            r20, r50, r100 = float(rl['20']), float(rl['50']), float(rl['100'])
            assert r20 < r50 < r100, \
                f"Station {sid}: return levels not ordered: " \
                f"T20={r20:.1f}, T50={r50:.1f}, T100={r100:.1f}"

    def test_return_levels_positive_finite(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        for sid, sdata in data['stations'].items():
            for t, val in sdata['return_levels'].items():
                v = float(val)
                assert v > 0 and math.isfinite(v), \
                    f"Station {sid}: T{t} return level invalid: {v}"


# =========================================================================
# Test: GEV Self-Consistency
# =========================================================================

class TestGEVConsistency:
    """Verify return levels match GEV quantile function with reported parameters."""

    def test_return_level_gev_consistency(self):
        """Return level for period T should satisfy GEV.isf(1/T, params)."""
        from scipy.stats import genextreme

        with open('/app/results.json') as f:
            data = json.load(f)

        for sid, sdata in data['stations'].items():
            xi = sdata['gev_params']['shape']
            mu = sdata['gev_params']['location']
            sigma = sdata['gev_params']['scale']

            # scipy uses c = -xi (negated shape)
            c = -xi

            for t_str, rl_val in sdata['return_levels'].items():
                T = int(t_str)
                rl = float(rl_val)
                # Return level = quantile at exceedance probability 1/T
                expected_rl = genextreme.isf(1.0 / T, c, loc=mu, scale=sigma)
                tol = max(0.5, abs(expected_rl) * 0.02)
                assert abs(rl - expected_rl) < tol, \
                    f"Station {sid} T{T}: RL={rl:.2f} doesn't match " \
                    f"GEV.isf(1/{T}, c={c:.3f}, mu={mu:.2f}, sigma={sigma:.2f})=" \
                    f"{expected_rl:.2f}"


# =========================================================================
# Test: Verification Metrics
# =========================================================================

class TestVerificationMetrics:
    """Verify verification metrics are in valid ranges and show skill."""

    def test_metric_ranges(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        for sid, sdata in data['stations'].items():
            v = sdata['verification']
            pod = float(v['pod'])
            far = float(v['far'])
            csi = float(v['csi'])
            hss = float(v['hss'])

            assert 0 <= pod <= 1, \
                f"Station {sid}: POD={pod} out of [0,1]"
            assert 0 <= far <= 1, \
                f"Station {sid}: FAR={far} out of [0,1]"
            assert 0 <= csi <= 1, \
                f"Station {sid}: CSI={csi} out of [0,1]"
            assert -1 <= hss <= 1, \
                f"Station {sid}: HSS={hss} out of [-1,1]"

    def test_hss_positive(self):
        """Optimal threshold should produce positive HSS (better than random)."""
        with open('/app/results.json') as f:
            data = json.load(f)
        n_positive = 0
        for sid, sdata in data['stations'].items():
            hss = float(sdata['verification']['hss'])
            if hss > 0:
                n_positive += 1
        assert n_positive >= 3, \
            f"Only {n_positive}/5 stations have HSS>0; expected at least 3"

    def test_danger_threshold_reasonable(self):
        """Danger threshold should be a finite positive FWI value."""
        with open('/app/results.json') as f:
            data = json.load(f)
        for sid, sdata in data['stations'].items():
            thresh = float(sdata['danger_threshold'])
            assert thresh > 0 and math.isfinite(thresh), \
                f"Station {sid}: threshold={thresh} invalid"
            assert thresh < 200, \
                f"Station {sid}: threshold={thresh} unreasonably high"


# =========================================================================
# Test: Independent Verification Metric Recomputation
# =========================================================================

class TestIndependentVerification:
    """Recompute contingency table from raw data and verify reported metrics."""

    def test_recompute_metrics_station0(self):
        """Independently compute CSI and HSS for station 0 at reported threshold."""
        if not os.path.exists('/app/results.json'):
            pytest.skip("results.json not found")
        if not os.path.exists('/app/fwi_output.csv'):
            pytest.skip("fwi_output.csv not found")

        with open('/app/results.json') as f:
            results = json.load(f)

        fwi_out = load_csv('/app/fwi_output.csv')
        fire_data = load_csv('/app/fire_events.csv')

        sid = 0
        threshold = float(results['stations'][str(sid)]['danger_threshold'])
        fwi_rows = fwi_out[sid]
        fire_rows = fire_data[sid]

        tp = fp = fn = tn = 0
        for i in range(len(fwi_rows)):
            if int(fwi_rows[i]['season_mask']) != 1:
                continue
            fwi_val = parse_float(fwi_rows[i]['FWI'])
            if math.isnan(fwi_val):
                continue

            fire = int(fire_rows[i]['fire_occurred'])
            predicted = 1 if fwi_val >= threshold else 0

            if predicted == 1 and fire == 1:
                tp += 1
            elif predicted == 1 and fire == 0:
                fp += 1
            elif predicted == 0 and fire == 1:
                fn += 1
            else:
                tn += 1

        # Compute CSI
        if tp + fn + fp > 0:
            csi = tp / (tp + fn + fp)
        else:
            csi = 0.0

        # Compute HSS
        denom = (tp + fn) * (fn + tn) + (tp + fp) * (fp + tn)
        if denom > 0:
            hss = 2.0 * (tp * tn - fn * fp) / denom
        else:
            hss = 0.0

        reported_csi = float(results['stations'][str(sid)]['verification']['csi'])
        reported_hss = float(results['stations'][str(sid)]['verification']['hss'])

        assert abs(csi - reported_csi) < 0.02, \
            f"Station {sid}: recomputed CSI={csi:.4f}, reported={reported_csi:.4f}"
        assert abs(hss - reported_hss) < 0.02, \
            f"Station {sid}: recomputed HSS={hss:.4f}, reported={reported_hss:.4f}"
