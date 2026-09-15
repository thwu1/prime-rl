
import json
import os
import pytest

RESULTS_PATH = "/app/results.json"

# Pre-computed reference values from the full simulation
REFERENCE = {
    "net_revenue_month_1": 5545174.07,
    "net_revenue_month_12": 6168497.89,
    "net_revenue_month_24": 6954646.97,
    "net_revenue_month_36": 7760239.1,
    "net_revenue_month_48": 8397126.15,
    "net_revenue_month_60": 9324182.24,
    "cumulative_net_revenue": 441265073.95,
    "first_price_change_month_usa": 15,
    "first_price_change_month_aus": 9,
    "first_price_change_month_uk": 17,
    "total_subscribers_month_60": 213531,
    "usa_professional_charged_price_month_36": 74.99,
    "cumulative_ecl_provision_usd": 7696690.56,
    "cumulative_hedge_gain_usd": 493154.41,
    "aus_effective_fx_rate_2026": 0.644,
    "npv_cumulative_revenue": 387096283.49,
    "effective_hedge_count": 8,
    "weighted_avg_ecl_rate": 0.015478,
}

REL_TOL = 0.005  # 0.5% relative tolerance for monetary values


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}"
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


def _check_monetary(results, key):
    assert key in results, f"Missing key: {key}"
    actual = float(results[key])
    expected = REFERENCE[key]
    rel_err = abs(actual - expected) / abs(expected)
    assert rel_err < REL_TOL, (
        f"{key}: expected {expected}, got {actual}, "
        f"relative error {rel_err:.4%} exceeds {REL_TOL:.1%}"
    )


def _check_exact_int(results, key):
    assert key in results, f"Missing key: {key}"
    actual = int(results[key])
    expected = REFERENCE[key]
    assert actual == expected, (
        f"{key}: expected {expected}, got {actual}"
    )


def _check_exact_float(results, key, decimals=2):
    assert key in results, f"Missing key: {key}"
    actual = round(float(results[key]), decimals)
    expected = REFERENCE[key]
    assert actual == expected, (
        f"{key}: expected {expected}, got {actual}"
    )


class TestOutputStructure:
    """Verify results.json exists and has the required schema."""

    def test_results_file_exists(self, results):
        assert isinstance(results, dict)

    def test_all_required_keys_present(self, results):
        missing = set(REFERENCE.keys()) - set(results.keys())
        assert not missing, f"Missing keys: {missing}"


class TestMonthlyRevenue:
    """Verify monthly net revenue at checkpoint months."""

    def test_revenue_month_1(self, results):
        _check_monetary(results, "net_revenue_month_1")

    def test_revenue_month_12(self, results):
        _check_monetary(results, "net_revenue_month_12")

    def test_revenue_month_24(self, results):
        _check_monetary(results, "net_revenue_month_24")

    def test_revenue_month_36(self, results):
        _check_monetary(results, "net_revenue_month_36")

    def test_revenue_month_48(self, results):
        _check_monetary(results, "net_revenue_month_48")

    def test_revenue_month_60(self, results):
        _check_monetary(results, "net_revenue_month_60")

    def test_cumulative_revenue(self, results):
        _check_monetary(results, "cumulative_net_revenue")


class TestPricingMechanism:
    """Verify consensus-based pricing trigger timing and outcomes."""

    def test_first_price_change_usa(self, results):
        _check_exact_int(results, "first_price_change_month_usa")

    def test_first_price_change_aus(self, results):
        _check_exact_int(results, "first_price_change_month_aus")

    def test_first_price_change_uk(self, results):
        _check_exact_int(results, "first_price_change_month_uk")

    def test_usa_professional_price_month_36(self, results):
        _check_exact_float(results, "usa_professional_charged_price_month_36")


class TestSubscriberGrowth:
    """Verify subscriber projection at end of forecast horizon."""

    def test_total_subscribers_month_60(self, results):
        _check_exact_int(results, "total_subscribers_month_60")


class TestCreditProvisions:
    """Verify probability-weighted ECL provision computation."""

    def test_cumulative_ecl_provision(self, results):
        _check_monetary(results, "cumulative_ecl_provision_usd")

    def test_weighted_avg_ecl_rate(self, results):
        _check_exact_float(results, "weighted_avg_ecl_rate", decimals=6)


class TestHedgeAccounting:
    """Verify FX hedge accounting with effectiveness testing."""

    def test_cumulative_hedge_gain(self, results):
        _check_monetary(results, "cumulative_hedge_gain_usd")

    def test_aus_effective_fx_rate_2026(self, results):
        _check_exact_float(results, "aus_effective_fx_rate_2026", decimals=4)

    def test_effective_hedge_count(self, results):
        _check_exact_int(results, "effective_hedge_count")


class TestYieldCurveDiscounting:
    """Verify NPV computation using bootstrapped zero-coupon curve."""

    def test_npv_cumulative_revenue(self, results):
        _check_monetary(results, "npv_cumulative_revenue")
