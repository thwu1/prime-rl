
"""
Tests for seismic event depth determination and phase identification.
Independently recomputes ground truth using ObsPy TauP at the known true depth.
"""
import json
import math
import os

import pytest
from obspy.taup import TauPyModel
from obspy.geodetics import gps2dist_azimuth, kilometers2degrees
from obspy import UTCDateTime


# Ground truth parameters
TRUE_DEPTH = 237.0
EVENT_LAT = 38.322
EVENT_LON = 142.369
ORIGIN_TIME = UTCDateTime("2024-01-15T12:30:45.000000Z")
MODEL_NAME = "iasp91"

STATIONS = {
    "MAJO": {"lat": 36.5457, "lon": 138.2041},
    "MDJ":  {"lat": 44.6160, "lon": 129.5917},
    "INCN": {"lat": 37.4776, "lon": 126.6249},
    "BJT":  {"lat": 40.0183, "lon": 116.1679},
    "ULN":  {"lat": 47.8651, "lon": 107.0532},
    "AAK":  {"lat": 42.6390, "lon": 74.4940},
    "ARU":  {"lat": 56.4302, "lon": 58.5625},
    "OBN":  {"lat": 55.1146, "lon": 36.5674},
}

CANDIDATE_PHASES = ["P", "pP", "sP", "PP", "S", "sS", "SS", "PcP", "ScP", "ScS"]


def _compute_ground_truth():
    """Compute the ground truth phase assignments using TauP."""
    model = TauPyModel(model=MODEL_NAME)
    truth = {}

    for sta_name, sta_coords in sorted(STATIONS.items()):
        dist_m, az, baz = gps2dist_azimuth(
            EVENT_LAT, EVENT_LON, sta_coords["lat"], sta_coords["lon"]
        )
        dist_deg = kilometers2degrees(dist_m / 1000.0)

        arrivals = model.get_travel_times(
            source_depth_in_km=TRUE_DEPTH,
            distance_in_degree=dist_deg,
            phase_list=CANDIDATE_PHASES,
        )

        # First arrival of each phase name only (same logic as data generator)
        seen_phases = set()
        phase_map = {}
        for arr in sorted(arrivals, key=lambda a: a.time):
            if arr.name not in seen_phases:
                seen_phases.add(arr.name)
                abs_time = ORIGIN_TIME + arr.time
                phase_map[str(abs_time)] = arr.name

        truth[sta_name] = {
            "distance_deg": dist_deg,
            "phase_map": phase_map,
        }

    return truth


@pytest.fixture(scope="module")
def ground_truth():
    return _compute_ground_truth()


@pytest.fixture(scope="module")
def results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), f"Results file not found at {results_path}"
    with open(results_path) as f:
        return json.load(f)


class TestResultsSchema:
    """Verify the output JSON has the correct structure."""

    def test_has_depth(self, results):
        assert "depth_km" in results, "Missing 'depth_km' field"
        assert isinstance(results["depth_km"], (int, float)), "depth_km must be numeric"

    def test_has_velocity_model(self, results):
        assert "velocity_model" in results, "Missing 'velocity_model' field"
        assert results["velocity_model"] == "iasp91", "velocity_model must be 'iasp91'"

    def test_has_stations(self, results):
        assert "stations" in results, "Missing 'stations' field"
        assert isinstance(results["stations"], dict), "stations must be a dict"

    def test_has_rms_residual(self, results):
        assert "total_rms_residual_sec" in results, "Missing 'total_rms_residual_sec'"
        assert isinstance(results["total_rms_residual_sec"], (int, float))

    def test_all_stations_present(self, results):
        expected = set(STATIONS.keys())
        actual = set(results["stations"].keys())
        assert expected == actual, f"Missing stations: {expected - actual}, extra: {actual - expected}"

    def test_station_arrival_structure(self, results):
        for sta_name, sta_data in results["stations"].items():
            assert "arrivals" in sta_data, f"Station {sta_name} missing 'arrivals'"
            assert "distance_deg" in sta_data, f"Station {sta_name} missing 'distance_deg'"
            for arr in sta_data["arrivals"]:
                assert "time" in arr, f"Arrival in {sta_name} missing 'time'"
                assert "phase" in arr, f"Arrival in {sta_name} missing 'phase'"
                assert "residual_sec" in arr, f"Arrival in {sta_name} missing 'residual_sec'"


