
"""Tests for CMS165 eCQM Population Evaluator."""

import json
import os
import pytest


RESULTS_PATH = "/app/results.json"
POPULATIONS = ["initial_population", "denominator", "denominator_exclusion", "numerator"]

# Expected population membership derived from the authoritative CMS165 CQL specification.
# Visible patients (patient_001 through patient_012) are in the Docker image.
# Hidden patients (hidden_pt_a through hidden_pt_d) are injected at test time.
EXPECTED = {
    "patient_001": {
        "initial_population": True, "denominator": True,
        "denominator_exclusion": False, "numerator": True,
    },
    "patient_002": {
        "initial_population": True, "denominator": True,
        "denominator_exclusion": False, "numerator": False,
    },
    "patient_003": {
        "initial_population": False, "denominator": False,
        "denominator_exclusion": False, "numerator": False,
    },
    "patient_004": {
        "initial_population": False, "denominator": False,
        "denominator_exclusion": False, "numerator": False,
    },
    "patient_005": {
        "initial_population": True, "denominator": True,
        "denominator_exclusion": True, "numerator": False,
    },
    "patient_006": {
        "initial_population": True, "denominator": True,
        "denominator_exclusion": True, "numerator": False,
    },
    "patient_007": {
        "initial_population": True, "denominator": True,
        "denominator_exclusion": False, "numerator": False,
    },
    "patient_008": {
        "initial_population": True, "denominator": True,
        "denominator_exclusion": False, "numerator": True,
    },
    "patient_009": {
        "initial_population": False, "denominator": False,
        "denominator_exclusion": False, "numerator": False,
    },
    "patient_010": {
        "initial_population": True, "denominator": True,
        "denominator_exclusion": True, "numerator": False,
    },
    "patient_011": {
        "initial_population": True, "denominator": True,
        "denominator_exclusion": False, "numerator": False,
    },
    "patient_012": {
        "initial_population": True, "denominator": True,
        "denominator_exclusion": False, "numerator": True,
    },
    "hidden_pt_a": {
        "initial_population": True, "denominator": True,
        "denominator_exclusion": False, "numerator": True,
    },
    "hidden_pt_b": {
        "initial_population": True, "denominator": True,
        "denominator_exclusion": False, "numerator": True,
    },
    "hidden_pt_c": {
        "initial_population": True, "denominator": True,
        "denominator_exclusion": False, "numerator": True,
    },
    "hidden_pt_d": {
        "initial_population": True, "denominator": True,
        "denominator_exclusion": True, "numerator": False,
    },
}


@pytest.fixture(scope="module")
def results():
    """Load the evaluator's output results."""
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "The evaluator must write results to /app/results.json"
    )
    with open(RESULTS_PATH) as f:
        return json.load(f)


def _to_bool(v):
    """Normalize a value to boolean."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    if isinstance(v, (int, float)):
        return bool(v)
    return False


class TestResultsStructure:
    """Verify results file has all expected patients and populations."""

    def test_results_file_exists(self, results):
        assert results is not None

    def test_all_patients_present(self, results):
        missing = set(EXPECTED.keys()) - set(results.keys())
        assert not missing, f"Missing patients in results: {missing}"

    def test_all_populations_present(self, results):
        for patient_id in EXPECTED:
            assert patient_id in results, f"Patient {patient_id} missing"
            for pop in POPULATIONS:
                assert pop in results[patient_id], (
                    f"Population '{pop}' missing for {patient_id}"
                )


@pytest.mark.parametrize("patient_id", sorted(EXPECTED.keys()))
def test_initial_population(results, patient_id):
    actual = _to_bool(results[patient_id]["initial_population"])
    expected = EXPECTED[patient_id]["initial_population"]
    assert actual == expected, (
        f"{patient_id}: initial_population expected {expected}, got {actual}"
    )


@pytest.mark.parametrize("patient_id", sorted(EXPECTED.keys()))
def test_denominator(results, patient_id):
    actual = _to_bool(results[patient_id]["denominator"])
    expected = EXPECTED[patient_id]["denominator"]
    assert actual == expected, (
        f"{patient_id}: denominator expected {expected}, got {actual}"
    )


@pytest.mark.parametrize("patient_id", sorted(EXPECTED.keys()))
def test_denominator_exclusion(results, patient_id):
    actual = _to_bool(results[patient_id]["denominator_exclusion"])
    expected = EXPECTED[patient_id]["denominator_exclusion"]
    assert actual == expected, (
        f"{patient_id}: denominator_exclusion expected {expected}, got {actual}"
    )


@pytest.mark.parametrize("patient_id", sorted(EXPECTED.keys()))
def test_numerator(results, patient_id):
    actual = _to_bool(results[patient_id]["numerator"])
    expected = EXPECTED[patient_id]["numerator"]
    assert actual == expected, (
        f"{patient_id}: numerator expected {expected}, got {actual}"
    )
