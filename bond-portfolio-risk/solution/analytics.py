#!/usr/bin/env python3
"""Bond portfolio risk analytics engine.

Bootstraps a SOFR OIS curve, prices a bond portfolio, computes spreads,
duration risk metrics, scenario P&L, and key-rate durations using QuantLib.
"""

import json
import QuantLib as ql


def parse_date(s):
    """Parse ISO date string 'YYYY-MM-DD' into a QuantLib Date."""
    y, m, d = s.split('-')
    return ql.Date(int(d), int(m), int(y))


def build_ois_curve(market):
    """Bootstrap a SOFR OIS discount curve from market data."""
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


def extract_curve_data(today, calendar, curve_dc, curve):
    """Extract zero rates and discount factors at standard tenors."""
    tenors = ["1Y", "5Y", "10Y", "20Y", "30Y"]
    zero_rates = {}
    disc_factors = {}
    for tenor in tenors:
        dt = calendar.advance(today, ql.Period(tenor))
        zr = curve.zeroRate(dt, curve_dc, ql.Continuous).rate()
        df = curve.discount(dt)
        zero_rates[tenor] = round(zr * 100, 6)
        disc_factors[tenor] = round(df, 10)
    return {"zero_rates_continuous_pct": zero_rates, "discount_factors": disc_factors}


def build_and_analyze_bonds(today, calendar, curve, curve_dc, portfolio):
    """Build bonds, compute per-bond analytics, and return fixed bond objects."""
    bond_dc = ql.Thirty360(ql.Thirty360.BondBasis)
    face = portfolio['face_amount']
    settle_days = 2

    curve_handle = ql.YieldTermStructureHandle(curve)
    relinkable = ql.RelinkableYieldTermStructureHandle()
    relinkable.linkTo(curve)
    engine = ql.DiscountingBondEngine(relinkable)

    bond_results = {}
    fixed_bonds = {}
    base_model_prices = {}
    quoted_prices = {}

    for spec in portfolio['bonds']:
        bid = spec['id']
        issue = parse_date(spec['issue_date'])
        maturity = parse_date(spec['maturity_date'])
        coupon = spec['coupon_rate_pct'] / 100.0
        qp = spec['quoted_clean_price']
        quoted_prices[bid] = qp

        schedule = ql.MakeSchedule(
            effectiveDate=issue,
            terminationDate=maturity,
            frequency=ql.Semiannual,
            calendar=calendar,
            convention=ql.Unadjusted,
            backwards=True,
        )

        # Always create a fixed-rate bond for YTM, Z-spread, duration
        fixed_bond = ql.FixedRateBond(settle_days, face, schedule, [coupon], bond_dc)
        fixed_bond.setPricingEngine(engine)
        fixed_bonds[bid] = fixed_bond
        base_model_prices[bid] = fixed_bond.cleanPrice()

        price_obj = ql.BondPrice(qp, ql.BondPrice.Clean)
        ytm = fixed_bond.bondYield(price_obj, bond_dc, ql.Compounded, ql.Semiannual)

        z_spread = ql.BondFunctions.zSpread(
            fixed_bond, price_obj, curve, bond_dc, ql.Compounded, ql.Semiannual
        )

        mod_dur = ql.BondFunctions.duration(
            fixed_bond, ytm, bond_dc, ql.Compounded, ql.Semiannual,
            ql.Duration.Modified
        )

        dv01 = mod_dur * qp / 100.0 * face * 0.0001

        result = {
            "model_clean_price": round(base_model_prices[bid], 4),
            "ytm_pct": round(ytm * 100, 6),
            "z_spread_bps": round(z_spread * 10000, 2),
            "modified_duration": round(mod_dur, 6),
            "dv01_per_million_face": round(dv01, 2),
        }

        if spec['type'] == 'callable':
            call_date = parse_date(spec['call_date'])
            call_price_val = spec['call_price']
            hw_a = spec['hull_white_a']
            hw_sigma = spec['hull_white_sigma']

            callable_bond = ql.CallableFixedRateBond(
                settle_days, face, schedule, [coupon], bond_dc,
                ql.Unadjusted, 100.0, issue,
                [ql.Callability(
                    ql.BondPrice(call_price_val, ql.BondPrice.Clean),
                    ql.Callability.Call,
                    call_date,
                )]
            )

            hw_model = ql.HullWhite(curve_handle, a=hw_a, sigma=hw_sigma)
            tree_engine = ql.TreeCallableFixedRateBondEngine(hw_model, 100)
            callable_bond.setPricingEngine(tree_engine)

            callable_model_price = callable_bond.cleanPrice()
            result["model_clean_price"] = round(callable_model_price, 4)

            oas = callable_bond.OAS(
                qp, curve_handle, bond_dc, ql.Compounded, ql.Semiannual
            )
            result["oas_bps"] = round(oas * 10000, 2)

        bond_results[bid] = result

    return bond_results, fixed_bonds, base_model_prices, quoted_prices, relinkable


