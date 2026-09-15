"""Tests for CMIP6 ensemble climate risk analysis pipeline."""

import json
import os

import numpy as np
import pytest
import zarr

RESULTS_PATH = "/app/results.json"
ZARR_DIR = "/app/data/zarr"

MODELS = ["CESM2-TEST", "GFDL-TEST", "MIROC-TEST"]
EXPERIMENTS = ["historical", "ssp245", "ssp585"]


def stull_wbt(T_c, RH):
    """Reference Stull (2011) wet-bulb temperature approximation."""
    return (
        T_c * np.arctan(0.151977 * np.sqrt(RH + 8.313659))
        + np.arctan(T_c + RH)
        - np.arctan(RH - 1.676331)
        + 0.00391838 * RH**1.5 * np.arctan(0.023101 * RH)
        - 4.686035
    )


def area_weighted_percentile(data_2d, lat, percentile):
    """Compute area-weighted percentile from a 2D (lat, lon) field."""
    cos_lat = np.cos(np.deg2rad(lat))
    weights = np.broadcast_to(cos_lat[:, np.newaxis], data_2d.shape)
    flat_d = data_2d.ravel()
    flat_w = weights.ravel()
    mask = ~np.isnan(flat_d)
    flat_d, flat_w = flat_d[mask], flat_w[mask]
    idx = np.argsort(flat_d)
    sd, sw = flat_d[idx], flat_w[idx]
    cum = np.cumsum(sw)
    cum_norm = (cum - 0.5 * sw) / cum[-1]
    return float(np.interp(percentile / 100.0, cum_norm, sd))


def load_zarr_hurs(store):
    """Load humidity data, converting to percent if stored as fraction."""
    hurs = np.array(store["hurs"])
    units = dict(store["hurs"].attrs).get("units", "%")
    if units in ("1", "fraction"):
        hurs = hurs * 100.0
    return hurs


def compute_oni_reference():
    """Independently compute ONI from raw Zarr data."""
    store = zarr.open(os.path.join(ZARR_DIR, "CESM2-TEST_historical_tos"), "r")
    tos = np.array(store["tos"])
    lat = np.array(store["lat"])
    lon = np.array(store["lon"])

    lat_mask = np.abs(lat) <= 5.0
    lon_mask = (lon >= 190.0) & (lon <= 240.0)

    cos_lat = np.cos(np.deg2rad(lat[lat_mask]))
    nino_sst = tos[:, lat_mask][:, :, lon_mask]
    weights = np.broadcast_to(cos_lat[:, np.newaxis], nino_sst.shape[1:])

    nino34_ts = np.array(
        [np.average(nino_sst[t], weights=weights) for t in range(nino_sst.shape[0])]
    )

    clim = np.array([np.mean(nino34_ts[m::12]) for m in range(12)])
    anom = np.array([nino34_ts[i] - clim[i % 12] for i in range(len(nino34_ts))])

    oni = np.full(len(anom), np.nan)
    for i in range(1, len(anom) - 1):
        oni[i] = np.mean(anom[i - 1 : i + 2])

    return oni


def count_events(oni, threshold, direction):
    """Count ENSO events: direction='above' for El Nino, 'below' for La Nina."""
    count = 0
    consec = 0
    in_evt = False
    for v in oni:
        if np.isnan(v):
            consec = 0
            in_evt = False
            continue
        cond = v > threshold if direction == "above" else v < threshold
        if cond:
            consec += 1
            if consec >= 5 and not in_evt:
                count += 1
                in_evt = True
        else:
            consec = 0
            in_evt = False
    return count


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), "results.json not found at /app/results.json"
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ── WBT Reference ──


class TestWBTReference:
    def test_reference_value_precise(self, results):
        """WBT(20°C, 50%) must match Stull (2011) formula."""
        expected = float(stull_wbt(20.0, 50.0))
        actual = results["wbt_reference_check"]
        assert abs(actual - expected) < 0.05, (
            f"WBT reference: got {actual}, expected ~{expected:.4f}"
        )

    def test_reference_approximately_13_7(self, results):
        """Known result: ~13.7°C for T=20, RH=50."""
        assert abs(results["wbt_reference_check"] - 13.7) < 0.2


# ── WBT Extremes ──


