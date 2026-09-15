"""
Verification tests for UK Index-Linked Gilt Pricing and Risk Analytics Engine.

Tests verify correctness of:
  - 3-month lag Reference RPI interpolation
  - 8-month lag Reference RPI (flat monthly)
  - UK_GB BondCalcMode compounding convention
  - Multi-coupon general-case pricing formula
  - Ex-dividend accrued interest
  - Newton-Raphson yield solver round-trip
  - Modified duration, convexity, BPV
  - Breakeven inflation
"""


import json
import math
import os
import pytest
from datetime import date


# ===================== Reference pricing helpers =====================

def ref_dirty_price(y, coupon_rate, n, xi, freq=2, ex_div=False):
    """Compute correct dirty price using UK_GB BondCalcMode conventions."""
    coupon = coupon_rate / freq
    c1 = 0.0 if ex_div else coupon
    v2 = 1.0 / (1.0 + y / freq)
    v1 = v2 ** (1.0 - xi)
    v3 = v2

    if n == 1:
        return v1 * (c1 + 100.0)
    elif n == 2:
        return v1 * (c1 + v3 * (coupon + 100.0))
    else:
        s = c1
        for i in range(2, n):
            s += coupon * v2 ** (i - 1)
        s += (coupon + 100.0) * v2 ** (n - 2) * v3
        return v1 * s


def ref_clean_price(y, coupon_rate, n, xi, freq=2, ex_div=False):
    """Compute correct clean price."""
    dirty = ref_dirty_price(y, coupon_rate, n, xi, freq, ex_div)
    coupon = coupon_rate / freq
    ai_y = (xi - 1.0) * coupon if ex_div else xi * coupon
    return dirty - ai_y


def ref_mod_duration(y, coupon_rate, n, xi, freq=2, ex_div=False):
    """Modified duration via central finite difference on dirty price."""
    dy = 0.0001
    p = ref_dirty_price(y, coupon_rate, n, xi, freq, ex_div)
    p_up = ref_dirty_price(y + dy, coupon_rate, n, xi, freq, ex_div)
    p_dn = ref_dirty_price(y - dy, coupon_rate, n, xi, freq, ex_div)
    return -(p_up - p_dn) / (2.0 * dy * p)


def ref_convexity(y, coupon_rate, n, xi, freq=2, ex_div=False):
    """Convexity via central finite difference on dirty price."""
    dy = 0.0001
    p = ref_dirty_price(y, coupon_rate, n, xi, freq, ex_div)
    p_up = ref_dirty_price(y + dy, coupon_rate, n, xi, freq, ex_div)
    p_dn = ref_dirty_price(y - dy, coupon_rate, n, xi, freq, ex_div)
    return (p_up - 2.0 * p + p_dn) / (dy * dy * p)


def ref_bpv(mod_dur, dirty_price):
    return mod_dur * dirty_price / 10000.0


def days_between_py(d1, d2):
    """Calendar days between two dates."""
    return (d2 - d1).days


@pytest.fixture(scope="session")
def output():
    """Load the engine output."""
    path = "/app/output.json"
    assert os.path.exists(path), f"Output file {path} does not exist"
    with open(path) as f:
        return json.load(f)


def get_result(output, gilt_id):
    for r in output["results"]:
        if r["id"] == gilt_id:
            return r
    raise ValueError(f"Gilt {gilt_id} not found in output")


# ===================== Test 3-month lag RPI interpolation =====================

