
import json
import os
import pytest
import pandas as pd
import numpy as np

ANALYSIS_PATH = '/app/output/analysis.json'
DATA_DIR = '/fred_data'


@pytest.fixture
def analysis():
    assert os.path.exists(ANALYSIS_PATH), "analysis.json not found at /app/output/analysis.json"
    with open(ANALYSIS_PATH, 'r') as f:
        return json.load(f)


@pytest.fixture
def cpi_data():
    return pd.read_csv(os.path.join(DATA_DIR, 'CPIAUCSL.csv'), parse_dates=['observation_date'])


@pytest.fixture
def fedfunds_data():
    return pd.read_csv(os.path.join(DATA_DIR, 'FEDFUNDS.csv'), parse_dates=['observation_date'])


@pytest.fixture
def unrate_data():
    return pd.read_csv(os.path.join(DATA_DIR, 'UNRATE.csv'), parse_dates=['observation_date'])


class TestJSONStructure:
    def test_file_exists(self):
        assert os.path.exists(ANALYSIS_PATH), "analysis.json not found"

    def test_valid_json(self, analysis):
        assert isinstance(analysis, dict)

    def test_required_keys(self, analysis):
        required = ['sahm_rule', 'output_gap', 'taylor_rule',
                     'yield_curve_inversions', 'real_fed_funds_rate',
                     'monetary_stance']
        for key in required:
            assert key in analysis, f"Missing required key: {key}"

    def test_sahm_rule_structure(self, analysis):
        sahm = analysis['sahm_rule']
        assert 'trigger_dates' in sahm, "sahm_rule missing trigger_dates"
        assert 'indicator' in sahm, "sahm_rule missing indicator"
        assert isinstance(sahm['trigger_dates'], list)
        assert isinstance(sahm['indicator'], dict)
        assert len(sahm['trigger_dates']) > 0, "No Sahm triggers found"
        assert len(sahm['indicator']) > 100, "Too few Sahm indicator months"

    def test_output_gap_structure(self, analysis):
        gap = analysis['output_gap']
        assert gap['lambda'] == 1600, "HP filter lambda must be 1600"
        assert 'values' in gap
        assert isinstance(gap['values'], dict)
        assert len(gap['values']) > 200, "Too few output gap quarters"

    def test_taylor_rule_structure(self, analysis):
        tr = analysis['taylor_rule']
        assert tr['r_star'] == 2.0
        assert tr['pi_star'] == 2.0
        assert 'prescribed_rates' in tr
        assert isinstance(tr['prescribed_rates'], dict)
        assert len(tr['prescribed_rates']) > 500, "Too few Taylor Rule months"

    def test_yield_curve_structure(self, analysis):
        inv = analysis['yield_curve_inversions']
        assert isinstance(inv, list)
        assert len(inv) >= 5, f"Only {len(inv)} inversion episodes found, expected >= 5"
        for ep in inv:
            for key in ['start', 'end', 'duration_days', 'min_spread']:
                assert key in ep, f"Inversion episode missing key: {key}"
            assert ep['duration_days'] >= 5
            assert ep['min_spread'] < 0

    def test_real_rate_structure(self, analysis):
        rr = analysis['real_fed_funds_rate']
        assert isinstance(rr, dict)
        assert len(rr) > 500, "Too few real rate months"

    def test_monetary_stance_structure(self, analysis):
        ms = analysis['monetary_stance']
        assert 'quarterly_deviation' in ms, "monetary_stance missing quarterly_deviation"
        assert 'stance' in ms, "monetary_stance missing stance"
        assert isinstance(ms['quarterly_deviation'], dict)
        assert isinstance(ms['stance'], dict)
        assert len(ms['quarterly_deviation']) > 200, "Too few monetary stance quarters"
        assert set(ms['quarterly_deviation'].keys()) == set(ms['stance'].keys()), \
            "quarterly_deviation and stance must have identical quarter keys"