class TestWBTExtremes:
    def test_structure_complete(self, results):
        wbt = results["wbt_extremes"]
        for m in MODELS:
            assert m in wbt, f"Missing model {m}"
            for e in EXPERIMENTS:
                assert e in wbt[m], f"Missing experiment {e} for {m}"
                assert isinstance(wbt[m][e], (int, float))

    def test_reasonable_range(self, results):
        """WBT extremes should be in physically plausible range (°C)."""
        for m in MODELS:
            for e in EXPERIMENTS:
                val = results["wbt_extremes"][m][e]
                assert 0 < val < 50, f"WBT extreme {val} out of range for {m}/{e}"

    def test_unit_conversion_applied(self, results):
        """Values in Kelvin would be ~280+; in Celsius they should be < 50."""
        for m in MODELS:
            for e in EXPERIMENTS:
                assert results["wbt_extremes"][m][e] < 50, (
                    "Values suggest Kelvin was used instead of Celsius"
                )

    def test_scenario_ordering(self, results):
        """Warmer scenarios should produce higher WBT extremes."""
        wbt = results["wbt_extremes"]
        for m in MODELS:
            assert wbt[m]["ssp585"] > wbt[m]["ssp245"], (
                f"{m}: ssp585 should exceed ssp245"
            )
            assert wbt[m]["ssp245"] > wbt[m]["historical"], (
                f"{m}: ssp245 should exceed historical"
            )

    def test_cross_model_consistency(self, results):
        """Models should produce WBT in similar ranges (catches unit conversion errors)."""
        wbt = results["wbt_extremes"]
        for e in EXPERIMENTS:
            vals = [wbt[m][e] for m in MODELS]
            spread = max(vals) - min(vals)
            assert spread < 8.0, (
                f"Cross-model WBT spread too large for {e}: {spread:.1f}°C "
                "(possible humidity unit conversion error)"
            )

    def test_area_weighted_correctness_cesm2(self, results):
        """Independently compute area-weighted WBT extreme for CESM2-TEST."""
        store = zarr.open(os.path.join(ZARR_DIR, "CESM2-TEST_historical"), "r")
        tas = np.array(store["tas"]) - 273.15
        hurs = load_zarr_hurs(store)
        lat = np.array(store["lat"])

        wbt = stull_wbt(tas, hurs)

        p90_last12 = []
        for t in range(wbt.shape[0] - 12, wbt.shape[0]):
            p90_last12.append(area_weighted_percentile(wbt[t], lat, 90))

        expected = np.mean(p90_last12)
        actual = results["wbt_extremes"]["CESM2-TEST"]["historical"]
        assert abs(actual - expected) < 0.5, (
            f"CESM2-TEST historical: got {actual:.3f}, expected {expected:.3f}"
        )

    def test_humidity_unit_awareness(self, results):
        """Verify MIROC-TEST WBT is correct despite different humidity units."""
        store = zarr.open(os.path.join(ZARR_DIR, "MIROC-TEST_historical"), "r")
        tas = np.array(store["tas"]) - 273.15
        hurs = load_zarr_hurs(store)
        lat = np.array(store["lat"])

        wbt = stull_wbt(tas, hurs)

        p90_last12 = []
        for t in range(wbt.shape[0] - 12, wbt.shape[0]):
            p90_last12.append(area_weighted_percentile(wbt[t], lat, 90))

        expected = np.mean(p90_last12)
        actual = results["wbt_extremes"]["MIROC-TEST"]["historical"]
        assert abs(actual - expected) < 0.5, (
            f"MIROC-TEST historical: got {actual:.3f}, expected {expected:.3f} "
            "(check humidity unit conversion)"
        )

    def test_area_weighting_matters(self, results):
        """Verify that area weighting changes the result (not a simple percentile)."""
        store = zarr.open(os.path.join(ZARR_DIR, "CESM2-TEST_historical"), "r")
        tas = np.array(store["tas"]) - 273.15
        hurs = load_zarr_hurs(store)
        lat = np.array(store["lat"])

        wbt = stull_wbt(tas, hurs)

        unweighted_p90 = []
        for t in range(wbt.shape[0] - 12, wbt.shape[0]):
            unweighted_p90.append(float(np.nanpercentile(wbt[t], 90)))
        unweighted_avg = np.mean(unweighted_p90)

        weighted_p90 = []
        for t in range(wbt.shape[0] - 12, wbt.shape[0]):
            weighted_p90.append(area_weighted_percentile(wbt[t], lat, 90))
        weighted_avg = np.mean(weighted_p90)

        assert abs(weighted_avg - unweighted_avg) > 0.01, (
            "Weighted and unweighted 90th percentiles should differ"
        )

        actual = results["wbt_extremes"]["CESM2-TEST"]["historical"]
        err_weighted = abs(actual - weighted_avg)
        err_unweighted = abs(actual - unweighted_avg)
        assert err_weighted < err_unweighted or err_weighted < 0.5, (
            f"Result {actual:.3f} appears unweighted "
            f"(weighted={weighted_avg:.3f}, unweighted={unweighted_avg:.3f})"
        )


# ── Ensemble Mean ──


class TestEnsembleMean:
    def test_structure(self, results):
        ens = results["ensemble_mean_wbt_extremes"]
        for e in EXPERIMENTS:
            assert e in ens, f"Missing experiment {e}"
            assert isinstance(ens[e], (int, float))

    def test_consistency_with_individual(self, results):
        """Ensemble mean must equal arithmetic mean of individual model values."""
        wbt = results["wbt_extremes"]
        ens = results["ensemble_mean_wbt_extremes"]
        for e in EXPERIMENTS:
            expected = np.mean([wbt[m][e] for m in MODELS])
            assert abs(ens[e] - expected) < 0.01, (
                f"Ensemble mean for {e}: {ens[e]:.4f} != {expected:.4f}"
            )

    def test_scenario_ordering(self, results):
        ens = results["ensemble_mean_wbt_extremes"]
        assert ens["ssp585"] > ens["ssp245"] > ens["historical"]


