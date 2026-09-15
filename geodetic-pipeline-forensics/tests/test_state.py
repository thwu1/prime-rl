"""

Validates geodetic pipeline evaluation and projection identification task.
Tests independently compute reference values using cct and verify solver outputs.
"""
import json
import subprocess
import os
import math
import csv
import pytest


# ---------------------------------------------------------------------------
# Reference pipelines — authoritative transformation for each scenario.
# These are only present in the test file (not in the Docker image).
# ---------------------------------------------------------------------------
_REFERENCE_PIPELINES = {
    "oblique_stereo": (
        "+proj=sterea +lat_0=52.15616055556 +lon_0=5.38763888889 "
        "+k_0=0.9999079 +x_0=155000 +y_0=463000 +ellps=bessel +units=m"
    ),
    "laea_europe": (
        "+proj=laea +lat_0=52 +lon_0=10 "
        "+x_0=4321000 +y_0=3210000 +ellps=GRS80 +units=m"
    ),
    "geocentric": "+proj=cart +ellps=WGS84",
}


def load_scenarios():
    with open('/app/scenarios.json') as f:
        return json.load(f)


SCENARIOS = load_scenarios()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_cct(proj_string, lon, lat, z=0.0):
    """Transform coordinates using PROJ cct. Returns list of floats or None."""
    input_str = f"{lon} {lat} {z} 0\n"
    cmd = ['cct', '-d', '10'] + proj_string.split()
    try:
        result = subprocess.run(
            cmd, input=input_str, capture_output=True, text=True, timeout=30
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    if not output or '*' in output:
        return None
    try:
        return [float(v) for v in output.split()]
    except ValueError:
        return None


def positional_error_3d(a, b):
    """Euclidean distance using first 3 spatial dimensions."""
    n = min(3, len(a), len(b))
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(n)))


def generate_reference_coords(scenario_name):
    """Generate reference output coordinates by running the reference pipeline."""
    ref_pipeline = _REFERENCE_PIPELINES[scenario_name]
    input_points = SCENARIOS['evaluation_scenarios'][scenario_name]['input_points']
    coords = []
    for pt in input_points:
        z = pt[2] if len(pt) > 2 else 0.0
        result = run_cct(ref_pipeline, pt[0], pt[1], z)
        assert result is not None, \
            f"Reference pipeline failed for input {pt} in {scenario_name}"
        coords.append(result)
    return coords


def compute_metrics(proj_string, input_points, ref_coords):
    """Compute RMSE and max positional error for a pipeline against reference."""
    errors = []
    for pt, ref in zip(input_points, ref_coords):
        z = pt[2] if len(pt) > 2 else 0.0
        res = run_cct(proj_string, pt[0], pt[1], z)
        if res is None:
            return float('inf'), float('inf')
        errors.append(positional_error_3d(res, ref))
    rmse = math.sqrt(sum(e ** 2 for e in errors) / len(errors))
    return rmse, max(errors)


def classify_tier(rmse, tiers):
    if rmse < tiers['survey']['max_rmse_m']:
        return 'survey'
    elif rmse < tiers['mapping']['max_rmse_m']:
        return 'mapping'
    elif rmse < tiers['navigation']['max_rmse_m']:
        return 'navigation'
    return 'none'


# Pre-compute reference metrics once (shared across tests)
_ref_cache = {}


def get_reference_data():
    """Compute reference RMSE, rankings, tiers for all evaluation scenarios."""
    if _ref_cache:
        return _ref_cache
    tiers = SCENARIOS['accuracy_tiers']
    for sname, scenario in SCENARIOS['evaluation_scenarios'].items():
        ref_coords = generate_reference_coords(sname)
        input_points = scenario['input_points']
        metrics = {}
        for cname, proj_str in scenario['candidates'].items():
            rmse, max_err = compute_metrics(proj_str, input_points, ref_coords)
            metrics[cname] = {'rmse': rmse, 'max_error': max_err}
        ranking = sorted(metrics, key=lambda c: metrics[c]['rmse'])
        tier_map = {c: classify_tier(metrics[c]['rmse'], tiers) for c in metrics}
        survey_rec = next((c for c in ranking if tier_map[c] == 'survey'), None)
        _ref_cache[sname] = {
            'metrics': metrics,
            'ranking': ranking,
            'tiers': tier_map,
            'survey_recommendation': survey_rec,
        }
    return _ref_cache


def load_design_control_points():
    """Load design scenario control points from the CSV file."""
    pts = []
    with open('/app/survey_observations.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pts.append({
                'geographic': [float(row['longitude_deg']),
                               float(row['latitude_deg'])],
                'projected': [float(row['easting_m']),
                              float(row['northing_m'])],
            })
    return pts