class TestBaseRPI:
    """Verify Reference RPI interpolation formula: Ref = RPI(m-3) + (d-1)/D * delta."""

    def test_base_rpi_3m_01(self, output):
        """ILG_3M_01 effective 2024-05-27, lag=3.
        Ref months: Feb 2024 (381.0) and Mar 2024 (383.0).
        D=31 (May), d=27. Expected = 381.0 + (26/31)*2.0"""
        r = get_result(output, "ILG_3M_01")
        expected = 381.0 + (26.0 / 31.0) * (383.0 - 381.0)
        assert abs(r["base_rpi"] - expected) < 0.001, \
            f"base_rpi={r['base_rpi']}, expected={expected}"

    def test_coupon_index_ratio_nov(self, output):
        """First coupon 2024-11-27: Ref = RPI(Aug) + (26/30)*(RPI(Sep)-RPI(Aug))."""
        r = get_result(output, "ILG_3M_01")
        base_rpi = 381.0 + (26.0 / 31.0) * 2.0
        ref_nov = 389.9 + (26.0 / 30.0) * (388.6 - 389.9)
        expected_ir = ref_nov / base_rpi

        coupons = [c for c in r["cashflows"]
                   if c["date"] == "2024-11-27" and c["type"] == "coupon"]
        assert len(coupons) == 1
        assert abs(coupons[0]["index_ratio"] - expected_ir) < 0.0005

    def test_coupon_index_ratio_may(self, output):
        """Second coupon 2025-05-27: Ref = 394.0 + (26/31)*1.3."""
        r = get_result(output, "ILG_3M_01")
        base_rpi = 381.0 + (26.0 / 31.0) * 2.0
        ref_may = 394.0 + (26.0 / 31.0) * (395.3 - 394.0)
        expected_ir = ref_may / base_rpi

        coupons = [c for c in r["cashflows"]
                   if c["date"] == "2025-05-27" and c["type"] == "coupon"]
        assert len(coupons) == 1
        assert abs(coupons[0]["index_ratio"] - expected_ir) < 0.0005

    def test_base_rpi_3m_02(self, output):
        """ILG_3M_02 effective 2024-09-16, lag=3.
        Ref months: Jun (387.3) and Jul (387.5). D=30, d=16."""
        r = get_result(output, "ILG_3M_02")
        expected = 387.3 + (15.0 / 30.0) * (387.5 - 387.3)
        assert abs(r["base_rpi"] - expected) < 0.001

    def test_negative_rpi_change_coupon(self, output):
        """ILG_3M_02 first coupon 2025-03-16: Dec 2024 (392.1), Jan 2025 (391.7).
        RPI decreased month-over-month."""
        r = get_result(output, "ILG_3M_02")
        base = 387.3 + (15.0 / 30.0) * 0.2
        ref = 392.1 + (15.0 / 31.0) * (391.7 - 392.1)
        expected_ir = ref / base

        coupons = [c for c in r["cashflows"]
                   if c["date"] == "2025-03-16" and c["type"] == "coupon"]
        assert len(coupons) == 1
        assert abs(coupons[0]["index_ratio"] - expected_ir) < 0.001


# ===================== Test 8-month lag convention =====================

class TestEightMonthLag:
    """Verify 8-month lag uses flat monthly RPI (no daily interpolation)."""

    def test_base_rpi_8m(self, output):
        """Effective 2023-03-22, lag=8. Base = RPI(Jul 2022) = 343.2 exactly."""
        r = get_result(output, "ILG_8M_01")
        assert abs(r["base_rpi"] - 343.2) < 0.01, \
            f"base_rpi={r['base_rpi']}, expected=343.2"

    def test_settlement_ref_rpi_8m(self, output):
        """Settlement 2024-09-10, lag=8. Ref = RPI(Jan 2024) = 378.0 exactly."""
        r = get_result(output, "ILG_8M_01")
        assert abs(r["settlement_ref_rpi"] - 378.0) < 0.01

    def test_index_ratio_8m(self, output):
        """Settlement IR = 378.0 / 343.2."""
        r = get_result(output, "ILG_8M_01")
        expected_ir = 378.0 / 343.2
        assert abs(r["settlement_index_ratio"] - expected_ir) < 0.001

    def test_8m_coupon_uses_flat_rpi(self, output):
        """Coupon date Sep 22, 2024: 8-month lag -> RPI(Jan 2024) = 378.0."""
        r = get_result(output, "ILG_8M_01")
        expected_ir = 378.0 / 343.2
        coupons = [c for c in r["cashflows"]
                   if c["date"] == "2024-09-22" and c["type"] == "coupon"]
        assert len(coupons) == 1
        assert abs(coupons[0]["index_ratio"] - expected_ir) < 0.001


# ===================== Test UK_GB v1 compounding (n=2) =====================

class TestCleanPrice:
    """Verify v1 uses compounding: v1 = v2^(1-xi), for 2-coupon gilts."""

    def test_real_clean_price(self, output):
        """ILG_3M_01: n=2, yield=3.5%, xi=141/184."""
        r = get_result(output, "ILG_3M_01")
        expected = ref_clean_price(0.035, 2.0, 2, 141.0 / 184.0)
        assert abs(r["real_clean_price"] - expected) < 0.01, \
            f"real_clean_price={r['real_clean_price']}, expected={expected}"

    def test_real_dirty_price(self, output):
        """Dirty price must match v1*(c1 + v2*(c2+100))."""
        r = get_result(output, "ILG_3M_01")
        expected = ref_dirty_price(0.035, 2.0, 2, 141.0 / 184.0)
        assert abs(r["real_dirty_price"] - expected) < 0.01


