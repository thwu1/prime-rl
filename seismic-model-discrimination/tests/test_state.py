
"""
Verification tests for seismic network calibration task.

All expected values are recomputed independently using ObsPy — nothing
is hardcoded from the data generation process.
"""

import json
import pytest
import numpy as np
from obspy.taup import TauPyModel
from obspy.geodetics import locations2degrees, gps2dist_azimuth


# ---- Fixtures ----

@pytest.fixture(scope="module")
def input_data():
    with open("/app/data/stations.json") as f:
        stations = json.load(f)
    with open("/app/data/events.json") as f:
        events = json.load(f)
    with open("/app/data/observations.json") as f:
        observations = json.load(f)
    return stations, events, observations


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def theoretical_times(input_data):
    """Compute theoretical travel times for all three standard 1D models."""
    stations, events, observations = input_data
    model_cache = {
        name: TauPyModel(model=name) for name in ["iasp91", "ak135", "prem"]
    }

    times = {}
    for model_name, model in model_cache.items():
        times[model_name] = {}
        for i, obs in enumerate(observations):
            ev = events[obs["event_id"]]
            st = stations[obs["station"]]
            dist = float(locations2degrees(
                ev["lat"], ev["lon"], st["lat"], st["lon"]
            ))
            try:
                arrivals = model.get_travel_times(
                    source_depth_in_km=ev["depth_km"],
                    distance_in_degree=dist,
                    phase_list=[obs["phase"]]
                )
                if arrivals:
                    times[model_name][i] = float(arrivals[0].time)
            except Exception:
                continue
    return times


@pytest.fixture(scope="module")
def expected_outliers(input_data, theoretical_times):
    """Identify observations that are unambiguously outliers.

    Any observation with |residual| > 3.0 seconds from the ak135 prediction
    is a gross error (since noise sigma < 0.2s and true station corrections
    are < 1.0s, clean residuals never exceed ~1.5s).
    """
    _, _, observations = input_data
    outliers = []
    for i, obs in enumerate(observations):
        if i not in theoretical_times["ak135"]:
            continue
        resid = obs["arrival_time_sec"] - theoretical_times["ak135"][i]
        if abs(resid) > 3.0:
            outliers.append(i)
    return outliers


@pytest.fixture(scope="module")
def expected_corrections(input_data, theoretical_times, expected_outliers):
    """Compute station corrections using ak135, excluding known outliers."""
    stations, _, observations = input_data
    outlier_set = set(expected_outliers)

    corrections = {}
    for sta_name in stations:
        corrections[sta_name] = {}
        for phase in ["P", "S"]:
            residuals = []
            for i, obs in enumerate(observations):
                if i in outlier_set:
                    continue
                if obs["station"] != sta_name or obs["phase"] != phase:
                    continue
                if i in theoretical_times["ak135"]:
                    resid = obs["arrival_time_sec"] - theoretical_times["ak135"][i]
                    residuals.append(resid)
            if residuals:
                corrections[sta_name][phase] = float(np.mean(residuals))
    return corrections


# ---- Tests ----

class TestResultsStructure:
    def test_results_file_exists(self, results):
        assert results is not None
        assert isinstance(results, dict)

    def test_required_keys_present(self, results):
        for key in [
            "reference_model", "station_corrections", "outlier_indices",
            "clean_rms", "event_quality",
        ]:
            assert key in results, f"Missing key: {key}"

    def test_station_corrections_complete(self, results, input_data):
        stations = input_data[0]
        for sta in stations:
            assert sta in results["station_corrections"], \
                f"Missing corrections for {sta}"
            for phase in ["P", "S"]:
                assert phase in results["station_corrections"][sta], \
                    f"Missing {phase} correction for {sta}"

    def test_event_quality_complete(self, results, input_data):
        events = input_data[1]
        for ev_id in events:
            assert ev_id in results["event_quality"], \
                f"Missing quality for event {ev_id}"
            q = results["event_quality"][ev_id]
            assert "azimuthal_gap" in q
            assert "quality_class" in q
            assert q["quality_class"] in ["A", "B", "C", "D"]


class TestModelIdentification:
    def test_correct_model(self, results):
        """The data was generated with ak135."""
        assert results["reference_model"] == "ak135"

    def test_model_beats_alternatives(self, results, input_data, theoretical_times,
                                       expected_outliers):
        """ak135 should have lower clean-data RMS than other standard models."""
        observations = input_data[2]
        outlier_set = set(expected_outliers)

        rms = {}
        for model_name in ["iasp91", "ak135", "prem"]:
            residuals = []
            for i, obs in enumerate(observations):
                if i in outlier_set or i not in theoretical_times[model_name]:
                    continue
                resid = obs["arrival_time_sec"] - theoretical_times[model_name][i]
                residuals.append(resid)
            if residuals:
                rms[model_name] = float(
                    np.sqrt(np.mean(np.array(residuals) ** 2))
                )

        assert rms["ak135"] <= rms["iasp91"], \
            f"ak135 RMS ({rms['ak135']:.4f}) should be <= iasp91 ({rms['iasp91']:.4f})"
        assert rms["ak135"] <= rms["prem"], \
            f"ak135 RMS ({rms['ak135']:.4f}) should be <= prem ({rms['prem']:.4f})"


