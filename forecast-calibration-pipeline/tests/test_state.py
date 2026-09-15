"""
Test the forecast calibration pipeline output against reference computation.
"""

import json
import math
import os

import numpy as np
import pandas as pd
import pytest
import yaml


def _compute_reference():
    """Compute reference values from raw data using the specification."""
    with open('/data/config.yaml') as f:
        config = yaml.safe_load(f)

    instruments = config['instruments']
    vc = config['volatility_calculation']
    rules = config['trading_rules']
    forecast_cap = config['forecast_cap']
    avg_abs_fc = config['average_absolute_forecast']
    fw = config['forecast_weights']
    capital = config['notional_trading_capital']
    vol_target = config['percentage_vol_target']

    prices = {}
    for inst in instruments:
        df = pd.read_csv(f'/data/{inst}.csv', parse_dates=['date'], index_col='date')
        prices[inst] = df['price']

    # Blended volatility
    vols = {}
    for inst in instruments:
        ret = prices[inst].diff()
        fast = ret.ewm(span=vc['days'], min_periods=vc['min_periods']).std()
        slow = ret.expanding(min_periods=vc['min_periods']).std()
        blended = vc['proportion_of_slow_vol'] * slow + (1.0 - vc['proportion_of_slow_vol']) * fast
        vols[inst] = blended.clip(lower=vc['vol_abs_min'])

    # EWMAC raw forecasts
    rule_names = list(rules.keys())
    raw_fc = {}
    for rn in rule_names:
        raw_fc[rn] = {}
        for inst in instruments:
            f_ema = prices[inst].ewm(span=rules[rn]['Lfast']).mean()
            s_ema = prices[inst].ewm(span=rules[rn]['Lslow']).mean()
            raw_fc[rn][inst] = (f_ema - s_ema) / vols[inst]

    # Pooled forecast scalars
    scalars = {}
    for rn in rule_names:
        pooled = pd.concat([raw_fc[rn][inst] for inst in instruments]).dropna()
        scalars[rn] = avg_abs_fc / pooled.abs().mean()

    # Scale and cap
    sc_fc = {}
    for rn in rule_names:
        sc_fc[rn] = {}
        for inst in instruments:
            s = raw_fc[rn][inst] * scalars[rn]
            sc_fc[rn][inst] = s.clip(lower=-forecast_cap, upper=forecast_cap)

    # FDM
    corr_mats = []
    for inst in instruments:
        fc_df = pd.DataFrame({rn: sc_fc[rn][inst] for rn in rule_names}).dropna()
        if len(fc_df) > 20:
            corr_mats.append(fc_df.corr().values)
    avg_corr = np.mean(corr_mats, axis=0)
    w = np.array([fw[rn] for rn in rule_names])
    fdm = 1.0 / math.sqrt(float(w @ avg_corr @ w))
    fdm = min(fdm, 2.5)

    # Combined forecasts
    combined = {}
    for inst in instruments:
        c = sum(fw[rn] * sc_fc[rn][inst] for rn in rule_names) * fdm
        combined[inst] = c.clip(lower=-forecast_cap, upper=forecast_cap)

    # Subsystem positions
    positions = {}
    for inst in instruments:
        pos = (combined[inst] / avg_abs_fc) * (capital * vol_target / 100.0) / (
            vols[inst] * math.sqrt(252)
        )
        positions[inst] = pos

    return {
        'forecast_scalars': {rn: float(scalars[rn]) for rn in rule_names},
        'forecast_diversification_multiplier': float(fdm),
        'combined_forecasts_last': {
            inst: float(combined[inst].dropna().iloc[-1]) for inst in instruments
        },
        'subsystem_positions_last': {
            inst: float(positions[inst].dropna().iloc[-1]) for inst in instruments
        },
        'vol_on_last_date': {
            inst: float(vols[inst].dropna().iloc[-1]) for inst in instruments
        },
    }


@pytest.fixture(scope='module')
def ref():
    return _compute_reference()


@pytest.fixture(scope='module')
def agent():
    path = '/app/output/results.json'
    assert os.path.exists(path), f"Output file {path} not found"
    with open(path) as f:
        return json.load(f)


def _close(a, b, rtol=0.02, atol=0.05):
    """Check approximate equality with relative and absolute tolerance."""
    if abs(b) < 1e-8:
        return abs(a) < atol
    return abs(a - b) / abs(b) <= rtol or abs(a - b) <= atol


# ---- Structure tests ----


def test_output_exists():
    assert os.path.exists('/app/output/results.json'), "results.json not found at /app/output/"


def test_has_required_keys(agent):
    for key in [
        'forecast_scalars',
        'forecast_diversification_multiplier',
        'combined_forecasts_last',
        'subsystem_positions_last',
        'vol_on_last_date',
    ]:
        assert key in agent, f"Missing top-level key: {key}"


def test_forecast_scalars_keys(agent):
    for rn in ['ewmac8_32', 'ewmac16_64', 'ewmac32_128']:
        assert rn in agent['forecast_scalars'], f"Missing forecast scalar key: {rn}"


def test_instrument_keys_present(agent):
    for section in ['combined_forecasts_last', 'subsystem_positions_last', 'vol_on_last_date']:
        for inst in ['INSTR_A', 'INSTR_B', 'INSTR_C', 'INSTR_D']:
            assert inst in agent[section], f"Missing {inst} in {section}"


# ---- Invariant tests ----


def test_scalars_positive(agent):
    for rn, val in agent['forecast_scalars'].items():
        assert val > 0, f"Forecast scalar {rn} should be positive, got {val}"


