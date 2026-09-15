
import json
import os
import pytest
import mpmath

mpmath.mp.dps = 80

RESULTS_PATH = "/app/results.json"

# Reference values computed at 120-digit precision with mpmath,
# stored here as 60-digit strings for verification.
REFERENCE = {
    1:  {"re": "-1.85982529596651900689336133556739116912747062061404767370964",
         "im": "1.16234015269686196837049566913975091403921524602376986237176"},
    2:  {"re": "0.270086646120859431397345562951406115814500406176383708642043",
         "im": "0.000375115734360918740869578750003295991978966441715805877886388"},
    3:  {"re": "1622777117670872872553379.37367371906941387834703298311855760",
         "im": "0"},
    4:  {"re": "2.30248088069423377401396160880072699263210135295806202339710",
         "im": "1.59581200100074410488060053131370897472094356819073916336684"},
    5:  {"re": "0.00000288526718512807199318290909912402796145448086529388872274097",
         "im": "0"},
    6:  {"re": "0.137669706119561091837367025056652073516307015170769979053445",
         "im": "0"},
    7:  {"re": "0.117313286148208630839033949108738340993720192343489946722760",
         "im": "0"},
    8:  {"re": "-0.985236173497738445818628795302731760107403388654840059351724",
         "im": "-0.594265541210494398417990997400340618908631504083690661065619"},
    9:  {"re": "-0.330290237630208879021700102898908069651682252521046578055900",
         "im": "0"},
    10: {"re": "1.20742359495287125943637881702828699538534894464444253753862",
         "im": "0"},
    11: {"re": "0.00810445780953053498903036991649947482189467197914261274510072",
         "im": "0.131178382604566026882555066493519908965026607438079662499099"},
    12: {"re": "765957.935048572619472967809310119791625157073699477942718724",
         "im": "0"},
    13: {"re": "-12.8277608595999166244076737112526069492374595920459687383635",
         "im": "-27.1727978667305047418758499682952327091906261754623092314742"},
    14: {"re": "1.49403375610748452989339923230107490978258275842093474225384",
         "im": "0.185361894359971342029611632704422898696157087633857901320475"},
    15: {"re": "0.520996806283172524968891241818346416556617492390195813348968",
         "im": "0"},
    16: {"re": "6.33153936413614933200278637638633557540146052837006033653933",
         "im": "0"},
    17: {"re": "0.00938816131048446671731935423249580677687277559528796193370683",
         "im": "-0.0444629941413853855904381761096661286065468871580130944048400"},
    18: {"re": "-0.000271703883506150541041840828951586500768317513984953158428705",
         "im": "0.000339932898872135952771603766620071157464141845179644403542717"},
    19: {"re": "0.278217490870828929527621508771221882742103533314263240022854",
         "im": "0"},
    20: {"re": "-1.95905526497799700982113187769841517909884617030997387338688",
         "im": "0"},
}

REQUIRED_DIGITS = 40


def load_results():
    """Load and parse the agent's results.json."""
    assert os.path.isfile(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH, "r") as f:
        data = json.load(f)
    assert isinstance(data, list), "results.json must be a JSON array"
    return {entry["id"]: entry for entry in data}


def relative_error(computed_str, reference_str):
    """Compute relative error between two decimal string representations."""
    computed = mpmath.mpf(computed_str)
    reference = mpmath.mpf(reference_str)
    if reference == 0:
        return abs(computed)
    return abs((computed - reference) / reference)


def absolute_error(computed_str, reference_str):
    """Compute absolute error between two decimal string representations."""
    computed = mpmath.mpf(computed_str)
    reference = mpmath.mpf(reference_str)
    return abs(computed - reference)


def check_accuracy(entry_id, results):
    """Check that a result matches the reference to the required digits."""
    assert entry_id in results, f"Missing result for id={entry_id}"
    result = results[entry_id]
    ref = REFERENCE[entry_id]

    # Check real part
    ref_re = mpmath.mpf(ref["re"])
    comp_re = mpmath.mpf(result["value_re"])

    # Check imaginary part
    ref_im = mpmath.mpf(ref["im"])
    comp_im = mpmath.mpf(result["value_im"])

    # Compute complex absolute error
    ref_complex = mpmath.mpc(ref_re, ref_im)
    comp_complex = mpmath.mpc(comp_re, comp_im)
    abs_err = abs(comp_complex - ref_complex)

    # Relative error threshold: 10^(-40)
    magnitude = abs(ref_complex)
    if magnitude > mpmath.mpf("1e-300"):
        rel_err = abs_err / magnitude
        assert rel_err < mpmath.mpf("1e-40"), (
            f"id={entry_id}: relative error {float(rel_err):.2e} exceeds 1e-40"
        )
    else:
        # For near-zero values, use absolute error
        assert abs_err < mpmath.mpf("1e-80"), (
            f"id={entry_id}: absolute error {float(abs_err):.2e} too large for near-zero value"
        )