# ===================== Test multi-coupon general case (n>2) =====================

class TestMultiCouponPricing:
    """Verify general-case pricing formula for gilts with more than 2 remaining coupons."""

    def test_multi_coupon_n_remaining(self, output):
        """ILG_MULTI: effective 2024-01-15, maturity 2026-07-15,
        settlement 2025-01-10 -> 4 remaining coupons."""
        r = get_result(output, "ILG_MULTI")
        assert r["n_remaining_coupons"] == 4

    def test_multi_coupon_base_rpi(self, output):
        """ILG_MULTI effective 2024-01-15, lag=3.
        Ref months: Oct 2023 (377.8), Nov 2023 (377.3). D=31, d=15."""
        r = get_result(output, "ILG_MULTI")
        expected = 377.8 + (14.0 / 31.0) * (377.3 - 377.8)
        assert abs(r["base_rpi"] - expected) < 0.001

    def test_multi_coupon_clean_price(self, output):
        """ILG_MULTI: n=4, yield=2.5%, coupon=1.25%, xi=179/184.
        Tests the general-case loop with v2^(i-1) exponents."""
        r = get_result(output, "ILG_MULTI")
        xi = 179.0 / 184.0
        expected = ref_clean_price(0.025, 1.25, 4, xi)
        assert abs(r["real_clean_price"] - expected) < 0.005, \
            f"real_clean_price={r['real_clean_price']}, expected={expected}"

    def test_8m_real_clean_price(self, output):
        """ILG_8M_01: n=4, yield=1.0%, coupon=1.875%, xi=172/184.
        Another multi-coupon test with 8-month lag gilt."""
        r = get_result(output, "ILG_8M_01")
        xi = 172.0 / 184.0
        expected = ref_clean_price(0.01, 1.875, 4, xi)
        assert abs(r["real_clean_price"] - expected) < 0.005, \
            f"real_clean_price={r['real_clean_price']}, expected={expected}"


# ===================== Test ex-dividend handling =====================

class TestExDividend:
    """Verify ex-dividend accrued interest and pricing."""

    def test_is_ex_dividend(self, output):
        """Settlement 2024-11-22 is within 7 bdays of Nov 27 coupon."""
        r = get_result(output, "ILG_EXDIV")
        assert r["ex_dividend"] is True

    def test_accrued_interest_negative(self, output):
        """Ex-div accrued interest must be negative."""
        r = get_result(output, "ILG_EXDIV")
        assert r["accrued_interest"] < 0

    def test_accrued_interest_value(self, output):
        """AI = (xi-1)*coupon where xi=179/184, coupon=1.0."""
        r = get_result(output, "ILG_EXDIV")
        xi = 179.0 / 184.0
        expected_ai = (xi - 1.0) * 1.0
        assert abs(r["accrued_interest"] - expected_ai) < 0.001

    def test_ex_div_clean_price(self, output):
        """Ex-div clean price: c1=0 in yield formula, AI_y = (xi-1)*coupon."""
        r = get_result(output, "ILG_EXDIV")
        xi = 179.0 / 184.0
        expected = ref_clean_price(0.035, 2.0, 2, xi, ex_div=True)
        assert abs(r["real_clean_price"] - expected) < 0.01


# ===================== Test yield solver round-trip =====================

class TestYieldRoundtrip:
    """Verify Newton-Raphson yield solver converges correctly."""

    def test_yield_reasonable(self, output):
        """Recovered yield should be in a reasonable range."""
        r = get_result(output, "ILG_YFP")
        y = r["real_yield"]
        assert 0.0 < y < 0.10

    def test_yield_roundtrip_price(self, output):
        """clean_price(recovered_yield) should reproduce target 99.50."""
        r = get_result(output, "ILG_YFP")
        y = r["real_yield"]
        xi = 141.0 / 184.0
        computed_clean = ref_clean_price(y, 2.0, 2, xi)
        assert abs(computed_clean - 99.50) < 0.001

    def test_reported_clean_price(self, output):
        """The reported real_clean_price should match the target."""
        r = get_result(output, "ILG_YFP")
        assert abs(r["real_clean_price"] - 99.50) < 0.01


