
"""
Verification tests for the hydrological return level pipeline.
All expected values are computed at test time from raw CSV data —
no pre-stored ground-truth answers exist in the environment.
"""

import csv
import json
import os
import numpy as np
import pytest
from math import comb, gamma, log
from scipy.optimize import brentq


# ====================================================================
# Constants
# ====================================================================

STATIONS = ["alpine_01", "coastal_02", "plains_03"]
OUTPUT_PATH = "/app/output/return_levels.json"
DATA_DIR = "/app/data"
TOLERANCE = 0.01  # 1% relative tolerance


# ====================================================================
# Reference implementation for independent verification
# ====================================================================

def _ref_lmoments(x, nmom=4):
    """Hosking (1990) unbiased PWM-based sample L-moments."""
    x = np.sort(np.asarray(x, dtype=float))
    n = len(x)
    betas = np.zeros(nmom)
    for r in range(nmom):
        cn1r = comb(n - 1, r)
        s = 0.0
        for i in range(r, n):
            s += comb(i, r) / cn1r * x[i]
        betas[r] = s / n
    lmoms = np.zeros(nmom)
    for r in range(1, nmom + 1):
        val = 0.0
        for k in range(r):
            p = (-1) ** (r - 1 - k) * comb(r - 1, k) * comb(r - 1 + k, k)
            val += p * betas[k]
        lmoms[r - 1] = val
    return lmoms


def _ref_gev_tau3(kh):
    """Theoretical GEV L-skewness from Hosking kappa."""
    if abs(kh) < 1e-10:
        return 2 * log(3) / log(2) - 3
    return 2 * (1 - 3 ** (-kh)) / (1 - 2 ** (-kh)) - 3


def _ref_gev_tau4(kh):
    """Theoretical GEV L-kurtosis from Hosking kappa."""
    if abs(kh) < 1e-10:
        return 16 - 10 * log(3) / log(2)
    d = 1 - 2 ** (-kh)
    return (5 * (1 - 4 ** (-kh)) - 10 * (1 - 3 ** (-kh)) + 6 * d) / d


def _ref_fit_gev(x):
    """GEV fitting via method of L-moments (Hosking 1997)."""
    lm = _ref_lmoments(np.asarray(x), nmom=3)
    l1, l2, l3 = lm[0], lm[1], lm[2]
    t3 = l3 / l2
    kh = brentq(lambda k: _ref_gev_tau3(k) - t3, -0.99, 10.0, xtol=1e-12)
    if abs(kh) < 1e-8:
        scale = l2 / log(2)
        loc = l1 - scale * 0.5772156649015329
        shape = 0.0
    else:
        gk = gamma(1 + kh)
        scale = l2 * kh / ((1 - 2 ** (-kh)) * gk)
        loc = l1 - scale * (1 - gk) / kh
        shape = kh
    return loc, scale, shape


def _ref_return_level(loc, scale, shape, T):
    """GEV return level quantile function."""
    p = 1.0 - 1.0 / T
    if abs(shape) < 1e-10:
        return loc - scale * log(-log(p))
    return loc + scale / shape * (1 - (-log(p)) ** shape)