class TestSahmRule:
    def test_covid_trigger_exists(self, analysis):
        """Sahm Rule must trigger during COVID recession (2020)."""
        triggers = analysis['sahm_rule']['trigger_dates']
        covid_triggers = [t for t in triggers if t.startswith('2020-')]
        assert len(covid_triggers) >= 1, "No Sahm Rule trigger found in 2020"

    def test_gfc_trigger_exists(self, analysis):
        """Sahm Rule must trigger around the Great Financial Crisis."""
        triggers = analysis['sahm_rule']['trigger_dates']
        gfc_triggers = [t for t in triggers
                        if '2007-06-01' <= t <= '2008-12-01']
        assert len(gfc_triggers) >= 1, "No Sahm Rule trigger found around 2007-2008 GFC"

    def test_covid_indicator_spike(self, analysis):
        """Sahm indicator for April 2020 should be extremely high (COVID unemployment spike)."""
        indicator = analysis['sahm_rule']['indicator']
        apr_2020 = indicator.get('2020-04-01')
        assert apr_2020 is not None, "No Sahm indicator for 2020-04-01"
        assert apr_2020 > 3.0, f"Sahm indicator for Apr 2020 too low: {apr_2020}"

    def test_pre_covid_indicator_low(self, analysis):
        """Sahm indicator should be very low before COVID (stable economy in Jan 2020)."""
        indicator = analysis['sahm_rule']['indicator']
        jan_2020 = indicator.get('2020-01-01')
        assert jan_2020 is not None, "No Sahm indicator for 2020-01-01"
        assert jan_2020 < 0.20, f"Sahm indicator for Jan 2020 unexpectedly high: {jan_2020}"

    def test_indicator_non_negative(self, analysis):
        """Sahm indicator should never be significantly negative."""
        for date, val in analysis['sahm_rule']['indicator'].items():
            assert val >= -0.01, f"Negative Sahm indicator at {date}: {val}"

    def test_trigger_dates_have_high_indicator(self, analysis):
        """Each trigger date should have Sahm indicator >= 0.50."""
        indicator = analysis['sahm_rule']['indicator']
        for trigger_date in analysis['sahm_rule']['trigger_dates']:
            val = indicator.get(trigger_date)
            assert val is not None, f"No indicator value for trigger date {trigger_date}"
            assert val >= 0.49, f"Trigger at {trigger_date} has indicator {val} < 0.50"

    def test_trigger_count_reasonable(self, analysis):
        """Number of Sahm triggers should be historically reasonable (8-20)."""
        count = len(analysis['sahm_rule']['trigger_dates'])
        assert 8 <= count <= 20, f"Unexpected Sahm trigger count: {count}"

    def test_computation_spot_check(self, analysis, unrate_data):
        """Verify Sahm computation against raw UNRATE data for a stable period."""
        df = unrate_data.set_index('observation_date')['UNRATE'].sort_index()
        df.index = pd.to_datetime(df.index)
        ma3 = df.rolling(3).mean()
        min12 = ma3.rolling(12).min()
        sahm_check = ma3 - min12

        indicator = analysis['sahm_rule']['indicator']
        # Check a stable period (mid-2019)
        date_str = '2019-06-01'
        if date_str in indicator:
            expected = sahm_check.loc[pd.Timestamp(date_str)]
            actual = indicator[date_str]
            assert abs(actual - expected) < 0.02, \
                f"Sahm mismatch at {date_str}: expected {expected:.4f}, got {actual}"


