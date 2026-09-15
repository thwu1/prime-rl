"""
Test suite for short-rate model calibration and Bermudan swaption pricing.

Independently computes reference values using QuantLib and compares
against the agent's /app/results.json.

"""

import json
import os
import math

import pytest
import QuantLib as ql


# ---------------------------------------------------------------------------
# Reference computation helpers
# ---------------------------------------------------------------------------

def _load_market_data():
    with open("/app/market_data.json") as f:
        return json.load(f)


def _setup_curve(data, rate_override=None):
    """Build the flat-forward yield curve and set evaluation date."""
    parts = data["evaluation_date"].split("-")
    eval_date = ql.Date(int(parts[2]), int(parts[1]), int(parts[0]))
    ql.Settings.instance().evaluationDate = eval_date

    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    day_count = ql.Actual365Fixed()
    rate = rate_override if rate_override is not None else data["flat_forward_rate"]

    ts = ql.YieldTermStructureHandle(
        ql.FlatForward(data["settlement_days"], calendar, rate, day_count)
    )
    return eval_date, calendar, day_count, ts


def _calibrate(data, term_structure):
    """Calibrate HW1F to the swaption data and return model + helpers."""
    index = ql.Euribor1Y(term_structure)
    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    model = ql.HullWhite(term_structure)
    engine = ql.JamshidianSwaptionEngine(model)

    helpers = []
    for s in data["swaption_data"]:
        h = ql.SwaptionHelper(
            ql.Period(s["expiry_years"], ql.Years),
            ql.Period(s["tenor_years"], ql.Years),
            ql.QuoteHandle(ql.SimpleQuote(s["volatility"])),
            index,
            ql.Period(1, ql.Years),
            ql.Thirty360(ql.Thirty360.BondBasis),
            ql.Actual360(),
            term_structure,
        )
        h.setPricingEngine(engine)
        helpers.append(h)

    opt = ql.LevenbergMarquardt(1e-8, 1e-8, 1e-8)
    ec = ql.EndCriteria(10000, 100, 1e-6, 1e-8, 1e-8)
    model.calibrate(helpers, opt, ec)

    return model, helpers, index


def _make_swap(data, calendar, index, eval_date):
    """Create the underlying VanillaSwap for the Bermudan spec."""
    spec = data["bermudan_spec"]
    swap_start = calendar.advance(eval_date, ql.Period(1, ql.Years))
    swap_maturity = calendar.advance(eval_date, ql.Period(6, ql.Years))

    fixed_sched = ql.Schedule(
        swap_start, swap_maturity, ql.Period(1, ql.Years), calendar,
        ql.ModifiedFollowing, ql.ModifiedFollowing,
        ql.DateGeneration.Forward, False,
    )
    float_sched = ql.Schedule(
        swap_start, swap_maturity, ql.Period(6, ql.Months), calendar,
        ql.ModifiedFollowing, ql.ModifiedFollowing,
        ql.DateGeneration.Forward, False,
    )

    return ql.VanillaSwap(
        ql.VanillaSwap.Payer, spec["notional"], fixed_sched,
        spec["fixed_rate"], ql.Thirty360(ql.Thirty360.BondBasis),
        float_sched, index, 0.0, ql.Actual360(),
    )


def _european_price(data, model, calendar, index, eval_date):
    exercise_date = calendar.advance(eval_date, ql.Period(1, ql.Years))
    swap = _make_swap(data, calendar, index, eval_date)
    swaption = ql.Swaption(swap, ql.EuropeanExercise(exercise_date))
    swaption.setPricingEngine(ql.JamshidianSwaptionEngine(model))
    return swaption.NPV()


def _bermudan_price(data, model, calendar, index, eval_date, grid=720):
    spec = data["bermudan_spec"]
    swap = _make_swap(data, calendar, index, eval_date)
    ex_dates = [
        calendar.advance(eval_date, ql.Period(y, ql.Years))
        for y in spec["exercise_years"]
    ]
    swaption = ql.Swaption(swap, ql.BermudanExercise(ex_dates))
    swaption.setPricingEngine(ql.TreeSwaptionEngine(model, grid))
    return swaption.NPV()