def compute_scenarios(today, calendar, curve, portfolio, fixed_bonds,
                      base_model_prices, face, relinkable):
    """Compute P&L under each stress scenario."""
    base_model_value = sum(p / 100.0 * face for p in base_model_prices.values())
    scenario_results = {}

    for sname, sspec in portfolio['scenarios'].items():
        if sspec['type'] == 'parallel':
            shift = sspec['shift_bps'] / 10000.0
            shifted = ql.ZeroSpreadedTermStructure(
                ql.YieldTermStructureHandle(curve),
                ql.QuoteHandle(ql.SimpleQuote(shift)),
            )
            shifted.enableExtrapolation()
            relinkable.linkTo(shifted)

        elif sspec['type'] == 'twist':
            short_date = today
            long_date = calendar.advance(today, ql.Period(sspec['long_end_years'], ql.Years))
            short_sq = ql.SimpleQuote(sspec['short_spread_bps'] / 10000.0)
            long_sq = ql.SimpleQuote(sspec['long_spread_bps'] / 10000.0)
            shifted = ql.PiecewiseZeroSpreadedTermStructure(
                ql.YieldTermStructureHandle(curve),
                [ql.QuoteHandle(short_sq), ql.QuoteHandle(long_sq)],
                [short_date, long_date],
            )
            shifted.enableExtrapolation()
            relinkable.linkTo(shifted)

        scenario_value = sum(
            bond.cleanPrice() / 100.0 * face for bond in fixed_bonds.values()
        )
        pnl = scenario_value - base_model_value
        scenario_results[sname] = round(pnl, 2)

        relinkable.linkTo(curve)

    return scenario_results, base_model_value


def compute_key_rate_durations(today, calendar, curve, portfolio, fixed_bonds,
                               base_model_value, face, relinkable):
    """Compute key-rate durations via localized 1bp bumps."""
    krd_tenors = portfolio['key_rate_tenors_years']
    krd_dates = [calendar.advance(today, ql.Period(t, ql.Years)) for t in krd_tenors]
    bump = 0.0001  # 1bp

    krd_results = {}
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

        bumped_value = sum(
            bond.cleanPrice() / 100.0 * face for bond in fixed_bonds.values()
        )

        dv = bumped_value - base_model_value
        krd = -(dv / base_model_value) / bump
        krd_results[f"{tenor}Y"] = round(krd, 6)

        relinkable.linkTo(curve)

    return krd_results


def main():
    with open('/app/market_data.json') as f:
        market = json.load(f)
    with open('/app/portfolio.json') as f:
        portfolio = json.load(f)

    face = portfolio['face_amount']

    # Build curve
    today, calendar, curve_dc, curve = build_ois_curve(market)

    # Extract curve data
    curve_data = extract_curve_data(today, calendar, curve_dc, curve)

    # Build and analyze bonds
    bond_results, fixed_bonds, base_model_prices, quoted_prices, relinkable = \
        build_and_analyze_bonds(today, calendar, curve, curve_dc, portfolio)

    # Portfolio aggregates
    total_mv = sum(qp / 100.0 * face for qp in quoted_prices.values())
    portfolio_dv01 = sum(br["dv01_per_million_face"] for br in bond_results.values())

    # Scenarios
    scenario_results, base_model_value = compute_scenarios(
        today, calendar, curve, portfolio, fixed_bonds,
        base_model_prices, face, relinkable
    )

    # Key-rate durations
    krd_results = compute_key_rate_durations(
        today, calendar, curve, portfolio, fixed_bonds,
        base_model_value, face, relinkable
    )

    # Assemble results
    results = {
        "curve": curve_data,
        "bonds": bond_results,
        "portfolio": {
            "total_market_value": round(total_mv, 2),
            "portfolio_dv01": round(portfolio_dv01, 2),
            "scenarios": scenario_results,
            "key_rate_durations": krd_results,
        },
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