class TestOutputGap:
    def test_covid_recession_gap(self, analysis):
        """Output gap should be strongly negative during COVID crash (Q2 2020)."""
        gap = analysis['output_gap']['values']
        q2_2020 = gap.get('2020-Q2')
        assert q2_2020 is not None, "No output gap for 2020-Q2"
        assert q2_2020 < -5, f"Output gap for 2020-Q2 not negative enough: {q2_2020}"

    def test_gfc_recession_gap(self, analysis):
        """Output gap should be negative during the Great Financial Crisis."""
        gap = analysis['output_gap']['values']
        q2_2009 = gap.get('2009-Q2')
        q3_2009 = gap.get('2009-Q3')
        vals = [v for v in [q2_2009, q3_2009] if v is not None]
        assert len(vals) > 0, "No output gap for 2009 Q2 or Q3"
        assert min(vals) < -2, f"Output gap during GFC not negative enough: {vals}"

    def test_late_1990s_boom(self, analysis):
        """Output gap should be positive during late 1990s economic boom."""
        gap = analysis['output_gap']['values']
        boom_vals = []
        for key in ['1999-Q3', '1999-Q4', '2000-Q1']:
            v = gap.get(key)
            if v is not None:
                boom_vals.append(v)
        assert len(boom_vals) > 0, "No output gap for late 1990s"
        assert max(boom_vals) > 0, f"Output gap not positive in late 1990s boom: {boom_vals}"

    def test_mean_approximately_zero(self, analysis):
        """Mean output gap over the full sample should be approximately zero (HP filter property)."""
        gap = analysis['output_gap']['values']
        values = list(gap.values())
        mean_gap = sum(values) / len(values)
        assert abs(mean_gap) < 2.0, f"Mean output gap too far from zero: {mean_gap:.4f}"

    def test_reasonable_range(self, analysis):
        """All output gap values should be in a reasonable range."""
        gap = analysis['output_gap']['values']
        for key, val in gap.items():
            assert -30 < val < 30, f"Unreasonable output gap at {key}: {val}"

    def test_quarter_format(self, analysis):
        """Quarter keys should match YYYY-QN format."""
        import re
        pattern = re.compile(r'^\d{4}-Q[1-4]$')
        for key in analysis['output_gap']['values']:
            assert pattern.match(key), f"Invalid quarter format: {key}"


class TestTaylorRule:
    def test_high_inflation_era(self, analysis):
        """Taylor Rule should prescribe very high rates during Volcker era (1980)."""
        rates = analysis['taylor_rule']['prescribed_rates']
        # Mid-1980: inflation was ~14%, Taylor Rule should prescribe > 15%
        high_1980 = [v for k, v in rates.items() if k.startswith('1980-')]
        assert len(high_1980) > 0, "No Taylor Rule rates for 1980"
        assert max(high_1980) > 15, \
            f"Taylor rate peak in 1980 too low: {max(high_1980)}"

    def test_gfc_low_rates(self, analysis):
        """Taylor Rule should prescribe low or negative rates during GFC."""
        rates = analysis['taylor_rule']['prescribed_rates']
        low_2009 = [v for k, v in rates.items() if k.startswith('2009-')]
        assert len(low_2009) > 0, "No Taylor Rule rates for 2009"
        assert min(low_2009) < 2, \
            f"Taylor rate minimum in 2009 too high: {min(low_2009)}"

    def test_mathematical_consistency(self, analysis, cpi_data):
        """Verify Taylor Rule formula by re-computing from inflation and output gap."""
        rates = analysis['taylor_rule']['prescribed_rates']
        r_star = analysis['taylor_rule']['r_star']
        pi_star = analysis['taylor_rule']['pi_star']

        # Compute inflation from raw CPI
        cpi = cpi_data.set_index('observation_date')['CPIAUCSL'].sort_index()
        cpi.index = pd.to_datetime(cpi.index)
        inflation = (cpi / cpi.shift(12) - 1) * 100

        # Reconstruct quarterly output gap as a monthly interpolated series
        gap_values = analysis['output_gap']['values']
        gap_quarterly = {}
        for key, val in gap_values.items():
            year, qstr = key.split('-Q')
            quarter = int(qstr)
            month = (quarter - 1) * 3 + 1
            date = pd.Timestamp(f"{year}-{month:02d}-01")
            gap_quarterly[date] = val
        gap_series = pd.Series(gap_quarterly).sort_index()
        monthly_dates = pd.date_range(start=gap_series.index[0],
                                       end=gap_series.index[-1], freq='MS')
        gap_monthly = gap_series.reindex(monthly_dates).interpolate(method='linear')

        # Spot-check several dates
        check_dates = ['2000-01-01', '2005-01-01', '2010-01-01', '2015-01-01', '2019-01-01']
        checked = 0
        for date_str in check_dates:
            if date_str not in rates:
                continue
            date = pd.Timestamp(date_str)
            if date not in inflation.index or date not in gap_monthly.index:
                continue
            if pd.isna(inflation.loc[date]) or pd.isna(gap_monthly.loc[date]):
                continue

            pi = float(inflation.loc[date])
            gap = float(gap_monthly.loc[date])
            expected = r_star + pi + 0.5 * (pi - pi_star) + 0.5 * gap
            actual = rates[date_str]
            assert abs(actual - expected) < 0.15, \
                f"Taylor Rule mismatch at {date_str}: expected {expected:.4f}, got {actual}"
            checked += 1

        assert checked >= 3, f"Only verified {checked} Taylor Rule dates, need >= 3"

    def test_parameters(self, analysis):
        assert analysis['taylor_rule']['r_star'] == 2.0
        assert analysis['taylor_rule']['pi_star'] == 2.0


