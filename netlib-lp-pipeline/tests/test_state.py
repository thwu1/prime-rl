
import json
import os
import pytest

# Canonical Netlib reference values:
# - optimal_value: from MINOS 5.3 on VAX
# - num_rows/cols/nonzeros: from Netlib PROBLEM SUMMARY TABLE
#   (rows include cost row; cols/nonzeros exclude slacks but include cost row)
# - has_bounds/has_ranges: from Netlib BR column and BOUND-TYPE TABLE
REFERENCE = {
    "AFIRO": {
        "optimal_value": -4.6475314286e+02,
        "num_rows": 28, "num_cols": 32, "num_nonzeros": 88,
        "has_bounds": False, "has_ranges": False,
    },
    "SC50A": {
        "optimal_value": -6.4575077059e+01,
        "num_rows": 51, "num_cols": 48, "num_nonzeros": 131,
        "has_bounds": False, "has_ranges": False,
    },
    "ADLITTLE": {
        "optimal_value": 2.2549496316e+05,
        "num_rows": 57, "num_cols": 97, "num_nonzeros": 465,
        "has_bounds": False, "has_ranges": False,
    },
    "SHARE2B": {
        "optimal_value": -4.1573224074e+02,
        "num_rows": 97, "num_cols": 79, "num_nonzeros": 730,
        "has_bounds": False, "has_ranges": False,
    },
    "KB2": {
        "optimal_value": -1.7499001299e+03,
        "num_rows": 44, "num_cols": 41, "num_nonzeros": 291,
        "has_bounds": True, "has_ranges": False,
    },
    "BORE3D": {
        "optimal_value": 1.3730803942e+03,
        "num_rows": 234, "num_cols": 315, "num_nonzeros": 1525,
        "has_bounds": True, "has_ranges": False,
    },
    "BOEING2": {
        "optimal_value": -3.1501872802e+02,
        "num_rows": 167, "num_cols": 143, "num_nonzeros": 1339,
        "has_bounds": True, "has_ranges": True,
    },
    "CAPRI": {
        "optimal_value": 2.6900129138e+03,
        "num_rows": 272, "num_cols": 353, "num_nonzeros": 1786,
        "has_bounds": True, "has_ranges": False,
    },
}

OPT_TOLERANCE = 1e-6
DUALITY_GAP_TOLERANCE = 1e-4
CS_TOLERANCE = 1e-4


def relative_error(computed, reference):
    """Compute relative error, handling zero reference."""
    if abs(reference) < 1e-30:
        return abs(computed)
    return abs(computed - reference) / abs(reference)


