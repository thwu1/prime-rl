
import pytest
import json
import QuantLib as ql


BPS = 1e-4


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def _make_date(triple):
    return ql.Date(triple[0], triple[1], triple[2])


def _build_ois_curve(ois_rates, calendar):
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


@pytest.fixture(scope="module")
def market_data():
    return _load_json("/app/market_data.json")


@pytest.fixture(scope="module")
def results():
    return _load_json("/app/results.json")


@pytest.fixture(scope="module")
def reference(market_data):
    """Independently compute all expected analytics."""
    data = market_data
    today = _make_date(data["evaluation_date"])
    ql.Settings.instance().evaluationDate = today

    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    bond_dc = ql.Thirty360(ql.Thirty360.BondBasis)
    comp = ql.SimpleThenCompounded
    freq = ql.Annual

    # ----- SOFR curve -----
    sofr_curve = _build_ois_curve(data["ois_rates"], calendar)
    sofr_handle = ql.YieldTermStructureHandle(sofr_curve)

    # ----- Bond -----
    bd = data["bond"]
    issue = _make_date(bd["issue_date"])
    maturity = _make_date(bd["maturity_date"])
    first_call = _make_date(bd["first_call_date"])
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

    # ----- Bond yield -----
    bond_yield = bond.bondYield(cprice, bond_dc, comp, freq)

    # ----- I-spread -----
    ois = data["ois_rates"]
    tenor_data = []
    for ts, rp in ois.items():
        t = bond_dc.yearFraction(today, today + ql.Period(ts))
        tenor_data.append((t, rp / 100.0))
    tenor_data.sort()
    xs = [d[0] for d in tenor_data]
    ys = [d[1] for d in tenor_data]
    interp = ql.LinearInterpolation(xs, ys)
    T_mat = bond_dc.yearFraction(today, maturity)
    R_interp = interp(T_mat)
    i_spread = bond_yield - R_interp

    # ----- Z-spread -----
    z_spread = ql.BondFunctions.zSpread(
        bond, cprice, sofr_curve, bond_dc, comp, freq
    )

    # ----- OAS -----
    call_sched = []
    for i in range(len(schedule)):
        dt = schedule[i]
        if dt >= first_call and dt < maturity:
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

    # ----- Effective duration and convexity -----
    shift = data["parallel_shift_bps"] * BPS

    # Base callable model price
    p_cb_base = callable_bond.cleanPrice()

    # Up-shifted curve
    up_q = ql.SimpleQuote(shift)
    up_curve = ql.ZeroSpreadedTermStructure(
        sofr_handle, ql.QuoteHandle(up_q)
    )
    up_curve.enableExtrapolation()
    up_handle = ql.YieldTermStructureHandle(up_curve)

    callable_bond.setPricingEngine(
        ql.TreeCallableFixedRateBondEngine(
            ql.HullWhite(up_handle, a=hw["a"], sigma=hw["sigma"]),
            hw["tree_steps"],
        )
    )
    p_cb_up = callable_bond.cleanPrice()

    # Down-shifted curve
    down_q = ql.SimpleQuote(-shift)
    down_curve = ql.ZeroSpreadedTermStructure(
        sofr_handle, ql.QuoteHandle(down_q)
    )
    down_curve.enableExtrapolation()
    down_handle = ql.YieldTermStructureHandle(down_curve)

    callable_bond.setPricingEngine(
        ql.TreeCallableFixedRateBondEngine(
            ql.HullWhite(down_handle, a=hw["a"], sigma=hw["sigma"]),
            hw["tree_steps"],
        )
    )
    p_cb_down = callable_bond.cleanPrice()

    eff_dur = (p_cb_down - p_cb_up) / (2.0 * p_cb_base * shift)
    eff_conv = (p_cb_down + p_cb_up - 2.0 * p_cb_base) / (
        p_cb_base * shift * shift
    )

    # ----- Key-rate durations -----
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

    # ----- Stress P&L -----
    stressed_curve = _build_ois_curve(data["stress_ois_rates"], calendar)
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

    return {
        "bond_yield": bond_yield,
        "i_spread_bps": i_spread / BPS,
        "z_spread_bps": z_spread / BPS,
        "oas_bps": oas / BPS,
        "option_cost_bps": option_cost / BPS,
        "effective_duration": eff_dur,
        "effective_convexity": eff_conv,
        "key_rate_durations": krds,
        "stress_pnl": stress_pnl,
    }


# ---- Structure tests ----

def test_results_file_exists(results):
    assert isinstance(results, dict), "results.json must contain a JSON object"


def test_required_keys(results):
    required = [
        "bond_yield", "i_spread_bps", "z_spread_bps",
        "oas_bps", "option_cost_bps", "effective_duration",
        "effective_convexity", "key_rate_durations", "stress_pnl",
    ]
    for key in required:
        assert key in results, f"Missing required key: {key}"


def test_krd_keys(results):
    krd = results["key_rate_durations"]
    for tenor in ["2Y", "5Y", "10Y", "20Y", "30Y"]:
        assert tenor in krd, f"Missing KRD tenor: {tenor}"