def _load_station_flows(station_id):
    """Independently load and filter flow data from CSV files."""
    config_path = os.path.join(DATA_DIR, "stations.json")
    with open(config_path) as f:
        config = json.load(f)

    station = None
    for s in config["stations"]:
        if s["id"] == station_id:
            station = s
            break
    assert station is not None, f"Station {station_id} not in config"

    csv_path = os.path.join(DATA_DIR, station["data"]["source_file"])
    flow_col_idx = station["data"]["flow_column_index"] - 1  # 0-indexed
    quality_filter = station["analysis"]["quality_filter"]

    flows = []
    with open(csv_path) as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if row[4].strip() == quality_filter:
                flows.append(float(row[flow_col_idx]))
    return np.array(flows)


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture(scope="module")
def pipeline_output():
    """Load the pipeline output JSON."""
    assert os.path.exists(OUTPUT_PATH), (
        f"Output file {OUTPUT_PATH} not found. "
        f"Run 'python3 /app/run_analysis.py' first."
    )
    with open(OUTPUT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference_results():
    """Compute reference results for all stations from raw CSV data."""
    results = {}
    for sid in STATIONS:
        flows = _load_station_flows(sid)
        loc, scale, shape = _ref_fit_gev(flows)
        rl100 = _ref_return_level(loc, scale, shape, 100)
        lm = _ref_lmoments(flows, nmom=4)
        tau3 = lm[2] / lm[1]
        tau4 = lm[3] / lm[1]
        results[sid] = {
            "loc": loc, "scale": scale, "shape": shape,
            "rl100": rl100, "n_samples": len(flows),
            "tau3": tau3, "tau4": tau4,
        }
    return results


# ====================================================================
# Test: Output Structure
# ====================================================================

class TestOutputStructure:
    def test_output_exists(self):
        assert os.path.exists(OUTPUT_PATH)

    def test_all_stations_present(self, pipeline_output):
        for sid in STATIONS:
            assert sid in pipeline_output, f"Missing station {sid}"

    def test_required_keys(self, pipeline_output):
        required = [
            "gev_loc", "gev_scale", "gev_shape",
            "return_level_100yr", "n_samples",
            "distribution_selection", "bootstrap_ci",
        ]
        for sid in STATIONS:
            for key in required:
                assert key in pipeline_output[sid], (
                    f"Station {sid} missing key '{key}'"
                )


# ====================================================================
# Test: Return Level Accuracy
# ====================================================================

class TestReturnLevels:
    @pytest.mark.parametrize("station_id", STATIONS)
    def test_return_level_matches(self, station_id, pipeline_output,
                                  reference_results):
        computed = pipeline_output[station_id]["return_level_100yr"]
        expected = reference_results[station_id]["rl100"]
        rel_err = abs(computed - expected) / abs(expected)
        assert rel_err < TOLERANCE, (
            f"Station {station_id}: rl100={computed:.4f} vs "
            f"expected={expected:.4f} (err={rel_err:.4%})"
        )


# ====================================================================
# Test: GEV Parameters
# ====================================================================

class TestGEVParameters:
    @pytest.mark.parametrize("station_id", STATIONS)
    def test_shape_matches(self, station_id, pipeline_output,
                           reference_results):
        computed = pipeline_output[station_id]["gev_shape"]
        expected = reference_results[station_id]["shape"]
        assert abs(computed - expected) < 0.05, (
            f"Station {station_id}: shape={computed:.4f} vs "
            f"expected={expected:.4f}"
        )

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_scale_positive(self, station_id, pipeline_output):
        assert pipeline_output[station_id]["gev_scale"] > 0

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_loc_matches(self, station_id, pipeline_output,
                         reference_results):
        computed = pipeline_output[station_id]["gev_loc"]
        expected = reference_results[station_id]["loc"]
        rel_err = abs(computed - expected) / abs(expected)
        assert rel_err < TOLERANCE, (
            f"Station {station_id}: loc={computed:.4f} vs "
            f"expected={expected:.4f}"
        )


# ====================================================================
# Test: Sample Counts
# ====================================================================

class TestSampleCounts:
    @pytest.mark.parametrize("station_id", STATIONS)
    def test_n_samples_matches(self, station_id, pipeline_output,
                                reference_results):
        computed = pipeline_output[station_id]["n_samples"]
        expected = reference_results[station_id]["n_samples"]
        assert computed == expected, (
            f"Station {station_id}: {computed} vs expected {expected} samples"
        )


# ====================================================================
# Test: Distribution Selection
# ====================================================================

class TestDistributionSelection:
    @pytest.mark.parametrize("station_id", STATIONS)
    def test_selection_has_required_keys(self, station_id, pipeline_output):
        ds = pipeline_output[station_id]["distribution_selection"]
        for key in ["selected", "tau3", "tau4", "distances"]:
            assert key in ds, (
                f"Station {station_id}: missing key '{key}' "
                f"in distribution_selection"
            )

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_selected_is_valid(self, station_id, pipeline_output):
        sel = pipeline_output[station_id]["distribution_selection"]["selected"]
        assert sel in ["gev", "glo", "gpa"], f"Invalid selection: {sel}"

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_selected_minimizes_distance(self, station_id, pipeline_output):
        ds = pipeline_output[station_id]["distribution_selection"]
        selected = ds["selected"]
        distances = ds["distances"]
        min_dist = min(distances.values())
        assert abs(distances[selected] - min_dist) < 1e-10, (
            f"Selected '{selected}' does not minimize tau4 distance"
        )

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_tau3_matches_reference(self, station_id, pipeline_output,
                                    reference_results):
        ds = pipeline_output[station_id]["distribution_selection"]
        expected_tau3 = reference_results[station_id]["tau3"]
        assert abs(ds["tau3"] - expected_tau3) < 0.01, (
            f"tau3 mismatch: {ds['tau3']:.4f} vs {expected_tau3:.4f}"
        )

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_tau4_matches_reference(self, station_id, pipeline_output,
                                    reference_results):
        ds = pipeline_output[station_id]["distribution_selection"]
        expected_tau4 = reference_results[station_id]["tau4"]
        assert abs(ds["tau4"] - expected_tau4) < 0.01, (
            f"tau4 mismatch: {ds['tau4']:.4f} vs {expected_tau4:.4f}"
        )

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_glo_distance_correct(self, station_id, pipeline_output,
                                  reference_results):
        """Verify GLO distance matches the formula tau4 = (1+5*tau3^2)/6."""
        ds = pipeline_output[station_id]["distribution_selection"]
        tau3 = ds["tau3"]
        tau4 = ds["tau4"]
        glo_expected = (1 + 5 * tau3 ** 2) / 6
        glo_distance = ds["distances"]["glo"]
        assert abs(glo_distance - abs(tau4 - glo_expected)) < 0.005, (
            f"GLO distance inconsistent: reported={glo_distance:.4f}, "
            f"computed={abs(tau4 - glo_expected):.4f}"
        )

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_gpa_distance_correct(self, station_id, pipeline_output,
                                  reference_results):
        """Verify GPA distance matches tau4 = tau3*(1+5*tau3)/(5+tau3)."""
        ds = pipeline_output[station_id]["distribution_selection"]
        tau3 = ds["tau3"]
        tau4 = ds["tau4"]
        gpa_expected = tau3 * (1 + 5 * tau3) / (5 + tau3)
        gpa_distance = ds["distances"]["gpa"]
        assert abs(gpa_distance - abs(tau4 - gpa_expected)) < 0.005, (
            f"GPA distance inconsistent: reported={gpa_distance:.4f}, "
            f"computed={abs(tau4 - gpa_expected):.4f}"
        )

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_gev_distance_correct(self, station_id, pipeline_output):
        """Verify GEV distance uses correct tau4(kappa) formula."""
        ds = pipeline_output[station_id]["distribution_selection"]
        tau3 = ds["tau3"]
        tau4 = ds["tau4"]

        # Invert tau3 to get kappa, then compute theoretical tau4
        kh = brentq(lambda k: _ref_gev_tau3(k) - tau3, -0.99, 10.0,
                    xtol=1e-12)
        gev_tau4_expected = _ref_gev_tau4(kh)

        gev_distance = ds["distances"]["gev"]
        expected_dist = abs(tau4 - gev_tau4_expected)
        assert abs(gev_distance - expected_dist) < 0.005, (
            f"GEV distance inconsistent: reported={gev_distance:.6f}, "
            f"computed={expected_dist:.6f}"
        )


# ====================================================================
# Test: Bootstrap Confidence Intervals
# ====================================================================

class TestBootstrapCI:
    @pytest.mark.parametrize("station_id", STATIONS)
    def test_ci_has_required_keys(self, station_id, pipeline_output):
        bc = pipeline_output[station_id]["bootstrap_ci"]
        for key in ["point_estimate", "ci_lower", "ci_upper", "n_boot"]:
            assert key in bc, f"Missing key '{key}' in bootstrap_ci"

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_ci_contains_point_estimate(self, station_id, pipeline_output):
        bc = pipeline_output[station_id]["bootstrap_ci"]
        assert bc["ci_lower"] <= bc["point_estimate"] <= bc["ci_upper"], (
            f"CI [{bc['ci_lower']:.2f}, {bc['ci_upper']:.2f}] does not "
            f"contain point estimate {bc['point_estimate']:.2f}"
        )

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_ci_ordered(self, station_id, pipeline_output):
        bc = pipeline_output[station_id]["bootstrap_ci"]
        assert bc["ci_lower"] < bc["ci_upper"], (
            f"CI bounds not ordered: {bc['ci_lower']} >= {bc['ci_upper']}"
        )

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_ci_width_reasonable(self, station_id, pipeline_output):
        bc = pipeline_output[station_id]["bootstrap_ci"]
        width = bc["ci_upper"] - bc["ci_lower"]
        point = bc["point_estimate"]
        assert width > 0
        assert width < 2 * abs(point), (
            f"CI width {width:.2f} unreasonably large vs "
            f"point estimate {point:.2f}"
        )

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_point_estimate_matches_gev(self, station_id, pipeline_output):
        """Bootstrap point estimate should match GEV return level."""
        bc = pipeline_output[station_id]["bootstrap_ci"]
        rl = pipeline_output[station_id]["return_level_100yr"]
        rel_err = abs(bc["point_estimate"] - rl) / abs(rl)
        assert rel_err < TOLERANCE, (
            f"Bootstrap point estimate {bc['point_estimate']:.4f} != "
            f"GEV return level {rl:.4f}"
        )

    @pytest.mark.parametrize("station_id", STATIONS)
    def test_n_boot_sufficient(self, station_id, pipeline_output):
        bc = pipeline_output[station_id]["bootstrap_ci"]
        assert bc["n_boot"] >= 100, (
            f"Too few successful bootstrap resamples: {bc['n_boot']}"
        )
