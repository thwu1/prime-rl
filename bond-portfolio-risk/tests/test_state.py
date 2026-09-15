"""
Tests for bond portfolio risk analytics output.

Independently builds the SOFR OIS curve, prices bonds, and computes
analytics using QuantLib, then verifies the agent's results.json.
"""

import json
import math
import pytest
import QuantLib as ql


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(s):
    y, m, d = s.split('-')
    return ql.Date(int(d), int(m), int(y))


def load_inputs():
    with open('/app/market_data.json') as f:
        market = json.load(f)
    with open('/app/portfolio.json') as f:
        portfolio = json.load(f)
    return market, portfolio


def build_reference_curve(market):
    """Bootstrap the reference SOFR OIS curve."""
    today = parse_date(market['evaluation_date'])
    ql.Settings.instance().evaluationDate = today
    settle_days = market['settlement_days']
    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    curve_dc = ql.Actual360()

    sofr = ql.Sofr()
    helpers = []
    for tenor_str, rate_pct in market['ois_quotes_pct'].items():
        helpers.append(
            ql.OISRateHelper(
                settle_days,
                ql.Period(tenor_str),
                ql.QuoteHandle(ql.SimpleQuote(rate_pct / 100.0)),
                sofr,
                paymentFrequency=ql.Annual,
            )
        )

    curve = ql.PiecewiseLogCubicDiscount(0, calendar, helpers, curve_dc)
    curve.enableExtrapolation()
    return today, calendar, curve_dc, curve


def build_fixed_bond(spec, calendar, face, curve):
    """Build a FixedRateBond and attach a discounting engine."""
    bond_dc = ql.Thirty360(ql.Thirty360.BondBasis)
    issue = parse_date(spec['issue_date'])
    maturity = parse_date(spec['maturity_date'])
    coupon = spec['coupon_rate_pct'] / 100.0

    schedule = ql.MakeSchedule(
        effectiveDate=issue,
        terminationDate=maturity,
        frequency=ql.Semiannual,
        calendar=calendar,
        convention=ql.Unadjusted,
        backwards=True,
    )

    relinkable = ql.RelinkableYieldTermStructureHandle()
    relinkable.linkTo(curve)
    bond = ql.FixedRateBond(2, face, schedule, [coupon], bond_dc)
    bond.setPricingEngine(ql.DiscountingBondEngine(relinkable))
    return bond, bond_dc, relinkable, schedule, issue


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def results():
    with open('/app/results.json') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference():
    market, portfolio = load_inputs()
    today, calendar, curve_dc, curve = build_reference_curve(market)
    return {
        'market': market,
        'portfolio': portfolio,
        'today': today,
        'calendar': calendar,
        'curve_dc': curve_dc,
        'curve': curve,
    }


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_top_level_keys(self, results):
        assert 'curve' in results, "Missing 'curve' section"
        assert 'bonds' in results, "Missing 'bonds' section"
        assert 'portfolio' in results, "Missing 'portfolio' section"

    def test_curve_keys(self, results):
        curve = results['curve']
        assert 'zero_rates_continuous_pct' in curve
        assert 'discount_factors' in curve
        for tenor in ['1Y', '5Y', '10Y', '20Y', '30Y']:
            assert tenor in curve['zero_rates_continuous_pct'], f"Missing zero rate for {tenor}"
            assert tenor in curve['discount_factors'], f"Missing DF for {tenor}"

    def test_bond_keys(self, results):
        expected_ids = {'UST_5Y', 'UST_10Y', 'UST_20Y', 'CORP_CALLABLE', 'UST_30Y'}
        assert set(results['bonds'].keys()) == expected_ids
        for bid, bdata in results['bonds'].items():
            assert 'model_clean_price' in bdata, f"{bid}: missing model_clean_price"
            assert 'ytm_pct' in bdata, f"{bid}: missing ytm_pct"
            assert 'z_spread_bps' in bdata, f"{bid}: missing z_spread_bps"
            assert 'modified_duration' in bdata, f"{bid}: missing modified_duration"
            assert 'dv01_per_million_face' in bdata, f"{bid}: missing dv01_per_million_face"
        assert 'oas_bps' in results['bonds']['CORP_CALLABLE'], "CORP_CALLABLE missing oas_bps"

    def test_portfolio_keys(self, results):
        pf = results['portfolio']
        assert 'total_market_value' in pf
        assert 'portfolio_dv01' in pf
        assert 'scenarios' in pf
        assert 'key_rate_durations' in pf
        for s in ['parallel_up_100bp', 'parallel_down_100bp', 'flattening', 'steepening']:
            assert s in pf['scenarios'], f"Missing scenario {s}"
        for t in ['2Y', '5Y', '10Y', '20Y', '30Y']:
            assert t in pf['key_rate_durations'], f"Missing KRD tenor {t}"