class TestDepthDetermination:
    """Verify the depth is correctly determined."""

    def test_depth_within_tolerance(self, results):
        depth = results["depth_km"]
        assert abs(depth - TRUE_DEPTH) <= 3.0, (
            f"Depth {depth} km is not within ±3 km of true depth {TRUE_DEPTH} km"
        )


class TestPhaseAssignments:
    """Verify phase identifications match ground truth."""

    def test_phase_labels_correct(self, results, ground_truth):
        mismatches = []
        for sta_name in sorted(STATIONS.keys()):
            gt = ground_truth[sta_name]["phase_map"]
            result_arrivals = results["stations"][sta_name]["arrivals"]

            # Build a map from arrival time to assigned phase in results
            result_phase_map = {}
            for arr in result_arrivals:
                result_phase_map[arr["time"]] = arr["phase"]

            # Check each ground truth arrival
            for gt_time, gt_phase in gt.items():
                # Find the matching arrival in results by closest time
                gt_utc = UTCDateTime(gt_time)
                best_match = None
                best_dt = float("inf")
                for arr in result_arrivals:
                    arr_utc = UTCDateTime(arr["time"])
                    dt = abs(arr_utc - gt_utc)
                    if dt < best_dt:
                        best_dt = dt
                        best_match = arr

                if best_match is None:
                    mismatches.append(f"{sta_name}: no arrival found for GT time {gt_time} ({gt_phase})")
                elif best_dt > 0.5:
                    mismatches.append(
                        f"{sta_name}: closest arrival to GT {gt_phase} at {gt_time} "
                        f"is {best_dt:.2f}s away"
                    )
                elif best_match["phase"] != gt_phase:
                    mismatches.append(
                        f"{sta_name}: phase at {gt_time} should be {gt_phase}, "
                        f"got {best_match['phase']}"
                    )

        assert len(mismatches) == 0, (
            f"Phase assignment mismatches:\n" + "\n".join(mismatches)
        )

    def test_correct_number_of_arrivals_per_station(self, results, ground_truth):
        for sta_name in sorted(STATIONS.keys()):
            gt_count = len(ground_truth[sta_name]["phase_map"])
            result_count = len(results["stations"][sta_name]["arrivals"])
            assert result_count == gt_count, (
                f"Station {sta_name}: expected {gt_count} arrivals, got {result_count}"
            )


class TestResiduals:
    """Verify residuals are reasonable."""

    def test_rms_residual_small(self, results):
        rms = results["total_rms_residual_sec"]
        assert rms < 0.5, f"Total RMS residual {rms:.4f} sec exceeds 0.5 sec threshold"

    def test_individual_residuals_small(self, results):
        large_residuals = []
        for sta_name, sta_data in results["stations"].items():
            for arr in sta_data["arrivals"]:
                if abs(arr["residual_sec"]) > 1.0:
                    large_residuals.append(
                        f"{sta_name}/{arr['phase']}: {arr['residual_sec']:.4f}s"
                    )
        assert len(large_residuals) == 0, (
            f"Large individual residuals found:\n" + "\n".join(large_residuals)
        )


class TestDistances:
    """Verify epicentral distances are correctly computed."""

    def test_distances_accurate(self, results, ground_truth):
        for sta_name in sorted(STATIONS.keys()):
            gt_dist = ground_truth[sta_name]["distance_deg"]
            result_dist = results["stations"][sta_name]["distance_deg"]
            assert abs(gt_dist - result_dist) < 0.05, (
                f"Station {sta_name}: distance {result_dist:.4f}° "
                f"differs from expected {gt_dist:.4f}° by more than 0.05°"
            )
