"""Tests for the systematic trading backtest system."""

import pytest
import pandas as pd
import numpy as np
import json
import os
import sqlite3

INSTRUMENTS = ['BOND', 'EQUITY', 'COMMODITY']
RULES = ['ewmac16_64', 'ewmac32_128', 'ewmac64_256', 'carry']
DB = '/app/market.db'


def _prices(instr):
    c = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, price FROM prices WHERE instrument=? ORDER BY date",
        c, params=(instr,), parse_dates=['date'])
    c.close()
    return df.set_index('date')['price']


def _carry(instr):
    c = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, price, carry_price FROM carry_prices WHERE instrument=? ORDER BY date",
        c, params=(instr,), parse_dates=['date'])
    c.close()
    return df.set_index('date')


def _fx(pair):
    c = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, rate FROM fx_rates WHERE pair=? ORDER BY date",
        c, params=(pair,), parse_dates=['date'])
    c.close()
    return df.set_index('date')['rate']


def _rv(ch, d=35, sy=10, ps=0.3):
    f = ch.ewm(span=d, min_periods=d).std()
    sd = int(sy * 252)
    s = ch.rolling(sd, min_periods=d).std()
    return f * (1.0 - ps) + s * ps


@pytest.fixture(scope='session')
def diag():
    with open('/app/output/diagnostics.json') as f:
        return json.load(f)


@pytest.fixture(scope='session')
def pos():
    return pd.read_csv('/app/output/positions.csv',
                       parse_dates=['DATETIME'], index_col='DATETIME')


class TestOutputFiles:
    def test_positions(self):
        assert os.path.isfile('/app/output/positions.csv')

    def test_diagnostics(self):
        assert os.path.isfile('/app/output/diagnostics.json')

    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_vol(self, instr):
        assert os.path.isfile(f'/app/output/{instr}_vol.csv')

    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_raw(self, instr):
        assert os.path.isfile(f'/app/output/{instr}_raw_forecasts.csv')

    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_scaled(self, instr):
        assert os.path.isfile(f'/app/output/{instr}_scaled_forecasts.csv')

    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_combined(self, instr):
        assert os.path.isfile(f'/app/output/{instr}_combined_forecast.csv')


class TestVolatility:
    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_positive(self, instr):
        v = pd.read_csv(f'/app/output/{instr}_vol.csv',
                        parse_dates=['DATETIME'], index_col='DATETIME')
        valid = v.dropna()
        assert len(valid) > 0
        assert (valid > 0).all().all()

    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_sufficient(self, instr):
        v = pd.read_csv(f'/app/output/{instr}_vol.csv',
                        parse_dates=['DATETIME'], index_col='DATETIME')
        assert v.dropna().shape[0] > 500

    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_accuracy(self, instr):
        p = _prices(instr)
        ref = _rv(p.diff())
        ag = pd.read_csv(f'/app/output/{instr}_vol.csv',
                         parse_dates=['DATETIME'], index_col='DATETIME').iloc[:, 0]
        common = ref.dropna().index.intersection(ag.dropna().index)
        assert len(common) > 500
        rel = np.abs(ref.loc[common].values - ag.loc[common].values
                     ) / ref.loc[common].abs().values
        assert float(np.median(rel)) < 0.05, \
            f"{instr} vol median rel diff {float(np.median(rel)):.4f}"