def _compute_reference():
    """Full reference computation. Returns dict of reference values."""
    data = _load_market_data()

    eval_date, calendar, day_count, ts = _setup_curve(data)
    model, helpers, index = _calibrate(data, ts)
    a_ref, sigma_ref = model.params()

    eu_price = _european_price(data, model, calendar, index, eval_date)
    berm_price = _bermudan_price(data, model, calendar, index, eval_date)
    premium = (berm_price / eu_price - 1.0) * 100.0

    # DV01: bump +1bp, keep model params fixed, reprice Bermudan
    bumped_rate = data["flat_forward_rate"] + 0.0001
    _, calendar_b, _, ts_b = _setup_curve(data, rate_override=bumped_rate)
    bumped_model = ql.HullWhite(ts_b, a_ref, sigma_ref)
    bumped_index = ql.Euribor1Y(ts_b)
    berm_bumped = _bermudan_price(data, bumped_model, calendar_b, bumped_index, eval_date)
    dv01_ref = berm_bumped - berm_price

    return {
        "calibrated_a": a_ref,
        "calibrated_sigma": sigma_ref,
        "european_swaption_price": eu_price,
        "bermudan_swaption_price": berm_price,
        "bermudan_premium_pct": premium,
        "dv01": dv01_ref,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def reference():
    return _compute_reference()


@pytest.fixture(scope="module")
def agent_results():
    path = "/app/results.json"
    if not os.path.exists(path):
        pytest.fail(f"{path} not found — agent did not produce output")
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestResultsStructure:
    """Verify the agent output has the right shape."""

    REQUIRED_KEYS = [
        "calibrated_a",
        "calibrated_sigma",
        "european_swaption_price",
        "bermudan_swaption_price",
        "bermudan_premium_pct",
        "dv01",
    ]

    def test_all_keys_present(self, agent_results):
        for key in self.REQUIRED_KEYS:
            assert key in agent_results, f"Missing key: {key}"

    def test_all_values_numeric(self, agent_results):
        for key in self.REQUIRED_KEYS:
            val = agent_results[key]
            assert isinstance(val, (int, float)), (
                f"{key} must be numeric, got {type(val).__name__}"
            )


class TestCalibration:
    """Verify calibrated Hull-White parameters."""

    def test_mean_reversion(self, agent_results, reference):
        a_agent = agent_results["calibrated_a"]
        a_ref = reference["calibrated_a"]
        rel_err = abs(a_agent - a_ref) / abs(a_ref)
        assert rel_err < 0.05, (
            f"calibrated_a: agent={a_agent:.6f}, ref={a_ref:.6f}, "
            f"rel_err={rel_err:.4f} (>5%)"
        )

    def test_sigma(self, agent_results, reference):
        s_agent = agent_results["calibrated_sigma"]
        s_ref = reference["calibrated_sigma"]
        rel_err = abs(s_agent - s_ref) / abs(s_ref)
        assert rel_err < 0.05, (
            f"calibrated_sigma: agent={s_agent:.6f}, ref={s_ref:.6f}, "
            f"rel_err={rel_err:.4f} (>5%)"
        )

    def test_mean_reversion_positive(self, agent_results):
        assert agent_results["calibrated_a"] > 0, "Mean reversion must be positive"

    def test_sigma_positive(self, agent_results):
        assert agent_results["calibrated_sigma"] > 0, "Volatility must be positive"


class TestEuropeanPrice:
    """Verify the European swaption price."""

    def test_european_matches_reference(self, agent_results, reference):
        eu_agent = agent_results["european_swaption_price"]
        eu_ref = reference["european_swaption_price"]
        rel_err = abs(eu_agent - eu_ref) / abs(eu_ref)
        assert rel_err < 0.03, (
            f"european_swaption_price: agent={eu_agent:.2f}, ref={eu_ref:.2f}, "
            f"rel_err={rel_err:.4f} (>3%)"
        )

    def test_european_positive(self, agent_results):
        assert agent_results["european_swaption_price"] > 0, (
            "European swaption price must be positive"
        )


class TestBermudanPrice:
    """Verify the Bermudan swaption price."""

    def test_bermudan_matches_reference(self, agent_results, reference):
        b_agent = agent_results["bermudan_swaption_price"]
        b_ref = reference["bermudan_swaption_price"]
        rel_err = abs(b_agent - b_ref) / abs(b_ref)
        assert rel_err < 0.05, (
            f"bermudan_swaption_price: agent={b_agent:.2f}, ref={b_ref:.2f}, "
            f"rel_err={rel_err:.4f} (>5%)"
        )

    def test_bermudan_exceeds_european(self, agent_results):
        assert agent_results["bermudan_swaption_price"] > agent_results["european_swaption_price"], (
            "Bermudan price must exceed European price (early exercise premium)"
        )

    def test_bermudan_positive(self, agent_results):
        assert agent_results["bermudan_swaption_price"] > 0, (
            "Bermudan swaption price must be positive"
        )


class TestPremium:
    """Verify the early exercise premium percentage."""

    def test_premium_positive(self, agent_results):
        assert agent_results["bermudan_premium_pct"] > 0, (
            "Bermudan premium must be positive"
        )

    def test_premium_consistent(self, agent_results):
        eu = agent_results["european_swaption_price"]
        berm = agent_results["bermudan_swaption_price"]
        expected = (berm / eu - 1.0) * 100.0
        actual = agent_results["bermudan_premium_pct"]
        assert abs(actual - expected) < 0.5, (
            f"bermudan_premium_pct inconsistent: reported={actual:.4f}, "
            f"computed from prices={expected:.4f}"
        )

    def test_premium_matches_reference(self, agent_results, reference):
        p_agent = agent_results["bermudan_premium_pct"]
        p_ref = reference["bermudan_premium_pct"]
        assert abs(p_agent - p_ref) < max(0.20 * abs(p_ref), 2.0), (
            f"bermudan_premium_pct: agent={p_agent:.4f}, ref={p_ref:.4f}"
        )


class TestDV01:
    """Verify the DV01 sensitivity."""

    def test_dv01_sign(self, agent_results):
        # For a payer swaption, DV01 should be positive (value increases with rates)
        assert agent_results["dv01"] > 0, (
            "DV01 for a payer swaption must be positive"
        )

    def test_dv01_matches_reference(self, agent_results, reference):
        d_agent = agent_results["dv01"]
        d_ref = reference["dv01"]
        rel_err = abs(d_agent - d_ref) / abs(d_ref)
        assert rel_err < 0.10, (
            f"dv01: agent={d_agent:.4f}, ref={d_ref:.4f}, "
            f"rel_err={rel_err:.4f} (>10%)"
        )

    def test_dv01_reasonable_magnitude(self, agent_results):
        # DV01 for 10M notional, ~5Y tenor should be roughly O(100-10000)
        dv01 = abs(agent_results["dv01"])
        assert 1.0 < dv01 < 100000.0, (
            f"DV01 magnitude {dv01} seems unreasonable for 10M notional 5Y swaption"
        )