class TestYieldCurveInversions:
    def test_2022_inversion(self, analysis):
        """Must detect the major 2022-2023 yield curve inversion."""
        inversions = analysis['yield_curve_inversions']
        found = False
        for ep in inversions:
            if '2022-01-01' <= ep['start'] <= '2023-01-01':
                found = True
                assert ep['duration_days'] > 100, \
                    f"2022 inversion too short: {ep['duration_days']} days"
        assert found, "2022-2023 yield curve inversion not detected"

    def test_pre_gfc_inversion(self, analysis):
        """Must detect yield curve inversion before 2008 financial crisis."""
        inversions = analysis['yield_curve_inversions']
        found = any('2005-06-01' <= ep['start'] <= '2007-12-01'
                     for ep in inversions)
        assert found, "Pre-GFC (2006-2007) yield curve inversion not detected"

    def test_all_episodes_valid(self, analysis):
        """All inversion episodes should have valid data."""
        for ep in analysis['yield_curve_inversions']:
            assert ep['start'] <= ep['end'], \
                f"Start {ep['start']} after end {ep['end']}"
            assert ep['min_spread'] < 0, \
                f"Positive min_spread in inversion: {ep['min_spread']}"
            assert ep['duration_days'] >= 5, \
                f"Episode too short: {ep['duration_days']}"

    def test_reasonable_episode_count(self, analysis):
        """Should detect between 5 and 30 inversion episodes from 1976-present."""
        count = len(analysis['yield_curve_inversions'])
        assert 5 <= count <= 30, f"Unexpected inversion episode count: {count}"

    def test_chronological_order(self, analysis):
        """Inversion episodes should be in chronological order."""
        inversions = analysis['yield_curve_inversions']
        for i in range(1, len(inversions)):
            assert inversions[i]['start'] > inversions[i-1]['end'], \
                f"Episodes overlap or out of order: {inversions[i-1]['end']} -> {inversions[i]['start']}"


class TestRealFedFundsRate:
    def test_volcker_era_positive(self, analysis):
        """Real rate should be strongly positive during Volcker's tight money policy (late 1982)."""
        rr = analysis['real_fed_funds_rate']
        val = rr.get('1982-12-01')
        assert val is not None, "No real rate for 1982-12-01"
        assert val > 3, f"Real rate in Dec 1982 not positive enough: {val}"

    def test_negative_real_rate_2021(self, analysis):
        """Real rate should be very negative in 2021 (near-zero rates + rising inflation)."""
        rr = analysis['real_fed_funds_rate']
        found = False
        for month in ['2021-06-01', '2021-09-01', '2021-12-01']:
            if month in rr:
                assert rr[month] < -2, f"Real rate in {month} not negative: {rr[month]}"
                found = True
                break
        assert found, "No real rate data found for 2021"

    def test_computation_spot_check(self, analysis, cpi_data, fedfunds_data):
        """Verify real rate = FEDFUNDS - YoY CPI inflation against raw data."""
        rr = analysis['real_fed_funds_rate']

        cpi = cpi_data.set_index('observation_date')['CPIAUCSL'].sort_index()
        cpi.index = pd.to_datetime(cpi.index)
        ff = fedfunds_data.set_index('observation_date')['FEDFUNDS'].sort_index()
        ff.index = pd.to_datetime(ff.index)
        inflation = (cpi / cpi.shift(12) - 1) * 100

        check_dates = ['2000-06-01', '2005-06-01', '2010-06-01', '2015-06-01', '2019-06-01']
        checked = 0
        for date_str in check_dates:
            if date_str not in rr:
                continue
            date = pd.Timestamp(date_str)
            if date not in ff.index or date not in inflation.index:
                continue
            if pd.isna(ff.loc[date]) or pd.isna(inflation.loc[date]):
                continue

            expected = float(ff.loc[date]) - float(inflation.loc[date])
            actual = rr[date_str]
            assert abs(actual - expected) < 0.02, \
                f"Real rate mismatch at {date_str}: expected {expected:.4f}, got {actual}"
            checked += 1

        assert checked >= 3, f"Only verified {checked} real rate dates, need >= 3"


