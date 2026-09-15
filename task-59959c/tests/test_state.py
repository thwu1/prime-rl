"""Tests for CMIP6 multi-model climate sensitivity and extremes analysis."""

import pytest
import json
import os
import numpy as np
import xarray as xr
import pandas as pd
from scipy.stats import linregress

MODELS = ['SYNTH-ESM-A', 'SYNTH-ESM-B', 'SYNTH-ESM-C', 'SYNTH-ESM-D']
TCR_MODELS = ['SYNTH-ESM-A', 'SYNTH-ESM-C']


def _load_var(cat, model, experiment, variable):
    row = cat[(cat['source_id'] == model) &
              (cat['experiment_id'] == experiment) &
              (cat['variable_id'] == variable)]
    if len(row) == 0:
        return None
    return xr.open_zarr(row.iloc[0]['zstore'], consolidated=True)[variable]


def _to_kelvin(da):
    if da.attrs.get('units', 'K') == 'degC':
        return da + 273.15
    return da


def _to_celsius(da):
    if da.attrs.get('units', 'K') == 'K':
        return da - 273.15
    return da


def _area_mean(da):
    w = np.cos(np.deg2rad(da.lat))
    return da.weighted(w).mean(dim=['lat', 'lon'])


def _stull_wbt(T, RH):
    return (T * np.arctan(0.151977 * np.sqrt(RH + 8.313659)) +
            np.arctan(T + RH) - np.arctan(RH - 1.676331) +
            0.00391838 * RH ** 1.5 * np.arctan(0.023101 * RH) - 4.686035)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def results():
    with open('/app/results.json') as f:
        return json.load(f)


@pytest.fixture(scope='session')
def catalog():
    return pd.read_csv('/app/catalog.csv')