# ── Warming Amplification ──


class TestWarmingAmplification:
    def test_structure(self, results):
        assert "warming_amplification" in results
        wa = results["warming_amplification"]
        for m in MODELS:
            assert m in wa, f"Missing model {m}"
            assert isinstance(wa[m], (int, float))

    def test_positive(self, results):
        """Warming should increase WBT extremes, so amplification > 0."""
        wa = results["warming_amplification"]
        for m in MODELS:
            assert wa[m] > 0, f"Warming amplification should be positive for {m}"

    def test_reasonable_range(self, results):
        """Amplification ratio should be physically plausible."""
        wa = results["warming_amplification"]
        for m in MODELS:
            assert 0.1 < wa[m] < 3.0, (
                f"Amplification {wa[m]:.3f} out of expected range for {m}"
            )

    def test_independent_computation(self, results):
        """Independently compute warming amplification for CESM2-TEST."""
        global_means = {}
        for exp in ["historical", "ssp585"]:
            store = zarr.open(os.path.join(ZARR_DIR, f"CESM2-TEST_{exp}"), "r")
            tas = np.array(store["tas"]) - 273.15
            lat = np.array(store["lat"])
            cos_lat = np.cos(np.deg2rad(lat))
            weights = np.broadcast_to(cos_lat[:, np.newaxis], tas.shape[1:])

            means = []
            for t in range(tas.shape[0] - 12, tas.shape[0]):
                means.append(float(np.average(tas[t], weights=weights)))
            global_means[exp] = np.mean(means)

        delta_t = global_means["ssp585"] - global_means["historical"]
        wbt = results["wbt_extremes"]["CESM2-TEST"]
        delta_wbt = wbt["ssp585"] - wbt["historical"]
        expected_wa = delta_wbt / delta_t

        actual_wa = results["warming_amplification"]["CESM2-TEST"]
        assert abs(actual_wa - expected_wa) < 0.1, (
            f"CESM2-TEST amplification: got {actual_wa:.4f}, expected {expected_wa:.4f}"
        )


# ── ONI ──


class TestONI:
    def test_oni_structure(self, results):
        assert "oni" in results
        assert "oni_values" in results["oni"]

    def test_oni_length(self, results):
        oni_vals = results["oni"]["oni_values"]
        assert len(oni_vals) == 240, f"Expected 240 ONI values, got {len(oni_vals)}"

    def test_oni_edges_null(self, results):
        """First and last values should be null (centered running mean)."""
        oni_vals = results["oni"]["oni_values"]
        assert oni_vals[0] is None, "First ONI value should be null"
        assert oni_vals[-1] is None, "Last ONI value should be null"

    def test_oni_range(self, results):
        oni_vals = [v for v in results["oni"]["oni_values"] if v is not None]
        assert all(-5 < v < 5 for v in oni_vals), "ONI values out of range"

    def test_oni_correctness(self, results):
        """Compare agent ONI values against independently computed reference."""
        ref_oni = compute_oni_reference()
        agent_oni = results["oni"]["oni_values"]

        mismatches = 0
        compared = 0
        for i in range(1, len(ref_oni) - 1):
            if np.isnan(ref_oni[i]) or agent_oni[i] is None:
                continue
            compared += 1
            if abs(float(agent_oni[i]) - float(ref_oni[i])) > 0.15:
                mismatches += 1

        assert compared > 200, f"Too few valid ONI comparisons: {compared}"
        assert mismatches < compared * 0.05, (
            f"Too many ONI mismatches: {mismatches}/{compared}"
        )


# ── ENSO Events ──


class TestENSOEvents:
    def test_event_structure(self, results):
        events = results["enso_events"]
        assert "el_nino_count" in events
        assert "la_nina_count" in events
        assert isinstance(events["el_nino_count"], int)
        assert isinstance(events["la_nina_count"], int)

    def test_events_detected(self, results):
        events = results["enso_events"]
        assert events["el_nino_count"] > 0, "Should detect El Niño events"
        assert events["la_nina_count"] > 0, "Should detect La Niña events"

    def test_event_counts_match_reference(self, results):
        """Independently count events and compare."""
        ref_oni = compute_oni_reference()

        ref_en = count_events(ref_oni, 0.5, "above")
        ref_ln = count_events(ref_oni, -0.5, "below")

        events = results["enso_events"]
        assert abs(events["el_nino_count"] - ref_en) <= 1, (
            f"El Niño count: agent={events['el_nino_count']}, reference={ref_en}"
        )
        assert abs(events["la_nina_count"] - ref_ln) <= 1, (
            f"La Niña count: agent={events['la_nina_count']}, reference={ref_ln}"
        )
