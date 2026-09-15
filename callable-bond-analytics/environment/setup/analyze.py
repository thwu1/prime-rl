#!/usr/bin/env python3
"""
Callable bond analytics pipeline.
Reads /app/market_data.json, computes spread and risk analytics,
writes /app/results.json.
"""

import json
import QuantLib as ql

BPS = 1e-4


def make_date(triple):
    return ql.Date(triple[0], triple[1], triple[2])


def build_ois_curve(ois_rates, calendar):
    index = ql.Sofr()
    helpers = []
    for tenor_str, rate_pct in ois_rates.items():
        q = ql.SimpleQuote(rate_pct / 100.0)
        helpers.append(
            ql.OISRateHelper(
                2, ql.Period(tenor_str), ql.QuoteHandle(q), index
            )
        )
    curve = ql.PiecewiseLogCubicDiscount(0, calendar, helpers, ql.Actual360())
    curve.enableExtrapolation()
    return curve


def main():
    with open("/app/market_data.json") as f:
        data = json.load(f)

    today = make_date(data["evaluation_date"])
    ql.Settings.instance().evaluationDate = today

    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    bond_dc = ql.Thirty360(ql.Thirty360.BondBasis)
    comp = ql.SimpleThenCompounded
    freq = ql.Annual

    # ---- Build SOFR OIS curve ----
    sofr_curve = build_ois_curve(data["ois_rates"], calendar)
    sofr_handle = ql.YieldTermStructureHandle(sofr_curve)

    # ---- Construct the fixed-rate bond ----
    bd = data["bond"]
    issue = make_date(bd["issue_date"])
    maturity = make_date(bd["maturity_date"])
    first_call = make_date(bd["first_call_date"])
    coupon = bd["coupon_rate"] / 100.0
    face = bd["face_amount"]
    settle = bd["settlement_days"]
    cprice = bd["quoted_clean_price"]

    schedule = ql.MakeSchedule(
        effectiveDate=issue,
        terminationDate=maturity,
        frequency=ql.Annual,
        calendar=calendar,
        convention=ql.Following,
        backwards=True,
    )

    bond = ql.FixedRateBond(settle, face, schedule, [coupon], bond_dc)

    # ---- Bond yield from quoted clean price ----
    bond_yield = bond.bondYield(cprice, bond_dc, ql.Compounded, freq)

    # ---- I-spread: yield minus risk-free rate at maturity ----
    tenor_data = []
    for ts in data["ois_rates"]:
        dt = today + ql.Period(ts)
        t = bond_dc.yearFraction(today, dt)
        r = sofr_curve.zeroRate(dt, bond_dc, comp, freq).rate()
        tenor_data.append((t, r))
    tenor_data.sort()
    xs = [d[0] for d in tenor_data]
    ys = [d[1] for d in tenor_data]
    interp = ql.LinearInterpolation(xs, ys)
    T_mat = bond_dc.yearFraction(today, maturity)
    R_interp = interp(T_mat)
    i_spread = bond_yield - R_interp

    # ---- Z-spread ----
    z_spread = ql.BondFunctions.zSpread(
        bond, cprice, sofr_curve, ql.Actual365Fixed(), comp, freq
    )

    # ---- OAS via callable bond + Hull-White ----
    call_sched = []
    for i in range(len(schedule)):
        dt = schedule[i]
        if dt > first_call and dt < maturity:
            call_sched.append(
                ql.Callability(
                    ql.BondPrice(100.0, ql.BondPrice.Clean),
                    ql.Callability.Call,
                    dt,
                )
            )

    callable_bond = ql.CallableFixedRateBond(
        settle, face, schedule, [coupon], bond_dc,
        ql.Following, 100.0, issue, call_sched,
    )

    hw = data["hull_white"]
    callable_bond.setPricingEngine(
        ql.TreeCallableFixedRateBondEngine(
            ql.HullWhite(sofr_handle, a=hw["a"], sigma=hw["sigma"]),
            hw["tree_steps"],
        )
    )

    oas = callable_bond.OAS(cprice, sofr_handle, bond_dc, comp, freq)
    option_cost = z_spread - oas

    # ---- Key-rate durations ----
    bond.setPricingEngine(ql.DiscountingBondEngine(sofr_handle))
    base_price = bond.cleanPrice()

    krd_tenors = data["krd_tenors"]
    bump = data["krd_bump_bps"] * BPS

    tenor_info = [
        (ts, calendar.advance(today, ql.Period(ts))) for ts in krd_tenors
    ]

    krds = {}
    for k, (ts, _) in enumerate(tenor_info):
        spread_dates = [today]
        spread_vals = [
            ql.QuoteHandle(ql.SimpleQuote(bump if k == 0 else 0.0))
        ]

        for j, (_, dt_j) in enumerate(tenor_info):
            spread_dates.append(dt_j)
            spread_vals.append(
                ql.QuoteHandle(ql.SimpleQuote(bump if j == k else 0.0))
            )

        spread_dates.append(today + ql.Period("60Y"))
        spread_vals.append(
            ql.QuoteHandle(
                ql.SimpleQuote(bump if k == len(tenor_info) - 1 else 0.0)
            )
        )

        bumped = ql.PiecewiseZeroSpreadedTermStructure(
            sofr_handle, spread_vals, spread_dates
        )
        bumped.enableExtrapolation()

        bond.setPricingEngine(
            ql.DiscountingBondEngine(ql.YieldTermStructureHandle(bumped))
        )
        bp = bond.cleanPrice()
        krds[ts] = -(bp - base_price) / (base_price * bump)

    # ---- Stress P&L ----
    stressed_curve = build_ois_curve(data["stress_ois_rates"], calendar)
    stressed_handle = ql.YieldTermStructureHandle(stressed_curve)

    zq = ql.SimpleQuote(z_spread)
    base_sc = ql.ZeroSpreadedTermStructure(
        sofr_handle, ql.QuoteHandle(zq), comp, freq
    )
    stressed_sc = ql.ZeroSpreadedTermStructure(
        stressed_handle, ql.QuoteHandle(zq), comp, freq
    )

    bond.setPricingEngine(
        ql.DiscountingBondEngine(ql.YieldTermStructureHandle(base_sc))
    )
    p_base = bond.cleanPrice()

    bond.setPricingEngine(
        ql.DiscountingBondEngine(ql.YieldTermStructureHandle(stressed_sc))
    )
    p_stressed = bond.cleanPrice()

    stress_pnl = (p_stressed - p_base) * face / 100.0

    # ---- Output ----
    results = {
        "bond_yield": round(bond_yield, 10),
        "i_spread_bps": round(i_spread / BPS, 6),
        "z_spread_bps": round(z_spread / BPS, 6),
        "oas_bps": round(oas / BPS, 6),
        "option_cost_bps": round(option_cost / BPS, 6),
        "key_rate_durations": {t: round(v, 6) for t, v in krds.items()},
        "stress_pnl": round(stress_pnl, 2),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Analytics written to /app/results.json")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
