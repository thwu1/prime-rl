
import json
import math
import os
import pytest


RESULTS_PATH = "/app/results.json"


def relative_error(computed, reference, floor):
    """Compute relative error with an absolute floor for near-zero reference values."""
    return abs(computed - reference) / max(abs(reference), floor)


def load_results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


# ============================================================
# High-precision reference solutions (computed with Radau, rtol=1e-13, atol=1e-22)
# ============================================================

ROBER_REFERENCE = {
    "0.4":      [9.85172113860989129e-01, 3.38639537897490351e-05, 1.47940221852203447e-02],
    "4.0":      [9.05518678584253611e-01, 2.24047568756020055e-05, 9.44589166588701706e-02],
    "40.0":     [7.15827068719418147e-01, 9.18553476455711886e-06, 2.84163745745817875e-01],
    "400.0":    [4.50518668471106387e-01, 3.22290144167464875e-06, 5.49478108627451167e-01],
    "4000.0":   [1.83202257776715366e-01, 8.94237125277625788e-07, 8.16796847986160479e-01],
    "40000.0":  [3.89833770854878178e-02, 1.62176831590989452e-07, 9.61016460737681988e-01],
    "400000.0": [4.93827452098043879e-03, 1.98499408795462968e-08, 9.95061705629077586e-01],
}

HIRES_REFERENCE = {
    "200.0": [
        2.73651205813291772e-03, 5.35188152620779106e-04, 4.48509236242137924e-04,
        4.68813719637433627e-03, 7.08339578827022753e-02, 2.80462204558611539e-01,
        5.57159613406746964e-03, 1.28403865932528207e-04,
    ],
    "321.8122": [
        7.37131257332541263e-04, 1.44248572631613383e-04, 5.88872974096710624e-05,
        1.17565134328310051e-03, 2.38635619883059702e-03, 6.23896825274066012e-03,
        2.84999839518513274e-03, 2.85000160481489176e-03,
    ],
    "421.8122": [
        6.70305503581863547e-04, 1.30996846986346894e-04, 4.68622315977325888e-05,
        1.04466802055170477e-03, 5.94883830951485832e-04, 1.39962883394277268e-03,
        1.01449275771848331e-03, 4.68550724228153966e-03,
    ],
}

E5_REFERENCE = {
    "1.0":     [1.75999925606971572e-03, 1.38859969865607908e-12, 7.66437398977926545e-14, 1.31195595875828615e-12],
    "10.0":    [1.75992594976778836e-03, 1.38462815193641300e-11, 7.63700385300038328e-13, 1.30825811340640897e-11],
    "100.0":   [1.75346560834275600e-03, 1.08890610158055540e-10, 6.02636214012643799e-12, 1.02864248017929247e-10],
    "1000.0":  [1.61807699990729973e-03, 1.38223703049841006e-10, 8.25157350068418272e-12, 1.29972129549156238e-10],
    "10000.0": [7.24041390189715962e-04, 6.40799712116015275e-11, 7.96203400004295567e-12, 5.61179372115576719e-11],
}


# ============================================================
# Tests
# ============================================================

class TestResultsStructure:
    """Verify the results file exists and has the correct structure."""

    def test_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found"

    def test_valid_json(self):
        data = load_results()
        assert isinstance(data, dict)

    def test_has_all_problems(self):
        data = load_results()
        for problem in ["rober", "hires", "e5"]:
            assert problem in data, f"Missing problem: {problem}"

    def test_rober_structure(self):
        data = load_results()
        rober = data["rober"]
        assert "solutions" in rober, "rober missing 'solutions'"
        assert "conservation_max_error" in rober, "rober missing 'conservation_max_error'"
        sols = rober["solutions"]
        expected_times = ["0.4", "4.0", "40.0", "400.0", "4000.0", "40000.0", "400000.0"]
        for t in expected_times:
            assert t in sols, f"rober missing time point {t}"
            assert len(sols[t]) == 3, f"rober at t={t}: expected 3 components, got {len(sols[t])}"

    def test_hires_structure(self):
        data = load_results()
        hires = data["hires"]
        assert "solutions" in hires, "hires missing 'solutions'"
        assert "invariant_max_error" in hires, "hires missing 'invariant_max_error'"
        sols = hires["solutions"]
        expected_times = ["200.0", "321.8122", "421.8122"]
        for t in expected_times:
            assert t in sols, f"hires missing time point {t}"
            assert len(sols[t]) == 8, f"hires at t={t}: expected 8 components, got {len(sols[t])}"

    def test_e5_structure(self):
        data = load_results()
        e5 = data["e5"]
        assert "solutions" in e5, "e5 missing 'solutions'"
        sols = e5["solutions"]
        expected_times = ["1.0", "10.0", "100.0", "1000.0", "10000.0"]
        for t in expected_times:
            assert t in sols, f"e5 missing time point {t}"
            assert len(sols[t]) == 4, f"e5 at t={t}: expected 4 components, got {len(sols[t])}"