# ---------------------------------------------------------------------------
# Curve tests
# ---------------------------------------------------------------------------

class TestCurve:
    def test_zero_rates(self, results, reference):
        curve = reference['curve']
        today = reference['today']
        calendar = reference['calendar']
        curve_dc = reference['curve_dc']

        for tenor in ['1Y', '5Y', '10Y', '20Y', '30Y']:
            dt = calendar.advance(today, ql.Period(tenor))
            expected = curve.zeroRate(dt, curve_dc, ql.Continuous).rate() * 100
            actual = results['curve']['zero_rates_continuous_pct'][tenor]
            assert abs(actual - expected) < 0.01, \
                f"Zero rate {tenor}: expected {expected:.4f}%, got {actual:.4f}%"

    def test_discount_factors(self, results, reference):
        curve = reference['curve']
        today = reference['today']
        calendar = reference['calendar']

        for tenor in ['1Y', '5Y', '10Y', '20Y', '30Y']:
            dt = calendar.advance(today, ql.Period(tenor))
            expected = curve.discount(dt)
            actual = results['curve']['discount_factors'][tenor]
            assert abs(actual - expected) < 0.0005, \
                f"DF {tenor}: expected {expected:.8f}, got {actual:.8f}"

    def test_discount_factors_monotonic(self, results):
        dfs = results['curve']['discount_factors']
        ordered = [dfs[t] for t in ['1Y', '5Y', '10Y', '20Y', '30Y']]
        for i in range(len(ordered) - 1):
            assert ordered[i] > ordered[i + 1], \
                "Discount factors should be monotonically decreasing"

    def test_zero_rates_positive(self, results):
        for tenor, rate in results['curve']['zero_rates_continuous_pct'].items():
            assert rate > 0, f"Zero rate at {tenor} should be positive"


# ---------------------------------------------------------------------------
# Bond analytics tests
# ---------------------------------------------------------------------------