class TestForecasts:
    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_rules_present(self, instr):
        raw = pd.read_csv(f'/app/output/{instr}_raw_forecasts.csv',
                          parse_dates=['DATETIME'], index_col='DATETIME')
        for r in RULES:
            assert r in raw.columns, f"{instr} missing {r}"

    def test_ewmac_bond(self):
        p = _prices('BOND')
        v = _rv(p.diff())
        fe = p.ewm(span=32, min_periods=32).mean()
        se = p.ewm(span=128, min_periods=128).mean()
        exp = (fe - se) / v
        raw = pd.read_csv('/app/output/BOND_raw_forecasts.csv',
                          parse_dates=['DATETIME'], index_col='DATETIME')
        ag = raw['ewmac32_128']
        cm = exp.dropna().index.intersection(ag.dropna().index)
        assert len(cm) > 200
        c = float(np.corrcoef(exp.loc[cm].values, ag.loc[cm].values)[0, 1])
        assert c > 0.95, f"EWMAC32_128 corr {c:.4f}"

    def test_ewmac_commodity(self):
        p = _prices('COMMODITY')
        v = _rv(p.diff())
        fe = p.ewm(span=16, min_periods=16).mean()
        se = p.ewm(span=64, min_periods=64).mean()
        exp = (fe - se) / v
        raw = pd.read_csv('/app/output/COMMODITY_raw_forecasts.csv',
                          parse_dates=['DATETIME'], index_col='DATETIME')
        ag = raw['ewmac16_64']
        cm = exp.dropna().index.intersection(ag.dropna().index)
        assert len(cm) > 200
        c = float(np.corrcoef(exp.loc[cm].values, ag.loc[cm].values)[0, 1])
        assert c > 0.95

    def test_carry_direction(self):
        cd = _carry('BOND')
        avg_sp = (cd['carry_price'] - cd['price']).mean()
        raw = pd.read_csv('/app/output/BOND_raw_forecasts.csv',
                          parse_dates=['DATETIME'], index_col='DATETIME')
        cf = raw['carry'].dropna()
        assert len(cf) > 200
        if avg_sp > 0:
            assert cf.mean() > 0, \
                f"Carry spread positive ({avg_sp:.6f}) but forecast mean negative ({cf.mean():.4f})"
        else:
            assert cf.mean() < 0

    def test_carry_smooth(self):
        raw = pd.read_csv('/app/output/BOND_raw_forecasts.csv',
                          parse_dates=['DATETIME'], index_col='DATETIME')
        cf = raw['carry'].dropna()
        assert len(cf) > 200
        ac = float(cf.autocorr(lag=1))
        assert ac > 0.9, f"Carry autocorr {ac:.4f}"

    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_carry_vol_normalization(self, instr):
        """Carry should be normalized by daily vol, not annualized vol.
        If divided by annualized vol (wrong), the raw carry is ~sqrt(252)x
        too small and the scaled forecast mean|fc| will be far below 1.0.
        The carry rule applies EWM smoothing (span=90), so the reference
        must also be smoothed to allow meaningful structural comparison."""
        p = _prices(instr)
        cd = _carry(instr)
        v = _rv(p.diff())
        spread = cd['carry_price'] - cd['price']
        common = spread.dropna().index.intersection(v.dropna().index)
        ref_raw = (spread.loc[common] / v.loc[common]).ewm(
            span=90, min_periods=90).mean().dropna()
        raw = pd.read_csv(f'/app/output/{instr}_raw_forecasts.csv',
                          parse_dates=['DATETIME'], index_col='DATETIME')
        if 'carry' not in raw.columns:
            pytest.skip(f"No carry for {instr}")
        ag_carry = raw['carry'].dropna()
        cm = ref_raw.index.intersection(ag_carry.index)
        if len(cm) < 200:
            pytest.skip("Insufficient overlap")
        corr = float(np.corrcoef(ref_raw.loc[cm].values,
                                  ag_carry.loc[cm].values)[0, 1])
        assert corr > 0.90, \
            f"{instr} carry correlation with daily-vol-normalized ref = {corr:.4f}"
        slope = float(np.polyfit(ref_raw.loc[cm].values,
                                  ag_carry.loc[cm].values, 1)[0])
        assert 0.3 < slope < 3.0, \
            f"{instr} carry vol normalization slope {slope:.4f}"


class TestScaled:
    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_capped(self, instr):
        df = pd.read_csv(f'/app/output/{instr}_scaled_forecasts.csv',
                         parse_dates=['DATETIME'], index_col='DATETIME')
        for col in RULES:
            if col not in df.columns:
                continue
            v = df[col].dropna()
            assert v.max() <= 20.01, f"{instr} {col} max {v.max():.2f}"
            assert v.min() >= -20.01, f"{instr} {col} min {v.min():.2f}"

    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_carry_scale(self, instr):
        """Verify carry is normalized by daily vol, not annualized.
        With daily-vol normalization and scalar=30, mean|scaled_carry| should
        be roughly 2-8. With annualized-vol normalization, it would be ~0.1-0.5."""
        df = pd.read_csv(f'/app/output/{instr}_scaled_forecasts.csv',
                         parse_dates=['DATETIME'], index_col='DATETIME')
        if 'carry' not in df.columns:
            pytest.skip(f"No carry column for {instr}")
        carry = df['carry'].dropna()
        assert len(carry) > 200
        mean_abs = float(carry.abs().mean())
        assert mean_abs > 1.0, \
            f"{instr} scaled carry mean|fc|={mean_abs:.4f} too low — likely divided by annualized vol"


