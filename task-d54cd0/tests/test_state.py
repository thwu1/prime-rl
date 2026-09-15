"""Tests for CMIP6 climate extremes with ENSO teleconnections pipeline."""

import pytest
import json
import numpy as np
import xarray as xr
import os


def compute_wbt(T_celsius, RH_pct):
    """Stull (2011) wet bulb temperature approximation."""
    return (
        T_celsius * np.arctan(0.151977 * np.sqrt(RH_pct + 8.313659))
        + np.arctan(T_celsius + RH_pct)
        - np.arctan(RH_pct - 1.676331)
        + 0.00391838 * RH_pct ** 1.5 * np.arctan(0.023101 * RH_pct)
        - 4.686035
    )


MODELS = ['ModelAlpha', 'ModelBeta', 'ModelGamma']
ZARR_BASE = '/app/data/zarr_stores'


class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json'), "results.json not found at /app/results.json"

    def test_results_has_model_stats(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert 'model_stats' in results

    def test_results_has_ensemble(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert 'ensemble' in results

    def test_all_models_present(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        for model in MODELS:
            assert model in results['model_stats'], f"Model {model} missing from model_stats"

    def test_model_stat_keys(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        required = ['wbt_p90_elnino_mean', 'wbt_p90_lanina_mean',
                     'wbt_p90_neutral_mean', 'elnino_month_count', 'lanina_month_count']
        for model in MODELS:
            for key in required:
                assert key in results['model_stats'][model], \
                    f"Key {key} missing for model {model}"

    def test_ensemble_keys(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        required = ['wbt_p90_elnino_mean', 'wbt_p90_lanina_mean', 'wbt_p90_neutral_mean',
                     'wbt_p90_elnino_std', 'wbt_p90_lanina_std', 'wbt_p90_neutral_std']
        for key in required:
            assert key in results['ensemble'], f"Key {key} missing from ensemble"


class TestWBTFormula:
    def test_reference_point(self):
        """T=20C, RH=50% should give WBT ~ 13.7C."""
        wbt = compute_wbt(20.0, 50.0)
        assert abs(wbt - 13.7) < 0.1, f"WBT(20C, 50%) = {wbt:.4f}, expected ~13.7"

    def test_higher_humidity(self):
        """Higher humidity should increase WBT."""
        wbt_low = compute_wbt(30.0, 40.0)
        wbt_high = compute_wbt(30.0, 90.0)
        assert wbt_high > wbt_low, "WBT should increase with humidity"


class TestModelValues:
    """Recompute expected values from raw zarr data and compare to agent output."""

    @pytest.fixture(scope='class')
    def results(self):
        with open('/app/results.json') as f:
            return json.load(f)

    @pytest.fixture(scope='class')
    def reference(self):
        """Independently compute reference values from zarr data."""
        ref = {}
        for model in MODELS:
            store = os.path.join(ZARR_BASE, model, 'historical', 'r1i1p1f1')

            ds_tas = xr.open_zarr(os.path.join(store, 'tas'), consolidated=True)
            ds_hurs = xr.open_zarr(os.path.join(store, 'hurs'), consolidated=True)
            ds_tos = xr.open_zarr(os.path.join(store, 'tos'), consolidated=True)

            # WBT
            T_c = ds_tas['tas'].values - 273.15
            RH = ds_hurs['hurs'].values
            wbt = compute_wbt(T_c, RH)

            nt = wbt.shape[0]
            wbt_flat = wbt.reshape(nt, -1)
            wbt_p90 = np.percentile(wbt_flat, 90, axis=1)

            # ONI
            tos = ds_tos['tos']
            nino34 = tos.sel(lat=slice(-5, 5), lon=slice(190, 240))
            weights = np.cos(np.deg2rad(nino34.lat))
            nino34_mean = nino34.weighted(weights).mean(dim=['lat', 'lon'])
            nino34_C = nino34_mean - 273.15

            clim = nino34_C.groupby('time.month').mean()
            anom = nino34_C.groupby('time.month') - clim
            oni = anom.rolling(time=3, center=True).mean()
            oni_vals = oni.values

            valid = ~np.isnan(oni_vals)
            elnino = (oni_vals > 0.5) & valid
            lanina = (oni_vals < -0.5) & valid
            neutral = (~(oni_vals > 0.5)) & (~(oni_vals < -0.5)) & valid

            ref[model] = {
                'wbt_p90_elnino_mean': float(np.mean(wbt_p90[elnino])),
                'wbt_p90_lanina_mean': float(np.mean(wbt_p90[lanina])),
                'wbt_p90_neutral_mean': float(np.mean(wbt_p90[neutral])),
                'elnino_month_count': int(np.sum(elnino)),
                'lanina_month_count': int(np.sum(lanina)),
            }
        return ref

    @pytest.mark.parametrize("model", MODELS)
    def test_wbt_p90_elnino(self, results, reference, model):
        actual = results['model_stats'][model]['wbt_p90_elnino_mean']
        expected = reference[model]['wbt_p90_elnino_mean']
        assert abs(actual - expected) < 0.1, \
            f"{model} El Nino WBT P90: {actual:.4f} vs expected {expected:.4f}"

    @pytest.mark.parametrize("model", MODELS)
    def test_wbt_p90_lanina(self, results, reference, model):
        actual = results['model_stats'][model]['wbt_p90_lanina_mean']
        expected = reference[model]['wbt_p90_lanina_mean']
        assert abs(actual - expected) < 0.1, \
            f"{model} La Nina WBT P90: {actual:.4f} vs expected {expected:.4f}"

    @pytest.mark.parametrize("model", MODELS)
    def test_wbt_p90_neutral(self, results, reference, model):
        actual = results['model_stats'][model]['wbt_p90_neutral_mean']
        expected = reference[model]['wbt_p90_neutral_mean']
        assert abs(actual - expected) < 0.1, \
            f"{model} Neutral WBT P90: {actual:.4f} vs expected {expected:.4f}"

    @pytest.mark.parametrize("model", MODELS)
    def test_elnino_month_count(self, results, reference, model):
        actual = results['model_stats'][model]['elnino_month_count']
        expected = reference[model]['elnino_month_count']
        assert abs(actual - expected) <= 5, \
            f"{model} El Nino months: {actual} vs expected {expected}"

    @pytest.mark.parametrize("model", MODELS)
    def test_lanina_month_count(self, results, reference, model):
        actual = results['model_stats'][model]['lanina_month_count']
        expected = reference[model]['lanina_month_count']
        assert abs(actual - expected) <= 5, \
            f"{model} La Nina months: {actual} vs expected {expected}"


class TestEnsembleConsistency:
    """Verify ensemble stats are internally consistent with per-model values."""

    @pytest.fixture(scope='class')
    def results(self):
        with open('/app/results.json') as f:
            return json.load(f)

    @pytest.mark.parametrize("phase", ['elnino', 'lanina', 'neutral'])
    def test_ensemble_mean(self, results, phase):
        key = f'wbt_p90_{phase}_mean'
        vals = [results['model_stats'][m][key] for m in MODELS]
        expected = float(np.mean(vals))
        actual = results['ensemble'][key]
        assert abs(actual - expected) < 0.01, \
            f"Ensemble {phase} mean: {actual:.4f} vs expected {expected:.4f}"

    @pytest.mark.parametrize("phase", ['elnino', 'lanina', 'neutral'])
    def test_ensemble_std(self, results, phase):
        key_mean = f'wbt_p90_{phase}_mean'
        key_std = f'wbt_p90_{phase}_std'
        vals = [results['model_stats'][m][key_mean] for m in MODELS]
        expected = float(np.std(vals, ddof=0))
        actual = results['ensemble'][key_std]
        assert abs(actual - expected) < 0.01, \
            f"Ensemble {phase} std: {actual:.6f} vs expected {expected:.6f}"


class TestPhysicalPlausibility:
    @pytest.fixture(scope='class')
    def results(self):
        with open('/app/results.json') as f:
            return json.load(f)

    @pytest.mark.parametrize("model", MODELS)
    def test_wbt_range(self, results, model):
        stats = results['model_stats'][model]
        for key in ['wbt_p90_elnino_mean', 'wbt_p90_lanina_mean', 'wbt_p90_neutral_mean']:
            val = stats[key]
            assert 10 < val < 35, \
                f"{model} {key} = {val:.2f} outside plausible range [10, 35]"

    @pytest.mark.parametrize("model", MODELS)
    def test_enso_month_counts_reasonable(self, results, model):
        stats = results['model_stats'][model]
        total = stats['elnino_month_count'] + stats['lanina_month_count']
        # Should not exceed total months (780) minus 2 NaN edges
        assert total < 778, f"{model}: El Nino + La Nina = {total}, exceeds maximum"
        # Should have meaningful ENSO phases (at least 30 months each)
        assert stats['elnino_month_count'] > 30, \
            f"{model}: too few El Nino months ({stats['elnino_month_count']})"
        assert stats['lanina_month_count'] > 30, \
            f"{model}: too few La Nina months ({stats['lanina_month_count']})"
