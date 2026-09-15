"""
Tests for EPA ProUCL 5.2 Compliance Audit.
Verifies correctness of corrected UCL results and audit report.
"""

import json
import os
import csv
import numpy as np
from scipy import stats
import pytest


RESULTS_PATH = '/app/results.json'
AUDIT_PATH = '/app/audit_report.json'
DATA_PATH = '/app/data/site_data.csv'
ORIGINAL_PATH = '/app/original_analysis.json'

EXPECTED_ANALYTES = {'Arsenic', 'Benzo_a_pyrene', 'Cadmium', 'Benzene', 'Trichloroethene'}
REQUIRED_KEYS = {'n', 'n_detect', 'percent_nd', 'distribution', 'ucl_method',
                 'ucl95', 'mean_estimate', 'sd_estimate'}
VALID_DISTRIBUTIONS = {'normal', 'gamma', 'lognormal', 'nonparametric'}


@pytest.fixture(scope='module')
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file {RESULTS_PATH} not found"
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def audit():
    assert os.path.exists(AUDIT_PATH), f"Audit report {AUDIT_PATH} not found"
    with open(AUDIT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def original():
    with open(ORIGINAL_PATH) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def raw_data():
    data = {}
    with open(DATA_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            analyte = row['analyte']
            if analyte not in data:
                data[analyte] = {'values': [], 'detected': []}
            data[analyte]['values'].append(float(row['result']))
            data[analyte]['detected'].append(int(row['detect_flag']) == 1)
    return data


# ==== Results structural tests ====

def test_output_exists_and_valid_json():
    assert os.path.exists(RESULTS_PATH), "Results file not found"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Results must be a JSON object"
    assert len(data) > 0, "Results must not be empty"


def test_all_analytes_present(results):
    assert set(results.keys()) == EXPECTED_ANALYTES, \
        f"Expected analytes {EXPECTED_ANALYTES}, got {set(results.keys())}"


def test_required_keys_present(results):
    for analyte, result in results.items():
        missing = REQUIRED_KEYS - set(result.keys())
        assert not missing, f"Missing keys {missing} for {analyte}"


def test_valid_distribution_names(results):
    for analyte, result in results.items():
        assert result['distribution'] in VALID_DISTRIBUTIONS, \
            f"Invalid distribution '{result['distribution']}' for {analyte}"


def test_numeric_types(results):
    for analyte, result in results.items():
        assert isinstance(result['n'], int), f"n must be int for {analyte}"
        assert isinstance(result['n_detect'], int), f"n_detect must be int for {analyte}"
        assert isinstance(result['percent_nd'], (int, float)), \
            f"percent_nd must be numeric for {analyte}"
        assert isinstance(result['ucl95'], (int, float)), \
            f"ucl95 must be numeric for {analyte}"
        assert isinstance(result['mean_estimate'], (int, float)), \
            f"mean_estimate must be numeric for {analyte}"
        assert isinstance(result['sd_estimate'], (int, float)), \
            f"sd_estimate must be numeric for {analyte}"


# ==== Data integrity tests ====

def test_sample_counts(results, raw_data):
    for analyte in raw_data:
        n_total = len(raw_data[analyte]['values'])
        n_detect = sum(raw_data[analyte]['detected'])
        pct_nd = (n_total - n_detect) / n_total * 100

        assert results[analyte]['n'] == n_total, \
            f"Wrong n for {analyte}: expected {n_total}, got {results[analyte]['n']}"
        assert results[analyte]['n_detect'] == n_detect, \
            f"Wrong n_detect for {analyte}: expected {n_detect}, got {results[analyte]['n_detect']}"
        assert abs(results[analyte]['percent_nd'] - pct_nd) < 0.5, \
            f"Wrong percent_nd for {analyte}: expected {pct_nd:.1f}, got {results[analyte]['percent_nd']}"


# ==== Statistical invariant tests ====

def test_ucl_greater_than_or_equal_mean(results):
    for analyte, result in results.items():
        assert result['ucl95'] >= result['mean_estimate'] - 1e-6, \
            f"UCL ({result['ucl95']}) < mean ({result['mean_estimate']}) for {analyte}"


def test_positive_ucl_values(results):
    for analyte, result in results.items():
        assert result['ucl95'] > 0, f"UCL must be positive for {analyte}"


def test_positive_sd(results):
    for analyte, result in results.items():
        assert result['sd_estimate'] > 0, f"SD must be positive for {analyte}"


def test_no_chebyshev_recommendation(results):
    """ProUCL 5.2 never recommends Chebyshev UCL."""
    for analyte, result in results.items():
        method_lower = result['ucl_method'].lower()
        assert 'chebyshev' not in method_lower and 'cheby' not in method_lower, \
            f"ProUCL 5.2 must not recommend Chebyshev; got '{result['ucl_method']}' for {analyte}"


# ==== Distribution classification tests ====

def test_arsenic_classified_normal(results):
    """Arsenic data is symmetric/bell-shaped and must be classified as normal."""
    assert results['Arsenic']['distribution'] == 'normal', \
        f"Arsenic should be 'normal', got '{results['Arsenic']['distribution']}'"


def test_bap_not_classified_normal(results):
    """Benzo_a_pyrene spans 2 orders of magnitude (0.12-12.30) and must NOT be normal."""
    assert results['Benzo_a_pyrene']['distribution'] != 'normal', \
        f"Benzo_a_pyrene should not be 'normal', got '{results['Benzo_a_pyrene']['distribution']}'"


# ==== Numerical accuracy tests ====

def test_arsenic_mean_accuracy(results, raw_data):
    """Verify Arsenic mean is computed correctly (all detected, no censoring)."""
    vals = np.array(raw_data['Arsenic']['values'])
    expected_mean = float(np.mean(vals))
    actual = results['Arsenic']['mean_estimate']
    assert abs(actual - expected_mean) / expected_mean < 0.005, \
        f"Arsenic mean ({actual}) doesn't match expected ({expected_mean:.6f})"


def test_arsenic_sd_accuracy(results, raw_data):
    """Verify Arsenic SD is computed correctly (sample SD with ddof=1)."""
    vals = np.array(raw_data['Arsenic']['values'])
    expected_sd = float(np.std(vals, ddof=1))
    actual = results['Arsenic']['sd_estimate']
    assert abs(actual - expected_sd) / expected_sd < 0.02, \
        f"Arsenic SD ({actual}) doesn't match expected ({expected_sd:.6f})"


def test_arsenic_t_ucl_accuracy(results, raw_data):
    """For normal Arsenic data, UCL must match Student's-t formula within 2%."""
    vals = np.array([v for v, d in zip(raw_data['Arsenic']['values'],
                                        raw_data['Arsenic']['detected']) if d])
    n = len(vals)
    mean = np.mean(vals)
    sd = np.std(vals, ddof=1)
    t_crit = stats.t.ppf(0.95, n - 1)
    expected_ucl = mean + t_crit * sd / np.sqrt(n)

    actual = results['Arsenic']['ucl95']
    rel_error = abs(actual - expected_ucl) / expected_ucl
    assert rel_error < 0.02, \
        f"Arsenic UCL ({actual:.6f}) doesn't match t-UCL ({expected_ucl:.6f}), " \
        f"rel_error={rel_error:.4f}"


# ==== Censored data handling tests ====

def test_benzene_censoring_reduces_mean(results, raw_data):
    """Benzene has NDs; the estimated mean must be below the naive DL-substitution mean."""
    naive_mean = np.mean(raw_data['Benzene']['values'])
    actual = results['Benzene']['mean_estimate']
    assert actual < naive_mean, \
        f"Benzene censoring-adjusted mean ({actual:.4f}) should be < naive mean ({naive_mean:.4f})"


def test_benzene_mean_above_zero_substitution(results, raw_data):
    """Benzene mean should be above the zero-substitution mean."""
    vals = raw_data['Benzene']['values']
    detected = raw_data['Benzene']['detected']
    zero_sub = [v if d else 0.0 for v, d in zip(vals, detected)]
    mean_zero = np.mean(zero_sub)
    actual = results['Benzene']['mean_estimate']
    assert actual >= mean_zero, \
        f"Benzene mean ({actual:.4f}) should be >= zero-sub mean ({mean_zero:.4f})"


def test_tce_censoring_reduces_mean(results, raw_data):
    """TCE has 45% NDs; the estimated mean must be below the naive DL-substitution mean."""
    naive_mean = np.mean(raw_data['Trichloroethene']['values'])
    actual = results['Trichloroethene']['mean_estimate']
    assert actual < naive_mean, \
        f"TCE censoring-adjusted mean ({actual:.4f}) should be < naive mean ({naive_mean:.4f})"


def test_tce_mean_above_zero_substitution(results, raw_data):
    """TCE mean should be above the zero-substitution mean."""
    vals = raw_data['Trichloroethene']['values']
    detected = raw_data['Trichloroethene']['detected']
    zero_sub = [v if d else 0.0 for v, d in zip(vals, detected)]
    mean_zero = np.mean(zero_sub)
    actual = results['Trichloroethene']['mean_estimate']
    assert actual >= mean_zero, \
        f"TCE mean ({actual:.4f}) should be >= zero-sub mean ({mean_zero:.4f})"


def test_tce_heavy_censoring_method(results):
    """TCE has 45% censoring; method should reflect censored-data approach."""
    assert results['Trichloroethene']['percent_nd'] > 40
    method = results['Trichloroethene']['ucl_method'].lower()
    dist = results['Trichloroethene']['distribution']
    valid_indicators = ['km', 'kaplan', 'bootstrap', 'ros', 'percentile']
    has_valid = any(ind in method for ind in valid_indicators) or dist == 'nonparametric'
    assert has_valid, \
        f"TCE (45% ND) should use KM/bootstrap/nonparametric method, " \
        f"got method='{results['Trichloroethene']['ucl_method']}', dist='{dist}'"


def test_fully_detected_no_censoring_label(results):
    """Fully detected analytes should have 0% ND."""
    for analyte in ['Arsenic', 'Benzo_a_pyrene', 'Cadmium']:
        assert results[analyte]['percent_nd'] == 0.0, \
            f"{analyte} should have 0% ND, got {results[analyte]['percent_nd']}"
        assert results[analyte]['n'] == results[analyte]['n_detect'], \
            f"{analyte} n ({results[analyte]['n']}) should equal n_detect ({results[analyte]['n_detect']})"


# ==== Audit report tests ====

def test_audit_exists_and_valid():
    assert os.path.exists(AUDIT_PATH), "Audit report not found"
    with open(AUDIT_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Audit must be a JSON object"


def test_audit_all_analytes(audit):
    assert set(audit.keys()) == EXPECTED_ANALYTES, \
        f"Audit must cover all analytes; got {set(audit.keys())}"


def test_audit_structure(audit):
    for analyte, entry in audit.items():
        assert 'errors' in entry, f"Missing 'errors' key for {analyte}"
        assert 'original_ucl95' in entry, f"Missing 'original_ucl95' for {analyte}"
        assert 'corrected_ucl95' in entry, f"Missing 'corrected_ucl95' for {analyte}"
        assert isinstance(entry['errors'], list), f"errors must be a list for {analyte}"
        assert len(entry['errors']) > 0, \
            f"Each analyte in the original analysis has at least one violation; " \
            f"no errors found for {analyte}"


def test_audit_original_ucl_matches_input(audit, original):
    """Audit original_ucl95 must match the values from original_analysis.json."""
    for analyte in EXPECTED_ANALYTES:
        expected = original[analyte]['ucl95']
        actual = audit[analyte]['original_ucl95']
        assert abs(actual - expected) < 0.01, \
            f"Audit original_ucl95 for {analyte}: expected {expected}, got {actual}"


def test_audit_corrected_ucl_matches_results(audit, results):
    """Audit corrected_ucl95 must match the corrected results."""
    for analyte in EXPECTED_ANALYTES:
        expected = results[analyte]['ucl95']
        actual = audit[analyte]['corrected_ucl95']
        assert abs(actual - expected) < 0.01, \
            f"Audit corrected_ucl95 for {analyte}: expected {expected}, got {actual}"


def test_audit_chebyshev_flagged(audit):
    """Original used Chebyshev UCL for Arsenic and Cadmium; audit must flag this."""
    for analyte in ['Arsenic', 'Cadmium']:
        errors_text = ' '.join(audit[analyte]['errors']).lower()
        assert 'chebyshev' in errors_text, \
            f"Audit must flag Chebyshev UCL usage for {analyte}; " \
            f"errors: {audit[analyte]['errors']}"


def test_audit_bap_distribution_flagged(audit):
    """Original classified BaP as normal; audit must flag distribution error."""
    errors_text = ' '.join(audit['Benzo_a_pyrene']['errors']).lower()
    has_flag = any(kw in errors_text for kw in [
        'distribution', 'misclassif', 'goodness-of-fit', 'goodness of fit',
        'normality', 'skew', 'not normal', 'non-normal'
    ])
    assert has_flag, \
        f"Audit must flag BaP distribution misclassification; " \
        f"errors: {audit['Benzo_a_pyrene']['errors']}"


def test_audit_censoring_flagged(audit):
    """Original used improper censoring for Benzene and TCE; audit must flag this."""
    for analyte in ['Benzene', 'Trichloroethene']:
        errors_text = ' '.join(audit[analyte]['errors']).lower()
        has_flag = any(kw in errors_text for kw in [
            'censor', 'non-detect', 'nondetect', 'substitut',
            'detection limit', 'imput', 'kaplan-meier', 'regression on order'
        ])
        assert has_flag, \
            f"Audit must flag censoring methodology error for {analyte}; " \
            f"errors: {audit[analyte]['errors']}"