class TestCombined:
    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_capped(self, instr):
        df = pd.read_csv(f'/app/output/{instr}_combined_forecast.csv',
                         parse_dates=['DATETIME'], index_col='DATETIME')
        v = df.iloc[:, 0].dropna()
        assert v.max() <= 20.01
        assert v.min() >= -20.01

    def test_fdm_range(self, diag):
        for instr in INSTRUMENTS:
            fdm = diag[instr]['fdm']
            assert 1.0 <= fdm <= 2.5, f"{instr} FDM={fdm:.3f}"

    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_fdm_formula(self, instr, diag):
        """FDM must equal 1/sqrt(w'Hw) where H is the correlation matrix
        of scaled forecasts and w are normalized forecast weights."""
        sc = pd.read_csv(f'/app/output/{instr}_scaled_forecasts.csv',
                         parse_dates=['DATETIME'], index_col='DATETIME')
        wt = {'ewmac16_64': 0.21, 'ewmac32_128': 0.08,
              'ewmac64_256': 0.21, 'carry': 0.50}
        cl = sc.dropna()
        if len(cl) < 100:
            pytest.skip("Insufficient data")
        H = cl.corr()
        cols = [c for c in H.columns if c in wt]
        w = np.array([wt[c] for c in cols])
        w = w / w.sum()
        whw = float(w @ H.loc[cols, cols].values @ w)
        exp = min(1.0 / np.sqrt(max(whw, 0.01)), 2.5)
        act = diag[instr]['fdm']
        rd = abs(act - exp) / exp
        assert rd < 0.10, f"{instr} FDM: expected {exp:.3f}, got {act:.3f}"

    def test_weighted_combination(self):
        instr = 'BOND'
        sc = pd.read_csv(f'/app/output/{instr}_scaled_forecasts.csv',
                         parse_dates=['DATETIME'], index_col='DATETIME')
        cb = pd.read_csv(f'/app/output/{instr}_combined_forecast.csv',
                         parse_dates=['DATETIME'], index_col='DATETIME')
        wt = {'ewmac16_64': 0.21, 'ewmac32_128': 0.08,
              'ewmac64_256': 0.21, 'carry': 0.50}
        tw = sum(wt.values())
        cm = sc.dropna().index.intersection(cb.dropna().index)
        assert len(cm) > 200
        ws = sum(sc.loc[cm, r] * (w / tw)
                 for r, w in wt.items() if r in sc.columns)
        c = float(np.corrcoef(ws.values, cb.iloc[:, 0].loc[cm].values)[0, 1])
        assert c > 0.95, f"Weighted sum correlation {c:.4f}"

    def test_carry_weight_dominant(self):
        instr = 'EQUITY'
        sc = pd.read_csv(f'/app/output/{instr}_scaled_forecasts.csv',
                         parse_dates=['DATETIME'], index_col='DATETIME')
        cb = pd.read_csv(f'/app/output/{instr}_combined_forecast.csv',
                         parse_dates=['DATETIME'], index_col='DATETIME')
        cm = sc.dropna().index.intersection(cb.dropna().index)
        if len(cm) < 300:
            pytest.skip("Insufficient data")
        X = sc.loc[cm].values
        y = cb.iloc[:, 0].loc[cm].values
        coeffs = np.linalg.lstsq(X, y, rcond=None)[0]
        total = sum(abs(c) for c in coeffs)
        if total < 0.01:
            pytest.skip("Near-zero coefficients")
        norm = coeffs / total
        ci = list(sc.columns).index('carry')
        assert norm[ci] > 0.35, \
            f"Carry weight {norm[ci]:.3f} too low (expected >0.35)"