class TestResultsStructure:
    """Test structural validity of results.json."""

    def test_file_exists(self):
        assert os.path.isfile(RESULTS_PATH), "results.json must exist at /app/results.json"

    def test_valid_json(self):
        with open(RESULTS_PATH, "r") as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_all_ids_present(self):
        results = load_results()
        for eid in range(1, 21):
            assert eid in results, f"Missing result for id={eid}"

    def test_required_fields(self):
        results = load_results()
        for eid in range(1, 21):
            entry = results[eid]
            assert "value_re" in entry, f"id={eid} missing value_re"
            assert "value_im" in entry, f"id={eid} missing value_im"
            assert "error_bound" in entry, f"id={eid} missing error_bound"
            assert "methods" in entry, f"id={eid} missing methods"

    def test_methods_count(self):
        results = load_results()
        for eid in range(1, 21):
            methods = results[eid]["methods"]
            assert isinstance(methods, list), f"id={eid}: methods must be a list"
            assert len(methods) >= 2, (
                f"id={eid}: must use at least 2 methods, got {len(methods)}"
            )
            # All method names must be distinct
            assert len(set(methods)) >= 2, (
                f"id={eid}: methods must be distinct, got {methods}"
            )

    def test_error_bound_valid(self):
        results = load_results()
        for eid in range(1, 21):
            eb = float(results[eid]["error_bound"])
            assert eb > 0, f"id={eid}: error_bound must be positive"
            assert eb <= 1e-40, f"id={eid}: error_bound {eb} exceeds 1e-40"


class TestAccuracyGamma:
    """Test Gamma function evaluations."""

    def test_gamma_complex(self):
        results = load_results()
        check_accuracy(1, results)

    def test_gamma_near_pole(self):
        results = load_results()
        check_accuracy(2, results)

    def test_gamma_large_real(self):
        results = load_results()
        check_accuracy(3, results)

    def test_gamma_imaginary(self):
        results = load_results()
        check_accuracy(18, results)


class TestAccuracyDigamma:
    """Test digamma function evaluations."""

    def test_digamma_complex(self):
        results = load_results()
        check_accuracy(4, results)

    def test_digamma_negative(self):
        results = load_results()
        check_accuracy(20, results)


class TestAccuracyBessel:
    """Test Bessel function evaluations."""

    def test_j0_near_zero(self):
        results = load_results()
        check_accuracy(5, results)

    def test_j20_turning_point(self):
        results = load_results()
        check_accuracy(6, results)

    def test_y0(self):
        results = load_results()
        check_accuracy(7, results)

    def test_j5_complex(self):
        results = load_results()
        check_accuracy(8, results)


class TestAccuracyAiry:
    """Test Airy function evaluations."""

    def test_ai_oscillatory(self):
        results = load_results()
        check_accuracy(9, results)

    def test_bi_transition(self):
        results = load_results()
        check_accuracy(10, results)

    def test_ai_complex(self):
        results = load_results()
        check_accuracy(11, results)

    def test_ai_deep_oscillatory(self):
        results = load_results()
        check_accuracy(19, results)


class TestAccuracyHypergeometric:
    """Test hypergeometric function evaluations."""

    def test_1f1_cancellation(self):
        results = load_results()
        check_accuracy(12, results)

    def test_1f1_complex(self):
        results = load_results()
        check_accuracy(13, results)

    def test_2f1_near_circle(self):
        results = load_results()
        check_accuracy(14, results)

    def test_2f1_negative(self):
        results = load_results()
        check_accuracy(15, results)


class TestAccuracyExpInt:
    """Test exponential integral evaluations."""

    def test_e1_near_singularity(self):
        results = load_results()
        check_accuracy(16, results)

    def test_e1_complex(self):
        results = load_results()
        check_accuracy(17, results)


class TestErrorBoundsValidity:
    """Test that reported error bounds are actually valid upper bounds."""

    def test_error_bounds_are_valid(self):
        results = load_results()
        for eid in range(1, 21):
            result = results[eid]
            ref = REFERENCE[eid]

            ref_complex = mpmath.mpc(mpmath.mpf(ref["re"]), mpmath.mpf(ref["im"]))
            comp_complex = mpmath.mpc(
                mpmath.mpf(result["value_re"]),
                mpmath.mpf(result["value_im"])
            )
            true_error = float(abs(comp_complex - ref_complex))
            reported_bound = float(result["error_bound"])

            assert reported_bound >= true_error * 0.99, (
                f"id={eid}: reported error_bound {reported_bound:.2e} is less than "
                f"actual error {true_error:.2e} (bound must be >= true error)"
            )