# ---------------------------------------------------------------------------
# Sanity check: PROJ installation produces correct results
# ---------------------------------------------------------------------------

class TestProjSanity:
    """Ensure the alpha candidate achieves survey-grade in every scenario."""

    def test_oblique_stereo_alpha_survey(self):
        ref = get_reference_data()
        assert ref['oblique_stereo']['tiers']['alpha'] == 'survey', \
            "PROJ sanity: oblique_stereo alpha should be survey-grade"

    def test_laea_europe_alpha_survey(self):
        ref = get_reference_data()
        assert ref['laea_europe']['tiers']['alpha'] == 'survey', \
            "PROJ sanity: laea_europe alpha should be survey-grade"

    def test_geocentric_alpha_survey(self):
        ref = get_reference_data()
        assert ref['geocentric']['tiers']['alpha'] == 'survey', \
            "PROJ sanity: geocentric alpha should be survey-grade"


# ---------------------------------------------------------------------------
# File structure
# ---------------------------------------------------------------------------

class TestFileStructure:
    def test_accuracy_report_exists(self):
        assert os.path.isfile('/app/results/accuracy_report.json'), \
            "accuracy_report.json not found"

    def test_tier_classification_exists(self):
        assert os.path.isfile('/app/results/tier_classification.json'), \
            "tier_classification.json not found"

    def test_rankings_exists(self):
        assert os.path.isfile('/app/results/rankings.json'), \
            "rankings.json not found"

    def test_designed_pipeline_exists(self):
        assert os.path.isfile('/app/results/designed_pipeline.json'), \
            "designed_pipeline.json not found"

    def test_accuracy_report_valid_json(self):
        with open('/app/results/accuracy_report.json') as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_tier_classification_valid_json(self):
        with open('/app/results/tier_classification.json') as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_rankings_valid_json(self):
        with open('/app/results/rankings.json') as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_designed_pipeline_valid_json(self):
        with open('/app/results/designed_pipeline.json') as f:
            data = json.load(f)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Accuracy report
# ---------------------------------------------------------------------------

class TestAccuracyReport:
    @pytest.fixture
    def report(self):
        with open('/app/results/accuracy_report.json') as f:
            return json.load(f)

    def test_all_scenarios_present(self, report):
        for sname in SCENARIOS['evaluation_scenarios']:
            assert sname in report, f"Missing scenario '{sname}' in accuracy_report"

    def test_all_candidates_present(self, report):
        for sname, scenario in SCENARIOS['evaluation_scenarios'].items():
            for cname in scenario['candidates']:
                assert cname in report[sname], \
                    f"Missing candidate '{cname}' in scenario '{sname}'"

    def test_has_rmse_and_max_error(self, report):
        for sname in SCENARIOS['evaluation_scenarios']:
            for cname in report[sname]:
                entry = report[sname][cname]
                assert 'rmse_m' in entry, \
                    f"{sname}/{cname}: missing 'rmse_m'"
                assert 'max_error_m' in entry, \
                    f"{sname}/{cname}: missing 'max_error_m'"

    @pytest.mark.parametrize("scenario_name", [
        "oblique_stereo", "laea_europe", "geocentric"
    ])
    def test_rmse_values_correct(self, report, scenario_name):
        """Verify reported RMSE matches independently computed RMSE."""
        ref = get_reference_data()
        for cname in SCENARIOS['evaluation_scenarios'][scenario_name]['candidates']:
            reported = report[scenario_name][cname]['rmse_m']
            expected = ref[scenario_name]['metrics'][cname]['rmse']
            tol = max(expected * 0.05, 0.01)  # 5% or 0.01m
            assert abs(reported - expected) < tol, (
                f"{scenario_name}/{cname}: reported RMSE {reported:.6f} "
                f"vs computed {expected:.6f}, tolerance {tol:.6f}"
            )

    @pytest.mark.parametrize("scenario_name", [
        "oblique_stereo", "laea_europe", "geocentric"
    ])
    def test_max_error_values_correct(self, report, scenario_name):
        """Verify reported max_error matches independently computed value."""
        ref = get_reference_data()
        for cname in SCENARIOS['evaluation_scenarios'][scenario_name]['candidates']:
            reported = report[scenario_name][cname]['max_error_m']
            expected = ref[scenario_name]['metrics'][cname]['max_error']
            tol = max(expected * 0.05, 0.01)
            assert abs(reported - expected) < tol, (
                f"{scenario_name}/{cname}: reported max_error {reported:.6f} "
                f"vs computed {expected:.6f}, tolerance {tol:.6f}"
            )


# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------

class TestTierClassification:
    @pytest.fixture
    def tiers(self):
        with open('/app/results/tier_classification.json') as f:
            return json.load(f)

    def test_all_scenarios_present(self, tiers):
        for sname in SCENARIOS['evaluation_scenarios']:
            assert sname in tiers, f"Missing scenario '{sname}'"

    @pytest.mark.parametrize("scenario_name", [
        "oblique_stereo", "laea_europe", "geocentric"
    ])
    def test_tier_values_correct(self, tiers, scenario_name):
        """Verify each candidate's tier matches independently computed tier."""
        ref = get_reference_data()
        for cname in SCENARIOS['evaluation_scenarios'][scenario_name]['candidates']:
            reported = tiers[scenario_name][cname]
            expected = ref[scenario_name]['tiers'][cname]
            assert reported == expected, (
                f"{scenario_name}/{cname}: reported tier '{reported}', "
                f"expected '{expected}'"
            )


# ---------------------------------------------------------------------------
# Rankings
# ---------------------------------------------------------------------------

class TestRankings:
    @pytest.fixture
    def rankings(self):
        with open('/app/results/rankings.json') as f:
            return json.load(f)

    def test_all_scenarios_present(self, rankings):
        for sname in SCENARIOS['evaluation_scenarios']:
            assert sname in rankings, f"Missing scenario '{sname}'"

    @pytest.mark.parametrize("scenario_name", [
        "oblique_stereo", "laea_europe", "geocentric"
    ])
    def test_ranking_order(self, rankings, scenario_name):
        ref = get_reference_data()
        expected_order = ref[scenario_name]['ranking']
        actual_order = rankings[scenario_name]['ranking']
        assert actual_order == expected_order, (
            f"{scenario_name}: expected ranking {expected_order}, "
            f"got {actual_order}"
        )

    @pytest.mark.parametrize("scenario_name", [
        "oblique_stereo", "laea_europe", "geocentric"
    ])
    def test_survey_recommendation(self, rankings, scenario_name):
        ref = get_reference_data()
        expected_rec = ref[scenario_name]['survey_recommendation']
        actual_rec = rankings[scenario_name]['survey_recommendation']
        assert actual_rec == expected_rec, (
            f"{scenario_name}: expected survey_recommendation "
            f"'{expected_rec}', got '{actual_rec}'"
        )


# ---------------------------------------------------------------------------
# Designed pipeline — verified solely by execution accuracy
# ---------------------------------------------------------------------------

class TestDesignedPipeline:
    @pytest.fixture
    def designed(self):
        with open('/app/results/designed_pipeline.json') as f:
            return json.load(f)

    def test_has_proj_string(self, designed):
        assert 'proj_string' in designed, "Missing 'proj_string' key"
        assert isinstance(designed['proj_string'], str)

    def test_proj_string_valid_format(self, designed):
        ps = designed['proj_string']
        assert '+proj=' in ps, \
            f"proj_string should contain '+proj=', got: {ps[:60]}"

    def test_has_projection_type(self, designed):
        assert 'projection_type' in designed, "Missing 'projection_type' key"
        assert isinstance(designed['projection_type'], str)
        assert len(designed['projection_type']) > 0, \
            "projection_type should not be empty"

    def test_pipeline_runs_without_error(self, designed):
        """Verify cct can execute the designed pipeline on at least one point."""
        ps = designed['proj_string']
        result = run_cct(ps, 132.0, 0.0)
        assert result is not None, \
            f"cct failed to execute designed pipeline: {ps}"

    def test_pipeline_accuracy_all_points(self, designed):
        """Verify the designed pipeline achieves <0.05m on all control points."""
        ps = designed['proj_string']
        control_pts = load_design_control_points()
        tolerance = 0.05  # meters
        for pt in control_pts:
            geo = pt['geographic']
            exp = pt['projected']
            result = run_cct(ps, geo[0], geo[1])
            assert result is not None, \
                f"cct failed for geographic input {geo}"
            err = math.sqrt(
                (result[0] - exp[0]) ** 2 + (result[1] - exp[1]) ** 2
            )
            assert err < tolerance, (
                f"Point ({geo[0]}, {geo[1]}): positional error "
                f"{err:.4f}m exceeds {tolerance}m tolerance. "
                f"Got ({result[0]:.3f}, {result[1]:.3f}), "
                f"expected ({exp[0]:.3f}, {exp[1]:.3f})"
            )
