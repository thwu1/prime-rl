#!/usr/bin/env python3
"""MSRB Rule G-33 Municipal Bond Pricing Engine."""

import json
import sys
import math
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP


# ── Date & day-count utilities ──────────────────────────────────────────────

def parse_date(s):
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def last_day_of_month(year, month):
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def add_months(d, months):
    m = d.month + months
    y = d.year
    while m > 12:
        m -= 12
        y += 1
    while m <= 0:
        m += 12
        y -= 1
    day = min(d.day, last_day_of_month(y, m))
    return date(y, m, day)


def days_30_360(d1, d2):
    """MSRB 30/360 day count with end-of-month adjustments."""
    y1, m1, dd1 = d1.year, d1.month, d1.day
    y2, m2, dd2 = d2.year, d2.month, d2.day
    if dd1 == 31:
        dd1 = 30
    if dd2 == 31 and dd1 >= 30:
        dd2 = 30
    return (y2 - y1) * 360 + (m2 - m1) * 30 + (dd2 - dd1)


# ── Precision utilities ────────────────────────────────────────────────────

def truncate(value, places):
    value = round(value, 10)
    factor = 10 ** places
    if value >= 0:
        return math.floor(value * factor) / factor
    else:
        return math.ceil(value * factor) / factor


def g33_round(value, places):
    d = Decimal(str(value))
    q = Decimal(10) ** -places
    return float(d.quantize(q, rounding=ROUND_HALF_UP))


def format_ai(raw):
    return g33_round(truncate(raw, 3), 2)


def format_price(raw):
    return truncate(raw, 3)


def format_yield(raw):
    return g33_round(truncate(raw, 4), 3)


# ── Coupon-date generation ──────────────────────────────────────────────────

def generate_coupon_dates_to(redemption, frequency, settlement):
    months_per_period = 12 // frequency
    dates = []
    current = redemption
    while current > settlement:
        dates.append(current)
        current = add_months(current, -months_per_period)
    dates.reverse()
    return dates


def find_period_bounds(settlement, redemption, frequency, dated_date=None):
    months_per_period = 12 // frequency
    coupon_dates = generate_coupon_dates_to(redemption, frequency, settlement)

    if not coupon_dates:
        prev = add_months(redemption, -months_per_period)
        return prev, redemption

    next_coupon = coupon_dates[0]
    prev_coupon = add_months(next_coupon, -months_per_period)

    if dated_date and prev_coupon < dated_date:
        prev_coupon = dated_date

    return prev_coupon, next_coupon


def count_remaining_coupons(settlement, redemption, frequency):
    months_per_period = 12 // frequency
    n = 0
    current = redemption
    while current > settlement:
        n += 1
        current = add_months(current, -months_per_period)
    return n


# ── Price formulas ──────────────────────────────────────────────────────────

def price_periodic_le1(RV, R, M, Y, A, E):
    C = (R / M) * 100.0
    DSC = E - A
    if E == 0:
        return RV
    w = DSC / E
    y = Y / M
    denom = 1.0 + w * y
    P = (RV + C) / denom - (A / E) * C
    return P


def price_periodic_gt1(RV, R, M, Y, N, A, E):
    C = (R / M) * 100.0
    if E == 0:
        return RV
    w = (E - A) / E
    y = Y / M
    base = 1.0 + y

    pv_rv = RV / (base ** (N - 1 + w))
    pv_coupons = 0.0
    for k in range(1, N + 1):
        pv_coupons += C / (base ** (k - 1 + w))

    P = pv_rv + pv_coupons - (A / E) * C
    return P


def price_at_redemption(RV, R, Y, DIR, DSM, B):
    numerator = RV + R * 100.0 * DIR / B
    denominator = 1.0 + Y * DSM / B
    return numerator / denominator


def price_discounted(RV, DR, DSM, B):
    return RV * (1.0 - DR * DSM / B)


# ── Yield formulas ──────────────────────────────────────────────────────────

def yield_periodic_le1(RV, R, M, P, A, E):
    C = (R / M) * 100.0
    DSC = E - A
    if DSC == 0 or E == 0:
        return 0.0
    numer = (RV + C) / (P + (A / E) * C) - 1.0
    Y = numer * M * E / DSC
    return Y


def yield_periodic_gt1(RV, R, M, P, N, A, E, tol=1e-12, max_iter=500):
    C = (R / M) * 100.0
    y_guess = (C + (RV - P) / N) / ((RV + P) / 2.0) * M
    if y_guess <= -1.0 / M:
        y_guess = 0.05
    if y_guess <= 0:
        y_guess = 0.01

    Y = y_guess
    for _ in range(max_iter):
        p_calc = price_periodic_gt1(RV, R, M, Y, N, A, E)
        h = max(abs(Y) * 1e-7, 1e-10)
        p_up = price_periodic_gt1(RV, R, M, Y + h, N, A, E)
        p_dn = price_periodic_gt1(RV, R, M, Y - h, N, A, E)
        dp = (p_up - p_dn) / (2.0 * h)
        if abs(dp) < 1e-20:
            break
        delta = (p_calc - P) / dp
        Y -= delta
        if abs(delta) < tol:
            break
    return Y


def yield_at_redemption(RV, R, P, DIR, DSM, B):
    if DSM == 0:
        return 0.0
    numer = (RV + R * 100.0 * DIR / B) / P - 1.0
    return numer * B / DSM


def roi_discounted(RV, P, DSM, B):
    if DSM == 0 or P == 0:
        return 0.0
    return ((RV - P) / P) * (B / DSM)


# ── Trade processing ───────────────────────────────────────────────────────

