
import json
import math
import pytest

RTOL = 1e-4  # relative tolerance
ATOL = 1e-10  # absolute tolerance for values near zero


def load_json(path):
    with open(path) as f:
        return json.load(f)


def approx_equal(a, b, rtol=RTOL, atol=ATOL):
    """Check approximate equality handling nulls and near-zero values."""
    if a is None or b is None:
        return False
    if isinstance(a, str) or isinstance(b, str):
        return False
    if abs(b) < atol and abs(a) < atol:
        return True
    if abs(b) < atol:
        return abs(a - b) < atol
    return abs(a - b) / max(abs(a), abs(b)) < rtol


def approx_equal_list(a, b, rtol=RTOL, atol=ATOL):
    """Check two lists are approximately equal element-wise."""
    if not isinstance(a, list) or not isinstance(b, list):
        return False
    if len(a) != len(b):
        return False
    return all(approx_equal(x, y, rtol, atol) for x, y in zip(a, b))


@pytest.fixture(scope="session")
def golden():
    """Load golden reference values produced by actuar."""
    return load_json("/tmp/golden.json")


@pytest.fixture(scope="session")
def solver_results():
    """Load solver's output."""
    return load_json("/app/results.json")


# ======================== Discretization Tests ========================

class TestDiscretization:
    def test_upper_values(self, solver_results, golden):
        assert approx_equal_list(
            solver_results["discretization"]["upper"],
            golden["discretization"]["upper"]
        ), "Upper discretization values mismatch"

    def test_lower_values(self, solver_results, golden):
        assert approx_equal_list(
            solver_results["discretization"]["lower"],
            golden["discretization"]["lower"]
        ), "Lower discretization values mismatch"

    def test_rounding_values(self, solver_results, golden):
        assert approx_equal_list(
            solver_results["discretization"]["rounding"],
            golden["discretization"]["rounding"]
        ), "Rounding discretization values mismatch"

    def test_unbiased_values(self, solver_results, golden):
        assert approx_equal_list(
            solver_results["discretization"]["unbiased"],
            golden["discretization"]["unbiased"]
        ), "Unbiased discretization values mismatch"

    def test_upper_nonnegative(self, solver_results):
        vals = solver_results["discretization"]["upper"]
        assert all(v >= -1e-15 for v in vals), "Upper PMF has negative values"

    def test_lower_nonnegative(self, solver_results):
        vals = solver_results["discretization"]["lower"]
        assert all(v >= -1e-15 for v in vals), "Lower PMF has negative values"

    def test_unbiased_nonnegative(self, solver_results):
        vals = solver_results["discretization"]["unbiased"]
        assert all(v >= -1e-15 for v in vals), "Unbiased PMF has negative values"

    def test_upper_sums_valid(self, solver_results):
        s = sum(solver_results["discretization"]["upper"])
        assert 0.99 < s <= 1.001, f"Upper PMF sum = {s}"

    def test_unbiased_sums_valid(self, solver_results):
        s = sum(solver_results["discretization"]["unbiased"])
        assert 0.99 < s <= 1.001, f"Unbiased PMF sum = {s}"

    def test_rounding_length(self, solver_results, golden):
        assert len(solver_results["discretization"]["rounding"]) == \
               len(golden["discretization"]["rounding"]), \
               "Rounding vector length mismatch"


# ======================== Aggregate Distribution Tests ========================

class TestAggregate:
    def test_mean(self, solver_results, golden):
        got = solver_results["aggregate"]["mean"]
        exp = golden["aggregate"]["mean"]
        assert approx_equal(got, exp), \
            f"Aggregate mean: got {got}, expected {exp}"

    def test_cdf_at_10(self, solver_results, golden):
        got = solver_results["aggregate"]["cdf_at_10"]
        exp = golden["aggregate"]["cdf_at_10"]
        assert approx_equal(got, exp), \
            f"CDF at 10: got {got}, expected {exp}"

    def test_cdf_at_20(self, solver_results, golden):
        got = solver_results["aggregate"]["cdf_at_20"]
        exp = golden["aggregate"]["cdf_at_20"]
        assert approx_equal(got, exp), \
            f"CDF at 20: got {got}, expected {exp}"

    def test_cdf_at_30(self, solver_results, golden):
        got = solver_results["aggregate"]["cdf_at_30"]
        exp = golden["aggregate"]["cdf_at_30"]
        assert approx_equal(got, exp), \
            f"CDF at 30: got {got}, expected {exp}"

    def test_cdf_at_40(self, solver_results, golden):
        got = solver_results["aggregate"]["cdf_at_40"]
        exp = golden["aggregate"]["cdf_at_40"]
        assert approx_equal(got, exp), \
            f"CDF at 40: got {got}, expected {exp}"

    def test_mean_reasonable(self, solver_results):
        """Aggregate mean for Poisson(10)*Gamma(2,1) should be ~20."""
        m = solver_results["aggregate"]["mean"]
        assert m is not None and 18.0 < m < 22.0, \
            f"Aggregate mean {m} is outside expected range [18,22]"