class TestPositions:
    def test_all_instruments(self, pos):
        for instr in INSTRUMENTS:
            assert instr in pos.columns

    def test_sufficient_data(self, pos):
        assert pos.dropna().shape[0] > 200

    @pytest.mark.parametrize('instr', INSTRUMENTS)
    def test_proportional(self, instr, pos):
        cb = pd.read_csv(f'/app/output/{instr}_combined_forecast.csv',
                         parse_dates=['DATETIME'], index_col='DATETIME')
        cm = cb.dropna().index.intersection(pos[instr].dropna().index)
        if len(cm) < 100:
            pytest.skip(f"Only {len(cm)} dates")
        c = float(np.corrcoef(cb.iloc[:, 0].loc[cm].values,
                               pos[instr].loc[cm].values)[0, 1])
        assert c > 0.85, f"{instr} pos-forecast corr {c:.4f}"

    def test_sizing_formula(self, diag):
        capital, vt, aa, idm = 500000, 20.0, 10.0, 1.5
        c = sqlite3.connect(DB)
        meta = pd.read_sql_query("SELECT * FROM instruments", c)
        c.close()
        for instr in INSTRUMENTS:
            row = meta[meta['code'] == instr].iloc[0]
            ps = float(row['pointsize'])
            cur = row['currency']
            if cur == 'USD':
                fx = 1.0
            else:
                fx = float(_fx(f'{cur}_USD').iloc[-1])
            d = diag[instr]
            av = d['last_vol'] * np.sqrt(252)
            ivv = av * ps * fx
            vs = (capital * vt / 100.0) / (ivv * aa)
            exp = d['last_combined_forecast'] * vs * d['instrument_weight'] * idm
            if abs(exp) < 0.001:
                continue
            rd = abs(d['last_portfolio_position'] - exp) / abs(exp)
            assert rd < 0.15, \
                f"{instr}: expected {exp:.4f}, got {d['last_portfolio_position']:.4f}"

    def test_equity_fx(self, diag):
        fxs = _fx('EUR_USD')
        lfx = float(fxs.iloc[-1])
        if abs(lfx - 1.0) <= 0.05:
            pytest.skip("EUR/USD too close to 1.0 for FX distinction test")
        d = diag['EQUITY']
        capital, vt, aa, idm = 500000, 20.0, 10.0, 1.5
        ps = 10
        av = d['last_vol'] * np.sqrt(252)
        ivv_fx = av * ps * lfx
        vs_fx = (capital * vt / 100.0) / (ivv_fx * aa)
        pos_fx = d['last_combined_forecast'] * vs_fx * d['instrument_weight'] * idm
        ivv_no = av * ps
        vs_no = (capital * vt / 100.0) / (ivv_no * aa)
        pos_no = d['last_combined_forecast'] * vs_no * d['instrument_weight'] * idm
        actual = d['last_portfolio_position']
        if abs(pos_fx - pos_no) < 0.001:
            pytest.skip("FX difference too small")
        err_fx = abs(actual - pos_fx)
        err_no = abs(actual - pos_no)
        assert err_fx < err_no, \
            f"Position {actual:.2f} closer to no-FX {pos_no:.2f} than FX-adjusted {pos_fx:.2f}"


class TestDiagnostics:
    def test_all_instruments(self, diag):
        for instr in INSTRUMENTS:
            assert instr in diag

    @pytest.mark.parametrize('key', [
        'fdm', 'last_vol', 'last_combined_forecast',
        'last_subsystem_position', 'last_portfolio_position',
        'instrument_weight', 'idm'])
    def test_fields(self, diag, key):
        for instr in INSTRUMENTS:
            assert key in diag[instr], f"{instr} missing {key}"

    def test_vol_bond(self, diag):
        v = diag['BOND']['last_vol']
        assert 0.01 < v < 5.0, f"BOND vol {v}"

    def test_vol_equity(self, diag):
        v = diag['EQUITY']['last_vol']
        assert 1.0 < v < 500.0, f"EQUITY vol {v}"

    def test_vol_commodity(self, diag):
        v = diag['COMMODITY']['last_vol']
        assert 0.01 < v < 50.0, f"COMMODITY vol {v}"

    def test_idm(self, diag):
        for instr in INSTRUMENTS:
            assert abs(diag[instr]['idm'] - 1.5) < 0.01

    def test_weights(self, diag):
        for instr, exp in [('BOND', 0.333), ('EQUITY', 0.333),
                           ('COMMODITY', 0.334)]:
            assert abs(diag[instr]['instrument_weight'] - exp) < 0.01
