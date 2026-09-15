"""
Hull-White one-factor model calibration and Bermudan swaption pricing.

"""

import json
import QuantLib as ql


def load_market_data(path="/app/market_data.json"):
    with open(path) as f:
        return json.load(f)


def build_yield_curve(data):
    """Build a flat-forward yield curve from market data."""
    eval_date = ql.Date(
        int(data["evaluation_date"].split("-")[2]),
        int(data["evaluation_date"].split("-")[1]),
        int(data["evaluation_date"].split("-")[0]),
    )
    ql.Settings.instance().evaluationDate = eval_date

    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    day_count = ql.Actual365Fixed()
    settlement_days = data["settlement_days"]
    rate = data["flat_forward_rate"]

    term_structure = ql.YieldTermStructureHandle(
        ql.FlatForward(settlement_days, calendar, rate, day_count)
    )
    return eval_date, calendar, day_count, term_structure


def create_swaption_helpers(data, term_structure, calendar):
    """Create SwaptionHelper objects for calibration."""
    index = ql.Euribor1Y(term_structure)
    helpers = []

    for s in data["swaption_data"]:
        expiry = ql.Period(s["expiry_years"], ql.Years)
        tenor = ql.Period(s["tenor_years"], ql.Years)
        vol_handle = ql.QuoteHandle(ql.SimpleQuote(s["volatility"]))

        helper = ql.SwaptionHelper(
            expiry,
            tenor,
            vol_handle,
            index,
            ql.Period(1, ql.Years),  # fixed leg tenor
            ql.Thirty360(ql.Thirty360.BondBasis),
            ql.Actual360(),
            term_structure,
        )
        helpers.append(helper)

    return helpers, index


def calibrate_hull_white(term_structure, helpers):
    """Calibrate HW1F model to swaption helpers using Levenberg-Marquardt."""
    model = ql.HullWhite(term_structure)

    engine = ql.JamshidianSwaptionEngine(model)
    for h in helpers:
        h.setPricingEngine(engine)

    optimization_method = ql.LevenbergMarquardt(1e-8, 1e-8, 1e-8)
    end_criteria = ql.EndCriteria(10000, 100, 1e-6, 1e-8, 1e-8)

    model.calibrate(helpers, optimization_method, end_criteria)

    a, sigma = model.params()
    return model, a, sigma


def price_european_swaption(data, model, term_structure, calendar, index):
    """Price the 1Yx5Y European payer swaption using Jamshidian engine."""
    eval_date = ql.Settings.instance().evaluationDate
    spec = data["bermudan_spec"]
    notional = spec["notional"]
    fixed_rate = spec["fixed_rate"]

    # Exercise date: 1Y from eval_date
    exercise_date = calendar.advance(eval_date, ql.Period(1, ql.Years))
    # Swap start = exercise date
    swap_start = exercise_date
    # Swap maturity: 6Y from eval_date (co-terminal)
    swap_maturity = calendar.advance(eval_date, ql.Period(6, ql.Years))

    fixed_schedule = ql.Schedule(
        swap_start,
        swap_maturity,
        ql.Period(1, ql.Years),
        calendar,
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Forward,
        False,
    )

    float_schedule = ql.Schedule(
        swap_start,
        swap_maturity,
        ql.Period(6, ql.Months),
        calendar,
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Forward,
        False,
    )

    swap = ql.VanillaSwap(
        ql.VanillaSwap.Payer,
        notional,
        fixed_schedule,
        fixed_rate,
        ql.Thirty360(ql.Thirty360.BondBasis),
        float_schedule,
        index,
        0.0,
        ql.Actual360(),
    )

    exercise = ql.EuropeanExercise(exercise_date)
    swaption = ql.Swaption(swap, exercise)

    engine = ql.JamshidianSwaptionEngine(model)
    swaption.setPricingEngine(engine)

    return swaption.NPV()