@pytest.fixture(scope="module")
def results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), (
        "results.json not found at /app/results.json"
    )
    with open(results_path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json must contain a JSON object"
    return data


def test_results_file_exists():
    """Check that the results file exists and is valid JSON."""
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json root must be a JSON object"


def test_all_problems_present(results):
    """Check that all 8 problems are present in the results."""
    for name in REFERENCE:
        assert name in results, f"Problem {name} missing from results"


@pytest.mark.parametrize("problem_name", list(REFERENCE.keys()))
def test_required_fields(results, problem_name):
    """Verify all required fields are present for each problem."""
    assert problem_name in results, f"{problem_name} missing from results"
    entry = results[problem_name]
    required_fields = [
        "optimal_value", "dual_optimal_value", "duality_gap",
        "cs_max_violation", "num_rows", "num_cols", "num_nonzeros",
        "has_bounds", "has_ranges",
    ]
    for field in required_fields:
        assert field in entry, (
            f"{problem_name}: missing required field '{field}'"
        )


@pytest.mark.parametrize("problem_name", list(REFERENCE.keys()))
def test_optimal_value(results, problem_name):
    """Verify primal optimal value matches Netlib reference within tolerance."""
    assert problem_name in results, f"{problem_name} missing from results"
    entry = results[problem_name]
    computed = entry["optimal_value"]
    assert computed is not None, f"{problem_name}: optimal_value is None"
    assert isinstance(computed, (int, float)), (
        f"{problem_name}: optimal_value must be numeric, got {type(computed)}"
    )
    ref_val = REFERENCE[problem_name]["optimal_value"]
    rel_err = relative_error(computed, ref_val)
    assert rel_err < OPT_TOLERANCE, (
        f"{problem_name}: optimal value {computed:.10e} differs from reference "
        f"{ref_val:.10e} (relative error: {rel_err:.2e}, tolerance: {OPT_TOLERANCE})"
    )


@pytest.mark.parametrize("problem_name", list(REFERENCE.keys()))
def test_strong_duality(results, problem_name):
    """Verify strong duality: |primal_opt - dual_opt| < tolerance."""
    assert problem_name in results, f"{problem_name} missing from results"
    entry = results[problem_name]
    gap = entry["duality_gap"]
    assert gap is not None, (
        f"{problem_name}: duality_gap is None (dual LP solve may have failed)"
    )
    assert isinstance(gap, (int, float)), (
        f"{problem_name}: duality_gap must be numeric"
    )
    assert gap < DUALITY_GAP_TOLERANCE, (
        f"{problem_name}: duality gap {gap:.2e} exceeds tolerance "
        f"{DUALITY_GAP_TOLERANCE} — dual LP may be incorrectly constructed"
    )


@pytest.mark.parametrize("problem_name", list(REFERENCE.keys()))
def test_dual_optimal_matches_reference(results, problem_name):
    """Verify the dual optimal value also approximates the Netlib reference.
    Strong duality guarantees primal_opt = dual_opt, so the dual should
    match the reference with slightly relaxed tolerance."""
    assert problem_name in results, f"{problem_name} missing from results"
    entry = results[problem_name]
    dual_opt = entry["dual_optimal_value"]
    assert dual_opt is not None, (
        f"{problem_name}: dual_optimal_value is None"
    )
    assert isinstance(dual_opt, (int, float)), (
        f"{problem_name}: dual_optimal_value must be numeric"
    )
    ref_val = REFERENCE[problem_name]["optimal_value"]
    rel_err = relative_error(dual_opt, ref_val)
    assert rel_err < OPT_TOLERANCE * 100, (
        f"{problem_name}: dual optimal {dual_opt:.10e} too far from reference "
        f"{ref_val:.10e} (relative error: {rel_err:.2e})"
    )


@pytest.mark.parametrize("problem_name", list(REFERENCE.keys()))
def test_complementary_slackness(results, problem_name):
    """Verify complementary slackness conditions hold at the optimal solution.
    CS requires: constraint_slack * dual_variable = 0 for all pairs,
    and (x_j - l_j) * w_lj = 0, (u_j - x_j) * w_uj = 0 for all bounds."""
    assert problem_name in results, f"{problem_name} missing from results"
    entry = results[problem_name]
    cs_max = entry["cs_max_violation"]
    assert cs_max is not None, (
        f"{problem_name}: cs_max_violation is None"
    )
    assert isinstance(cs_max, (int, float)), (
        f"{problem_name}: cs_max_violation must be numeric"
    )
    assert cs_max < CS_TOLERANCE, (
        f"{problem_name}: CS violation {cs_max:.2e} exceeds tolerance "
        f"{CS_TOLERANCE} — primal/dual solutions may be inconsistent"
    )


@pytest.mark.parametrize("problem_name", list(REFERENCE.keys()))
def test_num_rows(results, problem_name):
    """Verify row count matches Netlib PROBLEM SUMMARY TABLE."""
    assert problem_name in results, f"{problem_name} missing from results"
    computed = results[problem_name]["num_rows"]
    expected = REFERENCE[problem_name]["num_rows"]
    assert computed == expected, (
        f"{problem_name}: num_rows {computed} != expected {expected}"
    )


@pytest.mark.parametrize("problem_name", list(REFERENCE.keys()))
def test_num_cols(results, problem_name):
    """Verify column count matches Netlib PROBLEM SUMMARY TABLE."""
    assert problem_name in results, f"{problem_name} missing from results"
    computed = results[problem_name]["num_cols"]
    expected = REFERENCE[problem_name]["num_cols"]
    assert computed == expected, (
        f"{problem_name}: num_cols {computed} != expected {expected}"
    )


@pytest.mark.parametrize("problem_name", list(REFERENCE.keys()))
def test_num_nonzeros(results, problem_name):
    """Verify nonzero count matches Netlib PROBLEM SUMMARY TABLE."""
    assert problem_name in results, f"{problem_name} missing from results"
    computed = results[problem_name]["num_nonzeros"]
    expected = REFERENCE[problem_name]["num_nonzeros"]
    assert computed == expected, (
        f"{problem_name}: num_nonzeros {computed} != expected {expected}"
    )


@pytest.mark.parametrize("problem_name", list(REFERENCE.keys()))
def test_has_bounds(results, problem_name):
    """Verify correct identification of BOUNDS section in MPS file."""
    assert problem_name in results, f"{problem_name} missing from results"
    computed = results[problem_name]["has_bounds"]
    expected = REFERENCE[problem_name]["has_bounds"]
    assert computed == expected, (
        f"{problem_name}: has_bounds should be {expected}, got {computed}"
    )


@pytest.mark.parametrize("problem_name", list(REFERENCE.keys()))
def test_has_ranges(results, problem_name):
    """Verify correct identification of RANGES section in MPS file."""
    assert problem_name in results, f"{problem_name} missing from results"
    computed = results[problem_name]["has_ranges"]
    expected = REFERENCE[problem_name]["has_ranges"]
    assert computed == expected, (
        f"{problem_name}: has_ranges should be {expected}, got {computed}"
    )
