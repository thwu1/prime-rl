
"""Tests for CMIP6 ensemble evaluation and weighted projection pipeline."""

import json
import os
import numpy as np
import zarr
import pytest


RESULTS_PATH = "/app/results.json"
CATALOG_PATH = "/app/data/catalog.json"
MODELS = ["CESM2", "GFDL", "MIROC", "UKESM"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def catalog():
    with open(CATALOG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ref_data(catalog):
    """Load reference historical tas and latitude."""
    r = zarr.open(catalog["reference"]["historical"], "r")
    return r["tas"][:], r["lat"][:]


@pytest.fixture(scope="module")
def corrected(catalog):
    """Independently load and correct all model historical tas to degC on standard grid."""
    out = {}
    for model in MODELS:
        r = zarr.open(catalog[model]["historical"], "r")
        tas = r["tas"][:]
        lon = r["lon"][:]
        # Infer true unit from data range
        med = float(np.nanmedian(tas))
        tas_c = (tas - 273.15) if med > 200 else tas.copy()
        # Remap 0-360 longitude to standard
        if float(lon.min()) >= 0:
            slon = np.where(lon > 180, lon - 360, lon)
            idx = np.argsort(slon)
            tas_c = tas_c[:, :, idx]
        out[model] = tas_c
    return out


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_top_level_keys(self, results):
        required = [
            "model_diagnostics", "skill_metrics", "model_ranking",
            "ensemble_weights", "equal_weight_rmse",
            "weighted_ensemble_rmse", "weighted_beats_equal",
            "projected_warming",
        ]
        for k in required:
            assert k in results, f"Missing top-level key: {k}"

    def test_all_models_in_all_sections(self, results):
        for model in MODELS:
            assert model in results["model_diagnostics"], f"{model} missing from model_diagnostics"
            assert model in results["skill_metrics"], f"{model} missing from skill_metrics"
            assert model in results["ensemble_weights"], f"{model} missing from ensemble_weights"
            assert model in results["projected_warming"], f"{model} missing from projected_warming"

    def test_diagnostic_keys_complete(self, results):
        """Every model diagnostic must include both temperature and humidity fields."""
        required_keys = [
            "tas_metadata_unit", "tas_inferred_unit", "needs_unit_correction",
            "hurs_metadata_unit", "hurs_is_fractional",
            "lon_convention", "tas_has_nan", "tas_nan_month_count",
        ]
        for model in MODELS:
            d = results["model_diagnostics"][model]
            for k in required_keys:
                assert k in d, f"{model} missing diagnostic key: {k}"


# ---------------------------------------------------------------------------
# Temperature diagnostics tests
# ---------------------------------------------------------------------------

class TestTemperatureDiagnostics:
    def test_gfdl_metadata_lie_detected(self, results):
        """GFDL data is stored in degC but metadata claims K. Agent must detect this."""
        d = results["model_diagnostics"]["GFDL"]
        assert d["tas_metadata_unit"] == "K", "GFDL Zarr attrs should say K"
        assert d["tas_inferred_unit"] == "degC", (
            "GFDL data values ~30 are physically impossible as K; must infer degC"
        )
        assert d["needs_unit_correction"] is True

    def test_cesm2_correct_K(self, results):
        """CESM2 stores data in K and correctly labels it K."""
        d = results["model_diagnostics"]["CESM2"]
        assert d["tas_metadata_unit"] == "K"
        assert d["tas_inferred_unit"] == "K"
        assert d["needs_unit_correction"] is False

    def test_ukesm_unit_correct_degc(self, results):
        """UKESM stores data in degC and correctly labels it degC."""
        d = results["model_diagnostics"]["UKESM"]
        assert d["tas_metadata_unit"] == "degC"
        assert d["tas_inferred_unit"] == "degC"
        assert d["needs_unit_correction"] is False

    def test_miroc_unit_correct_k(self, results):
        """MIROC stores data in K and correctly labels it K."""
        d = results["model_diagnostics"]["MIROC"]
        assert d["tas_metadata_unit"] == "K"
        assert d["tas_inferred_unit"] == "K"
        assert d["needs_unit_correction"] is False

    def test_gfdl_metadata_lie_verified(self, catalog):
        """Independently verify GFDL metadata says K but data is degC-range."""
        r = zarr.open(catalog["GFDL"]["historical"], "r")
        assert str(r["tas"].attrs["units"]) == "K", "GFDL attrs must say K"
        med = float(np.nanmedian(r["tas"][:]))
        assert med < 100, f"GFDL tas median {med:.1f} should be in degC range (< 100)"

    def test_ukesm_lon_convention(self, results):
        """UKESM uses 0-to-360 longitude convention."""
        assert results["model_diagnostics"]["UKESM"]["lon_convention"] == "0_to_360"

    def test_standard_lon_models(self, results):
        """CESM2, GFDL, MIROC use standard longitude convention."""
        for m in ["CESM2", "GFDL", "MIROC"]:
            assert results["model_diagnostics"][m]["lon_convention"] == "standard", (
                f"{m} should have standard longitude convention"
            )

    def test_miroc_nan_detection(self, results):
        """MIROC historical has 12 months of NaN data."""
        d = results["model_diagnostics"]["MIROC"]
        assert d["tas_has_nan"] is True
        assert d["tas_nan_month_count"] == 12

    def test_no_false_nan_detection(self, results):
        """CESM2, GFDL, UKESM should have no NaN."""
        for m in ["CESM2", "GFDL", "UKESM"]:
            d = results["model_diagnostics"][m]
            assert d["tas_has_nan"] is False, f"{m} should have no NaN"
            assert d["tas_nan_month_count"] == 0, f"{m} nan_month_count should be 0"


# ---------------------------------------------------------------------------
# Humidity diagnostics tests
# ---------------------------------------------------------------------------

class TestHumidityDiagnostics:
    def test_ukesm_fractional_humidity(self, results):
        """UKESM humidity is stored as fractions (0-1), not percent."""
        d = results["model_diagnostics"]["UKESM"]
        assert d["hurs_is_fractional"] is True
        assert d["hurs_metadata_unit"] == "1"

    def test_percent_humidity_models(self, results):
        """CESM2, GFDL, MIROC store humidity in percent."""
        for m in ["CESM2", "GFDL", "MIROC"]:
            d = results["model_diagnostics"][m]
            assert d["hurs_is_fractional"] is False, f"{m} hurs should not be fractional"
            assert d["hurs_metadata_unit"] == "%", f"{m} hurs_metadata_unit should be '%'"

    def test_ukesm_fractional_verified(self, catalog):
        """Independently verify UKESM humidity values are in 0-1 range."""
        r = zarr.open(catalog["UKESM"]["historical"], "r")
        hurs = r["hurs"][:]
        med = float(np.nanmedian(hurs))
        assert med < 2.0, f"UKESM hurs median {med:.3f} should be < 2 (fractional)"
        assert str(r["hurs"].attrs["units"]) == "1"

    def test_percent_humidity_verified(self, catalog):
        """Independently verify non-UKESM models have percent humidity."""
        for model in ["CESM2", "GFDL", "MIROC"]:
            r = zarr.open(catalog[model]["historical"], "r")
            hurs = r["hurs"][:]
            med = float(np.nanmedian(hurs))
            assert med > 2.0, f"{model} hurs median {med:.3f} should be > 2 (percent)"


# ---------------------------------------------------------------------------
# Skill metric tests
# ---------------------------------------------------------------------------

class TestSkillMetrics:
    def test_rmse_positive(self, results):
        for model in MODELS:
            assert results["skill_metrics"][model]["rmse"] > 0, f"{model} RMSE not positive"

    def test_pattern_corr_range(self, results):
        for model in MODELS:
            pc = results["skill_metrics"][model]["pattern_correlation"]
            assert -1.0 <= pc <= 1.0, f"{model} pattern_corr {pc} out of [-1,1]"

    def test_pattern_corr_high(self, results):
        """All models share the same latitude-dependent base temperature pattern,
        so pattern correlation with the reference should be very high."""
        for model in MODELS:
            pc = results["skill_metrics"][model]["pattern_correlation"]
            assert pc > 0.9, f"{model} pattern_corr {pc} unexpectedly low"

    def test_bias_recomputed(self, results, ref_data, corrected):
        """Independently recompute mean bias and compare."""
        ref_tas, ref_lat = ref_data
        w = np.cos(np.deg2rad(ref_lat))
        for model in MODELS:
            diff = corrected[model] - ref_tas
            valid = ~np.any(np.isnan(diff.reshape(diff.shape[0], -1)), axis=1)
            dv = diff[valid]
            lon_mean = dv.mean(axis=2)
            bias_t = np.average(lon_mean, weights=w, axis=1)
            expected = float(bias_t.mean())
            actual = results["skill_metrics"][model]["mean_bias"]
            assert abs(actual - expected) < 0.05, (
                f"{model} bias mismatch: result={actual}, recomputed={expected:.4f}"
            )

    def test_rmse_recomputed(self, results, ref_data, corrected):
        """Independently recompute RMSE and compare."""
        ref_tas, ref_lat = ref_data
        w = np.cos(np.deg2rad(ref_lat))
        for model in MODELS:
            diff = corrected[model] - ref_tas
            valid = ~np.any(np.isnan(diff.reshape(diff.shape[0], -1)), axis=1)
            sq = diff[valid] ** 2
            sq_lon = sq.mean(axis=2)
            mse_t = np.average(sq_lon, weights=w, axis=1)
            expected = float(np.sqrt(mse_t.mean()))
            actual = results["skill_metrics"][model]["rmse"]
            assert abs(actual - expected) < 0.05, (
                f"{model} RMSE mismatch: result={actual}, recomputed={expected:.4f}"
            )

    def test_pattern_corr_recomputed(self, results, ref_data, corrected):
        """Independently recompute pattern correlation and compare."""
        ref_tas, ref_lat = ref_data
        w = np.cos(np.deg2rad(ref_lat))
        for model in MODELS:
            m_mean = np.nanmean(corrected[model], axis=0)
            r_mean = np.nanmean(ref_tas, axis=0)
            w2 = w[:, None] * np.ones(m_mean.shape[1])
            ws = w2.sum()
            mx = (w2 * m_mean).sum() / ws
            rx = (w2 * r_mean).sum() / ws
            num = (w2 * (m_mean - mx) * (r_mean - rx)).sum()
            dm = (w2 * (m_mean - mx) ** 2).sum()
            dr = (w2 * (r_mean - rx) ** 2).sum()
            expected = float(num / np.sqrt(dm * dr))
            actual = results["skill_metrics"][model]["pattern_correlation"]
            assert abs(actual - expected) < 0.01, (
                f"{model} pcorr mismatch: result={actual}, recomputed={expected:.4f}"
            )


# ---------------------------------------------------------------------------
# Ranking and weights tests
# ---------------------------------------------------------------------------

class TestModelRanking:
    def test_ranking_sorted_by_rmse(self, results):
        """Model ranking must be ascending by RMSE."""
        rmses = [results["skill_metrics"][m]["rmse"] for m in results["model_ranking"]]
        assert rmses == sorted(rmses), (
            f"Ranking not sorted by RMSE: {list(zip(results['model_ranking'], rmses))}"
        )

    def test_ranking_has_all_models(self, results):
        assert set(results["model_ranking"]) == set(MODELS)


class TestEnsembleWeights:
    def test_weights_sum_to_one(self, results):
        total = sum(results["ensemble_weights"][m] for m in MODELS)
        assert abs(total - 1.0) < 0.01, f"Weights sum to {total}, expected 1.0"

    def test_weights_inverse_rmse(self, results):
        """Weights must be proportional to inverse RMSE."""
        rmses = {m: results["skill_metrics"][m]["rmse"] for m in MODELS}
        inv = {m: 1.0 / rmses[m] for m in MODELS}
        inv_s = sum(inv.values())
        for m in MODELS:
            expected = inv[m] / inv_s
            actual = results["ensemble_weights"][m]
            assert abs(actual - expected) < 0.01, (
                f"{m} weight: result={actual}, expected={expected:.4f}"
            )


# ---------------------------------------------------------------------------
# Ensemble RMSE tests
# ---------------------------------------------------------------------------

class TestEnsemble:
    def test_ensemble_rmse_below_worst_model(self, results):
        """Both ensemble RMSE values should be below the worst individual model."""
        worst = max(results["skill_metrics"][m]["rmse"] for m in MODELS)
        assert results["equal_weight_rmse"] < worst, "Equal-weight ensemble worse than worst model"
        assert results["weighted_ensemble_rmse"] < worst, "Weighted ensemble worse than worst model"

    def test_weighted_beats_equal_consistent(self, results):
        """The boolean must match the actual RMSE comparison."""
        expected = results["weighted_ensemble_rmse"] < results["equal_weight_rmse"]
        assert results["weighted_beats_equal"] == expected


# ---------------------------------------------------------------------------
# Projected warming tests
# ---------------------------------------------------------------------------

class TestProjectedWarming:
    def test_warming_positive(self, results):
        """All models should show positive warming under SSP585."""
        for model in MODELS:
            assert results["projected_warming"][model] > 0, (
                f"{model} warming not positive: {results['projected_warming'][model]}"
            )

    def test_warming_order_follows_sensitivity(self, results):
        """Warming should follow sensitivity: UKESM(1.2) > MIROC(1.1) > CESM2(1.0) > GFDL(0.9)."""
        w = results["projected_warming"]
        assert w["UKESM"] > w["MIROC"] > w["CESM2"] > w["GFDL"], (
            f"Expected UKESM>MIROC>CESM2>GFDL, got "
            f"UKESM={w['UKESM']:.4f}, MIROC={w['MIROC']:.4f}, "
            f"CESM2={w['CESM2']:.4f}, GFDL={w['GFDL']:.4f}"
        )

    def test_weighted_ensemble_warming_consistent(self, results):
        """Weighted ensemble warming = sum(w_i * warming_i)."""
        wts = results["ensemble_weights"]
        expected = sum(results["projected_warming"][m] * wts[m] for m in MODELS)
        actual = results["projected_warming"]["weighted_ensemble"]
        assert abs(actual - expected) < 0.05, (
            f"Weighted ensemble warming: result={actual}, expected={expected:.4f}"
        )

    def test_warming_magnitudes_plausible(self, results):
        """Warming should be roughly 3-7 degC for SSP585 end-of-century."""
        for model in MODELS:
            w = results["projected_warming"][model]
            assert 2.0 < w < 10.0, f"{model} warming {w:.2f} outside plausible range"