def price_bermudan_swaption(data, model, term_structure, calendar, index):
    """Price the co-terminal Bermudan payer swaption using tree engine."""
    eval_date = ql.Settings.instance().evaluationDate
    spec = data["bermudan_spec"]
    notional = spec["notional"]
    fixed_rate = spec["fixed_rate"]

    # Swap from year 1 to year 6 (co-terminal)
    swap_start = calendar.advance(eval_date, ql.Period(1, ql.Years))
    swap_maturity = calendar.advance(eval_date, ql.Period(6, ql.Years))

    fixed_schedule = ql.Schedule(
        swap_start,
        swap_maturity,
        ql.Period(1, ql.Years),
        calendar,
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Forward,
        False,
    )

    float_schedule = ql.Schedule(
        swap_start,
        swap_maturity,
        ql.Period(6, ql.Months),
        calendar,
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Forward,
        False,
    )

    swap = ql.VanillaSwap(
        ql.VanillaSwap.Payer,
        notional,
        fixed_schedule,
        fixed_rate,
        ql.Thirty360(ql.Thirty360.BondBasis),
        float_schedule,
        index,
        0.0,
        ql.Actual360(),
    )

    # Exercise dates: years 1 through 5
    exercise_dates = []
    for y in spec["exercise_years"]:
        exercise_dates.append(calendar.advance(eval_date, ql.Period(y, ql.Years)))

    exercise = ql.BermudanExercise(exercise_dates)
    swaption = ql.Swaption(swap, exercise)

    engine = ql.TreeSwaptionEngine(model, 720)
    swaption.setPricingEngine(engine)

    return swaption.NPV()


def compute_dv01(data, model, base_bermudan_price, calendar):
    """Compute DV01 by bumping the flat forward rate +1bp and repricing."""
    a_val, sigma_val = model.params()

    # Bumped curve (+1bp)
    bumped_rate = data["flat_forward_rate"] + 0.0001
    bumped_ts = ql.YieldTermStructureHandle(
        ql.FlatForward(
            data["settlement_days"],
            calendar,
            bumped_rate,
            ql.Actual365Fixed(),
        )
    )

    # Create new model with same calibrated parameters on the bumped curve
    bumped_model = ql.HullWhite(bumped_ts, a_val, sigma_val)
    bumped_index = ql.Euribor1Y(bumped_ts)

    bumped_price = price_bermudan_swaption(
        data, bumped_model, bumped_ts, calendar, bumped_index
    )

    return bumped_price - base_bermudan_price


def main():
    data = load_market_data()

    # Step 1: Build yield curve
    eval_date, calendar, day_count, term_structure = build_yield_curve(data)

    # Step 2: Create calibration instruments
    helpers, index = create_swaption_helpers(data, term_structure, calendar)

    # Step 3: Calibrate Hull-White model
    model, a, sigma = calibrate_hull_white(term_structure, helpers)

    print(f"Calibrated parameters: a = {a:.6f}, sigma = {sigma:.6f}")
    for i, h in enumerate(helpers):
        print(
            f"  Swaption {i+1}: model_price = {h.modelValue():.4f}, "
            f"market_price = {h.marketValue():.4f}, "
            f"error = {h.modelValue() - h.marketValue():.6f}"
        )

    # Step 4: Price European swaption (1Yx5Y)
    european_price = price_european_swaption(
        data, model, term_structure, calendar, index
    )
    print(f"European 1Yx5Y payer swaption: {european_price:.4f}")

    # Step 5: Price Bermudan swaption
    bermudan_price = price_bermudan_swaption(
        data, model, term_structure, calendar, index
    )
    print(f"Bermudan co-terminal payer swaption: {bermudan_price:.4f}")

    # Step 6: Early exercise premium
    premium_pct = (bermudan_price / european_price - 1.0) * 100.0
    print(f"Bermudan premium: {premium_pct:.4f}%")

    # Step 7: DV01
    dv01 = compute_dv01(data, model, bermudan_price, calendar)
    print(f"DV01: {dv01:.4f}")

    # Write results
    results = {
        "calibrated_a": a,
        "calibrated_sigma": sigma,
        "european_swaption_price": european_price,
        "bermudan_swaption_price": bermudan_price,
        "bermudan_premium_pct": premium_pct,
        "dv01": dv01,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