class TestMonetaryStance:
    def test_valid_stances(self, analysis):
        """All stance values must be one of the three valid categories."""
        valid = {"accommodative", "restrictive", "neutral"}
        for qtr, stance in analysis['monetary_stance']['stance'].items():
            assert stance in valid, f"Invalid stance at {qtr}: {stance}"

    def test_stance_deviation_consistency(self, analysis):
        """Stance classification must be consistent with the deviation value."""
        ms = analysis['monetary_stance']
        for qtr in ms['quarterly_deviation']:
            dev = ms['quarterly_deviation'][qtr]
            stance = ms['stance'][qtr]
            if dev < -2.0:
                assert stance == "accommodative", \
                    f"Deviation {dev} at {qtr} should be accommodative, got {stance}"
            elif dev > 2.0:
                assert stance == "restrictive", \
                    f"Deviation {dev} at {qtr} should be restrictive, got {stance}"
            else:
                assert stance == "neutral", \
                    f"Deviation {dev} at {qtr} should be neutral, got {stance}"

    def test_2021_accommodative(self, analysis):
        """Near-zero rates with rapidly rising inflation in 2021 = very accommodative."""
        ms = analysis['monetary_stance']
        found = False
        for qtr in ['2021-Q3', '2021-Q4']:
            if qtr in ms['stance']:
                assert ms['stance'][qtr] == "accommodative", \
                    f"2021 should be accommodative, got {ms['stance'][qtr]}"
                assert ms['quarterly_deviation'][qtr] < -3.0, \
                    f"Deviation in {qtr} should be very negative, got {ms['quarterly_deviation'][qtr]}"
                found = True
        assert found, "No stance data for 2021 Q3/Q4"

    def test_deviation_spot_check(self, analysis, fedfunds_data):
        """Verify deviation = avg_actual - avg_prescribed for a specific quarter."""
        ms = analysis['monetary_stance']
        taylor = analysis['taylor_rule']['prescribed_rates']

        ff = fedfunds_data.set_index('observation_date')['FEDFUNDS'].sort_index()
        ff.index = pd.to_datetime(ff.index)

        # Check 2015-Q1
        qtr = '2015-Q1'
        if qtr in ms['quarterly_deviation']:
            months = ['2015-01-01', '2015-02-01', '2015-03-01']
            actual_vals = []
            prescribed_vals = []
            for m in months:
                ts = pd.Timestamp(m)
                if ts in ff.index and m in taylor:
                    actual_vals.append(float(ff.loc[ts]))
                    prescribed_vals.append(taylor[m])

            if len(actual_vals) == 3 and len(prescribed_vals) == 3:
                expected_dev = sum(actual_vals) / 3 - sum(prescribed_vals) / 3
                actual_dev = ms['quarterly_deviation'][qtr]
                assert abs(actual_dev - expected_dev) < 0.15, \
                    f"Deviation mismatch at {qtr}: expected {expected_dev:.4f}, got {actual_dev}"

    def test_quarter_format(self, analysis):
        """Quarter keys should match YYYY-QN format."""
        import re
        pattern = re.compile(r'^\d{4}-Q[1-4]$')
        for key in analysis['monetary_stance']['quarterly_deviation']:
            assert pattern.match(key), f"Invalid quarter format: {key}"

    def test_keys_match_output_gap_range(self, analysis):
        """Monetary stance quarters should be a subset of output gap quarters."""
        gap_keys = set(analysis['output_gap']['values'].keys())
        stance_keys = set(analysis['monetary_stance']['quarterly_deviation'].keys())
        extra = stance_keys - gap_keys
        assert len(extra) == 0, \
            f"Monetary stance has quarters not in output gap: {extra}"