# ---- Value accuracy tests ----

def test_bond_yield(results, reference):
    assert abs(results["bond_yield"] - reference["bond_yield"]) < 1e-5, (
        f"bond_yield: got {results['bond_yield']}, "
        f"expected {reference['bond_yield']}"
    )


def test_i_spread(results, reference):
    assert abs(results["i_spread_bps"] - reference["i_spread_bps"]) < 1.0, (
        f"i_spread_bps: got {results['i_spread_bps']}, "
        f"expected {reference['i_spread_bps']}"
    )


def test_z_spread(results, reference):
    assert abs(results["z_spread_bps"] - reference["z_spread_bps"]) < 1.0, (
        f"z_spread_bps: got {results['z_spread_bps']}, "
        f"expected {reference['z_spread_bps']}"
    )


def test_oas(results, reference):
    assert abs(results["oas_bps"] - reference["oas_bps"]) < 3.0, (
        f"oas_bps: got {results['oas_bps']}, "
        f"expected {reference['oas_bps']}"
    )


def test_option_cost(results, reference):
    assert abs(results["option_cost_bps"] - reference["option_cost_bps"]) < 3.0, (
        f"option_cost_bps: got {results['option_cost_bps']}, "
        f"expected {reference['option_cost_bps']}"
    )


def test_effective_duration(results, reference):
    assert abs(
        results["effective_duration"] - reference["effective_duration"]
    ) < 0.5, (
        f"effective_duration: got {results['effective_duration']}, "
        f"expected {reference['effective_duration']}"
    )


def test_effective_convexity(results, reference):
    assert abs(
        results["effective_convexity"] - reference["effective_convexity"]
    ) < 30.0, (
        f"effective_convexity: got {results['effective_convexity']}, "
        f"expected {reference['effective_convexity']}"
    )


def test_krd_2y(results, reference):
    assert abs(
        results["key_rate_durations"]["2Y"]
        - reference["key_rate_durations"]["2Y"]
    ) < 0.1, "KRD 2Y mismatch"


def test_krd_5y(results, reference):
    assert abs(
        results["key_rate_durations"]["5Y"]
        - reference["key_rate_durations"]["5Y"]
    ) < 0.1, "KRD 5Y mismatch"


def test_krd_10y(results, reference):
    assert abs(
        results["key_rate_durations"]["10Y"]
        - reference["key_rate_durations"]["10Y"]
    ) < 0.2, "KRD 10Y mismatch"


def test_krd_20y(results, reference):
    assert abs(
        results["key_rate_durations"]["20Y"]
        - reference["key_rate_durations"]["20Y"]
    ) < 0.3, "KRD 20Y mismatch"


def test_krd_30y(results, reference):
    assert abs(
        results["key_rate_durations"]["30Y"]
        - reference["key_rate_durations"]["30Y"]
    ) < 0.3, "KRD 30Y mismatch"


def test_stress_pnl(results, reference):
    assert abs(results["stress_pnl"] - reference["stress_pnl"]) < 1000, (
        f"stress_pnl: got {results['stress_pnl']}, "
        f"expected {reference['stress_pnl']}"
    )


# ---- Consistency / sanity tests ----

def test_z_spread_greater_than_oas(results):
    assert results["z_spread_bps"] > results["oas_bps"], (
        "Z-spread must exceed OAS for a callable bond"
    )


def test_option_cost_positive(results):
    assert results["option_cost_bps"] > 0, (
        "Option cost must be positive for a callable bond"
    )


def test_stress_pnl_negative(results):
    assert results["stress_pnl"] < 0, (
        "Stress P&L must be negative when rates increase"
    )


def test_krd_all_positive(results):
    for tenor, val in results["key_rate_durations"].items():
        assert val > 0, f"KRD at {tenor} must be positive for a long fixed-rate bond"


def test_krd_sum_reasonable(results):
    krd_sum = sum(results["key_rate_durations"].values())
    assert 5.0 < krd_sum < 30.0, (
        f"Sum of KRDs ({krd_sum}) outside plausible modified-duration range"
    )


def test_bond_yield_reasonable(results):
    assert 0.02 < results["bond_yield"] < 0.06, (
        f"Bond yield {results['bond_yield']} outside plausible range"
    )


def test_i_spread_reasonable(results):
    assert 0.0 < results["i_spread_bps"] < 200.0, (
        f"I-spread {results['i_spread_bps']} bps outside plausible range"
    )


def test_effective_duration_positive(results):
    assert results["effective_duration"] > 0, (
        "Effective duration must be positive"
    )


def test_effective_duration_less_than_krd_sum(results):
    """Callable bond effective duration should be less than bullet modified
    duration (approximated by sum of KRDs)."""
    krd_sum = sum(results["key_rate_durations"].values())
    assert results["effective_duration"] < krd_sum, (
        "Effective duration of callable bond must be less than "
        "modified duration of bullet equivalent"
    )


def test_effective_convexity_reasonable(results):
    assert -500 < results["effective_convexity"] < 500, (
        f"Effective convexity {results['effective_convexity']} "
        f"outside reasonable range"
    )
