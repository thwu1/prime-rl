#!/usr/bin/env python3

"""
Dual-curve interest rate swap pricing engine.

Bootstraps an EONIA OIS discount curve and a Euribor 6M forward curve
(with OIS discounting) from market data, prices a portfolio of vanilla
interest rate swaps, computes DV01 via parallel rate bumping, and
writes structured results to /app/results.json.
"""

import json
import QuantLib as ql


def parse_tenor(s):
    """Parse tenor string like '5Y', '6M', '1W' into QuantLib Period."""
    n = int(s[:-1])
    unit_map = {"D": ql.Days, "W": ql.Weeks, "M": ql.Months, "Y": ql.Years}
    return ql.Period(n, unit_map[s[-1]])


def build_ois_curve(mkt, eval_date, calendar, quotes_out):
    """
    Bootstrap EONIA OIS discount curve from deposits and OIS swap rates.
    All input rates use mutable SimpleQuote objects stored in quotes_out
    so we can bump them for DV01 computation.
    """
    eonia = ql.Eonia()
    helpers = []
    dep_dc = ql.Actual360()
    ts_dc = ql.Actual365Fixed()

    # Overnight deposits
    for dep in mkt["ois_curve"]["deposits"]:
        q = ql.SimpleQuote(dep["rate"])
        quotes_out.append(q)
        helpers.append(
            ql.DepositRateHelper(
                ql.QuoteHandle(q),
                ql.Period(1, ql.Days),
                dep["settlement_days"],
                calendar,
                ql.Following,
                False,
                dep_dc,
            )
        )

    # Short-term OIS swaps
    for ois in mkt["ois_curve"]["short_ois"]:
        tenor = parse_tenor(ois["tenor"])
        q = ql.SimpleQuote(ois["rate"])
        quotes_out.append(q)
        helpers.append(ql.OISRateHelper(2, tenor, ql.QuoteHandle(q), eonia))

    # Long-term OIS swaps
    for ois in mkt["ois_curve"]["long_ois"]:
        tenor = parse_tenor(ois["tenor"])
        q = ql.SimpleQuote(ois["rate"])
        quotes_out.append(q)
        helpers.append(ql.OISRateHelper(2, tenor, ql.QuoteHandle(q), eonia))

    curve = ql.PiecewiseFlatForward(eval_date, helpers, ts_dc)
    curve.enableExtrapolation()
    return curve


def build_euribor_curve(mkt, settlement_date, calendar, disc_handle, quotes_out):
    """
    Bootstrap Euribor 6M forward curve from deposit, FRAs, and swap rates.
    Swap rate helpers use the OIS curve (disc_handle) for discounting.
    """
    euribor6m = ql.Euribor6M()
    helpers = []
    dep_dc = ql.Actual360()
    ts_dc = ql.Actual365Fixed()
    sw_dc = ql.Thirty360(ql.Thirty360.European)

    # 6M deposit
    dep = mkt["euribor6m_curve"]["deposit"]
    q = ql.SimpleQuote(dep["rate"])
    quotes_out.append(q)
    helpers.append(
        ql.DepositRateHelper(
            ql.QuoteHandle(q),
            ql.Period(6, ql.Months),
            dep["settlement_days"],
            calendar,
            ql.Following,
            False,
            dep_dc,
        )
    )

    # FRAs
    for fra in mkt["euribor6m_curve"]["fras"]:
        q = ql.SimpleQuote(fra["rate"])
        quotes_out.append(q)
        helpers.append(
            ql.FraRateHelper(
                ql.QuoteHandle(q), fra["months_to_start"], euribor6m
            )
        )

    # Swaps (with OIS discounting)
    for sw in mkt["euribor6m_curve"]["swaps"]:
        tenor = parse_tenor(sw["tenor"])
        q = ql.SimpleQuote(sw["rate"])
        quotes_out.append(q)
        helpers.append(
            ql.SwapRateHelper(
                ql.QuoteHandle(q),
                tenor,
                calendar,
                ql.Annual,
                ql.Unadjusted,
                sw_dc,
                euribor6m,
                ql.QuoteHandle(),
                ql.Period(0, ql.Days),
                disc_handle,
            )
        )

    curve = ql.PiecewiseFlatForward(settlement_date, helpers, ts_dc)
    curve.enableExtrapolation()
    return curve