@pytest.fixture(scope='session')
def expected(catalog):
    exp = {
        'ecs': {}, 'feedback': {}, 'forcing': {},
        'tcr': {}, 'ratio': {},
        'warming': {}, 'max_wbt': {}, 'cells_28': {},
    }

    for m in MODELS:
        # --- Gregory regression from abrupt-4xCO2 vs piControl ---
        tas_pi = _to_kelvin(_load_var(catalog, m, 'piControl', 'tas'))
        tas_4x = _to_kelvin(_load_var(catalog, m, 'abrupt-4xCO2', 'tas'))
        rsdt = _load_var(catalog, m, 'abrupt-4xCO2', 'rsdt')
        rsut = _load_var(catalog, m, 'abrupt-4xCO2', 'rsut')
        rlut = _load_var(catalog, m, 'abrupt-4xCO2', 'rlut')

        T_pi = float(_area_mean(tas_pi).mean(dim='time').values)
        T_4x_ann = _area_mean(tas_4x).groupby('time.year').mean()
        dT = T_4x_ann.values - T_pi
        N_ann = _area_mean(rsdt - rsut - rlut).groupby('time.year').mean()
        slope, intercept, _, _, _ = linregress(dT, N_ann.values)

        exp['feedback'][m] = float(slope)
        exp['forcing'][m] = float(intercept / 2.0)
        exp['ecs'][m] = float(-intercept / (2 * slope))

        # --- TCR ---
        if m in TCR_MODELS:
            tas_1pct = _to_kelvin(_load_var(catalog, m, '1pctCO2', 'tas'))
            T_1pct_ann = _area_mean(tas_1pct).groupby('time.year').mean()
            dT_1pct = T_1pct_ann.values - T_pi
            years = T_1pct_ann.year.values
            sim_yr = years - years[0]
            mask = (sim_yr >= 60) & (sim_yr <= 79)
            tcr_val = float(np.mean(dT_1pct[mask]))
            exp['tcr'][m] = tcr_val
            exp['ratio'][m] = exp['ecs'][m] / tcr_val

        # --- Warming ---
        tas_hist = _to_kelvin(_load_var(catalog, m, 'historical', 'tas'))
        tas_ssp = _to_kelvin(_load_var(catalog, m, 'ssp585', 'tas'))
        T_hist = float(_area_mean(tas_hist).mean(dim='time').values)
        T_ssp = float(_area_mean(tas_ssp.sel(time=slice('2091', '2100')))
                      .mean(dim='time').values)
        exp['warming'][m] = T_ssp - T_hist

        # --- WBT extremes ---
        tas_raw = _load_var(catalog, m, 'ssp585', 'tas')
        hurs = _load_var(catalog, m, 'ssp585', 'hurs')
        T_C = _to_celsius(tas_raw).sel(time=slice('2091', '2100'))
        RH = hurs.sel(time=slice('2091', '2100'))
        wbt = _stull_wbt(T_C, RH)
        exp['max_wbt'][m] = float(wbt.max().values)
        wbt_tmean = wbt.mean(dim='time')
        exp['cells_28'][m] = int((wbt_tmean > 28).sum().values)

    # Ensemble stats
    ecs_vals = list(exp['ecs'].values())
    exp['ecs_mean'] = float(np.mean(ecs_vals))
    exp['ecs_std'] = float(np.std(ecs_vals, ddof=0))
    exp['outside_ipcc'] = sorted([m for m, v in exp['ecs'].items()
                                   if v < 2.5 or v > 4.0])
    return exp


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestResultStructure:
    def test_file_exists(self):
        assert os.path.exists('/app/results.json'), "results.json not found"

    def test_required_keys(self, results):
        for key in ['ecs', 'feedback_parameter', 'forcing_2xCO2',
                     'tcr', 'ecs_tcr_ratio',
                     'warming_ssp585_K', 'max_wbt_C',
                     'grid_cells_wbt_above_28',
                     'ecs_ensemble_mean', 'ecs_ensemble_std',
                     'models_outside_ipcc_likely',
                     'ecs_ranking', 'most_warming_model']:
            assert key in results, f"Missing required key: {key}"

    def test_all_models_in_ecs(self, results):
        for m in MODELS:
            assert m in results['ecs'], f"Model {m} missing from ecs"

    def test_all_models_in_feedback(self, results):
        for m in MODELS:
            assert m in results['feedback_parameter'], \
                f"Model {m} missing from feedback_parameter"

    def test_all_models_in_forcing(self, results):
        for m in MODELS:
            assert m in results['forcing_2xCO2'], \
                f"Model {m} missing from forcing_2xCO2"

    def test_all_models_in_warming(self, results):
        for m in MODELS:
            assert m in results['warming_ssp585_K'], \
                f"Model {m} missing from warming_ssp585_K"

    def test_tcr_models_present(self, results):
        for m in TCR_MODELS:
            assert m in results['tcr'], f"Model {m} missing from tcr"

    def test_ecs_tcr_ratio_models(self, results):
        for m in TCR_MODELS:
            assert m in results['ecs_tcr_ratio'], \
                f"Model {m} missing from ecs_tcr_ratio"

    def test_ecs_ranking_length(self, results):
        assert len(results['ecs_ranking']) == len(MODELS)


# ---------------------------------------------------------------------------
# ECS tests
# ---------------------------------------------------------------------------

class TestECS:
    def test_ecs_values(self, results, expected):
        for m in MODELS:
            agent = results['ecs'][m]
            exp = expected['ecs'][m]
            assert abs(agent - exp) < 0.4, \
                f"ECS {m}: agent={agent:.3f}, expected={exp:.3f}"

    def test_ecs_ranking(self, results, expected):
        ranking = sorted(expected['ecs'].items(),
                         key=lambda x: x[1], reverse=True)
        expected_ranking = [m for m, _ in ranking]
        assert results['ecs_ranking'] == expected_ranking, \
            f"Ranking: got {results['ecs_ranking']}, want {expected_ranking}"


# ---------------------------------------------------------------------------
# Feedback parameter and forcing tests
# ---------------------------------------------------------------------------