# ===================== Test risk analytics =====================

class TestRiskAnalytics:
    """Verify modified duration, convexity, BPV, and breakeven inflation."""

    def test_mod_duration_positive_3m(self, output):
        """Modified duration must be positive for ILG_3M_01."""
        r = get_result(output, "ILG_3M_01")
        assert r["modified_duration"] > 0

    def test_mod_duration_value_3m(self, output):
        """Modified duration for ILG_3M_01 (n=2, y=3.5%, xi=141/184)."""
        r = get_result(output, "ILG_3M_01")
        expected = ref_mod_duration(0.035, 2.0, 2, 141.0 / 184.0)
        assert abs(r["modified_duration"] - expected) < 0.02, \
            f"mod_dur={r['modified_duration']}, expected={expected}"

    def test_mod_duration_multi(self, output):
        """Modified duration for ILG_MULTI (n=4) should be larger than ILG_3M_01 (n=2)."""
        r_short = get_result(output, "ILG_3M_01")
        r_long = get_result(output, "ILG_MULTI")
        assert r_long["modified_duration"] > r_short["modified_duration"], \
            "Longer gilt should have higher duration"

    def test_mod_duration_value_multi(self, output):
        """Modified duration for ILG_MULTI (n=4, y=2.5%, xi=179/184)."""
        r = get_result(output, "ILG_MULTI")
        expected = ref_mod_duration(0.025, 1.25, 4, 179.0 / 184.0)
        assert abs(r["modified_duration"] - expected) < 0.02

    def test_convexity_positive(self, output):
        """Convexity must be positive for standard bonds."""
        r = get_result(output, "ILG_MULTI")
        assert r["convexity"] > 0

    def test_convexity_value(self, output):
        """Convexity for ILG_MULTI."""
        r = get_result(output, "ILG_MULTI")
        expected = ref_convexity(0.025, 1.25, 4, 179.0 / 184.0)
        assert abs(r["convexity"] - expected) < 0.5, \
            f"convexity={r['convexity']}, expected={expected}"

    def test_bpv_value(self, output):
        """BPV = mod_dur * dirty_price / 10000 for ILG_3M_01."""
        r = get_result(output, "ILG_3M_01")
        dirty = ref_dirty_price(0.035, 2.0, 2, 141.0 / 184.0)
        mod_dur = ref_mod_duration(0.035, 2.0, 2, 141.0 / 184.0)
        expected_bpv = mod_dur * dirty / 10000.0
        assert abs(r["bpv"] - expected_bpv) < 0.0005, \
            f"bpv={r['bpv']}, expected={expected_bpv}"

    def test_breakeven_inflation_positive(self, output):
        """Breakeven inflation must be positive (RPI has risen)."""
        r = get_result(output, "ILG_3M_01")
        assert r["breakeven_inflation"] > 0

    def test_breakeven_inflation_value(self, output):
        """Breakeven for ILG_MULTI: pow(IR, 1/T)-1 where T=elapsed years."""
        r = get_result(output, "ILG_MULTI")
        eff = date(2024, 1, 15)
        stl = date(2025, 1, 10)
        elapsed_days = (stl - eff).days
        elapsed_years = elapsed_days / 365.25
        ir = r["settlement_index_ratio"]
        expected_bei = ir ** (1.0 / elapsed_years) - 1.0
        assert abs(r["breakeven_inflation"] - expected_bei) < 0.002, \
            f"bei={r['breakeven_inflation']}, expected={expected_bei}"

    def test_analytics_nonzero_all_gilts(self, output):
        """All price_from_yield gilts must have non-zero analytics."""
        for gilt_id in ["ILG_3M_01", "ILG_3M_02", "ILG_8M_01", "ILG_EXDIV", "ILG_MULTI"]:
            r = get_result(output, gilt_id)
            assert r["modified_duration"] != 0.0, f"{gilt_id}: mod_dur is zero"
            assert r["convexity"] != 0.0, f"{gilt_id}: convexity is zero"
            assert r["bpv"] != 0.0, f"{gilt_id}: bpv is zero"
            assert r["breakeven_inflation"] != 0.0, f"{gilt_id}: bei is zero"
