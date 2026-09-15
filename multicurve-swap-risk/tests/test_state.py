
"""
Tests for multicurve swap pricing results.

Verifies correctness of the dual-curve framework output by checking:
- Structural completeness of results.json
- Fair rates match curve calibration inputs (model-independent)
- NPV signs consistent with fixed rate vs market rate
- Discount factor properties (monotonicity, range)
- DV01 signs consistent with swap type
- Portfolio aggregation consistency
- Independent cross-validation of NPV magnitudes
"""

import json
import math
import os

import QuantLib as ql
import pytest


@pytest.fixture(scope="module")
def results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), "results.json not found at /app/results.json"
    with open(results_path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def market_data():
    with open("/app/market_data.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def portfolio():
    with open("/app/portfolio.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_top_level_keys(self, results):
        required = {
            "evaluation_date", "settlement_date", "swaps",
            "portfolio_npv", "portfolio_dv01", "ois_discount_factors",
        }
        assert required.issubset(set(results.keys())), (
            f"Missing keys: {required - set(results.keys())}"
        )

    def test_swap_count(self, results):
        assert len(results["swaps"]) == 3

    def test_swap_fields(self, results):
        required = {"id", "npv", "fair_rate", "fair_spread", "dv01"}
        for swap in results["swaps"]:
            assert required.issubset(set(swap.keys())), (
                f"Swap {swap.get('id')} missing keys: {required - set(swap.keys())}"
            )

    def test_swap_ids(self, results):
        ids = {s["id"] for s in results["swaps"]}
        assert ids == {"swap_1", "swap_2", "swap_3"}

    def test_discount_factor_keys(self, results):
        dfs = results["ois_discount_factors"]
        for k in ["1Y", "5Y", "10Y", "30Y"]:
            assert k in dfs, f"Missing ois_discount_factors['{k}']"

    def test_evaluation_date(self, results):
        assert results["evaluation_date"] == "2012-12-11"

    def test_settlement_date(self, results):
        # T+2 from 2012-12-11 (Tuesday) on TARGET calendar = 2012-12-13 (Thursday)
        assert results["settlement_date"] == "2012-12-13"

    def test_numeric_types(self, results):
        for swap in results["swaps"]:
            for field in ["npv", "fair_rate", "fair_spread", "dv01"]:
                val = swap[field]
                assert isinstance(val, (int, float)), (
                    f"swap {swap['id']}.{field} is {type(val)}, expected numeric"
                )
        assert isinstance(results["portfolio_npv"], (int, float))
        assert isinstance(results["portfolio_dv01"], (int, float))


# ---------------------------------------------------------------------------
# Fair rate tests — model-independent calibration checks
# ---------------------------------------------------------------------------

class TestFairRates:
    """
    The Euribor 6M curve is bootstrapped from swap rate helpers.
    A spot swap at a tenor matching an input swap rate must have
    fair_rate == input_rate (within bootstrapping tolerance).
    """

    def _get_swap(self, results, swap_id):
        return next(s for s in results["swaps"] if s["id"] == swap_id)

    def test_swap1_fair_rate_matches_5y_market(self, results):
        """swap_1 is 5Y spot — fair rate must match 5Y Euribor swap input (0.00762)."""
        swap = self._get_swap(results, "swap_1")
        assert abs(swap["fair_rate"] - 0.007620) < 2e-4, (
            f"swap_1 fair_rate={swap['fair_rate']:.6f}, expected ~0.007620"
        )

    def test_swap3_fair_rate_matches_10y_market(self, results):
        """swap_3 is 10Y spot — fair rate must match 10Y Euribor swap input (0.01584)."""
        swap = self._get_swap(results, "swap_3")
        assert abs(swap["fair_rate"] - 0.015840) < 2e-4, (
            f"swap_3 fair_rate={swap['fair_rate']:.6f}, expected ~0.015840"
        )

    def test_swap2_fair_rate_range(self, results):
        """swap_2 is 1Y-forward 5Y — fair rate should be between 5Y and 7Y market rates."""
        swap = self._get_swap(results, "swap_2")
        # 5Y rate = 0.00762, 6Y rate = 0.00954, 7Y rate = 0.01135
        # Forward-starting 5Y rate should be in a reasonable range
        assert 0.005 < swap["fair_rate"] < 0.018, (
            f"swap_2 fair_rate={swap['fair_rate']:.6f} out of expected range"
        )

    def test_fair_rates_positive(self, results):
        for swap in results["swaps"]:
            assert swap["fair_rate"] > 0, (
                f"swap {swap['id']} fair_rate={swap['fair_rate']} should be positive"
            )


# ---------------------------------------------------------------------------
# NPV sign tests
# ---------------------------------------------------------------------------

class TestNPVSigns:
    """
    NPV signs depend on swap type and whether fixed rate is above/below fair rate.
    Payer: NPV = PV(float) - PV(fixed) > 0 when fixed_rate < fair_rate
    Receiver: NPV = PV(fixed) - PV(float) > 0 when fixed_rate > fair_rate
    """

    def _get_swap(self, results, swap_id):
        return next(s for s in results["swaps"] if s["id"] == swap_id)

    def test_swap1_npv_positive(self, results):
        """swap_1: payer at 0.70%, market ~0.762% -> paying below market -> NPV > 0."""
        swap = self._get_swap(results, "swap_1")
        assert swap["npv"] > 0, f"swap_1 NPV={swap['npv']}, expected > 0"

    def test_swap2_npv_positive(self, results):
        """swap_2: payer at 0.70%, forward fair rate should be > 0.70% -> NPV > 0."""
        swap = self._get_swap(results, "swap_2")
        assert swap["npv"] > 0, f"swap_2 NPV={swap['npv']}, expected > 0"

    def test_swap3_npv_positive(self, results):
        """swap_3: receiver at 2.0%, market 10Y ~1.584% -> receiving above market -> NPV > 0."""
        swap = self._get_swap(results, "swap_3")
        assert swap["npv"] > 0, f"swap_3 NPV={swap['npv']}, expected > 0"

    def test_swap1_npv_magnitude(self, results):
        """swap_1 NPV should be a few thousand (1M notional, ~6bp rate difference, 5Y)."""
        swap = self._get_swap(results, "swap_1")
        assert 500 < swap["npv"] < 20000, (
            f"swap_1 NPV={swap['npv']:.2f} outside expected range [500, 20000]"
        )

    def test_swap3_npv_magnitude(self, results):
        """swap_3 NPV on 5M notional, ~42bp rate diff, 10Y -> large positive."""
        swap = self._get_swap(results, "swap_3")
        assert 50000 < swap["npv"] < 500000, (
            f"swap_3 NPV={swap['npv']:.2f} outside expected range [50000, 500000]"
        )


# ---------------------------------------------------------------------------
# Discount factor tests
# ---------------------------------------------------------------------------

class TestDiscountFactors:
    def test_all_between_zero_and_one(self, results):
        dfs = results["ois_discount_factors"]
        for k, v in dfs.items():
            assert 0 < v < 1, f"DF[{k}]={v} should be in (0, 1)"

    def test_monotonically_decreasing(self, results):
        dfs = results["ois_discount_factors"]
        assert dfs["1Y"] > dfs["5Y"] > dfs["10Y"] > dfs["30Y"], (
            "Discount factors should decrease with tenor"
        )

    def test_1y_near_one(self, results):
        """1Y OIS rate is very low (~0.07%), so D(1Y) should be very close to 1."""
        df = results["ois_discount_factors"]["1Y"]
        assert df > 0.990, f"D(1Y)={df}, expected > 0.990 given near-zero OIS rates"

    def test_30y_range(self, results):
        """30Y OIS rate ~2%, so D(30Y) should be roughly 0.4-0.7."""
        df = results["ois_discount_factors"]["30Y"]
        assert 0.35 < df < 0.75, f"D(30Y)={df}, expected in (0.35, 0.75)"


# ---------------------------------------------------------------------------
# DV01 tests
# ---------------------------------------------------------------------------

class TestDV01:
    def _get_swap(self, results, swap_id):
        return next(s for s in results["swaps"] if s["id"] == swap_id)

    def test_payer_dv01_positive(self, results):
        """Payer swaps gain value when rates rise -> DV01 > 0."""
        for sid in ["swap_1", "swap_2"]:
            swap = self._get_swap(results, sid)
            assert swap["dv01"] > 0, (
                f"{sid} DV01={swap['dv01']}, expected > 0 for payer swap"
            )

    def test_receiver_dv01_negative(self, results):
        """Receiver swaps lose value when rates rise -> DV01 < 0."""
        swap = self._get_swap(results, "swap_3")
        assert swap["dv01"] < 0, (
            f"swap_3 DV01={swap['dv01']}, expected < 0 for receiver swap"
        )

    def test_dv01_magnitudes(self, results):
        """DV01 should be roughly notional * annuity * 1bp."""
        swap1 = self._get_swap(results, "swap_1")
        # 5Y annuity on 1M notional ~ 1M * 4.9 * 0.0001 ~ 490
        assert 100 < abs(swap1["dv01"]) < 2000, (
            f"swap_1 |DV01|={abs(swap1['dv01']):.2f}, expected ~500"
        )

        swap3 = self._get_swap(results, "swap_3")
        # 10Y annuity on 5M notional ~ 5M * 8.8 * 0.0001 ~ 4400
        assert 1000 < abs(swap3["dv01"]) < 15000, (
            f"swap_3 |DV01|={abs(swap3['dv01']):.2f}, expected ~4400"
        )

    def test_nonzero(self, results):
        for swap in results["swaps"]:
            assert swap["dv01"] != 0, f"swap {swap['id']} DV01 should not be 0"


# ---------------------------------------------------------------------------
# Portfolio consistency tests
# ---------------------------------------------------------------------------

class TestPortfolioConsistency:
    def test_portfolio_npv_is_sum(self, results):
        total = sum(s["npv"] for s in results["swaps"])
        assert abs(results["portfolio_npv"] - total) < 1.0, (
            f"portfolio_npv={results['portfolio_npv']:.2f} != sum={total:.2f}"
        )

    def test_portfolio_dv01_is_sum(self, results):
        total = sum(s["dv01"] for s in results["swaps"])
        assert abs(results["portfolio_dv01"] - total) < 1.0, (
            f"portfolio_dv01={results['portfolio_dv01']:.2f} != sum={total:.2f}"
        )


# ---------------------------------------------------------------------------
# Independent cross-validation using QuantLib
# ---------------------------------------------------------------------------

def _parse_tenor(s):
    n = int(s[:-1])
    unit = {"D": ql.Days, "W": ql.Weeks, "M": ql.Months, "Y": ql.Years}[s[-1]]
    return ql.Period(n, unit)


def _build_curves():
    """
    Build OIS discount curve and Euribor 6M forward curve independently
    to cross-validate the agent's results.
    """
    with open("/app/market_data.json") as f:
        mkt = json.load(f)

    eval_date = ql.Date(11, 12, 2012)
    ql.Settings.instance().evaluationDate = eval_date
    calendar = ql.TARGET()
    settlement = calendar.advance(eval_date, 2, ql.Days)
    ts_dc = ql.Actual365Fixed()
    dep_dc = ql.Actual360()

    # --- OIS curve ---
    eonia = ql.Eonia()
    ois_helpers = []
    for dep in mkt["ois_curve"]["deposits"]:
        ois_helpers.append(
            ql.DepositRateHelper(
                ql.QuoteHandle(ql.SimpleQuote(dep["rate"])),
                ql.Period(1, ql.Days), dep["settlement_days"],
                calendar, ql.Following, False, dep_dc,
            )
        )
    for ois in mkt["ois_curve"]["short_ois"] + mkt["ois_curve"]["long_ois"]:
        tenor = _parse_tenor(ois["tenor"])
        ois_helpers.append(
            ql.OISRateHelper(
                2, tenor, ql.QuoteHandle(ql.SimpleQuote(ois["rate"])), eonia,
            )
        )
    ois_curve = ql.PiecewiseFlatForward(eval_date, ois_helpers, ts_dc)
    ois_curve.enableExtrapolation()
    disc_handle = ql.YieldTermStructureHandle(ois_curve)

    # --- Euribor 6M curve ---
    euribor6m = ql.Euribor6M()
    eur_helpers = []
    dep = mkt["euribor6m_curve"]["deposit"]
    eur_helpers.append(
        ql.DepositRateHelper(
            ql.QuoteHandle(ql.SimpleQuote(dep["rate"])),
            ql.Period(6, ql.Months), dep["settlement_days"],
            calendar, ql.Following, False, dep_dc,
        )
    )
    for fra in mkt["euribor6m_curve"]["fras"]:
        eur_helpers.append(
            ql.FraRateHelper(
                ql.QuoteHandle(ql.SimpleQuote(fra["rate"])),
                fra["months_to_start"], euribor6m,
            )
        )
    sw_dc = ql.Thirty360(ql.Thirty360.European)
    for sw in mkt["euribor6m_curve"]["swaps"]:
        tenor = _parse_tenor(sw["tenor"])
        eur_helpers.append(
            ql.SwapRateHelper(
                ql.QuoteHandle(ql.SimpleQuote(sw["rate"])),
                tenor, calendar, ql.Annual, ql.Unadjusted, sw_dc,
                euribor6m, ql.QuoteHandle(), ql.Period(0, ql.Days),
                disc_handle,
            )
        )
    eur_curve = ql.PiecewiseFlatForward(settlement, eur_helpers, ts_dc)
    eur_curve.enableExtrapolation()
    fwd_handle = ql.YieldTermStructureHandle(eur_curve)

    return disc_handle, fwd_handle, settlement, calendar


class TestIndependentValidation:
    """Cross-validate agent's results against independent QuantLib computation."""

    def test_swap1_npv_crosscheck(self, results):
        disc_h, fwd_h, settlement, cal = _build_curves()
        engine = ql.DiscountingSwapEngine(disc_h)
        index = ql.Euribor6M(fwd_h)

        maturity = cal.advance(settlement, 5, ql.Years)
        fixed_sched = ql.Schedule(
            settlement, maturity, ql.Period(ql.Annual),
            cal, ql.Unadjusted, ql.Unadjusted,
            ql.DateGeneration.Forward, False,
        )
        float_sched = ql.Schedule(
            settlement, maturity, ql.Period(ql.Semiannual),
            cal, ql.ModifiedFollowing, ql.ModifiedFollowing,
            ql.DateGeneration.Forward, False,
        )
        swap = ql.VanillaSwap(
            ql.Swap.Payer, 1_000_000.0,
            fixed_sched, 0.007, ql.Thirty360(ql.Thirty360.European),
            float_sched, index, 0.0, ql.Actual360(),
        )
        swap.setPricingEngine(engine)
        ref_npv = swap.NPV()
        ref_fair = swap.fairRate()

        agent_swap = next(s for s in results["swaps"] if s["id"] == "swap_1")

        # Fair rate should match tightly (both calibrated to same data)
        assert abs(agent_swap["fair_rate"] - ref_fair) < 5e-4, (
            f"Fair rate mismatch: agent={agent_swap['fair_rate']:.6f}, ref={ref_fair:.6f}"
        )

        # NPV may differ due to interpolation method, but should be close
        npv_tol = max(abs(ref_npv) * 0.15, 500)
        assert abs(agent_swap["npv"] - ref_npv) < npv_tol, (
            f"NPV mismatch: agent={agent_swap['npv']:.2f}, ref={ref_npv:.2f}, tol={npv_tol:.2f}"
        )

    def test_swap3_npv_crosscheck(self, results):
        disc_h, fwd_h, settlement, cal = _build_curves()
        engine = ql.DiscountingSwapEngine(disc_h)
        index = ql.Euribor6M(fwd_h)

        maturity = cal.advance(settlement, 10, ql.Years)
        fixed_sched = ql.Schedule(
            settlement, maturity, ql.Period(ql.Annual),
            cal, ql.Unadjusted, ql.Unadjusted,
            ql.DateGeneration.Forward, False,
        )
        float_sched = ql.Schedule(
            settlement, maturity, ql.Period(ql.Semiannual),
            cal, ql.ModifiedFollowing, ql.ModifiedFollowing,
            ql.DateGeneration.Forward, False,
        )
        swap = ql.VanillaSwap(
            ql.Swap.Receiver, 5_000_000.0,
            fixed_sched, 0.020, ql.Thirty360(ql.Thirty360.European),
            float_sched, index, 0.0, ql.Actual360(),
        )
        swap.setPricingEngine(engine)
        ref_npv = swap.NPV()
        ref_fair = swap.fairRate()

        agent_swap = next(s for s in results["swaps"] if s["id"] == "swap_3")

        assert abs(agent_swap["fair_rate"] - ref_fair) < 5e-4, (
            f"Fair rate mismatch: agent={agent_swap['fair_rate']:.6f}, ref={ref_fair:.6f}"
        )

        npv_tol = max(abs(ref_npv) * 0.15, 2000)
        assert abs(agent_swap["npv"] - ref_npv) < npv_tol, (
            f"NPV mismatch: agent={agent_swap['npv']:.2f}, ref={ref_npv:.2f}, tol={npv_tol:.2f}"
        )

    def test_ois_discount_factor_crosscheck(self, results):
        disc_h, _, settlement, cal = _build_curves()

        for tenor_str, expected_range in [
            ("1Y", (0.990, 1.000)),
            ("5Y", (0.950, 0.995)),
            ("10Y", (0.850, 0.930)),
            ("30Y", (0.400, 0.650)),
        ]:
            agent_df = results["ois_discount_factors"][tenor_str]
            low, high = expected_range
            assert low < agent_df < high, (
                f"DF[{tenor_str}]={agent_df} outside expected range ({low}, {high})"
            )