class TestFeedbackForcing:
    def test_feedback_parameter_values(self, results, expected):
        for m in MODELS:
            agent = results['feedback_parameter'][m]
            exp = expected['feedback'][m]
            assert abs(agent - exp) < 0.15, \
                f"Feedback {m}: agent={agent:.3f}, expected={exp:.3f}"

    def test_feedback_parameter_negative(self, results):
        for m in MODELS:
            assert results['feedback_parameter'][m] < 0, \
                f"Feedback parameter for {m} should be negative (stable climate)"

    def test_forcing_2xCO2_values(self, results, expected):
        for m in MODELS:
            agent = results['forcing_2xCO2'][m]
            exp = expected['forcing'][m]
            assert abs(agent - exp) < 0.5, \
                f"F_2x {m}: agent={agent:.3f}, expected={exp:.3f}"

    def test_forcing_2xCO2_positive(self, results):
        for m in MODELS:
            assert results['forcing_2xCO2'][m] > 0, \
                f"F_2x for {m} should be positive"


# ---------------------------------------------------------------------------
# TCR tests
# ---------------------------------------------------------------------------

class TestTCR:
    def test_tcr_values(self, results, expected):
        for m in TCR_MODELS:
            agent = results['tcr'][m]
            exp = expected['tcr'][m]
            assert abs(agent - exp) < 0.25, \
                f"TCR {m}: agent={agent:.3f}, expected={exp:.3f}"


# ---------------------------------------------------------------------------
# ECS/TCR ratio tests
# ---------------------------------------------------------------------------

class TestECSTCRRatio:
    def test_ratio_values(self, results, expected):
        for m in TCR_MODELS:
            agent = results['ecs_tcr_ratio'][m]
            exp = expected['ratio'][m]
            assert abs(agent - exp) < 0.2, \
                f"ECS/TCR ratio {m}: agent={agent:.3f}, expected={exp:.3f}"

    def test_ratio_greater_than_one(self, results):
        for m in TCR_MODELS:
            assert results['ecs_tcr_ratio'][m] > 1.0, \
                f"ECS/TCR ratio for {m} should be > 1.0"


# ---------------------------------------------------------------------------
# Warming tests
# ---------------------------------------------------------------------------

class TestWarming:
    def test_warming_values(self, results, expected):
        for m in MODELS:
            agent = results['warming_ssp585_K'][m]
            exp = expected['warming'][m]
            assert abs(agent - exp) < 0.25, \
                f"Warming {m}: agent={agent:.3f}, expected={exp:.3f}"

    def test_most_warming_model(self, results, expected):
        exp_most = max(expected['warming'].items(), key=lambda x: x[1])[0]
        assert results['most_warming_model'] == exp_most, \
            f"Most warming: got {results['most_warming_model']}, want {exp_most}"


# ---------------------------------------------------------------------------
# WBT tests
# ---------------------------------------------------------------------------

class TestWBT:
    def test_max_wbt(self, results, expected):
        for m in MODELS:
            agent = results['max_wbt_C'][m]
            exp = expected['max_wbt'][m]
            assert abs(agent - exp) < 1.0, \
                f"Max WBT {m}: agent={agent:.2f}, expected={exp:.2f}"

    def test_grid_cells_above_28(self, results, expected):
        for m in MODELS:
            agent = results['grid_cells_wbt_above_28'][m]
            exp = expected['cells_28'][m]
            assert abs(agent - exp) <= 3, \
                f"Grid cells >28 {m}: agent={agent}, expected={exp}"


# ---------------------------------------------------------------------------
# Ensemble statistics tests
# ---------------------------------------------------------------------------

class TestEnsembleStats:
    def test_ensemble_mean(self, results, expected):
        agent = results['ecs_ensemble_mean']
        exp = expected['ecs_mean']
        assert abs(agent - exp) < 0.3, \
            f"ECS ensemble mean: agent={agent:.3f}, expected={exp:.3f}"

    def test_ensemble_std(self, results, expected):
        agent = results['ecs_ensemble_std']
        exp = expected['ecs_std']
        assert abs(agent - exp) < 0.3, \
            f"ECS ensemble std: agent={agent:.3f}, expected={exp:.3f}"

    def test_models_outside_ipcc(self, results, expected):
        agent_set = set(results['models_outside_ipcc_likely'])
        exp_set = set(expected['outside_ipcc'])
        assert agent_set == exp_set, \
            f"Models outside IPCC likely: got {agent_set}, want {exp_set}"