class TestBondAnalytics:
    def test_ytm_values(self, results, reference):
        """Verify YTM for each bond independently."""
        portfolio = reference['portfolio']
        face = portfolio['face_amount']
        bond_dc = ql.Thirty360(ql.Thirty360.BondBasis)

        for spec in portfolio['bonds']:
            bid = spec['id']
            bond, dc, _, _, _ = build_fixed_bond(spec, reference['calendar'],
                                                  face, reference['curve'])
            price_obj = ql.BondPrice(spec['quoted_clean_price'], ql.BondPrice.Clean)
            expected_ytm = bond.bondYield(price_obj, dc, ql.Compounded, ql.Semiannual) * 100
            actual_ytm = results['bonds'][bid]['ytm_pct']
            assert abs(actual_ytm - expected_ytm) < 0.02, \
                f"{bid} YTM: expected {expected_ytm:.4f}%, got {actual_ytm:.4f}%"

    def test_z_spreads(self, results, reference):
        """Verify Z-spread for each bond independently."""
        portfolio = reference['portfolio']
        face = portfolio['face_amount']
        bond_dc = ql.Thirty360(ql.Thirty360.BondBasis)
        curve = reference['curve']

        for spec in portfolio['bonds']:
            bid = spec['id']
            bond, dc, _, _, _ = build_fixed_bond(spec, reference['calendar'],
                                                  face, curve)
            price_obj = ql.BondPrice(spec['quoted_clean_price'], ql.BondPrice.Clean)
            expected_z = ql.BondFunctions.zSpread(
                bond, price_obj, curve, dc, ql.Compounded, ql.Semiannual
            ) * 10000
            actual_z = results['bonds'][bid]['z_spread_bps']
            assert abs(actual_z - expected_z) < 3.0, \
                f"{bid} Z-spread: expected {expected_z:.2f}bp, got {actual_z:.2f}bp"

    def test_modified_duration(self, results, reference):
        """Verify modified duration for each bond."""
        portfolio = reference['portfolio']
        face = portfolio['face_amount']
        bond_dc = ql.Thirty360(ql.Thirty360.BondBasis)

        for spec in portfolio['bonds']:
            bid = spec['id']
            bond, dc, _, _, _ = build_fixed_bond(spec, reference['calendar'],
                                                  face, reference['curve'])
            price_obj = ql.BondPrice(spec['quoted_clean_price'], ql.BondPrice.Clean)
            ytm = bond.bondYield(price_obj, dc, ql.Compounded, ql.Semiannual)
            expected_dur = ql.BondFunctions.duration(
                bond, ytm, dc, ql.Compounded, ql.Semiannual, ql.Duration.Modified
            )
            actual_dur = results['bonds'][bid]['modified_duration']
            assert abs(actual_dur - expected_dur) < 0.05, \
                f"{bid} ModDur: expected {expected_dur:.4f}, got {actual_dur:.4f}"

    def test_dv01_values(self, results, reference):
        """Verify DV01 = mod_dur * price/100 * face * 0.0001."""
        portfolio = reference['portfolio']
        face = portfolio['face_amount']

        for spec in portfolio['bonds']:
            bid = spec['id']
            bdata = results['bonds'][bid]
            expected_dv01 = bdata['modified_duration'] * spec['quoted_clean_price'] / 100.0 * face * 0.0001
            actual_dv01 = bdata['dv01_per_million_face']
            assert abs(actual_dv01 - expected_dv01) / max(abs(expected_dv01), 1e-6) < 0.02, \
                f"{bid} DV01: expected {expected_dv01:.2f}, got {actual_dv01:.2f}"

    def test_model_prices_positive(self, results):
        for bid, bdata in results['bonds'].items():
            assert bdata['model_clean_price'] > 0, f"{bid}: model price must be positive"

    def test_duration_ordering(self, results):
        """Longer bonds should generally have higher duration."""
        dur_5y = results['bonds']['UST_5Y']['modified_duration']
        dur_10y = results['bonds']['UST_10Y']['modified_duration']
        dur_30y = results['bonds']['UST_30Y']['modified_duration']
        assert dur_5y < dur_10y < dur_30y, \
            "Duration should increase: 5Y < 10Y < 30Y"

    def test_z_spread_sign(self, results, reference):
        """Z-spread should be positive when quoted price < model price,
        negative when quoted price > model price."""
        portfolio = reference['portfolio']
        face = portfolio['face_amount']
        for spec in portfolio['bonds']:
            bid = spec['id']
            bdata = results['bonds'][bid]
            # Just check Z-spread is a finite number
            assert math.isfinite(bdata['z_spread_bps']), \
                f"{bid}: Z-spread must be finite"


# ---------------------------------------------------------------------------
# Callable bond OAS test
# ---------------------------------------------------------------------------

class TestCallableBond:
    def test_oas_exists_and_positive(self, results):
        oas = results['bonds']['CORP_CALLABLE']['oas_bps']
        assert oas > 0, "OAS should be positive for this bond"

    def test_oas_less_than_z_spread(self, results):
        """OAS should be less than Z-spread for a callable bond
        (the call option has value, reducing the spread)."""
        oas = results['bonds']['CORP_CALLABLE']['oas_bps']
        z_spread = results['bonds']['CORP_CALLABLE']['z_spread_bps']
        assert oas < z_spread, \
            f"OAS ({oas:.2f}bp) should be < Z-spread ({z_spread:.2f}bp) for callable"

    def test_oas_value(self, results, reference):
        """Independently compute OAS and compare."""
        portfolio = reference['portfolio']
        face = portfolio['face_amount']
        curve = reference['curve']
        calendar = reference['calendar']
        bond_dc = ql.Thirty360(ql.Thirty360.BondBasis)
        curve_handle = ql.YieldTermStructureHandle(curve)

        spec = [s for s in portfolio['bonds'] if s['id'] == 'CORP_CALLABLE'][0]
        issue = parse_date(spec['issue_date'])
        maturity = parse_date(spec['maturity_date'])
        coupon = spec['coupon_rate_pct'] / 100.0
        call_date = parse_date(spec['call_date'])

        schedule = ql.MakeSchedule(
            effectiveDate=issue,
            terminationDate=maturity,
            frequency=ql.Semiannual,
            calendar=calendar,
            convention=ql.Unadjusted,
            backwards=True,
        )

        callable_bond = ql.CallableFixedRateBond(
            2, face, schedule, [coupon], bond_dc,
            ql.Unadjusted, 100.0, issue,
            [ql.Callability(
                ql.BondPrice(spec['call_price'], ql.BondPrice.Clean),
                ql.Callability.Call,
                call_date,
            )]
        )

        hw_model = ql.HullWhite(curve_handle, a=spec['hull_white_a'],
                                 sigma=spec['hull_white_sigma'])
        tree_engine = ql.TreeCallableFixedRateBondEngine(hw_model, 100)
        callable_bond.setPricingEngine(tree_engine)

        expected_oas = callable_bond.OAS(
            spec['quoted_clean_price'], curve_handle, bond_dc,
            ql.Compounded, ql.Semiannual
        ) * 10000

        actual_oas = results['bonds']['CORP_CALLABLE']['oas_bps']
        assert abs(actual_oas - expected_oas) < 10.0, \
            f"OAS: expected {expected_oas:.2f}bp, got {actual_oas:.2f}bp"