def process_periodic(spec):
    settlement = parse_date(spec["settlement_date"])
    maturity = parse_date(spec["maturity_date"])
    R = spec["coupon_rate"]
    M = spec["frequency"]
    RV = spec.get("redemption_value", 100.0)
    compute = spec["compute"]
    dated = parse_date(spec["dated_date"]) if spec.get("dated_date") else None
    call_schedule = spec.get("call_schedule") or []

    prev_cp, next_cp = find_period_bounds(settlement, maturity, M, dated)
    A = days_30_360(prev_cp, settlement)
    E = days_30_360(prev_cp, next_cp)

    C = (R / M) * 100.0
    ai_raw = (A / E) * C if E > 0 else 0.0
    ai = format_ai(ai_raw)

    result = {"accrued_interest": ai}

    def calc_price(rv_local, redemption_date, yield_val):
        n = count_remaining_coupons(settlement, redemption_date, M)
        if n <= 1:
            return price_periodic_le1(rv_local, R, M, yield_val, A, E)
        return price_periodic_gt1(rv_local, R, M, yield_val, n, A, E)

    def calc_yield(rv_local, redemption_date, price_val):
        n = count_remaining_coupons(settlement, redemption_date, M)
        if n <= 1:
            return yield_periodic_le1(rv_local, R, M, price_val, A, E)
        return yield_periodic_gt1(rv_local, R, M, price_val, n, A, E)

    if compute == "price":
        Y = spec["yield_input"]
        P_mat = calc_price(RV, maturity, Y)

        if call_schedule:
            best_price = P_mat
            best_date = spec["maturity_date"]
            best_rv = RV

            for call in call_schedule:
                cdate = parse_date(call["date"])
                cprice = call["price"]
                if cdate <= settlement:
                    continue
                p_call = calc_price(cprice, cdate, Y)
                if p_call < best_price:
                    best_price = p_call
                    best_date = call["date"]
                    best_rv = cprice

            result["dollar_price"] = format_price(best_price)
            result["yield"] = format_yield(Y)
            result["yield_to_worst"] = format_yield(Y)
            result["worst_date"] = best_date
            result["worst_rv"] = best_rv
        else:
            result["dollar_price"] = format_price(P_mat)
            result["yield"] = format_yield(Y)
            result["yield_to_worst"] = None
            result["worst_date"] = None
            result["worst_rv"] = None

    elif compute == "yield":
        P = spec["price_input"]
        Y_mat = calc_yield(RV, maturity, P)

        if call_schedule:
            best_yield = Y_mat
            best_date = spec["maturity_date"]
            best_rv = RV

            for call in call_schedule:
                cdate = parse_date(call["date"])
                cprice = call["price"]
                if cdate <= settlement:
                    continue
                y_call = calc_yield(cprice, cdate, P)
                if y_call < best_yield:
                    best_yield = y_call
                    best_date = call["date"]
                    best_rv = cprice

            result["dollar_price"] = format_price(P)
            result["yield"] = format_yield(Y_mat)
            result["yield_to_worst"] = format_yield(best_yield)
            result["worst_date"] = best_date
            result["worst_rv"] = best_rv
        else:
            result["dollar_price"] = format_price(P)
            result["yield"] = format_yield(Y_mat)
            result["yield_to_worst"] = None
            result["worst_date"] = None
            result["worst_rv"] = None

    return result


def process_at_redemption(spec):
    settlement = parse_date(spec["settlement_date"])
    maturity = parse_date(spec["maturity_date"])
    dated = parse_date(spec["dated_date"])
    R = spec["coupon_rate"]
    RV = spec.get("redemption_value", 100.0)
    compute = spec["compute"]
    B = 360

    DIR = days_30_360(dated, maturity)
    DSM = days_30_360(settlement, maturity)
    DIS = days_30_360(dated, settlement)

    ai_raw = R * DIS / B * 100.0
    ai = format_ai(ai_raw)

    result = {"accrued_interest": ai}

    if compute == "price":
        Y = spec["yield_input"]
        P = price_at_redemption(RV, R, Y, DIR, DSM, B)
        result["dollar_price"] = format_price(P)
        result["yield"] = format_yield(Y)
    elif compute == "yield":
        P = spec["price_input"]
        Y = yield_at_redemption(RV, R, P, DIR, DSM, B)
        result["dollar_price"] = format_price(P)
        result["yield"] = format_yield(Y)

    result["yield_to_worst"] = None
    result["worst_date"] = None
    result["worst_rv"] = None
    return result


def process_discounted(spec):
    settlement = parse_date(spec["settlement_date"])
    maturity = parse_date(spec["maturity_date"])
    RV = spec.get("redemption_value", 100.0)
    compute = spec["compute"]
    B = 360

    DSM = days_30_360(settlement, maturity)

    result = {"accrued_interest": 0.0}

    if compute == "price":
        DR = spec.get("discount_rate") or spec.get("yield_input") or 0.0
        P = price_discounted(RV, DR, DSM, B)
        IR = roi_discounted(RV, P, DSM, B)
        result["dollar_price"] = format_price(P)
        result["yield"] = format_yield(IR)
    elif compute == "yield":
        P = spec["price_input"]
        IR = roi_discounted(RV, P, DSM, B)
        result["dollar_price"] = format_price(P)
        result["yield"] = format_yield(IR)

    result["yield_to_worst"] = None
    result["worst_date"] = None
    result["worst_rv"] = None
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 muni_calc.py <input.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        spec = json.load(f)

    stype = spec["security_type"]
    if stype == "periodic":
        result = process_periodic(spec)
    elif stype == "at_redemption":
        result = process_at_redemption(spec)
    elif stype == "discounted":
        result = process_discounted(spec)
    else:
        print(f"Unknown security_type: {stype}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