def test_scalar_ordering(agent):
    s = agent['forecast_scalars']
    assert s['ewmac8_32'] > s['ewmac16_64'] > s['ewmac32_128'], (
        f"Expected ewmac8_32 > ewmac16_64 > ewmac32_128 but got "
        f"{s['ewmac8_32']:.4f}, {s['ewmac16_64']:.4f}, {s['ewmac32_128']:.4f}"
    )


def test_fdm_in_valid_range(agent):
    fdm = agent['forecast_diversification_multiplier']
    assert 1.0 <= fdm <= 2.5, f"FDM should be in [1.0, 2.5], got {fdm}"


def test_combined_forecasts_within_cap(agent):
    for inst, val in agent['combined_forecasts_last'].items():
        assert -20.0 <= val <= 20.0, f"Combined forecast for {inst} out of [-20, 20]: {val}"


def test_vol_values_positive(agent):
    for inst, val in agent['vol_on_last_date'].items():
        assert val > 0, f"Vol for {inst} should be positive, got {val}"


# ---- Reference comparison: forecast scalars ----


def test_scalar_ewmac8_32(agent, ref):
    a = agent['forecast_scalars']['ewmac8_32']
    e = ref['forecast_scalars']['ewmac8_32']
    assert _close(a, e), f"ewmac8_32 scalar: got {a:.6f}, expected {e:.6f}"


def test_scalar_ewmac16_64(agent, ref):
    a = agent['forecast_scalars']['ewmac16_64']
    e = ref['forecast_scalars']['ewmac16_64']
    assert _close(a, e), f"ewmac16_64 scalar: got {a:.6f}, expected {e:.6f}"


def test_scalar_ewmac32_128(agent, ref):
    a = agent['forecast_scalars']['ewmac32_128']
    e = ref['forecast_scalars']['ewmac32_128']
    assert _close(a, e), f"ewmac32_128 scalar: got {a:.6f}, expected {e:.6f}"


# ---- Reference comparison: FDM ----


def test_fdm_value(agent, ref):
    a = agent['forecast_diversification_multiplier']
    e = ref['forecast_diversification_multiplier']
    assert _close(a, e), f"FDM: got {a:.6f}, expected {e:.6f}"


# ---- Reference comparison: combined forecasts ----


def test_combined_A(agent, ref):
    a = agent['combined_forecasts_last']['INSTR_A']
    e = ref['combined_forecasts_last']['INSTR_A']
    assert _close(a, e), f"Combined INSTR_A: got {a:.6f}, expected {e:.6f}"


def test_combined_B(agent, ref):
    a = agent['combined_forecasts_last']['INSTR_B']
    e = ref['combined_forecasts_last']['INSTR_B']
    assert _close(a, e), f"Combined INSTR_B: got {a:.6f}, expected {e:.6f}"


def test_combined_C(agent, ref):
    a = agent['combined_forecasts_last']['INSTR_C']
    e = ref['combined_forecasts_last']['INSTR_C']
    assert _close(a, e), f"Combined INSTR_C: got {a:.6f}, expected {e:.6f}"


def test_combined_D(agent, ref):
    a = agent['combined_forecasts_last']['INSTR_D']
    e = ref['combined_forecasts_last']['INSTR_D']
    assert _close(a, e), f"Combined INSTR_D: got {a:.6f}, expected {e:.6f}"


# ---- Reference comparison: subsystem positions ----


def test_position_A(agent, ref):
    a = agent['subsystem_positions_last']['INSTR_A']
    e = ref['subsystem_positions_last']['INSTR_A']
    assert _close(a, e, rtol=0.03), f"Position INSTR_A: got {a:.4f}, expected {e:.4f}"


def test_position_B(agent, ref):
    a = agent['subsystem_positions_last']['INSTR_B']
    e = ref['subsystem_positions_last']['INSTR_B']
    assert _close(a, e, rtol=0.03), f"Position INSTR_B: got {a:.4f}, expected {e:.4f}"


def test_position_C(agent, ref):
    a = agent['subsystem_positions_last']['INSTR_C']
    e = ref['subsystem_positions_last']['INSTR_C']
    assert _close(a, e, rtol=0.03), f"Position INSTR_C: got {a:.4f}, expected {e:.4f}"


def test_position_D(agent, ref):
    a = agent['subsystem_positions_last']['INSTR_D']
    e = ref['subsystem_positions_last']['INSTR_D']
    assert _close(a, e, rtol=0.03), f"Position INSTR_D: got {a:.4f}, expected {e:.4f}"


# ---- Reference comparison: volatility ----


def test_vol_A(agent, ref):
    a = agent['vol_on_last_date']['INSTR_A']
    e = ref['vol_on_last_date']['INSTR_A']
    assert _close(a, e), f"Vol INSTR_A: got {a:.8f}, expected {e:.8f}"


def test_vol_B(agent, ref):
    a = agent['vol_on_last_date']['INSTR_B']
    e = ref['vol_on_last_date']['INSTR_B']
    assert _close(a, e), f"Vol INSTR_B: got {a:.8f}, expected {e:.8f}"


def test_vol_C(agent, ref):
    a = agent['vol_on_last_date']['INSTR_C']
    e = ref['vol_on_last_date']['INSTR_C']
    assert _close(a, e), f"Vol INSTR_C: got {a:.8f}, expected {e:.8f}"


def test_vol_D(agent, ref):
    a = agent['vol_on_last_date']['INSTR_D']
    e = ref['vol_on_last_date']['INSTR_D']
    assert _close(a, e), f"Vol INSTR_D: got {a:.8f}, expected {e:.8f}"