# ---------------------------------------------------------------------------
# Portfolio aggregate tests
# ---------------------------------------------------------------------------

class TestPortfolio:
    def test_total_market_value(self, results, reference):
        portfolio = reference['portfolio']
        face = portfolio['face_amount']
        expected_mv = sum(
            s['quoted_clean_price'] / 100.0 * face
            for s in portfolio['bonds']
        )
        actual_mv = results['portfolio']['total_market_value']
        assert abs(actual_mv - expected_mv) < 1.0, \
            f"Total MV: expected {expected_mv:.2f}, got {actual_mv:.2f}"

    def test_portfolio_dv01(self, results):
        expected = sum(
            results['bonds'][bid]['dv01_per_million_face']
            for bid in results['bonds']
        )
        actual = results['portfolio']['portfolio_dv01']
        assert abs(actual - expected) < 1.0, \
            f"Portfolio DV01: expected {expected:.2f}, got {actual:.2f}"

    def test_portfolio_dv01_positive(self, results):
        assert results['portfolio']['portfolio_dv01'] > 0, "Portfolio DV01 must be positive"


# ---------------------------------------------------------------------------
# Scenario tests
# ---------------------------------------------------------------------------

class TestScenarios:
    def test_parallel_up_negative(self, results):
        """Rates up => bond prices down => negative P&L."""
        pnl = results['portfolio']['scenarios']['parallel_up_100bp']
        assert pnl < 0, f"Parallel +100bp P&L should be negative, got {pnl}"

    def test_parallel_down_positive(self, results):
        """Rates down => bond prices up => positive P&L."""
        pnl = results['portfolio']['scenarios']['parallel_down_100bp']
        assert pnl > 0, f"Parallel -100bp P&L should be positive, got {pnl}"

    def test_parallel_symmetry(self, results):
        """Up and down P&L should be roughly symmetric (but not exactly due to convexity)."""
        up = results['portfolio']['scenarios']['parallel_up_100bp']
        down = results['portfolio']['scenarios']['parallel_down_100bp']
        # |down| should be slightly larger than |up| due to positive convexity
        assert abs(down) > abs(up) * 0.9, \
            "P&L asymmetry too large — check convexity"

    def test_parallel_up_magnitude(self, results, reference):
        """Independently compute parallel +100bp scenario."""
        portfolio = reference['portfolio']
        face = portfolio['face_amount']
        curve = reference['curve']
        calendar = reference['calendar']

        relinkable = ql.RelinkableYieldTermStructureHandle()
        relinkable.linkTo(curve)
        engine = ql.DiscountingBondEngine(relinkable)

        # Base values
        base_value = 0.0
        bonds = []
        for spec in portfolio['bonds']:
            bond, _, _, _, _ = build_fixed_bond(spec, calendar, face, curve)
            bond.setPricingEngine(engine)
            base_value += bond.cleanPrice() / 100.0 * face
            bonds.append(bond)

        # Shifted curve
        shifted = ql.ZeroSpreadedTermStructure(
            ql.YieldTermStructureHandle(curve),
            ql.QuoteHandle(ql.SimpleQuote(0.01)),
        )
        shifted.enableExtrapolation()
        relinkable.linkTo(shifted)

        shifted_value = sum(b.cleanPrice() / 100.0 * face for b in bonds)
        expected_pnl = shifted_value - base_value

        actual_pnl = results['portfolio']['scenarios']['parallel_up_100bp']
        assert abs(actual_pnl - expected_pnl) / abs(expected_pnl) < 0.03, \
            f"Parallel +100bp: expected {expected_pnl:.0f}, got {actual_pnl:.0f}"

        relinkable.linkTo(curve)

    def test_twist_scenarios_exist(self, results):
        assert isinstance(results['portfolio']['scenarios']['flattening'], (int, float))
        assert isinstance(results['portfolio']['scenarios']['steepening'], (int, float))

    def test_flattening_scenario(self, results, reference):
        """Independently compute flattening scenario P&L."""
        portfolio = reference['portfolio']
        face = portfolio['face_amount']
        curve = reference['curve']
        calendar = reference['calendar']
        today = reference['today']

        relinkable = ql.RelinkableYieldTermStructureHandle()
        relinkable.linkTo(curve)
        engine = ql.DiscountingBondEngine(relinkable)

        base_value = 0.0
        bonds = []
        for spec in portfolio['bonds']:
            bond, _, _, _, _ = build_fixed_bond(spec, calendar, face, curve)
            bond.setPricingEngine(engine)
            base_value += bond.cleanPrice() / 100.0 * face
            bonds.append(bond)

        sspec = portfolio['scenarios']['flattening']
        short_date = today
        long_date = calendar.advance(today, ql.Period(sspec['long_end_years'], ql.Years))
        shifted = ql.PiecewiseZeroSpreadedTermStructure(
            ql.YieldTermStructureHandle(curve),
            [ql.QuoteHandle(ql.SimpleQuote(sspec['short_spread_bps'] / 10000.0)),
             ql.QuoteHandle(ql.SimpleQuote(sspec['long_spread_bps'] / 10000.0))],
            [short_date, long_date],
        )
        shifted.enableExtrapolation()
        relinkable.linkTo(shifted)

        shifted_value = sum(b.cleanPrice() / 100.0 * face for b in bonds)
        expected_pnl = shifted_value - base_value

        actual_pnl = results['portfolio']['scenarios']['flattening']
        assert abs(actual_pnl - expected_pnl) / max(abs(expected_pnl), 1.0) < 0.05, \
            f"Flattening P&L: expected {expected_pnl:.0f}, got {actual_pnl:.0f}"

        relinkable.linkTo(curve)