class TestOutlierDetection:
    def test_detects_all_true_outliers(self, results, expected_outliers):
        """Every observation with a residual > 3s must be flagged."""
        detected = set(results["outlier_indices"])
        for idx in expected_outliers:
            assert idx in detected, \
                f"Observation {idx} is a clear outlier (>3s residual) but was not detected"

    def test_no_excessive_false_positives(self, results, expected_outliers):
        """Detected outliers should not vastly exceed the true count."""
        n_detected = len(results["outlier_indices"])
        n_expected = len(expected_outliers)
        assert n_detected <= n_expected * 2.5, \
            f"Too many outliers detected ({n_detected}) vs {n_expected} expected"

    def test_outlier_indices_valid(self, results, input_data):
        n_obs = len(input_data[2])
        for idx in results["outlier_indices"]:
            assert isinstance(idx, int), f"Outlier index must be int, got {type(idx)}"
            assert 0 <= idx < n_obs, f"Invalid outlier index: {idx}"

    def test_outlier_indices_unique(self, results):
        indices = results["outlier_indices"]
        assert len(indices) == len(set(indices)), "Duplicate outlier indices"


class TestStationCorrections:
    def test_p_corrections_match(self, results, expected_corrections, input_data):
        """P corrections should match independently computed values (centered)."""
        sta_list = sorted(input_data[0].keys())
        exp_vals = np.array([expected_corrections[s].get("P", 0.0) for s in sta_list])
        got_vals = np.array([results["station_corrections"][s]["P"] for s in sta_list])

        exp_centered = exp_vals - np.mean(exp_vals)
        got_centered = got_vals - np.mean(got_vals)

        for i, sta in enumerate(sta_list):
            assert abs(exp_centered[i] - got_centered[i]) < 0.25, \
                f"P correction for {sta}: expected ~{exp_centered[i]:.3f}, " \
                f"got {got_centered[i]:.3f}"

    def test_s_corrections_match(self, results, expected_corrections, input_data):
        """S corrections should match independently computed values (centered)."""
        sta_list = sorted(input_data[0].keys())
        exp_vals = np.array([expected_corrections[s].get("S", 0.0) for s in sta_list])
        got_vals = np.array([results["station_corrections"][s]["S"] for s in sta_list])

        exp_centered = exp_vals - np.mean(exp_vals)
        got_centered = got_vals - np.mean(got_vals)

        for i, sta in enumerate(sta_list):
            assert abs(exp_centered[i] - got_centered[i]) < 0.30, \
                f"S correction for {sta}: expected ~{exp_centered[i]:.3f}, " \
                f"got {got_centered[i]:.3f}"

    def test_corrections_reasonable_magnitude(self, results):
        for sta, corr in results["station_corrections"].items():
            for phase in ["P", "S"]:
                assert abs(corr[phase]) < 3.0, \
                    f"{phase} correction for {sta} ({corr[phase]:.2f}s) too large"


class TestCleanRMS:
    def test_rms_positive(self, results):
        assert results["clean_rms"] > 0

    def test_rms_near_noise_level(self, results):
        """After calibration and outlier removal, RMS should approach noise."""
        assert results["clean_rms"] < 0.35, \
            f"Clean RMS ({results['clean_rms']:.4f}) should be near noise level"

    def test_rms_improved_vs_raw(self, results, input_data, theoretical_times):
        """Clean RMS should be substantially better than raw uncorrected RMS."""
        observations = input_data[2]
        raw_residuals = []
        for i, obs in enumerate(observations):
            if i in theoretical_times["ak135"]:
                resid = obs["arrival_time_sec"] - theoretical_times["ak135"][i]
                raw_residuals.append(resid)
        raw_rms = float(np.sqrt(np.mean(np.array(raw_residuals) ** 2)))
        assert results["clean_rms"] < raw_rms * 0.5, \
            f"Clean RMS ({results['clean_rms']:.4f}) should be << raw ({raw_rms:.4f})"


class TestAzimuthalGap:
    def test_quality_classes_valid(self, results, input_data):
        for ev_id in input_data[1]:
            q = results["event_quality"][ev_id]["quality_class"]
            assert q in ["A", "B", "C", "D"], \
                f"Invalid quality class '{q}' for {ev_id}"

    def test_gaps_correct(self, results, input_data):
        """Independently compute azimuthal gaps and compare."""
        stations, events, observations = input_data

        for ev_id, event in events.items():
            event_stations = set()
            for obs in observations:
                if obs["event_id"] == ev_id:
                    event_stations.add(obs["station"])

            azimuths = []
            for sta_name in sorted(event_stations):
                sta = stations[sta_name]
                _, az, _ = gps2dist_azimuth(
                    event["lat"], event["lon"],
                    sta["lat"], sta["lon"]
                )
                azimuths.append(az)

            azimuths_sorted = sorted(azimuths)
            if len(azimuths_sorted) < 2:
                expected_gap = 360.0
            else:
                gaps = [
                    azimuths_sorted[j + 1] - azimuths_sorted[j]
                    for j in range(len(azimuths_sorted) - 1)
                ]
                gaps.append(360.0 - azimuths_sorted[-1] + azimuths_sorted[0])
                expected_gap = max(gaps)

            got_gap = results["event_quality"][ev_id]["azimuthal_gap"]
            assert abs(got_gap - expected_gap) < 2.0, \
                f"Gap for {ev_id}: expected {expected_gap:.1f}, got {got_gap:.1f}"

            # Verify quality class consistency
            if expected_gap < 90:
                expected_class = "A"
            elif expected_gap < 180:
                expected_class = "B"
            elif expected_gap < 270:
                expected_class = "C"
            else:
                expected_class = "D"
            assert results["event_quality"][ev_id]["quality_class"] == expected_class, \
                f"Quality for {ev_id}: expected {expected_class}, " \
                f"got {results['event_quality'][ev_id]['quality_class']}"