def create_swap(spec, settlement_date, calendar, index):
    """Create a VanillaSwap from a portfolio specification."""
    swap_type = ql.Swap.Payer if spec["type"] == "payer" else ql.Swap.Receiver
    notional = spec["notional"]
    fixed_rate = spec["fixed_rate"]
    mat_tenor = parse_tenor(spec["maturity_tenor"])

    if spec["start"] == "spot":
        start = settlement_date
    elif spec["start"] == "1Y_forward":
        start = calendar.advance(settlement_date, 1, ql.Years)
    else:
        raise ValueError(f"Unknown start type: {spec['start']}")

    end = calendar.advance(start, mat_tenor)

    fixed_sched = ql.Schedule(
        start, end,
        ql.Period(ql.Annual),
        calendar,
        ql.Unadjusted,
        ql.Unadjusted,
        ql.DateGeneration.Forward,
        False,
    )
    float_sched = ql.Schedule(
        start, end,
        ql.Period(ql.Semiannual),
        calendar,
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Forward,
        False,
    )

    return ql.VanillaSwap(
        swap_type,
        notional,
        fixed_sched,
        fixed_rate,
        ql.Thirty360(ql.Thirty360.European),
        float_sched,
        index,
        0.0,
        ql.Actual360(),
    )


def format_date(d):
    """Format QuantLib Date as YYYY-MM-DD."""
    return f"{d.year()}-{int(d.month()):02d}-{d.dayOfMonth():02d}"


def main():
    # Load data
    with open("/app/market_data.json") as f:
        mkt = json.load(f)
    with open("/app/portfolio.json") as f:
        portfolio = json.load(f)

    # Set evaluation date
    y, m, d = map(int, mkt["evaluation_date"].split("-"))
    eval_date = ql.Date(d, m, y)
    ql.Settings.instance().evaluationDate = eval_date

    calendar = ql.TARGET()
    settlement = calendar.advance(eval_date, 2, ql.Days)

    # Collect all mutable quotes for DV01 bumping
    all_quotes = []

    # Build OIS discount curve
    ois_curve = build_ois_curve(mkt, eval_date, calendar, all_quotes)
    disc_handle = ql.RelinkableYieldTermStructureHandle()
    disc_handle.linkTo(ois_curve)

    # Build Euribor 6M forward curve (uses OIS for discounting)
    eur_curve = build_euribor_curve(
        mkt, settlement, calendar, disc_handle, all_quotes
    )
    fwd_handle = ql.RelinkableYieldTermStructureHandle()
    fwd_handle.linkTo(eur_curve)

    # Pricing engine and index
    engine = ql.DiscountingSwapEngine(disc_handle)
    index = ql.Euribor6M(fwd_handle)

    # Create swaps
    swaps = []
    for spec in portfolio["swaps"]:
        swap = create_swap(spec, settlement, calendar, index)
        swap.setPricingEngine(engine)
        swaps.append((spec["id"], swap))

    # --- Base pricing ---
    base_results = []
    for sid, swap in swaps:
        base_results.append(
            {
                "id": sid,
                "npv": swap.NPV(),
                "fair_rate": swap.fairRate(),
                "fair_spread": swap.fairSpread(),
            }
        )

    # --- DV01: bump all quotes by +1bp ---
    bump = 0.0001  # 1 basis point
    original_values = [q.value() for q in all_quotes]

    for q in all_quotes:
        q.setValue(q.value() + bump)

    bumped_npvs = {}
    for sid, swap in swaps:
        bumped_npvs[sid] = swap.NPV()

    # Restore original values
    for q, orig in zip(all_quotes, original_values):
        q.setValue(orig)

    # Compute DV01 = bumped - base
    for br in base_results:
        br["dv01"] = bumped_npvs[br["id"]] - br["npv"]

    # --- Portfolio aggregation ---
    portfolio_npv = sum(r["npv"] for r in base_results)
    portfolio_dv01 = sum(r["dv01"] for r in base_results)

    # --- OIS discount factors ---
    ois_dfs = {}
    for tenor_str in ["1Y", "5Y", "10Y", "30Y"]:
        tenor = parse_tenor(tenor_str)
        dt = calendar.advance(settlement, tenor)
        ois_dfs[tenor_str] = ois_curve.discount(dt)

    # --- Write results ---
    results = {
        "evaluation_date": mkt["evaluation_date"],
        "settlement_date": format_date(settlement),
        "swaps": base_results,
        "portfolio_npv": portfolio_npv,
        "portfolio_dv01": portfolio_dv01,
        "ois_discount_factors": ois_dfs,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