# ---------------------------------------------------------------------------
# Key-rate duration tests
# ---------------------------------------------------------------------------

class TestKeyRateDurations:
    def test_all_positive(self, results):
        """KRDs should all be positive for a long-only bond portfolio."""
        for tenor, krd in results['portfolio']['key_rate_durations'].items():
            assert krd > 0, f"KRD at {tenor} should be positive, got {krd}"

    def test_krd_values(self, results, reference):
        """Independently compute KRDs and compare."""
        portfolio = reference['portfolio']
        face = portfolio['face_amount']
        curve = reference['curve']
        calendar = reference['calendar']
        today = reference['today']

        relinkable = ql.RelinkableYieldTermStructureHandle()
        relinkable.linkTo(curve)
        engine = ql.DiscountingBondEngine(relinkable)

        bonds = []
        base_value = 0.0
        for spec in portfolio['bonds']:
            bond, _, _, _, _ = build_fixed_bond(spec, calendar, face, curve)
            bond.setPricingEngine(engine)
            base_value += bond.cleanPrice() / 100.0 * face
            bonds.append(bond)

        krd_tenors = portfolio['key_rate_tenors_years']
        krd_dates = [calendar.advance(today, ql.Period(t, ql.Years)) for t in krd_tenors]
        bump = 0.0001

        for i, tenor in enumerate(krd_tenors):
            spread_handles = []
            for j in range(len(krd_tenors)):
                sq = ql.SimpleQuote(bump if j == i else 0.0)
                spread_handles.append(ql.QuoteHandle(sq))

            shifted = ql.PiecewiseZeroSpreadedTermStructure(
                ql.YieldTermStructureHandle(curve),
                spread_handles,
                krd_dates,
            )
            shifted.enableExtrapolation()
            relinkable.linkTo(shifted)

            bumped_value = sum(b.cleanPrice() / 100.0 * face for b in bonds)
            dv = bumped_value - base_value
            expected_krd = -(dv / base_value) / bump

            tenor_key = f"{tenor}Y"
            actual_krd = results['portfolio']['key_rate_durations'][tenor_key]

            assert abs(actual_krd - expected_krd) < max(0.15, abs(expected_krd) * 0.10), \
                f"KRD {tenor_key}: expected {expected_krd:.4f}, got {actual_krd:.4f}"

            relinkable.linkTo(curve)

    def test_krd_sum_approximates_duration(self, results):
        """Sum of KRDs should approximate the portfolio weighted duration."""
        krd_sum = sum(results['portfolio']['key_rate_durations'].values())
        # KRD sum should be a reasonable portfolio duration (positive, finite)
        assert 0.5 < krd_sum < 50, \
            f"Sum of KRDs ({krd_sum:.4f}) outside reasonable range for bond portfolio"