# ======================== Risk Measures Tests ========================

class TestRiskMeasures:
    def test_var_90(self, solver_results, golden):
        got = solver_results["risk_measures"]["var_90"]
        exp = golden["risk_measures"]["var_90"]
        assert approx_equal(got, exp), \
            f"VaR 90%: got {got}, expected {exp}"

    def test_var_95(self, solver_results, golden):
        got = solver_results["risk_measures"]["var_95"]
        exp = golden["risk_measures"]["var_95"]
        assert approx_equal(got, exp), \
            f"VaR 95%: got {got}, expected {exp}"

    def test_var_99(self, solver_results, golden):
        got = solver_results["risk_measures"]["var_99"]
        exp = golden["risk_measures"]["var_99"]
        assert approx_equal(got, exp), \
            f"VaR 99%: got {got}, expected {exp}"

    def test_cte_90(self, solver_results, golden):
        got = solver_results["risk_measures"]["cte_90"]
        exp = golden["risk_measures"]["cte_90"]
        assert approx_equal(got, exp), \
            f"CTE 90%: got {got}, expected {exp}"

    def test_cte_95(self, solver_results, golden):
        got = solver_results["risk_measures"]["cte_95"]
        exp = golden["risk_measures"]["cte_95"]
        assert approx_equal(got, exp), \
            f"CTE 95%: got {got}, expected {exp}"

    def test_cte_99(self, solver_results, golden):
        got = solver_results["risk_measures"]["cte_99"]
        exp = golden["risk_measures"]["cte_99"]
        assert approx_equal(got, exp), \
            f"CTE 99%: got {got}, expected {exp}"

    def test_var_ordering(self, solver_results):
        rm = solver_results["risk_measures"]
        if rm["var_90"] is not None and rm["var_95"] is not None \
                and rm["var_99"] is not None:
            assert rm["var_90"] <= rm["var_95"] <= rm["var_99"], \
                "VaR values should be non-decreasing with confidence level"

    def test_cte_exceeds_var(self, solver_results):
        rm = solver_results["risk_measures"]
        for lvl in ["90", "95", "99"]:
            v = rm.get(f"var_{lvl}")
            c = rm.get(f"cte_{lvl}")
            if v is not None and c is not None:
                assert c >= v - 1e-10, \
                    f"CTE_{lvl} = {c} should be >= VaR_{lvl} = {v}"


# ======================== Ruin Bounds Tests ========================

class TestRuinBounds:
    def test_lower_bounds(self, solver_results, golden):
        assert approx_equal_list(
            solver_results["ruin_bounds"]["lower"],
            golden["ruin_bounds"]["lower"]
        ), "Ruin lower bounds mismatch"

    def test_upper_bounds(self, solver_results, golden):
        assert approx_equal_list(
            solver_results["ruin_bounds"]["upper"],
            golden["ruin_bounds"]["upper"]
        ), "Ruin upper bounds mismatch"

    def test_lower_less_than_upper(self, solver_results):
        lower = solver_results["ruin_bounds"]["lower"]
        upper = solver_results["ruin_bounds"]["upper"]
        if lower[0] is not None and upper[0] is not None:
            for i, (l, u) in enumerate(zip(lower, upper)):
                assert l <= u + 1e-10, \
                    f"At u={i*5}: lower bound {l} > upper bound {u}"

    def test_bounds_nonnegative(self, solver_results):
        lower = solver_results["ruin_bounds"]["lower"]
        upper = solver_results["ruin_bounds"]["upper"]
        if lower[0] is not None:
            for v in lower:
                assert v >= -1e-10, f"Negative ruin lower bound: {v}"
        if upper[0] is not None:
            for v in upper:
                assert v >= -1e-10, f"Negative ruin upper bound: {v}"

    def test_bounds_at_most_one(self, solver_results):
        upper = solver_results["ruin_bounds"]["upper"]
        if upper[0] is not None:
            for v in upper:
                assert v <= 1.0 + 1e-10, f"Ruin upper bound > 1: {v}"

    def test_bounds_nonincreasing(self, solver_results):
        lower = solver_results["ruin_bounds"]["lower"]
        upper = solver_results["ruin_bounds"]["upper"]
        if lower[0] is not None:
            for i in range(1, len(lower)):
                assert lower[i] <= lower[i-1] + 1e-10, \
                    f"Lower bounds not non-increasing at index {i}"
        if upper[0] is not None:
            for i in range(1, len(upper)):
                assert upper[i] <= upper[i-1] + 1e-10, \
                    f"Upper bounds not non-increasing at index {i}"