class TestRoberAccuracy:
    """Verify ROBER solutions match reference to 6 significant digits."""

    @pytest.mark.parametrize("t_str", list(ROBER_REFERENCE.keys()))
    def test_rober_solution(self, t_str):
        data = load_results()
        computed = data["rober"]["solutions"][t_str]
        reference = ROBER_REFERENCE[t_str]
        for i in range(3):
            err = relative_error(computed[i], reference[i], floor=1e-12)
            assert err < 1e-4, (
                f"ROBER at t={t_str}, component y{i+1}: "
                f"computed={computed[i]:.10e}, reference={reference[i]:.10e}, "
                f"relative error={err:.2e} exceeds 1e-4"
            )

    def test_rober_conservation(self):
        data = load_results()
        max_err = data["rober"]["conservation_max_error"]
        assert isinstance(max_err, (int, float)), "conservation_max_error must be numeric"
        assert max_err < 1e-8, (
            f"ROBER conservation error {max_err:.2e} exceeds 1e-8"
        )
        # Also independently verify conservation from solutions
        sols = data["rober"]["solutions"]
        for t_str, y in sols.items():
            cons_err = abs(sum(y) - 1.0)
            assert cons_err < 1e-8, (
                f"ROBER conservation violated at t={t_str}: "
                f"|y1+y2+y3 - 1| = {cons_err:.2e}"
            )


class TestHiresAccuracy:
    """Verify HIRES solutions match reference to 6 significant digits."""

    @pytest.mark.parametrize("t_str", list(HIRES_REFERENCE.keys()))
    def test_hires_solution(self, t_str):
        data = load_results()
        computed = data["hires"]["solutions"][t_str]
        reference = HIRES_REFERENCE[t_str]
        for i in range(8):
            err = relative_error(computed[i], reference[i], floor=1e-10)
            assert err < 1e-4, (
                f"HIRES at t={t_str}, component y{i+1}: "
                f"computed={computed[i]:.10e}, reference={reference[i]:.10e}, "
                f"relative error={err:.2e} exceeds 1e-4"
            )

    def test_hires_invariant(self):
        data = load_results()
        max_err = data["hires"]["invariant_max_error"]
        assert isinstance(max_err, (int, float)), "invariant_max_error must be numeric"
        assert max_err < 1e-6, (
            f"HIRES invariant error {max_err:.2e} exceeds 1e-6"
        )
        # Also independently verify from solutions
        sols = data["hires"]["solutions"]
        for t_str, y in sols.items():
            inv_err = abs(y[6] + y[7] - 0.0057)
            assert inv_err < 1e-6, (
                f"HIRES invariant violated at t={t_str}: "
                f"|y7+y8 - 0.0057| = {inv_err:.2e}"
            )


class TestE5Accuracy:
    """Verify E5 solutions match reference to 4 significant digits."""

    @pytest.mark.parametrize("t_str", list(E5_REFERENCE.keys()))
    def test_e5_solution(self, t_str):
        data = load_results()
        computed = data["e5"]["solutions"][t_str]
        reference = E5_REFERENCE[t_str]
        for i in range(4):
            err = relative_error(computed[i], reference[i], floor=1e-18)
            assert err < 1e-2, (
                f"E5 at t={t_str}, component y{i+1}: "
                f"computed={computed[i]:.10e}, reference={reference[i]:.10e}, "
                f"relative error={err:.2e} exceeds 1e-2"
            )

    def test_e5_first_component_accuracy(self):
        """y1 is the largest component and should be very accurate."""
        data = load_results()
        for t_str, ref in E5_REFERENCE.items():
            computed = data["e5"]["solutions"][t_str]
            err = relative_error(computed[0], ref[0], floor=1e-18)
            assert err < 1e-4, (
                f"E5 y1 at t={t_str}: computed={computed[0]:.10e}, "
                f"reference={ref[0]:.10e}, relative error={err:.2e} exceeds 1e-4"
            )


class TestNumericalProperties:
    """Verify important numerical properties beyond just matching reference values."""

    def test_rober_y2_positivity(self):
        """y2 in ROBER must remain positive (physical constraint)."""
        data = load_results()
        for t_str, y in data["rober"]["solutions"].items():
            assert y[1] > 0, f"ROBER y2 is non-positive at t={t_str}: {y[1]}"

    def test_rober_all_positive(self):
        """All ROBER concentrations must be non-negative."""
        data = load_results()
        for t_str, y in data["rober"]["solutions"].items():
            for i, val in enumerate(y):
                assert val >= 0, f"ROBER y{i+1} is negative at t={t_str}: {val}"

    def test_e5_all_nonnegative(self):
        """All E5 concentrations must be non-negative."""
        data = load_results()
        for t_str, y in data["e5"]["solutions"].items():
            for i, val in enumerate(y):
                assert val >= -1e-20, f"E5 y{i+1} is negative at t={t_str}: {val}"

    def test_hires_all_nonnegative(self):
        """All HIRES concentrations must be non-negative."""
        data = load_results()
        for t_str, y in data["hires"]["solutions"].items():
            for i, val in enumerate(y):
                assert val >= -1e-10, f"HIRES y{i+1} is negative at t={t_str}: {val}"

    def test_e5_y1_monotone_decreasing(self):
        """E5 y1 should be monotonically decreasing over the time range."""
        data = load_results()
        e5 = data["e5"]["solutions"]
        times = sorted(e5.keys(), key=float)
        for i in range(len(times) - 1):
            y1_curr = e5[times[i]][0]
            y1_next = e5[times[i + 1]][0]
            assert y1_next < y1_curr, (
                f"E5 y1 not decreasing: y1({times[i]})={y1_curr:.6e} vs y1({times[i+1]})={y1_next:.6e}"
            )
